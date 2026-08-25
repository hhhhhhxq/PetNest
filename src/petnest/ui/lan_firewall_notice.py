"""桌宠旁不会自动消失的 Windows 防火墙提醒。"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QMouseEvent, QPaintEvent, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget


class _ClickableLabel(QLabel):
    clicked = Signal()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class LanFirewallNoticeBubble(QWidget):
    activated = Signal()
    dismissed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        flags = (
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.WindowStaysOnTopHint
        )
        super().__init__(parent, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setStyleSheet(
            "QLabel { color: #7d3d22; font-size: 12px; }"
            "QPushButton { border: none; color: #b06748; background: transparent; font-size: 15px; }"
            "QPushButton:hover { color: #7d3d22; }"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 7, 8)
        layout.setSpacing(7)
        self.message_label = _ClickableLabel(
            "局域网设备可能连不上\n当前是公用网络，点击检查防火墙设置",
            self,
        )
        self.message_label.setWordWrap(True)
        self.message_label.setMaximumWidth(270)
        self.message_label.clicked.connect(self._activate)
        layout.addWidget(self.message_label, 1)
        self.close_button = QPushButton("×", self)
        self.close_button.setFixedSize(20, 20)
        self.close_button.clicked.connect(self._dismiss)
        layout.addWidget(self.close_button, 0, Qt.AlignmentFlag.AlignTop)
        self._anchor = QRect()
        self._avoid = QRect()

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#ef9f7c"), 1))
        painter.setBrush(QColor("#fff3ec"))
        painter.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 12, 12)

    def show_notice(self, anchor_rect: QRect, *, avoid_rect: QRect | None = None) -> None:
        self._anchor = QRect(anchor_rect)
        self._avoid = QRect(avoid_rect) if avoid_rect is not None else QRect()
        self.adjustSize()
        self._place()
        self.show()
        self.raise_()

    def reposition(self, anchor_rect: QRect, *, avoid_rect: QRect | None = None) -> None:
        self._anchor = QRect(anchor_rect)
        self._avoid = QRect(avoid_rect) if avoid_rect is not None else QRect()
        if self.isVisible():
            self._place()

    def clear(self) -> None:
        self.hide()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._activate()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _activate(self) -> None:
        self.hide()
        self.activated.emit()

    def _dismiss(self) -> None:
        self.hide()
        self.dismissed.emit()

    def _place(self) -> None:
        screen = QGuiApplication.screenAt(self._anchor.center()) or self.screen() or QGuiApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        width, height = max(1, self.width()), max(1, self.height())
        candidates = (
            QPoint(self._anchor.center().x() - width // 2, self._anchor.top() - height - 10),
            QPoint(self._anchor.right() + 10, self._anchor.center().y() - height // 2),
            QPoint(self._anchor.left() - width - 10, self._anchor.center().y() - height // 2),
            QPoint(self._anchor.center().x() - width // 2, self._anchor.bottom() + 10),
        )
        chosen = candidates[0]
        for candidate in candidates:
            geometry = QRect(candidate, self.size())
            if available.contains(geometry) and (self._avoid.isNull() or not geometry.intersects(self._avoid)):
                chosen = candidate
                break
        self.move(
            min(max(chosen.x(), available.left()), available.right() - width + 1),
            min(max(chosen.y(), available.top()), available.bottom() - height + 1),
        )


__all__ = ["LanFirewallNoticeBubble"]
