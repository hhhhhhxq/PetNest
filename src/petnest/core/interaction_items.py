"""把无语义道具定义解析为当前宠物可触发的动作。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from petnest.core.fallback_resolver import FallbackResolver, GLOBAL_PLACEHOLDER
from petnest.models.pet_package import (
    AnimationDefinition,
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
    event_name: str
    action_name: str


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
            if requested is None:
                continue
            action_name = fallback_resolver.resolve(requested, pet_actions)
            action = source_animations.get(action_name)
            if action_name == GLOBAL_PLACEHOLDER or action is None or action.scope != "pet":
                continue
            resolved.append(ResolvedInteractionItem(definition, event_name, action_name))
        return tuple(resolved)


__all__ = [
    "INTERACTION_ITEM_EVENT_PREFIX",
    "InteractionItemResolver",
    "ResolvedInteractionItem",
    "interaction_item_event",
]
