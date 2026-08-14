"""全屏下班动画窗口和独立控制面板。"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

from PySide6.QtCore import QRect, Qt

from petnest.ui.work_finish_reminder import WorkFinishReminder
from tests.test_pet_window import _package


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
