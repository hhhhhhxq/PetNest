"""独立互动道具盒与标准 Qt 拖放源控件。"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

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
    QCloseEvent,
    QDrag,
    QEnterEvent,
    QGuiApplication,
    QHideEvent,
    QIcon,
    QMouseEvent,
    QPaintEvent,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QBoxLayout,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from petnest.core.interaction_items import ResolvedInteractionItem
from petnest.ui.lucide_icons import lucide_icon


INTERACTION_ITEM_MIME = "application/x-petnest-interaction-item"
_TOOLBOX_GAP = 8
_GRID_COLUMNS = 3
_MAX_VISIBLE_ROWS = 3
_ITEM_CARD_SIZE = QSize(70, 78)
_ITEM_GRID_SPACING = 4
_ITEM_ICON_SIZE = QSize(44, 44)
_ITEM_HOVER_ICON_SIZE = QSize(48, 48)
_ITEM_DRAG_PIXMAP_SIZE = QSize(50, 50)
_ITEM_INTRO_PEAK_SIZE = QSize(50, 50)
_LAUNCHER_SIZE = QSize(44, 44)
_LAUNCHER_CANVAS_SIZE = QSize(87, 79)
_LAUNCHER_ARC_DELTA = QPoint(43, 35)
_PANEL_GAP = 6


@dataclass(frozen=True)
class LauncherArcPlacement:
    """宠物旁 C 形入口组的一次几何规划。"""

    side: Literal["right", "left"]
    window_position: QPoint
    canvas_offset: QPoint
    toolbox_position: QPoint
    notebook_position: QPoint


def _overflow_score(rect: QRect, available: QRect) -> int:
    return (
        max(0, available.left() - rect.left())
        + max(0, rect.right() - available.right())
        + max(0, available.top() - rect.top())
        + max(0, rect.bottom() - available.bottom())
    )


def _clamp_rect_origin(rect: QRect, available: QRect) -> QPoint:
    max_x = max(available.left(), available.right() - rect.width() + 1)
    max_y = max(available.top(), available.bottom() - rect.height() + 1)
    return QPoint(
        min(max(rect.x(), available.left()), max_x),
        min(max(rect.y(), available.top()), max_y),
    )


def _overlap_area(rect: QRect, others: Sequence[QRect]) -> int:
    return sum(
        max(0, intersection.width()) * max(0, intersection.height())
        for other in others
        if not (intersection := rect.intersected(other)).isEmpty()
    )


def place_interaction_panel(
    anchor_rect: QRect,
    pet_rect: QRect,
    panel_size: QSize,
    available: QRect,
    *,
    preferred_side: Literal["right", "left"],
) -> QPoint:
    """在不移动入口锚点的前提下，为独立面板选择屏幕内位置。"""
    width = min(max(1, panel_size.width()), max(1, available.width()))
    height = min(max(1, panel_size.height()), max(1, available.height()))
    if preferred_side == "right":
        outward = QPoint(anchor_rect.right() + 1 + _PANEL_GAP, anchor_rect.top())
        opposite = QPoint(pet_rect.left() - _PANEL_GAP - width, anchor_rect.top())
    else:
        outward = QPoint(anchor_rect.left() - _PANEL_GAP - width, anchor_rect.top())
        opposite = QPoint(pet_rect.right() + 1 + _PANEL_GAP, anchor_rect.top())
    candidates = (
        outward,
        QPoint(
            anchor_rect.center().x() - width // 2,
            max(anchor_rect.bottom(), pet_rect.bottom()) + 1 + _PANEL_GAP,
        ),
        QPoint(
            anchor_rect.center().x() - width // 2,
            min(anchor_rect.top(), pet_rect.top()) - _PANEL_GAP - height,
        ),
        opposite,
    )
    bounded: list[QPoint] = []
    for candidate in candidates:
        point = _clamp_rect_origin(
            QRect(candidate, QSize(width, height)),
            available,
        )
        rect = QRect(point, QSize(width, height))
        bounded.append(point)
        if not rect.intersects(anchor_rect) and not rect.intersects(pet_rect):
            return point
    return min(
        bounded,
        key=lambda point: _overlap_area(
            QRect(point, QSize(width, height)),
            (anchor_rect, pet_rect),
        ),
    )


def plan_launcher_arc(
    pet_rect: QRect,
    available: QRect,
    panel_size: QSize,
    *,
    expanded: bool,
) -> LauncherArcPlacement:
    """规划入口组及可选展开面板在宠物外侧的位置。"""
    panel_width = max(0, panel_size.width()) if expanded else 0
    panel_height = max(0, panel_size.height()) if expanded else 0
    group_y = pet_rect.top() - 22
    right_group_x = pet_rect.right() + 1 + _TOOLBOX_GAP
    left_group_x = (
        pet_rect.left()
        - _TOOLBOX_GAP
        - _LAUNCHER_SIZE.width()
        - _LAUNCHER_ARC_DELTA.x()
    )
    right_canvas = QRect(
        QPoint(right_group_x, group_y),
        _LAUNCHER_CANVAS_SIZE,
    )
    left_canvas = QRect(
        QPoint(left_group_x, group_y),
        _LAUNCHER_CANVAS_SIZE,
    )
    right_rect = right_canvas
    left_rect = left_canvas
    if expanded and panel_width and panel_height:
        right_rect = right_rect.united(
            QRect(
                QPoint(right_canvas.right() + 1 + _PANEL_GAP, group_y),
                QSize(panel_width, panel_height),
            )
        )
        left_rect = left_rect.united(
            QRect(
                QPoint(left_canvas.left() - _PANEL_GAP - panel_width, group_y),
                QSize(panel_width, panel_height),
            )
        )
    side: Literal["right", "left"] = (
        "right"
        if _overflow_score(right_rect, available)
        <= _overflow_score(left_rect, available)
        else "left"
    )
    candidate = right_canvas if side == "right" else left_canvas
    window_position = _clamp_rect_origin(candidate, available)
    canvas_offset = QPoint(0, 0)
    toolbox_position = QPoint(0, 0) if side == "right" else QPoint(43, 0)
    notebook_position = QPoint(43, 35) if side == "right" else QPoint(0, 35)
    return LauncherArcPlacement(
        side,
        window_position,
        canvas_offset,
        toolbox_position,
        notebook_position,
    )


class InteractionItemPanel(QFrame):
    """承载独立磨砂道具卡片的透明面板。"""

    hover_changed = Signal(bool)

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        shelf_asset_path: Path | None = None,
    ) -> None:
        del shelf_asset_path
        flags = (
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.WindowStaysOnTopHint
        )
        super().__init__(parent, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAutoFillBackground(False)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setStyleSheet("background: transparent; border: none;")

    def enterEvent(self, event: QEnterEvent) -> None:  # noqa: N802 - Qt override
        self.hover_changed.emit(True)
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:  # noqa: N802 - Qt override
        self.hover_changed.emit(False)
        super().leaveEvent(event)


class InteractionItemButton(QToolButton):
    """以通用道具 ID 作为 Qt 拖放载荷的道具按钮。"""

    drag_started = Signal(str)
    drag_finished = Signal(str, object)

    def __init__(
        self, item: ResolvedInteractionItem, parent: QWidget | None = None
    ) -> None:
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
        self.setFixedSize(_ITEM_CARD_SIZE)
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
        self._start_drag()

    def _start_drag(self) -> Qt.DropAction:
        pixmap = self._source_icon.pixmap(_ITEM_DRAG_PIXMAP_SIZE)
        drag = QDrag(self)
        drag.setMimeData(self.mime_data())
        if self.item.definition.hold_play is not None:
            # 陪玩道具有自己的热点对齐光标层；隐藏系统拖拽缩略图，避免显示两份道具。
            transparent = QPixmap(1, 1)
            transparent.fill(Qt.GlobalColor.transparent)
            drag.setPixmap(transparent)
            drag.setHotSpot(QPoint())
        elif not pixmap.isNull():
            drag.setPixmap(pixmap)
            drag.setHotSpot(QPoint(pixmap.width() // 2, pixmap.height() // 2))
        identifier = self.item.definition.identifier
        self._set_dragging_visual(True)
        self.drag_started.emit(identifier)
        result = Qt.DropAction.IgnoreAction
        try:
            result = self._execute_drag(drag)
            return result
        finally:
            self.drag_finished.emit(identifier, result)
            self._set_dragging_visual(False)
            self.setCursor(Qt.CursorShape.OpenHandCursor)

    @staticmethod
    def _execute_drag(drag: QDrag) -> Qt.DropAction:
        return drag.exec(Qt.DropAction.MoveAction)

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
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        card = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)
        lifted = bool(self.property("lifted"))
        painter.setPen(QPen(QColor(185, 174, 163, 125), 1))
        card_alpha = 88 if self.isDown() else 72 if lifted else 56
        painter.setBrush(QColor(248, 244, 238, card_alpha))
        painter.drawRoundedRect(card, 9, 9)

        chip_width = min(
            self.width() - 8,
            max(34, self.fontMetrics().horizontalAdvance(self.text()) + 10),
        )
        chip = QRectF(
            (self.width() - chip_width) / 2,
            self.height() - 22,
            chip_width,
            17,
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 252, 247, 190))
        painter.drawRoundedRect(chip, 7, 7)

        icon_size = self.iconSize()
        icon = self.icon().pixmap(icon_size)
        if not icon.isNull():
            device_ratio = max(1.0, icon.devicePixelRatio())
            logical_size = QSize(
                max(1, round(icon.width() / device_ratio)),
                max(1, round(icon.height() / device_ratio)),
            )
            slot_top = 0 if lifted else 4
            icon_rect = QRect(
                (self.width() - logical_size.width()) // 2,
                slot_top + (icon_size.height() - logical_size.height()) // 2,
                logical_size.width(),
                logical_size.height(),
            )
            painter.drawPixmap(icon_rect, icon)
        elif self.property("dragging"):
            slot = QRectF(self.width() / 2 - 18, 7, 36, 38)
            pen = QPen(QColor(190, 125, 92, 85), 1, Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(slot)

        painter.setPen(QColor(87, 66, 57))
        painter.drawText(
            chip,
            Qt.AlignmentFlag.AlignCenter,
            self.text(),
        )
        painter.end()

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
    """跟随宠物显示、以三列磨砂卡片展示道具的独立工具窗。"""

    hover_changed = Signal(bool)
    intro_hint_started = Signal()
    notebook_requested = Signal()
    item_drag_started = Signal(str)
    item_drag_finished = Signal(str, object)

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
            "QToolButton#interactionItemLauncher, QToolButton#quickNotebookLauncher { "
            "background: transparent; border: none; "
            "border-radius: 22px; }"
            "QToolButton#interactionItemLauncher:hover, "
            "QToolButton#interactionItemLauncher:pressed, "
            "QToolButton#interactionItemLauncher:checked, "
            "QToolButton#quickNotebookLauncher:hover, "
            "QToolButton#quickNotebookLauncher:pressed, "
            "QToolButton#quickNotebookLauncher:checked { background: rgba(255, 242, 236, 190); }"
            "QLabel#interactionItemHint { background: transparent; border: none; color: #785F52; "
            "font-size: 11px; font-weight: 600; padding: 0 2px 2px 2px; }"
            'QLabel#interactionItemHint[intro="true"] { color: #C86845; '
            "background: rgba(255, 226, 213, 150); border-radius: 6px; }"
            "QWidget#interactionItemGrid { background: transparent; border: none; }"
            "QScrollArea#interactionItemScroll { background: transparent; border: none; }"
            "QScrollArea#interactionItemScroll QWidget#qt_scrollarea_viewport { "
            "background: transparent; border: none; }"
            "QScrollBar:vertical { background: transparent; width: 7px; margin: 0; }"
            "QScrollBar::handle:vertical { background: rgba(166, 150, 137, 105); "
            "border-radius: 3px; min-height: 24px; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
            "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { "
            "background: transparent; }"
            "QToolButton#interactionItemButton { background: transparent; border: none; "
            "border-radius: 10px; color: #574239; font-size: 11px; "
            "padding: 2px 2px 4px 2px; }"
            'QToolButton#interactionItemButton[lifted="true"] { padding: 0 2px 8px 2px; }'
            "QToolButton#interactionItemButton:hover, "
            "QToolButton#interactionItemButton:pressed { background: transparent; border: none; }"
            'QToolButton#interactionItemButton[dragging="true"] { '
            "background: transparent; color: rgba(108, 85, 74, 150); }"
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(_PANEL_GAP)

        self.launcher_canvas = QWidget(self)
        self.launcher_canvas.setObjectName("interactionLauncherCanvas")
        self.launcher_canvas.setFixedSize(_LAUNCHER_CANVAS_SIZE)

        self.launcher = QToolButton(self.launcher_canvas)
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
        self.launcher.move(0, 0)

        self.notebook_launcher = QToolButton(self.launcher_canvas)
        self.notebook_launcher.setObjectName("quickNotebookLauncher")
        self.notebook_launcher.setIcon(
            lucide_icon(
                "notebook",
                color="#A84F30",
                fill="#F1B292",
                size=25,
            )
        )
        self.notebook_launcher.setIconSize(QSize(25, 25))
        self.notebook_launcher.setFixedSize(44, 44)
        self.notebook_launcher.setCheckable(True)
        self.notebook_launcher.setCursor(Qt.CursorShape.PointingHandCursor)
        self.notebook_launcher.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.notebook_launcher.setToolTip("便签本")
        self.notebook_launcher.setAccessibleName("便签本")
        self.notebook_launcher.clicked.connect(
            lambda _checked=False: self.notebook_requested.emit()
        )
        notebook_shadow = QGraphicsDropShadowEffect(self.notebook_launcher)
        notebook_shadow.setBlurRadius(6)
        notebook_shadow.setOffset(0, 1)
        notebook_shadow.setColor(QColor(0, 0, 0, 80))
        self.notebook_launcher.setGraphicsEffect(notebook_shadow)
        self.notebook_launcher.move(_LAUNCHER_ARC_DELTA)
        self.notebook_launcher.hide()
        layout.addWidget(self.launcher_canvas, 0, Qt.AlignmentFlag.AlignTop)

        self.panel = InteractionItemPanel(self)
        self.panel.setObjectName("interactionItemPanel")
        self.panel.hover_changed.connect(self.hover_changed.emit)
        panel_layout = QVBoxLayout(self.panel)
        panel_layout.setContentsMargins(4, 4, 4, 4)
        panel_layout.setSpacing(3)
        self.hint_label = QLabel("拖给宠物", self.panel)
        self.hint_label.setObjectName("interactionItemHint")
        self.hint_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        panel_layout.addWidget(self.hint_label)

        self._item_grid = QWidget(self.panel)
        self._item_grid.setObjectName("interactionItemGrid")
        self._item_layout = QGridLayout(self._item_grid)
        self._item_layout.setContentsMargins(0, 0, 0, 0)
        self._item_layout.setHorizontalSpacing(_ITEM_GRID_SPACING)
        self._item_layout.setVerticalSpacing(_ITEM_GRID_SPACING)
        self._item_scroll = QScrollArea(self.panel)
        self._item_scroll.setObjectName("interactionItemScroll")
        self._item_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._item_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._item_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self._item_scroll.setWidgetResizable(False)
        self._item_scroll.setWidget(self._item_grid)
        panel_layout.addWidget(self._item_scroll)
        self._natural_item_scroll_size = QSize(0, 0)

        self._item_buttons: tuple[InteractionItemButton, ...] = ()
        self._notebook_enabled = False
        self._is_expanded = False
        self._arc_side: Literal["right", "left"] = "right"
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

    @property
    def notebook_enabled(self) -> bool:
        return self._notebook_enabled

    def set_items(self, items: Sequence[ResolvedInteractionItem]) -> None:
        was_expanded = self._is_expanded
        self._stop_intro_animation()
        for button in self._item_buttons:
            self._item_layout.removeWidget(button)
            button.setParent(None)
            button.deleteLater()

        buttons: list[InteractionItemButton] = []
        for index, item in enumerate(tuple(items)):
            button = InteractionItemButton(item, self.panel)
            button.drag_started.connect(self.item_drag_started.emit)
            button.drag_finished.connect(self.item_drag_finished.emit)
            self._item_layout.addWidget(
                button, index // _GRID_COLUMNS, index % _GRID_COLUMNS
            )
            buttons.append(button)
        self._item_buttons = tuple(buttons)
        self._sync_item_grid_size()

        self.launcher.setVisible(bool(buttons))
        if not buttons and not self._notebook_enabled:
            self.hide_all()
            return
        if was_expanded:
            self.open_panel()
        else:
            self.collapse()

    def _sync_item_grid_size(self) -> None:
        count = len(self._item_buttons)
        if count == 0:
            self._natural_item_scroll_size = QSize(0, 0)
            self._item_grid.setFixedSize(0, 0)
            self._item_scroll.setFixedSize(0, 0)
            return

        columns = min(count, _GRID_COLUMNS)
        rows = (count + _GRID_COLUMNS - 1) // _GRID_COLUMNS
        visible_rows = min(rows, _MAX_VISIBLE_ROWS)
        grid_width = (
            columns * _ITEM_CARD_SIZE.width() + max(0, columns - 1) * _ITEM_GRID_SPACING
        )
        grid_height = (
            rows * _ITEM_CARD_SIZE.height() + max(0, rows - 1) * _ITEM_GRID_SPACING
        )
        visible_height = (
            visible_rows * _ITEM_CARD_SIZE.height()
            + max(0, visible_rows - 1) * _ITEM_GRID_SPACING
        )
        scrollbar_width = (
            self.style().pixelMetric(QStyle.PixelMetric.PM_ScrollBarExtent)
            if rows > _MAX_VISIBLE_ROWS
            else 0
        )
        self._natural_item_scroll_size = QSize(
            grid_width + scrollbar_width,
            visible_height,
        )
        self._item_grid.setFixedSize(grid_width, grid_height)
        self._item_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._item_scroll.setFixedSize(self._natural_item_scroll_size)

    def set_notebook_enabled(self, enabled: bool) -> None:
        self._notebook_enabled = bool(enabled)
        self.notebook_launcher.setVisible(self._notebook_enabled)
        self.launcher.setVisible(bool(self._item_buttons))
        if not self._notebook_enabled:
            self.notebook_launcher.setChecked(False)
        if not self._item_buttons and not self._notebook_enabled:
            self.hide_all()
            return
        self._fit_contents()
        if self.isVisible():
            self.reposition(self._pet_rect)

    def set_notebook_open(self, opened: bool) -> None:
        self.notebook_launcher.setChecked(self._notebook_enabled and opened)

    def open_panel(self) -> None:
        if not self._item_buttons:
            return
        self._is_expanded = True
        self.launcher.setChecked(True)
        self._fit_contents()
        if self.isVisible():
            self.panel.show()
            self.reposition(self._pet_rect)
            self.panel.raise_()
            self.raise_()
        else:
            self.panel.hide()
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
        if not self._item_buttons and not self._notebook_enabled:
            self.hide_all()
            return
        self._pet_rect = QRect(pet_rect)
        self.collapse()
        self.launcher.setVisible(bool(self._item_buttons))
        self.notebook_launcher.setVisible(self._notebook_enabled)
        self._fit_contents()
        self.show()
        self.reposition(self._pet_rect)
        self.raise_()

    def reposition(self, pet_rect: QRect) -> None:
        self._pet_rect = QRect(pet_rect)
        if not self.isVisible():
            return
        screen = (
            QGuiApplication.screenAt(self._pet_rect.center())
            or QGuiApplication.primaryScreen()
        )
        if screen is None:
            return
        available = screen.availableGeometry()
        self._fit_contents(available.size())
        placement = plan_launcher_arc(
            self._pet_rect,
            available,
            self.panel.size() if self._item_buttons else QSize(0, 0),
            expanded=bool(self._item_buttons),
        )
        self._apply_arc_side(placement.side)
        self.move(placement.window_position)
        if self._is_expanded and self.panel.isVisible():
            anchor_rect = QRect(
                self.launcher_canvas.mapToGlobal(QPoint()),
                self.launcher_canvas.size(),
            )
            self.panel.move(
                place_interaction_panel(
                    anchor_rect,
                    self._pet_rect,
                    self.panel.size(),
                    available,
                    preferred_side=placement.side,
                )
            )

    def enterEvent(self, event: QEnterEvent) -> None:  # noqa: N802 - Qt override
        self.hover_changed.emit(True)
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:  # noqa: N802 - Qt override
        self.hover_changed.emit(False)
        super().leaveEvent(event)

    def hideEvent(self, event: QHideEvent) -> None:  # noqa: N802 - Qt override
        self._stop_intro_animation()
        self._is_expanded = False
        self.launcher.setChecked(False)
        self.panel.hide()
        super().hideEvent(event)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt override
        self.panel.close()
        super().closeEvent(event)

    def _apply_arc_side(self, side: Literal["right", "left"]) -> None:
        self._arc_side = side
        root_layout = self.layout()
        if not isinstance(root_layout, QBoxLayout):
            return
        both_launchers = bool(self._item_buttons) and self._notebook_enabled
        notebook_position = _LAUNCHER_ARC_DELTA if both_launchers else QPoint(0, 0)
        if side == "right":
            self.launcher.move(0, 0)
            self.notebook_launcher.move(notebook_position)
            root_layout.setDirection(QBoxLayout.Direction.LeftToRight)
        else:
            self.launcher.move(_LAUNCHER_ARC_DELTA.x(), 0)
            self.notebook_launcher.move(
                QPoint(0, _LAUNCHER_ARC_DELTA.y())
                if both_launchers
                else QPoint(_LAUNCHER_ARC_DELTA.x(), 0)
            )
            root_layout.setDirection(QBoxLayout.Direction.RightToLeft)
        root_layout.activate()

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

    def _fit_contents(self, available_size: QSize | None = None) -> None:
        scroll_size = QSize(self._natural_item_scroll_size)
        self._item_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        if available_size is not None and not scroll_size.isEmpty():
            panel_layout = self.panel.layout()
            if panel_layout is not None:
                margins = panel_layout.contentsMargins()
                panel_chrome_height = (
                    margins.top()
                    + margins.bottom()
                    + panel_layout.spacing()
                    + self.hint_label.sizeHint().height()
                )
                max_scroll_size = QSize(
                    max(
                        1,
                        available_size.width() - margins.left() - margins.right(),
                    ),
                    max(1, available_size.height() - panel_chrome_height),
                )
                scroll_size = scroll_size.boundedTo(max_scroll_size)
                if scroll_size.width() < self._natural_item_scroll_size.width():
                    self._item_scroll.setHorizontalScrollBarPolicy(
                        Qt.ScrollBarPolicy.ScrollBarAsNeeded
                    )
        self._item_scroll.setFixedSize(scroll_size)
        self.panel.resize(
            self.panel.sizeHint().expandedTo(self.panel.minimumSizeHint())
            if available_size is None
            else self.panel.sizeHint().boundedTo(available_size)
        )
        if self.layout() is not None:
            self.layout().activate()
        self.resize(self.sizeHint())


__all__ = [
    "INTERACTION_ITEM_MIME",
    "InteractionItemButton",
    "InteractionItemPanel",
    "InteractionItemToolbox",
    "LauncherArcPlacement",
    "place_interaction_panel",
    "plan_launcher_arc",
]
