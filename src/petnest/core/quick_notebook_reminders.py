"""便签提醒的纯时间计算。"""

from __future__ import annotations

from datetime import datetime, timedelta


REPEAT_RULES = ("once", "daily", "weekly")


def snooze_until(now: datetime) -> datetime:
    _require_aware(now)
    return now + timedelta(minutes=10)


def is_due(
    due_at: datetime,
    *,
    last_triggered_at: datetime | None,
    now: datetime,
) -> bool:
    _require_aware(due_at)
    _require_aware(now)
    if last_triggered_at is not None:
        _require_aware(last_triggered_at)
    current = now.astimezone(due_at.tzinfo)
    return current >= due_at and (last_triggered_at is None or last_triggered_at < due_at)


def next_occurrence(
    due_at: datetime,
    repeat: str,
    weekdays: tuple[int, ...],
    after: datetime,
) -> datetime | None:
    _require_aware(due_at)
    _require_aware(after)
    current = after.astimezone(due_at.tzinfo)
    if repeat == "once":
        return due_at if due_at > current else None
    if repeat == "daily":
        candidate = due_at
        if candidate > current:
            return candidate
        days = (current.date() - candidate.date()).days
        candidate += timedelta(days=max(1, days))
        if candidate <= current:
            candidate += timedelta(days=1)
        return candidate
    if repeat == "weekly":
        allowed = {day for day in weekdays if 0 <= day <= 6}
        if not allowed:
            raise ValueError("每周提醒至少需要选择一天")
        for offset in range(8):
            date_value = current.date() + timedelta(days=offset)
            candidate = datetime.combine(date_value, due_at.timetz())
            if candidate > current and candidate.weekday() in allowed:
                return candidate
        return None
    raise ValueError(f"不支持的提醒重复规则：{repeat}")


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("提醒时间必须包含时区")


__all__ = ["REPEAT_RULES", "is_due", "next_occurrence", "snooze_until"]
