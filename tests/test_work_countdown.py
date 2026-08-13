"""下班倒计时文字与窗口配置。"""

from datetime import datetime

import pytest
from PySide6.QtCore import QTime
from PySide6.QtWidgets import QApplication, QWidget
from pytestqt.qtbot import QtBot

from petnest.ui.work_countdown import WorkCountdownWindow, WorkEndTimeDialog, countdown_text


def test_countdown_before_and_during_work_only_shows_time_until_end() -> None:
    monday = datetime(2026, 8, 10, 8, 30, 0)
    assert countdown_text(monday, "18:00") == "距离下班 09:30:00"
    assert countdown_text(monday.replace(hour=17, minute=0), "18:00") == "距离下班 01:00:00"


def test_countdown_uses_same_end_time_after_work_and_on_weekend() -> None:
    monday = datetime(2026, 8, 10, 18, 0, 0)
    sunday = datetime(2026, 8, 9, 10, 0, 0)
    assert countdown_text(monday, "18:00") == "下班啦 🎉"
    assert countdown_text(sunday, "18:00") == "距离下班 08:00:00"


def test_invalid_end_time_uses_default() -> None:
    monday = datetime(2026, 8, 10, 10, 0, 0)
    assert countdown_text(monday, "invalid") == "距离下班 08:00:00"


def test_countdown_controller_never_creates_a_second_visible_window(qtbot: QtBot) -> None:
    app = QApplication.instance() or QApplication([])
    del app

    class _PetWindow(QWidget):
        def set_countdown_appearance(self, **_kwargs: object) -> None:
            pass

        def set_countdown_text(self, _text: str | None) -> None:
            pass

    pet = _PetWindow()
    qtbot.addWidget(pet)
    countdown = WorkCountdownWindow(pet)
    countdown.configure(
        enabled=True,
        end_time="18:00",
        gap=0,
        width=132,
        height=37,
        theme="cream",
        always_on_top=True,
    )

    pet.show()

    assert countdown not in QApplication.topLevelWidgets()


def test_work_end_time_dialog_returns_selected_time(qtbot: QtBot) -> None:
    dialog = WorkEndTimeDialog("18:00")
    qtbot.addWidget(dialog)

    dialog.time_input.setTime(QTime(19, 45))

    assert dialog.selected_time() == "19:45"
