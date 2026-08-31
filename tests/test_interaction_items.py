from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from petnest.core.interaction_items import (
    InteractionItemResolver,
    interaction_item_event,
)
from petnest.models.pet_package import (
    AnimationDefinition,
    Canvas,
    InteractionItemDefinition,
    PetPackage,
)


def _animation(tmp_path: Path, name: str, *, scope: str = "pet") -> AnimationDefinition:
    return AnimationDefinition(
        name=name,
        path=tmp_path,
        fps=8,
        loop=name == "idle",
        next_animation=None if name == "idle" else "context",
        priority=10 if name == "idle" else 70,
        interruptible=name == "idle",
        scope=scope,
    )


def _package(tmp_path: Path) -> PetPackage:
    item = InteractionItemDefinition("item_1", "任意道具", tmp_path / "item.png")
    return PetPackage(
        root=tmp_path,
        identifier="test_pet",
        name="Test Pet",
        version="1",
        canvas=Canvas(16, 16),
        animations={
            "idle": _animation(tmp_path, "idle"),
            "wave": _animation(tmp_path, "wave"),
            "fullscreen": _animation(tmp_path, "fullscreen", scope="fullscreen"),
        },
        bindings={"interaction.item.item_1": "wave"},
        fallbacks={},
        interaction_items=(item,),
    )


def test_item_event_uses_generic_stable_prefix() -> None:
    assert interaction_item_event("anything") == "interaction.item.anything"


def test_resolver_keeps_order_and_resolves_bound_pet_action(tmp_path: Path) -> None:
    resolved = InteractionItemResolver().resolve(_package(tmp_path))

    assert [(item.definition.identifier, item.event_name, item.action_name) for item in resolved] == [
        ("item_1", "interaction.item.item_1", "wave")
    ]


def test_resolver_uses_fallback_and_filters_unavailable_items(tmp_path: Path) -> None:
    package = _package(tmp_path)
    package = replace(
        package,
        interaction_items=(
            package.interaction_items[0],
            InteractionItemDefinition("item_2", "无绑定", tmp_path / "two.png"),
            InteractionItemDefinition("item_3", "缺失", tmp_path / "three.png"),
        ),
        bindings={
            "interaction.item.item_1": "missing_with_fallback",
            "interaction.item.item_3": "missing_without_fallback",
        },
        fallbacks={"missing_with_fallback": ("wave",)},
    )

    resolved = InteractionItemResolver().resolve(package)

    assert [item.definition.identifier for item in resolved] == ["item_1"]
    assert resolved[0].action_name == "wave"


def test_resolver_filters_fullscreen_animation(tmp_path: Path) -> None:
    package = _package(tmp_path)
    package = replace(
        package,
        bindings={"interaction.item.item_1": "fullscreen"},
    )

    assert InteractionItemResolver().resolve(package) == ()


def test_resolver_accepts_definition_binding_and_animation_overrides(tmp_path: Path) -> None:
    package = _package(tmp_path)
    override = InteractionItemDefinition("custom_1", "自定义", tmp_path / "custom.png")

    resolved = InteractionItemResolver().resolve(
        package,
        definitions=(override,),
        bindings={"interaction.item.custom_1": "custom_wave"},
        animations={"custom_wave": _animation(tmp_path, "custom_wave")},
    )

    assert [(item.definition.identifier, item.action_name) for item in resolved] == [
        ("custom_1", "custom_wave")
    ]
