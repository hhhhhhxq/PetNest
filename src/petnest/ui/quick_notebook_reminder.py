"""宠物旁持久显示的便签提醒卡片。"""

from __future__ import annotations

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPaintEvent, QPainter, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from petnest.ui.quick_notebook_window import place_notebook


class QuickNotebookReminderCard(QFrame):
    completed = Signal(str)
    snoozed = Signal(str)
    open_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        flags = Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
        super().__init__(parent, flags)
        self.setObjectName("quickNotebookReminderCard")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._reminder_id = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 13, 15, 13)
        layout.setSpacing(9)
        caption = QLabel("便签提醒", self)
        caption.setObjectName("quickNotebookReminderCaption")
        layout.addWidget(caption)
        self.message_label = QLabel(self)
        self.message_label.setObjectName("quickNotebookReminderMessage")
        self.message_label.setWordWrap(True)
        self.message_label.setMaximumWidth(280)
        layout.addWidget(self.message_label)
        actions = QHBoxLayout()
        actions.setSpacing(7)
        self.snooze_button = QPushButton("稍后 10 分钟", self)
        self.open_button = QPushButton("打开便签", self)
        self.complete_button = QPushButton("完成", self)
        self.complete_button.setObjectName("primaryButton")
        actions.addWidget(self.snooze_button)
        actions.addStretch(1)
        actions.addWidget(self.open_button)
        actions.addWidget(self.complete_button)
        layout.addLayout(actions)

        self.setStyleSheet(
            "QFrame#quickNotebookReminderCard { background: transparent; }"
            "QLabel#quickNotebookReminderCaption { color: #A45F43; font-size: 11px; font-weight: 700; }"
            "QLabel#quickNotebookReminderMessage { color: #4B4641; font-size: 13px; }"
            "QPushButton { background: #FFFFFF; color: #6F625A; border: 1px solid #E3D7CC; "
            "border-radius: 8px; padding: 6px 9px; }"
            "QPushButton#primaryButton { background: #D98663; color: white; border-color: #D98663; }"
        )
        self.complete_button.clicked.connect(self._complete)
        self.snooze_button.clicked.connect(self._snooze)
        self.open_button.clicked.connect(self._open)

    def show_reminder(self, reminder_id: str, text: str, anchor_rect: QRect) -> None:
        self._reminder_id = reminder_id
        self.message_label.setText(text)
        self.adjustSize()
        screen = QGuiApplication.screenAt(anchor_rect.center()) or QGuiApplication.primaryScreen()
        if screen is not None:
            self.move(place_notebook(anchor_rect, self.size(), screen.availableGeometry()))
        self.show()
        self.raise_()

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#DDCFC2"), 1))
        painter.setBrush(QColor("#FFFDFA"))
        painter.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 14, 14)

    def _complete(self) -> None:
        reminder_id = self._reminder_id
        self.hide()
        if reminder_id:
            self.completed.emit(reminder_id)

    def _snooze(self) -> None:
        reminder_id = self._reminder_id
        self.hide()
        if reminder_id:
            self.snoozed.emit(reminder_id)

    def _open(self) -> None:
        reminder_id = self._reminder_id
        self.hide()
        if reminder_id:
            self.open_requested.emit(reminder_id)


__all__ = ["QuickNotebookReminderCard"]
