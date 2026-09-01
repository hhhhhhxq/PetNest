"""独立互动道具盒与标准 Qt 拖放源控件。"""

from __future__ import annotations

import sys
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
    QBoxLayout,
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
    extra_width = panel_width + (_PANEL_GAP if panel_width else 0)
    window_size = QSize(
        _LAUNCHER_CANVAS_SIZE.width() + extra_width,
        max(_LAUNCHER_CANVAS_SIZE.height(), panel_height),
    )
    group_y = pet_rect.top() - 22
    right_group_x = pet_rect.right() + 1 + _TOOLBOX_GAP
    left_group_x = (
        pet_rect.left()
        - _TOOLBOX_GAP
        - _LAUNCHER_SIZE.width()
        - _LAUNCHER_ARC_DELTA.x()
    )
    right_rect = QRect(QPoint(right_group_x, group_y), window_size)
    left_rect = QRect(QPoint(left_group_x - extra_width, group_y), window_size)
    side: Literal["right", "left"] = (
        "right"
        if _overflow_score(right_rect, available) <= _overflow_score(left_rect, available)
        else "left"
    )
    candidate = right_rect if side == "right" else left_rect
    window_position = _clamp_rect_origin(candidate, available)
    canvas_offset = QPoint(0 if side == "right" else extra_width, 0)
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
    notebook_requested = Signal()

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
        self.notebook_launcher.clicked.connect(lambda _checked=False: self.notebook_requested.emit())
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
        for index, item in enumerate(tuple(items)[:_MAX_ITEMS]):
            button = InteractionItemButton(item, self.panel)
            self._item_layout.addWidget(button, index // _GRID_COLUMNS, index % _GRID_COLUMNS)
            buttons.append(button)
        self._item_buttons = tuple(buttons)

        self.launcher.setVisible(bool(buttons))
        if not buttons and not self._notebook_enabled:
            self.hide_all()
            return
        if was_expanded:
            self.open_panel()
        else:
            self.collapse()

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
        screen = QGuiApplication.screenAt(self._pet_rect.center()) or QGuiApplication.primaryScreen()
        if screen is None:
            return
        placement = plan_launcher_arc(
            self._pet_rect,
            screen.availableGeometry(),
            self._planned_panel_size(),
            expanded=self._is_expanded,
        )
        self._apply_arc_side(placement.side)
        self._fit_contents()
        self.move(placement.window_position)

    def enterEvent(self, event: QEnterEvent) -> None:  # noqa: N802 - Qt override
        self.hover_changed.emit(True)
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:  # noqa: N802 - Qt override
        self.hover_changed.emit(False)
        super().leaveEvent(event)

    def _apply_arc_side(self, side: Literal["right", "left"]) -> None:
        self._arc_side = side
        root_layout = self.layout()
        if not isinstance(root_layout, QBoxLayout):
            return
        if side == "right":
            self.launcher.move(0, 0)
            self.notebook_launcher.move(_LAUNCHER_ARC_DELTA)
            root_layout.setDirection(QBoxLayout.Direction.LeftToRight)
        else:
            self.launcher.move(_LAUNCHER_ARC_DELTA.x(), 0)
            self.notebook_launcher.move(0, _LAUNCHER_ARC_DELTA.y())
            root_layout.setDirection(QBoxLayout.Direction.RightToLeft)
        root_layout.activate()

    def _planned_panel_size(self) -> QSize:
        if not self._is_expanded or not self.panel.isVisible():
            return QSize(0, 0)
        return self.panel.sizeHint().expandedTo(self.panel.minimumSizeHint())

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
    "LauncherArcPlacement",
    "plan_launcher_arc",
]
