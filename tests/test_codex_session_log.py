"""Codex 会话 JSONL 的隐私友好增量状态监听。"""

from __future__ import annotations

from datetime import UTC, date, datetime
import json
import os
from pathlib import Path

from petnest.core.codex_link import CodexLinkCoordinator
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


class _FakeThreadIndex:
    def __init__(self, paths: tuple[Path, ...] = ()) -> None:
        self.paths = paths
        self.calls = 0
        self.error: Exception | None = None
        self.last_status = "ready"

    def recent_rollout_paths(self, *, limit: int = 64) -> tuple[Path, ...]:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.paths[:limit]


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


def test_start_preserves_an_unfinished_last_line_until_it_is_completed(
    tmp_path: Path,
) -> None:
    root = tmp_path / "sessions"
    session_id = "01a0437c-4699-7571-b916-d766c9198dea"
    path = _day(root) / f"rollout-partial-{session_id}.jsonl"
    complete = _meta(session_id) + _event("task_started", "turn-startup")
    path.write_bytes(complete[:-5])
    watcher = CodexSessionLogWatcher(root, today=lambda: TODAY)

    watcher.start()
    assert watcher.poll() == ()
    with path.open("ab") as stream:
        stream.write(complete[-5:])

    assert [event.payload["turn_id"] for event in watcher.poll()] == [
        "turn-startup"
    ]


def test_embedded_session_metadata_cannot_split_lifecycle_identity(
    tmp_path: Path,
) -> None:
    root = tmp_path / "sessions"
    file_session = "01a0437c-4699-7571-b916-d766c9198dea"
    parent_session = "01a042d6-1dfa-7df2-bc26-56dace38139d"
    path = _day(root) / f"rollout-fork-{file_session}.jsonl"
    path.write_bytes(_meta(file_session))
    watcher = CodexSessionLogWatcher(root, today=lambda: TODAY)
    coordinator = CodexLinkCoordinator(lambda _event: None)
    watcher.start()
    with path.open("ab") as stream:
        stream.write(
            _meta(parent_session)
            + _event("task_started", "turn-fork")
            + _meta(file_session)
            + _event("task_complete", "turn-fork")
        )

    events = watcher.poll()
    for event in events:
        coordinator.consume(event)

    assert [event.payload["session_id"] for event in events] == [
        file_session,
        file_session,
    ]
    assert coordinator.snapshot.state == "review"
    assert coordinator.snapshot.count == 1


def test_runtime_new_date_file_does_not_replay_completed_history(
    tmp_path: Path,
) -> None:
    root = tmp_path / "sessions"
    watcher = CodexSessionLogWatcher(
        root,
        today=lambda: TODAY,
        utc_now=lambda: datetime(2026, 8, 20, 12, 0, 20, tzinfo=UTC),
    )
    watcher.start()
    session_id = "01a0437c-4699-7571-b916-d766c9198dea"
    path = _day(root) / f"rollout-runtime-{session_id}.jsonl"
    path.write_bytes(
        _meta(session_id)
        + _event("task_started", "turn-old", timestamp="2026-08-20T11:59:30Z")
        + _event("task_complete", "turn-old", timestamp="2026-08-20T11:59:40Z")
    )

    assert watcher.poll() == ()

    with path.open("ab") as stream:
        stream.write(_event("task_started", "turn-new"))
    assert [event.payload for event in watcher.poll()] == [
        {
            "hook_event_name": "UserPromptSubmit",
            "session_id": session_id,
            "turn_id": "turn-new",
        }
    ]


def test_runtime_new_date_file_recovers_only_recent_unfinished_turn(
    tmp_path: Path,
) -> None:
    root = tmp_path / "sessions"
    watcher = CodexSessionLogWatcher(
        root,
        today=lambda: TODAY,
        utc_now=lambda: datetime(2026, 8, 20, 12, 0, 20, tzinfo=UTC),
    )
    watcher.start()
    file_session = "01a0437c-4699-7571-b916-d766c9198dea"
    parent_session = "01a042d6-1dfa-7df2-bc26-56dace38139d"
    path = _day(root) / f"rollout-runtime-{file_session}.jsonl"
    path.write_bytes(
        _meta(file_session)
        + _meta(parent_session)
        + _event("task_started", "turn-running")
    )

    assert [event.payload for event in watcher.poll()] == [
        {
            "hook_event_name": "UserPromptSubmit",
            "session_id": file_session,
            "turn_id": "turn-running",
        }
    ]
    assert watcher.poll() == ()


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


