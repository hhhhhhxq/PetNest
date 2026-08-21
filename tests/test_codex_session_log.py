"""Codex 会话 JSONL 的隐私友好增量状态监听。"""

from __future__ import annotations

from datetime import date
import json
from pathlib import Path

from petnest.core.codex_session_log import CodexSessionLogWatcher


TODAY = date(2026, 8, 20)


def _day(root: Path, value: date = TODAY) -> Path:
    path = root / f"{value:%Y}" / f"{value:%m}" / f"{value:%d}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _line(kind: str, payload: dict[str, object]) -> bytes:
    return (json.dumps({"timestamp": "2026-08-20T12:00:00Z", "type": kind, "payload": payload}) + "\n").encode()


def _meta(session_id: str) -> bytes:
    return _line("session_meta", {"session_id": session_id, "cli_version": "0.147.0"})


def _event(name: str, turn_id: str, **extra: object) -> bytes:
    return _line("event_msg", {"type": name, "turn_id": turn_id, **extra})


def _write_unread(path: Path, *session_ids: str) -> None:
    path.write_text(
        json.dumps(
            {
                "electron-persisted-atom-state": {
                    "unread-thread-ids-by-host-v1": {"local": list(session_ids)}
                }
            }
        ),
        encoding="utf-8",
    )


def test_start_baselines_existing_file_without_replaying_history(tmp_path: Path) -> None:
    root = tmp_path / "sessions"
    path = _day(root) / "rollout-existing.jsonl"
    path.write_bytes(_meta("session-1") + _event("task_started", "turn-old"))
    watcher = CodexSessionLogWatcher(root, today=lambda: TODAY)

    watcher.start()

    assert watcher.poll() == ()
    with path.open("ab") as stream:
        stream.write(_event("task_started", "turn-new"))
    events = watcher.poll()
    assert len(events) == 1
    assert events[0].source == "codex-log"
    assert events[0].payload == {
        "hook_event_name": "UserPromptSubmit",
        "session_id": "session-1",
        "turn_id": "turn-new",
    }


