"""不与聊天或倒计时争用空间的 Codex 状态气泡。"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QMouseEvent, QPaintEvent, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from petnest.core.codex_link import CodexLinkSnapshot


class _BubbleMessageLabel(QLabel):
    clicked = Signal()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class CodexStatusBubble(QWidget):
    """持续展示注意状态，并把完成提示折叠为未读徽标。"""

    activated = Signal()
    dismissed = Signal()

    def __init__(self, parent: QWidget | None = None, *, review_duration_ms: int = 10_000) -> None:
        flags = (
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.WindowStaysOnTopHint
        )
        super().__init__(parent, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setObjectName("codexStatusBubble")
        self.setStyleSheet(
            "QLabel { color: #684d45; font-size: 12px; }"
            "QPushButton { border: none; color: #a58b80; background: transparent; font-size: 15px; }"
            "QPushButton:hover { color: #7e5a4c; }"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(11, 7, 7, 7)
        layout.setSpacing(7)
        self.message_label = _BubbleMessageLabel(self)
        self.message_label.setWordWrap(True)
        self.message_label.setMaximumWidth(260)
        self.message_label.clicked.connect(self._activate)
        layout.addWidget(self.message_label, 1)
        self.close_button = QPushButton("×", self)
        self.close_button.setFixedSize(20, 20)
        self.close_button.clicked.connect(self._dismiss)
        layout.addWidget(self.close_button, 0, Qt.AlignmentFlag.AlignTop)
        self.dismiss_timer = QTimer(self)
        self.dismiss_timer.setSingleShot(True)
        self.dismiss_timer.timeout.connect(self._collapse_review)
        self._review_duration_ms = max(1, int(review_duration_ms))
        self._snapshot = CodexLinkSnapshot()
        self._anchor = QRect()
        self._avoid = QRect()
        self._is_compact = False

    @property
    def is_compact(self) -> bool:
        return self._is_compact

    def text(self) -> str:
        return self.message_label.text()

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802 - Qt override
        """Windows 透明顶层窗口必须显式绘制，样式表背景可能被合成器忽略。"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#efcdbd"), 1))
        painter.setBrush(QColor("#fffaf5"))
        painter.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 12, 12)

    def show_snapshot(
        self,
        snapshot: CodexLinkSnapshot,
        anchor_rect: QRect,
        avoid_rect: QRect | None = None,
    ) -> None:
        self.dismiss_timer.stop()
        self._snapshot = snapshot
        self._anchor = QRect(anchor_rect)
        self._avoid = QRect(avoid_rect) if avoid_rect is not None else QRect()
        self._is_compact = False
        if snapshot.state in {"idle", "running"}:
            self.hide()
            return
        self.message_label.setText(snapshot.message)
        self.close_button.show()
        self.adjustSize()
        self._place()
        self.show()
        self.raise_()
        if snapshot.state == "review":
            self.dismiss_timer.start(self._review_duration_ms)

    def reposition(self, anchor_rect: QRect, avoid_rect: QRect | None = None) -> None:
        self._anchor = QRect(anchor_rect)
        self._avoid = QRect(avoid_rect) if avoid_rect is not None else QRect()
        if self.isVisible():
            self._place()

    def clear(self) -> None:
        self.dismiss_timer.stop()
        self._snapshot = CodexLinkSnapshot()
        self._is_compact = False
        self.hide()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override
        if event.button() == Qt.MouseButton.LeftButton:
            self._activate()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _activate(self) -> None:
        self.dismiss_timer.stop()
        self.hide()
        self.activated.emit()

    def _dismiss(self) -> None:
        self.clear()
        self.dismissed.emit()

    def _collapse_review(self) -> None:
        if self._snapshot.state != "review":
            return
        if self._snapshot.unread_review_count <= 0:
            self.hide()
            return
        count = self._snapshot.unread_review_count
        self.message_label.setText("Codex · 1 个待查看" if count == 1 else f"Codex · {count} 个待查看")
        self.close_button.hide()
        self._is_compact = True
        self.adjustSize()
        self._place()
        self.show()

    def _place(self) -> None:
        screen = QGuiApplication.screenAt(self._anchor.center()) or self.screen() or QGuiApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        width = max(1, self.width())
        height = max(1, self.height())
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
        x = min(max(chosen.x(), available.left()), available.right() - width + 1)
        y = min(max(chosen.y(), available.top()), available.bottom() - height + 1)
        self.move(x, y)


__all__ = ["CodexStatusBubble"]
