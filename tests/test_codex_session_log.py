"""Codex 会话 JSONL 的隐私友好增量状态监听。"""

from __future__ import annotations

from datetime import UTC, date, datetime
import json
import os
from pathlib import Path

from petnest.core.codex_session_log import CodexSessionLogWatcher


TODAY = date(2026, 8, 20)


def _day(root: Path, value: date = TODAY) -> Path:
    path = root / f"{value:%Y}" / f"{value:%m}" / f"{value:%d}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _line(
    kind: str,
    payload: dict[str, object],
    *,
    timestamp: str = "2026-08-20T12:00:00Z",
) -> bytes:
    document = {"timestamp": timestamp, "type": kind, "payload": payload}
    return (json.dumps(document) + "\n").encode()


def _meta(session_id: str) -> bytes:
    return _line("session_meta", {"session_id": session_id, "cli_version": "0.147.0"})


def _event(
    name: str,
    turn_id: str,
    *,
    timestamp: str = "2026-08-20T12:00:00Z",
    **extra: object,
) -> bytes:
    return _line(
        "event_msg",
        {"type": name, "turn_id": turn_id, **extra},
        timestamp=timestamp,
    )


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


def test_start_recovers_only_recent_unfinished_turn(tmp_path: Path) -> None:
    root = tmp_path / "sessions"
    path = _day(root) / "rollout-recent.jsonl"
    path.write_bytes(
        _meta("session-restore")
        + _event("task_started", "turn-complete", timestamp="2026-08-20T11:59:30Z")
        + _event("task_complete", "turn-complete", timestamp="2026-08-20T11:59:40Z")
        + _event("task_started", "turn-running", timestamp="2026-08-20T12:00:00Z")
    )
    watcher = CodexSessionLogWatcher(
        root,
        today=lambda: TODAY,
        utc_now=lambda: datetime(2026, 8, 20, 12, 0, 20, tzinfo=UTC),
    )

    watcher.start()

    assert [event.payload for event in watcher.poll()] == [
        {
            "hook_event_name": "UserPromptSubmit",
            "session_id": "session-restore",
            "turn_id": "turn-running",
        }
    ]
    assert watcher.poll() == ()


def test_start_does_not_recover_old_completed_or_aborted_turns(tmp_path: Path) -> None:
    root = tmp_path / "sessions"
    path = _day(root) / "rollout-terminal.jsonl"
    path.write_bytes(
        _meta("session-terminal")
        + _event("task_started", "turn-old", timestamp="2026-08-20T11:57:59Z")
        + _event("task_started", "turn-complete", timestamp="2026-08-20T11:59:30Z")
        + _event("task_complete", "turn-complete", timestamp="2026-08-20T11:59:40Z")
        + _event("task_started", "turn-aborted", timestamp="2026-08-20T11:59:45Z")
        + _event("turn_aborted", "turn-aborted", timestamp="2026-08-20T11:59:50Z")
    )
    watcher = CodexSessionLogWatcher(
        root,
        today=lambda: TODAY,
        utc_now=lambda: datetime(2026, 8, 20, 12, 0, 0, tzinfo=UTC),
    )

    watcher.start()

    assert watcher.poll() == ()


def test_start_does_not_recover_when_last_log_line_is_incomplete(tmp_path: Path) -> None:
    root = tmp_path / "sessions"
    path = _day(root) / "rollout-writing.jsonl"
    incomplete_terminal = _event(
        "task_complete",
        "turn-writing",
        timestamp="2026-08-20T12:00:10Z",
    )[:-5]
    path.write_bytes(
        _meta("session-writing")
        + _event("task_started", "turn-writing")
        + incomplete_terminal
    )
    watcher = CodexSessionLogWatcher(
        root,
        today=lambda: TODAY,
        utc_now=lambda: datetime(2026, 8, 20, 12, 0, 20, tzinfo=UTC),
    )

    watcher.start()

    assert watcher.poll() == ()