def test_start_ignores_timestamp_that_overflows_during_utc_conversion(tmp_path: Path) -> None:
    root = tmp_path / "sessions"
    path = _day(root) / "rollout-overflowing-timestamp.jsonl"
    path.write_bytes(
        _meta("session-overflow")
        + _event(
            "task_started",
            "turn-overflow",
            timestamp="0001-01-01T00:00:00+23:59",
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


def test_activity_for_another_turn_does_not_refresh_recovered_lease(
    tmp_path: Path,
) -> None:
    root = tmp_path / "sessions"
    path = _day(root) / "rollout-other-turn-growth.jsonl"
    path.write_bytes(
        _meta("session-other-turn-growth")
        + _event("task_started", "turn-original")
    )
    now = [0.0]
    watcher = CodexSessionLogWatcher(
        root,
        today=lambda: TODAY,
        utc_now=lambda: datetime(2026, 8, 20, 12, 0, 20, tzinfo=UTC),
        monotonic_time=lambda: now[0],
    )
    watcher.start()
    assert watcher.poll()[0].payload["turn_id"] == "turn-original"

    now[0] = 290.0
    with path.open("ab") as stream:
        stream.write(
            _line(
                "event_msg",
                {"type": "future_event", "turn_id": "turn-unrelated"},
            )
        )
    assert watcher.poll() == ()
    now[0] = 300.1

    assert [event.payload for event in watcher.poll()] == [
        {
            "hook_event_name": "TurnAborted",
            "session_id": "session-other-turn-growth",
            "turn_id": "turn-original",
        }
    ]


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


def test_growth_without_a_bounded_turn_id_does_not_refresh_recovered_lease(
    tmp_path: Path,
) -> None:
    root = tmp_path / "sessions"
    path = _day(root) / "rollout-untrusted-growth.jsonl"
    path.write_bytes(
        _meta("session-untrusted-growth")
        + _event("task_started", "turn-untrusted-growth")
    )
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
        stream.write(_line("event_msg", {"type": "future_event"}))
    assert watcher.poll() == ()
    now[0] = 300.1

    assert [event.payload["hook_event_name"] for event in watcher.poll()] == [
        "TurnAborted"
    ]


def test_incompatible_growth_does_not_refresh_recovered_lease(tmp_path: Path) -> None:
    root = tmp_path / "sessions"
    path = _day(root) / "rollout-incompatible-growth.jsonl"
    path.write_bytes(
        _meta("session-incompatible-growth")
        + _event("task_started", "turn-incompatible-growth")
    )
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
        stream.write(_line("session_meta", {"future_session_key": "unsupported"}))
    assert watcher.poll() == ()
    now[0] = 299.0
    with path.open("ab") as stream:
        stream.write(_line("event_msg", {"type": "future_event", "turn_id": "turn-x"}))
    assert watcher.poll() == ()
    now[0] = 300.1

    assert [event.payload["hook_event_name"] for event in watcher.poll()] == [
        "TurnAborted"
    ]


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


def test_runtime_baseline_tail_reads_share_the_recovery_budget(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    root = tmp_path / "sessions"
    watcher = CodexSessionLogWatcher(
        root,
        today=lambda: TODAY,
        max_files=4,
        max_line_bytes=4096,
        startup_recovery_max_files=4,
        startup_recovery_max_bytes=4096,
    )
    watcher.start()
    for index in range(4):
        session_id = f"0000000{index}-0000-0000-0000-00000000000{index}"
        path = _day(root) / f"rollout-{session_id}.jsonl"
        path.write_bytes(b"x" * 8192)
    original_read = watcher._read_verified_candidate
    read_bytes = [0]

    def counted_read(*args: object, **kwargs: object) -> bytes | None:
        result = original_read(*args, **kwargs)
        if result is not None:
            read_bytes[0] += len(result)
        return result

    monkeypatch.setattr(watcher, "_read_verified_candidate", counted_read)  # type: ignore[attr-defined]

    assert watcher.poll() == ()
    assert read_bytes[0] <= 4096


def test_runtime_baseline_retries_nonempty_candidates_left_after_budget_exhaustion(
    tmp_path: Path,
) -> None:
    root = tmp_path / "sessions"
    watcher = CodexSessionLogWatcher(root, today=lambda: TODAY, max_files=3)
    watcher.start()
    oldest: Path | None = None
    for index in range(3):
        session_id = f"0000000{index}-0000-0000-0000-00000000000{index}"
        path = _day(root) / f"rollout-{session_id}.jsonl"
        path.write_bytes(_meta(session_id)[:-1])
        modified_ns = (index + 1) * 1_000_000_000
        os.utime(path, ns=(modified_ns, modified_ns))
        if index == 0:
            oldest = path
    watcher._startup_recovery_max_bytes = 2

    assert watcher.poll() == ()
    assert oldest is not None
    assert oldest not in watcher._cursors


def test_runtime_baseline_preserves_partial_line_beyond_recovery_file_limit(
    tmp_path: Path,
) -> None:
    root = tmp_path / "sessions"
    watcher = CodexSessionLogWatcher(
        root,
        today=lambda: TODAY,
        max_files=9,
        startup_recovery_max_files=8,
        startup_recovery_max_bytes=64 * 1024,
    )
    watcher.start()
    session_id = "00000000-0000-0000-0000-000000000000"
    partial_path = _day(root) / f"rollout-partial-{session_id}.jsonl"
    complete = _meta(session_id) + _event("task_started", "turn-partial")
    partial_path.write_bytes(complete[:-5])
    os.utime(partial_path, ns=(1_000_000_000, 1_000_000_000))
    for index in range(1, 9):
        other_id = f"0000000{index}-0000-0000-0000-00000000000{index}"
        path = _day(root) / f"rollout-{other_id}.jsonl"
        path.write_bytes(_meta(other_id))
        modified_ns = (index + 1) * 1_000_000_000
        os.utime(path, ns=(modified_ns, modified_ns))

    assert watcher.poll() == ()
    with partial_path.open("ab") as stream:
        stream.write(complete[-5:])

    assert [event.payload["turn_id"] for event in watcher.poll()] == [
        "turn-partial"
    ]


def test_runtime_baseline_preserves_partial_line_when_recovery_is_disabled(
    tmp_path: Path,
) -> None:
    root = tmp_path / "sessions"
    watcher = CodexSessionLogWatcher(
        root,
        today=lambda: TODAY,
        startup_recovery_window_seconds=0,
    )
    watcher.start()
    session_id = "01a0437c-4699-7571-b916-d766c9198dea"
    path = _day(root) / f"rollout-partial-{session_id}.jsonl"
    complete = _meta(session_id) + _event("task_started", "turn-disabled")
    path.write_bytes(complete[:-5])

    assert watcher.poll() == ()
    with path.open("ab") as stream:
        stream.write(complete[-5:])

    assert [event.payload["turn_id"] for event in watcher.poll()] == [
        "turn-disabled"
    ]


def test_recovery_uses_first_session_metadata_when_filename_has_no_uuid(
    tmp_path: Path,
) -> None:
    root = tmp_path / "sessions"
    path = _day(root) / "rollout-without-id.jsonl"
    path.write_bytes(
        _meta("session-file")
        + _line("event_msg", {"type": "future_event", "turn_id": "padding"}) * 80
        + _meta("session-parent")
        + _event("task_started", "turn-running")
    )
    watcher = CodexSessionLogWatcher(
        root,
        today=lambda: TODAY,
        utc_now=lambda: datetime(2026, 8, 20, 12, 0, 20, tzinfo=UTC),
        startup_recovery_max_bytes=4096,
        max_line_bytes=1024,
    )

    watcher.start()

    assert [event.payload["session_id"] for event in watcher.poll()] == [
        "session-file"
    ]


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
    path = _day(root) / "rollout-new.jsonl"
    path.write_bytes(_meta("session-2"))
    watcher = CodexSessionLogWatcher(root, today=lambda: TODAY)
    watcher.start()
    with path.open("ab") as stream:
        stream.write(
            _event("task_started", "turn-1", prompt="private")
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
    session_id = "01a0437c-4699-7571-b916-d766c9198dea"
    path = _day(root) / f"rollout-partial-{session_id}.jsonl"
    complete = _meta(session_id) + _event("task_started", "turn-1")
    path.write_bytes(complete[:-5])

    assert watcher.poll() == ()
    with path.open("ab") as stream:
        stream.write(complete[-5:])
    assert [event.payload["turn_id"] for event in watcher.poll()] == ["turn-1"]


def test_malformed_and_unknown_lines_are_ignored(tmp_path: Path) -> None:
    root = tmp_path / "sessions"
    path = _day(root) / "rollout-broken.jsonl"
    path.write_bytes(_meta("session-4"))
    watcher = CodexSessionLogWatcher(root, today=lambda: TODAY)
    watcher.start()
    with path.open("ab") as stream:
        stream.write(
            b"{ broken\n"
            + _line("event_msg", {"type": "future_event", "turn_id": "turn-x"})
            + _event("task_started", "turn-ok")
        )

    events = watcher.poll()

    assert len(events) == 1
    assert events[0].payload["turn_id"] == "turn-ok"


def test_file_truncation_resets_reader_without_crashing(tmp_path: Path) -> None:
    root = tmp_path / "sessions"
    path = _day(root) / "rollout-truncate.jsonl"
    path.write_bytes(
        _meta("session-5")
        + _event("task_started", "turn-old", timestamp="2026-08-20T11:57:00Z")
    )
    watcher = CodexSessionLogWatcher(
        root,
        today=lambda: TODAY,
        utc_now=lambda: datetime(2026, 8, 20, 12, 0, 20, tzinfo=UTC),
    )
    watcher.start()

    path.write_bytes(_meta("session-5") + _event("task_started", "turn-new"))
    events = watcher.poll()

    assert [event.payload["turn_id"] for event in events] == ["turn-new"]


def test_file_rebaseline_aborts_the_previous_recovered_turn(tmp_path: Path) -> None:
    root = tmp_path / "sessions"
    session_id = "01a0437c-4699-7571-b916-d766c9198dea"
    path = _day(root) / f"rollout-replaced-{session_id}.jsonl"
    path.write_bytes(
        _meta(session_id)
        + _line("event_msg", {"type": "future_event", "turn_id": "padding"}) * 8
        + _event("task_started", "turn-old")
    )
    watcher = CodexSessionLogWatcher(
        root,
        today=lambda: TODAY,
        utc_now=lambda: datetime(2026, 8, 20, 12, 0, 20, tzinfo=UTC),
    )
    watcher.start()
    assert [event.payload["turn_id"] for event in watcher.poll()] == ["turn-old"]

    path.write_bytes(
        _meta(session_id)
        + _event("task_started", "turn-finished")
        + _event("task_complete", "turn-finished", timestamp="2026-08-20T12:00:10Z")
    )

    assert [event.payload for event in watcher.poll()] == [
        {
            "hook_event_name": "TurnAborted",
            "session_id": session_id,
            "turn_id": "turn-old",
        }
    ]


def test_today_and_previous_day_are_scanned_but_older_days_are_not(tmp_path: Path) -> None:
    root = tmp_path / "sessions"
    yesterday = _day(root, date(2026, 8, 19)) / "rollout-yesterday.jsonl"
    yesterday.write_bytes(_meta("session-y"))
    old = _day(root, date(2026, 8, 18)) / "rollout-old.jsonl"
    old.write_bytes(_meta("session-o"))
    watcher = CodexSessionLogWatcher(root, today=lambda: TODAY)
    watcher.start()
    with yesterday.open("ab") as stream:
        stream.write(_event("task_started", "turn-y"))
    with old.open("ab") as stream:
        stream.write(_event("task_started", "turn-o"))

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
    path = _day(root) / "rollout-future.jsonl"
    path.write_bytes(b"")
    watcher = CodexSessionLogWatcher(root, today=lambda: TODAY)
    watcher.start()
    with path.open("ab") as stream:
        stream.write(
            _line("session_meta", {"future_session_key": "session-future"})
            + _event("task_started", "turn-future")
        )

    assert watcher.poll() == ()
    assert watcher.status.state == "incompatible"


def test_status_event_without_turn_id_degrades_to_incompatible(tmp_path: Path) -> None:
    root = tmp_path / "sessions"
    path = _day(root) / "rollout-missing-turn.jsonl"
    path.write_bytes(_meta("session-missing-turn"))
    watcher = CodexSessionLogWatcher(root, today=lambda: TODAY)
    watcher.start()
    with path.open("ab") as stream:
        stream.write(_line("event_msg", {"type": "task_started"}))

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


def test_incremental_read_rejects_file_swapped_after_safe_stat(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    root = tmp_path / "sessions"
    watcher = CodexSessionLogWatcher(root, today=lambda: TODAY)
    watcher.start()
    inside = _day(root) / "rollout-inside.jsonl"
    inside.write_bytes(_meta("session-inside"))
    outside = tmp_path / "outside.jsonl"
    outside.write_bytes(
        _meta("session-outside") + _event("task_started", "turn-outside")
    )
    original_open = Path.open

    def swapped_open(target: Path, *args: object, **kwargs: object) -> object:
        if target == inside and args and args[0] == "rb":
            return original_open(outside, *args, **kwargs)
        return original_open(target, *args, **kwargs)

    monkeypatch.setattr(Path, "open", swapped_open)  # type: ignore[attr-defined]

    assert watcher.poll() == ()


def test_incremental_read_stops_at_snapshot_eof_when_file_grows_before_open(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    root = tmp_path / "sessions"
    path = _day(root) / "rollout-growth-between-stat-and-open.jsonl"
    path.write_bytes(_meta("session-growth-between-stat-and-open"))
    watcher = CodexSessionLogWatcher(root, today=lambda: TODAY)
    watcher.start()
    with path.open("ab") as stream:
        stream.write(_event("task_started", "turn-in-snapshot"))
    original_open = Path.open
    injected = [False]

    def append_before_open(target: Path, *args: object, **kwargs: object) -> object:
        if target == path and args and args[0] == "rb" and not injected[0]:
            injected[0] = True
            with original_open(path, "ab") as stream:
                stream.write(_event("task_started", "turn-after-snapshot"))
        return original_open(target, *args, **kwargs)

    monkeypatch.setattr(Path, "open", append_before_open)  # type: ignore[attr-defined]

    assert [event.payload["turn_id"] for event in watcher.poll()] == [
        "turn-in-snapshot"
    ]
    assert [event.payload["turn_id"] for event in watcher.poll()] == [
        "turn-after-snapshot"
    ]


def test_startup_recovery_rejects_file_swapped_after_safe_stat(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    root = tmp_path / "sessions"
    inside = _day(root) / "rollout-recovery-inside.jsonl"
    outside = tmp_path / "recovery-outside.jsonl"
    outside_data = _meta("session-recovery-outside") + _event(
        "task_started", "turn-recovery-outside"
    )
    outside.write_bytes(outside_data)
    inside.write_bytes(b"x" * len(outside_data))
    original_open = Path.open

    def swapped_open(target: Path, *args: object, **kwargs: object) -> object:
        if target == inside and args and args[0] == "rb":
            return original_open(outside, *args, **kwargs)
        return original_open(target, *args, **kwargs)

    monkeypatch.setattr(Path, "open", swapped_open)  # type: ignore[attr-defined]
    watcher = CodexSessionLogWatcher(
        root,
        today=lambda: TODAY,
        utc_now=lambda: datetime(2026, 8, 20, 12, 0, 20, tzinfo=UTC),
    )

    watcher.start()

    assert watcher.poll() == ()


def test_runtime_baseline_does_not_keep_cursor_when_snapshot_is_swapped(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    root = tmp_path / "sessions"
    watcher = CodexSessionLogWatcher(root, today=lambda: TODAY)
    watcher.start()
    inside = _day(root) / "rollout-runtime-inside.jsonl"
    outside = tmp_path / "runtime-outside.jsonl"
    outside_data = _meta("session-outside") + _event(
        "task_started", "turn-outside"
    )
    outside.write_bytes(outside_data)
    inside.write_bytes(b"x" * len(outside_data))
    original_open = Path.open

    def swapped_open(target: Path, *args: object, **kwargs: object) -> object:
        if target == inside and args and args[0] == "rb":
            return original_open(outside, *args, **kwargs)
        return original_open(target, *args, **kwargs)

    monkeypatch.setattr(Path, "open", swapped_open)  # type: ignore[attr-defined]

    assert watcher.poll() == ()
    assert inside not in watcher._cursors


def test_indexed_old_file_is_discovered_at_runtime_and_incrementally_completes(
    tmp_path: Path,
) -> None:
    root = tmp_path / "sessions"
    old = _day(root, date(2026, 8, 1)) / "rollout-indexed.jsonl"
    old.write_bytes(_meta("session-indexed") + _event("task_started", "turn-indexed"))
    index = _FakeThreadIndex()
    now = [0.0]
    watcher = CodexSessionLogWatcher(
        root,
        today=lambda: TODAY,
        monotonic_time=lambda: now[0],
        utc_now=lambda: datetime(2026, 8, 20, 12, 0, 20, tzinfo=UTC),
        thread_index_factory=lambda _home: index,
        index_refresh_seconds=2.0,
    )
    watcher.start()
    assert watcher.poll() == ()

    index.paths = (old,)
    now[0] = 2.0

    assert [event.payload for event in watcher.poll()] == [
        {
            "hook_event_name": "UserPromptSubmit",
            "session_id": "session-indexed",
            "turn_id": "turn-indexed",
        }
    ]
    with old.open("ab") as stream:
        stream.write(_event("task_complete", "turn-indexed"))
    assert [event.payload["hook_event_name"] for event in watcher.poll()] == ["Stop"]


def test_indexed_completed_history_is_never_replayed(tmp_path: Path) -> None:
    root = tmp_path / "sessions"
    old = _day(root, date(2026, 8, 1)) / "rollout-completed.jsonl"
    old.write_bytes(
        _meta("session-completed")
        + _event("task_started", "turn-completed", timestamp="2026-08-20T11:59:00Z")
        + _event("task_complete", "turn-completed", timestamp="2026-08-20T11:59:30Z")
    )
    index = _FakeThreadIndex((old,))
    watcher = CodexSessionLogWatcher(
        root,
        today=lambda: TODAY,
        utc_now=lambda: datetime(2026, 8, 20, 12, 0, 20, tzinfo=UTC),
        thread_index_factory=lambda _home: index,
    )

    watcher.start()

    assert watcher.poll() == ()


def test_start_recovers_recent_unfinished_turn_from_indexed_old_file(tmp_path: Path) -> None:
    root = tmp_path / "sessions"
    old = _day(root, date(2026, 8, 1)) / "rollout-running.jsonl"
    old.write_bytes(_meta("session-running") + _event("task_started", "turn-running"))
    index = _FakeThreadIndex((old,))
    watcher = CodexSessionLogWatcher(
        root,
        today=lambda: TODAY,
        utc_now=lambda: datetime(2026, 8, 20, 12, 0, 20, tzinfo=UTC),
        thread_index_factory=lambda _home: index,
    )

    watcher.start()

    assert [event.payload["turn_id"] for event in watcher.poll()] == ["turn-running"]


def test_index_and_date_candidate_are_parsed_once(tmp_path: Path) -> None:
    root = tmp_path / "sessions"
    path = _day(root) / "rollout-00000000-0000-0000-0000-000000000001.jsonl"
    path.write_bytes(_event("task_complete", "turn-old"))
    index = _FakeThreadIndex((path,))
    watcher = CodexSessionLogWatcher(
        root,
        today=lambda: TODAY,
        thread_index_factory=lambda _home: index,
    )
    watcher.start()
    with path.open("ab") as stream:
        stream.write(_event("task_started", "turn-once"))

    assert [event.payload["turn_id"] for event in watcher.poll()] == ["turn-once"]


def test_index_failure_does_not_interrupt_date_based_watching(tmp_path: Path) -> None:
    root = tmp_path / "sessions"
    index = _FakeThreadIndex()
    index.error = RuntimeError("database is busy")
    path = _day(root) / "rollout-date-fallback.jsonl"
    path.write_bytes(_meta("session-date"))
    watcher = CodexSessionLogWatcher(
        root,
        today=lambda: TODAY,
        thread_index_factory=lambda _home: index,
    )
    watcher.start()
    with path.open("ab") as stream:
        stream.write(_event("task_started", "turn-date"))

    assert [event.payload["turn_id"] for event in watcher.poll()] == ["turn-date"]
    assert watcher.status.state == "active"


def test_index_is_only_refreshed_after_its_configured_interval(tmp_path: Path) -> None:
    index = _FakeThreadIndex()
    now = [0.0]
    watcher = CodexSessionLogWatcher(
        tmp_path / "sessions",
        today=lambda: TODAY,
        monotonic_time=lambda: now[0],
        thread_index_factory=lambda _home: index,
        index_refresh_seconds=2.0,
    )

    watcher.start()
    assert index.calls == 1
    watcher.poll()
    assert index.calls == 1
    now[0] = 1.9
    watcher.poll()
    assert index.calls == 1
    now[0] = 2.0
    watcher.poll()
    assert index.calls == 2


def test_index_rejects_outside_and_non_jsonl_candidates(tmp_path: Path) -> None:
    root = tmp_path / "sessions"
    outside = tmp_path / "outside.jsonl"
    outside.write_bytes(_meta("session-outside") + _event("task_started", "turn-outside"))
    non_jsonl = _day(root, date(2026, 8, 1)) / "rollout.txt"
    non_jsonl.write_bytes(_meta("session-text") + _event("task_started", "turn-text"))
    index = _FakeThreadIndex((outside, non_jsonl))
    watcher = CodexSessionLogWatcher(
        root,
        today=lambda: TODAY,
        thread_index_factory=lambda _home: index,
    )

    watcher.start()

    assert watcher.poll() == ()


def test_reconfigure_builds_an_index_for_the_new_codex_home(tmp_path: Path) -> None:
    homes: list[Path] = []

    def make_index(home: Path) -> _FakeThreadIndex:
        homes.append(home)
        return _FakeThreadIndex()

    first = tmp_path / "first"
    second = tmp_path / "second"
    watcher = CodexSessionLogWatcher(
        first / "sessions", today=lambda: TODAY, thread_index_factory=make_index
    )
    watcher.start()
    watcher.reconfigure(second)

    assert homes == [first.resolve(), second.resolve()]


def test_indexed_and_date_candidates_share_the_max_files_limit(tmp_path: Path) -> None:
    root = tmp_path / "sessions"
    today_path = _day(root) / "rollout-today.jsonl"
    today_path.write_bytes(_meta("session-today") + _event("task_started", "turn-today"))
    old = _day(root, date(2026, 8, 1)) / "rollout-old.jsonl"
    old.write_bytes(_meta("session-old") + _event("task_started", "turn-old"))
    old_stat = old.stat()
    os.utime(old, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns + 1_000_000_000))
    index = _FakeThreadIndex((old,))
    watcher = CodexSessionLogWatcher(
        root,
        today=lambda: TODAY,
        max_files=1,
        utc_now=lambda: datetime(2026, 8, 20, 12, 0, 20, tzinfo=UTC),
        thread_index_factory=lambda _home: index,
    )

    watcher.start()

    assert [event.payload["session_id"] for event in watcher.poll()] == ["session-old"]


def test_late_selected_indexed_file_is_baselined_before_its_history_is_read(
    tmp_path: Path,
) -> None:
    root = tmp_path / "sessions"
    indexed = _day(root, date(2026, 8, 1)) / "rollout-indexed.jsonl"
    indexed.write_bytes(
        _meta("session-indexed-late")
        + _event("task_started", "turn-indexed-late", timestamp="2026-08-20T11:57:00Z")
    )
    date_candidate = _day(root) / "rollout-date-candidate.jsonl"
    date_candidate.write_bytes(b"")
    indexed_stat = indexed.stat()
    os.utime(
        date_candidate,
        ns=(indexed_stat.st_atime_ns, indexed_stat.st_mtime_ns + 2_000_000_000),
    )
    index = _FakeThreadIndex((indexed,))
    watcher = CodexSessionLogWatcher(
        root,
        today=lambda: TODAY,
        max_files=1,
        utc_now=lambda: datetime(2026, 8, 20, 12, 0, 20, tzinfo=UTC),
        thread_index_factory=lambda _home: index,
    )
    watcher.start()

    with indexed.open("ab") as stream:
        stream.write(_line("event_msg", {"type": "future_event", "turn_id": "ignored"}))
    date_stat = date_candidate.stat()
    os.utime(
        indexed,
        ns=(date_stat.st_atime_ns, date_stat.st_mtime_ns + 1_000_000_000),
    )

    assert watcher.poll() == ()
    with indexed.open("ab") as stream:
        stream.write(_event("task_complete", "turn-indexed-late"))
    date_stat = date_candidate.stat()
    os.utime(
        indexed,
        ns=(date_stat.st_atime_ns, date_stat.st_mtime_ns + 1_000_000_000),
    )
    assert [event.payload["hook_event_name"] for event in watcher.poll()] == ["Stop"]


def test_index_status_preserves_a_running_old_path_until_its_terminal_event(
    tmp_path: Path,
) -> None:
    root = tmp_path / "sessions"
    path = _day(root, date(2026, 8, 1)) / "rollout-index-status.jsonl"
    path.write_bytes(_meta("session-index-status"))
    index = _FakeThreadIndex((path,))
    now = [0.0]
    watcher = CodexSessionLogWatcher(
        root,
        today=lambda: TODAY,
        monotonic_time=lambda: now[0],
        thread_index_factory=lambda _home: index,
        index_refresh_seconds=1.0,
    )
    watcher.start()
    with path.open("ab") as stream:
        stream.write(_event("task_started", "turn-index-status"))
    assert [event.payload["hook_event_name"] for event in watcher.poll()] == [
        "UserPromptSubmit"
    ]

    index.paths = ()
    index.last_status = "unavailable"
    now[0] = 1.0
    assert watcher.poll() == ()
    assert path in watcher._indexed_paths

    index.last_status = "ready"
    now[0] = 2.0
    assert watcher.poll() == ()
    assert path not in watcher._indexed_paths
    assert path in {candidate.path for candidate in watcher._candidate_files(())}

    with path.open("ab") as stream:
        stream.write(_event("task_complete", "turn-index-status"))
    assert [event.payload["hook_event_name"] for event in watcher.poll()] == ["Stop"]
    assert path not in {candidate.path for candidate in watcher._candidate_files(())}


def test_cursor_cache_stays_bounded_during_index_rotation_and_keeps_active_lease(
    tmp_path: Path,
) -> None:
    root = tmp_path / "sessions"
    active = _day(root, date(2026, 8, 1)) / "rollout-active.jsonl"
    active.write_bytes(_meta("session-active") + _event("task_started", "turn-active"))
    os.utime(active, ns=(1_000_000_000, 1_000_000_000))
    index = _FakeThreadIndex((active,))
    now = [0.0]
    watcher = CodexSessionLogWatcher(
        root,
        today=lambda: TODAY,
        max_files=2,
        monotonic_time=lambda: now[0],
        utc_now=lambda: datetime(2026, 8, 20, 12, 0, 20, tzinfo=UTC),
        thread_index_factory=lambda _home: index,
        index_refresh_seconds=0.1,
    )
    watcher.start()
    assert watcher.poll()[0].payload["turn_id"] == "turn-active"

    latest: tuple[Path, Path] | None = None
    for batch in range(12):
        paths: list[Path] = []
        for item in range(2):
            path = _day(root, date(2026, 8, 2)) / f"rollout-{batch}-{item}.jsonl"
            path.write_bytes(_meta(f"session-{batch}-{item}"))
            modified_ns = (batch * 2 + item + 10) * 1_000_000_000
            os.utime(path, ns=(modified_ns, modified_ns))
            paths.append(path)
        latest = (paths[0], paths[1])
        index.paths = latest
        now[0] += 1.0
        assert watcher.poll() == ()

    assert latest is not None
    assert len(watcher._cursors) <= 4
    assert active in watcher._cursors
    assert set(latest).issubset(watcher._cursors)

    with active.open("ab") as stream:
        stream.write(_event("task_complete", "turn-active"))
    active_stat = active.stat()
    os.utime(
        active,
        ns=(active_stat.st_atime_ns, max(active_stat.st_mtime_ns, 99_000_000_000)),
    )
    now[0] += 1.0

    assert [event.payload["hook_event_name"] for event in watcher.poll()] == ["Stop"]


def test_poll_scans_date_candidates_once(tmp_path: Path, monkeypatch: object) -> None:
    watcher = CodexSessionLogWatcher(tmp_path / "sessions", today=lambda: TODAY)
    watcher.start()
    calls = [0]

    def count_date_candidates() -> tuple[Path, ...]:
        calls[0] += 1
        return ()

    monkeypatch.setattr(watcher, "_date_candidate_files", count_date_candidates)  # type: ignore[attr-defined]

    watcher.poll()

    assert calls == [1]


def test_poll_uses_one_safe_stat_for_a_path_shared_by_date_and_index(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    root = tmp_path / "sessions"
    path = _day(root) / "rollout-snapshot.jsonl"
    path.write_bytes(_meta("session-snapshot"))
    index = _FakeThreadIndex((path,))
    watcher = CodexSessionLogWatcher(
        root,
        today=lambda: TODAY,
        thread_index_factory=lambda _home: index,
    )
    watcher.start()
    calls: list[Path] = []

    def count_safe_stat(candidate: Path) -> object:
        calls.append(candidate)
        return candidate.stat()

    monkeypatch.setattr(  # type: ignore[attr-defined]
        watcher,
        "_safe_session_stat",
        count_safe_stat,
        raising=False,
    )

    assert watcher.poll() == ()
    assert calls == [path]
