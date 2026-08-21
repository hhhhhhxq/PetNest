"""Discover Codex installations and validate local status-log sources."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import date, timedelta
from enum import StrEnum
import json
from pathlib import Path
import shutil


class CodexAvailabilityState(StrEnum):
    """Connection availability independent from the current Codex task state."""

    DISABLED = "disabled"
    DETECTING = "detecting"
    NOT_DETECTED = "not_detected"
    DATA_ONLY = "data_only"
    WAITING_FOR_SESSIONS = "waiting_for_sessions"
    UNREADABLE = "unreadable"
    INCOMPATIBLE = "incompatible"
    READY = "ready"
    ACTIVE = "active"


@dataclass(frozen=True, slots=True)
class CodexHomeCandidate:
    """One normalized Codex Home candidate and the evidence that produced it."""

    home: Path
    source: str
    manual: bool


@dataclass(frozen=True, slots=True)
class CodexInstallEvidence:
    """One privacy-safe signal that Codex is installed, configured, or was used."""

    kind: str
    detail: str
    path: Path | None = None


@dataclass(frozen=True, slots=True)
class CodexLinkAvailability:
    """A privacy-safe discovery result consumed by the app and settings UI."""

    state: CodexAvailabilityState
    message: str
    codex_detected: bool
    evidence: tuple[str, ...] = ()
    selected_home: Path | None = None
    sessions_path: Path | None = None
    manual_override: bool = False
    can_watch: bool = False
    technical_reason: str = ""


class CodexLogSourceProbe:
    """Validate bounded structural fields without retaining conversation content."""

    _STATUS_EVENT_TYPES = frozenset({"task_started", "task_complete", "turn_aborted"})

    def __init__(
        self,
        *,
        today: Callable[[], date] = date.today,
        max_files: int = 64,
        max_probe_bytes: int = 64 * 1024,
    ) -> None:
        self._today = today
        self._max_files = max(1, int(max_files))
        self._max_probe_bytes = max(1024, int(max_probe_bytes))

    def probe(self, candidate: CodexHomeCandidate) -> CodexLinkAvailability:
        home = candidate.home.expanduser().resolve()
        sessions = home / "sessions"
        if not home.is_dir():
            return CodexLinkAvailability(
                state=CodexAvailabilityState.NOT_DETECTED,
                message="未找到 Codex 数据目录",
                codex_detected=False,
                selected_home=home,
                manual_override=candidate.manual,
                technical_reason="Codex Home 不存在",
            )
        if sessions.exists() and (not sessions.is_dir() or _is_link_like(sessions)):
            return CodexLinkAvailability(
                state=CodexAvailabilityState.UNREADABLE,
                message="无法读取 Codex 本地日志",
                codex_detected=False,
                evidence=(candidate.source,),
                selected_home=home,
                sessions_path=sessions,
                manual_override=candidate.manual,
                technical_reason="sessions 不是安全的普通目录",
            )
        if not sessions.exists():
            return self._waiting_result(candidate, home, sessions)
        files = self._candidate_files(sessions)
        if not files:
            return self._waiting_result(candidate, home, sessions)
        reasons: list[str] = []
        states: list[CodexAvailabilityState] = []
        for path in files:
            state, reason = self._probe_file(path)
            if state is CodexAvailabilityState.READY:
                return CodexLinkAvailability(
                    state=CodexAvailabilityState.READY,
                    message="联动已准备好，等待新的任务",
                    codex_detected=False,
                    evidence=(candidate.source,),
                    selected_home=home,
                    sessions_path=sessions,
                    manual_override=candidate.manual,
                    can_watch=True,
                )
            states.append(state)
            reasons.append(reason)
        state = (
            CodexAvailabilityState.UNREADABLE
            if CodexAvailabilityState.UNREADABLE in states
            else CodexAvailabilityState.INCOMPATIBLE
        )
        message = (
            "无法读取 Codex 本地日志"
            if state is CodexAvailabilityState.UNREADABLE
            else "当前 Codex 版本暂不支持基础联动"
        )
        return CodexLinkAvailability(
            state=state,
            message=message,
            codex_detected=False,
            evidence=(candidate.source,),
            selected_home=home,
            sessions_path=sessions,
            manual_override=candidate.manual,
            can_watch=False,
            technical_reason="; ".join(reason for reason in reasons[:3] if reason),
        )

    @staticmethod
    def _waiting_result(
        candidate: CodexHomeCandidate,
        home: Path,
        sessions: Path,
    ) -> CodexLinkAvailability:
        return CodexLinkAvailability(
            state=CodexAvailabilityState.WAITING_FOR_SESSIONS,
            message="等待 Codex 创建本地任务",
            codex_detected=False,
            evidence=(candidate.source,),
            selected_home=home,
            sessions_path=sessions,
            manual_override=candidate.manual,
            can_watch=True,
        )

    def _candidate_files(self, sessions: Path) -> tuple[Path, ...]:
        current = self._today()
        directories = tuple(
            sessions / f"{day:%Y}" / f"{day:%m}" / f"{day:%d}"
            for day in (current - timedelta(days=1), current)
        )
        files: list[Path] = []
        for directory in directories:
            if not directory.is_dir() or _is_link_like(directory):
                continue
            try:
                files.extend(
                    path
                    for path in directory.glob("*.jsonl")
                    if path.is_file() and not _is_link_like(path)
                )
            except OSError:
                continue
        files.sort(key=lambda path: str(path).casefold())
        return tuple(files[-self._max_files :])

    def _probe_file(self, path: Path) -> tuple[CodexAvailabilityState, str]:
        try:
            with path.open("rb") as stream:
                raw = stream.read(self._max_probe_bytes)
        except OSError as error:
            return CodexAvailabilityState.UNREADABLE, f"无法读取 {path.name}: {error}"
        session_id: str | None = None
        invalid_status_event = ""
        for line in raw.splitlines():
            try:
                document = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if not isinstance(document, dict):
                continue
            payload = document.get("payload")
            if document.get("type") == "session_meta" and isinstance(payload, dict):
                value = payload.get("session_id")
                if _bounded_identifier(value):
                    session_id = str(value)
            if document.get("type") == "event_msg" and isinstance(payload, dict):
                event_type = payload.get("type")
                if event_type in self._STATUS_EVENT_TYPES and not _bounded_identifier(payload.get("turn_id")):
                    invalid_status_event = f"{path.name} 的 {event_type} 缺少 turn_id"
        if session_id is None:
            return CodexAvailabilityState.INCOMPATIBLE, f"{path.name} 缺少 session_id"
        if invalid_status_event:
            return CodexAvailabilityState.INCOMPATIBLE, invalid_status_event
        return CodexAvailabilityState.READY, ""


class CodexInstallationDetector:
    """Collect platform-specific evidence without treating stale data as installation."""

    def __init__(
        self,
        *,
        platform_name: str,
        environment: Mapping[str, str],
        user_home: Path,
        which: Callable[[str], str | None] = shutil.which,
        application_roots: tuple[Path, ...] | None = None,
    ) -> None:
        self._platform_name = platform_name
        self._environment = environment
        self._user_home = user_home.expanduser().resolve()
        self._which = which
        self._application_roots = application_roots

    def detect(self) -> tuple[CodexInstallEvidence, ...]:
        evidence: list[CodexInstallEvidence] = []
        if self._platform_name == "win32":
            evidence.extend(self._windows_desktop_evidence())
        elif self._platform_name == "darwin":
            evidence.extend(self._macos_desktop_evidence())
        command = self._which("codex")
        if command:
            evidence.append(
                CodexInstallEvidence("cli", "PATH 中的 Codex CLI", Path(command).expanduser().resolve())
            )
        configured = self._environment.get("CODEX_HOME")
        if configured and configured.strip():
            evidence.append(
                CodexInstallEvidence(
                    "configured-home",
                    "CODEX_HOME",
                    Path(configured).expanduser().resolve(),
                )
            )
        default = self._user_home / ".codex"
        if default.is_dir() and not _is_link_like(default):
            evidence.append(CodexInstallEvidence("data", "默认 Codex 数据目录", default.resolve()))
        return _deduplicate_evidence(evidence)

    def _windows_desktop_evidence(self) -> tuple[CodexInstallEvidence, ...]:
        local = self._environment.get("LOCALAPPDATA")
        if not local:
            return ()
        candidates = []
        try:
            candidates = [
                path
                for path in Path(local).glob("OpenAI/Codex/bin/*/codex.exe")
                if path.is_file() and not _is_link_like(path)
            ]
        except OSError:
            return ()
        candidates.sort(key=_modified_ns, reverse=True)
        return tuple(
            CodexInstallEvidence("desktop", "Codex Desktop", path.resolve())
            for path in candidates
        )

    def _macos_desktop_evidence(self) -> tuple[CodexInstallEvidence, ...]:
        roots = self._application_roots or (
            Path("/Applications"),
            self._user_home / "Applications",
        )
        found: list[CodexInstallEvidence] = []
        for root in roots:
            app = root / "Codex.app"
            if app.is_dir() and not _is_link_like(app):
                found.append(CodexInstallEvidence("desktop", "Codex.app", app.resolve()))
        return tuple(found)


class CodexHomeDiscovery:
    """Generate every plausible Codex Home instead of stopping at the first directory."""

    def __init__(
        self,
        *,
        environment: Mapping[str, str],
        user_home: Path,
        app_home_provider: Callable[[], Path | None],
    ) -> None:
        self._environment = environment
        self._user_home = user_home.expanduser().resolve()
        self._app_home_provider = app_home_provider

    def candidates(self, manual_home: Path | None) -> tuple[CodexHomeCandidate, ...]:
        if manual_home is not None:
            return (
                CodexHomeCandidate(
                    normalize_selected_codex_home(manual_home),
                    source="manual",
                    manual=True,
                ),
            )
        raw: list[tuple[Path, str]] = []
        configured = self._environment.get("CODEX_HOME")
        if configured and configured.strip():
            raw.append((Path(configured).expanduser(), "environment"))
        try:
            app_home = self._app_home_provider()
        except (OSError, RuntimeError, ValueError):
            app_home = None
        if app_home is not None:
            raw.append((app_home, "app-server"))
        raw.append((self._user_home / ".codex", "default"))
        candidates: list[CodexHomeCandidate] = []
        seen: set[Path] = set()
        for path, source in raw:
            resolved = path.expanduser().resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            candidates.append(CodexHomeCandidate(resolved, source, False))
        return tuple(candidates)


class CodexDiscoveryService:
    """Select the best verified source while respecting an explicit manual home."""

    _STATE_SCORE = {
        CodexAvailabilityState.READY: 50,
        CodexAvailabilityState.WAITING_FOR_SESSIONS: 40,
        CodexAvailabilityState.UNREADABLE: 30,
        CodexAvailabilityState.INCOMPATIBLE: 20,
        CodexAvailabilityState.DATA_ONLY: 10,
        CodexAvailabilityState.NOT_DETECTED: 0,
    }

    def __init__(
        self,
        detector: CodexInstallationDetector,
        home_discovery: CodexHomeDiscovery,
        probe: CodexLogSourceProbe,
    ) -> None:
        self._detector = detector
        self._home_discovery = home_discovery
        self._probe = probe

    def discover(self, manual_home: Path | None) -> CodexLinkAvailability:
        evidence = self._detector.detect()
        candidates = self._home_discovery.candidates(manual_home)
        results = tuple(self._probe.probe(item) for item in candidates)
        if manual_home is not None:
            return self._manual_result(results, evidence)
        return self._best_auto_result(results, evidence, candidates)

    def _manual_result(
        self,
        results: tuple[CodexLinkAvailability, ...],
        evidence: tuple[CodexInstallEvidence, ...],
    ) -> CodexLinkAvailability:
        if not results:
            return CodexLinkAvailability(
                CodexAvailabilityState.NOT_DETECTED,
                "手动选择的 Codex 数据目录无效",
                self._has_strong_evidence(evidence),
                tuple(item.kind for item in evidence),
                manual_override=True,
                technical_reason="没有可验证的手动目录",
            )
        selected = results[0]
        automatic_candidates = self._home_discovery.candidates(None)
        automatic = tuple(self._probe.probe(candidate) for candidate in automatic_candidates)
        auto_ready = any(item.state is CodexAvailabilityState.READY for item in automatic)
        reason = selected.technical_reason
        if selected.state is not CodexAvailabilityState.READY and auto_ready:
            reason = (reason + "; " if reason else "") + "自动查找另有可用目录，可恢复自动查找"
        message = (
            "已选择 Codex 数据目录，等待 Codex 创建本地任务"
            if selected.state is CodexAvailabilityState.WAITING_FOR_SESSIONS
            else selected.message
        )
        strong = self._has_strong_evidence(evidence) or any(
            candidate.source == "app-server" for candidate in automatic_candidates
        )
        return replace(
            selected,
            message=message,
            codex_detected=selected.codex_detected or strong,
            evidence=_evidence_labels(evidence, automatic_candidates),
            manual_override=True,
            technical_reason=reason,
        )

    def _best_auto_result(
        self,
        results: tuple[CodexLinkAvailability, ...],
        evidence: tuple[CodexInstallEvidence, ...],
        candidates: tuple[CodexHomeCandidate, ...],
    ) -> CodexLinkAvailability:
        strong = self._has_strong_evidence(evidence) or any(
            candidate.source == "app-server" for candidate in candidates
        )
        labels = _evidence_labels(evidence, candidates)
        if not results:
            state = (
                CodexAvailabilityState.DATA_ONLY
                if any(item.kind == "data" for item in evidence)
                else CodexAvailabilityState.NOT_DETECTED
            )
            message = (
                "发现 Codex 数据，但未确认当前安装"
                if state is CodexAvailabilityState.DATA_ONLY
                else "未检测到 Codex，安装或启动后会自动连接"
            )
            return CodexLinkAvailability(state, message, strong, labels)
        selected = max(results, key=lambda item: self._STATE_SCORE[item.state])
        if selected.state is CodexAvailabilityState.WAITING_FOR_SESSIONS and not strong:
            return replace(
                selected,
                state=CodexAvailabilityState.DATA_ONLY,
                message="发现 Codex 数据，但未确认当前安装",
                codex_detected=False,
                evidence=labels,
                can_watch=False,
            )
        if selected.state is CodexAvailabilityState.WAITING_FOR_SESSIONS and strong:
            selected = replace(selected, message="已检测到 Codex，等待创建本地任务")
        return replace(
            selected,
            codex_detected=selected.codex_detected or strong,
            evidence=labels,
        )

    @staticmethod
    def _has_strong_evidence(evidence: tuple[CodexInstallEvidence, ...]) -> bool:
        return any(item.kind in {"desktop", "cli", "configured-home"} for item in evidence)


def normalize_selected_codex_home(path: Path) -> Path:
    """Accept either Codex Home or its sessions child and return the Home path."""
    resolved = path.expanduser().resolve()
    return resolved.parent if resolved.name.casefold() == "sessions" else resolved


def _bounded_identifier(value: object) -> bool:
    return isinstance(value, str) and 0 < len(value) <= 200


def _modified_ns(path: Path) -> int:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return 0


def _deduplicate_evidence(
    evidence: list[CodexInstallEvidence],
) -> tuple[CodexInstallEvidence, ...]:
    result: list[CodexInstallEvidence] = []
    seen: set[tuple[str, Path | None]] = set()
    for item in evidence:
        key = (item.kind, item.path)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return tuple(result)


def _evidence_labels(
    evidence: tuple[CodexInstallEvidence, ...],
    candidates: tuple[CodexHomeCandidate, ...],
) -> tuple[str, ...]:
    values = [item.kind for item in evidence]
    values.extend(candidate.source for candidate in candidates)
    return tuple(dict.fromkeys(values))


def _is_link_like(path: Path) -> bool:
    try:
        return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())
    except OSError:
        return True


__all__ = [
    "CodexAvailabilityState",
    "CodexDiscoveryService",
    "CodexHomeCandidate",
    "CodexHomeDiscovery",
    "CodexInstallEvidence",
    "CodexInstallationDetector",
    "CodexLinkAvailability",
    "CodexLogSourceProbe",
    "normalize_selected_codex_home",
]
