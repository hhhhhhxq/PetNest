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
from threading import Thread
from time import monotonic
from typing import Any, Callable, Iterable, TextIO


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
class LocalCodexUsage:
    tokens: CodexTokenUsage = CodexTokenUsage()
    observed_start_used_percent: float | None = None
    observed_end_used_percent: float | None = None
    files_scanned: int = 0
    files_skipped: int = 0

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
    ) -> None:
        self.executable = executable or discover_codex_executable()
        self.timeout = timeout
        self._transport = transport or _stdio_rpc_transport

    def fetch_report(self) -> CodexUsageReport:
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
            self.executable,
            requests,
            frozenset({1, 2, 3, 4}),
            self.timeout,
        )
        initialize = responses[1]
        account = _parse_account(responses[2], responses[3])
        limits = _parse_rate_limits(responses[3])
        primary = next((item for item in limits if item.limit_id == "codex"), limits[0])
        summary, daily = _parse_account_tokens(responses[4])
        raw_home = initialize.get("codexHome")
        if not isinstance(raw_home, str) or not raw_home:
            raise CodexUsageError("Codex app-server 未返回本地数据目录")
        codex_home = Path(raw_home).expanduser()
        local = scan_local_codex_usage(codex_home, primary)
        return CodexUsageReport(
            account=account,
            rate_limits=limits,
            primary_limit=primary,
            account_tokens=summary,
            daily_usage=daily,
            local_usage=local,
            fetched_at=datetime.now(UTC),
            codex_home=codex_home,
        )


def discover_codex_executable() -> Path:
    """Find the app-bundled Codex binary before falling back to ``PATH``."""
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
        candidates.extend(
            (
                local_app_data / "Programs/ChatGPT/resources/codex.exe",
                local_app_data / "Programs/OpenAI/ChatGPT/resources/codex.exe",
                local_app_data / "Programs/Codex/resources/codex.exe",
            )
        )
    path_match = shutil.which("codex.exe" if sys.platform == "win32" else "codex")
    if path_match:
        candidates.append(Path(path_match))
    for candidate in candidates:
        if candidate.is_file() and (os.name == "nt" or os.access(candidate, os.X_OK)):
            return candidate
    raise CodexUsageError("未找到 Codex。请先安装或更新 ChatGPT/Codex 桌面应用。")


def scan_local_codex_usage(codex_home: Path, rate_limit: CodexRateLimit) -> LocalCodexUsage:
    """Sum local token events belonging to the current account's quota window.

    Token events include the backend quota reset timestamp. Matching that value
    prevents ordinary account switches from mixing two accounts' local usage.
    """
    window = rate_limit.primary
    if window is None or window.resets_at is None or window.starts_at is None:
        return LocalCodexUsage()
    reset_epoch = int(window.resets_at.timestamp())
    start = window.starts_at
    end = datetime.now(UTC) + timedelta(minutes=1)
    total = CodexTokenUsage()
    observations: list[tuple[datetime, float]] = []
    scanned = 0
    skipped = 0
    seen_events: set[tuple[str, str, int]] = set()
    for path in _session_files(codex_home, start):
        try:
            stream = path.open("r", encoding="utf-8")
        except OSError:
            skipped += 1
            continue
        scanned += 1
        with stream:
            for line in stream:
                event = _local_token_event(line, rate_limit.limit_id, reset_epoch, start, end)
                if event is None:
                    continue
                timestamp, usage, used_percent = event
                signature = (path.stem[-36:], timestamp.isoformat(), usage.total_tokens)
                if signature in seen_events:
                    continue
                seen_events.add(signature)
                total += usage
                observations.append((timestamp, used_percent))
    observations.sort(key=lambda item: item[0])
    observed_start = observations[0][1] if observations else None
    observed_end = window.used_percent if observations else None
    return LocalCodexUsage(
        tokens=total,
        observed_start_used_percent=observed_start,
        observed_end_used_percent=observed_end,
        files_scanned=scanned,
        files_skipped=skipped,
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
                    snapshot = CodexAccountSnapshot(**value)
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
        by_cycle = {_account_cycle_key(item): item for item in cycles}
        by_cycle[_account_cycle_key(snapshot)] = snapshot
        # Keep enough weekly cycles for several accounts without unbounded state.
        ordered = sorted(
            by_cycle.values(),
            key=lambda item: (item.resets_at or "", item.updated_at),
            reverse=True,
        )[:200]
        payload = {
            "schema_version": 1,
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

    @staticmethod
    def _finalize_expired_cycles(
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
            local = scan_local_codex_usage(report.codex_home, historical_limit).tokens
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
                    finalized=True,
                )
            )
        return finalized


def _account_cycle_key(snapshot: CodexAccountSnapshot) -> str:
    reset = snapshot.resets_at or snapshot.updated_at
    return f"{snapshot.account_key}:{reset}"


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
        snapshots = {
            _device_cycle_key(item): item
            for item in self._load_all()
        }
        snapshots[_device_cycle_key(snapshot)] = snapshot
        ordered = sorted(
            snapshots.values(),
            key=lambda item: item.updated_at,
            reverse=True,
        )[:500]
        payload = {
            "schema_version": 2,
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
                snapshot = CodexDeviceUsageSnapshot(**value)
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
    )
    return all(isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 10**18 for value in counters)


def _stdio_rpc_transport(
    executable: Path,
    messages: list[dict[str, Any]],
    expected_ids: frozenset[int],
    timeout: float,
) -> dict[int, dict[str, Any]]:
    creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    try:
        process = subprocess.Popen(
            [str(executable), "app-server", "--stdio"],
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


def _local_token_event(
    line: str,
    limit_id: str,
    reset_epoch: int,
    start: datetime,
    end: datetime,
) -> tuple[datetime, CodexTokenUsage, float] | None:
    try:
        raw = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(raw, dict):
        return None
    payload = raw.get("payload")
    if not isinstance(payload, dict) or payload.get("type") != "token_count":
        return None
    timestamp = _timestamp(raw.get("timestamp"))
    if timestamp is None or timestamp < start or timestamp > end:
        return None
    limits = payload.get("rate_limits")
    if not isinstance(limits, dict) or str(limits.get("limit_id") or "codex") != limit_id:
        return None
    primary = limits.get("primary")
    if not isinstance(primary, dict):
        return None
    event_reset = _integer(primary.get("resets_at"))
    used_percent = _number(primary.get("used_percent"))
    if event_reset is None or abs(event_reset - reset_epoch) > 10 or used_percent is None:
        return None
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
    return timestamp, usage, max(0.0, min(100.0, used_percent))


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
    "CodexAccountSnapshot",
    "CodexDeviceUsageSnapshot",
    "CodexDeviceUsageStore",
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
    "scan_local_codex_usage",
    "codex_device_usage_path",
]
