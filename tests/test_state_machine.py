"""状态机的确定性行为。"""

from __future__ import annotations

import pytest

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
        "working": _animation("working", priority=60),
        "click": _animation("click", priority=50, loop=False, interruptible=False),
        "drag": _animation("drag", priority=80, interruptible=False),
        "drop": _animation("drop", priority=70, loop=False, interruptible=False),
        "waiting": _animation("waiting", priority=100, loop=False, interruptible=False),
        "success": _animation("success", priority=100, loop=False, interruptible=False),
        "error": _animation("error", priority=100, loop=False, interruptible=False),
    }
    return PetStateMachine(
        animations,
        {
            "mouse.enter": "hover", "mouse.leave": "idle", "mouse.click": "click",
            "mouse.drag_start": "drag", "mouse.drag_end": "drop",
            "agent.working": "working", "agent.waiting": "waiting",
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


def test_unbound_drag_end_forces_drag_to_restore_pointer_context() -> None:
    animations = {
        "idle": _animation("idle", priority=10),
        "hover": _animation("hover", priority=30),
        "drag": _animation("drag", priority=80, interruptible=False),
    }
    machine = PetStateMachine(
        animations,
        {"mouse.enter": "hover", "mouse.drag_start": "drag"},
        {},
    )

    machine.handle(PetEvent("mouse.drag_start", timestamp=1.0))
    released = machine.handle(PetEvent("mouse.drag_end", timestamp=2.0))
    assert released.changed
    assert released.current_action == "idle"

    machine.handle(PetEvent("mouse.enter", timestamp=3.0))
    machine.handle(PetEvent("mouse.drag_start", timestamp=4.0))
    assert machine.handle(PetEvent("mouse.drag_end", timestamp=5.0)).current_action == "hover"


def test_agent_idle_forces_attention_animation_back_to_pointer_context() -> None:
    machine = _machine()
    machine.handle(PetEvent("agent.success", timestamp=1.0))

    transition = machine.handle(PetEvent("agent.idle", timestamp=2.0))

    assert transition.changed
    assert transition.current_action == "idle"


def test_working_context_is_restored_after_click_completion() -> None:
    machine = _machine()
    machine.handle(PetEvent("agent.working", timestamp=1.0))
    machine.handle(PetEvent("mouse.enter", timestamp=2.0))
    machine.handle(PetEvent("mouse.click", timestamp=3.0))

    assert machine.complete_current_animation().current_action == "working"


def test_working_context_is_restored_after_drag_drop_completion() -> None:
    machine = _machine()
    machine.handle(PetEvent("agent.working", timestamp=1.0))
    machine.handle(PetEvent("mouse.drag_start", timestamp=2.0))
    machine.handle(PetEvent("mouse.drag_end", timestamp=3.0))

    assert machine.complete_current_animation().current_action == "working"


def test_mouse_hover_is_temporary_when_working_context_is_active() -> None:
    machine = _machine()
    machine.handle(PetEvent("agent.working", timestamp=1.0))

    assert machine.handle(PetEvent("mouse.enter", timestamp=2.0)).current_action == "hover"
    assert machine.handle(PetEvent("mouse.leave", timestamp=3.0)).current_action == "working"


def test_mouse_leave_respects_explicit_binding_without_working_context() -> None:
    source = _machine()
    animations = {**source.animations, "custom_leave": _animation("custom_leave", priority=20)}
    machine = PetStateMachine(animations, {"mouse.leave": "custom_leave"}, {})

    assert machine.handle(PetEvent("mouse.leave", timestamp=1.0)).current_action == "custom_leave"


def test_mouse_leave_restores_working_instead_of_its_explicit_binding() -> None:
    source = _machine()
    animations = {**source.animations, "custom_leave": _animation("custom_leave", priority=20)}
    machine = PetStateMachine(
        animations,
        {"agent.working": "working", "mouse.enter": "hover", "mouse.leave": "custom_leave"},
        {},
    )
    machine.handle(PetEvent("agent.working", timestamp=1.0))
    machine.handle(PetEvent("mouse.enter", timestamp=2.0))

    assert machine.handle(PetEvent("mouse.leave", timestamp=3.0)).current_action == "working"


def test_agent_idle_respects_explicit_binding_and_clears_working_context() -> None:
    source = _machine()
    animations = {
        **source.animations,
        "custom_agent_idle": _animation("custom_agent_idle", priority=20, loop=False),
    }
    machine = PetStateMachine(
        animations,
        {"agent.working": "working", "agent.idle": "custom_agent_idle"},
        {},
    )
    machine.handle(PetEvent("agent.working", timestamp=1.0))

    assert machine.handle(PetEvent("agent.idle", timestamp=2.0)).current_action == "custom_agent_idle"
    assert machine.complete_current_animation().current_action == "idle"


def test_working_event_during_noninterruptible_click_is_restored_on_completion() -> None:
    machine = _machine()
    machine.handle(PetEvent("mouse.click", timestamp=1.0))

    assert machine.handle(PetEvent("agent.working", timestamp=2.0)).current_action == "click"
    assert machine.complete_current_animation().current_action == "working"


def test_working_does_not_interrupt_noninterruptible_drag() -> None:
    machine = _machine()
    machine.handle(PetEvent("mouse.drag_start", timestamp=1.0))

    assert machine.handle(PetEvent("agent.working", timestamp=2.0)).current_action == "drag"
    machine.handle(PetEvent("mouse.drag_end", timestamp=3.0))
    assert machine.complete_current_animation().current_action == "working"


def test_working_does_not_interrupt_noninterruptible_success() -> None:
    machine = _machine()
    machine.handle(PetEvent("agent.success", timestamp=1.0))

    assert machine.handle(PetEvent("agent.working", timestamp=2.0)).current_action == "success"
    assert machine.complete_current_animation().current_action == "working"


def test_agent_idle_clears_working_context_before_a_later_click_completes() -> None:
    machine = _machine()
    machine.handle(PetEvent("agent.working", timestamp=1.0))
    machine.handle(PetEvent("agent.idle", timestamp=2.0))
    machine.handle(PetEvent("mouse.click", timestamp=3.0))

    assert machine.complete_current_animation().current_action == "idle"


@pytest.mark.parametrize("event_name", ["agent.waiting", "agent.success", "agent.error"])
def test_terminal_agent_events_clear_previous_working_context(event_name: str) -> None:
    machine = _machine()
    machine.handle(PetEvent("agent.working", timestamp=1.0))
    machine.handle(PetEvent(event_name, timestamp=2.0))

    assert machine.complete_current_animation().current_action == "idle"


def test_debounced_success_does_not_clear_working_context() -> None:
    machine = _machine()
    machine.handle(PetEvent("agent.success", timestamp=1.0))
    machine.handle(PetEvent("agent.working", timestamp=1.005))

    transition = machine.handle(PetEvent("agent.success", timestamp=1.01))

    assert transition.reason == "debounced"
    assert machine.complete_current_animation().current_action == "working"


def test_new_working_event_reestablishes_context_after_success() -> None:
    machine = _machine()
    machine.handle(PetEvent("agent.working", timestamp=1.0))
    machine.handle(PetEvent("agent.success", timestamp=2.0))
    machine.complete_current_animation()
    machine.handle(PetEvent("agent.working", timestamp=3.0))
    machine.handle(PetEvent("mouse.click", timestamp=4.0))

    assert machine.complete_current_animation().current_action == "working"


@pytest.mark.parametrize(
    ("bindings", "fallbacks", "expected_reason"),
    [
        ({}, {}, "unbound"),
        ({"agent.working": "missing"}, {}, "unavailable"),
    ],
)
def test_unbound_or_unavailable_working_does_not_create_context(
    bindings: dict[str, str], fallbacks: dict[str, tuple[str, ...]], expected_reason: str,
) -> None:
    source = _machine()
    machine = PetStateMachine(source.animations, bindings, fallbacks)

    transition = machine.handle(PetEvent("agent.working", timestamp=1.0))
    machine.handle(PetEvent("mouse.click", timestamp=2.0))

    assert transition.reason == expected_reason
    assert machine.complete_current_animation().current_action == "idle"


def test_working_fallback_to_idle_remains_idle_context() -> None:
    source = _machine()
    machine = PetStateMachine(
        source.animations,
        {"agent.working": "missing", "mouse.click": "click"},
        {"missing": ("idle",)},
    )

    assert machine.handle(PetEvent("agent.working", timestamp=1.0)).current_action == "idle"
    machine.handle(PetEvent("mouse.click", timestamp=2.0))
    assert machine.complete_current_animation().current_action == "idle"


def test_nonloop_working_fallback_does_not_persist_as_context() -> None:
    source = _machine()
    machine = PetStateMachine(
        source.animations,
        {"agent.working": "missing"},
        {"missing": ("click",)},
    )

    assert machine.handle(PetEvent("agent.working", timestamp=1.0)).current_action == "click"
    assert machine.complete_current_animation().current_action == "idle"
