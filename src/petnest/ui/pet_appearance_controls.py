"""Visual choices and an aspect-fit preview for the pet library."""

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QHBoxLayout,
    QGridLayout,
    QSizePolicy,
    QToolButton,
    QWidget,
)


class PetToggle(QCheckBox):
    """A labelled switch with normal checkbox keyboard/accessibility semantics."""

    def sizeHint(self):
        return QSize(self.fontMetrics().horizontalAdvance(self.text()) + 50, 26)

    def minimumSizeHint(self):
        return self.sizeHint()

    def hitButton(self, point):
        return self.rect().contains(point)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.isEnabled():
            painter.setOpacity(0.45)
        top = (self.height() - 20) / 2
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#d68c65" if self.isChecked() else "#ded5cd"))
        painter.drawRoundedRect(QRectF(1, top, 34, 20), 10, 10)
        painter.setBrush(QColor("#fffdfa"))
        painter.drawEllipse(QRectF(18 if self.isChecked() else 4, top + 3, 14, 14))
        painter.setPen(QColor("#51463e"))
        painter.drawText(
            self.rect().adjusted(44, 0, 0, 0),
            Qt.AlignmentFlag.AlignVCenter,
            self.text(),
        )
        if self.hasFocus():
            painter.setPen(QPen(QColor("#a76747"), 1, Qt.PenStyle.DotLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(QRectF(0, top - 2, 37, 24), 12, 12)


class AppearanceChoices(QWidget):
    currentIndexChanged = Signal(int)

    def __init__(self, choices, *, icon_size, columns=None, parent=None):
        super().__init__(parent)
        self._choices = tuple(choices.items())
        self._index = -1
        self.buttons = []
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        row = QGridLayout(self) if columns else QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        for index, (_, label) in enumerate(self._choices):
            button = QToolButton(self)
            button.setObjectName("appearanceChoice")
            button.setText(label)
            button.setAccessibleName(label)
            button.setToolTip(label)
            button.setCheckable(True)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            button.setIconSize(icon_size)
            button.setMinimumHeight(icon_size.height() + 34)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.group.addButton(button, index)
            self.buttons.append(button)
            if columns:
                row.addWidget(button, index // columns, index % columns)
                row.setColumnStretch(index % columns, 1)
            else:
                row.addWidget(button, 1)
        self.group.idClicked.connect(self.setCurrentIndex)

    def findData(self, value):
        return next((i for i, (key, _) in enumerate(self._choices) if key == value), -1)

    def currentData(self):
        return self._choices[self._index][0] if self._index >= 0 else None

    def setCurrentIndex(self, index):
        if 0 <= index < len(self.buttons) and index != self._index:
            self._index = index
            self.buttons[index].setChecked(True)
            self.currentIndexChanged.emit(index)

    def set_images(self, images):
        for button, (key, _) in zip(self.buttons, self._choices, strict=True):
            button.setIcon(QIcon(QPixmap.fromImage(images[key])))


class PetPreview(QWidget):
    """Paint inside a bounded stage; images never impose a QLabel minimum size."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(220)
        self.setFixedHeight(190)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._pixmap = QPixmap()
        self._source = QRect()

    def set_frame(self, pixmap, *, cat=False):
        self._pixmap = pixmap
        # Remove empty canvas padding while retaining the cat and floating keycaps.
        self._source = QRect(38, 50, 270, 250) if cat else pixmap.rect()
        self.update()

    def target_rect(self):
        available = self.rect().adjusted(8, 4, -8, -4)
        size = self._source.size().scaled(
            available.size(), Qt.AspectRatioMode.KeepAspectRatio
        )
        return QRectF(
            (self.width() - size.width()) / 2,
            (self.height() - size.height()) / 2,
            size.width(),
            size.height(),
        )

    def logical_cursor(self):
        rect = self.target_rect()
        if rect.isEmpty():
            return QPointF(184, 124)
        cursor = self.mapFromGlobal(QCursor.pos())
        return QPointF(
            self._source.x()
            + (cursor.x() - rect.x()) * self._source.width() / rect.width(),
            self._source.y()
            + (cursor.y() - rect.y()) * self._source.height() / rect.height(),
        )

    def paintEvent(self, event):
        if not self._pixmap.isNull():
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.drawPixmap(self.target_rect(), self._pixmap, QRectF(self._source))


LIBRARY_STYLE = """
QFrame#petLibraryCard { background: #fffdfa; border: 1px solid #eadfd5; border-radius: 16px; }
QFrame#petPreviewCard { background: #f7eee5; border: 1px solid #eadfd5; border-radius: 16px; }
QLabel#petSectionTitle { color: #51463e; font-size: 13px; font-weight: 600; }
QLabel#petDetailTitle { color: #413a35; font-size: 22px; font-weight: 700; }
QLabel#petHint { color: #8b7b70; font-size: 11px; background: transparent; }
QLabel#petStatusBadge { color: #548169; background: #eaf2eb; border-radius: 9px; padding: 5px 10px; font-size: 11px; }
QLabel#petInputStatus { font-size: 13px; font-weight: 600; background: transparent; }
QToolButton#appearanceChoice {
    background: #fcf8f3; border: 2px solid transparent; border-radius: 11px;
    padding: 4px; color: #776a60; font-size: 11px;
}
QToolButton#appearanceChoice:hover { background: #f7eee5; border-color: #e7c7b3; }
QToolButton#appearanceChoice:checked { background: #fff0e5; border-color: #d68c65; color: #9f5334; font-weight: 600; }
QToolButton#appearanceChoice:focus { border-color: #a76747; }
QScrollArea#petDetailScroll, QWidget#petDetailBody { background: transparent; border: none; }
QListWidget#petLibraryList { border: none; background: transparent; outline: none; }
QListWidget#petLibraryList::item { padding: 13px 10px; margin-bottom: 6px; border-radius: 10px; }
QListWidget#petLibraryList::item:selected { background: #f9ebe1; color: #ad6949; }
"""
