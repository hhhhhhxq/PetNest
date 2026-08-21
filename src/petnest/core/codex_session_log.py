"""只读取新增状态字段的 Codex 会话 JSONL 回退源。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
import json
from pathlib import Path
import re
from time import monotonic

from petnest.models.event import PetEvent


_SESSION_ID_IN_NAME = re.compile(
    r"([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})\.jsonl\Z",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class CodexLogSourceStatus:
    """设置页可展示但不包含会话正文的日志源状态。"""

    state: str
    message: str
    last_event_at: datetime | None = None


@dataclass(slots=True)
class _FileCursor:
    offset: int
    modified_ns: int
    session_id: str | None
    pending: bytes = b""
    compatible: bool = True


@dataclass(slots=True)
class _RecoveredTurn:
    path: Path
    session_id: str
    turn_id: str
    expires_at: float


class CodexSessionLogWatcher:
    """以固定偏移增量读取当前用户今天和前一天的 Codex JSONL。"""

    def __init__(
        self,
        root: Path,
        *,
        today: Callable[[], date] = date.today,
        global_state_path: Path | None = None,
        max_files: int = 64,
        max_read_bytes: int = 2 * 1024 * 1024,
        max_line_bytes: int = 1024 * 1024,
        monotonic_time: Callable[[], float] = monotonic,
        utc_now: Callable[[], datetime] | None = None,
        unread_stable_seconds: float = 1.0,
        startup_recovery_window_seconds: float = 120.0,
        recovered_lease_seconds: float = 300.0,
        startup_recovery_max_files: int = 8,
        startup_recovery_max_bytes: int = 2 * 1024 * 1024,
    ) -> None:
        self.root = root.expanduser().resolve()
        self._today = today
        self.global_state_path = (
            global_state_path.expanduser().resolve()
            if global_state_path is not None
            else self.root.parent / ".codex-global-state.json"
        )
        self._max_files = max(1, int(max_files))
        self._max_read_bytes = max(1024, int(max_read_bytes))
        self._max_line_bytes = max(1024, int(max_line_bytes))
        self._monotonic_time = monotonic_time
        self._utc_now = utc_now or (lambda: datetime.now(UTC))
        self._unread_stable_seconds = max(0.0, float(unread_stable_seconds))
        self._startup_recovery_window_seconds = max(
            0.0, float(startup_recovery_window_seconds)
        )
        self._recovered_lease_seconds = max(1.0, float(recovered_lease_seconds))
        self._startup_recovery_max_files = max(1, int(startup_recovery_max_files))
        self._startup_recovery_max_bytes = max(
            self._max_line_bytes, int(startup_recovery_max_bytes)
        )
        self._running = False
        self._cursors: dict[Path, _FileCursor] = {}
        self._pending_recovery_events: list[PetEvent] = []
        self._recovered_turns: dict[tuple[str, str], _RecoveredTurn] = {}
        self._unread_ids: set[str] = set()
        self._unread_baselined = False
        self._pending_unread_since: dict[str, float] = {}
        self._confirmed_unread_ids: set[str] = set()
        self._status = CodexLogSourceStatus("stopped", "本地日志回退未启动")

    @property
    def status(self) -> CodexLogSourceStatus:
        return self._status

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self) -> None:
        """从当前 EOF 建立基线，并保守恢复刚启动且明确未结束的 turn。"""
        self._running = True
        self._cursors.clear()
        self._pending_recovery_events.clear()
        self._recovered_turns.clear()
        initial_unread = self._read_unread_ids()
        self._unread_baselined = initial_unread is not None
        self._unread_ids = initial_unread or set()
        self._pending_unread_since.clear()
        self._confirmed_unread_ids.clear()
        for path in self._candidate_files():
            try:
                stat = path.stat()
            except OSError:
                continue
            self._cursors[path] = _FileCursor(
                offset=stat.st_size,
                modified_ns=stat.st_mtime_ns,
                session_id=self._session_id_from_name(path),
            )
        self._recover_recent_running_turns()
        message = "等待新的 Codex 任务" if self.root.exists() else "等待 Codex 创建本机会话目录"
        self._status = CodexLogSourceStatus("waiting", message)

    def stop(self) -> None:
        self._running = False
        self._cursors.clear()
        self._pending_recovery_events.clear()
        self._recovered_turns.clear()
        self._unread_ids.clear()
        self._unread_baselined = False
        self._pending_unread_since.clear()
        self._confirmed_unread_ids.clear()
        self._status = CodexLogSourceStatus("stopped", "本地日志回退未启动")

    def reconfigure(self, codex_home: Path) -> None:
        """Switch to one verified Codex Home and baseline its existing history."""
        home = codex_home.expanduser().resolve()
        root = home / "sessions"
        global_state_path = home / ".codex-global-state.json"
        if self.root == root and self.global_state_path == global_state_path:
            return
        was_running = self._running
        self.stop()
        self.root = root
        self.global_state_path = global_state_path
        if was_running:
            self.start()

    def poll(self) -> tuple[PetEvent, ...]:
        """读取本轮新增完整行并返回脱敏状态事件。"""
        if not self._running:
            return ()
        emitted: list[PetEvent] = list(self._pending_recovery_events)
        self._pending_recovery_events.clear()
        emitted.extend(self._poll_unread_events())
        for path in self._candidate_files():
            try:
                stat = path.stat()
            except OSError:
                continue
            cursor = self._cursors.get(path)
            if cursor is None:
                cursor = _FileCursor(0, stat.st_mtime_ns, self._session_id_from_name(path))
                self._cursors[path] = cursor
            elif stat.st_size < cursor.offset or (
                stat.st_size == cursor.offset
                and cursor.offset > 0
                and stat.st_mtime_ns != cursor.modified_ns
            ):
                cursor.offset = 0
                cursor.pending = b""
                cursor.session_id = self._session_id_from_name(path)
                cursor.compatible = True
            if stat.st_size <= cursor.offset:
                cursor.modified_ns = stat.st_mtime_ns
                continue
            try:
                with path.open("rb") as stream:
                    stream.seek(cursor.offset)
                    data = stream.read(self._max_read_bytes)
            except OSError:
                continue
            if data:
                self._refresh_recovered_turns(path)
            cursor.offset += len(data)
            cursor.modified_ns = stat.st_mtime_ns
            buffer = cursor.pending + data
            lines = buffer.split(b"\n")
            cursor.pending = b"" if buffer.endswith(b"\n") else lines.pop()
            if len(cursor.pending) > self._max_line_bytes:
                cursor.pending = b""
            for raw_line in lines:
                if not raw_line or len(raw_line) > self._max_line_bytes:
                    continue
                event = self._parse_line(path, cursor, raw_line)
                if event is not None:
                    emitted.extend(self._reconcile_recovered_turn(event, path))
                    emitted.append(event)
        emitted.extend(self._expire_recovered_turns())
        if emitted:
            now = self._utc_now()
            self._status = CodexLogSourceStatus("active", "已联动 · 本地日志回退", now)
        elif self.root.exists() and self._status.state not in {"active", "incompatible"}:
            self._status = CodexLogSourceStatus("waiting", "等待新的 Codex 任务")
        return tuple(emitted)

    def _recover_recent_running_turns(self) -> None:
        if self._startup_recovery_window_seconds <= 0:
            return
        candidates = sorted(
            self._cursors,
            key=lambda path: self._cursors[path].modified_ns,
            reverse=True,
        )[: self._startup_recovery_max_files]
        if not candidates:
            return
        per_file_bytes = max(1024, self._startup_recovery_max_bytes // len(candidates))
        total_remaining = self._startup_recovery_max_bytes
        now = self._utc_now()
        lower_bound = now - timedelta(seconds=self._startup_recovery_window_seconds)
        for path in candidates:
            if total_remaining <= 0:
                break
            cursor = self._cursors[path]
            read_limit = min(per_file_bytes, total_remaining, cursor.offset)
            total_remaining -= read_limit
            if read_limit <= 0:
                continue
            record = self._latest_lifecycle_record(path, cursor, read_limit)
            if record is None:
                continue
            event_name, session_id, turn_id, timestamp = record
            if event_name != "task_started" or not (lower_bound <= timestamp <= now):
                continue
            key = (session_id, turn_id)
            self._recovered_turns[key] = _RecoveredTurn(
                path=path,
                session_id=session_id,
                turn_id=turn_id,
                expires_at=self._monotonic_time() + self._recovered_lease_seconds,
            )
            self._pending_recovery_events.append(
                PetEvent(
                    "codex.hook",
                    source="codex-log",
                    payload={
                        "hook_event_name": "UserPromptSubmit",
                        "session_id": session_id,
                        "turn_id": turn_id,
                    },
                )
            )

    def _latest_lifecycle_record(
        self,
        path: Path,
        cursor: _FileCursor,
        read_limit: int,
    ) -> tuple[str, str, str, datetime] | None:
        if _is_link_like(path) or not _path_chain_is_safe(self.root.parent, path):
            return None
        start = max(0, cursor.offset - read_limit)
        try:
            with path.open("rb") as stream:
                stream.seek(start)
                data = stream.read(read_limit)
        except OSError:
            return None
        if data and not data.endswith(b"\n"):
            return None
        lines = data.split(b"\n")
        if start > 0 and lines:
            lines.pop(0)
        session_id = cursor.session_id or self._session_id_from_name(path)
        latest: tuple[str, str, str, datetime] | None = None
        for raw_line in lines:
            if not raw_line:
                continue
            if len(raw_line) > self._max_line_bytes:
                return None
            try:
                document = json.loads(raw_line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return None
            if not isinstance(document, dict):
                return None
            payload = document.get("payload")
            if document.get("type") == "session_meta":
                if not isinstance(payload, dict):
                    return None
                candidate_id = payload.get("session_id")
                if not _bounded_id(candidate_id):
                    return None
                session_id = str(candidate_id)
                cursor.session_id = session_id
                continue
            if document.get("type") != "event_msg":
                continue
            if not isinstance(payload, dict):
                return None
            event_name = payload.get("type")
            turn_id = payload.get("turn_id")
            if event_name not in {"task_started", "task_complete", "turn_aborted"}:
                continue
            if not _bounded_id(session_id) or not _bounded_id(turn_id):
                return None
            timestamp = _parse_timestamp(document.get("timestamp"))
            if timestamp is None:
                return None
            latest = (str(event_name), str(session_id), str(turn_id), timestamp)
        return latest

    def _refresh_recovered_turns(self, path: Path) -> None:
        expires_at = self._monotonic_time() + self._recovered_lease_seconds
        for recovered in self._recovered_turns.values():
            if recovered.path == path:
                recovered.expires_at = expires_at

    def _reconcile_recovered_turn(
        self,
        event: PetEvent,
        path: Path,
    ) -> tuple[PetEvent, ...]:
        event_name = event.payload.get("hook_event_name")
        session_id = event.payload.get("session_id")
        turn_id = event.payload.get("turn_id")
        if not isinstance(session_id, str) or not isinstance(turn_id, str):
            return ()
        key = (session_id, turn_id)
        if event_name in {"Stop", "TurnAborted"}:
            self._recovered_turns.pop(key, None)
            return ()
        if event_name != "UserPromptSubmit":
            return ()
        stale = [
            recovered_key
            for recovered_key, recovered in self._recovered_turns.items()
            if recovered.path == path and recovered_key != key
        ]
        events = tuple(
            self._recovered_abort_event(self._recovered_turns.pop(item))
            for item in stale
        )
        return events

    def _expire_recovered_turns(self) -> tuple[PetEvent, ...]:
        now = self._monotonic_time()
        expired = [
            key
            for key, value in self._recovered_turns.items()
            if value.expires_at <= now
        ]
        return tuple(
            self._recovered_abort_event(self._recovered_turns.pop(key))
            for key in expired
        )

    @staticmethod
    def _recovered_abort_event(recovered: _RecoveredTurn) -> PetEvent:
        return PetEvent(
            "codex.hook",
            source="codex-log",
            payload={
                "hook_event_name": "TurnAborted",
                "session_id": recovered.session_id,
                "turn_id": recovered.turn_id,
            },
        )

    def _poll_unread_events(self) -> tuple[PetEvent, ...]:
        current = self._read_unread_ids()
        if current is None:
            return ()
        if not self._unread_baselined:
            self._unread_ids = current
            self._pending_unread_since.clear()
            self._confirmed_unread_ids.clear()
            self._unread_baselined = True
            return ()
        now = self._monotonic_time()
        added_ids = current - self._unread_ids
        removed_ids = self._unread_ids - current
        for session_id in added_ids:
            self._pending_unread_since.setdefault(session_id, now)
        events: list[PetEvent] = []
        for session_id in removed_ids:
            self._pending_unread_since.pop(session_id, None)
            if session_id not in self._confirmed_unread_ids:
                continue
            self._confirmed_unread_ids.discard(session_id)
            events.append(
                PetEvent(
                    "codex.hook",
                    source="codex-log",
                    payload={"hook_event_name": "ThreadRead", "session_id": session_id},
                )
            )
        for session_id in tuple(self._pending_unread_since):
            if session_id not in current:
                self._pending_unread_since.pop(session_id, None)
                continue
            if now - self._pending_unread_since[session_id] < self._unread_stable_seconds:
                continue
            self._pending_unread_since.pop(session_id, None)
            self._confirmed_unread_ids.add(session_id)
            events.append(
                PetEvent(
                    "codex.hook",
                    source="codex-log",
                    payload={"hook_event_name": "ThreadUnread", "session_id": session_id},
                )
            )
        self._unread_ids = current
        events.sort(key=lambda event: str(event.payload.get("session_id", "")))
        return tuple(events)

    def _read_unread_ids(self) -> set[str] | None:
        path = self.global_state_path
        try:
            stat = path.stat()
            if not path.is_file() or _is_link_like(path) or stat.st_size > 2 * 1024 * 1024:
                return None
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        if not isinstance(document, dict):
            return None
        atoms = document.get("electron-persisted-atom-state")
        unread_by_host = atoms.get("unread-thread-ids-by-host-v1") if isinstance(atoms, dict) else None
        values = unread_by_host.get("local") if isinstance(unread_by_host, dict) else None
        if not isinstance(values, list):
            return None
        return {str(value) for value in values[:4096] if _bounded_id(value)}

    def _parse_line(self, path: Path, cursor: _FileCursor, raw_line: bytes) -> PetEvent | None:
        try:
            document = json.loads(raw_line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        if not isinstance(document, dict):
            return None
        payload = document.get("payload")
        if document.get("type") == "session_meta" and isinstance(payload, dict):
            session_id = payload.get("session_id")
            if _bounded_id(session_id):
                cursor.session_id = str(session_id)
            else:
                cursor.compatible = False
                self._status = CodexLogSourceStatus(
                    "incompatible",
                    "当前 Codex 会话日志缺少 session_id，已停止状态猜测",
                )
            return None
        if document.get("type") != "event_msg" or not isinstance(payload, dict):
            return None
        if not cursor.compatible:
            return None
        session_id = cursor.session_id or self._session_id_from_name(path)
        turn_id = payload.get("turn_id")
        event_name = payload.get("type")
        if event_name in {"task_started", "task_complete", "turn_aborted"} and not _bounded_id(turn_id):
            cursor.compatible = False
            self._status = CodexLogSourceStatus(
                "incompatible",
                f"当前 Codex 会话日志的 {event_name} 缺少 turn_id，已停止状态猜测",
            )
            return None
        if not _bounded_id(session_id) or not _bounded_id(turn_id):
            return None
        sanitized: dict[str, object] = {
            "session_id": str(session_id),
            "turn_id": str(turn_id),
        }
        if event_name == "task_started":
            sanitized["hook_event_name"] = "UserPromptSubmit"
        elif event_name == "task_complete":
            sanitized["hook_event_name"] = "Stop"
            sanitized["stop_hook_active"] = False
        elif event_name == "turn_aborted":
            sanitized["hook_event_name"] = "TurnAborted"
        else:
            return None
        return PetEvent("codex.hook", source="codex-log", payload=sanitized)

    def _candidate_files(self) -> tuple[Path, ...]:
        current = self._today()
        directories = tuple(self.root / f"{day:%Y}" / f"{day:%m}" / f"{day:%d}" for day in (current - timedelta(days=1), current))
        candidates: list[tuple[int, str, Path]] = []
        for directory in directories:
            if not _path_chain_is_safe(self.root.parent, directory) or not directory.is_dir():
                continue
            try:
                files = directory.glob("*.jsonl")
                for path in files:
                    if not path.is_file() or _is_link_like(path):
                        continue
                    stat = path.stat()
                    candidates.append((stat.st_mtime_ns, str(path).casefold(), path))
            except OSError:
                continue
        candidates.sort()
        return tuple(item[2] for item in candidates[-self._max_files :])

    @staticmethod
    def _session_id_from_name(path: Path) -> str | None:
        match = _SESSION_ID_IN_NAME.search(path.name)
        return match.group(1) if match is not None else None


def _bounded_id(value: object) -> bool:
    return isinstance(value, str) and 0 < len(value) <= 200


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or len(value) > 100:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _is_link_like(path: Path) -> bool:
    try:
        return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())
    except OSError:
        return True


def _path_chain_is_safe(root: Path, path: Path) -> bool:
    try:
        relative = path.absolute().relative_to(root.absolute())
    except ValueError:
        return False
    current = root.absolute()
    if _is_link_like(current):
        return False
    for part in relative.parts:
        current /= part
        if _is_link_like(current):
            return False
    return True


__all__ = ["CodexLogSourceStatus", "CodexSessionLogWatcher"]
