"""显示在桌宠旁边的上下班倒计时提示。"""

from __future__ import annotations

from datetime import datetime, time, timedelta
import sys

from PySide6.QtCore import QEvent, QObject, QPoint, Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QLabel, QWidget


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


def _duration(delta: timedelta) -> str:
    seconds = max(0, int(delta.total_seconds()))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


class WorkCountdownWindow(QLabel):
    """跟随宠物移动、不会拦截鼠标的轻量提示牌。"""

    def __init__(self, pet_window: QWidget) -> None:
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.NoDropShadowWindowHint
        )
        # macOS 对“有父对象的顶层 NSPanel”显示不稳定，因此使用真正独立
        # 的顶层窗口，并通过 destroyed 信号显式管理生命周期。
        super().__init__(None, flags)
        self.pet_window: QWidget | None = pet_window
        pet_window.installEventFilter(self)
        pet_window.destroyed.connect(self._pet_destroyed)
        self.start_time = "09:00"
        self.end_time = "18:00"
        self.daily_end_times: dict[str, str | None] | None = None
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        if sys.platform == "darwin":
            # Qt.Tool 在 macOS 上是 NSPanel，默认会在应用失焦后隐藏。倒计时
            # 和宠物本体一样，需要跨应用持续显示。
            self.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(
            "QLabel { color: white; background: rgba(35, 35, 40, 218); "
            "border: 1px solid rgba(255, 255, 255, 55); border-radius: 10px; "
            "padding: 7px 11px; font-size: 13px; font-weight: 600; }"
        )
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
        always_on_top: bool,
    ) -> None:
        self.start_time = start_time
        self.end_time = end_time
        self.daily_end_times = daily_end_times
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, always_on_top)
        if enabled:
            self.refresh()
            self.timer.start()
        else:
            self.timer.stop()
            self.hide()
            self.pet_window.set_countdown_text(None) if self.pet_window is not None else None

    def refresh(self, now: datetime | None = None) -> None:
        text = countdown_text(
            now or datetime.now().astimezone(), self.start_time, self.end_time, self.daily_end_times
        )
        if self.pet_window is not None:
            self.pet_window.set_countdown_text(text)  # type: ignore[attr-defined]

    def reposition(self) -> None:
        if self.pet_window is None:
            return
        anchor = self.pet_window.frameGeometry()
        target = QPoint(anchor.center().x() - self.width() // 2, anchor.top() - self.height() - 8)
        screen = QGuiApplication.screenAt(anchor.center()) or self.pet_window.screen()
        if screen is not None:
            area = screen.availableGeometry()
            target.setX(max(area.left(), min(target.x(), area.right() - self.width() + 1)))
            if target.y() < area.top():
                target.setY(min(area.bottom() - self.height() + 1, anchor.bottom() + 8))
        self.move(target)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt 覆盖名。
        if watched is self.pet_window:
            if event.type() in {QEvent.Type.Move, QEvent.Type.Resize}:
                self.reposition()
            elif event.type() == QEvent.Type.Hide:
                self.hide()
            elif event.type() == QEvent.Type.Show and self.timer.isActive():
                self.reposition()
                self.show()
        return super().eventFilter(watched, event)

    def _pet_destroyed(self) -> None:
        self.timer.stop()
        self.pet_window = None
        self.hide()
