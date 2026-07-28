"""将系统空闲秒数转换为不重复的宠物状态事件。"""

from __future__ import annotations

from enum import StrEnum


class SystemIdleState(StrEnum):
    ACTIVE = "active"
    BORED = "bored"
    SLEEPING = "sleeping"


class SystemIdleMonitor:
    """只在跨越空闲阈值或恢复输入时产生一次事件。"""

    def __init__(self, *, bored_seconds: int = 30, sleep_seconds: int = 180) -> None:
        if bored_seconds <= 0:
            raise ValueError("无聊阈值必须大于 0")
        if sleep_seconds <= bored_seconds:
            raise ValueError("睡眠阈值必须大于无聊阈值")
        self.bored_seconds = bored_seconds
        self.sleep_seconds = sleep_seconds
        self._state = SystemIdleState.ACTIVE

    @property
    def state(self) -> SystemIdleState:
        return self._state

    def update(self, idle_seconds: float) -> str | None:
        """消化空闲秒数，并在状态变化时返回对应事件名。"""
        if idle_seconds < 0:
            raise ValueError("空闲秒数不能为负数")
        target = (
            SystemIdleState.SLEEPING if idle_seconds >= self.sleep_seconds
            else SystemIdleState.BORED if idle_seconds >= self.bored_seconds
            else SystemIdleState.ACTIVE
        )
        previous = self._state
        self._state = target
        if target == previous:
            return None
        if target == SystemIdleState.BORED:
            return "system.bored"
        if target == SystemIdleState.SLEEPING:
            return "system.sleep"
        return "system.wake"

    def reset(self) -> None:
        """禁用监控或换宠物时回到活动状态，不补发唤醒事件。"""
        self._state = SystemIdleState.ACTIVE
