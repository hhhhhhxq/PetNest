"""上下班倒计时文字与窗口配置。"""

from datetime import datetime

import pytest
from PySide6.QtCore import QTime
from PySide6.QtWidgets import QApplication, QWidget
from pytestqt.qtbot import QtBot

from petnest.ui.work_countdown import (
    WorkCountdownWindow,
    clock_in_is_available,
    countdown_text,
    effective_clock_in_at,
    elastic_work_end_at,
)


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


def test_elastic_clock_in_clamps_before_window_to_start() -> None:
    recorded = datetime(2026, 8, 13, 9, 10)

    assert effective_clock_in_at(recorded, "09:30", "10:00") == datetime(2026, 8, 13, 9, 30)
    assert elastic_work_end_at(recorded, "09:30", "10:00", 540) == datetime(2026, 8, 13, 18, 30)


def test_elastic_clock_in_uses_recorded_time_inside_window() -> None:
    recorded = datetime(2026, 8, 13, 9, 40)

    assert effective_clock_in_at(recorded, "09:30", "10:00") == recorded
    assert elastic_work_end_at(recorded, "09:30", "10:00", 540) == datetime(2026, 8, 13, 18, 40)


def test_elastic_clock_in_clamps_after_window_to_end() -> None:
    recorded = datetime(2026, 8, 13, 10, 20)

    assert effective_clock_in_at(recorded, "09:30", "10:00") == datetime(2026, 8, 13, 10, 0)
    assert elastic_work_end_at(recorded, "09:30", "10:00", 540) == datetime(2026, 8, 13, 19, 0)


def test_clock_in_is_available_only_after_start_on_selected_workday() -> None:
    workdays = {"0": "18:00", "1": "18:00", "2": "18:00", "3": "18:00", "4": "18:00", "5": None, "6": None}

    assert not clock_in_is_available(datetime(2026, 8, 13, 9, 29), workdays, "09:30")
    assert clock_in_is_available(datetime(2026, 8, 13, 9, 30), workdays, "09:30")
    assert not clock_in_is_available(datetime(2026, 8, 15, 9, 30), workdays, "09:30")


def test_clock_in_is_available_for_selected_weekend_workday() -> None:
    workdays = {"0": None, "1": None, "2": None, "3": None, "4": None, "5": "18:00", "6": None}

    assert clock_in_is_available(datetime(2026, 8, 15, 9, 30), workdays, "09:30")


def test_elastic_countdown_uses_independent_clock_in_card_after_start(qtbot: QtBot) -> None:
    class _PetWindow(QWidget):
        def __init__(self) -> None:
            super().__init__()
            self.texts: list[str | None] = []

        def set_countdown_appearance(self, **_kwargs: object) -> None:
            pass

        def set_countdown_text(self, text: str | None) -> None:
            self.texts.append(text)

    pet = _PetWindow()
    qtbot.addWidget(pet)
    recorded: list[datetime] = []
    countdown = WorkCountdownWindow(pet)
    countdown.configure(
        enabled=True,
        start_time="09:00",
        end_time="18:00",
        daily_end_times={"0": "18:00", "1": "18:00", "2": "18:00", "3": "18:00", "4": "18:00", "5": None, "6": None},
        gap=0,
        width=132,
        height=37,
        theme="cream",
        always_on_top=True,
        schedule_mode="elastic",
        clock_in_start_time="09:30",
        clock_in_end_time="10:00",
        work_duration_minutes=540,
        on_clock_in=recorded.append,
    )

    before = datetime(2026, 8, 13, 9, 29)
    countdown.refresh(before)
    assert not countdown.clock_in_card.isVisible()
    assert pet.texts[-1] == "距离上班 00:01:00"

    available = datetime(2026, 8, 13, 9, 35)
    countdown.refresh(available)
    assert countdown.clock_in_card.isVisible()
    assert countdown.clock_in_card.time_input.time().toString("HH:mm") == "09:35"
    assert pet.texts[-1] is None

    countdown.clock_in_card.time_input.setTime(QTime(9, 40))
    countdown.clock_in_card.clock_in_button.click()
    assert recorded == [datetime(2026, 8, 13, 9, 40)]
    assert not countdown.clock_in_card.isVisible()
    assert pet.texts[-1] == "距离下班 09:05:00"
    countdown.timer.stop()


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
