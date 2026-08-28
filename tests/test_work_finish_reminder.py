"""全屏下班动画窗口和独立控制面板。"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from PySide6.QtCore import QRect, Qt

from petnest.core.work_finish_animation import resolve_work_finish_animation
from petnest.models.pet_package import Canvas
from petnest.ui.work_finish_reminder import WorkFinishReminder
from tests.test_pet_window import _package


def _with_fullscreen_pair(package, direction: str, *, include_loop: bool = False):
    walk = replace(
        package.animations["idle"],
        name="work_finish_walk",
        scope="fullscreen",
        canvas=Canvas(24, 18),
        entrance_direction=direction,
    )
    lie_down = replace(
        package.animations["idle"],
        name="work_finish_lie_down",
        scope="fullscreen",
        canvas=Canvas(24, 18),
    )
    animations = {**package.animations, "work_finish_walk": walk, "work_finish_lie_down": lie_down}
    if include_loop:
        animations["work_finish_lie_loop"] = replace(
            package.animations["hover"],
            name="work_finish_lie_loop",
            scope="fullscreen",
            canvas=Canvas(24, 18),
            loop=True,
        )
    return replace(package, animations=animations)


def _with_directional_fallbacks(package):
    source = package.animations["drag"]
    return replace(
        package,
        animations={
            **package.animations,
            "walk_left": replace(source, name="walk_left"),
            "walk_right": replace(source, name="walk_right"),
            "drag_left": replace(source, name="drag_left"),
            "drag_right": replace(source, name="drag_right"),
        },
    )


@pytest.mark.parametrize(
    ("entrance_direction", "expected"),
    [("right", "walk_left"), ("left", "walk_right"), ("none", "drag")],
)
def test_pet_fallback_matches_motion_to_entrance_direction(tmp_path: Path, entrance_direction: str, expected: str) -> None:
    animation = resolve_work_finish_animation(
        _with_directional_fallbacks(_package(tmp_path)),
        fallback_entrance_direction=entrance_direction,
    )

    assert animation.walk is not None
    assert animation.walk.name == expected
    assert animation.entrance_direction == entrance_direction


@pytest.mark.parametrize(
    ("entrance_direction", "expected"),
    [("right", "drag_left"), ("left", "drag_right")],
)
def test_directional_drag_precedes_generic_drag_when_directional_walk_is_missing(
    tmp_path: Path,
    entrance_direction: str,
    expected: str,
) -> None:
    package = _package(tmp_path)
    source = package.animations["drag"]
    package = replace(
        package,
        animations={
            **package.animations,
            "drag_left": replace(source, name="drag_left"),
            "drag_right": replace(source, name="drag_right"),
        },
    )

    animation = resolve_work_finish_animation(package, fallback_entrance_direction=entrance_direction)

    assert animation.walk is not None
    assert animation.walk.name == expected


def test_reminder_uses_full_screen_and_ninety_two_percent_frame_width(qtbot, tmp_path: Path) -> None:
    geometry = QRect(100, 50, 1000, 800)
    reminder = WorkFinishReminder()
    qtbot.addWidget(reminder.animation_window)
    qtbot.addWidget(reminder.control_window)

    reminder.show_for(
        _package(tmp_path),
        geometry,
        datetime(2026, 8, 14, 18, 0),
        available_geometry=QRect(100, 50, 1000, 760),
    )

    assert reminder.animation_window.geometry() == geometry
    assert reminder.animation_window.target_frame_width == 920
    assert reminder.animation_window.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    assert reminder.animation_window.windowFlags() & Qt.WindowType.WindowTransparentForInput
    assert reminder.animation_window.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    assert reminder.control_window.pos().x() == 124
    assert reminder.control_window.pos().y() == 74
    assert reminder.animation_window.isVisible()
    assert reminder.control_window.isVisible()
    reminder.hide()


def test_animation_moves_from_offscreen_right_to_center_and_holds_last_lie_frame(qtbot, tmp_path: Path) -> None:
    now = [0.0]
    reminder = WorkFinishReminder(clock=lambda: now[0])
    qtbot.addWidget(reminder.animation_window)
    qtbot.addWidget(reminder.control_window)
    reminder.show_for(_package(tmp_path), QRect(0, 0, 1000, 800), datetime(2026, 8, 14, 18, 0))

    reminder.animation_window._refresh_frame()
    start = reminder.animation_window.current_frame_rect()
    assert start.left() == 1000

    now[0] = 4.0
    reminder.animation_window._refresh_frame()
    centered = reminder.animation_window.current_frame_rect()
    assert abs(centered.center().x() - 500) <= 1

    now[0] = 20.0
    reminder.animation_window._refresh_frame()
    assert reminder.animation_window.current_phase == "holding"
    assert reminder.animation_window.current_frame_index == 1
    reminder.hide()


def test_animation_starts_optional_lie_loop_at_zero_then_repeats(qtbot, tmp_path: Path) -> None:
    now = [0.0]
    reminder = WorkFinishReminder(clock=lambda: now[0])
    qtbot.addWidget(reminder.animation_window)
    qtbot.addWidget(reminder.control_window)
    package = _with_fullscreen_pair(_package(tmp_path), "right", include_loop=True)
    reminder.show_for(package, QRect(0, 0, 1000, 800), datetime(2026, 8, 14, 18, 0))

    now[0] = 4.201
    reminder.animation_window._refresh_frame()
    assert reminder.animation_window.current_phase == "lying_loop"
    assert reminder.animation_window.current_frame_index == 0

    now[0] = 4.301
    reminder.animation_window._refresh_frame()
    assert reminder.animation_window.current_frame_index == 1

    now[0] = 4.401
    reminder.animation_window._refresh_frame()
    assert reminder.animation_window.current_frame_index == 0
    reminder.hide()


def test_animation_moves_from_offscreen_left_to_center(qtbot, tmp_path: Path) -> None:
    now = [0.0]
    reminder = WorkFinishReminder(clock=lambda: now[0])
    qtbot.addWidget(reminder.animation_window)
    qtbot.addWidget(reminder.control_window)
    reminder.show_for(
        _with_fullscreen_pair(_package(tmp_path), "left"),
        QRect(0, 0, 1000, 800),
        datetime(2026, 8, 14, 18, 0),
    )

    assert reminder.animation_window.current_frame_rect().right() < 0

    now[0] = 4.0
    reminder.animation_window._refresh_frame()
    centered = reminder.animation_window.current_frame_rect()
    assert abs(centered.center().x() - 500) <= 1
    reminder.hide()


def test_pet_fallback_direction_is_forwarded_to_animation_window(qtbot, tmp_path: Path) -> None:
    reminder = WorkFinishReminder(clock=lambda: 0.0)
    qtbot.addWidget(reminder.animation_window)
    qtbot.addWidget(reminder.control_window)

    reminder.show_for(
        _with_directional_fallbacks(_package(tmp_path)),
        QRect(0, 0, 1000, 800),
        datetime(2026, 8, 14, 18, 0),
        fallback_entrance_direction="left",
    )

    assert reminder.animation_window._entrance_direction == "left"
    assert reminder.animation_window.current_frame_rect().right() < 0
    reminder.hide()


def test_animation_with_none_direction_starts_centered(qtbot, tmp_path: Path) -> None:
    reminder = WorkFinishReminder()
    qtbot.addWidget(reminder.animation_window)
    qtbot.addWidget(reminder.control_window)
    reminder.show_for(
        _with_fullscreen_pair(_package(tmp_path), "none"),
        QRect(0, 0, 1000, 800),
        datetime(2026, 8, 14, 18, 0),
    )

    rect = reminder.animation_window.current_frame_rect()

    assert abs(rect.center().x() - 500) <= 1
    reminder.hide()


def test_reused_animation_window_stays_transparent_until_new_pet_frame_is_painted(qtbot, tmp_path: Path) -> None:
    reminder = WorkFinishReminder()
    qtbot.addWidget(reminder.animation_window)
    qtbot.addWidget(reminder.control_window)
    previous_pet = _with_fullscreen_pair(
        _package(tmp_path, identifier="previous", colour=(255, 0, 0, 255)),
        "none",
    )
    current_pet = _with_fullscreen_pair(
        _package(tmp_path, identifier="current", colour=(0, 0, 255, 255)),
        "none",
    )

    reminder.show_for(previous_pet, QRect(0, 0, 1000, 800), datetime.now())
    qtbot.waitUntil(lambda: reminder.animation_window.windowOpacity() == 1.0)
    reminder.hide()

    reminder.animation_window.setUpdatesEnabled(False)
    reminder.show_for(current_pet, QRect(0, 0, 1000, 800), datetime.now())

    assert reminder.animation_window.windowOpacity() == 0.0
    qtbot.wait(25)
    assert reminder.animation_window.windowOpacity() == 0.0

    reminder.animation_window.setUpdatesEnabled(True)
    reminder.animation_window.repaint()
    qtbot.waitUntil(lambda: reminder.animation_window.windowOpacity() == 1.0)
    rendered = reminder.animation_window.grab().toImage()
    center = rendered.pixelColor(rendered.rect().center())
    assert center.blue() > center.red()
    reminder.hide()


def test_stale_first_paint_reveal_cannot_unlock_the_next_pet(qtbot, tmp_path: Path) -> None:
    reminder = WorkFinishReminder()
    qtbot.addWidget(reminder.animation_window)
    qtbot.addWidget(reminder.control_window)
    previous_pet = _package(tmp_path, identifier="previous")
    current_pet = _package(tmp_path, identifier="current")

    reminder.animation_window.setUpdatesEnabled(False)
    reminder.show_for(previous_pet, QRect(0, 0, 1000, 800), datetime.now())
    stale_generation = reminder.animation_window._display_generation
    reminder.hide()
    reminder.show_for(current_pet, QRect(0, 0, 1000, 800), datetime.now())

    reminder.animation_window._reveal_painted_generation(stale_generation)

    assert reminder.animation_window.windowOpacity() == 0.0
    reminder.hide()


def test_control_buttons_emit_actions_and_hide_stops_timers(qtbot, tmp_path: Path) -> None:
    reminder = WorkFinishReminder()
    qtbot.addWidget(reminder.animation_window)
    qtbot.addWidget(reminder.control_window)
    finished: list[bool] = []
    continued: list[bool] = []
    reminder.finish_requested.connect(lambda: finished.append(True))
    reminder.continue_requested.connect(lambda: continued.append(True))
    reminder.show_for(_package(tmp_path), QRect(0, 0, 1000, 800), datetime.now())

    reminder.control_window.finish_button.click()
    reminder.control_window.continue_button.click()

    assert finished == [True]
    assert continued == [True]
    assert reminder.animation_window.timer.isActive()
    assert reminder.control_window.timer.isActive()
    reminder.hide()
    assert not reminder.animation_window.timer.isActive()
    assert not reminder.control_window.timer.isActive()


def test_control_buttons_are_large_full_width_and_stacked(qtbot) -> None:
    reminder = WorkFinishReminder()
    qtbot.addWidget(reminder.animation_window)
    qtbot.addWidget(reminder.control_window)

    reminder.control_window.show_for(QRect(0, 0, 1000, 800), datetime.now())
    qtbot.wait(10)

    finish = reminder.control_window.finish_button
    continue_button = reminder.control_window.continue_button
    assert finish.text() == "下班啦🎉"
    assert reminder.control_window.width() >= 300
    assert finish.height() >= 56
    assert continue_button.height() >= 56
    assert finish.width() == continue_button.width()
    assert finish.width() >= 250
    assert finish.geometry().bottom() < continue_button.geometry().top()
    reminder.hide()


def test_missing_animation_still_shows_controls(qtbot, tmp_path: Path) -> None:
    package = replace(_package(tmp_path), animations={})
    reminder = WorkFinishReminder()
    qtbot.addWidget(reminder.animation_window)
    qtbot.addWidget(reminder.control_window)

    reminder.show_for(package, QRect(0, 0, 1000, 800), datetime.now() - timedelta(minutes=1))

    assert not reminder.animation_window.isVisible()
    assert reminder.control_window.isVisible()
    assert "29:" in reminder.control_window.timeout_label.text()
    reminder.hide()


def test_external_control_window_close_emits_dismissed(qtbot, tmp_path: Path) -> None:
    reminder = WorkFinishReminder()
    qtbot.addWidget(reminder.animation_window)
    qtbot.addWidget(reminder.control_window)
    dismissed: list[bool] = []
    reminder.dismissed.connect(lambda: dismissed.append(True))
    reminder.show_for(_package(tmp_path), QRect(0, 0, 1000, 800), datetime.now())

    reminder.control_window.close()

    assert dismissed == [True]


def test_shutdown_does_not_emit_external_dismissal(qtbot, tmp_path: Path) -> None:
    reminder = WorkFinishReminder()
    qtbot.addWidget(reminder.animation_window)
    qtbot.addWidget(reminder.control_window)
    dismissed: list[bool] = []
    reminder.dismissed.connect(lambda: dismissed.append(True))
    reminder.show_for(_package(tmp_path), QRect(0, 0, 1000, 800), datetime.now())

    reminder.shutdown()

    assert dismissed == []
