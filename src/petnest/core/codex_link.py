"""Codex Hooks 配置、脱敏本机桥接与任务状态协调。"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
import hmac
import json
import os
from pathlib import Path
import secrets
import shlex
import shutil
import socket
import subprocess
import sys
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
        token = self._read_metadata().token if self.metadata_path.exists() else None
        return CodexHookStatus(
            "installed",
            "Hook 已安装；首次使用请在 Codex /hooks 中确认信任",
            True,
            token,
        )

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
            cleaned.append({"matcher": "", "hooks": [self._handler()]})
            hooks[event_name] = cleaned
        self._write_hooks(document)
        return CodexHookStatus(
            "installed",
            "Hook 已安装；请在 Codex /hooks 中检查并信任 PetNest Hook",
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

    def _handler(self) -> dict[str, object]:
        arguments = (*self._command_prefix, _BRIDGE_ARGUMENT, str(self.metadata_path))
        return {
            "type": "command",
            "command": shlex.join(arguments),
            "commandWindows": subprocess.list2cmdline(arguments),
            "timeoutSec": 5,
            "async": True,
            "statusMessage": "同步 PetNest 宠物状态",
        }

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


def _default_command_prefix() -> tuple[str, ...]:
    if getattr(sys, "frozen", False):
        return (str(Path(sys.executable).resolve()),)
    return (str(Path(sys.executable).resolve()), "-m", "petnest")


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
    "CodexLinkError",
    "CodexLinkMetadata",
    "forward_codex_hook",
]
