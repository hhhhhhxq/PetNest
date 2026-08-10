"""上下班倒计时文字与窗口配置。"""

from datetime import datetime

import pytest
from PySide6.QtWidgets import QApplication, QWidget
from pytestqt.qtbot import QtBot

from petnest.ui.work_countdown import WorkCountdownWindow, countdown_text


def test_countdown_before_and_during_work() -> None:
    monday = datetime(2026, 8, 10, 8, 30, 0)
    assert countdown_text(monday, "09:00", "18:00") == "距离上班 00:30:00"
    assert countdown_text(monday.replace(hour=17, minute=0), "09:00", "18:00") == "距离下班 01:00:00"


def test_countdown_after_work_and_on_weekend() -> None:
    monday = datetime(2026, 8, 10, 18, 0, 0)
    sunday = datetime(2026, 8, 9, 10, 0, 0)
    assert countdown_text(monday, "09:00", "18:00") == "下班啦 🎉"
    assert countdown_text(sunday, "09:00", "18:00") == "今天休息 ☕"


def test_invalid_work_period_is_explained() -> None:
    monday = datetime(2026, 8, 10, 10, 0, 0)
    assert countdown_text(monday, "18:00", "09:00") == "上下班时间设置有误"


def test_daily_schedule_uses_each_days_end_time() -> None:
    schedule = {"0": "18:30", "1": "17:00", "2": None, "3": "20:00", "4": "16:30", "5": None, "6": None}

    monday = datetime(2026, 8, 10, 17, 30)
    tuesday = datetime(2026, 8, 11, 16, 30)
    wednesday = datetime(2026, 8, 12, 10, 0)

    assert countdown_text(monday, "09:30", "18:00", schedule) == "距离下班 01:00:00"
    assert countdown_text(tuesday, "09:30", "18:00", schedule) == "距离下班 00:30:00"
    assert countdown_text(wednesday, "09:30", "18:00", schedule) == "今天休息 ☕"


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
        start_time="09:00",
        end_time="18:00",
        daily_end_times=None,
        gap=0,
        width=132,
        height=37,
        theme="cream",
        always_on_top=True,
    )

    pet.show()

    assert countdown not in QApplication.topLevelWidgets()
