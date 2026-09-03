"""Reusable Qt widgets for PetNest pet-store cards and idle previews."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QMouseEvent, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from petnest.core.pet_store_catalog import PetStoreItem
from petnest.core.pet_store_state import PetStoreStatus


_STATUS_TEXT = {
    PetStoreStatus.ADOPTED: "已领养",
    PetStoreStatus.UPDATE_AVAILABLE: "可更新",
    PetStoreStatus.LOCAL_EXISTING: "本地已有",
}


class PetStoreCard(QFrame):
    selected = Signal(str)
    cover_requested = Signal(str)

    def __init__(
        self,
        item: PetStoreItem,
        parent: QWidget | None = None,
        *,
        package_size: int | None = None,
    ) -> None:
        super().__init__(parent)
        self.item = item
        self._cover_requested = False
        self.setObjectName("petStoreCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumWidth(190)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(7)

        cover_shell = QFrame(self)
        self.cover_shell = cover_shell
        cover_shell.setObjectName("petStoreCover")
        cover_layout = QVBoxLayout(cover_shell)
        cover_layout.setContentsMargins(0, 0, 0, 0)
        self.cover_label = QLabel("🐾", cover_shell)
        self.cover_label.setObjectName("petStoreCoverLabel")
        self.cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover_label.setFixedHeight(128)
        cover_layout.addWidget(self.cover_label)
        self.status_badge = QLabel("", cover_shell)
        self.status_badge.setObjectName("petStoreBadge")
        self.status_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_badge.hide()
        layout.addWidget(cover_shell)

        self.name_label = QLabel(item.name, self)
        self.name_label.setObjectName("petStoreName")
        layout.addWidget(self.name_label)
        details = QHBoxLayout()
        self.action_label = QLabel(f"{item.action_count} 个动作", self)
        self.action_label.setObjectName("mutedLabel")
        details.addWidget(self.action_label)
        details.addStretch(1)
        self.size_label = QLabel(
            _format_bytes(item.package.size if package_size is None else package_size),
            self,
        )
        self.size_label.setObjectName("mutedLabel")
        details.addWidget(self.size_label)
        layout.addLayout(details)
        self.updated_label = QLabel(
            f"更新于 {item.updated_at.astimezone().strftime('%Y-%m-%d')}", self
        )
        self.updated_label.setObjectName("mutedLabel")
        layout.addWidget(self.updated_label)

    def set_store_status(self, status: PetStoreStatus) -> None:
        text = _STATUS_TEXT.get(status)
        if text is None:
            self.status_badge.clear()
            self.status_badge.hide()
            return
        self.status_badge.setText(text)
        self.status_badge.setProperty("storeStatus", status.value)
        self.status_badge.style().unpolish(self.status_badge)
        self.status_badge.style().polish(self.status_badge)
        self.status_badge.show()
        self.status_badge.adjustSize()
        self.status_badge.move(8, 8)
        self.status_badge.raise_()

    def set_cover(self, path: Path) -> bool:
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            self.cover_label.setText("🐾")
            return False
        self.cover_label.setText("")
        self.cover_label.setPixmap(
            pixmap.scaled(
                self.cover_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        return True

    def request_cover_if_visible(self, viewport: QWidget) -> None:
        if self._cover_requested or not self.isVisibleTo(viewport):
            return
        top_left = self.mapTo(viewport, QPoint(0, 0))
        if not QRect(top_left, self.size()).intersects(viewport.rect()):
            return
        self._cover_requested = True
        self.cover_requested.emit(self.item.identifier)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.selected.emit(self.item.identifier)
        super().mousePressEvent(event)


class PetStoreIdlePreview(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("petStorePreview")
        layout = QVBoxLayout(self)
        self.frame_label = QLabel("预览加载中…", self)
        self.frame_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.frame_label.setMinimumSize(260, 260)
        layout.addWidget(self.frame_label)
        self.frames: list[QPixmap] = []
        self.frame_durations_ms: tuple[int, ...] = ()
        self.current_frame_index = 0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.advance_frame)

    def load_strip(
        self,
        path: Path,
        *,
        frame_width: int,
        frame_height: int,
        durations_ms: tuple[int, ...],
    ) -> bool:
        self.stop()
        strip = QPixmap(str(path))
        if (
            strip.isNull()
            or frame_width <= 0
            or frame_height <= 0
            or strip.height() != frame_height
            or strip.width() % frame_width
        ):
            self.frame_label.setText("无法播放动画预览")
            return False
        frame_count = strip.width() // frame_width
        if frame_count != len(durations_ms) or any(value <= 0 for value in durations_ms):
            self.frame_label.setText("动画预览时间线无效")
            return False
        self.frames = [
            strip.copy(index * frame_width, 0, frame_width, frame_height)
            for index in range(frame_count)
        ]
        self.frame_durations_ms = tuple(durations_ms)
        self.current_frame_index = 0
        self._show_current_frame()
        self.timer.start(self.frame_durations_ms[0])
        return True

    def advance_frame(self) -> None:
        if not self.frames:
            return
        self.current_frame_index = (self.current_frame_index + 1) % len(self.frames)
        self._show_current_frame()
        self.timer.start(self.frame_durations_ms[self.current_frame_index])

    def stop(self) -> None:
        self.timer.stop()
        self.frames = []
        self.frame_durations_ms = ()
        self.current_frame_index = 0
        self.frame_label.clear()

    def _show_current_frame(self) -> None:
        pixmap = self.frames[self.current_frame_index]
        self.frame_label.setText("")
        self.frame_label.setPixmap(
            pixmap.scaled(
                self.frame_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )


def _format_bytes(size: int) -> str:
    value = float(size)
    for suffix in ("B", "KB", "MB", "GB"):
        if value < 1024 or suffix == "GB":
            return f"{value:.0f} {suffix}" if suffix == "B" else f"{value:.1f} {suffix}"
        value /= 1024
    return f"{size} B"


__all__ = ["PetStoreCard", "PetStoreIdlePreview"]
