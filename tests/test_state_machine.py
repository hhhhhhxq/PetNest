"""状态机的确定性行为。"""

from __future__ import annotations

from petnest.core.state_machine import PetStateMachine
from petnest.models.event import PetEvent
from petnest.models.pet_package import AnimationDefinition


def _animation(name: str, *, priority: int, loop: bool = True, interruptible: bool = True) -> AnimationDefinition:
    return AnimationDefinition(
        name=name, path=None, fps=10, loop=loop, next_animation=None,
        priority=priority, interruptible=interruptible,
    )


def _machine() -> PetStateMachine:
    animations = {
        "idle": _animation("idle", priority=10),
        "hover": _animation("hover", priority=30),
        "click": _animation("click", priority=50, loop=False, interruptible=False),
        "drag": _animation("drag", priority=80, interruptible=False),
        "drop": _animation("drop", priority=70, loop=False, interruptible=False),
        "success": _animation("success", priority=100, loop=False, interruptible=False),
        "error": _animation("error", priority=100, loop=False, interruptible=False),
    }
    return PetStateMachine(
        animations,
        {
            "mouse.enter": "hover", "mouse.leave": "idle", "mouse.click": "click",
            "mouse.drag_start": "drag", "mouse.drag_end": "drop",
            "agent.success": "success", "agent.error": "error",
        },
        {"missing": ("hover", "idle")},
    )


def test_idle_transitions_to_hover_on_mouse_enter() -> None:
    machine = _machine()
    assert machine.handle(PetEvent("mouse.enter")).current_action == "hover"


def test_hover_transitions_to_idle_click_and_drag() -> None:
    machine = _machine()
    machine.handle(PetEvent("mouse.enter"))
    assert machine.handle(PetEvent("mouse.leave")).current_action == "idle"
    machine.handle(PetEvent("mouse.enter"))
    assert machine.handle(PetEvent("mouse.click")).current_action == "click"
    machine.complete_current_animation()
    assert machine.handle(PetEvent("mouse.drag_start")).current_action == "drag"


def test_drag_is_not_interrupted_by_hover_but_ends_as_drop() -> None:
    machine = _machine()
    machine.handle(PetEvent("mouse.drag_start"))
    assert machine.handle(PetEvent("mouse.enter")).current_action == "drag"
    assert machine.handle(PetEvent("mouse.drag_end")).current_action == "drop"


def test_single_animation_completion_restores_hover_context() -> None:
    machine = _machine()
    machine.handle(PetEvent("mouse.enter"))
    machine.handle(PetEvent("mouse.click"))
    assert machine.complete_current_animation().current_action == "hover"


def test_success_and_error_take_priority_over_normal_mouse_actions() -> None:
    machine = _machine()
    machine.handle(PetEvent("mouse.drag_start"))
    assert machine.handle(PetEvent("agent.success")).current_action == "success"
    assert machine.handle(PetEvent("agent.error")).current_action == "error"


def test_duplicate_event_does_not_restart_the_same_action() -> None:
    machine = _machine()
    first = machine.handle(PetEvent("mouse.enter", timestamp=1.0))
    duplicate = machine.handle(PetEvent("mouse.enter", timestamp=1.0))
    assert first.changed is True
    assert duplicate.changed is False


def test_missing_bound_action_uses_configured_fallback() -> None:
    machine = _machine()
    machine = PetStateMachine(machine.animations, {"custom.wave": "missing"}, {"missing": ("hover", "idle")})
    assert machine.handle(PetEvent("custom.wave")).current_action == "hover"
