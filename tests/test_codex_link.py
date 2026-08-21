"""Codex Hooks 安装、脱敏桥接与任务状态聚合。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from petnest.core.codex_link import (
    CodexHookManager,
    CodexLinkCoordinator,
    CodexLinkError,
    forward_codex_hook,
)
from petnest.models.event import PetEvent


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
    assert handler["timeout"] == 5
    assert handler["async"] is False
    assert "timeoutSec" not in handler
    assert "--codex-hook" in str(handler["commandWindows"])
    assert str(handler["commandWindows"]).startswith("& ")
    assert "'C:\\Program Files\\PetNest\\PetNest.exe'" in str(handler["commandWindows"])
    assert first_document["hooks"]["SessionEnd"][-1]["hooks"][0]["timeout"] == 3
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


def test_inspect_reports_invalid_metadata_without_raising(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    manager.install()
    manager.metadata_path.write_text("{ broken", encoding="utf-8")

    status = manager.inspect()

    assert status.state == "error"
    assert status.installed is False
    assert "无法读取 Codex 联动元数据" in status.message


def test_hook_manager_can_switch_codex_home_without_moving_petnest_metadata(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    original_metadata_path = manager.metadata_path
    second = tmp_path / "second-codex-home"

    manager.set_codex_home(second)

    assert manager.codex_home == second.resolve()
    assert manager.hooks_path == second.resolve() / "hooks.json"
    assert manager.metadata_path == original_metadata_path


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


def _hook(event_name: str, session: str = "s1", turn: str | None = "t1", **payload: object) -> PetEvent:
    values: dict[str, object] = {"hook_event_name": event_name, "session_id": session, **payload}
    if turn is not None:
        values["turn_id"] = turn
    return PetEvent("codex.hook", source="codex-hook", payload=values)


def _log(event_name: str, session: str = "s1", turn: str = "t1", **payload: object) -> PetEvent:
    values: dict[str, object] = {
        "hook_event_name": event_name,
        "session_id": session,
        "turn_id": turn,
        **payload,
    }
    return PetEvent("codex.hook", source="codex-log", payload=values)


def test_coordinator_maps_running_waiting_and_review_to_pet_events() -> None:
    published: list[PetEvent] = []
    snapshots = []
    coordinator = CodexLinkCoordinator(published.append, snapshots.append)

    assert coordinator.consume(_hook("UserPromptSubmit"))
    assert coordinator.snapshot.state == "running"
    assert published[-1].event_name == "agent.working"

    assert coordinator.consume(_hook("PermissionRequest"))
    assert coordinator.snapshot.state == "waiting"
    assert coordinator.snapshot.message == "Codex 正在等待你处理"
    assert published[-1].event_name == "agent.waiting"

    assert coordinator.consume(_hook("Stop"))
    assert coordinator.snapshot.state == "review"
    assert coordinator.snapshot.message == "Codex 任务已完成，等待查看"
    assert coordinator.snapshot.unread_review_count == 0
    assert published[-1].event_name == "agent.success"
    assert snapshots[-1] == coordinator.snapshot

    assert coordinator.consume(_log("ThreadUnread"))
    assert coordinator.snapshot.unread_review_count == 1


def test_coordinator_uses_session_when_codex_omits_turn_id() -> None:
    published: list[PetEvent] = []
    coordinator = CodexLinkCoordinator(published.append)

    assert coordinator.consume(_hook("UserPromptSubmit", turn=None))
    assert coordinator.snapshot.state == "running"
    assert published[-1].event_name == "agent.working"

    assert coordinator.consume(_hook("PermissionRequest", turn=None))
    assert coordinator.snapshot.state == "waiting"
    assert published[-1].event_name == "agent.waiting"

    assert coordinator.consume(_hook("Stop", turn=None))
    assert coordinator.snapshot.state == "review"
    assert published[-1].event_name == "agent.success"


def test_log_turn_and_hook_without_turn_are_merged_into_one_task() -> None:
    published: list[PetEvent] = []
    coordinator = CodexLinkCoordinator(published.append)

    assert coordinator.consume(_log("UserPromptSubmit"))
    assert coordinator.snapshot.state == "running"

    assert coordinator.consume(_hook("PermissionRequest", turn=None))
    assert coordinator.snapshot.state == "waiting"
    assert coordinator.snapshot.count == 1
    assert [event.event_name for event in published] == ["agent.working", "agent.waiting"]


def test_duplicate_log_and_hook_stop_do_not_replay_review() -> None:
    published: list[PetEvent] = []
    snapshots = []
    coordinator = CodexLinkCoordinator(published.append, snapshots.append)
    coordinator.consume(_log("UserPromptSubmit"))

    coordinator.consume(_log("Stop"))
    coordinator.consume(_hook("Stop", turn=None))

    assert coordinator.snapshot.state == "review"
    assert [event.event_name for event in published] == ["agent.working", "agent.success"]
    assert len(snapshots) == 2


def test_delayed_duplicate_stop_after_animation_does_not_replay_review() -> None:
    published: list[PetEvent] = []
    coordinator = CodexLinkCoordinator(published.append)
    coordinator.consume(_log("Stop", session="same", turn="turn-1"))
    coordinator.finish_review_animation()

    assert coordinator.consume(_hook("Stop", session="same", turn="turn-1"))

    assert coordinator.snapshot.state == "idle"
    assert coordinator.snapshot.unread_review_count == 0
    assert [event.event_name for event in published] == ["agent.success", "agent.idle"]


def test_delayed_log_start_does_not_revive_completed_turn() -> None:
    published: list[PetEvent] = []
    coordinator = CodexLinkCoordinator(published.append)
    coordinator.consume(_hook("Stop", session="same", turn="turn-1"))
    coordinator.finish_review_animation()

    assert coordinator.consume(_log("UserPromptSubmit", session="same", turn="turn-1"))

    assert coordinator.snapshot.state == "idle"
    assert [event.event_name for event in published] == ["agent.success", "agent.idle"]


def test_log_turn_aborted_clears_current_turn_without_failure_bubble() -> None:
    published: list[PetEvent] = []
    coordinator = CodexLinkCoordinator(published.append)
    coordinator.consume(_log("UserPromptSubmit", turn="turn-1"))

    assert coordinator.consume(_log("TurnAborted", turn="turn-1"))

    assert coordinator.snapshot.state == "idle"
    assert [event.event_name for event in published] == ["agent.working", "agent.idle"]


def test_new_turn_replaces_old_review_in_the_same_session() -> None:
    coordinator = CodexLinkCoordinator(lambda _event: None)
    coordinator.consume(_log("UserPromptSubmit", turn="turn-1"))
    coordinator.consume(_log("Stop", turn="turn-1"))
    coordinator.consume(_log("ThreadUnread", turn="ignored"))
    assert coordinator.snapshot.unread_review_count == 1

    coordinator.consume(_log("UserPromptSubmit", turn="turn-2"))

    assert coordinator.snapshot.state == "running"
    assert coordinator.snapshot.count == 1
    assert coordinator.snapshot.unread_review_count == 0


def test_thread_read_removes_only_that_sessions_review() -> None:
    coordinator = CodexLinkCoordinator(lambda _event: None)
    coordinator.consume(_log("Stop", session="read", turn="t1"))
    coordinator.consume(_log("Stop", session="unread", turn="t2"))
    coordinator.consume(_log("ThreadUnread", session="read", turn="ignored"))
    coordinator.consume(_log("ThreadUnread", session="unread", turn="ignored"))
    assert coordinator.snapshot.unread_review_count == 2

    assert coordinator.consume(_log("ThreadRead", session="read", turn="ignored"))

    assert coordinator.snapshot.state == "review"
    assert coordinator.snapshot.count == 1
    assert coordinator.snapshot.unread_review_count == 1


def test_tool_failure_is_temporary_and_later_activity_restores_running() -> None:
    published: list[PetEvent] = []
    coordinator = CodexLinkCoordinator(published.append)

    coordinator.consume(_hook("PostToolUse", tool_failed=True))
    assert coordinator.snapshot.state == "failed"
    assert published[-1].event_name == "agent.error"

    coordinator.consume(_hook("PreToolUse"))
    assert coordinator.snapshot.state == "running"
    assert published[-1].event_name == "agent.working"


def test_coordinator_aggregates_multiple_tasks_by_priority_and_count() -> None:
    coordinator = CodexLinkCoordinator(lambda _event: None)

    coordinator.consume(_hook("UserPromptSubmit", session="s1", turn="t1"))
    coordinator.consume(_hook("PermissionRequest", session="s2", turn="t2"))
    coordinator.consume(_hook("PermissionRequest", session="s3", turn="t3"))

    assert coordinator.snapshot.state == "waiting"
    assert coordinator.snapshot.count == 2
    assert coordinator.snapshot.message == "2 个 Codex 任务等待你处理"

    coordinator.consume(_hook("Stop", session="s2", turn="t2"))
    assert coordinator.snapshot.state == "waiting"
    assert coordinator.snapshot.count == 1


def test_session_end_cleans_tasks_and_stop_guard_does_not_mark_review() -> None:
    published: list[PetEvent] = []
    coordinator = CodexLinkCoordinator(published.append)
    coordinator.consume(_hook("UserPromptSubmit", session="s1", turn="t1"))

    assert not coordinator.consume(_hook("Stop", session="s1", turn="t1", stop_hook_active=True))
    assert coordinator.snapshot.state == "running"

    assert coordinator.consume(_hook("SessionEnd", session="s1", turn=None))
    assert coordinator.snapshot.state == "idle"
    assert published[-1].event_name == "agent.idle"


def test_coordinator_rejects_untrusted_sources_and_invalid_identifiers() -> None:
    coordinator = CodexLinkCoordinator(lambda _event: None)

    assert not coordinator.consume(PetEvent("codex.hook", source="external", payload={"hook_event_name": "Stop"}))
    assert not coordinator.consume(PetEvent("codex.hook", source="codex-hook", payload={"hook_event_name": "Stop"}))
    assert coordinator.snapshot.state == "idle"


def test_marking_reviews_read_keeps_review_state_but_clears_unread_count() -> None:
    coordinator = CodexLinkCoordinator(lambda _event: None)
    coordinator.consume(_hook("Stop"))
    coordinator.consume(_log("ThreadUnread"))

    coordinator.mark_reviews_read()

    assert coordinator.snapshot.state == "review"
    assert coordinator.snapshot.unread_review_count == 0


def test_foreground_completion_returns_idle_after_review_animation_without_badge() -> None:
    published: list[PetEvent] = []
    coordinator = CodexLinkCoordinator(published.append)
    coordinator.consume(_log("Stop"))

    coordinator.finish_review_animation()

    assert coordinator.snapshot.state == "idle"
    assert coordinator.snapshot.unread_review_count == 0
    assert [event.event_name for event in published] == ["agent.success", "agent.idle"]


def test_confirmed_unread_survives_animation_as_idle_badge_without_replaying_review() -> None:
    published: list[PetEvent] = []
    coordinator = CodexLinkCoordinator(published.append)
    coordinator.consume(_log("Stop", session="background"))
    coordinator.consume(_log("ThreadUnread", session="background", turn="ignored"))

    coordinator.finish_review_animation()

    assert coordinator.snapshot.state == "idle"
    assert coordinator.snapshot.unread_review_count == 1
    assert coordinator.snapshot.message == "Codex 任务已完成，等待查看"
    assert [event.event_name for event in published] == ["agent.success", "agent.idle"]


def test_thread_unread_before_stop_is_applied_when_completion_arrives() -> None:
    coordinator = CodexLinkCoordinator(lambda _event: None)
    coordinator.consume(_log("ThreadUnread", session="background", turn="ignored"))

    coordinator.consume(_log("Stop", session="background", turn="turn-1"))

    assert coordinator.snapshot.state == "review"
    assert coordinator.snapshot.unread_review_count == 1


def test_late_unread_after_completion_correlation_ttl_is_ignored() -> None:
    now = [0.0]
    coordinator = CodexLinkCoordinator(
        lambda _event: None,
        monotonic_time=lambda: now[0],
        completed_session_ttl=2.0,
    )
    coordinator.consume(_log("Stop", session="foreground", turn="turn-1"))
    coordinator.finish_review_animation()
    now[0] = 3.0

    coordinator.consume(_log("ThreadUnread", session="foreground", turn="ignored"))

    assert coordinator.snapshot.state == "idle"
    assert coordinator.snapshot.unread_review_count == 0


def test_two_confirmed_background_completions_report_two_unread() -> None:
    published: list[PetEvent] = []
    coordinator = CodexLinkCoordinator(published.append)
    for session, turn in (("first", "t1"), ("second", "t2")):
        coordinator.consume(_log("Stop", session=session, turn=turn))
        coordinator.consume(_log("ThreadUnread", session=session, turn="ignored"))

    coordinator.finish_review_animation()

    assert coordinator.snapshot.state == "idle"
    assert coordinator.snapshot.unread_review_count == 2
    assert coordinator.snapshot.message == "2 个 Codex 任务已完成，等待查看"
    assert [event.event_name for event in published] == ["agent.success", "agent.idle"]


def test_dismissing_reviews_removes_review_tasks_and_restores_idle() -> None:
    published: list[PetEvent] = []
    coordinator = CodexLinkCoordinator(published.append)
    coordinator.consume(_hook("Stop"))

    coordinator.dismiss_reviews()

    assert coordinator.snapshot.state == "idle"
    assert coordinator.snapshot.unread_review_count == 0
    assert [event.event_name for event in published] == ["agent.success", "agent.idle"]
