"""下班全屏动画动作解析。"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from petnest.core.work_finish_animation import resolve_work_finish_animation
from petnest.models.pet_package import Canvas
from tests.test_pet_window import _package


def _with_fullscreen_action(package, source: str, name: str):
    definition = replace(
        package.animations[source],
        name=name,
        scope="fullscreen",
        canvas=Canvas(24, 18),
    )
    return replace(package, animations={**package.animations, name: definition})


def test_resolver_prefers_complete_fullscreen_pair(tmp_path: Path) -> None:
    package = _package(tmp_path)
    package = _with_fullscreen_action(package, "idle", "work_finish_walk")
    package = _with_fullscreen_action(package, "click", "work_finish_lie_down")

    resolved = resolve_work_finish_animation(package)

    assert resolved.walk is not None
    assert resolved.walk.name == "work_finish_walk"
    assert resolved.lie_down is not None
    assert resolved.lie_down.name == "work_finish_lie_down"
    assert resolved.is_specialized


def test_resolver_uses_current_pet_drag_and_sleep_fallbacks(tmp_path: Path) -> None:
    package = _package(tmp_path)
    sleep = replace(package.animations["idle"], name="sleep")
    package = replace(package, animations={**package.animations, "sleep": sleep})

    resolved = resolve_work_finish_animation(package)

    assert resolved.walk is not None
    assert resolved.walk.name == "drag"
    assert resolved.lie_down is not None
    assert resolved.lie_down.name == "sleep"
    assert not resolved.is_specialized


def test_resolver_prefers_walk_over_drag(tmp_path: Path) -> None:
    package = _package(tmp_path)
    walk = replace(package.animations["idle"], name="walk")
    package = replace(package, animations={**package.animations, "walk": walk})

    resolved = resolve_work_finish_animation(package)

    assert resolved.walk is not None
    assert resolved.walk.name == "walk"


def test_resolver_skips_fullscreen_drag_in_ordinary_fallback(tmp_path: Path) -> None:
    package = _package(tmp_path)
    fullscreen_drag = replace(package.animations["drag"], scope="fullscreen", canvas=Canvas(24, 18))
    package = replace(package, animations={**package.animations, "drag": fullscreen_drag})

    resolved = resolve_work_finish_animation(package)

    assert resolved.walk is not None
    assert resolved.walk.name == "idle"


def test_incomplete_fullscreen_pair_never_leaks_another_pet_animation(tmp_path: Path) -> None:
    package = _with_fullscreen_action(_package(tmp_path), "idle", "work_finish_walk")

    resolved = resolve_work_finish_animation(package)

    assert resolved.walk is not None
    assert resolved.walk.name == "drag"
    assert resolved.lie_down is not None
    assert resolved.lie_down.name == "idle"
    assert not resolved.is_specialized
