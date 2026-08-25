"""Read Codex account quota and local token usage without handling auth secrets.

The installed Codex app-server supplies the signed-in account snapshot, rolling
rate limits, and account token totals. Local per-computer tokens are derived
from Codex's own token-count events under the returned ``codexHome`` directory.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
from queue import Empty, Queue
import re
import shutil
import subprocess
import sys
from threading import RLock, Thread
from time import monotonic
from typing import Any, Callable, Iterable, TextIO
import uuid


class CodexUsageError(RuntimeError):
    """A safe, user-facing Codex usage lookup failure."""


@dataclass(frozen=True, slots=True)
class CodexAccount:
    key: str
    label: str
    plan_type: str


@dataclass(frozen=True, slots=True)
class CodexRateWindow:
    used_percent: float
    window_duration_minutes: int | None
    resets_at: datetime | None

    @property
    def remaining_percent(self) -> float:
        return max(0.0, 100.0 - self.used_percent)

    @property
    def starts_at(self) -> datetime | None:
        if self.resets_at is None or self.window_duration_minutes is None:
            return None
        return self.resets_at - timedelta(minutes=self.window_duration_minutes)


@dataclass(frozen=True, slots=True)
class CodexRateLimit:
    limit_id: str
    limit_name: str | None
    plan_type: str | None
    primary: CodexRateWindow | None
    secondary: CodexRateWindow | None
    credit_balance: str | None
    has_credits: bool
    unlimited_credits: bool


@dataclass(frozen=True, slots=True)
class CodexTokenUsage:
    input_tokens: int = 0
    cached_input_tokens: int = 0
    cache_write_input_tokens: int = 0
    output_tokens: int = 0
    reasoning_output_tokens: int = 0
    total_tokens: int = 0
    requests: int = 0

    def __add__(self, other: "CodexTokenUsage") -> "CodexTokenUsage":
        return CodexTokenUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            cached_input_tokens=self.cached_input_tokens + other.cached_input_tokens,
            cache_write_input_tokens=self.cache_write_input_tokens + other.cache_write_input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            reasoning_output_tokens=self.reasoning_output_tokens + other.reasoning_output_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
            requests=self.requests + other.requests,
        )


@dataclass(frozen=True, slots=True)
class CodexModelUsage:
    """One model's local usage within a quota window."""

    model: str
    uses: int = 0
    total_tokens: int = 0
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    weighted_credits: float | None = None


@dataclass(frozen=True, slots=True)
class LocalCodexUsage:
    tokens: CodexTokenUsage = CodexTokenUsage()
    model_usage: tuple[CodexModelUsage, ...] = ()
    weighted_credits: float | None = None
    weighted_complete: bool = True
    pending_tokens: CodexTokenUsage = CodexTokenUsage()
    anomaly_tokens: CodexTokenUsage = CodexTokenUsage()
    duplicate_events: int = 0
    fast_uses: int = 0
    standard_uses: int = 0
    observed_start_used_percent: float | None = None
    observed_end_used_percent: float | None = None
    files_scanned: int = 0
    files_skipped: int = 0
    pending_event_ids: tuple[str, ...] = ()

    @property
    def scan_status(self) -> str:
        if self.tokens.requests > 0 or self.tokens.total_tokens > 0:
            return "matched"
        if self.files_scanned > 0:
            return "no_matching_events"
        if self.files_skipped > 0:
            return "unreadable_files"
        return "no_session_files"

    @property
    def observed_quota_change(self) -> float | None:
        if self.observed_start_used_percent is None or self.observed_end_used_percent is None:
            return None
        return max(0.0, self.observed_end_used_percent - self.observed_start_used_percent)


@dataclass(frozen=True, slots=True)
class AccountTokenSummary:
    lifetime_tokens: int | None = None
    peak_daily_tokens: int | None = None
    current_streak_days: int | None = None
    longest_streak_days: int | None = None
    longest_running_turn_seconds: int | None = None


@dataclass(frozen=True, slots=True)
class DailyTokenUsage:
    start_date: date
    tokens: int


@dataclass(frozen=True, slots=True)
class CodexUsageReport:
    account: CodexAccount
    rate_limits: tuple[CodexRateLimit, ...]
    primary_limit: CodexRateLimit
    account_tokens: AccountTokenSummary
    daily_usage: tuple[DailyTokenUsage, ...]
    local_usage: LocalCodexUsage
    fetched_at: datetime
    codex_home: Path


@dataclass(frozen=True, slots=True)
class CodexAccountInterval:
    """A period during which PetNest directly observed one signed-in account."""

    account_key: str
    started_at: datetime
    last_seen_at: datetime
    ended_at: datetime | None = None
    observer_id: str = ""


class CodexAccountObservationStore:
    """Persist non-secret account observation intervals for local attribution."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = RLock()
        self._observer_id = uuid.uuid4().hex

    def load(self) -> tuple[CodexAccountInterval, ...]:
        with self._lock:
            if not self.path.exists():
                return ()
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                return ()
        values = raw.get("intervals") if isinstance(raw, dict) else None
        if not isinstance(values, list):
            return ()
        intervals: list[CodexAccountInterval] = []
        for value in values[-500:]:
            if not isinstance(value, dict):
                continue
            account_key = str(value.get("account_key") or "")
            started_at = _timestamp(value.get("started_at"))
            last_seen_at = _timestamp(value.get("last_seen_at"))
            ended_at = _timestamp(value.get("ended_at")) if value.get("ended_at") else None
            observer_id = str(value.get("observer_id") or "")
            if (
                not re.fullmatch(r"[0-9a-f]{24}", account_key)
                or started_at is None
                or last_seen_at is None
                or last_seen_at < started_at
                or (ended_at is not None and ended_at < started_at)
                or len(observer_id) > 64
            ):
                continue
            intervals.append(
                CodexAccountInterval(
                    account_key=account_key,
                    started_at=started_at,
                    last_seen_at=last_seen_at,
                    ended_at=ended_at,
                    observer_id=observer_id,
                )
            )
        intervals.sort(key=lambda item: item.started_at)
        return tuple(intervals)

    def observe(
        self,
        account_key: str | None,
        observed_at: datetime,
        *,
        inferred_started_at: datetime | None = None,
    ) -> tuple[CodexAccountInterval, ...]:
        with self._lock:
            observed = _aware_utc(observed_at)
            inferred = _aware_utc(inferred_started_at) if inferred_started_at is not None else None
            intervals = list(self.load())
            open_index = next(
                (
                    index
                    for index in range(len(intervals) - 1, -1, -1)
                    if intervals[index].ended_at is None
                    and intervals[index].observer_id == self._observer_id
                ),
                None,
            )
            current = intervals[open_index] if open_index is not None else None
            if account_key is not None and not re.fullmatch(r"[0-9a-f]{24}", account_key):
                raise ValueError("Codex 账号匿名键无效")
            if current is not None and current.account_key == account_key:
                intervals[open_index] = replace(
                    current,
                    last_seen_at=max(current.last_seen_at, observed),
                )
            else:
                if current is not None and open_index is not None:
                    intervals[open_index] = replace(current, ended_at=current.last_seen_at)
                if account_key is not None:
                    start = observed
                    if not intervals and inferred is not None:
                        start = min(observed, inferred)
                    intervals.append(
                        CodexAccountInterval(
                            account_key=account_key,
                            started_at=start,
                            last_seen_at=observed,
                            observer_id=self._observer_id,
                        )
                    )
            self._save(intervals)
            return tuple(intervals)

    def _save(self, intervals: list[CodexAccountInterval]) -> None:
        payload = {
            "schema_version": 1,
            "intervals": [
                {
                    "account_key": item.account_key,
                    "started_at": item.started_at.isoformat(),
                    "last_seen_at": item.last_seen_at.isoformat(),
                    "ended_at": item.ended_at.isoformat() if item.ended_at is not None else None,
                    "observer_id": item.observer_id,
                }
                for item in intervals[-500:]
            ],
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            temporary.replace(self.path)
        finally:
            if temporary.exists():
                temporary.unlink()


class CodexManualAttributionStore:
    """Persist explicit user claims for otherwise-unattributable token events."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = RLock()

    def claimed_event_ids(self, account_key: str, reset_epoch: int) -> frozenset[str]:
        with self._lock:
            raw = self._load()
        key = f"{account_key}:{reset_epoch}"
        values = raw.get("claims", {}).get(key, []) if isinstance(raw.get("claims"), dict) else []
        if not isinstance(values, list):
            return frozenset()
        return frozenset(value for value in values if isinstance(value, str) and value)

    def claim(self, account_key: str, reset_epoch: int, event_ids: Iterable[str]) -> int:
        if re.fullmatch(r"[0-9a-f]{24}", account_key) is None or reset_epoch <= 0:
            raise ValueError("补登账号或额度周期无效")
        additions = {str(value) for value in event_ids if str(value)}
        if not additions:
            return 0
        with self._lock:
            raw = self._load()
            claims = raw.get("claims")
            if not isinstance(claims, dict):
                claims = {}
            key = f"{account_key}:{reset_epoch}"
            existing = {value for value in claims.get(key, []) if isinstance(value, str)}
            before = len(existing)
            existing.update(additions)
            claims[key] = sorted(existing)
            payload = {"schema_version": 1, "claims": claims}
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(self.path.suffix + ".tmp")
            try:
                temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                temporary.replace(self.path)
            finally:
                if temporary.exists():
                    temporary.unlink()
            return len(existing) - before

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return {}
        return raw if isinstance(raw, dict) else {}

