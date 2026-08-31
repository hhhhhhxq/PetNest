"""独立互动道具盒与标准 Qt 拖放源控件。"""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QEvent, QMimeData, QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QDrag, QEnterEvent, QGuiApplication, QIcon, QMouseEvent
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QToolButton,
    QWidget,
)

from petnest.core.interaction_items import ResolvedInteractionItem
from petnest.ui.lucide_icons import lucide_icon


INTERACTION_ITEM_MIME = "application/x-petnest-interaction-item"
_TOOLBOX_GAP = 8
_MAX_ITEMS = 8
_GRID_COLUMNS = 4


def clamp_toolbox_position(pet_rect: QRect, available: QRect, size: QSize) -> QPoint:
    """把工具盒放在宠物右侧，必要时翻到左侧并限制在可用屏幕内。"""
    width = max(0, size.width())
    height = max(0, size.height())
    x = pet_rect.right() + 1 + _TOOLBOX_GAP
    if x + width > available.right() + 1:
        x = pet_rect.left() - _TOOLBOX_GAP - width
    max_x = max(available.left(), available.right() - width + 1)
    max_y = max(available.top(), available.bottom() - height + 1)
    x = min(max(x, available.left()), max_x)
    y = min(max(pet_rect.top(), available.top()), max_y)
    return QPoint(x, y)


class InteractionItemButton(QToolButton):
    """以通用道具 ID 作为 Qt 拖放载荷的道具按钮。"""

    def __init__(self, item: ResolvedInteractionItem, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.item = item
        self._drag_start: QPoint | None = None
        self.setToolTip(item.definition.label)
        self.setAccessibleName(item.definition.label)
        self.setIcon(QIcon(str(item.definition.icon)))
        self.setIconSize(QSize(36, 36))
        self.setFixedSize(52, 52)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def mime_data(self) -> QMimeData:
        mime = QMimeData()
        mime.setData(
            INTERACTION_ITEM_MIME,
            self.item.definition.identifier.encode("utf-8"),
        )
        return mime

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override
        if (
            self._drag_start is None
            or not event.buttons() & Qt.MouseButton.LeftButton
            or (event.position().toPoint() - self._drag_start).manhattanLength()
            < QApplication.startDragDistance()
        ):
            super().mouseMoveEvent(event)
            return

        self._drag_start = None
        pixmap = self.icon().pixmap(self.iconSize())
        drag = QDrag(self)
        drag.setMimeData(self.mime_data())
        if not pixmap.isNull():
            drag.setPixmap(pixmap)
            drag.setHotSpot(QPoint(pixmap.width() // 2, pixmap.height() // 2))
        drag.exec(Qt.DropAction.MoveAction)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override
        self._drag_start = None
        super().mouseReleaseEvent(event)


class InteractionItemToolbox(QFrame):
    """跟随宠物显示、可展开至两行道具网格的独立工具窗。"""

    hover_changed = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        flags = (
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.WindowStaysOnTopHint
        )
        super().__init__(parent, flags)
        self.setObjectName("interactionItemToolbox")
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setStyleSheet(
            "QFrame#interactionItemToolbox { background: transparent; }"
            "QFrame#interactionItemPanel { background: #FFFDF9; border: 1px solid #E8DED5; "
            "border-radius: 10px; }"
            "QToolButton { background: #FFFDF9; border: 1px solid #E8DED5; border-radius: 10px; }"
            "QToolButton:hover, QToolButton:checked { background: #FFF2EC; border-color: #D98663; }"
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        self.launcher = QToolButton(self)
        self.launcher.setIcon(lucide_icon("package-open", color="#D98663", size=22))
        self.launcher.setIconSize(QSize(22, 22))
        self.launcher.setFixedSize(44, 44)
        self.launcher.setCheckable(True)
        self.launcher.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.launcher.setToolTip("互动道具")
        self.launcher.setAccessibleName("互动道具")
        self.launcher.clicked.connect(self._toggle_panel)
        layout.addWidget(self.launcher, 0, Qt.AlignmentFlag.AlignTop)

        self.panel = QFrame(self)
        self.panel.setObjectName("interactionItemPanel")
        self._item_layout = QGridLayout(self.panel)
        self._item_layout.setContentsMargins(6, 6, 6, 6)
        self._item_layout.setHorizontalSpacing(4)
        self._item_layout.setVerticalSpacing(4)
        layout.addWidget(self.panel, 0, Qt.AlignmentFlag.AlignTop)

        self._item_buttons: tuple[InteractionItemButton, ...] = ()
        self._is_expanded = False
        self._pet_rect = QRect()
        self.panel.hide()

    @property
    def item_buttons(self) -> tuple[InteractionItemButton, ...]:
        return self._item_buttons

    @property
    def is_expanded(self) -> bool:
        return self._is_expanded

    def set_items(self, items: Sequence[ResolvedInteractionItem]) -> None:
        was_expanded = self._is_expanded
        for button in self._item_buttons:
            self._item_layout.removeWidget(button)
            button.setParent(None)
            button.deleteLater()

        buttons: list[InteractionItemButton] = []
        for index, item in enumerate(tuple(items)[:_MAX_ITEMS]):
            button = InteractionItemButton(item, self.panel)
            self._item_layout.addWidget(button, index // _GRID_COLUMNS, index % _GRID_COLUMNS)
            buttons.append(button)
        self._item_buttons = tuple(buttons)

        if not buttons:
            self.hide_all()
            return
        if was_expanded:
            self.open_panel()
        else:
            self.collapse()

    def open_panel(self) -> None:
        if not self._item_buttons:
            return
        self._is_expanded = True
        self.launcher.setChecked(True)
        self.panel.show()
        self._fit_contents()
        if self.isVisible():
            self.reposition(self._pet_rect)

    def collapse(self) -> None:
        self._is_expanded = False
        self.launcher.setChecked(False)
        self.panel.hide()
        self._fit_contents()
        if self.isVisible():
            self.reposition(self._pet_rect)

    def hide_all(self) -> None:
        self.collapse()
        self.hide()

    def show_for(self, pet_rect: QRect) -> None:
        if not self._item_buttons:
            self.hide_all()
            return
        self._pet_rect = QRect(pet_rect)
        self.collapse()
        self.launcher.show()
        self._fit_contents()
        self.show()
        self.reposition(self._pet_rect)
        self.raise_()

    def reposition(self, pet_rect: QRect) -> None:
        self._pet_rect = QRect(pet_rect)
        if not self.isVisible():
            return
        screen = QGuiApplication.screenAt(self._pet_rect.center()) or QGuiApplication.primaryScreen()
        if screen is None:
            return
        self.move(clamp_toolbox_position(self._pet_rect, screen.availableGeometry(), self.size()))

    def enterEvent(self, event: QEnterEvent) -> None:  # noqa: N802 - Qt override
        self.hover_changed.emit(True)
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:  # noqa: N802 - Qt override
        self.hover_changed.emit(False)
        super().leaveEvent(event)

    def _toggle_panel(self, checked: bool) -> None:
        if checked:
            self.open_panel()
        else:
            self.collapse()

    def _fit_contents(self) -> None:
        if self.layout() is not None:
            self.layout().activate()
        self.resize(self.sizeHint())


__all__ = [
    "INTERACTION_ITEM_MIME",
    "InteractionItemButton",
    "InteractionItemToolbox",
    "clamp_toolbox_position",
]
