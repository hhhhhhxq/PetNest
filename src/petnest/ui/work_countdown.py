"""显示在桌宠旁边的上下班倒计时与独立弹性打卡卡片。"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, time, timedelta
import logging

from PySide6.QtCore import QObject, QPoint, QSignalBlocker, QTime, QTimer, Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QTimeEdit, QVBoxLayout, QWidget

from petnest.ui.theme import COLORS

LOGGER = logging.getLogger(__name__)


def countdown_text(
    now: datetime,
    start_text: str,
    end_text: str,
    daily_end_times: dict[str, str | None] | None = None,
) -> str:
    """根据本地时间生成工作日状态文字。"""
    if daily_end_times is not None:
        scheduled_end = daily_end_times.get(str(now.weekday()))
        if scheduled_end is None:
            return "今天休息 ☕"
        end_text = scheduled_end
    elif now.weekday() >= 5:
        return "今天休息 ☕"
    start = _parse_time(start_text, time(9))
    end = _parse_time(end_text, time(18))
    start_at = datetime.combine(now.date(), start, tzinfo=now.tzinfo)
    end_at = datetime.combine(now.date(), end, tzinfo=now.tzinfo)
    if end_at <= start_at:
        return "上下班时间设置有误"
    if now < start_at:
        return f"距离上班 {_duration(start_at - now)}"
    if now < end_at:
        return f"距离下班 {_duration(end_at - now)}"
    return "下班啦 🎉"


def _parse_time(value: str, fallback: time) -> time:
    try:
        return time.fromisoformat(value)
    except (TypeError, ValueError):
        return fallback


def effective_clock_in_at(recorded_at: datetime, start_text: str, end_text: str) -> datetime:
    """将用户记录的打卡时间限制在允许窗口内。"""
    start = _parse_time(start_text, time(9, 30))
    end = _parse_time(end_text, time(10))
    start_at = datetime.combine(recorded_at.date(), start, tzinfo=recorded_at.tzinfo)
    end_at = datetime.combine(recorded_at.date(), end, tzinfo=recorded_at.tzinfo)
    if end_at <= start_at:
        return start_at
    return min(max(recorded_at, start_at), end_at)


def elastic_work_end_at(
    recorded_at: datetime,
    start_text: str,
    end_text: str,
    work_duration_minutes: int,
) -> datetime:
    """返回弹性打卡对应的下班时刻。"""
    duration = work_duration_minutes if isinstance(work_duration_minutes, int) and work_duration_minutes > 0 else 540
    return effective_clock_in_at(recorded_at, start_text, end_text) + timedelta(minutes=duration)


def clock_in_is_available(
    now: datetime,
    workdays: dict[str, str | None],
    start_text: str,
) -> bool:
    """判断当前是否已到选中工作日的允许打卡开始时间。"""
    if workdays.get(str(now.weekday())) is None:
        return False
    start = _parse_time(start_text, time(9, 30))
    start_at = datetime.combine(now.date(), start, tzinfo=now.tzinfo)
    return now >= start_at


def _duration(delta: timedelta) -> str:
    seconds = max(0, int(delta.total_seconds()))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


class ClockInCard(QFrame):
    """独立于倒计时气泡的轻量打卡卡片。"""

    clock_in_requested = Signal(object)

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("clockInCard")
        self.setWindowFlags(
            Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet(
            f"""
            QFrame#clockInCard {{
                background: {COLORS['surface']};
                border: 1px solid {COLORS['border']};
                border-radius: 12px;
            }}
            QLabel#clockInTitle {{ color: {COLORS['text']}; font-size: 14px; font-weight: 700; }}
            QLabel#clockInHint {{ color: {COLORS['muted_text']}; }}
            QTimeEdit {{
                background: {COLORS['surface_alt']};
                color: {COLORS['text']};
                border: 1px solid {COLORS['border']};
                border-radius: 8px;
                padding: 7px 8px;
                min-width: 80px;
            }}
            QPushButton {{
                background: {COLORS['accent']}; color: white;
                border: 1px solid {COLORS['accent']}; border-radius: 8px;
                padding: 7px 13px; font-weight: 700;
            }}
            QPushButton:hover {{ background: #C87555; }}
            """
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)
        title = QLabel("上班打卡", self)
        title.setObjectName("clockInTitle")
        hint = QLabel("可调整记录时间", self)
        hint.setObjectName("clockInHint")
        layout.addWidget(title)
        layout.addWidget(hint)
        controls = QHBoxLayout()
        self.time_input = QTimeEdit(self)
        self.time_input.setDisplayFormat("HH:mm")
        self.time_input.setToolTip("点击箭头或直接输入打卡时间")
        self.clock_in_button = QPushButton("打卡", self)
        self.clock_in_button.setToolTip("按当前输入时间记录上班")
        controls.addWidget(self.time_input)
        controls.addWidget(self.clock_in_button)
        layout.addLayout(controls)
        self.clock_in_button.clicked.connect(lambda: self.clock_in_requested.emit(self.time_input.time()))
        self.adjustSize()

    def show_for(self, now: datetime) -> None:
        """首次显示或跨日显示时使用当前时间填充输入框。"""
        if not self.isVisible() or getattr(self, "_draft_date", None) != now.date():
            blocker = QSignalBlocker(self.time_input)
            self.time_input.setTime(QTime(now.hour, now.minute))
            del blocker
            self._draft_date = now.date()


class WorkCountdownWindow(QObject):
    """上下班倒计时控制器；原倒计时文字仍由宠物窗口统一绘制。"""

    def __init__(self, pet_window: QWidget) -> None:
        super().__init__(pet_window)
        self.pet_window: QWidget | None = pet_window
        pet_window.destroyed.connect(self._pet_destroyed)
        self.start_time = "09:00"
        self.end_time = "18:00"
        self.daily_end_times: dict[str, str | None] | None = None
        self.schedule_mode = "fixed"
        self.clock_in_start_time = "09:30"
        self.clock_in_end_time = "10:00"
        self.work_duration_minutes = 540
        self._clock_in_date: str | None = None
        self._clock_in_time: str | None = None
        self._on_clock_in: Callable[[datetime], object] | None = None
        self._last_now: datetime | None = None
        self.clock_in_card = ClockInCard(pet_window)
        self.clock_in_card.clock_in_requested.connect(self._handle_clock_in)
        self.timer = QTimer(self)
        self.timer.setInterval(1_000)
        self.timer.timeout.connect(self.refresh)

    def configure(
        self,
        *,
        enabled: bool,
        start_time: str,
        end_time: str,
        daily_end_times: dict[str, str | None] | None,
        gap: int,
        width: int,
        height: int,
        theme: str,
        always_on_top: bool,
        schedule_mode: str = "fixed",
        clock_in_start_time: str = "09:30",
        clock_in_end_time: str = "10:00",
        work_duration_minutes: int = 540,
        clock_in_date: str | None = None,
        clock_in_time: str | None = None,
        on_clock_in: Callable[[datetime], object] | None = None,
    ) -> None:
        del always_on_top
        self.start_time = start_time
        self.end_time = end_time
        self.daily_end_times = daily_end_times
        self.schedule_mode = schedule_mode if schedule_mode in {"fixed", "elastic"} else "fixed"
        self.clock_in_start_time = clock_in_start_time
        self.clock_in_end_time = clock_in_end_time
        self.work_duration_minutes = work_duration_minutes
        self._clock_in_date = clock_in_date
        self._clock_in_time = clock_in_time
        self._on_clock_in = on_clock_in
        if self.pet_window is not None:
            self.pet_window.set_countdown_appearance(  # type: ignore[attr-defined]
                gap=gap, width=width, height=height, theme=theme
            )
        if enabled:
            self.refresh()
            self.timer.start()
        else:
            self.timer.stop()
            self.clock_in_card.hide()
            self.pet_window.set_countdown_text(None) if self.pet_window is not None else None

    def refresh(self, now: datetime | None = None) -> None:
        if self.pet_window is None:
            return
        current = now or datetime.now().astimezone()
        self._last_now = current
        if self.schedule_mode != "elastic":
            self.clock_in_card.hide()
            self.pet_window.set_countdown_text(  # type: ignore[attr-defined]
                countdown_text(current, self.start_time, self.end_time, self.daily_end_times)
            )
            return
        self._refresh_elastic(current)

    def _refresh_elastic(self, now: datetime) -> None:
        workdays = self.daily_end_times or {
            "0": self.end_time,
            "1": self.end_time,
            "2": self.end_time,
            "3": self.end_time,
            "4": self.end_time,
            "5": None,
            "6": None,
        }
        if workdays.get(str(now.weekday())) is None:
            self.clock_in_card.hide()
            self.pet_window.set_countdown_text("今天休息 ☕")  # type: ignore[attr-defined]
            return
        if self._clock_in_date != now.date().isoformat():
            self._clock_in_date = None
            self._clock_in_time = None
        recorded = self._recorded_at(now)
        if recorded is None:
            if clock_in_is_available(now, workdays, self.clock_in_start_time):
                self._position_card()
                self.clock_in_card.show_for(now)
                self.clock_in_card.show()
                self.pet_window.set_countdown_text(None)  # type: ignore[attr-defined]
            else:
                self.clock_in_card.hide()
                self.pet_window.set_countdown_text(  # type: ignore[attr-defined]
                    countdown_text(now, self.clock_in_start_time, self.end_time, workdays)
                )
            return
        self.clock_in_card.hide()
        end_at = elastic_work_end_at(
            recorded,
            self.clock_in_start_time,
            self.clock_in_end_time,
            self.work_duration_minutes,
        )
        if now < end_at:
            text = f"距离下班 {_duration(end_at - now)}"
        else:
            text = "下班啦 🎉"
        self.pet_window.set_countdown_text(text)  # type: ignore[attr-defined]

    def _recorded_at(self, now: datetime) -> datetime | None:
        if self._clock_in_date != now.date().isoformat() or not self._clock_in_time:
            return None
        parsed = _parse_time(self._clock_in_time, time(9, 30))
        return datetime.combine(now.date(), parsed, tzinfo=now.tzinfo)

    def _handle_clock_in(self, selected_time: object) -> None:
        now = self._last_now or datetime.now().astimezone()
        if isinstance(selected_time, QTime):
            recorded = datetime.combine(
                now.date(),
                time(selected_time.hour(), selected_time.minute()),
                tzinfo=now.tzinfo,
            )
        else:
            recorded = now
        self._clock_in_date = recorded.date().isoformat()
        self._clock_in_time = recorded.strftime("%H:%M")
        if self._on_clock_in is not None:
            try:
                self._on_clock_in(recorded)
            except Exception:  # noqa: BLE001 - 持久化失败不应让倒计时崩溃。
                LOGGER.exception("保存上班打卡记录失败")
        self.refresh(now)

    def _position_card(self) -> None:
        if self.pet_window is None:
            return
        point = self.pet_window.mapToGlobal(QPoint(self.pet_window.width() + 12, max(8, self.pet_window.height() // 3)))
        self.clock_in_card.move(point)

    def _pet_destroyed(self) -> None:
        self.timer.stop()
        self.clock_in_card.hide()
        self.pet_window = None


__all__ = [
    "ClockInCard",
    "WorkCountdownWindow",
    "clock_in_is_available",
    "countdown_text",
    "effective_clock_in_at",
    "elastic_work_end_at",
]
