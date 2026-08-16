"""可复用的动作时间编辑内容组件。

此组件只负责编辑动作草稿，不创建窗口、不写入宠物包文件，也不处理保存
按钮。需要对话框或页面外壳的调用方可以直接组合它，并通过
``updated_frame_durations`` 取得本次编辑的时长覆盖。
"""

from __future__ import annotations

from PySide6.QtCore import QSignalBlocker, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPalette, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QRadioButton,
    QSizePolicy,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from petnest.models.pet_package import AnimationDefinition, PetPackage
from petnest.ui.animation_preview_widget import AnimationPreviewWidget
from petnest.ui.theme import COLORS


_TRIGGER_TEXT = {
    "idle": "默认待机",
    "drag": "拖动宠物时",
    "click": "鼠标点击时",
    "drop": "结束拖动时",
    "error": "任务报错时",
    "waiting": "任务等待时",
    "working": "任务工作时",
    "hover": "鼠标移入时",
    "codex_running_left": "外部事件可触发",
    "bored": "系统长时间无输入时",
    "sleep": "系统无人操作更久时",
    "wake": "系统恢复输入时",
    "work_finish_walk": "全屏下班提醒 · 走路循环",
    "work_finish_lie_down": "全屏下班提醒 · 躺下过渡",
}
_PREVIEW_HIGHLIGHT_STYLE = (
    f"background: {COLORS['accent_soft']}; border: 1px solid {COLORS['accent']}; border-radius: 8px;"
)


