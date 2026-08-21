"""Codex Hooks 配置、脱敏本机桥接与任务状态协调。"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import secrets
import shlex
import shutil
import socket
import sys
from time import monotonic
from typing import Any


CODEX_HOOK_EVENTS = (
    "SessionStart",
    "SessionEnd",
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "PermissionRequest",
    "Stop",
)
_BRIDGE_ARGUMENT = "--codex-hook"
_METADATA_SCHEMA_VERSION = 1
_MAX_HOOK_INPUT_BYTES = 65_536


class CodexLinkError(RuntimeError):
    """联动文件不安全或不可写时中止操作。"""


@dataclass(frozen=True, slots=True)
class CodexLinkMetadata:
    """桥接子命令连接运行中 PetNest 所需的最小本机数据。"""

    token: str
    host: str
    port: int


@dataclass(frozen=True, slots=True)
class CodexHookStatus:
    """设置页可直接展示的 Hook 安装状态。"""

    state: str
    message: str
    installed: bool
    token: str | None = None


HookTransport = Callable[[str, int, bytes], object]


@dataclass(frozen=True, slots=True)
class CodexLinkSnapshot:
    """多个 Codex 任务聚合后的宠物与气泡状态。"""

    state: str = "idle"
    count: int = 0
    unread_review_count: int = 0
    message: str = ""


@dataclass(frozen=True, slots=True)
class _CodexTask:
    state: str
    unread_review: bool = False
    review_animation_pending: bool = False


class CodexLinkCoordinator:
    """把可信 Hook 事件聚合成通用 agent 事件和展示快照。"""

    _STATE_PRIORITY = ("waiting", "failed", "review", "running")
    _PET_EVENTS = {
        "idle": "agent.idle",
        "running": "agent.working",
        "waiting": "agent.waiting",
        "failed": "agent.error",
        "review": "agent.success",
    }

    def __init__(
        self,
        publish: Callable[["PetEvent"], object],
        snapshot_changed: Callable[[CodexLinkSnapshot], object] | None = None,
        *,
        monotonic_time: Callable[[], float] = monotonic,
        completed_session_ttl: float = 5.0,
    ) -> None:
        self._publish = publish
        self._snapshot_changed = snapshot_changed
        self._tasks: dict[tuple[str, str], _CodexTask] = {}
        self._active_turns: dict[str, str] = {}
        self._monotonic_time = monotonic_time
        self._completed_session_ttl = max(0.0, float(completed_session_ttl))
        self._completed_sessions: dict[str, float] = {}
        self._unread_sessions: set[str] = set()
        self._completed_turns: set[tuple[str, str]] = set()
        self._completed_turn_order: deque[tuple[str, str]] = deque()
        self._max_completed_turns = 4096
        self._snapshot = CodexLinkSnapshot()

    @property
    def snapshot(self) -> CodexLinkSnapshot:
        return self._snapshot

    def consume(self, event: "PetEvent") -> bool:
        """处理一条已鉴权事件；无效来源和缺失标识不会改变状态。"""
        if event.event_name != "codex.hook" or event.source not in {"codex-hook", "codex-log"}:
            return False
        payload = event.payload
        hook_name = payload.get("hook_event_name")
        session_id = _bounded_identifier(payload.get("session_id"))
        turn_id = _bounded_identifier(payload.get("turn_id"))
        if session_id is None:
            return False
        self._prune_completed_sessions()
        if (
            hook_name == "UserPromptSubmit"
            and turn_id is not None
            and (session_id, turn_id) in self._completed_turns
        ):
            return True
        if hook_name == "ThreadUnread" and event.source == "codex-log":
            changed = session_id not in self._unread_sessions
            self._unread_sessions.add(session_id)
            review_found = False
            for key, task in tuple(self._tasks.items()):
                if key[0] != session_id or task.state != "review":
                    continue
                review_found = True
                if not task.unread_review:
                    changed = True
                    self._tasks[key] = _CodexTask("review", True, task.review_animation_pending)
            if session_id in self._completed_sessions and not review_found:
                changed = True
                self._tasks[(session_id, "__unread__")] = _CodexTask("review", True, False)
            if changed:
                self._emit_snapshot()
            return changed
        if hook_name == "ThreadRead" and event.source == "codex-log":
            removed = session_id in self._unread_sessions or session_id in self._completed_sessions
            self._unread_sessions.discard(session_id)
            self._completed_sessions.pop(session_id, None)
            for key, task in tuple(self._tasks.items()):
                if key[0] == session_id and task.state == "review":
                    removed = True
                    del self._tasks[key]
                    if self._active_turns.get(session_id) == key[1]:
                        self._active_turns.pop(session_id, None)
            if removed:
                self._emit_snapshot()
            return removed
        if hook_name == "TurnAborted" and event.source == "codex-log":
            active_turn = turn_id or self._active_turns.get(session_id) or "__session__"
            removed = self._tasks.pop((session_id, active_turn), None) is not None
            if self._active_turns.get(session_id) == active_turn:
                self._active_turns.pop(session_id, None)
            if removed:
                self._emit_snapshot()
            return removed
        if hook_name not in CODEX_HOOK_EVENTS:
            return False
        if hook_name == "SessionStart":
            return True
        if hook_name == "SessionEnd":
            removed = session_id in self._unread_sessions or session_id in self._completed_sessions
            self._unread_sessions.discard(session_id)
            self._completed_sessions.pop(session_id, None)
            for key in tuple(self._tasks):
                if key[0] == session_id:
                    removed = True
                    del self._tasks[key]
            if removed:
                self._active_turns.pop(session_id, None)
                self._emit_snapshot()
            return removed
        provisional_key = (session_id, "__session__")
        if hook_name == "UserPromptSubmit":
            self._unread_sessions.discard(session_id)
            self._completed_sessions.pop(session_id, None)
            for old_key, old_task in tuple(self._tasks.items()):
                if old_key[0] == session_id and old_task.state == "review":
                    del self._tasks[old_key]
        if turn_id is not None:
            key = (session_id, turn_id)
            if hook_name == "UserPromptSubmit":
                for old_key in tuple(self._tasks):
                    if old_key[0] == session_id and old_key not in {key, provisional_key}:
                        del self._tasks[old_key]
            provisional = self._tasks.pop(provisional_key, None)
            if provisional is not None and key not in self._tasks:
                self._tasks[key] = provisional
            self._active_turns[session_id] = turn_id
        else:
            active_turn = self._active_turns.get(session_id)
            active_task = self._tasks.get((session_id, active_turn)) if active_turn is not None else None
            # 新一轮 UserPromptSubmit 可能早于 JSONL task_started。上一轮已
            # review 时先放进 provisional，日志 turn 到达后再迁移；若日志
            # 已先标记 running，则直接复用真实 turn，避免重复任务。
            if hook_name == "UserPromptSubmit" and (active_task is None or active_task.state != "running"):
                key = provisional_key
            else:
                key = (session_id, active_turn or "__session__")
        if hook_name == "Stop" and payload.get("stop_hook_active") is True:
            return False
        if hook_name == "Stop":
            completion_key = (session_id, key[1])
            if not self._remember_completed_turn(completion_key):
                return True
            self._completed_sessions[session_id] = self._monotonic_time()
            task = _CodexTask(
                "review",
                session_id in self._unread_sessions,
                True,
            )
        elif hook_name == "PermissionRequest":
            task = _CodexTask("waiting")
        elif hook_name == "PostToolUse" and payload.get("tool_failed") is True:
            task = _CodexTask("failed")
        else:
            task = _CodexTask("running")
        self._tasks[key] = task
        self._emit_snapshot()
        return True

    def mark_reviews_read(self) -> None:
        """只清除未读徽标，不改变 review 动作状态。"""
        changed = bool(self._unread_sessions)
        for session_id in self._unread_sessions:
            self._completed_sessions.pop(session_id, None)
        self._unread_sessions.clear()
        for key, task in tuple(self._tasks.items()):
            if task.unread_review:
                changed = True
                if task.state == "review" and not task.review_animation_pending:
                    del self._tasks[key]
                else:
                    self._tasks[key] = _CodexTask(
                        task.state,
                        False,
                        task.review_animation_pending,
                    )
        if changed:
            self._emit_snapshot(publish_pet_event=False)

    def finish_review_animation(self) -> None:
        """结束一次完成动画；仅保留已被 Codex 确认未读的徽标状态。"""
        changed = False
        for key, task in tuple(self._tasks.items()):
            if task.state != "review" or not task.review_animation_pending:
                continue
            changed = True
            if task.unread_review:
                self._tasks[key] = _CodexTask("review", True, False)
            else:
                del self._tasks[key]
                if self._active_turns.get(key[0]) == key[1]:
                    self._active_turns.pop(key[0], None)
        if changed:
            self._emit_snapshot(pet_event_priority=100)

    def dismiss_reviews(self) -> None:
        """确认并移除 review 任务，恢复剩余任务或输入上下文。"""
        removed = False
        for key, task in tuple(self._tasks.items()):
            if task.state == "review":
                removed = True
                del self._tasks[key]
                self._unread_sessions.discard(key[0])
                self._completed_sessions.pop(key[0], None)
                if self._active_turns.get(key[0]) == key[1]:
                    self._active_turns.pop(key[0], None)
        if removed:
            self._emit_snapshot()

    def clear(self) -> None:
        """关闭联动时清空所有任务并恢复宠物上下文。"""
        if (
            not self._tasks
            and not self._completed_sessions
            and not self._unread_sessions
            and self._snapshot.state == "idle"
        ):
            return
        self._tasks.clear()
        self._active_turns.clear()
        self._completed_sessions.clear()
        self._unread_sessions.clear()
        self._completed_turns.clear()
        self._completed_turn_order.clear()
        self._emit_snapshot()

    def _remember_completed_turn(self, key: tuple[str, str]) -> bool:
        if key in self._completed_turns:
            return False
        self._completed_turns.add(key)
        self._completed_turn_order.append(key)
        while len(self._completed_turn_order) > self._max_completed_turns:
            expired = self._completed_turn_order.popleft()
            self._completed_turns.discard(expired)
        return True

    def _prune_completed_sessions(self) -> None:
        cutoff = self._monotonic_time() - self._completed_session_ttl
        for session_id, completed_at in tuple(self._completed_sessions.items()):
            if completed_at < cutoff and session_id not in self._unread_sessions:
                self._completed_sessions.pop(session_id, None)

    def _emit_snapshot(
        self,
        *,
        publish_pet_event: bool = True,
        pet_event_priority: int = 90,
    ) -> None:
        snapshot = self._aggregate()
        if snapshot == self._snapshot:
            return
        previous_state = self._snapshot.state
        self._snapshot = snapshot
        if publish_pet_event and snapshot.state != previous_state:
            from petnest.models.event import PetEvent

            self._publish(
                PetEvent(
                    self._PET_EVENTS[snapshot.state],
                    source="codex-link",
                    priority=pet_event_priority,
                )
            )
        if self._snapshot_changed is not None:
            self._snapshot_changed(snapshot)

    def _aggregate(self) -> CodexLinkSnapshot:
        if not self._tasks:
            return CodexLinkSnapshot()
        states = tuple(
            task.state
            for task in self._tasks.values()
            if task.state != "review" or task.review_animation_pending
        )
        state = next(
            (candidate for candidate in self._STATE_PRIORITY if candidate in states),
            "idle",
        )
        count = states.count(state) if state != "idle" else 0
        unread = sum(task.unread_review for task in self._tasks.values())
        message_state = "review" if unread and state in {"idle", "running"} else state
        message_count = unread if message_state == "review" and state != "review" else count
        return CodexLinkSnapshot(
            state,
            count,
            unread,
            _snapshot_message(message_state, message_count),
        )


class CodexHookManager:
    """只合并和移除 PetNest 自己的用户级 Codex Hook。"""

    def __init__(
        self,
        codex_home: Path | None,
        data_dir: Path,
        *,
        port: int,
        command_prefix: tuple[str, ...] | None = None,
    ) -> None:
        self.codex_home = (codex_home or Path.home() / ".codex").expanduser().resolve()
        self.data_dir = data_dir.expanduser().resolve()
        self.hooks_path = self.codex_home / "hooks.json"
        self.metadata_path = self.data_dir / "codex-link.json"
        self.port = _valid_port(port)
        self._command_prefix = command_prefix or _default_command_prefix()

    def inspect(self) -> CodexHookStatus:
        """只读检查 PetNest handlers 是否完整，不修改任何文件。"""
        if not self.hooks_path.exists():
            return CodexHookStatus("missing", "尚未安装 PetNest Codex Hook", False)
        try:
            document = self._read_hooks()
        except CodexLinkError as error:
            return CodexHookStatus("error", str(error), False)
        installed_events = {
            event_name
            for event_name, groups in _hook_events(document).items()
            if _contains_petnest_handler(groups)
        }
        complete = installed_events == set(CODEX_HOOK_EVENTS)
        if not complete:
            return CodexHookStatus("partial", "PetNest Codex Hook 不完整，可点击安装/修复", False)
        try:
            token = self._read_metadata().token if self.metadata_path.exists() else None
        except CodexLinkError as error:
            return CodexHookStatus("error", str(error), False)
        return CodexHookStatus(
            "installed",
            "Hook 已安装；如需精确联动，请在 Codex 设置 → 钩子 → 用户配置中审核",
            True,
            token,
        )

    def set_port(self, port: int) -> None:
        """端口设置变化时刷新后续元数据写入目标。"""
        self.port = _valid_port(port)

    def set_codex_home(self, codex_home: Path) -> None:
        """切换当前 profile 的 Hook 配置，不移动 PetNest 私有元数据。"""
        resolved = codex_home.expanduser().resolve()
        self.codex_home = resolved
        self.hooks_path = resolved / "hooks.json"

    def install(self) -> CodexHookStatus:
        """结构化合并全部 PetNest Hook；已有配置无法解析时绝不覆盖。"""
        document = self._read_hooks() if self.hooks_path.exists() else {"hooks": {}}
        metadata = self.ensure_metadata()
        hooks = document.setdefault("hooks", {})
        if not isinstance(hooks, dict):
            raise CodexLinkError("Codex hooks.json 的 hooks 字段不是对象，未做任何修改")
        for event_name in CODEX_HOOK_EVENTS:
            existing = hooks.get(event_name, [])
            if not isinstance(existing, list):
                raise CodexLinkError(f"Codex hooks.json 的 {event_name} 字段不是数组，未做任何修改")
            cleaned = _remove_petnest_handlers(existing)
            cleaned.append({"matcher": "", "hooks": [self._handler(event_name)]})
            hooks[event_name] = cleaned
        self._write_hooks(document)
        return CodexHookStatus(
            "installed",
            "Hook 已安装；请在 Codex 设置 → 钩子 → 用户配置中检查并信任",
            True,
            metadata.token,
        )

    def remove(self) -> CodexHookStatus:
        """仅移除命令中带 PetNest 桥接参数的 handlers。"""
        if not self.hooks_path.exists():
            return CodexHookStatus("missing", "没有已安装的 PetNest Codex Hook", False)
        document = self._read_hooks()
        hooks = document.get("hooks")
        if not isinstance(hooks, dict):
            raise CodexLinkError("Codex hooks.json 的 hooks 字段不是对象，未做任何修改")
        for event_name in tuple(hooks):
            groups = hooks[event_name]
            if not isinstance(groups, list):
                continue
            cleaned = _remove_petnest_handlers(groups)
            if cleaned:
                hooks[event_name] = cleaned
            elif _contains_petnest_handler(groups):
                del hooks[event_name]
        self._write_hooks(document)
        return CodexHookStatus("missing", "已移除 PetNest Codex Hook", False)

    def ensure_metadata(self) -> CodexLinkMetadata:
        """生成或刷新端口，同时保持每次安装的随机令牌稳定。"""
        if self.metadata_path.exists():
            current = self._read_metadata()
            metadata = CodexLinkMetadata(current.token, "127.0.0.1", self.port)
        else:
            metadata = CodexLinkMetadata(secrets.token_urlsafe(32), "127.0.0.1", self.port)
        _atomic_write_json(
            self.metadata_path,
            {
                "schema_version": _METADATA_SCHEMA_VERSION,
                "token": metadata.token,
                "host": metadata.host,
                "port": metadata.port,
            },
        )
        return metadata

    def _read_hooks(self) -> dict[str, Any]:
        try:
            raw = json.loads(self.hooks_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise CodexLinkError(f"无法解析 Codex hooks.json，未做任何修改：{error}") from error
        if not isinstance(raw, dict):
            raise CodexLinkError("无法解析 Codex hooks.json：根节点必须是对象")
        return raw

    def _read_metadata(self) -> CodexLinkMetadata:
        try:
            raw = json.loads(self.metadata_path.read_text(encoding="utf-8"))
            token = raw["token"]
            host = raw["host"]
            port = raw["port"]
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as error:
            raise CodexLinkError(f"无法读取 Codex 联动元数据：{error}") from error
        if (
            raw.get("schema_version") != _METADATA_SCHEMA_VERSION
            or not isinstance(token, str)
            or len(token) < 43
            or host != "127.0.0.1"
        ):
            raise CodexLinkError("Codex 联动元数据无效")
        return CodexLinkMetadata(token, host, _valid_port(port))

    def _handler(self, event_name: str) -> dict[str, object]:
        arguments = (*self._command_prefix, _BRIDGE_ARGUMENT, str(self.metadata_path))
        return {
            "type": "command",
            "command": shlex.join(arguments),
            # Codex Desktop 在 Windows 上通过 PowerShell `-Command` 执行
            # commandWindows。带空格的可执行路径必须使用调用运算符 &；
            # subprocess.list2cmdline 生成的是 cmd.exe 语法，会被当成
            # 普通字符串而不启动进程。
            "commandWindows": _powershell_command(arguments),
            "timeout": 3 if event_name == "SessionEnd" else 5,
            "async": False,
            "statusMessage": "同步 PetNest 宠物状态",
        }

    def handler_for(self, event_name: str) -> dict[str, object]:
        """为用户 Hook 或插件生成相同的本机桥接命令。"""
        if event_name not in CODEX_HOOK_EVENTS:
            raise CodexLinkError(f"不支持的 Codex Hook 事件：{event_name}")
        return self._handler(event_name)

    def _write_hooks(self, document: dict[str, Any]) -> None:
        self.hooks_path.parent.mkdir(parents=True, exist_ok=True)
        if self.hooks_path.exists():
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
            backup = self.hooks_path.with_name(f"{self.hooks_path.name}.petnest-{stamp}.bak")
            try:
                shutil.copy2(self.hooks_path, backup)
            except OSError as error:
                raise CodexLinkError(f"无法备份 Codex hooks.json，未做任何修改：{error}") from error
        try:
            _atomic_write_json(self.hooks_path, document)
        except OSError as error:
            raise CodexLinkError(f"无法写入 Codex hooks.json：{error}") from error


def forward_codex_hook(
    metadata_path: Path,
    raw_input: bytes,
    *,
    transport: HookTransport | None = None,
) -> bool:
    """把 Hook 标准输入裁剪成状态字段并快速发送给运行中的 PetNest。"""
    if len(raw_input) > _MAX_HOOK_INPUT_BYTES:
        return False
    try:
        raw = json.loads(raw_input.decode("utf-8"))
        metadata_raw = json.loads(metadata_path.expanduser().resolve().read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    if not isinstance(raw, Mapping) or not isinstance(metadata_raw, Mapping):
        return False
    try:
        metadata = _metadata_from_mapping(metadata_raw)
    except CodexLinkError:
        return False
    payload = _sanitized_hook_payload(raw)
    if payload is None:
        return False
    message = {
        "event": "codex.hook",
        "source": "codex-hook",
        "token": metadata.token,
        "payload": payload,
    }
    body = (json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    try:
        (transport or _send_json_line)(metadata.host, metadata.port, body)
    except OSError:
        return False
    return True


def _sanitized_hook_payload(raw: Mapping[str, object]) -> dict[str, object] | None:
    event_name = raw.get("hook_event_name")
    if event_name not in CODEX_HOOK_EVENTS:
        return None
    payload: dict[str, object] = {"hook_event_name": str(event_name)}
    for name in ("session_id", "turn_id", "tool_name"):
        value = raw.get(name)
        if isinstance(value, str) and 0 < len(value) <= 200:
            payload[name] = value
    stop_hook_active = raw.get("stop_hook_active")
    if isinstance(stop_hook_active, bool):
        payload["stop_hook_active"] = stop_hook_active
    failed = raw.get("tool_failed")
    response = raw.get("tool_response")
    if isinstance(failed, bool):
        payload["tool_failed"] = failed
    elif isinstance(response, Mapping):
        if response.get("success") is False or bool(response.get("error")):
            payload["tool_failed"] = True
        elif response.get("success") is True:
            payload["tool_failed"] = False
    return payload


def _send_json_line(host: str, port: int, body: bytes) -> None:
    with socket.create_connection((host, port), timeout=0.25) as connection:
        connection.settimeout(0.25)
        connection.sendall(body)


def _metadata_from_mapping(raw: Mapping[str, object]) -> CodexLinkMetadata:
    token = raw.get("token")
    host = raw.get("host")
    port = raw.get("port")
    if (
        raw.get("schema_version") != _METADATA_SCHEMA_VERSION
        or not isinstance(token, str)
        or len(token) < 43
        or host != "127.0.0.1"
    ):
        raise CodexLinkError("Codex 联动元数据无效")
    return CodexLinkMetadata(token, host, _valid_port(port))


def _valid_port(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 65_535:
        raise CodexLinkError("Codex 联动端口必须介于 1 和 65535")
    return value


def _bounded_identifier(value: object) -> str | None:
    if not isinstance(value, str) or not 0 < len(value) <= 200:
        return None
    return value


def _snapshot_message(state: str, count: int) -> str:
    if state == "waiting":
        return "Codex 正在等待你处理" if count == 1 else f"{count} 个 Codex 任务等待你处理"
    if state == "failed":
        return "Codex 执行遇到问题" if count == 1 else f"{count} 个 Codex 任务执行遇到问题"
    if state == "review":
        return "Codex 任务已完成，等待查看" if count == 1 else f"{count} 个 Codex 任务已完成，等待查看"
    if state == "running":
        return "Codex 正在运行" if count == 1 else f"{count} 个 Codex 任务正在运行"
    return ""


def _default_command_prefix() -> tuple[str, ...]:
    if getattr(sys, "frozen", False):
        return (str(Path(sys.executable).resolve()),)
    return (str(Path(sys.executable).resolve()), "-m", "petnest")


def _powershell_command(arguments: tuple[str, ...]) -> str:
    """生成可直接交给 PowerShell ``-Command`` 的安全参数表达式。"""
    quoted = " ".join("'" + argument.replace("'", "''") + "'" for argument in arguments)
    return f"& {quoted}"


def _hook_events(document: Mapping[str, object]) -> Mapping[str, object]:
    hooks = document.get("hooks", {})
    return hooks if isinstance(hooks, Mapping) else {}


def _is_petnest_handler(handler: object) -> bool:
    if not isinstance(handler, Mapping):
        return False
    command = f"{handler.get('command', '')} {handler.get('commandWindows', '')}"
    return _BRIDGE_ARGUMENT in command


def _contains_petnest_handler(groups: object) -> bool:
    if not isinstance(groups, list):
        return False
    return any(
        isinstance(group, Mapping)
        and isinstance(group.get("hooks"), list)
        and any(_is_petnest_handler(handler) for handler in group["hooks"])
        for group in groups
    )


def _remove_petnest_handlers(groups: list[object]) -> list[object]:
    cleaned: list[object] = []
    for group in groups:
        if not isinstance(group, Mapping) or not isinstance(group.get("hooks"), list):
            cleaned.append(group)
            continue
        handlers = [handler for handler in group["hooks"] if not _is_petnest_handler(handler)]
        if handlers:
            copied = dict(group)
            copied["hooks"] = handlers
            cleaned.append(copied)
    return cleaned


def _atomic_write_json(path: Path, document: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    contents = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    try:
        temporary.write_text(contents, encoding="utf-8")
        with temporary.open("r+", encoding="utf-8") as stream:
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


__all__ = [
    "CODEX_HOOK_EVENTS",
    "CodexHookManager",
    "CodexHookStatus",
    "CodexLinkCoordinator",
    "CodexLinkError",
    "CodexLinkMetadata",
    "CodexLinkSnapshot",
    "forward_codex_hook",
]
