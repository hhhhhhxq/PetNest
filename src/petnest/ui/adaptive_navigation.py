"""Font- and style-aware list navigation shared by PetNest dialogs."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QModelIndex, QMargins, QSize, QTimer, Qt, Signal
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QListWidget,
    QStyleOptionViewItem,
    QStyledItemDelegate,
    QWidget,
)


class _AdaptiveNavigationDelegate(QStyledItemDelegate):
    def __init__(
        self,
        *,
        minimum_row_height: int,
        vertical_padding: int,
        horizontal_padding: int,
        item_margin: int,
        icon_text_spacing: int,
        parent: QWidget,
    ) -> None:
        super().__init__(parent)
        self._minimum_row_height = max(1, int(minimum_row_height))
        self._vertical_padding = max(0, int(vertical_padding))
        self._horizontal_padding = max(0, int(horizontal_padding))
        self._item_margin = max(0, int(item_margin))
        self._icon_text_spacing = max(0, int(icon_text_spacing))

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:  # noqa: N802
        base = super().sizeHint(option, index)
        text = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        decoration = index.data(Qt.ItemDataRole.DecorationRole)
        icon_width = max(0, option.decorationSize.width()) if decoration is not None else 0
        icon_height = max(0, option.decorationSize.height()) if decoration is not None else 0
        content_height = max(option.fontMetrics.height(), icon_height)
        required_height = content_height + 2 * (
            self._vertical_padding + self._item_margin
        )
        required_width = option.fontMetrics.horizontalAdvance(text) + 2 * (
            self._horizontal_padding + self._item_margin
        )
        if decoration is not None:
            required_width += icon_width + self._icon_text_spacing
        return QSize(
            max(base.width(), required_width),
            max(base.height(), self._minimum_row_height, required_height),
        )


class AdaptiveNavigationList(QListWidget):
    """A QListWidget whose rows remain readable across fonts, styles and DPI."""

    metrics_changed = Signal(int, int)
    _METRIC_CHANGE_EVENTS = frozenset(
        {
            QEvent.Type.FontChange,
            QEvent.Type.ApplicationFontChange,
            QEvent.Type.StyleChange,
            QEvent.Type.LayoutDirectionChange,
            QEvent.Type.ScreenChangeInternal,
            QEvent.Type.DevicePixelRatioChange,
        }
    )

    def __init__(
        self,
        *,
        minimum_row_height: int,
        vertical_padding: int,
        horizontal_padding: int,
        item_margin: int,
        outer_padding: QMargins,
        icon_text_spacing: int = 6,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._outer_padding = QMargins(
            outer_padding.left(),
            outer_padding.top(),
            outer_padding.right(),
            outer_padding.bottom(),
        )
        self._last_metrics = (-1, -1)
        self._reflow_timer = QTimer(self)
        self._reflow_timer.setSingleShot(True)
        self._reflow_timer.setInterval(0)
        self._reflow_timer.timeout.connect(self.reflow)
        self.setItemDelegate(
            _AdaptiveNavigationDelegate(
                minimum_row_height=minimum_row_height,
                vertical_padding=vertical_padding,
                horizontal_padding=horizontal_padding,
                item_margin=item_margin,
                icon_text_spacing=icon_text_spacing,
                parent=self,
            )
        )
        self.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        model = self.model()
        model.rowsInserted.connect(self.schedule_reflow)
        model.rowsRemoved.connect(self.schedule_reflow)
        model.modelReset.connect(self.schedule_reflow)
        model.dataChanged.connect(self.schedule_reflow)
        self.schedule_reflow()

    def schedule_reflow(self, *_args: object) -> None:
        if not self._reflow_timer.isActive():
            self._reflow_timer.start()

    def reflow(self) -> None:
        self.ensurePolished()
        self.doItemsLayout()
        metrics = (self.full_content_height(), self.recommended_content_width())
        self.updateGeometry()
        self.viewport().update()
        if metrics != self._last_metrics:
            self._last_metrics = metrics
            self.metrics_changed.emit(*metrics)

    def full_content_height(self) -> int:
        row_height = sum(max(1, self.sizeHintForRow(row)) for row in range(self.count()))
        return (
            row_height
            + self.frameWidth() * 2
            + self._outer_padding.top()
            + self._outer_padding.bottom()
        )

    def recommended_content_width(self) -> int:
        column_width = max(0, self.sizeHintForColumn(0)) if self.count() else 0
        return (
            column_width
            + self.frameWidth() * 2
            + self._outer_padding.left()
            + self._outer_padding.right()
        )

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802
        super().changeEvent(event)
        if event.type() in self._METRIC_CHANGE_EVENTS and hasattr(self, "_reflow_timer"):
            self.schedule_reflow()

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802
        super().showEvent(event)
        self.schedule_reflow()


def bounded_navigation_sidebar_width(
    *,
    base_width: int,
    available_width: int,
    navigation_width: int,
    surrounding_width: int,
) -> int:
    """Grow a sidebar for navigation while reserving two thirds for content."""

    base = max(1, int(base_width))
    available = max(1, int(available_width))
    desired = max(base, int(navigation_width) + max(0, int(surrounding_width)))
    maximum = max(base, available // 3)
    return min(desired, maximum)


__all__ = ["AdaptiveNavigationList", "bounded_navigation_sidebar_width"]