class AnimationTimingEditor(QWidget):
    """编辑动作的总时长或逐帧时长，并提供实时预览。"""

    dirty_changed = Signal(bool)

    def __init__(self, package: PetPackage, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("animationTimingEditor")
        self._package = package
        self._initial_timelines = {
            name: _source_durations(definition)
            for name, definition in package.animations.items()
        }
        self._timelines = dict(self._initial_timelines)
        self._initial_modes = {
            name: ("per_frame" if definition.frame_durations_ms else "total")
            for name, definition in package.animations.items()
        }
        self._modes = dict(self._initial_modes)
        self._changed_actions: set[str] = set()
        self._current_action: str | None = None
        self._loading = False
        self._duration_spins: list[QSpinBox] = []
        self._preview_pixmaps: dict[str, tuple[QPixmap, ...]] = {}
        self._highlighted_frame_index: int | None = None

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(14)

        self.action_card = QFrame(self)
        self.action_card.setObjectName("settingsCard")
        self.action_card.setMinimumWidth(450)
        action_card_layout = QVBoxLayout(self.action_card)
        action_card_layout.setContentsMargins(14, 12, 14, 12)
        action_card_layout.addWidget(QLabel("动作列表", self.action_card))
        self.action_table = QTableWidget(0, 5, self.action_card)
        self.action_table.setObjectName("animationActionTable")
        self.action_table.setHorizontalHeaderLabels(("动作", "展示时机", "帧数", "当前方式", "实际总时长"))
        self.action_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.action_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.action_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.action_table.horizontalHeader().setVisible(False)
        self.action_table.verticalHeader().setVisible(False)
        self.action_table.setShowGrid(False)
        action_palette = self.action_table.palette()
        for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive):
            action_palette.setColor(group, QPalette.ColorRole.Highlight, QColor(COLORS["accent_soft"]))
            action_palette.setColor(group, QPalette.ColorRole.HighlightedText, QColor(COLORS["accent"]))
        self.action_table.setPalette(action_palette)
        for column in (2, 3, 4):
            self.action_table.setColumnHidden(column, True)
        action_header = self.action_table.horizontalHeader()
        action_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        action_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.action_table.setWordWrap(True)
        self.action_table.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.action_table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.action_table.itemSelectionChanged.connect(self._load_selected_action)
        action_card_layout.addWidget(self.action_table, 1)

        self.editor_card = QFrame(self)
        self.editor_card.setObjectName("settingsCard")
        editor_card_layout = QVBoxLayout(self.editor_card)
        editor_card_layout.setContentsMargins(14, 12, 14, 12)
        self.editor_heading_label = QLabel("选择动作", self.editor_card)
        self.editor_heading_label.setStyleSheet("font-size: 17px; font-weight: 700;")
        editor_card_layout.addWidget(self.editor_heading_label)
        self.editor_description_label = QLabel("选择一个动作查看并调整播放节奏", self.editor_card)
        self.editor_description_label.setObjectName("mutedLabel")
        editor_card_layout.addWidget(self.editor_description_label)

        self.mode_status_label = QLabel("—", self.editor_card)
        self.mode_status_label.setObjectName("mutedLabel")
        editor_card_layout.addWidget(self.mode_status_label)
        self.total_radio = QRadioButton("按总时长", self.editor_card)
        self.per_frame_radio = QRadioButton("逐帧编辑", self.editor_card)
        self.mode_group = QButtonGroup(self)
        self.mode_group.addButton(self.total_radio)
        self.mode_group.addButton(self.per_frame_radio)
        self.total_radio.toggled.connect(self._mode_changed)
        self.per_frame_radio.toggled.connect(self._mode_changed)
        mode_switch = QFrame(self.editor_card)
        mode_switch.setObjectName("modeSwitch")
        mode_switch_layout = QHBoxLayout(mode_switch)
        mode_switch_layout.setContentsMargins(6, 5, 6, 5)
        mode_switch_layout.setSpacing(6)
        mode_switch_layout.addWidget(self.total_radio, 1)
        mode_switch_layout.addWidget(self.per_frame_radio, 1)
        editor_card_layout.addWidget(mode_switch)

        self.mode_explanation_card = QFrame(self.editor_card)
        self.mode_explanation_card.setObjectName("modeExplanationCard")
        explanation_layout = QVBoxLayout(self.mode_explanation_card)
        explanation_layout.setContentsMargins(14, 10, 14, 10)
        self.mode_explanation_title = QLabel("编辑方式", self.mode_explanation_card)
        self.mode_explanation_title.setStyleSheet("font-weight: 700;")
        explanation_layout.addWidget(self.mode_explanation_title)
        self.mode_explanation_label = QLabel("保持原有帧间比例，统一缩放节奏", self.mode_explanation_card)
        self.mode_explanation_label.setObjectName("mutedLabel")
        explanation_layout.addWidget(self.mode_explanation_label)
        editor_card_layout.addWidget(self.mode_explanation_card)

        controls = QFormLayout()
        self.base_duration_label = QLabel("—", self.editor_card)
        self.total_duration_spin = QSpinBox(self.editor_card)
        self.total_duration_spin.setRange(1, 600_000)
        self.total_duration_spin.setSingleStep(50)
        self.total_duration_spin.setSuffix(" ms")
        self.total_duration_spin.valueChanged.connect(self._total_duration_changed)
        controls.addRow("基准时长", self.base_duration_label)
        controls.addRow("目标总时长", self.total_duration_spin)
        editor_card_layout.addLayout(controls)

        timeline_heading = QHBoxLayout()
        self.total_timeline_heading = QLabel("节奏分配预览", self.editor_card)
        self.total_timeline_heading.setStyleSheet("font-weight: 700;")
        timeline_heading.addWidget(self.total_timeline_heading)
        self.total_timeline_hint = QLabel("按原比例缩放", self.editor_card)
        self.total_timeline_hint.setObjectName("mutedLabel")
        timeline_heading.addWidget(self.total_timeline_hint)
        timeline_heading.addStretch(1)
        editor_card_layout.addLayout(timeline_heading)
        self.total_timeline = QFrame(self.editor_card)
        self.total_timeline.setObjectName("totalTimeline")
        self.total_timeline_layout = QHBoxLayout(self.total_timeline)
        self.total_timeline_layout.setContentsMargins(12, 12, 12, 12)
        self.total_timeline_layout.setSpacing(5)
        editor_card_layout.addWidget(self.total_timeline)

        self.frame_list = QListWidget(self.editor_card)
        self.frame_list.setMinimumWidth(320)
        self.frame_list.setObjectName("animationFrameList")
        self.frame_list.setSpacing(4)
        self.frame_list.itemClicked.connect(self._select_preview_frame)
        editor_card_layout.addWidget(self.frame_list, 1)
        self.duration_table = self.frame_list

        self.preview_card = QFrame(self)
        self.preview_card.setObjectName("previewCard")
        self.preview_card.setMinimumWidth(260)
        preview_card_layout = QVBoxLayout(self.preview_card)
        preview_card_layout.setContentsMargins(14, 14, 14, 14)
        preview_title = QLabel("实时动作预览", self.preview_card)
        preview_title.setStyleSheet("color: #B07962; font-size: 13px; font-weight: 700;")
        preview_card_layout.addWidget(preview_title)
        self.preview = AnimationPreviewWidget(self.preview_card)
        self.preview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.preview.preview_label.setMinimumSize(220, 300)
        self.preview.preview_label.setObjectName("animationPreviewChecker")
        self.preview.preview_label.setProperty("checkerboard", True)
        preview_card_layout.addWidget(self.preview, 1)
        self.preview_label = self.preview.preview_label
        self.preview_frame_label = self.preview.preview_frame_label
        self.preview_play_button = self.preview.preview_play_button
        self.preview_timer = self.preview.preview_timer
        self.preview.frame_changed.connect(self._on_preview_frame_changed)

        root.addWidget(self.action_card, 4)
        root.addWidget(self.editor_card, 5)
        root.addWidget(self.preview_card, 3)

        self._populate_action_table()
        self._sync_responsive_preview()
        if self.action_table.rowCount():
            self.action_table.selectRow(0)

    @property
    def preview_frame_index(self) -> int:
        """当前预览帧索引，实时委托给可复用的预览组件。"""

        return self.preview.preview_frame_index

    @preview_frame_index.setter
    def preview_frame_index(self, value: int) -> None:
        index = int(value)
        if self.preview._pixmaps:
            index = max(0, min(index, len(self.preview._pixmaps) - 1))
        else:
            index = 0
        self.preview.preview_frame_index = index

    def is_dirty(self) -> bool:
        return bool(self._changed_actions)

    def updated_frame_durations(self) -> dict[str, tuple[int, ...]]:
        """只返回本次编辑实际改变过的动作。"""

        return {
            action: self._timelines[action]
            for action in self._package.animations
            if action in self._changed_actions
        }

    def applied_summary(self) -> str:
        if self._current_action is None:
            return ""
        return (
            f"已保存：{self._current_action}，{_mode_label(self._modes[self._current_action])}，"
            f"{sum(self._timelines[self._current_action])} ms"
        )

    def restore_current_action(self) -> None:
        """恢复当前动作的草稿，不影响其它动作的编辑状态。"""

        action = self._current_action
        if action is None or action not in self._initial_timelines:
            return
        self._timelines[action] = self._initial_timelines[action]
        self._modes[action] = self._initial_modes[action]
        self._update_changed_action(action)
        self._populate_action_table()
        self._load_selected_action()

    def mark_saved(self, package: PetPackage) -> None:
        """把当前草稿标记为新基线，并切换到最新宠物包。"""

        was_dirty = self.is_dirty()
        current_action = self._current_action
        current_timelines = dict(self._timelines)
        current_modes = dict(self._modes)
        self._package = package
        self._timelines = {
            name: (
                current_timelines[name]
                if name in current_timelines and len(current_timelines[name]) == len(definition.frames)
                else _source_durations(definition)
            )
            for name, definition in package.animations.items()
        }
        self._modes = {
            name: current_modes.get(
                name,
                "per_frame" if definition.frame_durations_ms else "total",
            )
            for name, definition in package.animations.items()
        }
        self._initial_timelines = dict(self._timelines)
        self._initial_modes = dict(self._modes)
        self._changed_actions.clear()
        self._preview_pixmaps.clear()
        self._populate_action_table()
        if current_action in package.animations:
            self._current_action = current_action
            self._load_selected_action()
        elif self.action_table.rowCount():
            self.action_table.selectRow(0)
        else:
            self._current_action = None
            self.stop_preview()
        if was_dirty:
            self.dirty_changed.emit(False)

    def stop_preview(self) -> None:
        """停止预览计时器，供外壳关闭时调用。"""

        self.preview.set_playing(False)

    def resizeEvent(self, event: object) -> None:  # noqa: N802 - Qt override signature.
        super().resizeEvent(event)  # type: ignore[arg-type]
        self._sync_responsive_preview()

    def _sync_responsive_preview(self) -> None:
        """窄窗口隐藏预览，优先保证动作列表和编辑控件完整可用。"""

        self.preview_card.setVisible(self.width() >= 1180)

    def _populate_action_table(self) -> None:
        selected_row = self.action_table.currentRow()
        with QSignalBlocker(self.action_table):
            self.action_table.setRowCount(len(self._package.animations))
            for row, (action, definition) in enumerate(self._package.animations.items()):
                values = (
                    action,
                    f"{_TRIGGER_TEXT.get(action, '自定义动作')} · {len(definition.frames)} 帧 · "
                    f"{sum(self._timelines.get(action, ()))} ms",
                    str(len(definition.frames)),
                    _mode_label(self._modes.get(action, "total")),
                    f"{sum(self._timelines.get(action, ()))} ms",
                )
                for column, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    if column == 0:
                        item.setData(Qt.ItemDataRole.UserRole, action)
                    self.action_table.setItem(row, column, item)
            if 0 <= selected_row < self.action_table.rowCount():
                self.action_table.selectRow(selected_row)

    def _load_selected_action(self) -> None:
        items = self.action_table.selectedItems()
        if not items:
            return
        action_item = self.action_table.item(items[0].row(), 0)
        if action_item is None:
            return
        action = str(action_item.data(Qt.ItemDataRole.UserRole))
        if action not in self._package.animations:
            return
        self._current_action = action
        definition = self._package.animations[action]
        self.editor_heading_label.setText(f"{action} · {_TRIGGER_TEXT.get(action, '自定义动作')}")
        self.editor_description_label.setText(
            f"共 {len(definition.frames)} 帧 · "
            f"{'只调整整体播放速度' if self._modes[action] == 'total' else '每帧单独设置播放时长'}"
        )
        self._loading = True
        try:
            with (
                QSignalBlocker(self.total_radio),
                QSignalBlocker(self.per_frame_radio),
                QSignalBlocker(self.total_duration_spin),
            ):
                self.total_radio.setChecked(self._modes[action] == "total")
                self.per_frame_radio.setChecked(self._modes[action] == "per_frame")
                self.total_duration_spin.setValue(sum(self._timelines[action]))
            self.base_duration_label.setText(f"{sum(_source_durations(definition))} ms")
            self._populate_frame_list(action)
            self._update_mode_widgets()
        finally:
            self._loading = False
        self._restart_preview()

    def _mode_changed(self, checked: bool) -> None:
        if self._loading or not checked or self._current_action is None:
            return
        action = self._current_action
        mode = "total" if self.total_radio.isChecked() else "per_frame"
        self._modes[action] = mode
        self._update_changed_action(action)
        self._update_mode_widgets()
        self._populate_action_table()

    def _update_mode_widgets(self) -> None:
        total_mode = self.total_radio.isChecked()
        self.total_duration_spin.setEnabled(total_mode)
        self.base_duration_label.setVisible(total_mode)
        self.total_timeline.setVisible(total_mode)
        self.frame_list.setVisible(not total_mode)
        self._update_total_timeline()
        self.mode_status_label.setText(
            "当前方式：按总时长播放（仅缩放原有节奏）"
            if total_mode
            else "当前方式：手动逐帧播放（忽略总时长缩放）"
        )
        self.mode_explanation_label.setText(
            "保持原有帧间比例，统一缩放节奏"
            if total_mode
            else "每一帧独立控制，不会自动缩放其他帧"
        )
        self.total_timeline_hint.setText(
            f"按原比例缩放至 {sum(self._timelines.get(self._current_action, ())) / 1000:.2f} 秒"
            if self._current_action is not None
            else "按原比例缩放"
        )

    def _update_total_timeline(self) -> None:
        while self.total_timeline_layout.count():
            child = self.total_timeline_layout.takeAt(0)
            if child.widget() is not None:
                child.widget().deleteLater()
        if self._current_action is None:
            return
        durations = self._timelines.get(self._current_action, ())
        maximum = max(durations, default=1)
        for index, duration in enumerate(durations):
            bar = QFrame(self.total_timeline)
            bar.setObjectName("timelineSegment")
            bar.setMinimumWidth(max(14, round(92 * duration / maximum)))
            bar.setToolTip(f"第 {index + 1} 帧 · {duration} ms")
            bar.setStyleSheet(
                f"background: {COLORS['accent'] if index == 0 else COLORS['accent_soft']};"
                f"border: 1px solid {COLORS['accent']}; border-radius: 5px;"
            )
            self.total_timeline_layout.addWidget(bar, max(1, duration))
        self.total_timeline_layout.addStretch(1)

    def _populate_frame_list(self, action: str) -> None:
        self.frame_list.clear()
        self._duration_spins.clear()
        self._highlighted_frame_index = None
        definition = self._package.animations[action]
        durations = self._timelines.get(action, ())
        for index, path in enumerate(definition.frames):
            duration = durations[index] if index < len(durations) else 100
            pixmap = self._pixmaps_for(action)[index]
            item = QListWidgetItem(QIcon(pixmap), "")
            item.setData(Qt.ItemDataRole.UserRole, index)
            item.setSizeHint(QSize(0, 84))
            row = QWidget(self.frame_list)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(6, 4, 6, 4)
            thumbnail = QLabel(row)
            thumbnail.setPixmap(
                pixmap.scaled(72, 72, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            )
            thumbnail.setFixedSize(76, 76)
            thumbnail.setAlignment(Qt.AlignmentFlag.AlignCenter)
            row_layout.addWidget(thumbnail)
            row_layout.addWidget(QLabel(f"第 {index + 1} 帧", row))
            spin = QSpinBox(row)
            spin.setRange(1, 60_000)
            spin.setValue(duration)
            spin.setSuffix(" ms")
            spin.valueChanged.connect(self._duration_changed)
            row_layout.addWidget(spin)
            self._duration_spins.append(spin)
            self.frame_list.addItem(item)
            self.frame_list.setItemWidget(item, row)

    def _total_duration_changed(self, total_duration: int) -> None:
        if self._loading or self._current_action is None or not self.total_radio.isChecked():
            return
        action = self._current_action
        self._timelines[action] = _scaled_timeline(self._timelines.get(action, ()), total_duration)
        self._update_changed_action(action)
        self._populate_frame_list(action)
        self._populate_action_table()
        self._restart_preview()

    def _duration_changed(self, _value: int) -> None:
        if self._loading or self._current_action is None or not self.per_frame_radio.isChecked():
            return
        action = self._current_action
        self._timelines[action] = self._table_durations()
        self._update_changed_action(action)
        self._populate_action_table()
        self._restart_preview()

    def _table_durations(self) -> tuple[int, ...]:
        return tuple(spin.value() for spin in self._duration_spins)

    def _update_changed_action(self, action: str) -> None:
        before = self.is_dirty()
        differs = (
            self._timelines.get(action) != self._initial_timelines.get(action)
            or self._modes.get(action) != self._initial_modes.get(action)
        )
        if differs:
            self._changed_actions.add(action)
        else:
            self._changed_actions.discard(action)
        after = self.is_dirty()
        if before != after:
            self.dirty_changed.emit(after)

    def _pixmaps_for(self, action: str) -> tuple[QPixmap, ...]:
        cached = self._preview_pixmaps.get(action)
        if cached is None:
            cached = tuple(QPixmap(str(path)) for path in self._package.animations[action].frames)
            self._preview_pixmaps[action] = cached
        return cached

    def _restart_preview(self) -> None:
        if self._current_action is None or self._current_action not in self._package.animations:
            self.preview.clear()
            self._highlighted_frame_index = None
            return
        definition = self._package.animations[self._current_action]
        timeline = self._timelines.get(self._current_action, ())
        self.preview.set_frames(definition.frames, frame_durations_ms=timeline)
        self._set_preview_highlight()

    def _advance_preview(self) -> None:
        self.preview._advance_preview()

    def _on_preview_frame_changed(self, index: int) -> None:
        """同步真实计时器和手动推进时的帧列表高亮。"""

        if index < 0 or index >= self.frame_list.count():
            return
        self._set_preview_highlight()

    def _render_preview(self) -> None:
        self._set_preview_frame(self.preview.preview_frame_index)

    def _set_preview_frame(self, index: int) -> None:
        pixmaps = self.preview._pixmaps
        if not pixmaps:
            return
        bounded = max(0, min(int(index), len(pixmaps) - 1))
        self.preview.preview_frame_index = bounded
        self.preview._render()
        self._set_preview_highlight()

    def _set_preview_highlight(self) -> None:
        """只更新前后两行的视觉高亮，不改变列表选择或滚动位置。"""

        if self._highlighted_frame_index == self.preview_frame_index:
            if self.frame_list.count() == 0:
                self._highlighted_frame_index = None
            return
        self._set_frame_row_style(self._highlighted_frame_index, "")
        if 0 <= self.preview_frame_index < self.frame_list.count():
            self._set_frame_row_style(self.preview_frame_index, _PREVIEW_HIGHLIGHT_STYLE)
            self._highlighted_frame_index = self.preview_frame_index
        else:
            self._highlighted_frame_index = None

    def _set_frame_row_style(self, row: int | None, style: str) -> None:
        if row is None or row < 0 or row >= self.frame_list.count():
            return
        item_widget = self.frame_list.itemWidget(self.frame_list.item(row))
        if item_widget is not None:
            item_widget.setStyleSheet(style)

    def _select_preview_frame(self, item: QListWidgetItem) -> None:
        self.stop_preview()
        self._set_preview_frame(int(item.data(Qt.ItemDataRole.UserRole)))

    def _toggle_preview(self) -> None:
        if self._current_action is None:
            return
        self.preview.set_playing(not self.preview.preview_timer.isActive())

    def _cleanup_preview(self) -> None:
        """在内容组件或兼容外壳关闭时释放计时器和图片缓存。"""

        self.stop_preview()
        self._preview_pixmaps.clear()
        self.preview.clear()
        self._highlighted_frame_index = None

    def closeEvent(self, event: object) -> None:  # noqa: N802 - Qt override signature.
        self._cleanup_preview()
        super().closeEvent(event)  # type: ignore[arg-type]


def _source_durations(definition: AnimationDefinition) -> tuple[int, ...]:
    return definition.frame_durations_ms or tuple(round(1000 / definition.fps) for _ in definition.frames)


def _scaled_timeline(source: tuple[int, ...], target_total: int) -> tuple[int, ...]:
    if not source:
        return ()
    source_total = sum(source)
    if source_total <= 0:
        return (max(1, target_total // len(source)),) * len(source)
    target_total = max(len(source), int(target_total))
    durations = [max(1, round(duration * target_total / source_total)) for duration in source]
    difference = target_total - sum(durations)
    index = len(durations) - 1
    while difference:
        adjustment = 1 if difference > 0 else -1
        if durations[index] + adjustment > 0:
            durations[index] += adjustment
            difference -= adjustment
        index = (index - 1) % len(durations)
    return tuple(durations)


def _mode_label(mode: str) -> str:
    return "总时长" if mode == "total" else "逐帧"


__all__ = ["AnimationTimingEditor"]
