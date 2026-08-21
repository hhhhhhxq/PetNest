"""可在编辑器、导入和导出页面复用的透明帧动画预览。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path, PureWindowsPath

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from petnest.core.package_validator import natural_sort_key
from petnest.ui.theme import COLORS


class CheckerboardLabel(QLabel):
    """在透明帧后绘制棋盘格，避免透明区域与窗口背景混淆。"""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.tile_size = 18
        self.light_color = QColor("#FBF5F0")
        self.dark_color = QColor("#F2E7DF")

    def paintEvent(self, event: object) -> None:  # noqa: ARG002 - Qt event signature
        painter = QPainter(self)
        tile = self.tile_size
        light = self.light_color
        dark = self.dark_color
        for y in range(0, self.height(), tile):
            for x in range(0, self.width(), tile):
                painter.fillRect(x, y, tile, tile, light if (x // tile + y // tile) % 2 == 0 else dark)
        pixmap = self.pixmap()
        if pixmap is not None and not pixmap.isNull():
            scaled = pixmap.scaled(
                self.contentsRect().size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            painter.drawPixmap(
                (self.width() - scaled.width()) // 2,
                (self.height() - scaled.height()) // 2,
                scaled,
            )
        elif self.text():
            painter.setPen(QColor(COLORS["muted_text"]))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.text())


class AnimationPreviewWidget(QWidget):
    """播放 PNG 帧并按逐帧时长或 FPS 驱动计时器。"""

    frame_changed = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.preview_frame_index = 0
        self._pixmaps: tuple[QPixmap, ...] = ()
        self._durations: tuple[int, ...] = ()
        self._paused = True
        self._invalid_frame = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.preview_label = CheckerboardLabel("暂无可预览的帧", self)
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setMinimumSize(220, 260)
        self.preview_label.setProperty("checkerboard", True)
        self.preview_label.setStyleSheet(f"border: 1px solid {COLORS['border']}; border-radius: 10px;")
        layout.addWidget(self.preview_label, 1)
        self.preview_frame_label = QLabel("—", self)
        self.preview_frame_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_frame_label.setObjectName("mutedLabel")
        layout.addWidget(self.preview_frame_label)
        self.preview_play_button = QPushButton("播放预览", self)
        self.preview_play_button.clicked.connect(self._toggle_playing)
        layout.addWidget(self.preview_play_button)
        self.preview_timer = QTimer(self)
        self.preview_timer.timeout.connect(self._advance_preview)

    @property
    def frame_count(self) -> int:
        return len(self._pixmaps)

    def set_frames(
        self,
        frames: Sequence[Path | QPixmap],
        *,
        frame_durations_ms: Sequence[int] | None = None,
        fps: float | None = None,
    ) -> None:
        """设置帧；帧时长优先于 FPS，缺帧会停止播放并显示错误。"""

        self.preview_timer.stop()
        self._pixmaps = tuple(item if isinstance(item, QPixmap) else QPixmap(str(item)) for item in frames)
        self._invalid_frame = not self._pixmaps or any(item.isNull() for item in self._pixmaps)
        self._durations = _durations(len(self._pixmaps), frame_durations_ms, fps)
        self.preview_frame_index = 0
        self._paused = self._invalid_frame
        self.preview_play_button.setText("播放预览" if self._paused else "暂停预览")
        self._render()
        if self._invalid_frame:
            self.preview_label.setText("无法读取此帧预览")
            self.preview_frame_label.setText("—")
            return
        self._render()
        self._start_timer()

    def set_animation(self, definition: Mapping[str, object], root: Path) -> None:
        """从宠物动作定义读取相对资源目录。"""

        configured = definition.get("path")
        if not isinstance(configured, str) or Path(configured).is_absolute() or PureWindowsPath(configured).is_absolute():
            self.set_frames(())
            return
        animation_root = (Path(root).expanduser().resolve() / configured).resolve()
        root_resolved = Path(root).expanduser().resolve()
        if not animation_root.is_relative_to(root_resolved) or not animation_root.is_dir():
            self.set_frames(())
            return
        frames = tuple(sorted((item for item in animation_root.iterdir() if item.is_file() and item.suffix.casefold() == ".png"), key=natural_sort_key))
        raw_durations = definition.get("frame_durations_ms")
        durations = raw_durations if isinstance(raw_durations, (list, tuple)) else None
        fps = definition.get("fps") if isinstance(definition.get("fps"), (int, float)) else None
        self.set_frames(frames, frame_durations_ms=durations, fps=float(fps) if fps is not None else None)

    def set_playing(self, playing: bool) -> None:
        if self._invalid_frame:
            self._paused = True
            self.preview_timer.stop()
            return
        self._paused = not playing
        if self._paused:
            self.preview_timer.stop()
            self.preview_play_button.setText("播放预览")
        else:
            self.preview_play_button.setText("暂停预览")
            self._start_timer()

    def set_current_frame(self, index: int, *, pause: bool = False) -> None:
        """定位到指定帧；需要用户检查单帧时可同时暂停播放。"""

        if not self._pixmaps or self._invalid_frame:
            return
        if pause:
            self.set_playing(False)
        self.preview_frame_index = max(0, min(int(index), len(self._pixmaps) - 1))
        self._render()
        self.frame_changed.emit(self.preview_frame_index)

    def replay(self) -> None:
        """从第一帧重新开始循环播放。"""

        if not self._pixmaps or self._invalid_frame:
            return
        self.set_current_frame(0)
        self.set_playing(True)

    def next_delay_ms(self) -> int | None:
        if not self._durations or self.preview_frame_index >= len(self._durations):
            return None
        return self._durations[self.preview_frame_index]

    def clear(self) -> None:
        self.set_frames(())

    def _start_timer(self) -> None:
        delay = self.next_delay_ms()
        if delay is not None and not self._paused:
            self.preview_timer.start(delay)

    def _advance_preview(self) -> None:
        if self._paused or not self._pixmaps:
            return
        self.preview_frame_index = (self.preview_frame_index + 1) % len(self._pixmaps)
        self._render()
        self.frame_changed.emit(self.preview_frame_index)
        self._start_timer()

    def _render(self) -> None:
        if not self._pixmaps or self._invalid_frame:
            self.preview_label.setPixmap(QPixmap())
            return
        self.preview_label.setText("")
        self.preview_label.setPixmap(self._pixmaps[self.preview_frame_index])
        delay = self.next_delay_ms()
        self.preview_frame_label.setText(
            f"第 {self.preview_frame_index + 1} 帧" + (f" · {delay} ms" if delay is not None else "")
        )

    def _toggle_playing(self) -> None:
        self.set_playing(self._paused)

    def closeEvent(self, event: object) -> None:  # noqa: N802 - Qt override signature.
        self.preview_timer.stop()
        super().closeEvent(event)  # type: ignore[arg-type]


def _durations(
    frame_count: int,
    raw_durations: Sequence[int] | None,
    fps: float | None,
) -> tuple[int, ...]:
    if frame_count <= 0:
        return ()
    if raw_durations is not None and len(raw_durations) == frame_count:
        parsed = tuple(int(item) for item in raw_durations)
        if all(item > 0 for item in parsed):
            return parsed
    delay = max(1, round(1000 / fps)) if fps and fps > 0 else 100
    return (delay,) * frame_count


__all__ = ["AnimationPreviewWidget", "CheckerboardLabel"]
