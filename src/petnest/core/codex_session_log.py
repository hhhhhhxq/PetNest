"""只读取新增状态字段的 Codex 会话 JSONL 回退源。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
import json
from pathlib import Path
import re

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


class CodexSessionLogWatcher:
    """以固定偏移增量读取当前用户今天和前一天的 Codex JSONL。"""

    def __init__(
        self,
        root: Path,
        *,
        today: Callable[[], date] = date.today,
        max_files: int = 64,
        max_read_bytes: int = 2 * 1024 * 1024,
        max_line_bytes: int = 1024 * 1024,
    ) -> None:
        self.root = root.expanduser().resolve()
        self._today = today
        self._max_files = max(1, int(max_files))
        self._max_read_bytes = max(1024, int(max_read_bytes))
        self._max_line_bytes = max(1024, int(max_line_bytes))
        self._running = False
        self._cursors: dict[Path, _FileCursor] = {}
        self._status = CodexLogSourceStatus("stopped", "本地日志回退未启动")

    @property
    def status(self) -> CodexLogSourceStatus:
        return self._status

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self) -> None:
        """从当前 EOF 建立基线，绝不把历史 turn 当成新状态。"""
        self._running = True
        self._cursors.clear()
        for path in self._candidate_files():
            try:
                stat = path.stat()
            except OSError:
                continue
            self._cursors[path] = _FileCursor(
                offset=stat.st_size,
                modified_ns=stat.st_mtime_ns,
                session_id=self._session_id(path),
            )
        message = "等待新的 Codex 任务" if self.root.exists() else "等待 Codex 创建本机会话目录"
        self._status = CodexLogSourceStatus("waiting", message)

    def stop(self) -> None:
        self._running = False
        self._cursors.clear()
        self._status = CodexLogSourceStatus("stopped", "本地日志回退未启动")

    def poll(self) -> tuple[PetEvent, ...]:
        """读取本轮新增完整行并返回脱敏状态事件。"""
        if not self._running:
            return ()
        emitted: list[PetEvent] = []
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
                    emitted.append(event)
        if emitted:
            now = datetime.now(UTC)
            self._status = CodexLogSourceStatus("active", "已联动 · 本地日志回退", now)
        elif self.root.exists() and self._status.state not in {"active", "incompatible"}:
            self._status = CodexLogSourceStatus("waiting", "等待新的 Codex 任务")
        return tuple(emitted)

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
        if not _bounded_id(session_id) or not _bounded_id(turn_id):
            return None
        event_name = payload.get("type")
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
            sanitized["hook_event_name"] = "PostToolUse"
            sanitized["tool_failed"] = True
        else:
            return None
        return PetEvent("codex.hook", source="codex-log", payload=sanitized)

    def _candidate_files(self) -> tuple[Path, ...]:
        current = self._today()
        directories = tuple(self.root / f"{day:%Y}" / f"{day:%m}" / f"{day:%d}" for day in (current - timedelta(days=1), current))
        candidates: list[Path] = []
        for directory in directories:
            if not directory.is_dir() or directory.is_symlink():
                continue
            try:
                files = directory.glob("*.jsonl")
                candidates.extend(path for path in files if path.is_file() and not path.is_symlink())
            except OSError:
                continue
        candidates.sort(key=lambda item: str(item).casefold())
        return tuple(candidates[-self._max_files :])

    def _session_id(self, path: Path) -> str | None:
        from_name = self._session_id_from_name(path)
        if from_name is not None:
            return from_name
        try:
            with path.open("rb") as stream:
                raw_line = stream.readline(self._max_line_bytes + 1)
            if len(raw_line) > self._max_line_bytes:
                return None
            document = json.loads(raw_line.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        payload = document.get("payload") if isinstance(document, dict) else None
        session_id = payload.get("session_id") if document.get("type") == "session_meta" and isinstance(payload, dict) else None
        return str(session_id) if _bounded_id(session_id) else None

    @staticmethod
    def _session_id_from_name(path: Path) -> str | None:
        match = _SESSION_ID_IN_NAME.search(path.name)
        return match.group(1) if match is not None else None


def _bounded_id(value: object) -> bool:
    return isinstance(value, str) and 0 < len(value) <= 200


__all__ = ["CodexLogSourceStatus", "CodexSessionLogWatcher"]
