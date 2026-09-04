"""把无语义道具定义解析为当前宠物可触发的动作。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

from petnest.core.fallback_resolver import FallbackResolver, GLOBAL_PLACEHOLDER
from petnest.models.pet_package import (
    AnimationDefinition,
    HoldPlayDefinition,
    HoldPlayTargetDefinition,
    InteractionItemDefinition,
    PetPackage,
)


INTERACTION_ITEM_EVENT_PREFIX = "interaction.item."


def interaction_item_event(identifier: str) -> str:
    """返回互动道具对应的通用事件名。"""
    return f"{INTERACTION_ITEM_EVENT_PREFIX}{identifier}"


@dataclass(frozen=True, slots=True)
class ResolvedInteractionItem:
    """一个已经解析到可播放宠物动作的互动道具。"""

    definition: InteractionItemDefinition
    event_name: str | None
    action_name: str | None


class InteractionItemResolver:
    """过滤并解析当前宠物包中真正可用的互动道具。"""

    def resolve(
        self,
        package: PetPackage,
        *,
        definitions: Sequence[InteractionItemDefinition] | None = None,
        bindings: Mapping[str, str] | None = None,
        animations: Mapping[str, AnimationDefinition] | None = None,
    ) -> tuple[ResolvedInteractionItem, ...]:
        source_definitions = tuple(definitions) if definitions is not None else package.interaction_items
        source_bindings = bindings if bindings is not None else package.bindings
        source_animations = animations if animations is not None else package.animations
        pet_actions = {
            name for name, definition in source_animations.items() if definition.scope == "pet"
        }
        fallback_resolver = FallbackResolver(package.fallbacks)

        resolved: list[ResolvedInteractionItem] = []
        for definition in source_definitions:
            event_name = interaction_item_event(definition.identifier)
            requested = source_bindings.get(event_name)
            action_name: str | None = None
            if requested is not None:
                candidate = fallback_resolver.resolve(requested, pet_actions)
                action = source_animations.get(candidate)
                if candidate != GLOBAL_PLACEHOLDER and action is not None and action.scope == "pet":
                    action_name = candidate
            hold_play = _resolve_hold_play(
                definition.hold_play,
                pet_actions,
                source_animations,
                fallback_resolver,
            )
            if action_name is None and hold_play is None:
                continue
            resolved.append(
                ResolvedInteractionItem(
                    replace(definition, hold_play=hold_play),
                    event_name if action_name is not None else None,
                    action_name,
                )
            )
        return tuple(resolved)


def _resolve_hold_play(
    configured: HoldPlayDefinition | None,
    pet_actions: set[str],
    animations: Mapping[str, AnimationDefinition],
    fallback_resolver: FallbackResolver,
) -> HoldPlayDefinition | None:
    if configured is None:
        return None
    ready_action = fallback_resolver.resolve(configured.ready_action, pet_actions)
    ready = animations.get(ready_action)
    if ready_action == GLOBAL_PLACEHOLDER or ready is None or ready.scope != "pet":
        return None

    explicit: dict[str, HoldPlayTargetDefinition] = {}
    for direction, target in configured.targets.items():
        action_name = fallback_resolver.resolve(target.action, pet_actions)
        action = animations.get(action_name)
        if action_name == GLOBAL_PLACEHOLDER or action is None or action.scope != "pet":
            continue
        explicit[direction] = replace(target, action=action_name)
    center = explicit.get("center")
    if center is None:
        return None
    left = explicit.get("left", center)
    right = explicit.get("right", center)
    targets = {
        "center": center,
        "left": left,
        "right": right,
        "up_left": explicit.get("up_left", left),
        "up_right": explicit.get("up_right", right),
    }
    return replace(
        configured,
        ready_action=ready_action,
        targets=targets,  # type: ignore[arg-type]
    )


__all__ = [
    "INTERACTION_ITEM_EVENT_PREFIX",
    "InteractionItemResolver",
    "ResolvedInteractionItem",
    "interaction_item_event",
]
