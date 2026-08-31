"""独立互动道具盒与标准 Qt 拖放源控件。"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

from PySide6.QtCore import (
    QEvent,
    QEasingCurve,
    QMimeData,
    QPoint,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSequentialAnimationGroup,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QDrag,
    QEnterEvent,
    QGuiApplication,
    QIcon,
    QMouseEvent,
    QPaintEvent,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from petnest.core.interaction_items import ResolvedInteractionItem
from petnest.ui.lucide_icons import lucide_icon


INTERACTION_ITEM_MIME = "application/x-petnest-interaction-item"
_TOOLBOX_GAP = 8
_MAX_ITEMS = 8
_GRID_COLUMNS = 4
_ITEM_ICON_SIZE = QSize(44, 44)
_ITEM_HOVER_ICON_SIZE = QSize(48, 48)
_ITEM_DRAG_PIXMAP_SIZE = QSize(50, 50)
_ITEM_INTRO_PEAK_SIZE = QSize(50, 50)


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


class InteractionItemPanel(QFrame):
    """使用生成图片端盖保护绘制的自然木置物架。"""

    _SOURCE_CAP_WIDTH = 150
    _LABEL_BAND_HEIGHT = 18

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        shelf_asset_path: Path | None = None,
    ) -> None:
        super().__init__(parent)
        if shelf_asset_path is None:
            root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[3]))
            shelf_asset_path = root / "assets" / "interaction_items" / "wood_shelf.png"
        self.shelf_asset_path = shelf_asset_path
        self.shelf_pixmap = QPixmap(str(shelf_asset_path))

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt override
        del event
        source = self.shelf_pixmap
        target = self.shelf_target_rect()
        if source.isNull() or target.width() <= 0 or target.height() <= 0:
            return

        source_cap = min(self._SOURCE_CAP_WIDTH, source.width() // 2)
        natural_target_cap = round(source_cap * target.height() / source.height())
        target_cap = min(target.width() // 2, max(1, natural_target_cap))
        source_middle_width = source.width() - source_cap * 2
        target_middle_width = target.width() - target_cap * 2

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawPixmap(
            QRect(target.left(), target.top(), target_cap, target.height()),
            source,
            QRect(0, 0, source_cap, source.height()),
        )
        if target_middle_width > 0 and source_middle_width > 0:
            painter.drawPixmap(
                QRect(
                    target.left() + target_cap,
                    target.top(),
                    target_middle_width,
                    target.height(),
                ),
                source,
                QRect(source_cap, 0, source_middle_width, source.height()),
            )
        painter.drawPixmap(
            QRect(
                target.right() - target_cap + 1,
                target.top(),
                target_cap,
                target.height(),
            ),
            source,
            QRect(source.width() - source_cap, 0, source_cap, source.height()),
        )
        painter.end()

    def shelf_target_rect(self) -> QRect:
        shelf_height = max(1, self.height() - self._LABEL_BAND_HEIGHT)
        rise = max(1, round(shelf_height * 0.10))
        return QRect(0, -rise, self.width(), shelf_height)


class InteractionItemButton(QToolButton):
    """以通用道具 ID 作为 Qt 拖放载荷的道具按钮。"""

    def __init__(self, item: ResolvedInteractionItem, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.item = item
        self._drag_start: QPoint | None = None
        self._source_icon = QIcon(str(item.definition.icon))
        self._shadow = QGraphicsDropShadowEffect(self)
        self._shadow.setBlurRadius(9)
        self._shadow.setOffset(0, 2)
        self._shadow.setColor(QColor(78, 54, 42, 100))
        self._shadow.setEnabled(False)
        self.setGraphicsEffect(self._shadow)
        self.setObjectName("interactionItemButton")
        self.setProperty("lifted", False)
        self.setProperty("dragging", False)
        self.setText(
            self.fontMetrics().elidedText(
                item.definition.label,
                Qt.TextElideMode.ElideRight,
                60,
            )
        )
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        self.setToolTip(f"拖动 {item.definition.label} 到宠物身上")
        self.setAccessibleName(item.definition.label)
        self.setAccessibleDescription(f"拖动 {item.definition.label} 到宠物身上")
        self.setIcon(self._source_icon)
        self.setIconSize(_ITEM_ICON_SIZE)
        self.setFixedSize(68, 88)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
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
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
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
        pixmap = self._source_icon.pixmap(_ITEM_DRAG_PIXMAP_SIZE)
        drag = QDrag(self)
        drag.setMimeData(self.mime_data())
        if not pixmap.isNull():
            drag.setPixmap(pixmap)
            drag.setHotSpot(QPoint(pixmap.width() // 2, pixmap.height() // 2))
        self._set_dragging_visual(True)
        try:
            drag.exec(Qt.DropAction.MoveAction)
        finally:
            self._set_dragging_visual(False)
            self.setCursor(Qt.CursorShape.OpenHandCursor)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override
        self._drag_start = None
        super().mouseReleaseEvent(event)
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def enterEvent(self, event: QEnterEvent) -> None:  # noqa: N802 - Qt override
        self._set_lifted(True)
        self.setIconSize(_ITEM_HOVER_ICON_SIZE)
        self._shadow.setEnabled(True)
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:  # noqa: N802 - Qt override
        if not self.property("dragging"):
            self._set_lifted(False)
            self.setIconSize(_ITEM_ICON_SIZE)
            self._shadow.setEnabled(False)
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        super().leaveEvent(event)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt override
        if self.property("dragging"):
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            slot = QRectF(self.width() / 2 - 18, 7, 36, 38)
            pen = QPen(QColor(190, 125, 92, 85), 1, Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(slot)
            painter.end()
        super().paintEvent(event)

    def _set_lifted(self, lifted: bool) -> None:
        self.setProperty("lifted", lifted)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def _set_dragging_visual(self, dragging: bool) -> None:
        self.setProperty("dragging", dragging)
        self.setIcon(QIcon() if dragging else self._source_icon)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()


class InteractionItemToolbox(QFrame):
    """跟随宠物显示、可展开至两行道具网格的独立工具窗。"""

    hover_changed = Signal(bool)
    intro_hint_started = Signal()

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
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setStyleSheet(
            "QFrame#interactionItemToolbox { background: transparent; }"
            "QFrame#interactionItemPanel { background: transparent; border: none; }"
            "QToolButton#interactionItemLauncher { background: transparent; border: none; "
            "border-radius: 22px; }"
            "QToolButton#interactionItemLauncher:hover, "
            "QToolButton#interactionItemLauncher:pressed, "
            "QToolButton#interactionItemLauncher:checked { background: rgba(255, 242, 236, 190); }"
            "QLabel#interactionItemHint { background: transparent; border: none; color: #785F52; "
            "font-size: 11px; font-weight: 600; padding: 0 2px 2px 2px; }"
            "QLabel#interactionItemHint[intro=\"true\"] { color: #C86845; "
            "background: rgba(255, 226, 213, 150); border-radius: 6px; }"
            "QWidget#interactionItemGrid { background: transparent; border: none; }"
            "QToolButton#interactionItemButton { background: transparent; border: none; "
            "border-radius: 10px; color: #574239; font-size: 11px; "
            "padding: 2px 2px 4px 2px; }"
            "QToolButton#interactionItemButton[lifted=\"true\"] { padding: 0 2px 8px 2px; }"
            "QToolButton#interactionItemButton:hover, "
            "QToolButton#interactionItemButton:pressed { background: transparent; border: none; }"
            "QToolButton#interactionItemButton[dragging=\"true\"] { "
            "background: transparent; color: rgba(108, 85, 74, 150); }"
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        self.launcher = QToolButton(self)
        self.launcher.setObjectName("interactionItemLauncher")
        self.launcher.setIcon(
            lucide_icon(
                "package-open",
                color="#A84F30",
                fill="#E89A78",
                size=25,
            )
        )
        self.launcher.setIconSize(QSize(25, 25))
        self.launcher.setFixedSize(44, 44)
        self.launcher.setCheckable(True)
        self.launcher.setCursor(Qt.CursorShape.PointingHandCursor)
        self.launcher.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.launcher.setToolTip("互动道具")
        self.launcher.setAccessibleName("互动道具")
        launcher_shadow = QGraphicsDropShadowEffect(self.launcher)
        launcher_shadow.setBlurRadius(6)
        launcher_shadow.setOffset(0, 1)
        launcher_shadow.setColor(QColor(0, 0, 0, 80))
        self.launcher.setGraphicsEffect(launcher_shadow)
        self.launcher.clicked.connect(self._toggle_panel)
        layout.addWidget(self.launcher, 0, Qt.AlignmentFlag.AlignTop)

        self.panel = InteractionItemPanel(self)
        self.panel.setObjectName("interactionItemPanel")
        panel_layout = QVBoxLayout(self.panel)
        panel_layout.setContentsMargins(9, 8, 9, 19)
        panel_layout.setSpacing(3)
        self.hint_label = QLabel("拖给宠物", self.panel)
        self.hint_label.setObjectName("interactionItemHint")
        self.hint_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        panel_layout.addWidget(self.hint_label)

        self._item_grid = QWidget(self.panel)
        self._item_grid.setObjectName("interactionItemGrid")
        self._item_layout = QGridLayout(self._item_grid)
        self._item_layout.setContentsMargins(0, 0, 0, 0)
        self._item_layout.setHorizontalSpacing(4)
        self._item_layout.setVerticalSpacing(4)
        panel_layout.addWidget(self._item_grid)
        layout.addWidget(self.panel, 0, Qt.AlignmentFlag.AlignTop)

        self._item_buttons: tuple[InteractionItemButton, ...] = ()
        self._is_expanded = False
        self._pet_rect = QRect()
        self._intro_has_played = False
        self._intro_animation: QSequentialAnimationGroup | None = None
        self.panel.hide()

    @property
    def item_buttons(self) -> tuple[InteractionItemButton, ...]:
        return self._item_buttons

    @property
    def is_expanded(self) -> bool:
        return self._is_expanded

    @property
    def intro_has_played(self) -> bool:
        return self._intro_has_played

    def set_items(self, items: Sequence[ResolvedInteractionItem]) -> None:
        was_expanded = self._is_expanded
        self._stop_intro_animation()
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
        self._play_intro_hint_once()

    def collapse(self) -> None:
        self._stop_intro_animation()
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

    def _play_intro_hint_once(self) -> None:
        if self._intro_has_played or not self._item_buttons:
            return

        self._intro_has_played = True
        self.intro_hint_started.emit()
        self.hint_label.setProperty("intro", True)
        self._refresh_style(self.hint_label)

        button = self._item_buttons[0]
        animation = QSequentialAnimationGroup(self)
        grow = QPropertyAnimation(button, b"iconSize", animation)
        grow.setDuration(320)
        grow.setStartValue(_ITEM_ICON_SIZE)
        grow.setEndValue(_ITEM_INTRO_PEAK_SIZE)
        grow.setEasingCurve(QEasingCurve.Type.OutCubic)
        shrink = QPropertyAnimation(button, b"iconSize", animation)
        shrink.setDuration(340)
        shrink.setStartValue(_ITEM_INTRO_PEAK_SIZE)
        shrink.setEndValue(_ITEM_ICON_SIZE)
        shrink.setEasingCurve(QEasingCurve.Type.InOutCubic)
        animation.addAnimation(grow)
        animation.addAnimation(shrink)
        animation.finished.connect(self._finish_intro_hint)
        self._intro_animation = animation
        animation.start()

    def _stop_intro_animation(self) -> None:
        animation = self._intro_animation
        if animation is None:
            return
        self._intro_animation = None
        animation.stop()
        animation.deleteLater()
        self._finish_intro_visual()

    def _finish_intro_hint(self) -> None:
        animation = self._intro_animation
        self._intro_animation = None
        if animation is not None:
            animation.deleteLater()
        self._finish_intro_visual()

    def _finish_intro_visual(self) -> None:
        self.hint_label.setProperty("intro", False)
        self._refresh_style(self.hint_label)
        if self._item_buttons:
            first_button = self._item_buttons[0]
            first_button.setIconSize(
                _ITEM_HOVER_ICON_SIZE if first_button.underMouse() else _ITEM_ICON_SIZE
            )

    @staticmethod
    def _refresh_style(widget: QWidget) -> None:
        widget.style().unpolish(widget)
        widget.style().polish(widget)
        widget.update()

    def _fit_contents(self) -> None:
        if self.layout() is not None:
            self.layout().activate()
        self.resize(self.sizeHint())


__all__ = [
    "INTERACTION_ITEM_MIME",
    "InteractionItemButton",
    "InteractionItemPanel",
    "InteractionItemToolbox",
    "clamp_toolbox_position",
]
