"""不依赖 Qt 的下班决策、加班累计与整小时提醒状态。"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from math import floor
from typing import Literal, Mapping


WorkFinishStatus = Literal["prompting", "overtime", "finished"]
PromptKind = Literal["initial", "hourly"]
PromptTiming = Literal["scheduled"]
PROMPT_TIMEOUT = timedelta(minutes=30)


@dataclass(frozen=True, slots=True)
class WorkFinishState:
    """一个工作日内可持久化的下班提醒状态。"""

    work_date: date
    end_at: datetime
    status: WorkFinishStatus
    prompt_kind: PromptKind | None = None
    prompt_started_at: datetime | None = None
    next_prompt_at: datetime | None = None
    prompt_timing: PromptTiming | None = None


@dataclass(frozen=True, slots=True)
class WorkFinishTransition:
    """一次计时刷新产生的状态与 UI 副作用。"""

    state: WorkFinishState | None
    should_prompt: bool = False
    changed: bool = False


def advance_work_finish(
    state: WorkFinishState | None,
    now: datetime,
    end_at: datetime,
    *,
    work_date: date | None = None,
    prompt_visible: bool = False,
) -> WorkFinishTransition:
    """推进到当前绝对时间；错过多个小时节点时只产生一次提醒。"""
    active_date = work_date or end_at.date()
    if state is not None and (state.work_date != active_date or state.end_at != end_at):
        state = None
        reset = True
    else:
        reset = False

    if now < end_at:
        return WorkFinishTransition(state=None, changed=reset or state is not None)

    if state is None:
        prompting = WorkFinishState(
            work_date=active_date,
            end_at=end_at,
            status="prompting",
            prompt_kind="initial",
            prompt_started_at=now,
        )
        return WorkFinishTransition(prompting, should_prompt=True, changed=True)

    if state.status == "prompting":
        if state.prompt_kind == "hourly" and state.prompt_timing != "scheduled":
            return WorkFinishTransition(finish_work(state), changed=True)
        started_at = state.prompt_started_at or now
        if now >= started_at + PROMPT_TIMEOUT:
            return WorkFinishTransition(finish_work(state), changed=True)
        return WorkFinishTransition(state, should_prompt=not prompt_visible)

    if state.status == "overtime":
        next_prompt = state.next_prompt_at or _next_hour_node(state.end_at, now)
        if now >= next_prompt:
            if now >= next_prompt + PROMPT_TIMEOUT:
                return WorkFinishTransition(finish_work(state), changed=True)
            prompting = replace(
                state,
                status="prompting",
                prompt_kind="hourly",
                prompt_started_at=next_prompt,
                next_prompt_at=None,
                prompt_timing="scheduled",
            )
            return WorkFinishTransition(prompting, should_prompt=True, changed=True)
        if state.next_prompt_at is None:
            return WorkFinishTransition(replace(state, next_prompt_at=next_prompt), changed=True)
    return WorkFinishTransition(state)


def continue_overtime(state: WorkFinishState, now: datetime) -> WorkFinishState:
    """关闭当前提示，并从原定下班时刻计算下一个未来小时节点。"""
    return replace(
        state,
        status="overtime",
        prompt_kind=None,
        prompt_started_at=None,
        next_prompt_at=_next_hour_node(state.end_at, now),
        prompt_timing=None,
    )


def finish_work(state: WorkFinishState) -> WorkFinishState:
    """把当天标为已下班并清除所有后续提醒。"""
    return replace(
        state,
        status="finished",
        prompt_kind=None,
        prompt_started_at=None,
        next_prompt_at=None,
        prompt_timing=None,
    )


def overtime_duration(state: WorkFinishState, now: datetime) -> timedelta:
    """返回从原定下班时刻开始的非负累计时长。"""
    return max(timedelta(), now - state.end_at)


def state_to_dict(state: WorkFinishState | None) -> dict[str, str | None] | None:
    """转换为设置文件可保存的窄 JSON 结构。"""
    if state is None:
        return None
    return {
        "work_date": state.work_date.isoformat(),
        "end_at": state.end_at.isoformat(),
        "status": state.status,
        "prompt_kind": state.prompt_kind,
        "prompt_started_at": _datetime_text(state.prompt_started_at),
        "next_prompt_at": _datetime_text(state.next_prompt_at),
        "prompt_timing": state.prompt_timing,
    }


def state_from_dict(value: object) -> WorkFinishState | None:
    """宽容读取持久化状态；任何矛盾都只丢弃本段状态。"""
    if not isinstance(value, Mapping):
        return None
    try:
        work_date = date.fromisoformat(_required_text(value, "work_date"))
        end_at = datetime.fromisoformat(_required_text(value, "end_at"))
        status = _required_text(value, "status")
        prompt_kind = _optional_text(value.get("prompt_kind"))
        prompt_started_at = _optional_datetime(value.get("prompt_started_at"))
        next_prompt_at = _optional_datetime(value.get("next_prompt_at"))
        prompt_timing = _optional_text(value.get("prompt_timing"))
    except (TypeError, ValueError):
        return None
    if status not in {"prompting", "overtime", "finished"}:
        return None
    if prompt_kind not in {None, "initial", "hourly"}:
        return None
    if prompt_timing not in {None, "scheduled"}:
        return None
    if prompt_timing is not None and not (status == "prompting" and prompt_kind == "hourly"):
        return None
    if status == "prompting" and (prompt_kind is None or prompt_started_at is None):
        return None
    if status == "overtime" and next_prompt_at is None:
        return None
    return WorkFinishState(
        work_date=work_date,
        end_at=end_at,
        status=status,
        prompt_kind=prompt_kind,
        prompt_started_at=prompt_started_at,
        next_prompt_at=next_prompt_at,
        prompt_timing=prompt_timing,
    )


def _next_hour_node(end_at: datetime, now: datetime) -> datetime:
    elapsed_hours = max(0.0, (now - end_at).total_seconds() / 3600)
    return end_at + timedelta(hours=max(1, floor(elapsed_hours) + 1))


def _datetime_text(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _required_text(value: Mapping[object, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ValueError(key)
    return item


def _optional_text(value: object) -> str | None:
    if value is None or isinstance(value, str):
        return value
    raise TypeError("expected optional string")


def _optional_datetime(value: object) -> datetime | None:
    text = _optional_text(value)
    return datetime.fromisoformat(text) if text else None


__all__ = [
    "PROMPT_TIMEOUT",
    "WorkFinishState",
    "WorkFinishTransition",
    "advance_work_finish",
    "continue_overtime",
    "finish_work",
    "overtime_duration",
    "state_from_dict",
    "state_to_dict",
]
