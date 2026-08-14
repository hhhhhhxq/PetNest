"""下班、加班和整小时提醒的纯时间状态。"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from petnest.core.work_finish_state import (
    WorkFinishState,
    advance_work_finish,
    continue_overtime,
    finish_work,
    overtime_duration,
    state_from_dict,
    state_to_dict,
)


def test_reaching_work_end_starts_one_initial_prompt() -> None:
    end_at = datetime(2026, 8, 14, 18, 0)

    first = advance_work_finish(None, end_at, end_at)
    repeated = advance_work_finish(first.state, end_at + timedelta(seconds=1), end_at, prompt_visible=True)

    assert first.should_prompt
    assert first.changed
    assert first.state is not None
    assert first.state.status == "prompting"
    assert first.state.prompt_kind == "initial"
    assert not repeated.should_prompt
    assert not repeated.changed


def test_late_start_creates_initial_prompt_instead_of_assuming_overtime() -> None:
    end_at = datetime(2026, 8, 14, 18, 0)

    transition = advance_work_finish(None, end_at + timedelta(hours=2), end_at)

    assert transition.should_prompt
    assert transition.state is not None
    assert transition.state.prompt_kind == "initial"


def test_overtime_uses_original_end_and_next_relative_hour() -> None:
    end_at = datetime(2026, 8, 14, 18, 40)
    prompting = advance_work_finish(None, datetime(2026, 8, 14, 18, 45), end_at)
    assert prompting.state is not None

    overtime = continue_overtime(prompting.state, datetime(2026, 8, 14, 18, 46))

    assert overtime.status == "overtime"
    assert overtime.next_prompt_at == datetime(2026, 8, 14, 19, 40)
    assert overtime_duration(overtime, datetime(2026, 8, 14, 18, 50)) == timedelta(minutes=10)


def test_reaching_or_missing_an_hourly_node_requests_only_one_hourly_prompt() -> None:
    end_at = datetime(2026, 8, 14, 18, 0)
    initial = advance_work_finish(None, end_at, end_at)
    assert initial.state is not None
    overtime = continue_overtime(initial.state, end_at + timedelta(minutes=1))

    due = advance_work_finish(overtime, end_at + timedelta(hours=2, minutes=5), end_at)
    repeated = advance_work_finish(
        due.state,
        end_at + timedelta(hours=2, minutes=5, seconds=1),
        end_at,
        prompt_visible=True,
    )

    assert due.should_prompt
    assert due.state is not None
    assert due.state.prompt_kind == "hourly"
    assert not repeated.should_prompt


def test_prompt_times_out_after_thirty_absolute_minutes() -> None:
    end_at = datetime(2026, 8, 14, 18, 0)
    transition = advance_work_finish(None, end_at, end_at)

    expired = advance_work_finish(
        transition.state,
        end_at + timedelta(minutes=30),
        end_at,
        prompt_visible=True,
    )

    assert expired.state is not None
    assert expired.state.status == "finished"
    assert not expired.should_prompt


def test_finish_choice_ends_the_day_and_serialization_round_trips() -> None:
    end_at = datetime(2026, 8, 14, 18, 0)
    initial = advance_work_finish(None, end_at, end_at)
    assert initial.state is not None

    finished = finish_work(initial.state)
    restored = state_from_dict(state_to_dict(finished))

    assert restored == finished
    assert restored is not None
    assert restored.status == "finished"


def test_state_from_dict_rejects_inconsistent_or_malformed_values() -> None:
    assert state_from_dict({"status": "overtime"}) is None
    assert state_from_dict({
        "work_date": "2026-08-14",
        "end_at": "not-a-date",
        "status": "overtime",
        "prompt_kind": None,
        "prompt_started_at": None,
        "next_prompt_at": None,
    }) is None


def test_previous_workday_state_is_replaced_for_new_work_date() -> None:
    old = WorkFinishState(
        work_date=date(2026, 8, 13),
        end_at=datetime(2026, 8, 13, 18, 0),
        status="finished",
    )
    new_end = datetime(2026, 8, 14, 18, 0)

    before_end = advance_work_finish(old, datetime(2026, 8, 14, 17, 0), new_end, work_date=date(2026, 8, 14))
    at_end = advance_work_finish(before_end.state, new_end, new_end, work_date=date(2026, 8, 14))

    assert before_end.state is None
    assert before_end.changed
    assert at_end.state is not None
    assert at_end.state.work_date == date(2026, 8, 14)
    assert at_end.should_prompt
