"""上下班倒计时文字与窗口配置。"""

from datetime import datetime

import pytest
from PySide6.QtCore import QTime
from PySide6.QtWidgets import QApplication, QTimeEdit, QWidget
from pytestqt.qtbot import QtBot

from petnest.ui.work_countdown import (
    WorkCountdownWindow,
    clock_in_is_available,
    countdown_text,
    effective_clock_in_at,
    elastic_work_end_at,
)
from petnest.core.work_finish_state import WorkFinishState


def test_fixed_countdown_stays_hidden_before_work_and_counts_down_after_start() -> None:
    monday = datetime(2026, 8, 10, 8, 30, 0)
    assert countdown_text(monday, "09:00", "18:00") is None
    assert countdown_text(monday.replace(hour=9, minute=0), "09:00", "18:00") == "距离下班 09:00:00"
    assert countdown_text(monday.replace(hour=17, minute=0), "09:00", "18:00") == "距离下班 01:00:00"


def test_countdown_after_work_and_on_weekend() -> None:
    monday = datetime(2026, 8, 10, 18, 0, 0)
    sunday = datetime(2026, 8, 9, 10, 0, 0)
    assert countdown_text(monday, "09:00", "18:00") == "下班啦 🎉"
    assert countdown_text(sunday, "09:00", "18:00") == "今天休息 ☕"


def test_invalid_start_time_does_not_restore_work_start_countdown() -> None:
    monday = datetime(2026, 8, 10, 10, 0, 0)
    assert countdown_text(monday, "18:00", "09:00") == "下班啦 🎉"


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


def test_clock_in_availability_uses_configured_latest_possible_work_end() -> None:
    workdays = {"0": "18:00", "1": "18:00", "2": "18:00", "3": "18:00", "4": "18:00", "5": None, "6": None}

    assert not clock_in_is_available(
        datetime(2026, 8, 13, 8, 14, 59),
        workdays,
        "08:15",
        "09:05",
        455,
    )
    assert clock_in_is_available(
        datetime(2026, 8, 13, 8, 15),
        workdays,
        "08:15",
        "09:05",
        455,
    )
    assert clock_in_is_available(
        datetime(2026, 8, 13, 16, 39, 59),
        workdays,
        "08:15",
        "09:05",
        455,
    )
    assert not clock_in_is_available(
        datetime(2026, 8, 13, 16, 40),
        workdays,
        "08:15",
        "09:05",
        455,
    )


def test_clock_in_availability_can_continue_from_previous_workday_across_midnight() -> None:
    workdays = {"0": None, "1": None, "2": None, "3": "23:30", "4": None, "5": None, "6": None}

    assert clock_in_is_available(
        datetime(2026, 8, 14, 0, 30),
        workdays,
        "23:00",
        "23:30",
        120,
    )
    assert not clock_in_is_available(
        datetime(2026, 8, 14, 1, 30),
        workdays,
        "23:00",
        "23:30",
        120,
    )


def test_elastic_countdown_uses_independent_clock_in_card_only_during_available_period(qtbot: QtBot) -> None:
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
    assert pet.texts[-1] is None

    available = datetime(2026, 8, 13, 9, 35)
    countdown.refresh(available)
    assert countdown.clock_in_card.isVisible()
    assert countdown.clock_in_card.clock_in_button.text() == "上工"
    assert countdown.clock_in_card.time_input.time().toString("HH:mm") == "09:35"
    assert countdown.clock_in_card.time_input.minimumTime().toString("HH:mm") == "09:30"
    assert countdown.clock_in_card.time_input.maximumTime().toString("HH:mm") == "09:35"
    assert pet.texts[-1] is None

    countdown.clock_in_card.time_input.setTime(QTime(9, 32))
    countdown.clock_in_card.clock_in_button.click()
    assert recorded == [datetime(2026, 8, 13, 9, 32)]
    assert not countdown.clock_in_card.isVisible()
    assert pet.texts[-1] == "距离下班 08:57:00"
    countdown.timer.stop()


