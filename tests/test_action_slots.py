"""可触发动作槽位、绑定解析和默认动画字段测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from petnest.core.action_slots import (
    action_slot,
    action_slots,
    action_trigger_label,
    resolve_slot,
    resolve_slot_import_target,
    validate_action_name,
)
from petnest.models.pet_package import AnimationDefinition, Canvas, PetPackage


EXPECTED_KEYS = {
    "idle",
    "mouse_hover",
    "mouse_click",
    "mouse_drag",
    "mouse_drop",
    "move_walk",
    "move_walk_left",
    "move_walk_right",
    "move_walk_up",
    "move_walk_down",
    "move_drag_left",
    "move_drag_right",
    "move_drag_up",
    "move_drag_down",
    "agent_working",
    "agent_waiting",
    "agent_success",
    "agent_error",
    "system_bored",
    "system_sleep",
    "system_wake",
    "work_finish_walk",
    "work_finish_lie_down",
    "work_finish_lie_loop",
}


def _package(
    tmp_path: Path,
    bindings: dict[str, str] | None = None,
    animations: tuple[str, ...] = (),
) -> PetPackage:
    definitions = {
        name: AnimationDefinition(name, tmp_path, 8, True, None, 10, True)
        for name in animations
    }
    return PetPackage(
        tmp_path,
        "pet",
        "Pet",
        "1.0.0",
        Canvas(256, 256),
        definitions,
        bindings or {},
        {},
    )


def test_registry_contains_only_runtime_triggerable_slots() -> None:
    slots = action_slots()

    assert {slot.key for slot in slots} == EXPECTED_KEYS
    assert len(slots) == len(EXPECTED_KEYS)
    assert all(slot.label and slot.category and slot.canonical_action for slot in slots)
    assert "custom" not in {slot.key for slot in slots}
    assert "codex_running_left" not in {slot.canonical_action for slot in slots}


def test_success_slot_uses_current_pet_binding(tmp_path: Path) -> None:
    package = _package(tmp_path, {"agent.success": "success"}, ("success",))

    resolution = resolve_slot(package, action_slot("agent_success"))

    assert resolution.action_name == "success"
    assert resolution.binding is None
    assert action_trigger_label(package, "success") == "任务完成"


def test_unbound_success_slot_uses_review_and_requests_binding(tmp_path: Path) -> None:
    resolution = resolve_slot(_package(tmp_path), action_slot("agent_success"))

    assert resolution.action_name == "review"
    assert resolution.binding == ("agent.success", "review")


def test_bound_event_import_target_does_not_follow_runtime_fallback(tmp_path: Path) -> None:
    package = _package(tmp_path, {"agent.success": "success"}, ("celebrate",))
    package = PetPackage(
        package.root,
        package.identifier,
        package.name,
        package.version,
        package.canvas,
        package.animations,
        package.bindings,
        {"success": ("celebrate",)},
    )

    runtime_resolution = resolve_slot(package, action_slot("agent_success"))

    assert runtime_resolution.action_name == "celebrate"
    assert runtime_resolution.binding is None
    assert action_trigger_label(package, "celebrate") == "任务完成"
    import_resolution = resolve_slot_import_target(package, action_slot("agent_success"))

    assert import_resolution.action_name == "success"
    assert import_resolution.binding is None


@pytest.mark.parametrize("unsafe", ["../../outside", "C:\\outside", "NUL", "bad/name"])
def test_unsafe_or_missing_bound_action_is_never_used_as_an_output_path(
    tmp_path: Path, unsafe: str
) -> None:
    package = _package(tmp_path, {"agent.success": unsafe})

    resolution = resolve_slot(package, action_slot("agent_success"))
    import_resolution = resolve_slot_import_target(package, action_slot("agent_success"))

    assert resolution.action_name == "review"
    assert resolution.binding == ("agent.success", "review")
    assert import_resolution.action_name == "review"
    assert import_resolution.binding == ("agent.success", "review")
    with pytest.raises(ValueError, match="不安全"):
        validate_action_name(unsafe)


def test_direct_runtime_slot_never_creates_event_binding(tmp_path: Path) -> None:
    resolution = resolve_slot(_package(tmp_path), action_slot("move_walk_left"))

    assert resolution.action_name == "walk_left"
    assert resolution.binding is None


def test_slot_defaults_match_continuous_transient_and_fullscreen_semantics() -> None:
    working = action_slot("agent_working")
    click = action_slot("mouse_click")
    finish = action_slot("work_finish_lie_down")

    assert working.loop is True
    assert working.next_animation is None
    assert click.loop is False
    assert click.next_animation == "context"
    assert finish.scope == "fullscreen"
    assert finish.loop is False
    assert finish.next_animation is None


def test_unknown_existing_animation_is_not_presented_as_creatable_custom_action(tmp_path: Path) -> None:
    assert action_trigger_label(_package(tmp_path), "legacy_wave") == "未绑定到 PetNest 触发时机"


def test_legacy_codex_directional_action_keeps_accurate_editor_label(tmp_path: Path) -> None:
    assert action_trigger_label(_package(tmp_path), "codex_running_left") == "旧版 Codex 左向拖动动作"
