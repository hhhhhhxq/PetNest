"""显示在桌宠旁边的下班倒计时提示。"""

from __future__ import annotations

from datetime import datetime, time, timedelta

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QWidget


def countdown_text(
    now: datetime,
    end_text: str,
    daily_end_times: dict[str, str | None] | None = None,
) -> str:
    """根据本地时间生成下班倒计时或休息状态文字。"""
    if daily_end_times is not None:
        scheduled_end = daily_end_times.get(str(now.weekday()))
        if scheduled_end is None:
            return "今天休息 ☕"
        end_text = scheduled_end
    elif now.weekday() >= 5:
        return "今天休息 ☕"
    end = _parse_time(end_text, time(18))
    end_at = datetime.combine(now.date(), end, tzinfo=now.tzinfo)
    if now < end_at:
        return f"距离下班 {_duration(end_at - now)}"
    return "下班啦 🎉"


def _parse_time(value: str, fallback: time) -> time:
    try:
        return time.fromisoformat(value)
    except (TypeError, ValueError):
        return fallback


def _duration(delta: timedelta) -> str:
    seconds = max(0, int(delta.total_seconds()))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


class WorkCountdownWindow(QObject):
    """下班倒计时控制器；文字由宠物窗口统一绘制，不创建独立窗口。"""

    def __init__(self, pet_window: QWidget) -> None:
        super().__init__(pet_window)
        self.pet_window: QWidget | None = pet_window
        pet_window.destroyed.connect(self._pet_destroyed)
        self.end_time = "18:00"
        self.daily_end_times: dict[str, str | None] | None = None
        self.timer = QTimer(self)
        self.timer.setInterval(1_000)
        self.timer.timeout.connect(self.refresh)

    def configure(
        self,
        *,
        enabled: bool,
        end_time: str,
        daily_end_times: dict[str, str | None] | None,
        gap: int,
        width: int,
        height: int,
        theme: str,
        always_on_top: bool,
    ) -> None:
        del always_on_top
        self.end_time = end_time
        self.daily_end_times = daily_end_times
        if self.pet_window is not None:
            self.pet_window.set_countdown_appearance(  # type: ignore[attr-defined]
                gap=gap, width=width, height=height, theme=theme
            )
        if enabled:
            self.refresh()
            self.timer.start()
        else:
            self.timer.stop()
            self.pet_window.set_countdown_text(None) if self.pet_window is not None else None

    def refresh(self, now: datetime | None = None) -> None:
        text = countdown_text(now or datetime.now().astimezone(), self.end_time, self.daily_end_times)
        if self.pet_window is not None:
            self.pet_window.set_countdown_text(text)  # type: ignore[attr-defined]

    def _pet_destroyed(self) -> None:
        self.timer.stop()
        self.pet_window = None