def test_start_does_not_recover_past_malformed_lifecycle_record(tmp_path: Path) -> None:
    root = tmp_path / "sessions"
    path = _day(root) / "rollout-malformed-terminal.jsonl"
    path.write_bytes(
        _meta("session-malformed")
        + _event("task_started", "turn-malformed")
        + _event(
            "task_complete",
            "turn-malformed",
            timestamp="not-a-timestamp",
        )
    )
    watcher = CodexSessionLogWatcher(
        root,
        today=lambda: TODAY,
        utc_now=lambda: datetime(2026, 8, 20, 12, 0, 20, tzinfo=UTC),
    )

    watcher.start()

    assert watcher.poll() == ()


def test_recovered_turn_expires_after_five_minutes_without_file_growth(tmp_path: Path) -> None:
    root = tmp_path / "sessions"
    path = _day(root) / "rollout-expiring.jsonl"
    path.write_bytes(_meta("session-expiring") + _event("task_started", "turn-expiring"))
    now = [0.0]
    watcher = CodexSessionLogWatcher(
        root,
        today=lambda: TODAY,
        utc_now=lambda: datetime(2026, 8, 20, 12, 0, 20, tzinfo=UTC),
        monotonic_time=lambda: now[0],
    )
    watcher.start()
    assert watcher.poll()[0].payload["hook_event_name"] == "UserPromptSubmit"

    now[0] = 300.1

    assert [event.payload for event in watcher.poll()] == [
        {
            "hook_event_name": "TurnAborted",
            "session_id": "session-expiring",
            "turn_id": "turn-expiring",
        }
    ]
    assert watcher.poll() == ()


def test_terminal_event_clears_recovered_lease_immediately(tmp_path: Path) -> None:
    root = tmp_path / "sessions"
    path = _day(root) / "rollout-terminal-after-recovery.jsonl"
    path.write_bytes(_meta("session-terminal-later") + _event("task_started", "turn-terminal-later"))
    now = [0.0]
    watcher = CodexSessionLogWatcher(
        root,
        today=lambda: TODAY,
        utc_now=lambda: datetime(2026, 8, 20, 12, 0, 20, tzinfo=UTC),
        monotonic_time=lambda: now[0],
    )
    watcher.start()
    assert watcher.poll()[0].payload["hook_event_name"] == "UserPromptSubmit"
    with path.open("ab") as stream:
        stream.write(
            _event(
                "task_complete",
                "turn-terminal-later",
                timestamp="2026-08-20T12:00:30Z",
            )
        )

    assert [event.payload["hook_event_name"] for event in watcher.poll()] == ["Stop"]
    now[0] = 600.0
    assert watcher.poll() == ()


def test_file_growth_refreshes_recovered_turn_lease(tmp_path: Path) -> None:
    root = tmp_path / "sessions"
    path = _day(root) / "rollout-growing.jsonl"
    path.write_bytes(_meta("session-growing") + _event("task_started", "turn-growing"))
    now = [0.0]
    watcher = CodexSessionLogWatcher(
        root,
        today=lambda: TODAY,
        utc_now=lambda: datetime(2026, 8, 20, 12, 0, 20, tzinfo=UTC),
        monotonic_time=lambda: now[0],
    )
    watcher.start()
    assert watcher.poll()[0].payload["hook_event_name"] == "UserPromptSubmit"

    now[0] = 290.0
    with path.open("ab") as stream:
        stream.write(_line("event_msg", {"type": "future_event", "turn_id": "turn-growing"}))
    assert watcher.poll() == ()
    now[0] = 310.0
    assert watcher.poll() == ()
    now[0] = 590.1
    assert watcher.poll()[0].payload["hook_event_name"] == "TurnAborted"


