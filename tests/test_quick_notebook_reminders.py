from __future__ import annotations

from datetime import datetime, timedelta, timezone

from petnest.core.quick_notebook_reminders import is_due, next_occurrence, snooze_until


TZ = timezone(timedelta(hours=8))


def test_once_reminder_stops_after_due_time() -> None:
    due = datetime(2026, 9, 3, 10, 0, tzinfo=TZ)

    assert next_occurrence(due, "once", (), datetime(2026, 9, 1, tzinfo=TZ)) == due
    assert next_occurrence(due, "once", (), datetime(2026, 9, 4, tzinfo=TZ)) is None


def test_daily_and_weekly_reminders_advance_from_after_time() -> None:
    due = datetime(2026, 9, 1, 18, 0, tzinfo=TZ)
    after = datetime(2026, 9, 1, 18, 1, tzinfo=TZ)

    assert next_occurrence(due, "daily", (), after) == datetime(2026, 9, 2, 18, 0, tzinfo=TZ)
    assert next_occurrence(due, "weekly", (0, 4), after) == datetime(2026, 9, 4, 18, 0, tzinfo=TZ)


def test_weekly_reminder_can_use_same_day_when_time_is_still_ahead() -> None:
    due = datetime(2026, 9, 4, 18, 0, tzinfo=TZ)
    after = datetime(2026, 9, 4, 9, 0, tzinfo=TZ)

    assert next_occurrence(due, "weekly", (4,), after) == due


def test_snooze_is_exactly_ten_minutes() -> None:
    now = datetime(2026, 9, 1, 10, 0, tzinfo=TZ)

    assert snooze_until(now) == datetime(2026, 9, 1, 10, 10, tzinfo=TZ)


def test_due_check_does_not_repeat_the_same_occurrence() -> None:
    due = datetime(2026, 9, 1, 10, 0, tzinfo=TZ)
    now = datetime(2026, 9, 1, 10, 1, tzinfo=TZ)

    assert is_due(due, last_triggered_at=None, now=now) is True
    assert is_due(due, last_triggered_at=due, now=now) is False
