"""宠物旁轻量便签本窗口。"""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from PySide6.QtCore import QDateTime, QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFocusEvent, QGuiApplication, QInputMethodEvent, QPaintEvent, QPainter, QPainterPath, QPalette, QPen, QRegion, QTextFormat
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateTimeEdit,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QLayout,
    QListWidget,
    QListWidgetItem,
    QListView,
    QPlainTextEdit,
    QProgressBar,
    QProxyStyle,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QStyle,
    QStyledItemDelegate,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from petnest.core.quick_notebook_store import (
    NotebookPage,
    PageType,
    QuickNotebookStore,
    ReminderItem,
    TodoItem,
)
from petnest.ui.lucide_icons import lucide_icon


BOOK_WIDTH = 390
RAIL_WIDTH = 89
NATURAL_HEIGHT = 448
SHADOW_BOTTOM_MARGIN = 10
PLACEMENT_GAP = 9
TAB_HEIGHT = 43
TAB_GAP = 8
TAB_TOP = 28


class _InputMethodPlaceholderMixin:
    """组词还没写入 text/document 时，也隐藏占位文字，避免与预编辑文字重叠。"""

    def setPlaceholderText(self, text: str) -> None:  # noqa: N802 - Qt override
        self._placeholder_text = text
        self._sync_placeholder()

    def _sync_placeholder(self) -> None:
        composing = getattr(self, "_ime_composing", False)
        super().setPlaceholderText("" if composing else getattr(self, "_placeholder_text", ""))

    def inputMethodEvent(self, event: QInputMethodEvent) -> None:  # noqa: N802 - Qt override
        self._ime_composing = bool(event.preeditString())
        self._sync_placeholder()
        super().inputMethodEvent(event)

    def focusOutEvent(self, event: QFocusEvent) -> None:  # noqa: N802 - Qt override
        super().focusOutEvent(event)
        self._ime_composing = False
        self._sync_placeholder()


class _NotebookLineEdit(_InputMethodPlaceholderMixin, QLineEdit):
    pass


class _NotebookTextEdit(_InputMethodPlaceholderMixin, QPlainTextEdit):
    pass


class _NotebookPopupStyle(QProxyStyle):
    def __init__(self) -> None:
        super().__init__("Fusion")

    def styleHint(self, hint, option=None, widget=None, return_data=None):  # noqa: N802 - Qt override
        if hint == QStyle.StyleHint.SH_ComboBox_Popup:
            return 0
        return super().styleHint(hint, option, widget, return_data)