RpcTransport = Callable[
    [Path, list[dict[str, Any]], frozenset[int], float],
    dict[int, dict[str, Any]],
]


class CodexUsageClient:
    """Query the installed Codex app-server and correlate its local logs."""

    def __init__(
        self,
        executable: Path | None = None,
        *,
        timeout: float = 20.0,
        transport: RpcTransport | None = None,
        observation_store: CodexAccountObservationStore | None = None,
        manual_attribution_store: CodexManualAttributionStore | None = None,
    ) -> None:
        self._executables = (executable,) if executable is not None else discover_codex_executables()
        self.executable = self._executables[0]
        self.timeout = timeout
        self._transport = transport or _stdio_rpc_transport
        self._observation_store = observation_store
        self._manual_attribution_store = manual_attribution_store

    def observe_account(self) -> CodexAccount | None:
        """Record the current login without fetching quota or scanning logs."""
        responses = self._transport(
            self.executable,
            [
                {
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "clientInfo": {"name": "petnest", "version": "0.1.0"},
                        "capabilities": {"experimentalApi": True},
                    },
                },
                {"method": "initialized"},
                {
                    "id": 2,
                    "method": "account/read",
                    "params": {"refreshToken": False},
                },
            ],
            frozenset({1, 2}),
            self.timeout,
        )
        observed_at = datetime.now(UTC)
        try:
            account = _parse_account(responses[2], {})
        except CodexUsageError:
            if self._observation_store is not None:
                self._observation_store.observe(None, observed_at)
            return None
        if self._observation_store is not None:
            raw_home = responses[1].get("codexHome")
            codex_home = Path(raw_home).expanduser() if isinstance(raw_home, str) else Path()
            self._observation_store.observe(
                account.key,
                observed_at,
                inferred_started_at=_auth_modified_at(codex_home, observed_at),
            )
        return account

    def fetch_codex_home(self) -> Path:
        """只初始化 app-server，读取当前实际生效的 codexHome。"""
        failures: list[str] = []
        for executable in self._executables:
            try:
                responses = self._transport(
                    executable,
                    [
                        {
                            "id": 1,
                            "method": "initialize",
                            "params": {
                                "clientInfo": {"name": "petnest", "version": "0.1.0"},
                                "capabilities": {"experimentalApi": True},
                            },
                        },
                        {"method": "initialized"},
                    ],
                    frozenset({1}),
                    min(self.timeout, 5.0),
                )
                raw_home = responses[1].get("codexHome")
                if isinstance(raw_home, str) and raw_home.strip():
                    self.executable = executable
                    return Path(raw_home).expanduser().resolve()
                failures.append("app-server 未返回 codexHome")
            except (CodexUsageError, OSError, ValueError) as error:
                failures.append(str(error))
        raise CodexUsageError(failures[-1] if failures else "无法读取 codexHome")

    def fetch_report(self) -> CodexUsageReport:
        failures: list[tuple[Path, str]] = []
        candidates = (self.executable,) + tuple(
            candidate for candidate in self._executables if candidate != self.executable
        )
        for executable in candidates:
            try:
                report = self._fetch_report(executable)
            except CodexUsageError as error:
                failures.append((executable, str(error)))
                continue
            self.executable = executable
            return report
        if len(failures) == 1:
            raise CodexUsageError(failures[0][1])
        attempted = "、".join(path.name for path, _message in failures)
        detail = failures[-1][1] if failures else "未找到可启动文件"
        raise CodexUsageError(f"无法启动可用的 Codex（已尝试 {attempted}）：{detail}")

    def _fetch_report(self, executable: Path) -> CodexUsageReport:
        requests = [
            {
                "id": 1,
                "method": "initialize",
                "params": {
                    "clientInfo": {"name": "petnest", "version": "0.1.0"},
                    "capabilities": {"experimentalApi": True},
                },
            },
            {"method": "initialized"},
            {
                "id": 2,
                "method": "account/read",
                "params": {"refreshToken": False},
            },
            {"id": 3, "method": "account/rateLimits/read"},
            {"id": 4, "method": "account/usage/read"},
        ]
        responses = self._transport(
            executable,
            requests,
            frozenset({1, 2, 3, 4}),
            self.timeout,
        )
        fetched_at = datetime.now(UTC)
        initialize = responses[1]
        try:
            account = _parse_account(responses[2], responses[3])
        except CodexUsageError:
            if self._observation_store is not None:
                self._observation_store.observe(None, fetched_at)
            raise
        limits = _parse_rate_limits(responses[3])
        primary = next((item for item in limits if item.limit_id == "codex"), limits[0])
        summary, daily = _parse_account_tokens(responses[4])
        raw_home = initialize.get("codexHome")
        if not isinstance(raw_home, str) or not raw_home:
            raise CodexUsageError("Codex app-server 未返回本地数据目录")
        codex_home = Path(raw_home).expanduser()
        intervals: tuple[CodexAccountInterval, ...] = ()
        if self._observation_store is not None:
            intervals = self._observation_store.observe(
                account.key,
                fetched_at,
                inferred_started_at=_inferred_account_start(codex_home, primary, fetched_at),
            )
        local = scan_local_codex_usage(
            codex_home,
            primary,
            account_key=account.key,
            account_intervals=intervals,
            now=fetched_at,
            claimed_event_ids=(
                self._manual_attribution_store.claimed_event_ids(
                    account.key, int(primary.primary.resets_at.timestamp())
                )
                if self._manual_attribution_store is not None
                and primary.primary is not None
                and primary.primary.resets_at is not None
                else ()
            ),
        )
        return CodexUsageReport(
            account=account,
            rate_limits=limits,
            primary_limit=primary,
            account_tokens=summary,
            daily_usage=daily,
            local_usage=local,
            fetched_at=fetched_at,
            codex_home=codex_home,
        )


def discover_codex_executable() -> Path:
    """Return the first discovered Codex executable for compatibility."""
    return discover_codex_executables()[0]


