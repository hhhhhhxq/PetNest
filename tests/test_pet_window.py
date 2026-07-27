"""PySide6 desktop pet window behavior, exercised without a real display."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PIL import Image
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest

from petnest.core.animation_player import AnimationPlayer
from petnest.core.state_machine import PetStateMachine
from petnest.models.pet_package import (
    AnimationDefinition,
    Canvas,
    DisplaySettings,
    PetPackage,
)
from petnest.ui.pet_window import PetWindow


def _package(tmp_path: Path, *, identifier: str = "cat", colour: tuple[int, int, int, int] = (255, 0, 0, 255)) -> PetPackage:
    animations: dict[str, AnimationDefinition] = {}
    for name, loop, priority, interruptible in (
        ("idle", True, 10, True),
        ("hover", True, 20, True),
        ("click", False, 30, False),
        ("drag", True, 40, False),
        ("drop", False, 35, False),
    ):
        frames: list[Path] = []
        for index, alpha in enumerate((colour[3], 255), start=1):
            path = tmp_path / f"{identifier}-{name}-{index}.png"
            Image.new("RGBA", (10, 8), (*colour[:3], alpha)).save(path)
            frames.append(path)
        animations[name] = AnimationDefinition(
            name=name,
            path=tmp_path,
            fps=10,
            loop=loop,
            next_animation=None,
            priority=priority,
            interruptible=interruptible,
            frames=tuple(frames),
        )
    return PetPackage(
        root=tmp_path,
        identifier=identifier,
        name=identifier,
        version="1",
        canvas=Canvas(10, 8),
        animations=animations,
        bindings={
            "mouse.enter": "hover",
            "mouse.leave": "idle",
            "mouse.click": "click",
            "mouse.drag_start": "drag",
            "mouse.drag_end": "drop",
        },
        fallbacks={},
        display=DisplaySettings(default_scale=1.5, alpha_hit_test_threshold=10),
    )


def _window(tmp_path: Path, **kwargs: object) -> PetWindow:
    package = _package(tmp_path)
    return PetWindow(
        package,
        player=AnimationPlayer(),
        state_machine=PetStateMachine(package.animations, package.bindings, package.fallbacks),
        **kwargs,
    )


def _drag_move(window: PetWindow, x: int, y: int) -> None:
    point = QPointF(x, y)
    event = QMouseEvent(
        QEvent.Type.MouseMove,
        point,
        QPointF(window.mapToGlobal(point.toPoint())),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QTest.qWait(1)
    from PySide6.QtWidgets import QApplication

    QApplication.sendEvent(window, event)


def test_window_is_transparent_frameless_topmost_and_uses_scaled_canvas(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    window = _window(tmp_path)
    qtbot.addWidget(window)
    window.show()

    assert window.windowFlags() & Qt.WindowType.FramelessWindowHint
    assert window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    assert window.windowFlags() & Qt.WindowType.Tool
    assert window.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    assert window.focusPolicy() == Qt.FocusPolicy.NoFocus
    assert window.size().width() == 15
    assert window.size().height() == 12


def test_idle_frame_is_rendered_and_alpha_hit_testing_uses_current_frame_cache(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    window = _window(tmp_path)
    qtbot.addWidget(window)
    window.show()

    assert window.current_action == "idle"
    assert not window.current_pixmap.isNull()
    assert window.is_opaque_at(0, 0)
    assert window.is_opaque_at(0, 0)  # repeated access must use the same cached alpha mask


def test_mouse_enter_and_click_drive_the_configured_state_machine(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    window = _window(tmp_path)
    qtbot.addWidget(window)
    window.show()

    QTest.mouseMove(window, window.rect().center())
    assert window.current_action == "hover"

    QTest.mouseClick(window, Qt.MouseButton.LeftButton, pos=window.rect().center())
    assert window.current_action == "click"


def test_drag_starts_only_after_threshold_moves_window_and_saves_position(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    positions: list[tuple[int, int]] = []
    window = _window(tmp_path, position_saved=lambda point: positions.append((point.x(), point.y())))
    qtbot.addWidget(window)
    window.move(100, 100)
    window.show()
    start = window.pos()
    center = window.rect().center()

    QTest.mousePress(window, Qt.MouseButton.LeftButton, pos=center)
    _drag_move(window, center.x() + window.drag_threshold - 1, center.y())
    assert window.current_action == "idle"
    assert window.pos() == start

    _drag_move(window, center.x() + window.drag_threshold + 2, center.y())
    assert window.current_action == "drag"
    assert window.pos() != start

    QTest.mouseRelease(window, Qt.MouseButton.LeftButton, pos=center)
    assert window.current_action == "drop"
    assert positions[-1] == (window.x(), window.y())


def test_timer_advances_frames_and_pause_resume_stops_and_restarts_it(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    window = _window(tmp_path)
    qtbot.addWidget(window)
    window.show()
    initial_index = window.player.current_frame_index

    window.animation_timer.timeout.emit()
    assert window.player.current_frame_index != initial_index

    window.set_paused(True)
    paused_index = window.player.current_frame_index
    assert not window.animation_timer.isActive()
    window.animation_timer.timeout.emit()
    assert window.player.current_frame_index == paused_index

    window.set_paused(False)
    assert window.animation_timer.isActive()
    window.animation_timer.timeout.emit()
    assert window.player.current_frame_index != paused_index


def test_reloading_package_clears_old_animation_cache_and_starts_new_idle(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    first = _package(tmp_path, identifier="cat")
    player = AnimationPlayer()
    window = PetWindow(
        first,
        player=player,
        state_machine=PetStateMachine(first.animations, first.bindings, first.fallbacks),
    )
    qtbot.addWidget(window)
    window.show()
    old_frame = player.current_frame
    second = _package(tmp_path, identifier="dog", colour=(0, 255, 0, 255))

    window.load_package(second)

    assert window.package.identifier == "dog"
    assert window.current_action == "idle"
    assert player.current_frame is not old_frame
    assert player.current_frame.getpixel((0, 0)) == (0, 255, 0, 255)
