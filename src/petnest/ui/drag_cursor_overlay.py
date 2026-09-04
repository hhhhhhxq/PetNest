"""原生拖放期间显示输入透明的自定义道具光标。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QLabel, QWidget


class DragCursorOverlay(QLabel):
    """让指定图像热点跟随全局拖拽坐标的小型透明窗口。"""

    _MAX_ICON_SIZE = QSize(64, 64)

    def __init__(self, parent: QWidget | None = None) -> None:
        flags = (
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowTransparentForInput
        )
        super().__init__(parent, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setStyleSheet("background: transparent; border: none;")
        self._hotspot = QPoint()

    def show_at(
        self,
        global_hotspot: QPoint,
        icon: Path,
        *,
        hotspot: tuple[int, int],
    ) -> None:
        pixmap = QPixmap(str(icon))
        if pixmap.isNull():
            self.clear()
            return
        source_size = pixmap.size()
        pixmap = pixmap.scaled(
            self._MAX_ICON_SIZE,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._hotspot = QPoint(
            round(hotspot[0] * pixmap.width() / source_size.width()),
            round(hotspot[1] * pixmap.height() / source_size.height()),
        )
        self.setPixmap(pixmap)
        self.setFixedSize(pixmap.size())
        self.move_hotspot(global_hotspot)
        self.show()
        self.raise_()

    def move_hotspot(self, global_hotspot: QPoint) -> None:
        self.move(global_hotspot - self._hotspot)

    def clear(self) -> None:
        self.hide()
        self.clear_pixmap()
        self._hotspot = QPoint()

    def clear_pixmap(self) -> None:
        super().clear()


__all__ = ["DragCursorOverlay"]