def discover_codex_executables() -> tuple[Path, ...]:
    """Find all plausible Codex launchers in fallback order."""
    candidates: list[Path] = []
    for name in ("PETNEST_CODEX_EXECUTABLE", "CODEX_BIN"):
        value = os.environ.get(name)
        if value:
            candidates.append(Path(value).expanduser())
    if sys.platform == "darwin":
        candidates.extend(
            (
                Path("/Applications/ChatGPT.app/Contents/Resources/codex"),
                Path("/Applications/Codex.app/Contents/Resources/codex"),
                Path.home() / "Applications/ChatGPT.app/Contents/Resources/codex",
                Path.home() / "Applications/Codex.app/Contents/Resources/codex",
            )
        )
    elif sys.platform == "win32":
        local_app_data = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
        user_codex_root = local_app_data / "OpenAI/Codex/bin"
        if user_codex_root.is_dir():
            try:
                user_binaries = sorted(
                    user_codex_root.glob("*/codex.exe"),
                    key=lambda item: item.stat().st_mtime,
                    reverse=True,
                )
            except OSError:
                user_binaries = []
            candidates.extend(user_binaries)
        candidates.extend(
            (
                local_app_data / "Programs/ChatGPT/resources/codex.exe",
                local_app_data / "Programs/OpenAI/ChatGPT/resources/codex.exe",
                local_app_data / "Programs/Codex/resources/codex.exe",
            )
        )
    executable_names = ("codex.exe", "codex.cmd", "codex") if sys.platform == "win32" else ("codex",)
    for executable_name in executable_names:
        path_match = shutil.which(executable_name)
        if path_match:
            candidates.append(Path(path_match))
    discovered: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = str(candidate.absolute()).casefold() if sys.platform == "win32" else str(candidate.absolute())
        if normalized in seen:
            continue
        seen.add(normalized)
        if candidate.is_file() and (os.name == "nt" or os.access(candidate, os.X_OK)):
            discovered.append(candidate)
    if discovered:
        return tuple(discovered)
    raise CodexUsageError("未找到 Codex。请先安装或更新 ChatGPT/Codex 桌面应用。")


def locate_codex_home(
    *,
    environment: dict[str, str] | None = None,
    user_home: Path | None = None,
    client_factory: Callable[[], CodexUsageClient] = CodexUsageClient,
) -> Path:
    """定位当前 Codex 数据根目录，失败时保守回退到用户默认目录。"""
    values = os.environ if environment is None else environment
    configured = values.get("CODEX_HOME")
    if isinstance(configured, str) and configured.strip():
        return Path(configured).expanduser().resolve()
    default = ((user_home or Path.home()) / ".codex").expanduser().resolve()
    if default.is_dir():
        return default
    try:
        return client_factory().fetch_codex_home().expanduser().resolve()
    except (CodexUsageError, OSError, ValueError):
        return default


def _inferred_account_start(
    codex_home: Path,
    rate_limit: CodexRateLimit,
    observed_at: datetime,
) -> datetime:
    window_start = rate_limit.primary.starts_at if rate_limit.primary is not None else None
    inferred = _auth_modified_at(codex_home, observed_at)
    if window_start is not None:
        inferred = max(window_start, inferred)
    return inferred


def _auth_modified_at(codex_home: Path, observed_at: datetime) -> datetime:
    try:
        modified = datetime.fromtimestamp((codex_home / "auth.json").stat().st_mtime, UTC)
    except OSError:
        return observed_at
    return min(observed_at, modified)


def scan_local_codex_usage(
    codex_home: Path,
    rate_limit: CodexRateLimit,
    *,
    account_key: str | None = None,
    account_intervals: Iterable[CodexAccountInterval] = (),
    now: datetime | None = None,
    claimed_event_ids: Iterable[str] = (),
) -> LocalCodexUsage:
    """Sum local token events attributable to an account's current quota window.

    The enclosing ``turn_context.model`` is the source of truth for the model.
    Embedded rate-limit data is supporting evidence because Codex can attach a
    Spark/Bengalfox limit snapshot to an ordinary model token event.
    """
    window = rate_limit.primary
    if window is None or window.resets_at is None or window.starts_at is None:
        return LocalCodexUsage()
    reset_epoch = int(window.resets_at.timestamp())
    start = window.starts_at
    end = min(
        _aware_utc(now or datetime.now(UTC)) + timedelta(minutes=1),
        window.resets_at,
    )
    intervals = tuple(account_intervals)
    claimed = frozenset(claimed_event_ids)
    total = CodexTokenUsage()
    pending = CodexTokenUsage()
    anomalies = CodexTokenUsage()
    model_totals: dict[str, dict[str, int | float | bool]] = {}
    weighted_total = 0.0
    weighted_complete = True
    fast_uses = 0
    standard_uses = 0
    observations: list[tuple[datetime, float]] = []
    scanned = 0
    skipped = 0
    paths = tuple(_session_files(codex_home, start))
    fingerprint_paths = _session_ancestry_files(codex_home, paths)
    first_occurrence, duplicates = _token_fingerprint_index(fingerprint_paths, end)
    processed_events: set[str] = set()
    pending_event_ids: list[str] = []
    for path in paths:
        try:
            stream = path.open("r", encoding="utf-8")
        except OSError:
            skipped += 1
            continue
        scanned += 1
        current_model: str | None = None
        current_turn_id: str | None = None
        current_speed = "default"
        current_turn_speed = "default"
        current_model_use_counted = False
        previous_cumulative_total: int | None = None
        with stream:
            for line in stream:
                raw = _json_line(line)
                if raw is None:
                    continue
                speed = _local_speed_setting(raw, end)
                if speed is not None:
                    current_speed = speed
                    continue
                context = _local_model_context(raw, end)
                if context is not None:
                    current_model, current_turn_id = context
                    current_turn_speed = current_speed
                    current_model_use_counted = False
                    continue
                event = _local_token_event(raw, end, turn_id=current_turn_id)
                if event is None:
                    continue
                repeats_cumulative_total = (
                    event.cumulative_total_tokens is not None
                    and previous_cumulative_total is not None
                    and event.cumulative_total_tokens == previous_cumulative_total
                )
                if event.cumulative_total_tokens is not None:
                    previous_cumulative_total = event.cumulative_total_tokens
                if repeats_cumulative_total and _has_total_without_breakdown(event):
                    continue
                if (
                    event.timestamp < start
                    or event.timestamp >= window.resets_at
                    or first_occurrence.get(event.fingerprint) != event.timestamp
                    or event.fingerprint in processed_events
                ):
                    continue
                processed_events.add(event.fingerprint)
                attribution, anomalous = _event_attribution(
                    event,
                    current_model,
                    reset_epoch,
                    account_key,
                    intervals,
                )
                if attribution != "current" and event.fingerprint not in claimed:
                    pending += event.usage
                    pending_event_ids.append(event.fingerprint)
                    continue
                total += event.usage
                if anomalous:
                    anomalies += event.usage
                if (
                    event.used_percent is not None
                    and event.limit_id == rate_limit.limit_id
                    and event.reset_epoch is not None
                    and abs(event.reset_epoch - reset_epoch) <= 10
                ):
                    observations.append((event.timestamp, event.used_percent))
                if current_model is not None:
                    counters = model_totals.setdefault(
                        current_model,
                        {
                            "uses": 0,
                            "total": 0,
                            "input": 0,
                            "cached": 0,
                            "output": 0,
                            "weighted": 0.0,
                            "complete": True,
                        },
                    )
                    if not current_model_use_counted:
                        counters["uses"] = int(counters["uses"]) + 1
                        if current_turn_speed in {"fast", "priority"}:
                            fast_uses += 1
                        else:
                            standard_uses += 1
                        current_model_use_counted = True
                    counters["total"] = int(counters["total"]) + event.usage.total_tokens
                    counters["input"] = int(counters["input"]) + event.usage.input_tokens
                    counters["cached"] = int(counters["cached"]) + event.usage.cached_input_tokens
                    counters["output"] = int(counters["output"]) + event.usage.output_tokens
                    weighted = _weighted_credits(current_model, event.usage, current_turn_speed)
                    if weighted is None:
                        weighted_complete = False
                        counters["complete"] = False
                    else:
                        weighted_total += weighted
                        counters["weighted"] = float(counters["weighted"]) + weighted
                else:
                    weighted_complete = False
    observations.sort(key=lambda item: item[0])
    observed_start = observations[0][1] if observations else None
    observed_end = window.used_percent if observations else None
    models = tuple(
        CodexModelUsage(
            model=model,
            uses=int(values["uses"]),
            total_tokens=int(values["total"]),
            input_tokens=int(values["input"]),
            cached_input_tokens=int(values["cached"]),
            output_tokens=int(values["output"]),
            weighted_credits=(float(values["weighted"]) if values["complete"] else None),
        )
        for model, values in sorted(
            model_totals.items(),
            key=lambda item: (-int(item[1]["uses"]), -int(item[1]["total"]), item[0].casefold()),
        )[:20]
    )
    return LocalCodexUsage(
        tokens=total,
        model_usage=models,
        weighted_credits=weighted_total,
        weighted_complete=weighted_complete,
        pending_tokens=pending,
        anomaly_tokens=anomalies,
        duplicate_events=duplicates,
        fast_uses=fast_uses,
        standard_uses=standard_uses,
        observed_start_used_percent=observed_start,
        observed_end_used_percent=observed_end,
        files_scanned=scanned,
        files_skipped=skipped,
        pending_event_ids=tuple(pending_event_ids),
    )


