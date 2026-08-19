"""Codex Hooks 安装、脱敏桥接与任务状态聚合。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from petnest.core.codex_link import (
    CodexHookManager,
    CodexLinkError,
    forward_codex_hook,
)


def _manager(tmp_path: Path) -> CodexHookManager:
    return CodexHookManager(
        tmp_path / "codex-home",
        tmp_path / "petnest-data",
        port=18486,
        command_prefix=(r"C:\Program Files\PetNest\PetNest.exe",),
    )


def _petnest_handlers(document: dict[str, object]) -> list[dict[str, object]]:
    handlers: list[dict[str, object]] = []
    hooks = document.get("hooks", {})
    assert isinstance(hooks, dict)
    for groups in hooks.values():
        if not isinstance(groups, list):
            continue
        for group in groups:
            if isinstance(group, dict) and isinstance(group.get("hooks"), list):
                handlers.extend(
                    handler
                    for handler in group["hooks"]
                    if isinstance(handler, dict) and "--codex-hook" in str(handler.get("commandWindows", ""))
                )
    return handlers


def test_install_creates_all_hook_events_and_stable_metadata(tmp_path: Path) -> None:
    manager = _manager(tmp_path)

    first = manager.install()
    first_document = json.loads(manager.hooks_path.read_text(encoding="utf-8"))
    second = manager.install()
    second_document = json.loads(manager.hooks_path.read_text(encoding="utf-8"))

    assert first.installed and second.installed
    assert first.token == second.token
    assert first_document == second_document
    assert set(first_document["hooks"]) == {
        "SessionStart",
        "SessionEnd",
        "UserPromptSubmit",
        "PreToolUse",
        "PostToolUse",
        "PermissionRequest",
        "Stop",
    }
    assert len(_petnest_handlers(first_document)) == 7
    handler = _petnest_handlers(first_document)[0]
    assert handler["type"] == "command"
    assert handler["timeoutSec"] == 5
    assert handler["async"] is True
    assert "--codex-hook" in str(handler["commandWindows"])
    assert first.token is not None and len(first.token) >= 43


def test_install_preserves_unknown_fields_and_unrelated_hooks(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    manager.hooks_path.parent.mkdir(parents=True)
    original_handler = {"type": "command", "command": "keep-me", "timeoutSec": 9}
    manager.hooks_path.write_text(
        json.dumps(
            {
                "custom": {"future": True},
                "hooks": {
                    "Stop": [{"matcher": "keep", "hooks": [original_handler]}],
                    "FutureEvent": [{"matcher": "", "hooks": [{"type": "prompt"}]}],
                },
            }
        ),
        encoding="utf-8",
    )

    manager.install()
    installed = json.loads(manager.hooks_path.read_text(encoding="utf-8"))

    assert installed["custom"] == {"future": True}
    assert installed["hooks"]["Stop"][0]["hooks"][0] == original_handler
    assert installed["hooks"]["FutureEvent"] == [{"matcher": "", "hooks": [{"type": "prompt"}]}]
    assert list(manager.hooks_path.parent.glob("hooks.json.petnest-*.bak"))


def test_remove_deletes_only_petnest_handlers_and_keeps_metadata(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    manager.install()
    document = json.loads(manager.hooks_path.read_text(encoding="utf-8"))
    document["hooks"]["Stop"].insert(0, {"matcher": "", "hooks": [{"type": "command", "command": "keep-me"}]})
    manager.hooks_path.write_text(json.dumps(document), encoding="utf-8")
    token = manager.ensure_metadata().token

    removed = manager.remove()
    remaining = json.loads(manager.hooks_path.read_text(encoding="utf-8"))

    assert removed.installed is False
    assert _petnest_handlers(remaining) == []
    assert remaining["hooks"]["Stop"] == [{"matcher": "", "hooks": [{"type": "command", "command": "keep-me"}]}]
    assert manager.ensure_metadata().token == token


def test_invalid_hooks_json_is_never_overwritten(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    manager.hooks_path.parent.mkdir(parents=True)
    manager.hooks_path.write_text("{ broken", encoding="utf-8")

    with pytest.raises(CodexLinkError, match="无法解析"):
        manager.install()

    assert manager.hooks_path.read_text(encoding="utf-8") == "{ broken"
    assert not list(manager.hooks_path.parent.glob("hooks.json.petnest-*.bak"))


def test_forward_codex_hook_sends_only_allowlisted_status_fields(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    metadata = manager.ensure_metadata()
    sent: list[tuple[str, int, bytes]] = []
    raw = json.dumps(
        {
            "hook_event_name": "PermissionRequest",
            "session_id": "session-1",
            "turn_id": "turn-1",
            "tool_name": "shell",
            "prompt": "private prompt",
            "last_assistant_message": "private answer",
            "tool_input": {"command": "private command"},
        }
    ).encode()

    assert forward_codex_hook(manager.metadata_path, raw, transport=lambda host, port, body: sent.append((host, port, body)))

    host, port, body = sent[0]
    payload = json.loads(body)
    assert (host, port) == ("127.0.0.1", 18486)
    assert payload["event"] == "codex.hook"
    assert payload["source"] == "codex-hook"
    assert payload["token"] == metadata.token
    assert payload["payload"] == {
        "hook_event_name": "PermissionRequest",
        "session_id": "session-1",
        "turn_id": "turn-1",
        "tool_name": "shell",
    }
    assert b"private" not in body


def test_forward_codex_hook_rejects_malformed_or_oversized_input_without_sending(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    manager.ensure_metadata()
    sent: list[bytes] = []
    transport = lambda _host, _port, body: sent.append(body)

    assert not forward_codex_hook(manager.metadata_path, b"{ broken", transport=transport)
    assert not forward_codex_hook(manager.metadata_path, b"x" * 70_000, transport=transport)
    assert sent == []
