"""PySide6 desktop pet window behavior, exercised without a real display."""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PIL import Image
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from petnest.core.animation_player import AnimationPlayer
from petnest.core.state_machine import PetStateMachine
from petnest.models.event import PetEvent
from petnest.models.pet_package import (
    AnimationDefinition,
    Canvas,
    DisplaySettings,
    PetPackage,
)
from petnest.ui.pet_window import PetWindow
from petnest.ui.tray_icon import PetTrayIcon, application_icon


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


def test_macos_tool_window_remains_visible_when_application_is_inactive(
    qtbot: pytest.QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("petnest.ui.pet_window.sys.platform", "darwin")
    window = _window(tmp_path)
    qtbot.addWidget(window)

    assert window.testAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow)


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


def test_position_is_clamped_to_keep_part_of_pet_on_current_screen(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    window = _window(tmp_path)
    qtbot.addWidget(window)
    window.show()
    screen = QApplication.primaryScreen()
    assert screen is not None
    available = screen.availableGeometry()

    right = window.clamp_position(QPoint(available.right() + 10_000, available.center().y()))
    left = window.clamp_position(QPoint(available.left() - 10_000, available.center().y()))

    visible_width = min(window.minimum_visible_pixels, window.width())
    assert right.x() == available.right() - visible_width + 1
    assert left.x() == available.left() - window.width() + visible_width


def test_scale_change_reclamps_an_offscreen_window(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    window = _window(tmp_path)
    qtbot.addWidget(window)
    window.show()
    screen = QApplication.primaryScreen()
    assert screen is not None
    available = screen.availableGeometry()
    window.move(available.right() + 1, available.center().y())

    window.set_scale(2.0)

    visible_width = min(window.minimum_visible_pixels, window.width())
    assert window.x() == available.right() - visible_width + 1


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


def test_timer_uses_the_duration_of_each_current_frame(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    package = _package(tmp_path)
    idle = replace(package.animations["idle"], frame_durations_ms=(200, 80))
    package = replace(package, animations={**package.animations, "idle": idle})
    window = PetWindow(package)
    qtbot.addWidget(window)
    window.show()

    assert window.animation_timer.interval() == 200
    window.animation_timer.timeout.emit()
    assert window.animation_timer.interval() == 80


def test_restoring_runtime_state_restarts_the_requested_action_and_restores_pause(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    window = _window(tmp_path)
    qtbot.addWidget(window)
    window.show()
    window.handle_pet_event(PetEvent("mouse.enter", source="test"))
    window.animation_timer.timeout.emit()
    window.set_paused(True)

    window.restore_runtime_state("hover", paused=True)

    assert window.current_action == "hover"
    assert window.player.current_definition is not None
    assert window.player.current_definition.name == "hover"
    assert window.player.current_frame_index == 0
    assert window.player.is_paused
    assert not window.animation_timer.isActive()

    window.restore_runtime_state("missing", paused=False)

    assert window.current_action == "idle"
    assert not window.player.is_paused
    assert window.animation_timer.isActive()


def test_restoring_runtime_state_forces_low_priority_action_past_non_interruptible_idle(
    qtbot: pytest.QtBot, tmp_path: Path
) -> None:
    package = _package(tmp_path)
    animations = {
        **package.animations,
        "idle": replace(package.animations["idle"], priority=50, interruptible=False),
        "hover": replace(package.animations["hover"], priority=20),
    }
    window = PetWindow(replace(package, animations=animations))
    qtbot.addWidget(window)
    window.show()

    window.restore_runtime_state("hover", paused=True)

    assert window.current_action == "hover"
    assert window.player.current_frame_index == 0
    assert window.player.is_paused


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


def test_tray_exposes_a_local_spritesheet_import_action(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    window = _window(tmp_path)
    qtbot.addWidget(window)
    tray = PetTrayIcon(window, on_import=lambda: None)

    assert tray.import_action.text() == "导入精灵图…"


def test_application_icon_uses_the_dedicated_app_asset(qtbot: pytest.QtBot) -> None:
    assert not application_icon().isNull()


def test_tray_exposes_pet_folder_and_refresh_actions(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    window = _window(tmp_path)
    qtbot.addWidget(window)
    calls: list[str] = []
    tray = PetTrayIcon(window, on_open_pets_folder=lambda: calls.append("open"), on_refresh_pets=lambda: calls.append("refresh"))

    assert tray.open_pets_folder_action.text() == "打开宠物文件夹"
    assert tray.refresh_pets_action.text() == "刷新宠物列表"
    tray.open_pets_folder_action.trigger()
    tray.refresh_pets_action.trigger()
    assert calls == ["open", "refresh"]


def test_system_idle_actions_have_safe_default_bindings(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    package = _package(tmp_path)
    machine = PetWindow._make_state_machine(package)

    assert machine.handle(PetEvent("system.sleep", source="system")).current_action == "idle"