@dataclass(frozen=True, slots=True)
class CodexAccountSnapshot:
    account_key: str
    account_label: str
    plan_type: str
    updated_at: str
    used_percent: float
    remaining_percent: float
    window_duration_minutes: int | None
    resets_at: str | None
    local_tokens: int
    local_input_tokens: int
    local_cached_input_tokens: int
    local_output_tokens: int
    local_requests: int
    observed_quota_change: float | None
    account_lifetime_tokens: int | None
    local_model_usage: tuple[CodexModelUsage, ...] = ()
    local_fast_uses: int = 0
    local_standard_uses: int = 0
    local_files_scanned: int = 0
    local_files_skipped: int = 0
    local_scan_status: str = "unknown"
    local_weighted_credits: float | None = None
    local_weighted_complete: bool = True
    local_pending_tokens: int = 0
    local_anomaly_tokens: int = 0
    finalized: bool = False

    @classmethod
    def from_report(cls, report: CodexUsageReport) -> "CodexAccountSnapshot":
        window = report.primary_limit.primary
        if window is None:
            raise ValueError("Codex 主额度没有可保存的时间窗口")
        local = report.local_usage.tokens
        return cls(
            account_key=report.account.key,
            account_label=report.account.label,
            plan_type=report.account.plan_type,
            updated_at=report.fetched_at.isoformat(),
            used_percent=window.used_percent,
            remaining_percent=window.remaining_percent,
            window_duration_minutes=window.window_duration_minutes,
            resets_at=window.resets_at.isoformat() if window.resets_at is not None else None,
            local_tokens=local.total_tokens,
            local_input_tokens=local.input_tokens,
            local_cached_input_tokens=local.cached_input_tokens,
            local_output_tokens=local.output_tokens,
            local_requests=local.requests,
            observed_quota_change=report.local_usage.observed_quota_change,
            account_lifetime_tokens=report.account_tokens.lifetime_tokens,
            local_model_usage=report.local_usage.model_usage,
            local_fast_uses=report.local_usage.fast_uses,
            local_standard_uses=report.local_usage.standard_uses,
            local_files_scanned=report.local_usage.files_scanned,
            local_files_skipped=report.local_usage.files_skipped,
            local_scan_status=report.local_usage.scan_status,
            local_weighted_credits=report.local_usage.weighted_credits,
            local_weighted_complete=report.local_usage.weighted_complete,
            local_pending_tokens=report.local_usage.pending_tokens.total_tokens,
            local_anomaly_tokens=report.local_usage.anomaly_tokens.total_tokens,
            finalized=False,
        )


class CodexUsageHistoryStore:
    """Persist non-secret snapshots by account and quota-reset cycle."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> tuple[CodexAccountSnapshot, ...]:
        """Return the newest cycle for each account for the account selector."""
        newest: dict[str, CodexAccountSnapshot] = {}
        for snapshot in self._load_all():
            previous = newest.get(snapshot.account_key)
            if previous is None or snapshot.updated_at > previous.updated_at:
                newest[snapshot.account_key] = snapshot
        return tuple(sorted(newest.values(), key=lambda item: item.updated_at, reverse=True))

    def load_cycles(self, account_key: str) -> tuple[CodexAccountSnapshot, ...]:
        snapshots = [item for item in self._load_all() if item.account_key == account_key]
        snapshots.sort(
            key=lambda item: (item.resets_at or "", item.updated_at),
            reverse=True,
        )
        return tuple(snapshots)

    def _load_all(self) -> list[CodexAccountSnapshot]:
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return []
        if not isinstance(raw, dict):
            return []
        # Schema 1 stored only the latest account snapshot. Treat those entries
        # as ordinary cycles so upgrading does not discard existing history.
        containers = [raw.get("cycles"), raw.get("accounts")]
        snapshots: list[CodexAccountSnapshot] = []
        seen: set[tuple[str, str | None]] = set()
        for container in containers:
            if not isinstance(container, dict):
                continue
            for value in container.values():
                if not isinstance(value, dict):
                    continue
                try:
                    normalized = dict(value)
                    normalized["local_model_usage"] = _parse_model_usage(
                        normalized.get("local_model_usage")
                    )
                    snapshot = CodexAccountSnapshot(**normalized)
                except (TypeError, ValueError):
                    continue
                key = (snapshot.account_key, snapshot.resets_at)
                if key not in seen:
                    snapshots.append(snapshot)
                    seen.add(key)
        return snapshots

    def save_report(self, report: CodexUsageReport) -> CodexAccountSnapshot:
        snapshot = CodexAccountSnapshot.from_report(report)
        cycles = self._finalize_expired_cycles(self._load_all(), report)
        cycles = [
            item
            for item in cycles
            if not _same_account_cycle(item, snapshot)
        ]
        by_cycle = {_account_cycle_key(item): item for item in cycles}
        by_cycle[_account_cycle_key(snapshot)] = snapshot
        # Keep enough weekly cycles for several accounts without unbounded state.
        ordered = sorted(
            by_cycle.values(),
            key=lambda item: (item.resets_at or "", item.updated_at),
            reverse=True,
        )[:200]
        payload = {
            "schema_version": 4,
            "cycles": {_account_cycle_key(item): asdict(item) for item in ordered},
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            try:
                temporary.chmod(0o600)
            except OSError:
                # Windows ACLs and some packaged filesystems do not implement
                # POSIX modes; the snapshot contains no credentials or raw email.
                pass
            temporary.replace(self.path)
        finally:
            if temporary.exists():
                temporary.unlink()
        return snapshot

    def _finalize_expired_cycles(
        self,
        snapshots: list[CodexAccountSnapshot],
        report: CodexUsageReport,
    ) -> list[CodexAccountSnapshot]:
        finalized: list[CodexAccountSnapshot] = []
        for snapshot in snapshots:
            if snapshot.account_key != report.account.key or snapshot.finalized or not snapshot.resets_at:
                finalized.append(snapshot)
                continue
            try:
                reset = datetime.fromisoformat(snapshot.resets_at)
            except ValueError:
                finalized.append(snapshot)
                continue
            if reset.tzinfo is None:
                reset = reset.replace(tzinfo=UTC)
            if reset > report.fetched_at:
                finalized.append(snapshot)
                continue
            window = CodexRateWindow(
                used_percent=snapshot.used_percent,
                window_duration_minutes=snapshot.window_duration_minutes,
                resets_at=reset,
            )
            historical_limit = CodexRateLimit(
                limit_id="codex",
                limit_name="Codex",
                plan_type=snapshot.plan_type,
                primary=window,
                secondary=None,
                credit_balance=None,
                has_credits=False,
                unlimited_credits=False,
            )
            local_usage = scan_local_codex_usage(
                report.codex_home,
                historical_limit,
                account_key=report.account.key,
                account_intervals=CodexAccountObservationStore(
                    codex_account_observation_path(self.path)
                ).load(),
                now=report.fetched_at,
                claimed_event_ids=CodexManualAttributionStore(
                    codex_manual_attribution_path(self.path)
                ).claimed_event_ids(report.account.key, int(reset.timestamp())),
            )
            local = local_usage.tokens
            if local.total_tokens <= 0 and snapshot.local_tokens > 0:
                finalized.append(replace(snapshot, finalized=True))
                continue
            finalized.append(
                replace(
                    snapshot,
                    local_tokens=local.total_tokens,
                    local_input_tokens=local.input_tokens,
                    local_cached_input_tokens=local.cached_input_tokens,
                    local_output_tokens=local.output_tokens,
                    local_requests=local.requests,
                    local_model_usage=local_usage.model_usage,
                    local_fast_uses=local_usage.fast_uses,
                    local_standard_uses=local_usage.standard_uses,
                    local_files_scanned=local_usage.files_scanned,
                    local_files_skipped=local_usage.files_skipped,
                    local_scan_status=local_usage.scan_status,
                    local_weighted_credits=local_usage.weighted_credits,
                    local_weighted_complete=local_usage.weighted_complete,
                    local_pending_tokens=local_usage.pending_tokens.total_tokens,
                    local_anomaly_tokens=local_usage.anomaly_tokens.total_tokens,
                    finalized=True,
                )
            )
        return finalized


def _account_cycle_key(snapshot: CodexAccountSnapshot) -> str:
    reset = snapshot.resets_at or snapshot.updated_at
    return f"{snapshot.account_key}:{reset}"


def _same_account_cycle(first: CodexAccountSnapshot, second: CodexAccountSnapshot) -> bool:
    if first.account_key != second.account_key:
        return False
    first_reset = _timestamp(first.resets_at)
    second_reset = _timestamp(second.resets_at)
    if first_reset is None or second_reset is None:
        return first.resets_at == second.resets_at
    return abs((first_reset - second_reset).total_seconds()) <= 10


@dataclass(frozen=True, slots=True)
class CodexDeviceUsageSnapshot:
    """One computer's non-secret contribution to an account quota window."""

    account_key: str
    device_id: str
    device_label: str
    window_resets_at: int
    window_duration_minutes: int | None
    updated_at: str
    input_tokens: int
    cached_input_tokens: int
    cache_write_input_tokens: int
    output_tokens: int
    reasoning_output_tokens: int
    total_tokens: int
    requests: int
    model_usage: tuple[CodexModelUsage, ...] = ()
    account_label: str = ""
    plan_type: str = ""
    account_used_percent: float | None = None
    fast_uses: int = 0
    standard_uses: int = 0
    files_scanned: int = 0
    files_skipped: int = 0
    scan_status: str = "unknown"
    weighted_credits: float | None = None
    weighted_complete: bool = True
    pending_tokens: int = 0
    anomaly_tokens: int = 0

    @property
    def tokens(self) -> CodexTokenUsage:
        return CodexTokenUsage(
            input_tokens=self.input_tokens,
            cached_input_tokens=self.cached_input_tokens,
            cache_write_input_tokens=self.cache_write_input_tokens,
            output_tokens=self.output_tokens,
            reasoning_output_tokens=self.reasoning_output_tokens,
            total_tokens=self.total_tokens,
            requests=self.requests,
        )

    @classmethod
    def from_report(
        cls,
        report: CodexUsageReport,
        *,
        device_id: str,
        device_label: str,
    ) -> "CodexDeviceUsageSnapshot":
        window = report.primary_limit.primary
        if window is None or window.resets_at is None:
            raise ValueError("Codex 主额度没有可同步的重置时间")
        normalized_device_id = str(device_id).strip()
        normalized_label = str(device_label).strip()
        if not normalized_device_id or len(normalized_device_id) > 64:
            raise ValueError("本机设备 ID 无效")
        if not normalized_label:
            raise ValueError("本机设备名称无效")
        tokens = report.local_usage.tokens
        return cls(
            account_key=report.account.key,
            device_id=normalized_device_id,
            device_label=normalized_label[:40],
            window_resets_at=int(window.resets_at.timestamp()),
            window_duration_minutes=window.window_duration_minutes,
            updated_at=report.fetched_at.isoformat(),
            input_tokens=tokens.input_tokens,
            cached_input_tokens=tokens.cached_input_tokens,
            cache_write_input_tokens=tokens.cache_write_input_tokens,
            output_tokens=tokens.output_tokens,
            reasoning_output_tokens=tokens.reasoning_output_tokens,
            total_tokens=tokens.total_tokens,
            requests=tokens.requests,
            model_usage=report.local_usage.model_usage,
            account_label=report.account.label,
            plan_type=report.account.plan_type,
            account_used_percent=(window.used_percent if window is not None else None),
            fast_uses=report.local_usage.fast_uses,
            standard_uses=report.local_usage.standard_uses,
            files_scanned=report.local_usage.files_scanned,
            files_skipped=report.local_usage.files_skipped,
            scan_status=report.local_usage.scan_status,
            weighted_credits=report.local_usage.weighted_credits,
            weighted_complete=report.local_usage.weighted_complete,
            pending_tokens=report.local_usage.pending_tokens.total_tokens,
            anomaly_tokens=report.local_usage.anomaly_tokens.total_tokens,
        )


