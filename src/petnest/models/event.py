"""与输入来源无关的事件模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from time import monotonic
from typing import Mapping


class EventName(StrEnum):
    """PetNest 内置事件名称；自定义事件仍可以使用字符串。"""

    MOUSE_ENTER = "mouse.enter"
    MOUSE_LEAVE = "mouse.leave"
    MOUSE_CLICK = "mouse.click"
    MOUSE_DRAG_START = "mouse.drag_start"
    MOUSE_DRAG_MOVE = "mouse.drag_move"
    MOUSE_DRAG_END = "mouse.drag_end"
    APP_START = "app.start"
    APP_PAUSE = "app.pause"
    APP_RESUME = "app.resume"
    APP_QUIT = "app.quit"
    SYSTEM_IDLE = "system.idle"
    SYSTEM_BORED = "system.bored"
    SYSTEM_ACTIVE = "system.active"
    SYSTEM_LOCK = "system.lock"
    SYSTEM_UNLOCK = "system.unlock"
    SYSTEM_SLEEP = "system.sleep"
    SYSTEM_WAKE = "system.wake"
    AGENT_THINKING = "agent.thinking"
    AGENT_WORKING = "agent.working"
    AGENT_WAITING = "agent.waiting"
    AGENT_SUCCESS = "agent.success"
    AGENT_ERROR = "agent.error"
    AGENT_IDLE = "agent.idle"
    INTERACTION_MESSAGE = "interaction.message"


@dataclass(frozen=True, slots=True)
class PetEvent:
    """提交给状态机的安全事件，不持久化 payload。"""

    name: str | EventName
    source: str = "application"
    timestamp: float = field(default_factory=monotonic)
    payload: Mapping[str, object] = field(default_factory=dict)
    priority: int = 0

    @property
    def event_name(self) -> str:
        """始终以字符串形式提供事件名，便于读取宠物包绑定。"""
        return str(self.name)