def test_elastic_countdown_hides_unrecorded_clock_in_after_dynamic_cutoff(qtbot: QtBot) -> None:
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
    countdown = WorkCountdownWindow(pet)
    countdown.configure(
        enabled=True,
        start_time="07:00",
        end_time="18:00",
        daily_end_times={"0": "18:00", "1": "18:00", "2": "18:00", "3": "18:00", "4": "18:00", "5": None, "6": None},
        gap=0,
        width=132,
        height=37,
        theme="cream",
        always_on_top=True,
        schedule_mode="elastic",
        clock_in_start_time="08:15",
        clock_in_end_time="09:05",
        work_duration_minutes=455,
    )

    countdown.refresh(datetime(2026, 8, 13, 16, 39, 59))
    assert countdown.clock_in_card.isVisible()
    assert pet.texts[-1] is None

    countdown.refresh(datetime(2026, 8, 13, 16, 40))
    assert not countdown.clock_in_card.isVisible()
    assert pet.texts[-1] is None
    countdown.timer.stop()


def test_elastic_countdown_discards_yesterdays_clock_in_before_todays_window(qtbot: QtBot) -> None:
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
        clock_in_date="2026-08-13",
        clock_in_time="09:52",
    )

    countdown.refresh(datetime(2026, 8, 14, 1, 39))

    assert not countdown.clock_in_card.isVisible()
    assert pet.texts[-1] is None
    assert countdown._clock_in_date is None
    assert countdown._clock_in_time is None
    countdown.timer.stop()


def test_elastic_countdown_keeps_previous_days_overnight_clock_in_until_work_ends(qtbot: QtBot) -> None:
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
    countdown = WorkCountdownWindow(pet)
    countdown.configure(
        enabled=True,
        start_time="23:00",
        end_time="23:30",
        daily_end_times={"0": None, "1": None, "2": None, "3": "23:30", "4": None, "5": None, "6": None},
        gap=0,
        width=132,
        height=37,
        theme="cream",
        always_on_top=True,
        schedule_mode="elastic",
        clock_in_start_time="23:00",
        clock_in_end_time="23:30",
        work_duration_minutes=120,
        clock_in_date="2026-08-13",
        clock_in_time="23:15",
    )
    countdown._clock_in_date = "2026-08-13"
    countdown._clock_in_time = "23:15"

    countdown.refresh(datetime(2026, 8, 14, 0, 30))
    assert pet.texts[-1] == "距离下班 00:45:00"

    countdown.refresh(datetime(2026, 8, 14, 1, 15))
    assert pet.texts[-1] == "下班啦 🎉"

    countdown.refresh(datetime(2026, 8, 14, 1, 15, 1))
    assert not countdown.clock_in_card.isVisible()
    assert pet.texts[-1] == "下班啦 🎉"

    countdown.refresh(datetime(2026, 8, 14, 1, 30))
    assert not countdown.clock_in_card.isVisible()
    assert pet.texts[-1] == "下班啦 🎉"

    countdown.refresh(datetime(2026, 8, 14, 1, 45))
    assert countdown.work_finish_state is not None
    assert countdown.work_finish_state.status == "finished"
    assert pet.texts[-1] == "下班啦 🎉"
    countdown.timer.stop()


def test_elastic_clock_in_card_can_record_previous_workday_after_midnight(qtbot: QtBot) -> None:
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
        start_time="23:00",
        end_time="23:30",
        daily_end_times={"0": None, "1": None, "2": None, "3": "23:30", "4": None, "5": None, "6": None},
        gap=0,
        width=132,
        height=37,
        theme="cream",
        always_on_top=True,
        schedule_mode="elastic",
        clock_in_start_time="23:00",
        clock_in_end_time="23:30",
        work_duration_minutes=120,
        on_clock_in=recorded.append,
    )

    countdown.refresh(datetime(2026, 8, 14, 0, 30))
    assert countdown.clock_in_card.isVisible()
    assert countdown.clock_in_card.time_input.minimumTime().toString("HH:mm") == "23:00"
    assert countdown.clock_in_card.time_input.maximumTime().toString("HH:mm") == "23:30"

    countdown.clock_in_card.time_input.setTime(QTime(23, 20))
    countdown.clock_in_card.clock_in_button.click()
    assert recorded == [datetime(2026, 8, 13, 23, 20)]
    assert pet.texts[-1] == "距离下班 00:50:00"
    countdown.timer.stop()