def test_reconfigure_home_stops_old_source_and_baselines_new_history(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    watcher = CodexSessionLogWatcher(first / "sessions", today=lambda: TODAY)
    watcher.start()
    path = _day(second / "sessions") / "rollout-new-home.jsonl"
    path.write_bytes(_meta("session-2") + _event("task_started", "old-turn"))

    watcher.reconfigure(second)

    assert watcher.root == (second / "sessions").resolve()
    assert watcher.global_state_path == (second / ".codex-global-state.json").resolve()
    assert watcher.poll() == ()
    with path.open("ab") as stream:
        stream.write(_event("task_started", "new-turn"))
    assert watcher.poll()[0].payload["turn_id"] == "new-turn"


def test_new_file_maps_started_complete_and_aborted_without_content(tmp_path: Path) -> None:
    root = tmp_path / "sessions"
    watcher = CodexSessionLogWatcher(root, today=lambda: TODAY)
    watcher.start()
    path = _day(root) / "rollout-new.jsonl"
    path.write_bytes(
        _meta("session-2")
        + _event("task_started", "turn-1", prompt="private")
        + _event("task_complete", "turn-1", last_agent_message="private")
        + _event("turn_aborted", "turn-2", reason="private")
    )

    events = watcher.poll()

    assert [event.payload["hook_event_name"] for event in events] == [
        "UserPromptSubmit",
        "Stop",
        "TurnAborted",
    ]
    assert "tool_failed" not in events[-1].payload
    assert "prompt" not in events[0].payload
    assert "last_agent_message" not in events[1].payload
    assert "reason" not in events[2].payload


def test_partial_last_line_waits_for_completion(tmp_path: Path) -> None:
    root = tmp_path / "sessions"
    watcher = CodexSessionLogWatcher(root, today=lambda: TODAY)
    watcher.start()
    path = _day(root) / "rollout-partial.jsonl"
    complete = _meta("session-3") + _event("task_started", "turn-1")
    path.write_bytes(complete[:-5])

    assert watcher.poll() == ()
    with path.open("ab") as stream:
        stream.write(complete[-5:])
    assert [event.payload["turn_id"] for event in watcher.poll()] == ["turn-1"]


def test_malformed_and_unknown_lines_are_ignored(tmp_path: Path) -> None:
    root = tmp_path / "sessions"
    watcher = CodexSessionLogWatcher(root, today=lambda: TODAY)
    watcher.start()
    path = _day(root) / "rollout-broken.jsonl"
    path.write_bytes(
        _meta("session-4")
        + b"{ broken\n"
        + _line("event_msg", {"type": "future_event", "turn_id": "turn-x"})
        + _event("task_started", "turn-ok")
    )

    events = watcher.poll()

    assert len(events) == 1
    assert events[0].payload["turn_id"] == "turn-ok"


def test_file_truncation_resets_reader_without_crashing(tmp_path: Path) -> None:
    root = tmp_path / "sessions"
    path = _day(root) / "rollout-truncate.jsonl"
    path.write_bytes(_meta("session-5") + _event("task_started", "turn-old"))
    watcher = CodexSessionLogWatcher(root, today=lambda: TODAY)
    watcher.start()

    path.write_bytes(_meta("session-5") + _event("task_started", "turn-new"))
    events = watcher.poll()

    assert [event.payload["turn_id"] for event in events] == ["turn-new"]


def test_today_and_previous_day_are_scanned_but_older_days_are_not(tmp_path: Path) -> None:
    root = tmp_path / "sessions"
    watcher = CodexSessionLogWatcher(root, today=lambda: TODAY)
    watcher.start()
    (_day(root, date(2026, 8, 19)) / "rollout-yesterday.jsonl").write_bytes(
        _meta("session-y") + _event("task_started", "turn-y")
    )
    (_day(root, date(2026, 8, 18)) / "rollout-old.jsonl").write_bytes(
        _meta("session-o") + _event("task_started", "turn-o")
    )

    events = watcher.poll()

    assert [event.payload["session_id"] for event in events] == ["session-y"]


def test_runtime_watcher_ignores_intermediate_session_symlink(tmp_path: Path) -> None:
    root = tmp_path / "sessions"
    outside_year = tmp_path / "outside-year"
    outside_day = outside_year / "08" / "20"
    outside_day.mkdir(parents=True)
    (outside_day / "rollout-outside.jsonl").write_bytes(
        _meta("session-outside") + _event("task_started", "turn-outside")
    )
    root.mkdir()
    try:
        (root / "2026").symlink_to(outside_year, target_is_directory=True)
    except OSError:
        return
    watcher = CodexSessionLogWatcher(root, today=lambda: TODAY)
    watcher.start()

    with (outside_day / "rollout-outside.jsonl").open("ab") as stream:
        stream.write(_event("task_started", "turn-after-start"))

    assert watcher.poll() == ()


def test_stop_clears_offsets_and_disables_polling(tmp_path: Path) -> None:
    root = tmp_path / "sessions"
    watcher = CodexSessionLogWatcher(root, today=lambda: TODAY)
    watcher.start()
    watcher.stop()
    (_day(root) / "rollout-after-stop.jsonl").write_bytes(
        _meta("session-stop") + _event("task_started", "turn-stop")
    )

    assert watcher.poll() == ()
    assert watcher.status.state == "stopped"


def test_unrecognized_session_metadata_degrades_to_incompatible(tmp_path: Path) -> None:
    root = tmp_path / "sessions"
    watcher = CodexSessionLogWatcher(root, today=lambda: TODAY)
    watcher.start()
    path = _day(root) / "rollout-future-01a01dec-4d89-7fc3-b977-4d69ae338466.jsonl"
    path.write_bytes(
        _line("session_meta", {"future_session_key": "session-future"})
        + _event("task_started", "turn-future")
    )

    assert watcher.poll() == ()
    assert watcher.status.state == "incompatible"


def test_status_event_without_turn_id_degrades_to_incompatible(tmp_path: Path) -> None:
    root = tmp_path / "sessions"
    watcher = CodexSessionLogWatcher(root, today=lambda: TODAY)
    watcher.start()
    path = _day(root) / "rollout-missing-turn.jsonl"
    path.write_bytes(
        _meta("session-missing-turn")
        + _line("event_msg", {"type": "task_started"})
    )

    assert watcher.poll() == ()
    assert watcher.status.state == "incompatible"


def test_startup_unread_history_is_baselined_and_never_emitted(tmp_path: Path) -> None:
    root = tmp_path / "sessions"
    state_path = tmp_path / ".codex-global-state.json"
    _write_unread(state_path, "session-read", "session-still-unread")
    watcher = CodexSessionLogWatcher(root, today=lambda: TODAY, global_state_path=state_path)
    watcher.start()
    _write_unread(state_path, "session-still-unread")

    assert watcher.poll() == ()


def test_new_unread_thread_must_remain_stable_before_emitting(tmp_path: Path) -> None:
    root = tmp_path / "sessions"
    state_path = tmp_path / ".codex-global-state.json"
    now = [0.0]
    _write_unread(state_path)
    watcher = CodexSessionLogWatcher(
        root,
        today=lambda: TODAY,
        global_state_path=state_path,
        monotonic_time=lambda: now[0],
        unread_stable_seconds=1.0,
    )
    watcher.start()
    _write_unread(state_path, "session-new")

    assert watcher.poll() == ()
    now[0] = 0.9
    assert watcher.poll() == ()
    now[0] = 1.1
    events = watcher.poll()

    assert [event.payload for event in events] == [
        {"hook_event_name": "ThreadUnread", "session_id": "session-new"}
    ]

    _write_unread(state_path)
    read_events = watcher.poll()
    assert [event.payload for event in read_events] == [
        {"hook_event_name": "ThreadRead", "session_id": "session-new"}
    ]


def test_transient_unread_thread_removed_before_stable_never_emits(tmp_path: Path) -> None:
    root = tmp_path / "sessions"
    state_path = tmp_path / ".codex-global-state.json"
    now = [0.0]
    _write_unread(state_path)
    watcher = CodexSessionLogWatcher(
        root,
        today=lambda: TODAY,
        global_state_path=state_path,
        monotonic_time=lambda: now[0],
        unread_stable_seconds=1.0,
    )
    watcher.start()
    _write_unread(state_path, "session-transient")

    assert watcher.poll() == ()
    now[0] = 0.5
    _write_unread(state_path)
    assert watcher.poll() == ()
    now[0] = 2.0
    assert watcher.poll() == ()
