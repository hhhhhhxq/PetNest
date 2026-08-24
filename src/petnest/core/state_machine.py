"""由宠物包配置驱动、没有 UI 依赖的状态机。"""

from __future__ import annotations

from dataclasses import dataclass
from time import monotonic
from collections.abc import Callable
from typing import Mapping, Sequence

from petnest.core.fallback_resolver import FallbackResolver, GLOBAL_PLACEHOLDER
from petnest.models.event import PetEvent
from petnest.models.pet_package import AnimationDefinition


@dataclass(frozen=True, slots=True)
class StateTransition:
    """一次事件处理结果，可供 UI 决定是否切换播放实例。"""

    previous_action: str
    current_action: str
    changed: bool
    reason: str


class PetStateMachine:
    """根据事件绑定、动画优先级和上下文选择当前动作。"""

    def __init__(
        self,
        animations: Mapping[str, AnimationDefinition],
        bindings: Mapping[str, str],
        fallbacks: Mapping[str, Sequence[str]],
        *,
        debounce_seconds: float = 0.05,
        minimum_play_seconds: float = 0.0,
        timeout_seconds: float | None = None,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if "idle" not in animations:
            raise ValueError("状态机需要可用的 idle 动作")
        self.animations = dict(animations)
        self._bindings = dict(bindings)
        self._resolver = FallbackResolver(fallbacks)
        self._debounce_seconds = debounce_seconds
        self._minimum_play_seconds = minimum_play_seconds
        self._timeout_seconds = timeout_seconds
        self._clock = clock
        self._mouse_over = False
        self._working_context: str | None = None
        self._current_action = "idle"
        self._entered_at = clock()
        self._last_events: dict[tuple[str, str], float] = {}

    @property
    def current_action(self) -> str:
        return self._current_action

    def handle(self, event: PetEvent) -> StateTransition:
        """消化一个事件；未知或重复事件安全地保持当前动作。"""
        previous = self._current_action
        event_name = event.event_name
        event_key = (event.source, event_name)
        previous_timestamp = self._last_events.get(event_key)
        if previous_timestamp is not None and event.timestamp - previous_timestamp < self._debounce_seconds:
            return self._transition(previous, False, "debounced")
        self._last_events[event_key] = event.timestamp
        if event_name in {"agent.idle", "agent.waiting", "agent.success", "agent.error"}:
            self._working_context = None

        if event_name == "mouse.enter":
            self._mouse_over = True
        elif event_name == "mouse.leave":
            self._mouse_over = False

        requested = self._bindings.get(event_name)
        if event_name == "mouse.leave" and self._working_context in self.animations:
            requested = self._context_action()
        if requested is None:
            if event_name in {"mouse.leave", "mouse.drag_end", "agent.idle"}:
                requested = self._context_action()
            else:
                return self._transition(previous, False, "unbound")
        target = self._resolver.resolve(requested, self.animations)
        if target == GLOBAL_PLACEHOLDER:
            return self._transition(previous, False, "unavailable")
        if event_name == "agent.working":
            self._working_context = target if self.animations[target].loop else None
        forced = event_name in {"mouse.drag_end", "agent.idle"}
        if target == previous:
            return self._transition(previous, False, "already-current")
        if event_name == "agent.working" and not self.animations[previous].interruptible:
            return self._transition(previous, False, "not-interruptible")
        if not self._may_interrupt(target, event.priority, forced):
            return self._transition(previous, False, "not-interruptible")
        self._set_current(target)
        return self._transition(previous, True, "event")

    def complete_current_animation(self) -> StateTransition:
        """在单次动画结束时按照 next 或鼠标上下文恢复动作。"""
        previous = self._current_action
        definition = self.animations.get(previous)
        if definition is None or definition.loop:
            return self._transition(previous, False, "looping")
        requested = definition.next_animation
        target = self._resolver.resolve(requested, self.animations) if requested and requested != "context" else self._context_action()
        if target == GLOBAL_PLACEHOLDER or target == previous:
            return self._transition(previous, False, "no-completion-target")
        self._set_current(target)
        return self._transition(previous, True, "completed")

    def recover_if_timed_out(self) -> StateTransition:
        """可选的超时保护：卡住时恢复到当前输入上下文。"""
        previous = self._current_action
        if self._timeout_seconds is None or self._clock() - self._entered_at < self._timeout_seconds:
            return self._transition(previous, False, "not-timed-out")
        target = self._context_action()
        if target == previous:
            return self._transition(previous, False, "already-context")
        self._set_current(target)
        return self._transition(previous, True, "timed-out")

    def _may_interrupt(self, target: str, event_priority: int, forced: bool) -> bool:
        if forced:
            return True
        current = self.animations[self._current_action]
        if self._clock() - self._entered_at < self._minimum_play_seconds:
            return False
        if current.interruptible:
            return True
        # 同级关键动作（例如 success 与 error）允许互相覆盖；普通 hover
        # 的优先级仍低于 drag，因此不会中断拖拽。
        return max(event_priority, self.animations[target].priority) >= current.priority

    def _context_action(self) -> str:
        working_context = self._working_context
        if working_context is not None and working_context in self.animations:
            return working_context
        requested = "hover" if self._mouse_over else "idle"
        return self._resolver.resolve(requested, self.animations)

    def _set_current(self, action: str) -> None:
        self._current_action = action
        self._entered_at = self._clock()

    def _transition(self, previous: str, changed: bool, reason: str) -> StateTransition:
        return StateTransition(previous, self._current_action, changed, reason)