def test_failed_read_of_file_growth_does_not_refresh_recovered_lease(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    root = tmp_path / "sessions"
    path = _day(root) / "rollout-unreadable.jsonl"
    path.write_bytes(_meta("session-unreadable") + _event("task_started", "turn-unreadable"))
    now = [0.0]
    watcher = CodexSessionLogWatcher(
        root,
        today=lambda: TODAY,
        utc_now=lambda: datetime(2026, 8, 20, 12, 0, 20, tzinfo=UTC),
        monotonic_time=lambda: now[0],
    )
    watcher.start()
    assert watcher.poll()[0].payload["hook_event_name"] == "UserPromptSubmit"
    with path.open("ab") as stream:
        stream.write(_line("event_msg", {"type": "future_event", "turn_id": "turn-unreadable"}))
    original_open = Path.open

    def failing_open(target: Path, *args: object, **kwargs: object) -> object:
        if target == path and args and args[0] == "rb":
            raise PermissionError("temporarily unreadable")
        return original_open(target, *args, **kwargs)

    monkeypatch.setattr(Path, "open", failing_open)  # type: ignore[attr-defined]
    now[0] = 290.0
    assert watcher.poll() == ()
    now[0] = 300.1

    assert watcher.poll()[0].payload["hook_event_name"] == "TurnAborted"


def test_startup_recovery_budget_is_shared_across_latest_eight_files(tmp_path: Path) -> None:
    root = tmp_path / "sessions"
    padding = (
        _line("event_msg", {"type": "future_event", "turn_id": "padding"})
        * 12_000
    )
    expected_sessions: set[str] = set()
    for index in range(8):
        session_id = f"0000000{index}-0000-0000-0000-00000000000{index}"
        expected_sessions.add(session_id)
        path = _day(root) / f"rollout-{session_id}.jsonl"
        path.write_bytes(
            _meta(session_id)
            + padding
            + _event("task_started", f"turn-{index}")
        )
    watcher = CodexSessionLogWatcher(
        root,
        today=lambda: TODAY,
        utc_now=lambda: datetime(2026, 8, 20, 12, 0, 20, tzinfo=UTC),
        startup_recovery_max_bytes=2 * 1024 * 1024,
    )

    watcher.start()

    events = watcher.poll()
    assert {str(event.payload["session_id"]) for event in events} == expected_sessions


def test_startup_baseline_does_not_pre_read_session_metadata(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    root = tmp_path / "sessions"
    path = _day(root) / "rollout-no-preread.jsonl"
    path.write_bytes(_meta("session-no-preread") + _event("task_started", "turn-no-preread"))
    watcher = CodexSessionLogWatcher(
        root,
        today=lambda: TODAY,
        utc_now=lambda: datetime(2026, 8, 20, 12, 0, 20, tzinfo=UTC),
    )

    def reject_unbounded_read(_path: Path) -> str | None:
        raise AssertionError("startup baseline must not pre-read every file")

    monkeypatch.setattr(  # type: ignore[attr-defined]
        watcher,
        "_session_id",
        reject_unbounded_read,
        raising=False,
    )

    watcher.start()

    assert watcher.poll()[0].payload["session_id"] == "session-no-preread"


def test_startup_recovery_selects_latest_files_by_mtime_before_limiting(
    tmp_path: Path,
) -> None:
    root = tmp_path / "sessions"
    directory = _day(root)
    for index in range(64):
        session_id = f"10000000-0000-0000-0000-{index:012d}"
        path = directory / f"rollout-z-{index:02d}-{session_id}.jsonl"
        path.write_bytes(
            _meta(session_id)
            + _event("task_complete", f"turn-{index}", timestamp="2026-08-20T11:59:00Z")
        )
        os.utime(path, ns=(index + 1, index + 1))
    newest_session = "00000000-0000-0000-0000-000000000999"
    newest = directory / f"rollout-a-{newest_session}.jsonl"
    newest.write_bytes(_meta(newest_session) + _event("task_started", "turn-newest"))
    os.utime(newest, ns=(1_000_000, 1_000_000))
    watcher = CodexSessionLogWatcher(
        root,
        today=lambda: TODAY,
        utc_now=lambda: datetime(2026, 8, 20, 12, 0, 20, tzinfo=UTC),
    )

    watcher.start()

    assert [event.payload["session_id"] for event in watcher.poll()] == [newest_session]


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


def test_late_first_read_of_global_state_only_establishes_baseline(tmp_path: Path) -> None:
    root = tmp_path / "sessions"
    state_path = tmp_path / ".codex-global-state.json"
    now = [0.0]
    watcher = CodexSessionLogWatcher(
        root,
        today=lambda: TODAY,
        global_state_path=state_path,
        monotonic_time=lambda: now[0],
        unread_stable_seconds=1.0,
    )
    watcher.start()

    _write_unread(state_path, "historical-unread")
    assert watcher.poll() == ()
    now[0] = 2.0
    assert watcher.poll() == ()

    _write_unread(state_path)
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
