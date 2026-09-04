from __future__ import annotations

import pytest

from petnest.core.interaction_play import HoldPlayController, HoldPlayPhase
from petnest.models.pet_package import HoldPlayDefinition, HoldPlayTargetDefinition


def _target(action: str, point: tuple[int, int]) -> HoldPlayTargetDefinition:
    return HoldPlayTargetDefinition(
        action=action,
        contact_frame=5,
        contact_point=point,
        max_correction=(12, 10),
    )


@pytest.fixture
def definition(tmp_path) -> HoldPlayDefinition:
    center = _target("pounce_center", (100, 80))
    left = _target("pounce_left", (30, 100))
    right = _target("pounce_right", (170, 100))
    return HoldPlayDefinition(
        cursor=tmp_path / "wand.png",
        cursor_hotspot=(10, 10),
        ready_action="ready",
        attack_origin=(100, 150),
        settle_ms=140,
        cooldown_ms=350,
        rearm_distance=24,
        targets={
            "center": center,
            "left": left,
            "right": right,
            "up_left": _target("pounce_up_left", (50, 40)),
            "up_right": _target("pounce_up_right", (150, 40)),
        },
    )


@pytest.mark.parametrize(
    ("point", "expected"),
    [
        ((100, 100), "center"),
        ((20, 140), "left"),
        ((180, 140), "right"),
        ((80, 60), "up_left"),
        ((120, 60), "up_right"),
    ],
)
def test_resolve_direction_uses_attack_origin(definition, point, expected) -> None:
    assert HoldPlayController(definition).resolve_direction(point) == expected


def test_stable_target_triggers_once_and_locks_direction(definition) -> None:
    controller = HoldPlayController(definition)
    assert controller.enter(now_ms=0).action == "ready"

    assert controller.move((180, 140), now_ms=10).deadline_ms == 150
    assert controller.move((175, 145), now_ms=40).deadline_ms == 150
    assert controller.tick(now_ms=149).action is None

    attack = controller.tick(now_ms=150)
    assert attack.action == "pounce_right"
    assert controller.phase is HoldPlayPhase.ATTACKING
    controller.move((80, 60), now_ms=170)
    assert controller.current_direction == "right"


def test_attack_requires_cooldown_and_target_movement_to_rearm(definition) -> None:
    controller = HoldPlayController(definition)
    controller.enter(now_ms=0)
    controller.move((180, 140), now_ms=0)
    controller.tick(now_ms=140)
    completed = controller.attack_completed(now_ms=200)
    assert completed.phase is HoldPlayPhase.COOLDOWN
    assert completed.deadline_ms == 550

    controller.move((180, 140), now_ms=300)
    assert controller.tick(now_ms=550).action is None
    controller.move((140, 140), now_ms=560)
    assert controller.tick(now_ms=699).action is None
    assert controller.tick(now_ms=700).action == "pounce_center"


def test_release_inside_waits_for_attack_only_when_drop_action_exists(definition) -> None:
    controller = HoldPlayController(definition)
    controller.enter(now_ms=0)
    controller.move((180, 140), now_ms=0)
    controller.tick(now_ms=140)

    waiting = controller.release_inside(has_drop_action=True)
    assert waiting.phase is HoldPlayPhase.PENDING_DROP
    finished = controller.attack_completed(now_ms=200)
    assert finished.phase is HoldPlayPhase.INACTIVE
    assert finished.finish_drop

    controller.enter(now_ms=300)
    controller.move((180, 140), now_ms=300)
    controller.tick(now_ms=440)
    waiting_without_drop = controller.release_inside(has_drop_action=False)
    assert waiting_without_drop.phase is HoldPlayPhase.ATTACKING
    finished_without_drop = controller.attack_completed(now_ms=500)
    assert finished_without_drop.phase is HoldPlayPhase.INACTIVE
    assert not finished_without_drop.finish_drop


def test_ready_release_leave_and_cancel_are_deterministic(definition) -> None:
    controller = HoldPlayController(definition)
    controller.enter(now_ms=0)
    assert controller.release_inside(has_drop_action=True).finish_drop

    controller.enter(now_ms=10)
    assert controller.leave().phase is HoldPlayPhase.SUSPENDED
    assert controller.release_outside().phase is HoldPlayPhase.INACTIVE

    controller.enter(now_ms=20)
    controller.move((180, 140), now_ms=20)
    assert controller.cancel().phase is HoldPlayPhase.INACTIVE
    assert controller.candidate_target is None


def test_contact_correction_is_local_and_clamped(definition) -> None:
    controller = HoldPlayController(definition)
    controller.enter(now_ms=0)
    controller.move((190, 130), now_ms=0)
    controller.tick(now_ms=140)

    assert controller.correction_for_frame(2) == (0, 0)
    assert controller.correction_for_frame(3) == (4, 3)
    assert controller.correction_for_frame(4) == (8, 7)
    assert controller.correction_for_frame(5) == (12, 10)
    assert controller.correction_for_frame(6) == (8, 7)
    assert controller.correction_for_frame(7) == (4, 3)
    assert controller.correction_for_frame(8) == (0, 0)