def test_elastic_countdown_treats_invalid_clock_in_time_as_unrecorded(qtbot: QtBot) -> None:
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
        clock_in_date="2026-08-13",
        clock_in_time="not-a-time",
    )
    countdown._clock_in_date = "2026-08-13"
    countdown._clock_in_time = "not-a-time"

    countdown.refresh(datetime(2026, 8, 13, 9, 40))

    assert countdown.clock_in_card.isVisible()
    assert pet.texts[-1] is None
    countdown.timer.stop()


def test_elastic_countdown_switches_to_finished_at_exact_work_end(qtbot: QtBot) -> None:
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
        clock_in_date="2026-08-13",
        clock_in_time="09:40",
    )
    countdown._clock_in_date = "2026-08-13"
    countdown._clock_in_time = "09:40"

    countdown.refresh(datetime(2026, 8, 13, 18, 39, 59))
    assert pet.texts[-1] == "距离下班 00:00:01"

    countdown.refresh(datetime(2026, 8, 13, 18, 40))
    assert pet.texts[-1] == "下班啦 🎉"
    countdown.timer.stop()


def test_fixed_countdown_prompts_once_then_counts_overtime_from_original_end(qtbot: QtBot) -> None:
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
    prompts: list[WorkFinishState] = []
    saved: list[WorkFinishState | None] = []
    countdown = WorkCountdownWindow(pet)
    countdown.configure(
        enabled=True,
        start_time="09:00",
        end_time="18:00",
        daily_end_times={str(day): "18:00" for day in range(7)},
        gap=0,
        width=132,
        height=37,
        theme="cream",
        always_on_top=True,
        on_work_finish_prompt=prompts.append,
        on_work_finish_state=saved.append,
    )
    prompts.clear()
    saved.clear()

    countdown.refresh(datetime(2026, 8, 14, 17, 59, 59))
    countdown.refresh(datetime(2026, 8, 14, 18, 0))
    countdown.refresh(datetime(2026, 8, 14, 18, 0, 1))

    assert len(prompts) == 1
    assert prompts[0].prompt_kind == "initial"
    assert pet.texts[-1] == "下班啦 🎉"

    countdown.continue_overtime(datetime(2026, 8, 14, 18, 1))
    countdown.refresh(datetime(2026, 8, 14, 18, 2))

    assert pet.texts[-1] == "你已加班 00:02:00"
    assert saved[-1] is not None
    assert saved[-1].status == "overtime"
    countdown.timer.stop()


def test_overtime_prompts_again_at_relative_hour_and_times_out_as_finished(qtbot: QtBot) -> None:
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
    prompts: list[WorkFinishState] = []
    countdown = WorkCountdownWindow(pet)
    countdown.configure(
        enabled=True,
        start_time="09:00",
        end_time="18:40",
        daily_end_times={str(day): "18:40" for day in range(7)},
        gap=0,
        width=132,
        height=37,
        theme="cream",
        always_on_top=True,
        on_work_finish_prompt=prompts.append,
    )
    prompts.clear()

    countdown.refresh(datetime(2026, 8, 14, 18, 40))
    countdown.continue_overtime(datetime(2026, 8, 14, 18, 41))
    countdown.refresh(datetime(2026, 8, 14, 19, 39, 59))
    assert len(prompts) == 1

    countdown.refresh(datetime(2026, 8, 14, 19, 40))
    assert len(prompts) == 2
    assert prompts[-1].prompt_kind == "hourly"
    assert pet.texts[-1] == "你已加班 01:00:00"

    countdown.refresh(datetime(2026, 8, 14, 20, 10))
    assert countdown.work_finish_state is not None
    assert countdown.work_finish_state.status == "finished"
    assert pet.texts[-1] == "下班啦 🎉"
    countdown.timer.stop()


