"""同步、可测试的应用内事件总线。"""

from __future__ import annotations

from collections.abc import Callable

from petnest.models.event import PetEvent

EventHandler = Callable[[PetEvent], object]


class EventBus:
    """将事件来源与状态机解耦；订阅快照允许回调中取消订阅。"""

    def __init__(self) -> None:
        self._subscribers: list[EventHandler] = []

    def subscribe(self, handler: EventHandler) -> Callable[[], None]:
        """注册事件处理函数，并返回幂等取消函数。"""
        self._subscribers.append(handler)
        active = True

        def unsubscribe() -> None:
            nonlocal active
            if active:
                active = False
                try:
                    self._subscribers.remove(handler)
                except ValueError:
                    pass

        return unsubscribe

    def publish(self, event: PetEvent) -> list[object]:
        """按订阅顺序分发事件；事件处理器的返回值便于装配层使用。"""
        return [handler(event) for handler in tuple(self._subscribers)]
