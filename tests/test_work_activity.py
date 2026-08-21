"""Codex 与键盘 working 来源的纯状态仲裁。"""

from __future__ import annotations

from petnest.core.work_activity import WorkActivityCoordinator
from petnest.models.event import PetEvent


def _event(name: str, *, priority: int = 90) -> PetEvent:
    return PetEvent(name, source="codex-link", priority=priority)


def test_keyboard_stop_does_not_cancel_running_codex() -> None:
    published: list[PetEvent] = []
    coordinator = WorkActivityCoordinator(published.append)
    coordinator.handle_codex_event(_event("agent.working"))
    coordinator.keyboard_activity_started()
    published.clear()

    coordinator.keyboard_activity_stopped()

    assert published == []
    assert coordinator.effective_event == "agent.working"


def test_codex_idle_does_not_cancel_active_keyboard() -> None:
    published: list[PetEvent] = []
    coordinator = WorkActivityCoordinator(published.append)
    coordinator.keyboard_activity_started()
    published.clear()

    coordinator.handle_codex_event(_event("agent.idle"))

    assert published == []
    assert coordinator.effective_event == "agent.working"


def test_waiting_and_failed_override_keyboard_working() -> None:
    published: list[PetEvent] = []
    coordinator = WorkActivityCoordinator(published.append)
    coordinator.keyboard_activity_started()

    coordinator.handle_codex_event(_event("agent.waiting"))
    coordinator.keyboard_activity_started()
    coordinator.handle_codex_event(_event("agent.error"))

    assert [event.event_name for event in published] == [
        "agent.working",
        "agent.waiting",
        "agent.error",
    ]


def test_review_finishes_to_keyboard_working_without_changing_codex_state() -> None:
    published: list[PetEvent] = []
    coordinator = WorkActivityCoordinator(published.append)
    coordinator.keyboard_activity_started()
    coordinator.handle_codex_event(_event("agent.success", priority=100))
    published.clear()

    coordinator.finish_codex_review_animation()

    assert [event.event_name for event in published] == ["agent.working"]
    assert coordinator.codex_state == "review"


def test_review_finishes_to_idle_without_keyboard_activity() -> None:
    published: list[PetEvent] = []
    coordinator = WorkActivityCoordinator(published.append)
    coordinator.handle_codex_event(_event("agent.success", priority=100))
    published.clear()

    coordinator.finish_codex_review_animation()

    assert [event.event_name for event in published] == ["agent.idle"]


def test_repeated_keyboard_activity_does_not_restart_working() -> None:
    published: list[PetEvent] = []
    coordinator = WorkActivityCoordinator(published.append)

    coordinator.keyboard_activity_started()
    coordinator.keyboard_activity_started()
    coordinator.keyboard_activity_started()

    assert [event.event_name for event in published] == ["agent.working"]


def test_both_sources_must_end_before_idle_is_published() -> None:
    published: list[PetEvent] = []
    coordinator = WorkActivityCoordinator(published.append)
    coordinator.handle_codex_event(_event("agent.working"))
    coordinator.keyboard_activity_started()

    coordinator.handle_codex_event(_event("agent.idle"))
    assert coordinator.effective_event == "agent.working"
    coordinator.keyboard_activity_stopped()

    assert [event.event_name for event in published] == ["agent.working", "agent.idle"]


def test_unknown_codex_event_passes_through_without_changing_activity() -> None:
    published: list[PetEvent] = []
    coordinator = WorkActivityCoordinator(published.append)
    event = PetEvent("custom.event", source="test", priority=7)

    coordinator.handle_codex_event(event)

    assert published == [event]
    assert coordinator.codex_state == "idle"