class CodexDeviceUsageStore:
    """Persist the latest direct-LAN contribution per account and device."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(
        self,
        *,
        account_key: str | None = None,
        window_resets_at: int | None = None,
        exclude_device_id: str | None = None,
    ) -> tuple[CodexDeviceUsageSnapshot, ...]:
        snapshots = self._load_all()
        if account_key is not None:
            snapshots = [item for item in snapshots if item.account_key == account_key]
        if window_resets_at is not None:
            snapshots = [
                item
                for item in snapshots
                if abs(item.window_resets_at - window_resets_at) <= 10
            ]
        if exclude_device_id is not None:
            snapshots = [item for item in snapshots if item.device_id != exclude_device_id]
        snapshots.sort(key=lambda item: item.updated_at, reverse=True)
        return tuple(snapshots)

    def save(self, snapshot: CodexDeviceUsageSnapshot) -> None:
        if not _valid_device_snapshot(snapshot):
            raise ValueError("Codex 设备用量快照无效")
        existing = [
            item
            for item in self._load_all()
            if not (
                item.account_key == snapshot.account_key
                and item.device_id == snapshot.device_id
                and abs(item.window_resets_at - snapshot.window_resets_at) <= 10
            )
        ]
        snapshots = {
            _device_cycle_key(item): item
            for item in existing
        }
        snapshots[_device_cycle_key(snapshot)] = snapshot
        ordered = sorted(
            snapshots.values(),
            key=lambda item: item.updated_at,
            reverse=True,
        )[:500]
        payload = {
            "schema_version": 5,
            "devices": {
                _device_cycle_key(item): asdict(item)
                for item in ordered
            },
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            try:
                temporary.chmod(0o600)
            except OSError:
                pass
            temporary.replace(self.path)
        finally:
            if temporary.exists():
                temporary.unlink()

    def _load_all(self) -> list[CodexDeviceUsageSnapshot]:
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return []
        devices = raw.get("devices") if isinstance(raw, dict) else None
        if not isinstance(devices, dict):
            return []
        snapshots: list[CodexDeviceUsageSnapshot] = []
        for value in devices.values():
            if not isinstance(value, dict):
                continue
            try:
                normalized = dict(value)
                normalized["model_usage"] = _parse_model_usage(
                    normalized.get("model_usage")
                )
                snapshot = CodexDeviceUsageSnapshot(**normalized)
            except (TypeError, ValueError):
                continue
            if _valid_device_snapshot(snapshot):
                snapshots.append(snapshot)
        return snapshots


def codex_device_usage_path(account_history_path: Path) -> Path:
    """Derive a sibling file so existing account-history schema stays stable."""
    suffix = account_history_path.suffix or ".json"
    stem = account_history_path.stem if account_history_path.suffix else account_history_path.name
    return account_history_path.with_name(f"{stem}-devices{suffix}")


def codex_account_observation_path(account_history_path: Path) -> Path:
    """Derive a sibling non-secret account-observation file."""
    suffix = account_history_path.suffix or ".json"
    stem = account_history_path.stem if account_history_path.suffix else account_history_path.name
    return account_history_path.with_name(f"{stem}-accounts{suffix}")


def codex_manual_attribution_path(account_history_path: Path) -> Path:
    """Derive the local-only manual token attribution file."""
    suffix = account_history_path.suffix or ".json"
    stem = account_history_path.stem if account_history_path.suffix else account_history_path.name
    return account_history_path.with_name(f"{stem}-manual-attributions{suffix}")


def _device_cycle_key(snapshot: CodexDeviceUsageSnapshot) -> str:
    return f"{snapshot.account_key}:{snapshot.window_resets_at}:{snapshot.device_id}"


def _valid_device_snapshot(snapshot: CodexDeviceUsageSnapshot) -> bool:
    if not re.fullmatch(r"[0-9a-f]{24}", snapshot.account_key):
        return False
    if not snapshot.device_id or len(snapshot.device_id) > 64:
        return False
    if any(char in snapshot.device_id for char in "\\/\r\n\x00"):
        return False
    if not snapshot.device_label or len(snapshot.device_label) > 40:
        return False
    if len(snapshot.account_label) > 100 or any(
        char in snapshot.account_label for char in "\r\n\x00"
    ):
        return False
    if len(snapshot.plan_type) > 40 or any(char in snapshot.plan_type for char in "\r\n\x00"):
        return False
    if snapshot.account_used_percent is not None and (
        isinstance(snapshot.account_used_percent, bool)
        or not isinstance(snapshot.account_used_percent, (int, float))
        or not 0 <= snapshot.account_used_percent <= 100
    ):
        return False
    if not isinstance(snapshot.window_resets_at, int) or snapshot.window_resets_at <= 0:
        return False
    if snapshot.window_duration_minutes is not None and (
        not isinstance(snapshot.window_duration_minutes, int)
        or not 0 < snapshot.window_duration_minutes <= 525_600
    ):
        return False
    try:
        datetime.fromisoformat(snapshot.updated_at)
    except (TypeError, ValueError):
        return False
    counters = (
        snapshot.input_tokens,
        snapshot.cached_input_tokens,
        snapshot.cache_write_input_tokens,
        snapshot.output_tokens,
        snapshot.reasoning_output_tokens,
        snapshot.total_tokens,
        snapshot.requests,
        snapshot.fast_uses,
        snapshot.standard_uses,
        snapshot.files_scanned,
        snapshot.files_skipped,
        snapshot.pending_tokens,
        snapshot.anomaly_tokens,
    )
    return (
        all(isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 10**18 for value in counters)
        and (
            snapshot.weighted_credits is None
            or (
                isinstance(snapshot.weighted_credits, (int, float))
                and not isinstance(snapshot.weighted_credits, bool)
                and 0 <= snapshot.weighted_credits <= 10**18
            )
        )
        and isinstance(snapshot.weighted_complete, bool)
        and snapshot.scan_status
        in {"unknown", "matched", "no_matching_events", "unreadable_files", "no_session_files"}
        and snapshot.model_usage == _parse_model_usage(snapshot.model_usage)
    )


def _stdio_rpc_transport(
    executable: Path,
    messages: list[dict[str, Any]],
    expected_ids: frozenset[int],
    timeout: float,
) -> dict[int, dict[str, Any]]:
    creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    try:
        process = subprocess.Popen(
            _codex_app_server_command(executable),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            bufsize=1,
            creationflags=creation_flags,
        )
    except OSError as error:
        raise CodexUsageError(f"无法启动 Codex app-server：{error}") from error
    if process.stdin is None or process.stdout is None:
        process.kill()
        raise CodexUsageError("无法连接 Codex app-server 标准输入输出")
    lines: Queue[str | None] = Queue()

    def read_stdout(stream: TextIO) -> None:
        try:
            for line in stream:
                lines.put(line)
        finally:
            lines.put(None)

    reader = Thread(target=read_stdout, args=(process.stdout,), daemon=True)
    reader.start()
    try:
        for message in messages:
            process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
        process.stdin.flush()
        responses: dict[int, dict[str, Any]] = {}
        deadline = monotonic() + timeout
        while not expected_ids.issubset(responses):
            remaining = deadline - monotonic()
            if remaining <= 0:
                missing = sorted(expected_ids - responses.keys())
                raise CodexUsageError(f"等待 Codex 用量响应超时（缺少 {missing}）")
            try:
                line = lines.get(timeout=min(remaining, 0.5))
            except Empty:
                if process.poll() is not None:
                    raise CodexUsageError("Codex app-server 提前退出，请更新 Codex 后重试")
                continue
            if line is None:
                raise CodexUsageError("Codex app-server 未返回完整用量数据")
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict) or not isinstance(payload.get("id"), int):
                continue
            identifier = int(payload["id"])
            if identifier not in expected_ids:
                continue
            error = payload.get("error")
            if isinstance(error, dict):
                message = error.get("message")
                if identifier in {3, 4}:
                    raise CodexUsageError(
                        "当前 Codex 版本或账号不支持用量读取，请更新 ChatGPT/Codex 后重试"
                    )
                raise CodexUsageError(str(message or "Codex 请求失败"))
            result = payload.get("result")
            if not isinstance(result, dict):
                raise CodexUsageError("Codex app-server 返回格式无效")
            responses[identifier] = result
        return responses
    except (BrokenPipeError, OSError) as error:
        raise CodexUsageError(f"与 Codex app-server 通信失败：{error}") from error
    finally:
        try:
            process.stdin.close()
        except OSError:
            pass
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)


def _codex_app_server_command(executable: Path) -> list[str]:
    arguments = [str(executable), "app-server", "--stdio"]
    if sys.platform != "win32" or executable.suffix.casefold() not in {".cmd", ".bat"}:
        return arguments
    command_processor = os.environ.get("COMSPEC", "cmd.exe")
    return [command_processor, "/d", "/s", "/c", subprocess.list2cmdline(arguments)]


def _parse_account(account_payload: dict[str, Any], rate_payload: dict[str, Any]) -> CodexAccount:
    raw = account_payload.get("account")
    if not isinstance(raw, dict):
        raise CodexUsageError("Codex 尚未登录 ChatGPT 账号")
    account_type = str(raw.get("type", "unknown"))
    email = raw.get("email")
    plan = str(raw.get("planType") or _legacy_plan_type(rate_payload) or "unknown")
    if account_type == "chatgpt" and isinstance(email, str) and email.strip():
        normalized = email.strip().casefold()
        key = hashlib.sha256(f"chatgpt\0{normalized}".encode()).hexdigest()[:24]
        label = _mask_email(email.strip())
    else:
        key = hashlib.sha256(f"{account_type}\0{plan}".encode()).hexdigest()[:24]
        label = "API Key 登录" if account_type == "apiKey" else "当前 Codex 账号"
    return CodexAccount(key=key, label=label, plan_type=plan)


def _legacy_plan_type(payload: dict[str, Any]) -> str | None:
    raw = payload.get("rateLimits")
    if isinstance(raw, dict) and isinstance(raw.get("planType"), str):
        return raw["planType"]
    return None


def _parse_rate_limits(payload: dict[str, Any]) -> tuple[CodexRateLimit, ...]:
    by_id = payload.get("rateLimitsByLimitId")
    raw_limits: list[tuple[str, dict[str, Any]]] = []
    if isinstance(by_id, dict):
        for key, value in by_id.items():
            if isinstance(key, str) and isinstance(value, dict):
                raw_limits.append((key, value))
    if not raw_limits:
        legacy = payload.get("rateLimits")
        if isinstance(legacy, dict):
            raw_limits.append((str(legacy.get("limitId") or "codex"), legacy))
    if not raw_limits:
        raise CodexUsageError("当前账号没有可读取的 Codex 用量窗口")
    limits = [_rate_limit(key, value) for key, value in raw_limits]
    limits.sort(key=lambda item: (item.limit_id != "codex", (item.limit_name or item.limit_id).casefold()))
    return tuple(limits)


def _rate_limit(key: str, raw: dict[str, Any]) -> CodexRateLimit:
    credits = raw.get("credits")
    if not isinstance(credits, dict):
        credits = {}
    return CodexRateLimit(
        limit_id=str(raw.get("limitId") or key),
        limit_name=str(raw["limitName"]) if isinstance(raw.get("limitName"), str) else None,
        plan_type=str(raw["planType"]) if isinstance(raw.get("planType"), str) else None,
        primary=_rate_window(raw.get("primary")),
        secondary=_rate_window(raw.get("secondary")),
        credit_balance=str(credits["balance"]) if credits.get("balance") is not None else None,
        has_credits=bool(credits.get("hasCredits", False)),
        unlimited_credits=bool(credits.get("unlimited", False)),
    )


def _rate_window(raw: object) -> CodexRateWindow | None:
    if not isinstance(raw, dict):
        return None
    used = _number(raw.get("usedPercent"))
    if used is None:
        return None
    duration = _integer(raw.get("windowDurationMins"))
    reset_epoch = _integer(raw.get("resetsAt"))
    reset = datetime.fromtimestamp(reset_epoch, UTC) if reset_epoch is not None else None
    return CodexRateWindow(
        used_percent=max(0.0, min(100.0, used)),
        window_duration_minutes=max(0, duration) if duration is not None else None,
        resets_at=reset,
    )


def _parse_account_tokens(
    payload: dict[str, Any],
) -> tuple[AccountTokenSummary, tuple[DailyTokenUsage, ...]]:
    raw_summary = payload.get("summary")
    if not isinstance(raw_summary, dict):
        raw_summary = {}
    summary = AccountTokenSummary(
        lifetime_tokens=_integer(raw_summary.get("lifetimeTokens")),
        peak_daily_tokens=_integer(raw_summary.get("peakDailyTokens")),
        current_streak_days=_integer(raw_summary.get("currentStreakDays")),
        longest_streak_days=_integer(raw_summary.get("longestStreakDays")),
        longest_running_turn_seconds=_integer(raw_summary.get("longestRunningTurnSec")),
    )
    daily: list[DailyTokenUsage] = []
    buckets = payload.get("dailyUsageBuckets")
    if isinstance(buckets, list):
        for raw in buckets:
            if not isinstance(raw, dict):
                continue
            try:
                start_date = date.fromisoformat(str(raw.get("startDate")))
            except ValueError:
                continue
            tokens = _integer(raw.get("tokens"))
            if tokens is not None:
                daily.append(DailyTokenUsage(start_date, max(0, tokens)))
    daily.sort(key=lambda item: item.start_date)
    return summary, tuple(daily)


def _session_files(codex_home: Path, start: datetime) -> Iterable[Path]:
    earliest_date = (start - timedelta(days=1)).date()
    chosen: dict[str, Path] = {}
    for root_name in ("sessions", "archived_sessions"):
        root = codex_home / root_name
        if not root.is_dir():
            continue
        try:
            paths = root.rglob("*.jsonl")
            for path in paths:
                match = re.match(r"rollout-(\d{4}-\d{2}-\d{2})", path.name)
                file_date: date | None = None
                if match:
                    try:
                        file_date = date.fromisoformat(match.group(1))
                    except ValueError:
                        pass
                try:
                    modified = datetime.fromtimestamp(path.stat().st_mtime, UTC)
                except OSError:
                    continue
                if file_date is not None and file_date < earliest_date and modified < start:
                    continue
                session_id = path.stem[-36:]
                existing = chosen.get(session_id)
                if existing is None:
                    chosen[session_id] = path
                    continue
                try:
                    if path.stat().st_mtime > existing.stat().st_mtime:
                        chosen[session_id] = path
                except OSError:
                    continue
        except OSError:
            continue
    return tuple(sorted(chosen.values()))


def _all_session_paths(codex_home: Path) -> dict[str, Path]:
    chosen: dict[str, Path] = {}
    for root_name in ("sessions", "archived_sessions"):
        root = codex_home / root_name
        if not root.is_dir():
            continue
        try:
            for path in root.rglob("*.jsonl"):
                session_id = path.stem[-36:]
                existing = chosen.get(session_id)
                if existing is None:
                    chosen[session_id] = path
                    continue
                try:
                    if path.stat().st_mtime > existing.stat().st_mtime:
                        chosen[session_id] = path
                except OSError:
                    continue
        except OSError:
            continue
    return chosen


def _session_ancestry_files(codex_home: Path, paths: tuple[Path, ...]) -> tuple[Path, ...]:
    """Include parent/fork origins so replayed history can be deduplicated cheaply."""
    by_id = _all_session_paths(codex_home)
    selected: dict[str, Path] = {path.stem[-36:]: path for path in paths}
    pending = list(paths)
    while pending:
        path = pending.pop()
        for parent_id in _session_parent_ids(path):
            if parent_id in selected:
                continue
            parent = by_id.get(parent_id)
            if parent is not None:
                selected[parent_id] = parent
                pending.append(parent)
    return tuple(sorted(selected.values()))


def _session_parent_ids(path: Path) -> tuple[str, ...]:
    try:
        stream = path.open("r", encoding="utf-8")
    except OSError:
        return ()
    with stream:
        for line in stream:
            raw = _json_line(line)
            if raw is None or raw.get("type") != "session_meta":
                continue
            payload = raw.get("payload")
            if not isinstance(payload, dict):
                return ()
            identifiers: list[str] = []
            for key in ("parent_thread_id", "forked_from_id"):
                value = str(payload.get(key) or "").strip()
                if re.fullmatch(r"[0-9a-fA-F-]{36}", value):
                    identifiers.append(value)
            return tuple(dict.fromkeys(identifiers))
    return ()


def _json_line(line: str) -> dict[str, Any] | None:
    try:
        raw = json.loads(line)
    except json.JSONDecodeError:
        return None
    return raw if isinstance(raw, dict) else None


def _local_model_context(raw: dict[str, Any], end: datetime) -> tuple[str, str | None] | None:
    if raw.get("type") != "turn_context":
        return None
    timestamp = _timestamp(raw.get("timestamp"))
    payload = raw.get("payload")
    if timestamp is None or timestamp > end or not isinstance(payload, dict):
        return None
    model = str(payload.get("model") or "").strip()
    if not _valid_model_name(model):
        return None
    turn_id = str(payload.get("turn_id") or "").strip()
    return model, turn_id[:80] or None


def _local_speed_setting(raw: dict[str, Any], end: datetime) -> str | None:
    payload = raw.get("payload")
    if not isinstance(payload, dict) or payload.get("type") != "thread_settings_applied":
        return None
    timestamp = _timestamp(raw.get("timestamp"))
    settings = payload.get("thread_settings")
    if timestamp is None or timestamp > end or not isinstance(settings, dict):
        return None
    service_tier = settings.get("service_tier")
    return str(service_tier) if service_tier in {"fast", "priority", "default"} else None


@dataclass(frozen=True, slots=True)
class _LocalTokenEvent:
    timestamp: datetime
    usage: CodexTokenUsage
    limit_id: str | None
    reset_epoch: int | None
    used_percent: float | None
    cumulative_total_tokens: int | None
    fingerprint: str


def _local_token_event(
    raw: dict[str, Any],
    end: datetime,
    *,
    turn_id: str | None = None,
) -> _LocalTokenEvent | None:
    payload = raw.get("payload")
    if not isinstance(payload, dict) or payload.get("type") != "token_count":
        return None
    timestamp = _timestamp(raw.get("timestamp"))
    if timestamp is None or timestamp > end:
        return None
    limits = payload.get("rate_limits")
    limit_id = str(limits.get("limit_id") or "codex") if isinstance(limits, dict) else None
    primary = limits.get("primary") if isinstance(limits, dict) else None
    event_reset = _integer(primary.get("resets_at")) if isinstance(primary, dict) else None
    used_percent = _number(primary.get("used_percent")) if isinstance(primary, dict) else None
    info = payload.get("info")
    last = info.get("last_token_usage") if isinstance(info, dict) else None
    if not isinstance(last, dict):
        return None
    usage = CodexTokenUsage(
        input_tokens=_nonnegative_integer(last.get("input_tokens")),
        cached_input_tokens=_nonnegative_integer(last.get("cached_input_tokens")),
        cache_write_input_tokens=_nonnegative_integer(last.get("cache_write_input_tokens")),
        output_tokens=_nonnegative_integer(last.get("output_tokens")),
        reasoning_output_tokens=_nonnegative_integer(last.get("reasoning_output_tokens")),
        total_tokens=_nonnegative_integer(last.get("total_tokens")),
        requests=1,
    )
    cumulative = info.get("total_token_usage") if isinstance(info, dict) else None
    cumulative_total = _integer(cumulative.get("total_tokens")) if isinstance(cumulative, dict) else None
    if cumulative_total is not None and cumulative_total < 0:
        cumulative_total = None
    fingerprint_source: dict[str, object] = {"last": last}
    if turn_id:
        fingerprint_source["turn_id"] = turn_id
    if isinstance(cumulative, dict):
        fingerprint_source["total"] = cumulative
    else:
        # Old logs without cumulative usage cannot be safely matched across
        # writes; include their timestamp to avoid collapsing legitimate twins.
        fingerprint_source["timestamp"] = timestamp.isoformat()
    fingerprint = hashlib.sha256(
        json.dumps(
            fingerprint_source,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return _LocalTokenEvent(
        timestamp=timestamp,
        usage=usage,
        limit_id=limit_id,
        reset_epoch=event_reset,
        used_percent=(max(0.0, min(100.0, used_percent)) if used_percent is not None else None),
        cumulative_total_tokens=cumulative_total,
        fingerprint=fingerprint,
    )


def _has_total_without_breakdown(event: _LocalTokenEvent) -> bool:
    usage = event.usage
    return (
        usage.total_tokens > 0
        and not any(
            (
                usage.input_tokens,
                usage.cached_input_tokens,
                usage.cache_write_input_tokens,
                usage.output_tokens,
                usage.reasoning_output_tokens,
            )
        )
    )


def _token_fingerprint_index(
    paths: tuple[Path, ...],
    end: datetime,
) -> tuple[dict[str, datetime], int]:
    first: dict[str, datetime] = {}
    occurrences = 0
    for path in paths:
        try:
            stream = path.open("r", encoding="utf-8")
        except OSError:
            continue
        with stream:
            turn_id: str | None = None
            for line in stream:
                raw = _json_line(line)
                if raw is None:
                    continue
                context = _local_model_context(raw, end)
                if context is not None:
                    _model, turn_id = context
                    continue
                event = _local_token_event(raw, end, turn_id=turn_id)
                if event is None:
                    continue
                occurrences += 1
                earliest = first.get(event.fingerprint)
                if earliest is None or event.timestamp < earliest:
                    first[event.fingerprint] = event.timestamp
    return first, max(0, occurrences - len(first))


def _event_attribution(
    event: _LocalTokenEvent,
    model: str | None,
    reset_epoch: int,
    account_key: str | None,
    intervals: tuple[CodexAccountInterval, ...],
) -> tuple[str, bool]:
    if account_key is not None and intervals and not _inside_account_interval(
        event.timestamp,
        account_key,
        intervals,
    ):
        return "pending", False
    reset_matches = event.reset_epoch is not None and abs(event.reset_epoch - reset_epoch) <= 10
    if model is None:
        return ("current", False) if event.limit_id == "codex" and reset_matches else ("pending", False)
    if event.limit_id == "codex" and event.reset_epoch is not None and not reset_matches:
        # A normal-Codex snapshot for another reset cycle is strong evidence of
        # replayed history or another account, so keep it visible but pending.
        return "pending", False
    anomalous = event.limit_id not in {None, "codex"}
    return "current", anomalous


def _inside_account_interval(
    timestamp: datetime,
    account_key: str,
    intervals: tuple[CodexAccountInterval, ...],
) -> bool:
    for interval in intervals:
        if interval.account_key != account_key or timestamp < interval.started_at:
            continue
        confirmed_end = interval.ended_at or interval.last_seen_at
        if timestamp <= confirmed_end:
            return True
    return False


# Relative Codex credit rates per 1M tokens. They are intentionally kept as a
# local estimate: the server's account percentage remains the authoritative
# quota value and is only apportioned between devices using these weights.
_MODEL_CREDIT_RATES: dict[str, tuple[float, float, float]] = {
    "gpt-5.6-sol": (125.0, 12.5, 750.0),
    "gpt-5.6-terra": (50.0, 5.0, 300.0),
    "gpt-5.6-luna": (5.0, 0.5, 30.0),
    "gpt-5.5": (125.0, 12.5, 750.0),
    "gpt-5.4": (62.5, 6.25, 375.0),
    "gpt-5.4-mini": (18.75, 1.875, 113.0),
    "gpt-5.3-codex": (43.75, 4.375, 350.0),
}


def _weighted_credits(model: str, usage: CodexTokenUsage, speed: str) -> float | None:
    rates = _MODEL_CREDIT_RATES.get(model.strip().casefold())
    if rates is None:
        return None
    if usage.total_tokens > 0 and not any(
        (usage.input_tokens, usage.cached_input_tokens, usage.output_tokens)
    ):
        return None
    input_rate, cached_rate, output_rate = rates
    noncached_input = max(0, usage.input_tokens - usage.cached_input_tokens)
    weighted = (
        noncached_input * input_rate
        + usage.cached_input_tokens * cached_rate
        + usage.output_tokens * output_rate
    ) / 1_000_000
    if speed in {"fast", "priority"}:
        normalized = model.strip().casefold()
        factors = {
            "gpt-5.6-sol": 2.5,
            "gpt-5.6-terra": 2.5,
            "gpt-5.6-luna": 2.5,
            "gpt-5.5": 2.5,
            "gpt-5.4": 2.0,
        }
        weighted *= factors.get(normalized, 1.0)
    return weighted


def _valid_model_name(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value.strip())
        and len(value.strip()) <= 80
        and not any(char in value for char in "\r\n\x00")
    )


def _parse_model_usage(value: object) -> tuple[CodexModelUsage, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    parsed: list[CodexModelUsage] = []
    seen: set[str] = set()
    for raw in value[:20]:
        if isinstance(raw, CodexModelUsage):
            item = raw
        elif isinstance(raw, dict):
            raw_uses = raw.get("uses", 0)
            raw_tokens = raw.get("total_tokens", 0)
            if (
                isinstance(raw_uses, bool)
                or not isinstance(raw_uses, int)
                or isinstance(raw_tokens, bool)
                or not isinstance(raw_tokens, int)
            ):
                continue
            try:
                item = CodexModelUsage(
                    model=str(raw.get("model") or "").strip(),
                    uses=raw_uses,
                    total_tokens=raw_tokens,
                    input_tokens=_nonnegative_integer(raw.get("input_tokens")),
                    cached_input_tokens=_nonnegative_integer(raw.get("cached_input_tokens")),
                    output_tokens=_nonnegative_integer(raw.get("output_tokens")),
                    weighted_credits=(
                        float(raw["weighted_credits"])
                        if isinstance(raw.get("weighted_credits"), (int, float))
                        and not isinstance(raw.get("weighted_credits"), bool)
                        else None
                    ),
                )
            except (TypeError, ValueError):
                continue
        else:
            continue
        if (
            not _valid_model_name(item.model)
            or item.model in seen
            or isinstance(item.uses, bool)
            or isinstance(item.total_tokens, bool)
            or not 0 <= item.uses <= 10**12
            or not 0 <= item.total_tokens <= 10**18
            or not 0 <= item.input_tokens <= 10**18
            or not 0 <= item.cached_input_tokens <= 10**18
            or not 0 <= item.output_tokens <= 10**18
            or (item.weighted_credits is not None and not 0 <= item.weighted_credits <= 10**18)
        ):
            continue
        seen.add(item.model)
        parsed.append(item)
    parsed.sort(key=lambda item: (-item.uses, -item.total_tokens, item.model.casefold()))
    return tuple(parsed)


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if result.tzinfo is None:
        result = result.replace(tzinfo=UTC)
    return result.astimezone(UTC)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _mask_email(email: str) -> str:
    local, separator, domain = email.partition("@")
    if not separator:
        return "当前 ChatGPT 账号"
    if len(local) <= 1:
        masked_local = "*"
    elif len(local) == 2:
        masked_local = f"{local[0]}*"
    else:
        # Fixed-width masking avoids leaking the original local-part length.
        masked_local = f"{local[:2]}*****"
    return f"{masked_local}@{domain}"


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _integer(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


def _nonnegative_integer(value: object) -> int:
    parsed = _integer(value)
    return max(0, parsed) if parsed is not None else 0


__all__ = [
    "AccountTokenSummary",
    "CodexAccount",
    "CodexAccountInterval",
    "CodexAccountObservationStore",
    "CodexManualAttributionStore",
    "CodexAccountSnapshot",
    "CodexDeviceUsageSnapshot",
    "CodexDeviceUsageStore",
    "CodexModelUsage",
    "CodexRateLimit",
    "CodexRateWindow",
    "CodexTokenUsage",
    "CodexUsageClient",
    "CodexUsageError",
    "CodexUsageHistoryStore",
    "CodexUsageReport",
    "DailyTokenUsage",
    "LocalCodexUsage",
    "discover_codex_executable",
    "discover_codex_executables",
    "locate_codex_home",
    "scan_local_codex_usage",
    "codex_account_observation_path",
    "codex_manual_attribution_path",
    "codex_device_usage_path",
]