class _NotebookComboBox(QComboBox):
    """独立浅色弹出列表，不混用 macOS 深色原生菜单和纸面文字颜色。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._popup_style = _NotebookPopupStyle()
        self._popup_style.setParent(self)
        self.setStyle(self._popup_style)
        view = QListView(self)
        view.setObjectName("quickNotebookComboPopup")
        view.setStyle(self._popup_style)
        view.setItemDelegate(QStyledItemDelegate(view))
        view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setView(view)
        palette = QPalette(self.palette())
        for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive, QPalette.ColorGroup.Disabled):
            for role, color in (
                (QPalette.ColorRole.Window, "#FFFDFA"),
                (QPalette.ColorRole.Base, "#FFFDFA"),
                (QPalette.ColorRole.Button, "#FFFDFA"),
                (QPalette.ColorRole.Text, "#4B4641"),
                (QPalette.ColorRole.WindowText, "#4B4641"),
                (QPalette.ColorRole.ButtonText, "#4B4641"),
                (QPalette.ColorRole.Highlight, "#F2D8C8"),
                (QPalette.ColorRole.HighlightedText, "#4B3226"),
            ):
                palette.setColor(group, role, QColor(color))
        self.setPalette(palette)
        view.setPalette(palette)
        view.viewport().setPalette(palette)
        view.setStyleSheet("""
            QListView#quickNotebookComboPopup {
                background: #FFFDFA; color: #4B4641;
                selection-background-color: #F2D8C8;
                selection-color: #4B3226;
                border: 1px solid #CDB9A8; padding: 4px;
                font-size: 13px; outline: none;
            }
            QListView#quickNotebookComboPopup::item {
                min-height: 28px; padding: 2px 8px;
                background: #FFFDFA; color: #4B4641;
            }
            QListView#quickNotebookComboPopup::item:hover,
            QListView#quickNotebookComboPopup::item:selected {
                background: #F2D8C8; color: #4B3226;
            }
            QListView#quickNotebookComboPopup::item:disabled { color: #81736A; }
        """)
        self.setMaxVisibleItems(8)

    def showPopup(self) -> None:  # noqa: N802 - Qt override
        popup = self.view().window()
        popup.setObjectName("quickNotebookComboPopupFrame")
        popup.setPalette(self.view().palette())
        popup.setStyleSheet("QFrame#quickNotebookComboPopupFrame { background: #FFFDFA; border: 1px solid #CDB9A8; }")
        super().showPopup()


def place_notebook(
    pet_rect: QRect,
    size: QSize,
    available: QRect,
    *,
    avoid_rects: Sequence[QRect] = (),
    gap: int = PLACEMENT_GAP,
) -> QPoint:
    """按右、左、下、上顺序放置，并在极小屏幕上选择重叠最少的位置。"""
    width = min(max(1, size.width()), max(1, available.width()))
    height = min(max(1, size.height()), max(1, available.height()))
    candidates = (
        QPoint(pet_rect.right() + 1 + gap, pet_rect.center().y() - height // 2),
        QPoint(pet_rect.left() - gap - width, pet_rect.center().y() - height // 2),
        QPoint(pet_rect.center().x() - width // 2, pet_rect.bottom() + 1 + gap),
        QPoint(pet_rect.center().x() - width // 2, pet_rect.top() - gap - height),
    )
    bounded: list[QPoint] = []
    for candidate in candidates:
        point = _bounded_point(candidate, QSize(width, height), available)
        rect = QRect(point, QSize(width, height))
        bounded.append(point)
        if not rect.intersects(pet_rect) and not any(rect.intersects(item) for item in avoid_rects):
            return point
    return min(
        bounded,
        key=lambda point: _overlap_area(QRect(point, QSize(width, height)), (pet_rect, *avoid_rects)),
    )


def _bounded_point(point: QPoint, size: QSize, available: QRect) -> QPoint:
    max_x = max(available.left(), available.right() - size.width() + 1)
    max_y = max(available.top(), available.bottom() - size.height() + 1)
    return QPoint(
        min(max(point.x(), available.left()), max_x),
        min(max(point.y(), available.top()), max_y),
    )


def _overlap_area(rect: QRect, others: Sequence[QRect]) -> int:
    area = 0
    for other in others:
        intersection = rect.intersected(other)
        area += max(0, intersection.width()) * max(0, intersection.height())
    return area


class NotebookTypeTab(QToolButton):
    """向纸页外侧伸展的仿真彩色页签。"""

    def __init__(
        self,
        page_type: PageType,
        icon_name: str,
        label: str,
        color: str,
        parent: QWidget,
    ) -> None:
        super().__init__(parent)
        self.setProperty("pageType", page_type)
        self.setProperty("iconKind", page_type)
        self.setProperty("iconName", icon_name)
        self.setProperty("textColor", "#FFFFFF")
        self._icon = lucide_icon(icon_name, color="#FFFFFF", size=20)
        self._label = label
        self._color = QColor(color)
        self._active = False
        self.setFixedSize(88, TAB_HEIGHT)
        self.setText(label)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAccessibleName({"note": "普通便签", "todo": "待办清单", "reminder": "提醒事项"}[page_type])
        self.setToolTip({"note": "便签：随手记录文字", "todo": "待办：逐项勾选完成", "reminder": "提醒：到时间通知你"}[page_type])

    def set_active(self, active: bool) -> None:
        self._active = bool(active)
        self.setChecked(self._active)
        self.update()

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.moveTo(7, 0)
        path.lineTo(self.width(), 0)
        path.lineTo(self.width(), self.height())
        path.lineTo(7, self.height())
        path.lineTo(0, self.height() * 0.74)
        path.lineTo(0, self.height() * 0.26)
        path.closeSubpath()
        painter.fillPath(path, self._color if self._active else self._color.darker(115))
        painter.drawPixmap(9, 11, self._icon.pixmap(QSize(20, 20)))
        font = painter.font()
        font.setBold(True)
        font.setPixelSize(12)
        painter.setFont(font)
        painter.setPen(QColor("#FFFFFF"))
        painter.drawText(self.rect().adjusted(35, 0, -5, 0), Qt.AlignmentFlag.AlignVCenter, self._label)
        if self._active:
            painter.fillRect(self.width() - 4, 9, 3, self.height() - 18, QColor("#FFFFFF"))


def _remove_item_button(parent: QWidget, label: str) -> QToolButton:
    button = QToolButton(parent)
    button.setObjectName("quickNotebookRemoveItem")
    button.setIcon(lucide_icon("trash-2", color="#94867D", size=14))
    button.setFixedSize(26, 28)
    button.setToolTip(label)
    button.setAccessibleName(label)
    return button


class _RemovalHistory(QWidget):
    """当前页内可连续撤销的单条删除，不与整页回收站混用。"""

    restore_requested = Signal(int, object)

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._entries: list[tuple[int, TodoItem | ReminderItem]] = []
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.label = QLabel("已删除一条", self)
        self.label.setObjectName("quickNotebookHelper")
        self.undo_button = QPushButton("撤销", self)
        self.undo_button.setObjectName("quickNotebookUndo")
        self.undo_button.setToolTip("撤销本页刚才的删除；切换页面后不可撤销")
        layout.addWidget(self.label, 1)
        layout.addWidget(self.undo_button)
        self.undo_button.clicked.connect(self._undo)
        self.hide()

    def record(self, index: int, item: TodoItem | ReminderItem) -> None:
        self._entries.append((index, item))
        self.show()

    def reset(self) -> None:
        self._entries.clear()
        self.hide()

    def _undo(self) -> None:
        if self._entries:
            index, item = self._entries.pop()
            self.restore_requested.emit(index, item)
        self.setVisible(bool(self._entries))


class TodoCheckBox(QCheckBox):
    """与最终原型一致的圆角勾选框，不依赖平台原生 indicator。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("quickNotebookTodoCheck")
        self.setFixedSize(32, 32)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        target = QRect(7, 7, 18, 18)
        painter.setPen(QPen(QColor("#CDBDB0"), 1))
        painter.setBrush(QColor("#7FA287") if self.isChecked() else QColor("#FFFEFB"))
        painter.drawRoundedRect(target, 6, 6)
        if self.isChecked():
            painter.setPen(QPen(QColor("#FFFFFF"), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            path = QPainterPath()
            path.moveTo(12, 16)
            path.lineTo(15, 19)
            path.lineTo(21, 12)
            painter.drawPath(path)

    def hitButton(self, position: QPoint) -> bool:  # noqa: N802 - Qt override
        return self.rect().contains(position)


class _TodoRow(QFrame):
    changed = Signal()
    remove_requested = Signal()

    def __init__(self, item: TodoItem, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("quickNotebookTodoRow")
        self.setFixedHeight(48)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.item_id = item.id
        self.created_at = item.created_at
        self.completed_at = item.completed_at
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(8)
        self.check = TodoCheckBox(self)
        self.check.setChecked(item.completed)
        self.text = _NotebookLineEdit(item.text, self)
        self.text.setMinimumWidth(0)
        self.text.setPlaceholderText("点击输入待办事项")
        self.text.setAccessibleName("待办内容")
        self.check.setToolTip("标记完成 / 未完成")
        self.check.setAccessibleName("标记待办完成")
        layout.addWidget(self.check)
        layout.addWidget(self.text, 1)
        self.remove_button = _remove_item_button(self, "删除这条待办（可撤销）")
        self.remove_button.clicked.connect(self.remove_requested)
        layout.addWidget(self.remove_button)
        self.check.toggled.connect(self._completion_changed)
        self.text.textChanged.connect(self.changed)
        self._sync_completion_style()

    def value(self) -> TodoItem:
        completed = self.check.isChecked()
        completed_at = self.completed_at
        if completed and completed_at is None:
            completed_at = datetime.now(UTC).isoformat()
        if not completed:
            completed_at = None
        return TodoItem(
            self.item_id,
            self.text.text(),
            completed=completed,
            created_at=self.created_at,
            completed_at=completed_at,
        )

    def _completion_changed(self) -> None:
        self._sync_completion_style()
        self.changed.emit()

    def _sync_completion_style(self) -> None:
        completed = self.check.isChecked()
        self.setProperty("completed", completed)
        font = self.text.font()
        font.setStrikeOut(completed)
        self.text.setFont(font)
        self.style().unpolish(self)
        self.style().polish(self)


class TodoListEditor(QWidget):
    changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rows: list[_TodoRow] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(7)
        progress_row = QHBoxLayout()
        self.progress_label = QLabel("0 / 0 完成", self)
        self.progress_label.setObjectName("quickNotebookProgress")
        self.progress_bar = QProgressBar(self)
        self.progress_bar.setObjectName("quickNotebookProgressBar")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setTextVisible(False)
        self.progress_percent_label = QLabel("0%", self)
        self.progress_percent_label.setObjectName("quickNotebookProgressPercent")
        progress_row.addWidget(self.progress_label)
        progress_row.addWidget(self.progress_bar, 1)
        progress_row.addWidget(self.progress_percent_label)
        layout.addLayout(progress_row)
        self.rows_widget = QWidget(self)
        self.rows_widget.setObjectName("quickNotebookTodoRows")
        self.rows_layout = QVBoxLayout(self.rows_widget)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(7)
        self.rows_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self.rows_layout.addStretch(1)
        self.rows_scroll = QScrollArea(self)
        self.rows_scroll.setObjectName("quickNotebookTodoScroll")
        self.rows_scroll.setWidgetResizable(True)
        self.rows_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.rows_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.rows_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.rows_scroll.setWidget(self.rows_widget)
        self.rows_scroll.viewport().setObjectName("quickNotebookTodoViewport")
        layout.addWidget(self.rows_scroll, 1)
        self.empty_hint = QLabel("还没有待办\n点击下方按钮，写下第一件要做的事", self)
        self.empty_hint.setObjectName("quickNotebookHelper")
        self.empty_hint.setWordWrap(True)
        layout.insertWidget(1, self.empty_hint)
        self.removal_history = _RemovalHistory(self)
        self.removal_history.restore_requested.connect(self._restore_item)
        layout.addWidget(self.removal_history)
        self.add_button = QPushButton("＋ 添加待办事项", self)
        self.add_button.setObjectName("quickNotebookInlineAdd")
        self.add_button.clicked.connect(lambda: self.add_item(""))
        layout.addWidget(self.add_button)

    def set_items(self, items: Sequence[TodoItem]) -> None:
        self._clear_rows()
        self.removal_history.reset()
        for item in items:
            self._append_row(item)
        self._update_rows_extent()
        self._update_progress()

    def add_item(self, text: str) -> None:
        if not text.strip():
            blank = next((row for row in self._rows if not row.text.text().strip()), None)
            if blank is not None:
                self._focus_row(blank)
                return
        self._append_row(
            TodoItem(uuid.uuid4().hex, text, created_at=datetime.now(UTC).isoformat())
        )
        self._update_rows_extent()
        self._update_progress()
        self._focus_row(self._rows[-1])
        self.changed.emit()

    def items(self) -> tuple[TodoItem, ...]:
        return tuple(row.value() for row in self._rows)

    def _append_row(self, item: TodoItem, index: int | None = None) -> None:
        row = _TodoRow(item, self.rows_widget)
        row.changed.connect(self._row_changed)
        row.remove_requested.connect(lambda: self._remove_row(row))
        row.text.returnPressed.connect(lambda: self.add_item(""))
        position = len(self._rows) if index is None else min(index, len(self._rows))
        self.rows_layout.insertWidget(position, row)
        self._rows.insert(position, row)
        row.show()

    def _focus_row(self, row: _TodoRow) -> None:
        row.text.setFocus(Qt.FocusReason.OtherFocusReason)
        self.rows_layout.activate()
        self.rows_scroll.ensureWidgetVisible(row)

    def _remove_row(self, row: _TodoRow) -> None:
        self.removal_history.record(self._rows.index(row), row.value())
        self._rows.remove(row)
        self.rows_layout.removeWidget(row)
        row.hide()
        row.deleteLater()
        self._update_rows_extent()
        self._row_changed()

    def _restore_item(self, index: int, item: TodoItem) -> None:
        self._append_row(item, index)
        self._update_rows_extent()
        self._row_changed()

    def _update_rows_extent(self) -> None:
        self.rows_widget.setMinimumHeight(max(1, len(self._rows) * 55))

    def _row_changed(self) -> None:
        self._update_progress()
        self.changed.emit()

    def _update_progress(self) -> None:
        filled_rows = [row for row in self._rows if row.text.text().strip()]
        completed = sum(row.check.isChecked() for row in filled_rows)
        self.progress_label.setText(f"已完成 {completed} / {len(filled_rows)} 项")
        self.empty_hint.setVisible(not self._rows)
        percentage = round(completed * 100 / len(filled_rows)) if filled_rows else 0
        self.progress_bar.setValue(percentage)
        self.progress_percent_label.setText(f"{percentage}%")

    def _clear_rows(self) -> None:
        for row in self._rows:
            self.rows_layout.removeWidget(row)
            row.deleteLater()
        self._rows.clear()
        self._update_rows_extent()


class ReminderSwitch(QCheckBox):
    """提醒列表使用的紧凑开关。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("quickNotebookReminderSwitch")
        self.setFixedSize(31, 18)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#7FA287") if self.isChecked() else QColor("#D8CEC6"))
        painter.drawRoundedRect(self.rect(), 9, 9)
        painter.setBrush(QColor("#FFFFFF"))
        knob_x = 15 if self.isChecked() else 2
        painter.drawEllipse(knob_x, 2, 14, 14)


class _ReminderRow(QFrame):
    changed = Signal()
    remove_requested = Signal()
    layout_changed = Signal()

    def __init__(self, item: ReminderItem, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("quickNotebookReminderRow")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.item_id = item.id
        self.completed = item.completed
        self.snoozed_until = item.snoozed_until
        self.last_triggered_at = item.last_triggered_at
        self._applying_item = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 9, 10, 9)
        layout.setSpacing(7)

        summary = QHBoxLayout()
        summary.setSpacing(10)
        self.date_box = QToolButton(self)
        self.date_box.setObjectName("quickNotebookDateBox")
        self.date_box.setFixedSize(52, 58)
        self.date_box.setCursor(Qt.CursorShape.PointingHandCursor)
        summary.addWidget(self.date_box)
        text_column = QVBoxLayout()
        text_column.setSpacing(2)
        self.text = _NotebookLineEdit(item.text, self)
        self.text.setObjectName("quickNotebookReminderText")
        self.text.setMinimumWidth(0)
        self.text.setPlaceholderText("点击输入提醒内容")
        self.text.setAccessibleName("提醒内容")
        self.sub_label = QLabel(self)
        self.sub_label.setObjectName("quickNotebookReminderSub")
        self.sub_label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        text_column.addWidget(self.text)
        text_column.addWidget(self.sub_label)
        self.edit_time_button = QToolButton(self)
        self.edit_time_button.setObjectName("quickNotebookEditTime")
        self.edit_time_button.setText("设置时间 ▾")
        self.edit_time_button.setAccessibleName("设置提醒时间和重复规则")
        text_column.addWidget(self.edit_time_button, 0, Qt.AlignmentFlag.AlignLeft)
        summary.addLayout(text_column, 1)
        self.enabled = ReminderSwitch(self)
        self.enabled.setChecked(item.enabled)
        self.enabled.setToolTip("开启 / 暂停提醒")
        self.enabled.setAccessibleName("开启提醒")
        row_actions = QVBoxLayout()
        row_actions.setSpacing(5)
        row_actions.addWidget(self.enabled, 0, Qt.AlignmentFlag.AlignRight)
        self.remove_button = _remove_item_button(self, "删除这条提醒（可撤销）")
        self.remove_button.clicked.connect(self.remove_requested)
        row_actions.addWidget(self.remove_button, 0, Qt.AlignmentFlag.AlignRight)
        summary.addLayout(row_actions)
        layout.addLayout(summary)

        self.edit_panel = QWidget(self)
        edit_layout = QVBoxLayout(self.edit_panel)
        edit_layout.setContentsMargins(0, 0, 0, 0)
        edit_layout.setSpacing(5)
        controls = QVBoxLayout()
        self.due = QDateTimeEdit(self.edit_panel)
        self.due.setObjectName("quickNotebookReminderDateTime")
        self.due.setMinimumWidth(0)
        self.due.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.due.setCalendarPopup(True)
        self.due.setAccessibleName("提醒日期和时间")
        self.due.setDisplayFormat("yyyy-MM-dd HH:mm")
        parsed = QDateTime.fromString(item.due_at or "", Qt.DateFormat.ISODate)
        self.due.setDateTime(parsed if parsed.isValid() else QDateTime.currentDateTime().addSecs(3600))
        self.repeat = _NotebookComboBox(self.edit_panel)
        self.repeat.setObjectName("quickNotebookReminderRepeat")
        self.repeat.setMinimumWidth(0)
        self.repeat.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.repeat.setAccessibleName("重复规则")
        self.repeat.addItem("仅一次", "once")
        self.repeat.addItem("每天", "daily")
        self.repeat.addItem("每周", "weekly")
        self.repeat.setCurrentIndex(max(0, self.repeat.findData(item.repeat)))
        controls.addWidget(self.due, 1)
        controls.addWidget(self.repeat)
        edit_layout.addLayout(controls)
        self.weekday_widget = QWidget(self.edit_panel)
        weekday_layout = QGridLayout(self.weekday_widget)
        weekday_layout.setContentsMargins(0, 0, 0, 0)
        weekday_layout.setSpacing(4)
        self.weekday_checks: list[QCheckBox] = []
        for day, label in enumerate("一二三四五六日"):
            checkbox = QCheckBox(label, self.weekday_widget)
            checkbox.setChecked(day in item.weekdays)
            checkbox.toggled.connect(self._schedule_changed)
            weekday_layout.addWidget(checkbox, day // 4, day % 4)
            self.weekday_checks.append(checkbox)
        edit_layout.addWidget(self.weekday_widget)
        self.weekday_widget.setVisible(item.repeat == "weekly")
        self.edit_panel.hide()
        layout.addWidget(self.edit_panel)
        self.validation_label = QLabel(self)
        self.validation_label.setObjectName("quickNotebookValidation")
        self.validation_label.setWordWrap(True)
        self.validation_label.hide()
        layout.addWidget(self.validation_label)
        self.confirm_time_button = QPushButton("开启", self)
        self.confirm_time_button.setObjectName("quickNotebookUndo")
        self.confirm_time_button.setFixedSize(40, 26)
        self.confirm_time_button.setAccessibleName("确认并开启提醒")
        self.confirm_time_button.setToolTip("确认提醒内容和时间后，点击开启")
        self.confirm_time_button.clicked.connect(lambda: self.enabled.setChecked(True))
        row_actions.insertWidget(0, self.confirm_time_button, 0, Qt.AlignmentFlag.AlignRight)

        self.date_box.setToolTip("设置提醒时间和重复规则")
        self.date_box.clicked.connect(self.toggle_time_editor)
        self.edit_time_button.clicked.connect(self.toggle_time_editor)
        self.enabled.toggled.connect(self._enabled_changed)
        self.text.textChanged.connect(self._content_changed)
        self.due.dateTimeChanged.connect(self._schedule_changed)
        self.repeat.currentIndexChanged.connect(self._repeat_changed)
        self._refresh_summary()

    def toggle_time_editor(self) -> None:
        self.set_time_editor_visible(self.edit_panel.isHidden())

    def set_time_editor_visible(self, visible: bool) -> None:
        self.edit_panel.setVisible(visible)
        self.edit_time_button.setText("收起设置 ▴" if visible else "设置时间 ▾")
        self.layout_changed.emit()

    def value(self) -> ReminderItem:
        due_value = self.due.dateTime().toPython()
        if due_value.tzinfo is None or due_value.utcoffset() is None:
            due_value = due_value.replace(tzinfo=datetime.now().astimezone().tzinfo)
        return ReminderItem(
            self.item_id,
            self.text.text(),
            due_at=due_value.isoformat(),
            repeat=str(self.repeat.currentData()),
            weekdays=tuple(
                index for index, checkbox in enumerate(self.weekday_checks) if checkbox.isChecked()
            ),
            enabled=self.enabled.isChecked(),
            completed=self.completed,
            snoozed_until=self.snoozed_until,
            last_triggered_at=self.last_triggered_at,
        )

    def _content_changed(self) -> None:
        if self._applying_item:
            return
        if not self.text.text().strip() and self.enabled.isChecked():
            self.enabled.setChecked(False)
        self._refresh_summary()
        self.changed.emit()

    def _enabled_changed(self, enabled: bool) -> None:
        if self._applying_item:
            return
        error = ""
        if enabled:
            if not self.text.text().strip():
                error = "请先填写提醒内容"
            elif self.due.dateTime() <= QDateTime.currentDateTime():
                error = "请选择未来的提醒时间"
            elif self.repeat.currentData() == "weekly" and not any(box.isChecked() for box in self.weekday_checks):
                error = "每周提醒至少选择一天"
            if error:
                self.enabled.blockSignals(True)
                self.enabled.setChecked(False)
                self.enabled.blockSignals(False)
                self.set_time_editor_visible(True)
            else:
                self.completed = False
                self.snoozed_until = None
                self.last_triggered_at = None
        self.validation_label.setText(error)
        self.validation_label.setVisible(bool(error))
        self._content_changed()
        self.layout_changed.emit()

    def _schedule_changed(self) -> None:
        if self._applying_item:
            return
        self.enabled.setChecked(False)
        self.snoozed_until = None
        self.last_triggered_at = None
        self.validation_label.setText("时间已修改，请确认并开启")
        self.validation_label.show()
        self._content_changed()
        self.layout_changed.emit()

    def _repeat_changed(self) -> None:
        self.weekday_widget.setVisible(self.repeat.currentData() == "weekly")
        if self.repeat.currentData() == "weekly" and not any(box.isChecked() for box in self.weekday_checks):
            self.weekday_checks[self.due.dateTime().toPython().weekday()].setChecked(True)
        self.layout_changed.emit()
        self._schedule_changed()

    def apply_item(self, item: ReminderItem) -> None:
        """同步状态，不重建输入框或丢失正在编辑的文字/光标。"""
        self._applying_item = True
        try:
            self.completed = item.completed
            self.snoozed_until = item.snoozed_until
            self.last_triggered_at = item.last_triggered_at
            self.enabled.setChecked(item.enabled)
            due = QDateTime.fromString(item.due_at or "", Qt.DateFormat.ISODate)
            if due.isValid() and due != self.due.dateTime():
                self.due.setDateTime(due)
            self.repeat.setCurrentIndex(max(0, self.repeat.findData(item.repeat)))
            for index, checkbox in enumerate(self.weekday_checks):
                checkbox.setChecked(index in item.weekdays)
        finally:
            self._applying_item = False
        self._refresh_summary()
        self.layout_changed.emit()

    def _refresh_summary(self) -> None:
        due = self.due.dateTime().toPython()
        day_names = "一二三四五六日"
        self.date_box.setText(f"{due.day:02d}\n周{day_names[due.weekday()]}")
        repeat_label = {"once": "仅一次", "daily": "每天", "weekly": "每周"}.get(
            str(self.repeat.currentData()),
            "仅一次",
        )
        if self.repeat.currentData() == "weekly":
            days = "、".join(day_names[i] for i, box in enumerate(self.weekday_checks) if box.isChecked())
            repeat_label = f"每周{days}" if days else "请选择星期"
        state = " · 已完成" if self.completed else (" · 未开启" if not self.enabled.isChecked() else " · 已开启")
        summary = f"{due.strftime('%m-%d %H:%M')}\n{repeat_label}{state}"
        self.sub_label.setText(summary)
        self.sub_label.setWordWrap(True)
        self.confirm_time_button.setVisible(not self.enabled.isChecked())
        self.enabled.setVisible(self.enabled.isChecked())


class ReminderListEditor(QWidget):
    changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rows: list[_ReminderRow] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(7)
        self.rows_widget = QWidget(self)
        self.rows_widget.setObjectName("quickNotebookReminderRows")
        self.rows_layout = QVBoxLayout(self.rows_widget)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(7)
        self.rows_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self.rows_layout.addStretch(1)
        self.rows_scroll = QScrollArea(self)
        self.rows_scroll.setObjectName("quickNotebookReminderScroll")
        self.rows_scroll.setWidgetResizable(True)
        self.rows_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.rows_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.rows_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.rows_scroll.setWidget(self.rows_widget)
        self.rows_scroll.viewport().setObjectName("quickNotebookReminderViewport")
        layout.addWidget(self.rows_scroll, 1)
        self.empty_hint = QLabel("需要到点通知你？\n添加提醒，再设置日期、时间和重复规则", self)
        self.empty_hint.setObjectName("quickNotebookHelper")
        self.empty_hint.setWordWrap(True)
        layout.insertWidget(0, self.empty_hint)
        self.removal_history = _RemovalHistory(self)
        self.removal_history.restore_requested.connect(self._restore_item)
        layout.addWidget(self.removal_history)
        self.add_button = QPushButton("＋ 添加提醒事项", self)
        self.add_button.setObjectName("quickNotebookInlineAdd")
        self.add_button.clicked.connect(lambda: self.add_item(""))
        layout.addWidget(self.add_button)

    def set_items(self, items: Sequence[ReminderItem]) -> None:
        self._clear_rows()
        self.removal_history.reset()
        for item in items:
            self._append_row(item)
        self._update_rows_extent()

    def add_item(self, text: str) -> None:
        if not text.strip():
            blank = next((row for row in self._rows if not row.text.text().strip()), None)
            if blank is not None:
                self._focus_row(blank)
                return
        due_at = (datetime.now().astimezone() + timedelta(hours=1)).replace(
            second=0,
            microsecond=0,
        )
        self._append_row(
            ReminderItem(uuid.uuid4().hex, text, due_at=due_at.isoformat(), enabled=False)
        )
        self._update_rows_extent()
        self._focus_row(self._rows[-1])
        self.changed.emit()

    def items(self) -> tuple[ReminderItem, ...]:
        return tuple(row.value() for row in self._rows)

    def _append_row(self, item: ReminderItem, index: int | None = None) -> None:
        row = _ReminderRow(item, self.rows_widget)
        row.changed.connect(self.changed)
        row.layout_changed.connect(self._update_rows_extent)
        row.remove_requested.connect(lambda: self._remove_row(row))
        position = len(self._rows) if index is None else min(index, len(self._rows))
        self.rows_layout.insertWidget(position, row)
        self._rows.insert(position, row)
        row.show()

    def _focus_row(self, row: _ReminderRow) -> None:
        row.set_time_editor_visible(True)
        row.text.setFocus(Qt.FocusReason.OtherFocusReason)
        self.rows_layout.activate()
        self.rows_scroll.ensureWidgetVisible(row.text)

    def _remove_row(self, row: _ReminderRow) -> None:
        self.removal_history.record(self._rows.index(row), row.value())
        self._rows.remove(row)
        self.rows_layout.removeWidget(row)
        row.hide()
        row.deleteLater()
        self._update_rows_extent()
        self.changed.emit()

    def _restore_item(self, index: int, item: ReminderItem) -> None:
        self._append_row(item, index)
        self._update_rows_extent()
        self.changed.emit()

    def _update_rows_extent(self) -> None:
        self.empty_hint.setVisible(not self._rows)
        self.rows_widget.setMinimumHeight(max(1, sum(row.sizeHint().height() + 7 for row in self._rows)))

    def _clear_rows(self) -> None:
        for row in self._rows:
            self.rows_layout.removeWidget(row)
            row.deleteLater()
        self._rows.clear()
        self._update_rows_extent()


class _ElidedLabel(QLabel):
    def __init__(self, text: str, parent: QWidget) -> None:
        super().__init__(parent)
        self._full_text = text
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setToolTip(text)

    def resizeEvent(self, event: object) -> None:  # noqa: N802 - Qt override
        self.setText(
            self.fontMetrics().elidedText(
                self._full_text,
                Qt.TextElideMode.ElideRight,
                max(1, self.width()),
            )
        )
        super().resizeEvent(event)  # type: ignore[arg-type]


class DirectoryRowWidget(QWidget):
    """目录卡片内容；右侧页码和恢复操作拥有独立布局槽位。"""

    def __init__(
        self,
        title: str,
        right_text: str,
        parent: QWidget,
        *,
        on_activate: Callable[[], None] | None = None,
        on_restore: Callable[[], None] | None = None,
        categories: Sequence[str] = (),
    ) -> None:
        super().__init__(parent)
        self.setObjectName("quickNotebookDirectoryRow")
        self._on_activate = on_activate
        if on_activate is not None:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(11, 0, 9, 0)
        layout.setSpacing(8)
        self.title_label = _ElidedLabel(title, self)
        self.title_label.setObjectName("quickNotebookDirectoryItemTitle")
        text_column = QVBoxLayout()
        text_column.setSpacing(3)
        text_column.addWidget(self.title_label)
        self.category_label = _ElidedLabel(" · ".join(categories) or "未分类", self)
        self.category_label.setObjectName("quickNotebookDirectoryItemMeta")
        text_column.addWidget(self.category_label)
        self.category_label.setVisible(bool(categories))
        layout.addLayout(text_column, 1)
        self.right_label = QLabel(right_text, self)
        self.right_label.setObjectName("quickNotebookDirectoryItemMeta")
        self.restore_button: QPushButton | None = None
        if on_restore is None:
            layout.addWidget(self.right_label, 0, Qt.AlignmentFlag.AlignRight)
        else:
            self.right_label.hide()
            self.restore_button = QPushButton("恢复", self)
            self.restore_button.setObjectName("quickNotebookRestoreButton")
            self.restore_button.setFixedSize(48, 26)
            self.restore_button.clicked.connect(on_restore)
            layout.addWidget(self.restore_button, 0, Qt.AlignmentFlag.AlignRight)

    def mouseReleaseEvent(self, event: object) -> None:  # noqa: N802 - Qt override
        if event.button() == Qt.MouseButton.LeftButton and self._on_activate is not None:  # type: ignore[attr-defined]
            self._on_activate()
            event.accept()  # type: ignore[attr-defined]
            return
        super().mouseReleaseEvent(event)  # type: ignore[arg-type]


class QuickNotebookWindow(QWidget):
    """无顶部应用栏的三页型便签本。"""

    closed_by_user = Signal()

    def __init__(self, *, store: QuickNotebookStore, parent: QWidget | None = None) -> None:
        flags = Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
        super().__init__(parent, flags)
        self.store = store
        self.setObjectName("quickNotebookWindow")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._body_width = BOOK_WIDTH
        self._active_type: PageType = "note"
        self._current_page_id: str | None = None
        self._loading = False
        self._dirty = False
        self._title_is_custom = False
        self._reminder_baseline: dict[str, ReminderItem] = {}
        self._pending_reminder_changes: dict[tuple[str, str], ReminderItem] = {}
        self._retry_save: Callable[[], object] | None = None

        self.body_frame = QFrame(self)
        self.body_frame.setObjectName("quickNotebookPaper")
        shadow = QGraphicsDropShadowEffect(self.body_frame)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(78, 55, 38, 55))
        self.body_frame.setGraphicsEffect(shadow)
        body_layout = QVBoxLayout(self.body_frame)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)

        self.content_frame = QFrame(self.body_frame)
        self.content_frame.setObjectName("quickNotebookContent")
        content_layout = QVBoxLayout(self.content_frame)
        content_layout.setContentsMargins(17, 18, 17, 14)
        content_layout.setSpacing(8)
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        self.title_label = QLabel("标题（选填）", self.content_frame)
        self.title_label.setObjectName("quickNotebookFieldLabel")
        header.addWidget(self.title_label, 1)
        self.title_editor = _NotebookLineEdit(self.content_frame)
        self.title_editor.setObjectName("quickNotebookTitle")
        self.title_editor.setMinimumWidth(0)
        self.title_editor.setMinimumHeight(36)
        self.title_editor.setAccessibleName("标题（选填）")
        self.title_editor.setToolTip("点击修改标题；未填写时，自动使用第一条内容")
        self.title_label.setBuddy(self.title_editor)
        self.delete_button = QToolButton(self.content_frame)
        self.delete_button.setObjectName("quickNotebookDelete")
        self.delete_button.setAccessibleName("删除当前便签")
        self.delete_button.setToolTip("删除当前便签")
        self.delete_button.setProperty("iconName", "trash-2")
        self.delete_button.setIcon(lucide_icon("trash-2", color="#94867D", size=16))
        self.delete_button.setIconSize(QSize(16, 16))
        self.delete_button.setFixedSize(31, 31)
        header.addWidget(self.delete_button)
        self.close_button = QToolButton(self.content_frame)
        self.close_button.setObjectName("quickNotebookClose")
        self.close_button.setText("×")
        self.close_button.setFixedSize(28, 31)
        self.close_button.setAccessibleName("收起便签本")
        self.close_button.setToolTip("收起便签本（Esc），内容自动保存")
        header.addWidget(self.close_button)
        content_layout.addLayout(header)
        content_layout.addWidget(self.title_editor)
        self.page_hint = QLabel(self.content_frame)
        self.page_hint.setObjectName("quickNotebookHelper")
        self.page_hint.setWordWrap(True)
        content_layout.addWidget(self.page_hint)

        self.page_stack = QStackedWidget(self.content_frame)
        self.page_stack.setObjectName("quickNotebookPageStack")
        self.note_page = QWidget(self.page_stack)
        note_layout = QVBoxLayout(self.note_page)
        note_layout.setContentsMargins(10, 10, 10, 10)
        note_layout.setSpacing(8)
        self.body_label = QLabel("正文", self.note_page)
        self.body_label.setObjectName("quickNotebookFieldLabel")
        note_layout.addWidget(self.body_label)
        self.note_editor = _NotebookTextEdit(self.note_page)
        self.note_editor.setObjectName("quickNotebookNoteEditor")
        self.note_editor.setAccessibleName("便签正文")
        self.note_editor.setPlaceholderText("点击这里开始记录…")
        self.note_editor.setMinimumHeight(72)
        self.body_label.setBuddy(self.note_editor)
        note_layout.addWidget(self.note_editor, 1)
        self.tag_label = QLabel("分类（选填）", self.note_page)
        self.tag_label.setObjectName("quickNotebookFieldLabel")
        category_heading = QHBoxLayout()
        category_heading.addWidget(self.tag_label, 1)
        self.category_toggle = QToolButton(self.note_page)
        self.category_toggle.setObjectName("quickNotebookCategoryToggle")
        self.category_toggle.setCheckable(True)
        self.category_toggle.setText("添加分类 ▾")
        category_heading.addWidget(self.category_toggle)
        note_layout.addLayout(category_heading)
        self.category_panel = QWidget(self.note_page)
        category_layout = QVBoxLayout(self.category_panel)
        category_layout.setContentsMargins(0, 0, 0, 0)
        category_layout.setSpacing(5)
        self.tag_editor = _NotebookLineEdit(self.note_page)
        self.tag_editor.setObjectName("quickNotebookTagEditor")
        self.tag_editor.setPlaceholderText("例如：工作，生活")
        self.tag_editor.setAccessibleName("分类（选填，最多 5 个）")
        self.tag_editor.setToolTip("最多 5 个分类，例如：工作、生活")
        self.tag_editor.setMinimumWidth(0)
        self.tag_editor.setMinimumHeight(34)
        self.tag_label.setBuddy(self.tag_editor)
        category_layout.addWidget(self.tag_editor)
        self.tag_hint = QLabel("多个分类用逗号分隔，最多 5 个", self.note_page)
        self.tag_hint.setObjectName("quickNotebookFieldHelp")
        self.tag_hint.setWordWrap(True)
        category_layout.addWidget(self.tag_hint)
        note_layout.addWidget(self.category_panel)
        self.category_toggle.toggled.connect(self._toggle_categories)
        self.category_panel.hide()
        self.page_stack.addWidget(self.note_page)
        self.todo_editor = TodoListEditor(self.page_stack)
        self.todo_editor.setObjectName("quickNotebookTodoEditor")
        self.page_stack.addWidget(self.todo_editor)
        self.reminder_editor = ReminderListEditor(self.page_stack)
        self.reminder_editor.setObjectName("quickNotebookReminderEditor")
        self.page_stack.addWidget(self.reminder_editor)
        content_layout.addWidget(self.page_stack, 1)
        body_layout.addWidget(self.content_frame, 1)

        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.setInterval(500)
        self.save_timer.timeout.connect(self.flush_current_page)
        self.title_editor.textEdited.connect(self._on_title_edited)
        self.note_editor.textChanged.connect(self._on_page_content_changed)
        self.note_editor.cursorPositionChanged.connect(self._update_current_line_highlight)
        self.tag_editor.textChanged.connect(self._categories_changed)
        self.tag_editor.editingFinished.connect(self._normalize_categories)
        self.todo_editor.changed.connect(self._on_page_content_changed)
        self.reminder_editor.changed.connect(self._on_page_content_changed)

        self.footer = QFrame(self.body_frame)
        self.footer.setObjectName("quickNotebookFooter")
        footer_layout = QVBoxLayout(self.footer)
        footer_layout.setContentsMargins(13, 10, 13, 12)
        footer_layout.setSpacing(6)
        footer_navigation = QHBoxLayout()
        footer_navigation.setSpacing(6)
        self.directory_button = QPushButton("全部便签", self.footer)
        self.directory_button.setObjectName("quickNotebookDirectory")
        self.directory_button.setProperty("iconName", "menu")
        self.directory_button.setIcon(lucide_icon("menu", color="#81736A", size=14))
        self.directory_button.setIconSize(QSize(14, 14))
        self.page_count_label = QLabel("1 / 1", self.footer)
        self.page_count_label.setObjectName("quickNotebookPageCount")
        footer_navigation.addWidget(self.directory_button)
        footer_navigation.addStretch(1)
        self.previous_button = QToolButton(self.footer)
        self.previous_button.setText("‹")
        self.previous_button.setAccessibleName("上一页")
        self.previous_button.setFixedSize(31, 31)
        self.next_button = QToolButton(self.footer)
        self.next_button.setText("›")
        self.next_button.setAccessibleName("下一页")
        self.next_button.setFixedSize(31, 31)
        self.new_button = QPushButton("＋ 新建", self.footer)
        self.new_button.setObjectName("quickNotebookNew")
        self.new_button.setMinimumWidth(66)
        self.new_button.setFixedHeight(31)
        self.previous_button.setToolTip("上一页")
        self.next_button.setToolTip("下一页")
        footer_navigation.addWidget(self.previous_button)
        footer_navigation.addWidget(self.page_count_label)
        footer_navigation.addWidget(self.next_button)
        footer_layout.addLayout(footer_navigation)
        footer_actions = QHBoxLayout()
        self.save_hint = QLabel("已保存到本机", self.footer)
        self.save_hint.setObjectName("quickNotebookHelper")
        footer_actions.addWidget(self.save_hint)
        self.retry_button = QPushButton("重试", self.footer)
        self.retry_button.setObjectName("quickNotebookUndo")
        self.retry_button.clicked.connect(lambda: self._retry_save() if self._retry_save else self.flush_current_page())
        self.retry_button.hide()
        footer_actions.addWidget(self.retry_button)
        footer_actions.addStretch(1)
        footer_actions.addWidget(self.new_button)
        footer_layout.addLayout(footer_actions)
        body_layout.addWidget(self.footer)

        self.directory_overlay = QFrame(self.body_frame)
        self.directory_overlay.setObjectName("quickNotebookDirectoryOverlay")
        directory_layout = QVBoxLayout(self.directory_overlay)
        directory_layout.setContentsMargins(18, 18, 18, 18)
        directory_header = QHBoxLayout()
        self.directory_title = QLabel("普通便签目录", self.directory_overlay)
        self.directory_title.setObjectName("quickNotebookDirectoryTitle")
        directory_header.addWidget(self.directory_title)
        directory_header.addStretch(1)
        self.directory_close_button = QToolButton(self.directory_overlay)
        self.directory_close_button.setText("×")
        self.directory_close_button.setAccessibleName("关闭目录")
        directory_header.addWidget(self.directory_close_button)
        directory_layout.addLayout(directory_header)
        self.directory_scope = QLabel(self.directory_overlay)
        self.directory_scope.setObjectName("quickNotebookDirectoryScope")
        self.directory_scope.setWordWrap(True)
        directory_layout.addWidget(self.directory_scope)
        self.category_filter = _NotebookComboBox(self.directory_overlay)
        self.category_filter.setObjectName("quickNotebookCategoryFilter")
        self.category_filter.setAccessibleName("按分类筛选便签")
        self.category_filter.currentIndexChanged.connect(self._populate_directory)
        directory_layout.addWidget(self.category_filter)
        self.directory_empty = QLabel("这个分类下还没有便签", self.directory_overlay)
        self.directory_empty.setObjectName("quickNotebookHelper")
        directory_layout.addWidget(self.directory_empty)
        self.directory_empty.hide()
        self.directory_list = QListWidget(self.directory_overlay)
        self.directory_list.setObjectName("quickNotebookDirectoryList")
        self.directory_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.directory_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.directory_list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.directory_list.setWordWrap(False)
        self.directory_list.setSpacing(5)
        directory_layout.addWidget(self.directory_list, 1)
        directory_actions = QHBoxLayout()
        self.trash_button = QPushButton("回收站", self.directory_overlay)
        self.trash_button.setObjectName("quickNotebookTrashButton")
        self.trash_button.setMinimumHeight(28)
        self._showing_trash = False
        self.clear_all_button = QPushButton("清空全部便签…", self.directory_overlay)
        self.clear_all_button.setObjectName("quickNotebookClearAll")
        self.clear_all_button.setMinimumHeight(28)
        directory_actions.addWidget(self.trash_button)
        directory_actions.addStretch(1)
        directory_actions.addWidget(self.clear_all_button)
        directory_layout.addLayout(directory_actions)
        self.directory_overlay.hide()

        self.confirm_overlay = QFrame(self.body_frame)
        self.confirm_overlay.setObjectName("quickNotebookConfirmOverlay")
        confirm_layout = QVBoxLayout(self.confirm_overlay)
        confirm_layout.setContentsMargins(17, 16, 17, 16)
        confirm_layout.setSpacing(8)
        self.confirm_title = QLabel(self.confirm_overlay)
        self.confirm_title.setObjectName("quickNotebookConfirmTitle")
        self.confirm_message = QLabel(self.confirm_overlay)
        self.confirm_message.setObjectName("quickNotebookConfirmMessage")
        self.confirm_message.setWordWrap(True)
        confirm_layout.addWidget(self.confirm_title)
        confirm_layout.addWidget(self.confirm_message)
        confirm_actions = QHBoxLayout()
        confirm_actions.addStretch(1)
        self.confirm_cancel_button = QPushButton("取消", self.confirm_overlay)
        self.confirm_cancel_button.setObjectName("quickNotebookConfirmCancel")
        self.confirm_cancel_button.setMinimumSize(54, 28)
        self.confirm_action_button = QPushButton("删除", self.confirm_overlay)
        self.confirm_action_button.setObjectName("quickNotebookDangerButton")
        self.confirm_action_button.setMinimumSize(54, 28)
        confirm_actions.addWidget(self.confirm_cancel_button)
        confirm_actions.addWidget(self.confirm_action_button)
        confirm_layout.addLayout(confirm_actions)
        self.confirm_overlay.setFixedWidth(300)
        self.confirm_overlay.adjustSize()
        self.confirm_overlay.hide()
        self._confirm_kind = ""
        self._confirm_page_id: str | None = None

        self.type_tabs = (
            NotebookTypeTab("note", "pencil", "便签", "#9E8ACB", self),
            NotebookTypeTab("todo", "check", "待办", "#75A876", self),
            NotebookTypeTab("reminder", "clock-3", "提醒", "#D39C54", self),
        )
        for button in self.type_tabs:
            page_type = button.property("pageType")
            button.clicked.connect(lambda _checked=False, value=page_type: self.select_type(value))

        self.directory_button.clicked.connect(self.open_directory)
        self.directory_close_button.clicked.connect(self.directory_overlay.hide)
        self.directory_list.itemActivated.connect(self._activate_directory_item)
        self.previous_button.clicked.connect(self.previous_page)
        self.next_button.clicked.connect(self.next_page)
        self.new_button.clicked.connect(self.new_page)
        self.delete_button.clicked.connect(self._prompt_delete_current)
        self.close_button.clicked.connect(self.close_notebook)
        self.clear_all_button.clicked.connect(self._prompt_clear_all)
        self.trash_button.clicked.connect(lambda: self.open_directory() if self._showing_trash else self.open_trash())
        self.confirm_cancel_button.clicked.connect(self.confirm_overlay.hide)
        self.confirm_action_button.clicked.connect(self._run_confirmed_action)

        self.setStyleSheet(_notebook_stylesheet())
        self.resize(self.sizeHint())
        self.select_type(self.store.last_type)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt override
        return QSize(RAIL_WIDTH - 1 + BOOK_WIDTH, NATURAL_HEIGHT + SHADOW_BOTTOM_MARGIN)

    def fit_to_available_geometry(self, available: QRect) -> QSize:
        rail = min(RAIL_WIDTH, max(58, available.width() // 4))
        self._body_width = min(BOOK_WIDTH, max(1, available.width() - rail + 1))
        width = min(available.width(), rail - 1 + self._body_width)
        height = min(available.height(), NATURAL_HEIGHT + SHADOW_BOTTOM_MARGIN)
        self.resize(max(1, width), max(1, height))
        return self.size()

    def select_type(self, page_type: PageType) -> None:
        if page_type not in {"note", "todo", "reminder"}:
            raise ValueError(page_type)
        if page_type != self._active_type or self._current_page_id is not None:
            if not self.flush_current_page():
                self._set_active_type_visual(self._active_type)
                return
        page_ids = self.store.page_ids(page_type)
        selected = self.store.last_page_id_by_type.get(page_type)
        if selected not in page_ids:
            if not page_ids:
                if not self._try_persist(lambda: self.store.create_page(page_type), lambda: self.select_type(page_type)):
                    return
                page_ids = self.store.page_ids(page_type)
            selected = page_ids[0]
        self.show_page(selected)

    @property
    def current_page_id(self) -> str | None:
        return self._current_page_id

    def show_page(self, page_id: str) -> None:
        page = self.store.page(page_id)
        if page is None:
            raise KeyError(page_id)
        if self._current_page_id != page_id:
            if not self.flush_current_page():
                return
        elif self._dirty and not self.flush_current_page():
            return
        # flush may replace the in-memory page object.
        page = self.store.page(page_id)
        if page is None:
            return
        self._set_active_type_visual(page.type)
        self._current_page_id = page.id
        self.store.last_type = page.type
        self.store.last_page_id_by_type[page.type] = page.id
        self._loading = True
        try:
            self._title_is_custom = bool((page.custom_title or "").strip())
            self.title_editor.setText(page.custom_title or "")
            self._set_title_hint(page.display_title)
            self.note_editor.setPlainText(page.body)
            self.tag_editor.setText("、".join(page.tags))
            self.category_toggle.setChecked(False)
            self.category_panel.hide()
            self._update_category_summary()
            self.todo_editor.set_items(page.todo_items)
            self.reminder_editor.set_items(page.reminders)
            self._reminder_baseline = {item.id: item for item in self.reminder_editor.items()}
        finally:
            self._loading = False
        self._dirty = False
        self._save_selection()
        self._refresh_navigation()
        self.directory_overlay.hide()

    def set_custom_title(self, title: str | None) -> None:
        normalized = (title or "").strip()
        self._title_is_custom = bool(normalized)
        self.title_editor.setText(normalized)
        self._set_title_hint(self._derived_editor_title())
        self._dirty = True
        self._schedule_save()

    def _set_save_status(self, text: str, *, error: bool = False) -> None:
        self.save_hint.setText(text)
        self.save_hint.setToolTip(text)
        self.save_hint.setStyleSheet("color: #A23E32;" if error else "")

    def _save_selection(self) -> bool:
        if not self.flush_pending_reminder_changes():
            return False
        return self._try_persist(lambda: None, self._save_selection)

    def _try_persist(self, change: Callable[[], object], retry: Callable[[], object]) -> bool:
        self._set_save_status("保存中…")
        try:
            self.store.persist(change)
        except OSError:
            self._set_save_status("保存失败", error=True)
            self.save_hint.setToolTip("无法写入本机文件，内容仍保留。请检查磁盘空间和权限后重试。")
            self._retry_save = retry
            self.retry_button.show()
            self.directory_overlay.hide()
            self.confirm_overlay.hide()
            return False
        self._retry_save = None
        self.retry_button.hide()
        self._set_save_status("已保存到本机")
        return True

    def flush_current_page(self) -> bool:
        self.save_timer.stop()
        if not self._loading and not self.flush_pending_reminder_changes():
            return False
        if self._loading or not self._dirty or self._current_page_id is None:
            return True
        page = self.store.page(self._current_page_id)
        if page is None:
            return False
        custom_title = self.title_editor.text().strip() if self._title_is_custom else None
        if page.type == "note":
            tags = tuple(dict.fromkeys(
                part.strip()
                for part in re.split(r"[,，、]", self.tag_editor.text())
                if part.strip()
            ))
            if len(tags) > 5:
                self.category_toggle.setChecked(True)
                self._set_save_status("分类超限，未保存", error=True)
                return False
            updated = replace(
                page,
                custom_title=custom_title,
                body=self.note_editor.toPlainText(),
                tags=tags,
            )
        elif page.type == "todo":
            updated = replace(
                page,
                custom_title=custom_title,
                todo_items=list(self.todo_editor.items()),
            )
        else:
            updated = replace(
                page,
                custom_title=custom_title,
                reminders=self._merged_reminders(page),
            )
        if not self._try_persist(lambda: self.store.update_page(updated), self.flush_current_page):
            return False
        self._dirty = False
        if page.type == "note" and not self.tag_editor.hasFocus():
            self._normalize_categories()
        if not self._title_is_custom:
            self._set_title_hint(updated.display_title)
        if page.type == "reminder":
            self.sync_reminder_state(page.id)
        self._refresh_navigation()
        return True

    @staticmethod
    def _merge_reminder(draft: ReminderItem, baseline: ReminderItem, current: ReminderItem) -> ReminderItem:
        fields = ("text", "due_at", "repeat", "weekdays", "enabled")
        changes = {name: getattr(draft, name) for name in fields if getattr(draft, name) != getattr(baseline, name)}
        rearmed = draft.enabled and not baseline.enabled
        schedule_changed = any(name in changes for name in ("due_at", "repeat", "weekdays"))
        if rearmed:
            changes["completed"] = False
        if rearmed or schedule_changed:
            changes.update(snoozed_until=None, last_triggered_at=None)
        return replace(current, **changes)

    def _merged_reminders(self, page: NotebookPage) -> list[ReminderItem]:
        current = {item.id: item for item in page.reminders}
        result = []
        for draft in self.reminder_editor.items():
            baseline = self._reminder_baseline.get(draft.id)
            if baseline is None:
                result.append(draft)
            elif draft.id in current:
                result.append(self._merge_reminder(draft, baseline, current[draft.id]))
        result.extend(item for item in page.reminders if item.id not in self._reminder_baseline and item.id not in {value.id for value in result})
        return result

    def sync_reminder_state(self, page_id: str) -> None:
        if page_id != self._current_page_id:
            return
        page = self.store.page(page_id)
        if page is None or page.type != "reminder":
            return
        current = {item.id: item for item in page.reminders}
        self._loading = True
        try:
            for row in self.reminder_editor._rows:
                item = current.get(row.item_id)
                if item is None:
                    continue
                baseline = self._reminder_baseline.get(item.id, row.value())
                merged = self._merge_reminder(row.value(), baseline, item) if self._dirty else item
                row.apply_item(merged)
                # Keep the remote version as baseline so unsaved local edits remain changes.
                self._reminder_baseline[item.id] = item
        finally:
            self._loading = False

    def persist_reminder_change(self, page_id: str, item: ReminderItem) -> bool:
        def change() -> None:
            page = self.store.page(page_id)
            if page is not None:
                last_type = self.store.last_type
                last_ids = dict(self.store.last_page_id_by_type)
                self.store.update_page(replace(page, reminders=[item if value.id == item.id else value for value in page.reminders]))
                self.store.last_type = last_type
                self.store.last_page_id_by_type = last_ids
        retry = lambda: self.persist_reminder_change(page_id, item)
        if not self._try_persist(change, retry):
            self._pending_reminder_changes[(page_id, item.id)] = item
            return False
        self._pending_reminder_changes.pop((page_id, item.id), None)
        self.sync_reminder_state(page_id)
        if self._dirty:
            self._set_save_status("有修改待保存")
        return True

    def flush_pending_reminder_changes(self) -> bool:
        for (page_id, _item_id), item in tuple(self._pending_reminder_changes.items()):
            if not self.persist_reminder_change(page_id, item):
                return False
        return True

    def directory_titles(self) -> tuple[str, ...]:
        return tuple(page.display_title for page in self.store.pages(self._active_type))

    def open_directory(self) -> None:
        if not self.flush_current_page():
            return
        self._showing_trash = False
        pages = self.store.pages(self._active_type)
        label = {"note": "普通便签", "todo": "待办清单", "reminder": "提醒事项"}[
            self._active_type
        ]
        self.directory_title.setText(f"{label}目录")
        self.clear_all_button.setText(f"清空全部{label}…")
        self.clear_all_button.show()
        self.trash_button.setText(f"回收站 · {self.store.trash_count}")
        selected = self.category_filter.currentData()
        self.category_filter.blockSignals(True)
        self.category_filter.clear()
        self.category_filter.addItem("全部分类", None)
        self.category_filter.addItem("未分类", "")
        for tag in sorted({tag for page in pages for tag in page.tags}):
            self.category_filter.addItem(tag, tag)
        self.category_filter.setCurrentIndex(max(0, self.category_filter.findData(selected)))
        self.category_filter.blockSignals(False)
        self.category_filter.setVisible(self._active_type == "note")
        self._populate_directory()
        self.directory_overlay.show()
        self.directory_overlay.raise_()

    def _populate_directory(self) -> None:
        if self._showing_trash:
            return
        all_pages = self.store.pages(self._active_type)
        selected = self.category_filter.currentData() if self._active_type == "note" else None
        pages = sorted(
            (page for page in all_pages if selected is None or (not page.tags if selected == "" else selected in page.tags)),
            key=lambda page: page.updated_at,
            reverse=True,
        )
        self.directory_scope.setText(f"显示 {len(pages)} / {len(all_pages)} 页 · 最近编辑优先")
        self.directory_empty.setVisible(not pages)
        self.directory_list.clear()
        for index, page in enumerate(pages, start=1):
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, page.id)
            item.setToolTip(page.display_title)
            item.setSizeHint(QSize(0, 52))
            self.directory_list.addItem(item)
            self.directory_list.setItemWidget(
                item,
                DirectoryRowWidget(
                    page.display_title,
                    f"{self.store.page_ids(self._active_type).index(page.id) + 1} / {len(all_pages)}",
                    self.directory_list,
                    on_activate=lambda page_id=page.id: self.show_page(page_id),
                    categories=page.tags or (("未分类",) if page.type == "note" else ()),
                ),
            )
            if page.id == self._current_page_id:
                self.directory_list.setCurrentItem(item)

    def open_trash(self) -> None:
        self._showing_trash = True
        self.category_filter.hide()
        self.directory_empty.hide()
        entries = self.store.trash_entries()
        self.directory_title.setText(f"回收站 · {len(entries)}")
        self.directory_scope.setText("删除后保留 7 天")
        self.trash_button.setText("‹ 返回列表")
        self.clear_all_button.hide()
        self.directory_list.clear()
        for entry in entries:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, ("trash", entry.page.id))
            item.setToolTip(entry.page.display_title)
            item.setSizeHint(QSize(0, 52))
            self.directory_list.addItem(item)
            self.directory_list.setItemWidget(
                item,
                DirectoryRowWidget(
                    entry.page.display_title,
                    "",
                    self.directory_list,
                    on_restore=lambda _checked=False, page_id=entry.page.id: self.restore_from_trash(page_id),
                ),
            )

    def new_page(self) -> NotebookPage | None:
        if not self.flush_current_page():
            return None
        pages = self.store.pages(self._active_type)
        page = next((value for value in pages if value.is_empty and value.id == self._current_page_id), None)
        page = page or next((value for value in pages if value.is_empty), None)
        if page is None:
            if not self._try_persist(lambda: self.store.create_page(self._active_type), self.new_page):
                return None
            page = self.store.pages(self._active_type)[0]
        self.show_page(page.id)
        if page.type == "note":
            self.note_editor.setFocus(Qt.FocusReason.OtherFocusReason)
        elif page.type == "todo":
            self.todo_editor.add_item("")
        else:
            self.reminder_editor.add_item("")
        return page

    def previous_page(self) -> NotebookPage | None:
        if self._current_page_id is None:
            return None
        if not self.flush_current_page():
            return None
        page = self.store.previous_page(self._active_type, self._current_page_id)
        if page is not None:
            self.show_page(page.id)
        return page

    def next_page(self) -> NotebookPage | None:
        if self._current_page_id is None:
            return None
        if not self.flush_current_page():
            return None
        page = self.store.next_page(self._active_type, self._current_page_id)
        if page is not None:
            self.show_page(page.id)
        return page

    def confirm_delete_page(self, page_id: str) -> None:
        if page_id == self._current_page_id:
            if not self.flush_current_page():
                return
        page = self.store.page(page_id)
        current_type = page.type if page is not None else self._active_type
        if page is None:
            return
        def change() -> None:
            if page.is_empty:
                self.store.discard_page(page_id)
            else:
                self.store.delete_page(page_id)
        if not self._try_persist(change, lambda: self.confirm_delete_page(page_id)):
            return
        remaining = self.store.page_ids(current_type)
        if remaining:
            self.show_page(remaining[0])
        else:
            self._show_empty_type(current_type)

    def confirm_clear_all(self) -> None:
        if not self.flush_current_page():
            return
        if not self._try_persist(lambda: self.store.clear_type(self._active_type), self.confirm_clear_all):
            return
        self._show_empty_type(self._active_type)
        self.directory_overlay.hide()

    def restore_from_trash(self, page_id: str) -> NotebookPage | None:
        if not self.flush_current_page():
            return None
        if not self._try_persist(lambda: self.store.restore_page(page_id), lambda: self.restore_from_trash(page_id)):
            return None
        page = self.store.page(page_id)
        self.show_page(page.id)
        return page

    def _set_active_type_visual(self, page_type: PageType) -> None:
        self._active_type = page_type
        index = ("note", "todo", "reminder").index(page_type)
        self.page_stack.setCurrentIndex(index)
        self.page_hint.setText({
            "note": "不填标题时，自动用正文第一行命名。",
            "todo": "勾选完成一项 · 输入后按回车继续添加",
            "reminder": "设置时间，到点在宠物旁提醒你。",
        }[page_type])
        self.page_hint.setVisible(page_type == "todo")
        self.directory_button.setText({"note": "全部便签", "todo": "全部清单", "reminder": "全部提醒页"}[page_type])
        self.new_button.setText({"note": "＋ 新建便签", "todo": "＋ 新建清单", "reminder": "＋ 新建提醒页"}[page_type])
        self.new_button.setToolTip("另建一页，不会清空当前内容")
        delete_label = {"note": "删除当前便签", "todo": "删除整张待办清单", "reminder": "删除整页提醒"}[page_type]
        self.delete_button.setToolTip(delete_label)
        self.delete_button.setAccessibleName(delete_label)
        for position, button in enumerate(self.type_tabs):
            button.set_active(position == index)
        self._layout_floating_children()

    def _show_empty_type(self, page_type: PageType) -> None:
        self._set_active_type_visual(page_type)
        self._current_page_id = None
        self._loading = True
        try:
            self._title_is_custom = False
            self.title_editor.clear()
            self._set_title_hint(self._fallback_title())
            self.note_editor.clear()
            self.tag_editor.clear()
            self.category_toggle.setChecked(False)
            self._update_category_summary()
            self.todo_editor.set_items(())
            self.reminder_editor.set_items(())
        finally:
            self._loading = False
        self._dirty = False
        self.page_count_label.setText("0 / 0")
        self.previous_button.setEnabled(False)
        self.next_button.setEnabled(False)

    def _fallback_title(self) -> str:
        return {"note": "无标题便签", "todo": "新待办清单", "reminder": "新提醒列表"}[
            self._active_type
        ]

    def _refresh_navigation(self) -> None:
        ids = self.store.page_ids(self._active_type)
        if self._current_page_id not in ids:
            self.page_count_label.setText(f"0 / {len(ids)}")
            self.previous_button.setEnabled(False)
            self.next_button.setEnabled(False)
            return
        index = ids.index(self._current_page_id)
        self.page_count_label.setText(f"{index + 1} / {len(ids)}")
        self.previous_button.setEnabled(index > 0)
        self.next_button.setEnabled(index + 1 < len(ids))

    def _on_title_edited(self, text: str) -> None:
        if self._loading:
            return
        self._title_is_custom = bool(text.strip())
        self._set_title_hint(self._derived_editor_title())
        self._dirty = True
        self._schedule_save()

    def _on_page_content_changed(self) -> None:
        if self._loading:
            return
        if not self._title_is_custom:
            self._set_title_hint(self._derived_editor_title())
        self._dirty = True
        self._schedule_save()

    def _derived_editor_title(self) -> str:
        if self._active_type == "note":
            candidates = self.note_editor.toPlainText().splitlines()
        elif self._active_type == "todo":
            candidates = [item.text for item in self.todo_editor.items()]
        else:
            candidates = [item.text for item in self.reminder_editor.items()]
        return next((text.strip() for text in candidates if text.strip()), self._fallback_title())

    def _set_title_hint(self, derived_title: str) -> None:
        hint = (
            "点击输入标题，不填则自动命名"
            if derived_title == self._fallback_title()
            else f"自动命名：{derived_title}"
        )
        self.title_editor.setPlaceholderText(hint)

    def _schedule_save(self) -> None:
        if not self._loading and self._dirty and self._current_page_id is None:
            # 删除最后一页后仍可直接编辑，不能让新输入成为无归属数据。
            page = self.store.create_page(self._active_type)
            self._current_page_id = page.id
            self.store.last_type = page.type
            self.store.last_page_id_by_type[page.type] = page.id
            self._refresh_navigation()
        if not self._loading and self._current_page_id is not None:
            if self._retry_save is not None:
                self._retry_save = self.flush_current_page
            self._set_save_status("有修改待保存")
            self.save_timer.start()

    def _toggle_categories(self, expanded: bool) -> None:
        self.category_panel.setVisible(expanded)
        self._update_category_summary()

    def _update_category_summary(self) -> None:
        tags = tuple(dict.fromkeys(part.strip() for part in re.split(r"[,，、]", self.tag_editor.text()) if part.strip()))
        self.category_toggle.setText("收起 ▴" if self.category_toggle.isChecked() else (f"{len(tags)} 个分类 ▾" if tags else "添加分类 ▾"))
        self.category_toggle.setToolTip("、".join(tags) or "添加分类后可在全部便签中筛选")
        excess = len(tags) > 5
        self.tag_hint.setText(f"已有 {len(tags)} 个分类，最多 5 个；请删减后保存" if excess else "多个分类用逗号分隔，最多 5 个")
        self.tag_hint.setStyleSheet("color: #A23E32;" if excess else "")

    def _categories_changed(self) -> None:
        self._update_category_summary()
        if not self._loading:
            self.category_toggle.setChecked(True)
        self._on_page_content_changed()

    def _normalize_categories(self) -> None:
        tags = tuple(dict.fromkeys(part.strip() for part in re.split(r"[,，、]", self.tag_editor.text()) if part.strip()))
        if len(tags) <= 5:
            self.tag_editor.blockSignals(True)
            self.tag_editor.setText("、".join(tags))
            self.tag_editor.blockSignals(False)
            self._update_category_summary()

    def _update_current_line_highlight(self) -> None:
        if not self.note_editor.toPlainText():
            self.note_editor.setExtraSelections([])
            return
        selection = QTextEdit.ExtraSelection()
        selection.format.setBackground(QColor("#FFF0E8"))
        selection.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
        selection.cursor = self.note_editor.textCursor()
        selection.cursor.clearSelection()
        self.note_editor.setExtraSelections([selection])

    def _activate_directory_item(self, item: QListWidgetItem) -> None:
        value = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(value, tuple) and len(value) == 2 and value[0] == "trash":
            self.restore_from_trash(str(value[1]))
        elif isinstance(value, str):
            self.show_page(value)

    def _prompt_delete_current(self) -> None:
        if self._current_page_id is None:
            return
        self._confirm_kind = "delete"
        self._confirm_page_id = self._current_page_id
        self.confirm_title.setText(f"{self.delete_button.accessibleName()}？")
        self.confirm_message.setText("删除后进入回收站，可在 7 天内恢复。")
        self.confirm_action_button.setText("删除")
        self._show_confirm_overlay()

    def _prompt_clear_all(self) -> None:
        label = {"note": "普通便签", "todo": "待办清单", "reminder": "提醒事项"}[
            self._active_type
        ]
        count = len(self.store.page_ids(self._active_type))
        self._confirm_kind = "clear"
        self._confirm_page_id = None
        self.confirm_title.setText(f"清空全部{label}？")
        self.confirm_message.setText(f"当前类别的 {count} 张{label}将进入回收站，其他类别不受影响。")
        self.confirm_action_button.setText("全部清空")
        self._show_confirm_overlay()

    def _show_confirm_overlay(self) -> None:
        self.confirm_overlay.adjustSize()
        x = max(0, (self.body_frame.width() - self.confirm_overlay.width()) // 2)
        y = max(0, (self.body_frame.height() - self.confirm_overlay.height()) // 2)
        self.confirm_overlay.move(x, y)
        self.confirm_overlay.show()
        self.confirm_overlay.raise_()

    def _run_confirmed_action(self) -> None:
        kind = self._confirm_kind
        page_id = self._confirm_page_id
        self.confirm_overlay.hide()
        if kind == "delete" and page_id is not None:
            self.confirm_delete_page(page_id)
        elif kind == "clear":
            self.confirm_clear_all()

    def keyPressEvent(self, event: object) -> None:  # noqa: N802 - Qt override
        if event.key() == Qt.Key.Key_Escape:  # type: ignore[attr-defined]
            if self.confirm_overlay.isVisible():
                self.confirm_overlay.hide()
            elif self.directory_overlay.isVisible():
                self.directory_overlay.hide()
            else:
                self.close_notebook()
            event.accept()  # type: ignore[attr-defined]
            return
        super().keyPressEvent(event)  # type: ignore[arg-type]

    def close_notebook(self) -> None:
        if not self.flush_current_page():
            return
        self.hide()
        self.closed_by_user.emit()

    def reposition(self, pet_rect: QRect, *, avoid_rects: Sequence[QRect] = ()) -> None:
        screen = QGuiApplication.screenAt(pet_rect.center()) or QGuiApplication.primaryScreen()
        if screen is None:
            return
        self.fit_to_available_geometry(screen.availableGeometry())
        self.move(place_notebook(pet_rect, self.size(), screen.availableGeometry(), avoid_rects=avoid_rects))

    def show_for(self, pet_rect: QRect, *, avoid_rects: Sequence[QRect] = ()) -> None:
        self.reposition(pet_rect, avoid_rects=avoid_rects)
        self.show()
        self.raise_()

    def resizeEvent(self, event: object) -> None:  # noqa: N802 - Qt override
        self._layout_floating_children()
        super().resizeEvent(event)  # type: ignore[arg-type]

    def _layout_floating_children(self) -> None:
        body_x = max(0, self.width() - self._body_width)
        body_height = max(1, self.height() - SHADOW_BOTTOM_MARGIN)
        self.body_frame.setGeometry(body_x, 0, self._body_width, body_height)
        clip_path = QPainterPath()
        clip_path.addRoundedRect(self.body_frame.rect(), 17, 17)
        self.body_frame.setMask(QRegion(clip_path.toFillPolygon().toPolygon()))
        self.directory_overlay.setGeometry(self.body_frame.rect())
        if self.confirm_overlay.isVisible():
            self._show_confirm_overlay()
        for index, button in enumerate(self.type_tabs):
            button.setFixedWidth(min(88, body_x + 1))
            button.move(body_x - button.width() + 1, TAB_TOP + index * (TAB_HEIGHT + TAB_GAP))
            button.raise_()


def _notebook_stylesheet() -> str:
    return """
        QFrame#quickNotebookPaper {
            background: #FFFDFA;
            border: 1px solid #DDCFC2;
            border-radius: 17px;
        }
        QFrame#quickNotebookContent { background: transparent; border: none; }
        QLineEdit, QPlainTextEdit { placeholder-text-color: #796C62; }
        QLabel#quickNotebookFieldLabel { color: #4B4641; font-size: 13px; font-weight: 700; }
        QLabel#quickNotebookFieldHelp { color: #71655C; font-size: 11px; }
        QLabel#quickNotebookValidation { color: #A23E32; font-size: 11px; }
        QToolButton#quickNotebookCategoryToggle { color: #875334; background: #FFF4EC; border: none; padding: 4px 7px; font-size: 11px; }
        QComboBox#quickNotebookCategoryFilter { color: #4B4641; background: #FFFFFF; border: 1px solid #CDB9A8; border-radius: 7px; padding: 6px 8px; }
        QLineEdit#quickNotebookTitle { background: #FFFFFF; border: 1px solid #CDB9A8; border-radius: 8px; color: #4B4641; font-size: 14px; font-weight: 600; padding: 5px 9px; }
        QToolButton#quickNotebookDelete { background: transparent; border: none; border-radius: 9px; }
        QToolButton#quickNotebookDelete:hover { background: #F7EEE7; }
        QToolButton#quickNotebookClose { background: transparent; border: none; color: #81736A; font-size: 20px; }
        QToolButton#quickNotebookClose:hover { background: #F7EEE7; }
        QLabel#quickNotebookHelper { color: #81736A; font-size: 11px; }
        QToolButton#quickNotebookRemoveItem { background: transparent; border: none; }
        QToolButton#quickNotebookRemoveItem:hover { background: #F9E9E1; }
        QToolButton#quickNotebookEditTime { background: transparent; border: none; color: #A45F43; font-size: 10px; padding: 2px 0; text-align: left; }
        QPushButton#quickNotebookUndo { background: #FFF0E8; color: #A45F43; border: none; border-radius: 6px; padding: 4px 9px; }
        QStackedWidget#quickNotebookPageStack {
            background: #FFFEFB;
            border: 1px solid #EEE3DA;
            border-radius: 13px;
        }
        QStackedWidget#quickNotebookPageStack > QWidget { background: transparent; border: none; }
        QPlainTextEdit#quickNotebookNoteEditor { background: #FFFFFF; border: 1px solid #CDB9A8; border-radius: 8px; color: #4B4641; padding: 9px; font-size: 13px; }
        QLineEdit#quickNotebookTagEditor { background: #FFFFFF; color: #4B4641; border: 1px solid #CDB9A8; border-radius: 8px; padding: 5px 9px; font-size: 13px; }
        QLineEdit#quickNotebookTitle:hover, QLineEdit#quickNotebookTagEditor:hover, QPlainTextEdit#quickNotebookNoteEditor:hover { border-color: #B8947B; }
        QLineEdit#quickNotebookTitle:focus, QLineEdit#quickNotebookTagEditor:focus, QPlainTextEdit#quickNotebookNoteEditor:focus { background: #FFFBF7; border: 2px solid #B56F48; }
        QFrame#quickNotebookTodoRow { background: #FFFEFB; border: 1px solid #EEE3DA; border-radius: 11px; }
        QFrame#quickNotebookTodoRow[completed="true"] { background: #FAF7F3; color: #9B918A; }
        QFrame#quickNotebookTodoRow QLineEdit { background: transparent; border: none; color: #57514D; padding: 4px 2px; font-size: 12px; }
        QFrame#quickNotebookTodoRow QLineEdit:focus { background: #FFF4EC; border-radius: 5px; }
        QFrame#quickNotebookTodoRow[completed="true"] QLineEdit { color: #9B918A; }
        QFrame#quickNotebookReminderRow { background: #FFFEFB; border: 1px solid #EEE3DA; border-radius: 11px; }
        QLineEdit#quickNotebookReminderText { background: transparent; border: none; color: #4B4641; padding: 1px 0; font-size: 12px; font-weight: 600; }
        QLabel#quickNotebookReminderSub { color: #81736A; font-size: 10px; }
        QToolButton#quickNotebookDateBox { background: #FFF2DF; color: #A96F32; border: none; border-radius: 10px; font-size: 11px; font-weight: 700; }
        QDateTimeEdit#quickNotebookReminderDateTime, QComboBox#quickNotebookReminderRepeat { background: #FFFDF9; color: #57514D; border: 1px solid #E3D7CC; border-radius: 8px; padding: 5px 7px; }
        QFrame#quickNotebookReminderRow QCheckBox { color: #57514D; font-size: 11px; }
        QScrollArea#quickNotebookTodoScroll, QScrollArea#quickNotebookReminderScroll,
        QScrollArea#quickNotebookTodoScroll > QWidget, QScrollArea#quickNotebookReminderScroll > QWidget { background: transparent; border: none; }
        QWidget#quickNotebookTodoRows, QWidget#quickNotebookReminderRows,
        QWidget#quickNotebookTodoViewport, QWidget#quickNotebookReminderViewport { background: #FFFEFB; border: none; }
        QFrame#quickNotebookDirectoryOverlay { background: #FFFDFA; border: 1px solid #DDCFC2; border-radius: 17px; }
        QLabel#quickNotebookDirectoryTitle { color: #4B4641; font-size: 16px; font-weight: 700; }
        QLabel#quickNotebookDirectoryScope { color: #96887F; font-size: 11px; }
        QListWidget#quickNotebookDirectoryList { background: transparent; border: none; outline: none; padding: 0; }
        QListWidget#quickNotebookDirectoryList::item { background: #FFFEFB; color: #4B4641; border: 1px solid #EEE3DA; border-radius: 10px; padding: 4px 0; }
        QListWidget#quickNotebookDirectoryList::item:selected { background: #FFF7F2; color: #4B4641; border-color: #D9B9AA; }
        QWidget#quickNotebookDirectoryRow { background: transparent; border: none; }
        QLabel#quickNotebookDirectoryItemTitle { color: #4B4641; font-size: 12px; }
        QLabel#quickNotebookDirectoryItemMeta { color: #A0948C; font-size: 10px; }
        QPushButton#quickNotebookRestoreButton { background: #FFF0E8; color: #A45F43; border: 1px solid #E5C2B2; border-radius: 8px; padding: 4px 8px; font-size: 11px; font-weight: 700; }
        QPushButton#quickNotebookInlineAdd { background: #FFF9F5; color: #A36B53; border: 1px dashed #DDCBBD; border-radius: 10px; padding: 7px; text-align: left; }
        QLabel#quickNotebookProgress, QLabel#quickNotebookProgressPercent { color: #796E67; font-size: 11px; }
        QProgressBar#quickNotebookProgressBar { min-height: 6px; max-height: 6px; background: #EEE5DD; border: none; border-radius: 3px; }
        QProgressBar#quickNotebookProgressBar::chunk { background: #79A282; border-radius: 3px; }
        QPushButton#quickNotebookTrashButton { background: transparent; color: #81736A; border: none; padding: 4px 0; text-align: left; }
        QPushButton#quickNotebookClearAll { background: #FFF7F6; color: #B85F55; border: 1px solid #E7B9B3; border-radius: 9px; padding: 5px 8px; }
        QFrame#quickNotebookConfirmOverlay { background: #FFFFFF; border: 1px solid #E4D7CC; border-radius: 14px; }
        QLabel#quickNotebookConfirmTitle { color: #4B4641; font-size: 14px; font-weight: 700; }
        QLabel#quickNotebookConfirmMessage { color: #7D7169; font-size: 12px; }
        QFrame#quickNotebookConfirmOverlay QPushButton { min-width: 54px; min-height: 28px; padding: 5px 9px; border: 1px solid #DFD3C9; border-radius: 8px; background: #FFFFFF; color: #6F625A; }
        QFrame#quickNotebookConfirmOverlay QPushButton#quickNotebookDangerButton { background: #C96F64; color: #FFFFFF; border-color: #C96F64; }
        QLabel#quickNotebookHint { color: #81736A; font-size: 13px; }
        QFrame#quickNotebookFooter {
            background: #FFFDFA;
            border: none;
            border-top: 1px solid #EEE3DA;
            border-radius: 0 0 17px 17px;
        }
        QPushButton#quickNotebookDirectory { background: transparent; border: none; color: #81736A; }
        QLabel#quickNotebookPageCount { color: #81736A; font-size: 11px; }
        QToolButton { background: #FFFFFF; color: #7B6E66; border: 1px solid #E3D7CC; border-radius: 9px; }
        QToolButton:disabled { color: #C6BBB2; background: #FAF7F3; border-color: #EEE3DA; }
        QPushButton#quickNotebookNew { background: #D98663; color: white; border: 1px solid #D98663; border-radius: 9px; font-weight: 700; padding: 0 10px; }
        QScrollBar:vertical { background: transparent; width: 8px; margin: 2px 1px; }
        QScrollBar::handle:vertical { background: #D8C8BC; min-height: 28px; border-radius: 4px; }
        QScrollBar::handle:vertical:hover { background: #C9AD9E; }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; background: transparent; }
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
    """


__all__ = ["QuickNotebookWindow", "NotebookTypeTab", "place_notebook"]
