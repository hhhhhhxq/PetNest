"""为下班全屏提醒选择当前宠物的动画帧。"""

from __future__ import annotations

from dataclasses import dataclass

from petnest.models.pet_package import AnimationDefinition, PetPackage


@dataclass(frozen=True, slots=True)
class WorkFinishAnimationSet:
    """一次提醒使用的走入和躺下动作。"""

    walk: AnimationDefinition | None
    lie_down: AnimationDefinition | None
    is_specialized: bool


def resolve_work_finish_animation(package: PetPackage) -> WorkFinishAnimationSet:
    """优先使用成对的全屏动作，否则只从当前宠物普通动作回退。"""
    walk = package.animations.get("work_finish_walk")
    lie_down = package.animations.get("work_finish_lie_down")
    if (
        walk is not None
        and lie_down is not None
        and walk.scope == "fullscreen"
        and lie_down.scope == "fullscreen"
    ):
        return WorkFinishAnimationSet(walk, lie_down, True)

    idle = _pet_action(package, "idle")
    return WorkFinishAnimationSet(
        _pet_action(package, "walk") or _pet_action(package, "drag") or idle,
        _pet_action(package, "sleep") or idle,
        False,
    )


def _pet_action(package: PetPackage, name: str) -> AnimationDefinition | None:
    definition = package.animations.get(name)
    return definition if definition is not None and definition.scope == "pet" else None


__all__ = ["WorkFinishAnimationSet", "resolve_work_finish_animation"]
