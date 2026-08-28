"""为下班全屏提醒选择当前宠物的动画帧。"""

from __future__ import annotations

from dataclasses import dataclass

from petnest.models.pet_package import AnimationDefinition, PetPackage


@dataclass(frozen=True, slots=True)
class WorkFinishAnimationSet:
    """一次提醒使用的走入和躺下动作。"""

    walk: AnimationDefinition | None
    lie_down: AnimationDefinition | None
    lie_loop: AnimationDefinition | None
    is_specialized: bool
    entrance_direction: str


def resolve_work_finish_animation(
    package: PetPackage,
    *,
    fallback_entrance_direction: str = "right",
) -> WorkFinishAnimationSet:
    """优先使用成对的全屏动作，否则只从当前宠物普通动作回退。"""
    walk = package.animations.get("work_finish_walk")
    lie_down = package.animations.get("work_finish_lie_down")
    lie_loop = package.animations.get("work_finish_lie_loop")
    if (
        walk is not None
        and lie_down is not None
        and walk.scope == "fullscreen"
        and lie_down.scope == "fullscreen"
    ):
        valid_loop = lie_loop if lie_loop is not None and lie_loop.scope == "fullscreen" else None
        return WorkFinishAnimationSet(
            walk,
            lie_down,
            valid_loop,
            True,
            _entrance_direction(walk.entrance_direction),
        )

    idle = _pet_action(package, "idle")
    entrance_direction = _entrance_direction(fallback_entrance_direction)
    directional_candidates = {
        "right": ("walk_left", "drag_left"),
        "left": ("walk_right", "drag_right"),
        "none": (),
    }[entrance_direction]
    fallback_walk = next(
        (
            action
            for name in (*directional_candidates, "walk", "drag")
            if (action := _pet_action(package, name)) is not None
        ),
        idle,
    )
    return WorkFinishAnimationSet(
        fallback_walk,
        _pet_action(package, "sleep") or idle,
        None,
        False,
        entrance_direction,
    )


def _pet_action(package: PetPackage, name: str) -> AnimationDefinition | None:
    definition = package.animations.get(name)
    return definition if definition is not None and definition.scope == "pet" else None


def _entrance_direction(value: str) -> str:
    return value if value in {"left", "right", "none"} else "right"


__all__ = ["WorkFinishAnimationSet", "resolve_work_finish_animation"]