def test_elastic_countdown_prompt_uses_recorded_work_end(qtbot: QtBot) -> None:
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
    prompts: list[WorkFinishState] = []
    countdown = WorkCountdownWindow(pet)
    countdown.configure(
        enabled=True,
        start_time="09:00",
        end_time="18:00",
        daily_end_times={str(day): "18:00" for day in range(7)},
        gap=0,
        width=132,
        height=37,
        theme="cream",
        always_on_top=True,
        schedule_mode="elastic",
        clock_in_start_time="09:30",
        clock_in_end_time="10:00",
        work_duration_minutes=540,
        clock_in_date="2026-08-14",
        clock_in_time="09:40",
        on_work_finish_prompt=prompts.append,
    )
    prompts.clear()

    countdown.refresh(datetime(2026, 8, 14, 18, 39, 59))
    assert not prompts
    countdown.refresh(datetime(2026, 8, 14, 18, 40))

    assert len(prompts) == 1
    assert prompts[0].end_at == datetime(2026, 8, 14, 18, 40)
    countdown.timer.stop()


def test_clock_in_card_tracks_current_minute_until_user_edits_and_never_allows_future_time(qtbot: QtBot) -> None:
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
    )

    countdown.refresh(datetime(2026, 8, 13, 9, 35, 40))
    assert countdown.clock_in_card.time_input.time().toString("HH:mm") == "09:35"
    countdown.refresh(datetime(2026, 8, 13, 9, 39, 5))
    assert countdown.clock_in_card.time_input.time().toString("HH:mm") == "09:39"

    countdown.clock_in_card.time_input.setTime(QTime(9, 32))
    countdown.refresh(datetime(2026, 8, 13, 9, 45, 0))
    assert countdown.clock_in_card.time_input.time().toString("HH:mm") == "09:32"
    assert countdown.clock_in_card.time_input.maximumTime().toString("HH:mm") == "09:45"

    countdown.clock_in_card.time_input.setTime(QTime(9, 59))
    assert countdown.clock_in_card.time_input.time().toString("HH:mm") == "09:45"
    countdown.refresh(datetime(2026, 8, 13, 10, 5, 0))
    assert countdown.clock_in_card.time_input.maximumTime().toString("HH:mm") == "10:00"
    countdown.timer.stop()


def test_clock_in_time_can_step_back_across_the_hour_boundary(qtbot: QtBot) -> None:
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
    )

    countdown.refresh(datetime(2026, 8, 13, 10, 5))
    assert countdown.clock_in_card.time_input.time().toString("HH:mm") == "10:00"
    countdown.clock_in_card.time_input.setCurrentSection(QTimeEdit.Section.MinuteSection)
    assert countdown.clock_in_card.time_input.stepEnabled() & QTimeEdit.StepEnabledFlag.StepDownEnabled
    countdown.clock_in_card.time_input.stepDown()

    assert countdown.clock_in_card.time_input.time().toString("HH:mm") == "09:59"
    countdown.timer.stop()


def test_hiding_pet_also_hides_clock_in_card_and_showing_refreshes_it(qtbot: QtBot) -> None:
    class _PetWindow(QWidget):
        def set_countdown_appearance(self, **_kwargs: object) -> None:
            pass

        def set_countdown_text(self, _text: str | None) -> None:
            pass

        def mapToGlobal(self, point: object) -> object:  # noqa: N802 - Qt compatibility stub
            return point

    pet = _PetWindow()
    qtbot.addWidget(pet)
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
    )
    countdown.clock_in_card.show()

    countdown.set_pet_visible(False)
    assert not countdown.clock_in_card.isVisible()

    countdown.set_pet_visible(True)
    assert countdown.timer.isActive()
    countdown.clock_in_card.hide()


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
