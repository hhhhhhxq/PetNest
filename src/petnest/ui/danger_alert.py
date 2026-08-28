"""Confirmation and mouse-transparent full-screen danger alert UI."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Sequence
from math import cos, pi
from time import monotonic

from PySide6.QtCore import QRect, QTimer, Qt
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPaintEvent, QPainter
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from petnest.models.lan_interaction import LanPeer
from petnest.ui.theme import dialog_stylesheet


class DangerAlertConfirmDialog(QDialog):
    """Show the exact online recipients before a high-priority alert is sent."""

    def __init__(
        self,
        *,
        online: Sequence[LanPeer],
        unavailable: Sequence[LanPeer] = (),
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("发送危险预警")
        self.setModal(True)
        self.setMinimumWidth(420)
        self.setStyleSheet(dialog_stylesheet())
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(12)

        title = QLabel("确认发送“危险靠近”预警？", self)
        title.setStyleSheet("font-size: 18px; font-weight: 700; color: #9f1d20;")
        layout.addWidget(title)
        hint = QLabel("接收方屏幕将红色闪烁 3 次。请只在确有危险时使用。", self)
        hint.setWordWrap(True)
        layout.addWidget(hint)

        online_names = "、".join(peer.display_name for peer in online)
        self.online_label = QLabel(
            f"在线接收人（{len(online)}）：{online_names}"
            if online
            else "当前没有其他在线成员",
            self,
        )
        self.online_label.setWordWrap(True)
        layout.addWidget(self.online_label)

        unavailable_names = "、".join(peer.display_name for peer in unavailable)
        self.unavailable_label = QLabel(
            f"当前不会收到（{len(unavailable)}）：{unavailable_names}"
            if unavailable
            else "没有离线或状态未知的已保存伙伴",
            self,
        )
        self.unavailable_label.setWordWrap(True)
        self.unavailable_label.setStyleSheet("color: #777777;")
        layout.addWidget(self.unavailable_label)

        message_label = QLabel("提示文案（可选）", self)
        layout.addWidget(message_label)
        self.message_input = QLineEdit(self)
        self.message_input.setMaxLength(30)
        self.message_input.setPlaceholderText("留空则只显示红色警示")
        layout.addWidget(self.message_input)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel_button = QPushButton("取消", self)
        cancel_button.clicked.connect(self.reject)
        buttons.addWidget(cancel_button)
        self.send_button = QPushButton("立即发送", self)
        self.send_button.setEnabled(bool(online))
        self.send_button.setStyleSheet(
            "QPushButton { background: #c62828; color: white; border: 0; "
            "border-radius: 7px; padding: 8px 18px; font-weight: 700; }"
            "QPushButton:disabled { background: #d9a6a6; color: #6d3334; }"
        )
        self.send_button.clicked.connect(self.accept)
        buttons.addWidget(self.send_button)
        layout.addLayout(buttons)

    def alert_message(self) -> str:
        return self.message_input.text().strip()


class DangerAlertOverlay(QWidget):
    """Briefly cover one screen with a focus-free, mouse-transparent red warning."""

    DURATION_SECONDS = 1.5
    PEAK_COUNT = 3
    MAX_SEEN_IDS = 256

    def __init__(
        self,
        *,
        clock: Callable[[], float] = monotonic,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._clock = clock
        self.started_at = 0.0
        self.sender_name = ""
        self.alert_message = ""
        self.red_alpha = 0
        self._seen_ids: set[str] = set()
        self._seen_order: deque[str] = deque()
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
        self.timer.timeout.connect(self._refresh)

    def show_alert(
        self,
        alert_id: str,
        sender_name: str,
        geometry: QRect,
        message: str = "",
    ) -> None:
        alert_id = str(alert_id).strip()
        if not alert_id or alert_id in self._seen_ids:
            return
        self._seen_ids.add(alert_id)
        self._seen_order.append(alert_id)
        while len(self._seen_order) > self.MAX_SEEN_IDS:
            removed = self._seen_order.popleft()
            self._seen_ids.discard(removed)
        self.sender_name = str(sender_name).strip() or "附近伙伴"
        self.alert_message = str(message).strip()[:30]
        self.setGeometry(geometry)
        self.started_at = self._clock()
        self._refresh()
        self.show()
        self.raise_()
        self.timer.start()

    def stop(self) -> None:
        self.timer.stop()
        self.red_alpha = 0
        self.hide()

    def _refresh(self) -> None:
        elapsed = max(0.0, self._clock() - self.started_at)
        if elapsed >= self.DURATION_SECONDS:
            self.stop()
            return
        phase = elapsed / self.DURATION_SECONDS * self.PEAK_COUNT
        self.red_alpha = round(55 + 105 * (0.5 - 0.5 * cos(phase * 2 * pi)))
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802, ARG002 - Qt override.
        painter = QPainter(self)
        self._paint_warning_background(painter)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        center = self.rect().adjusted(40, 40, -40, -40)
        if self.alert_message:
            painter.setPen(QColor(255, 245, 242, 245))
            title_font = QFont()
            title_font.setBold(True)
            title_font.setPixelSize(max(34, min(68, self.height() // 13)))
            painter.setFont(title_font)
            painter.drawText(center, Qt.AlignmentFlag.AlignCenter, self.alert_message)
        painter.setPen(QColor(48, 5, 9, 220))
        sender_font = QFont()
        sender_font.setPixelSize(max(13, min(20, self.height() // 42)))
        painter.setFont(sender_font)
        painter.drawText(
            self.rect().adjusted(32, 28, -32, -28),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom,
            f"来自：{self.sender_name}",
        )
        painter.end()

    def _paint_warning_background(self, painter: QPainter) -> None:
        rect = self.rect()
        if rect.isEmpty():
            return
        center_alpha = max(28, round(self.red_alpha * 0.42))
        edge_alpha = min(230, self.red_alpha + 55)
        painter.fillRect(rect, QColor(112, 0, 10, center_alpha))

        fade_x = max(1.0, rect.width() * 0.40)
        fade_y = max(1.0, rect.height() * 0.40)
        gradients = (
            QLinearGradient(0.0, 0.0, fade_x, 0.0),
            QLinearGradient(float(rect.width()), 0.0, float(rect.width()) - fade_x, 0.0),
            QLinearGradient(0.0, 0.0, 0.0, fade_y),
            QLinearGradient(0.0, float(rect.height()), 0.0, float(rect.height()) - fade_y),
        )
        edge_color = QColor(135, 0, 12, edge_alpha)
        transparent = QColor(135, 0, 12, 0)
        for gradient in gradients:
            gradient.setColorAt(0.0, edge_color)
            gradient.setColorAt(1.0, transparent)
            painter.fillRect(rect, gradient)

        glow_x = max(1.0, rect.width() * 0.14)
        glow_y = max(1.0, rect.height() * 0.14)
        glow_alpha = min(195, self.red_alpha + 35)
        glow_gradients = (
            QLinearGradient(0.0, 0.0, glow_x, 0.0),
            QLinearGradient(float(rect.width()), 0.0, float(rect.width()) - glow_x, 0.0),
            QLinearGradient(0.0, 0.0, 0.0, glow_y),
            QLinearGradient(0.0, float(rect.height()), 0.0, float(rect.height()) - glow_y),
        )
        for gradient in glow_gradients:
            gradient.setColorAt(0.0, QColor(255, 60, 48, glow_alpha))
            gradient.setColorAt(0.35, QColor(235, 22, 28, round(glow_alpha * 0.46)))
            gradient.setColorAt(1.0, QColor(220, 15, 24, 0))
            painter.fillRect(rect, gradient)
