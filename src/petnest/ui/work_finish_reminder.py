"""透明全屏下班动画和独立的左上角决策面板。"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from math import ceil
from time import monotonic

from PySide6.QtCore import QObject, QRect, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QCloseEvent, QPaintEvent, QPainter, QPixmap
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from petnest.core.work_finish_animation import resolve_work_finish_animation
from petnest.core.work_finish_state import PROMPT_TIMEOUT
from petnest.models.pet_package import AnimationDefinition, PetPackage
from petnest.ui.theme import COLORS


class WorkFinishAnimationWindow(QWidget):
    """覆盖一个屏幕、但不拦截鼠标的透明动画层。"""

    WALK_SECONDS = 4.0
    WIDTH_RATIO = 0.92

    def __init__(self, *, clock: Callable[[], float] = monotonic) -> None:
        super().__init__(None)
        self._clock = clock
        self._started_at = 0.0
        self._walk_frames: tuple[QPixmap, ...] = ()
        self._lie_frames: tuple[QPixmap, ...] = ()
        self._lie_loop_frames: tuple[QPixmap, ...] = ()
        self._walk_durations: tuple[int, ...] = ()
        self._lie_durations: tuple[int, ...] = ()
        self._lie_loop_durations: tuple[int, ...] = ()
        self._entrance_direction = "right"
        self.current_phase = "hidden"
        self.current_frame_index = 0
        self.target_frame_width = 0
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._refresh_frame)

    def show_for(self, package: PetPackage, geometry: QRect) -> None:
        animation = resolve_work_finish_animation(package)
        self._walk_frames = _pixmaps(animation.walk)
        self._lie_frames = _pixmaps(animation.lie_down)
        self._lie_loop_frames = _pixmaps(animation.lie_loop)
        self._walk_durations = _durations(animation.walk, len(self._walk_frames))
        self._lie_durations = _durations(animation.lie_down, len(self._lie_frames))
        self._lie_loop_durations = _durations(animation.lie_loop, len(self._lie_loop_frames))
        self._entrance_direction = getattr(animation.walk, "entrance_direction", "right")
        if self._entrance_direction not in {"left", "right", "none"}:
            self._entrance_direction = "right"
        self.setGeometry(geometry)
        self.target_frame_width = round(geometry.width() * self.WIDTH_RATIO)
        self._started_at = self._clock()
        self.current_phase = "walking"
        self.current_frame_index = 0
        if not self._walk_frames and not self._lie_frames and not self._lie_loop_frames:
            self.hide()
            self.timer.stop()
            return
        self._refresh_frame()
        self.show()
        self.raise_()
        self.timer.start()

    def stop(self) -> None:
        self.timer.stop()
        self.current_phase = "hidden"
        self.hide()

    def _refresh_frame(self) -> None:
        elapsed = max(0.0, self._clock() - self._started_at)
        if elapsed < self.WALK_SECONDS and self._walk_frames:
            self.current_phase = "walking"
            self.current_frame_index = _timeline_index(
                int(elapsed * 1000),
                self._walk_durations,
                loop=True,
            )
        elif self._lie_frames:
            lie_elapsed_ms = max(0, int((elapsed - self.WALK_SECONDS) * 1000))
            lie_total = sum(self._lie_durations)
            if lie_elapsed_ms >= lie_total:
                if self._lie_loop_frames:
                    self.current_phase = "lying_loop"
                    self.current_frame_index = _timeline_index(
                        lie_elapsed_ms - lie_total,
                        self._lie_loop_durations,
                        loop=True,
                    )
                else:
                    self.current_phase = "holding"
                    self.current_frame_index = len(self._lie_frames) - 1
            else:
                self.current_phase = "lying"
                self.current_frame_index = _timeline_index(
                    lie_elapsed_ms,
                    self._lie_durations,
                    loop=False,
                )
        elif self._walk_frames:
            self.current_phase = "holding"
            self.current_frame_index = len(self._walk_frames) - 1
        self.update()

    def current_frame_rect(self) -> QRect:
        pixmap = self._current_pixmap()
        if pixmap is None or pixmap.isNull() or self.target_frame_width <= 0:
            return QRect()
        height = round(self.target_frame_width * pixmap.height() / pixmap.width())
        centered_x = (self.width() - self.target_frame_width) // 2
        if self.current_phase == "walking":
            elapsed = max(0.0, self._clock() - self._started_at)
            progress = min(1.0, elapsed / self.WALK_SECONDS)
            x = self._walking_x(progress)
        else:
            x = centered_x
        return QRect(x, (self.height() - height) // 2, self.target_frame_width, height)

    def _walking_x(self, progress: float) -> int:
        centered_x = (self.width() - self.target_frame_width) // 2
        if self._entrance_direction == "none":
            return centered_x
        start_x = -self.target_frame_width if self._entrance_direction == "left" else self.width()
        return round(start_x + (centered_x - start_x) * progress)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: ARG002 - Qt signature
        pixmap = self._current_pixmap()
        if pixmap is None or pixmap.isNull():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawPixmap(self.current_frame_rect(), pixmap)

    def _current_pixmap(self) -> QPixmap | None:
        if self.current_phase == "walking":
            frames = self._walk_frames
        elif self.current_phase == "lying_loop":
            frames = self._lie_loop_frames
        else:
            frames = self._lie_frames or self._walk_frames
        if not frames:
            return None
        return frames[min(self.current_frame_index, len(frames) - 1)]


class WorkFinishControlWindow(QFrame):
    """位于屏幕左上角、始终可点击的决策面板。"""

    finish_requested = Signal()
    continue_requested = Signal()
    closed = Signal()

    def __init__(self) -> None:
        super().__init__(None)
        self._prompt_started_at: datetime | None = None
        self.setObjectName("workFinishControlWindow")
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumWidth(320)
        self.setStyleSheet(
            f"""
            QFrame#workFinishControlWindow {{
                background: {COLORS['surface']};
                border: 1px solid {COLORS['border']};
                border-radius: 14px;
            }}
            QLabel#workFinishTitle {{ color: {COLORS['text']}; font-size: 20px; font-weight: 700; }}
            QLabel#workFinishTimeout {{ color: {COLORS['muted_text']}; font-size: 14px; }}
            QPushButton {{ border-radius: 12px; padding: 12px 20px; font-size: 18px; font-weight: 700; }}
            QPushButton#finishButton {{ background: {COLORS['accent']}; color: white; border: 1px solid {COLORS['accent']}; }}
            QPushButton#continueButton {{ background: {COLORS['surface_alt']}; color: {COLORS['text']}; border: 1px solid {COLORS['border']}; }}
            """
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 22)
        layout.setSpacing(12)
        title = QLabel("到下班时间啦", self)
        title.setObjectName("workFinishTitle")
        layout.addWidget(title)
        self.timeout_label = QLabel(self)
        self.timeout_label.setObjectName("workFinishTimeout")
        layout.addWidget(self.timeout_label)
        self.finish_button = QPushButton("下班啦🎉", self)
        self.finish_button.setObjectName("finishButton")
        self.continue_button = QPushButton("再加一会", self)
        self.continue_button.setObjectName("continueButton")
        for button in (self.finish_button, self.continue_button):
            button.setMinimumHeight(58)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            font = button.font()
            font.setPointSize(18)
            font.setBold(True)
            button.setFont(font)
            layout.addWidget(button)
        self.finish_button.clicked.connect(self.finish_requested.emit)
        self.continue_button.clicked.connect(self.continue_requested.emit)
        self.timer = QTimer(self)
        self.timer.setInterval(1_000)
        self.timer.timeout.connect(self._refresh_timeout)

    def show_for(self, available_geometry: QRect, prompt_started_at: datetime) -> None:
        self._prompt_started_at = prompt_started_at
        self._refresh_timeout()
        self.adjustSize()
        self.move(available_geometry.left() + 24, available_geometry.top() + 24)
        self.show()
        self.raise_()
        self.timer.start()

    def stop(self) -> None:
        self.timer.stop()
        self.hide()

    def closeEvent(self, event: QCloseEvent) -> None:
        super().closeEvent(event)
        self.closed.emit()

    def _refresh_timeout(self) -> None:
        if self._prompt_started_at is None:
            self.timeout_label.setText("")
            return
        now = datetime.now(tz=self._prompt_started_at.tzinfo) if self._prompt_started_at.tzinfo else datetime.now()
        remaining = max(0, ceil((self._prompt_started_at + PROMPT_TIMEOUT - now).total_seconds()))
        minutes, seconds = divmod(remaining, 60)
        self.timeout_label.setText(f"{minutes:02d}:{seconds:02d} 后自动下班")


class WorkFinishReminder(QObject):
    """协调动画层和控制层的轻量外观控制器。"""

    finish_requested = Signal()
    continue_requested = Signal()
    dismissed = Signal()

    def __init__(self, *, clock: Callable[[], float] = monotonic) -> None:
        super().__init__()
        self._shutting_down = False
        self.animation_window = WorkFinishAnimationWindow(clock=clock)
        self.control_window = WorkFinishControlWindow()
        self.control_window.finish_requested.connect(self.finish_requested.emit)
        self.control_window.continue_requested.connect(self.continue_requested.emit)
        self.control_window.closed.connect(self._control_closed)

    def show_for(
        self,
        package: PetPackage,
        geometry: QRect,
        prompt_started_at: datetime,
        *,
        available_geometry: QRect | None = None,
    ) -> None:
        self.animation_window.show_for(package, geometry)
        self.control_window.show_for(available_geometry or geometry, prompt_started_at)

    def hide(self) -> None:
        self.animation_window.stop()
        self.control_window.stop()

    def shutdown(self) -> None:
        self._shutting_down = True
        try:
            self.hide()
            self.animation_window.close()
            self.control_window.close()
        finally:
            self._shutting_down = False

    def _control_closed(self) -> None:
        if not self._shutting_down:
            self.dismissed.emit()

    @property
    def is_visible(self) -> bool:
        return self.control_window.isVisible()


def _pixmaps(definition: AnimationDefinition | None) -> tuple[QPixmap, ...]:
    if definition is None:
        return ()
    pixmaps = tuple(QPixmap(str(path)) for path in definition.frames)
    return tuple(pixmap for pixmap in pixmaps if not pixmap.isNull())


def _durations(definition: AnimationDefinition | None, frame_count: int) -> tuple[int, ...]:
    if definition is None or frame_count == 0:
        return ()
    source = definition.frame_durations_ms or tuple(round(1000 / definition.fps) for _ in range(frame_count))
    return tuple(max(1, round(duration / definition.speed_multiplier)) for duration in source[:frame_count])


def _timeline_index(elapsed_ms: int, durations: tuple[int, ...], *, loop: bool) -> int:
    if not durations:
        return 0
    total = sum(durations)
    position = elapsed_ms % total if loop else min(elapsed_ms, total - 1)
    boundary = 0
    for index, duration in enumerate(durations):
        boundary += duration
        if position < boundary:
            return index
    return len(durations) - 1


__all__ = [
    "WorkFinishAnimationWindow",
    "WorkFinishControlWindow",
    "WorkFinishReminder",
]
