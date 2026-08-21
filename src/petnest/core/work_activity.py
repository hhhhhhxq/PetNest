"""Arbitrate Codex and keyboard sources that share the working animation."""

from __future__ import annotations

from collections.abc import Callable

from petnest.models.event import PetEvent


_CODEX_STATES = {
    "agent.idle": "idle",
    "agent.working": "running",
    "agent.waiting": "waiting",
    "agent.error": "failed",
    "agent.success": "review",
}


class WorkActivityCoordinator:
    """Publish one effective pet event without merging source lifetimes."""

    def __init__(self, publish: Callable[[PetEvent], object]) -> None:
        self._publish = publish
        self.codex_state = "idle"
        self.keyboard_active = False
        self.review_animation_finished = True
        self.effective_event = "agent.idle"

    def handle_codex_event(self, event: PetEvent) -> None:
        state = _CODEX_STATES.get(event.event_name)
        if state is None:
            self._publish(event)
            return
        self.codex_state = state
        self.review_animation_finished = state != "review"
        self._emit_effective(priority=event.priority)

    def keyboard_activity_started(self) -> None:
        if self.keyboard_active:
            return
        self.keyboard_active = True
        self._emit_effective(priority=40)

    def keyboard_activity_stopped(self) -> None:
        if not self.keyboard_active:
            return
        self.keyboard_active = False
        self._emit_effective(priority=40)

    def finish_codex_review_animation(self) -> None:
        if self.codex_state != "review" or self.review_animation_finished:
            return
        self.review_animation_finished = True
        self._emit_effective(priority=100)

    def reset_keyboard(self) -> None:
        self.keyboard_activity_stopped()

    def _desired_event(self) -> str:
        if self.codex_state == "waiting":
            return "agent.waiting"
        if self.codex_state == "failed":
            return "agent.error"
        if self.codex_state == "review" and not self.review_animation_finished:
            return "agent.success"
        if self.codex_state == "running" or self.keyboard_active:
            return "agent.working"
        return "agent.idle"

    def _emit_effective(self, *, priority: int) -> None:
        desired = self._desired_event()
        if desired == self.effective_event:
            return
        self.effective_event = desired
        self._publish(PetEvent(desired, source="work-activity", priority=priority))


__all__ = ["WorkActivityCoordinator"]
