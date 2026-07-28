"""以互斥播放模式编辑当前宠物的动作时长。"""

from __future__ import annotations

from PySide6.QtCore import QSignalBlocker, QSize, Qt, QTimer
from PySide6.QtGui import QCloseEvent, QIcon, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from petnest.models.pet_package import AnimationDefinition, PetPackage


_TRIGGER_TEXT = {
    "idle": "默认待机", "drag": "拖动宠物时", "click": "鼠标点击时", "drop": "结束拖动时",
    "error": "任务报错时", "waiting": "任务等待时", "working": "任务工作时",
    "hover": "鼠标移入时", "codex_running_left": "外部事件可触发",
    "bored": "系统长时间无输入时", "sleep": "系统无人操作更久时", "wake": "系统恢复输入时",
}


class AnimationEditorDialog(QDialog):
    """编辑会写入宠物包的逐帧时长；每个动作在两种编辑方式间二选一。"""

    def __init__(self, package: PetPackage, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"编辑动画时长 — {package.name}")
        self.resize(900, 620)
        self._package = package
        self._timelines = {action: _source_durations(definition) for action, definition in package.animations.items()}
        self._modes = {
            action: "per_frame" if definition.frame_durations_ms is not None else "total"
            for action, definition in package.animations.items()
        }
        self._changed_actions: set[str] = set()
        self._current_action: str | None = None
        self._loading = False
        self._duration_spins: list[QSpinBox] = []
        self._preview_pixmaps: dict[str, tuple[QPixmap, ...]] = {}
        self.preview_frame_index = 0
        self._preview_paused = False
        self.preview_timer = QTimer(self)
        self.preview_timer.timeout.connect(self._advance_preview)

        root = QVBoxLayout(self)
        root.addWidget(QLabel("选择一种编辑方式；保存后会写入 pet.json 并自动重载当前宠物。", self))
        self.action_table = QTableWidget(0, 5, self)
        self.action_table.setHorizontalHeaderLabels(("动作", "展示时机", "帧数", "当前方式", "实际总时长"))
        self.action_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.action_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.action_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.action_table.itemSelectionChanged.connect(self._load_selected_action)
        root.addWidget(self.action_table, 1)

        self.mode_status_label = QLabel("—", self)
        root.addWidget(self.mode_status_label)
        self.total_radio = QRadioButton("按总时长播放（保留原有帧间节奏）", self)
        self.per_frame_radio = QRadioButton("手动编辑每帧时长", self)
        self.mode_group = QButtonGroup(self)
        self.mode_group.addButton(self.total_radio)
        self.mode_group.addButton(self.per_frame_radio)
        self.total_radio.toggled.connect(self._mode_changed)
        self.per_frame_radio.toggled.connect(self._mode_changed)
        root.addWidget(self.total_radio)

        controls = QFormLayout()
        self.base_duration_label = QLabel("—", self)
        self.total_duration_spin = QSpinBox(self)
        self.total_duration_spin.setRange(1, 600_000)
        self.total_duration_spin.setSingleStep(50)
        self.total_duration_spin.setSuffix(" ms")
        self.total_duration_spin.valueChanged.connect(self._total_duration_changed)
        controls.addRow("基准时长", self.base_duration_label)
        controls.addRow("目标总时长", self.total_duration_spin)
        root.addLayout(controls)

        root.addWidget(self.per_frame_radio)
        editor_row = QHBoxLayout()
        self.frame_list = QListWidget(self)
        self.frame_list.setMinimumWidth(320)
        self.frame_list.setSpacing(4)
        self.frame_list.itemClicked.connect(self._select_preview_frame)
        editor_row.addWidget(self.frame_list, 1)

        preview_column = QVBoxLayout()
        preview_column.addWidget(QLabel("实时动作预览", self))
        self.preview_label = QLabel("暂无可预览的帧", self)
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setMinimumSize(300, 300)
        self.preview_label.setStyleSheet("background: #eef1f5; border: 1px solid #c6cbd3; border-radius: 8px;")
        preview_column.addWidget(self.preview_label, 1)
        self.preview_play_button = QPushButton("暂停预览", self)
        self.preview_play_button.clicked.connect(self._toggle_preview)
        preview_column.addWidget(self.preview_play_button)
        editor_row.addLayout(preview_column, 1)
        root.addLayout(editor_row, 2)
        self.duration_table = self.frame_list

        self.apply_hint_label = QLabel("时长会随宠物文件夹一起分享。", self)
        root.addWidget(self.apply_hint_label)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self._populate_action_table()
        if self.action_table.rowCount():
            self.action_table.selectRow(0)

    def updated_frame_durations(self) -> dict[str, tuple[int, ...]]:
        """仅返回本次编辑实际修改过的动作，避免无谓重写其余配置。"""
        return {action: self._timelines[action] for action in self._changed_actions}

    def applied_summary(self) -> str:
        if self._current_action is None:
            return ""
        return f"已保存：{self._current_action}，{_mode_label(self._modes[self._current_action])}，{sum(self._timelines[self._current_action])} ms"

    def _populate_action_table(self) -> None:
        self.action_table.setRowCount(len(self._package.animations))
        for row, (action, definition) in enumerate(self._package.animations.items()):
            values = (
                action, _TRIGGER_TEXT.get(action, "自定义动作"), str(len(definition.frames)),
                _mode_label(self._modes[action]), f"{sum(self._timelines[action])} ms",
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, action)
                self.action_table.setItem(row, column, item)

    def _load_selected_action(self) -> None:
        items = self.action_table.selectedItems()
        if not items:
            return
        action = str(self.action_table.item(items[0].row(), 0).data(Qt.ItemDataRole.UserRole))
        self._current_action = action
        definition = self._package.animations[action]
        self._loading = True
        try:
            with QSignalBlocker(self.total_radio), QSignalBlocker(self.per_frame_radio), QSignalBlocker(self.total_duration_spin):
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
        self._changed_actions.add(action)
        self._update_mode_widgets()
        self._populate_action_table()

    def _update_mode_widgets(self) -> None:
        total_mode = self.total_radio.isChecked()
        self.total_duration_spin.setEnabled(total_mode)
        self.base_duration_label.setVisible(total_mode)
        self.frame_list.setVisible(not total_mode)
        self.mode_status_label.setText(
            "当前方式：按总时长播放（仅缩放原有节奏）" if total_mode else "当前方式：手动逐帧播放（忽略总时长缩放）"
        )

    def _populate_frame_list(self, action: str) -> None:
        self.frame_list.clear()
        self._duration_spins.clear()
        for index, (path, duration) in enumerate(zip(self._package.animations[action].frames, self._timelines[action], strict=True)):
            pixmap = self._pixmaps_for(action)[index]
            item = QListWidgetItem(QIcon(pixmap), "")
            item.setData(Qt.ItemDataRole.UserRole, index)
            item.setSizeHint(QSize(0, 84))
            row = QWidget(self.frame_list)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(6, 4, 6, 4)
            thumbnail = QLabel(row)
            thumbnail.setPixmap(pixmap.scaled(72, 72, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            thumbnail.setFixedSize(76, 76)
            thumbnail.setAlignment(Qt.AlignmentFlag.AlignCenter)
            row_layout.addWidget(thumbnail)
            row_layout.addWidget(QLabel(f"第 {index + 1} 帧", row))
            spin = QSpinBox(row)
            spin.setRange(1, 60_000)
            spin.setValue(duration)
            spin.valueChanged.connect(self._duration_changed)
            spin.setSuffix(" ms")
            row_layout.addWidget(spin)
            self._duration_spins.append(spin)
            self.frame_list.addItem(item)
            self.frame_list.setItemWidget(item, row)

    def _total_duration_changed(self, total_duration: int) -> None:
        if self._loading or self._current_action is None or not self.total_radio.isChecked():
            return
        action = self._current_action
        self._timelines[action] = _scaled_timeline(self._timelines[action], total_duration)
        self._changed_actions.add(action)
        self._populate_frame_list(action)
        self._populate_action_table()
        self._restart_preview()

    def _duration_changed(self, _value: int) -> None:
        if self._loading or self._current_action is None or not self.per_frame_radio.isChecked():
            return
        action = self._current_action
        self._timelines[action] = self._table_durations()
        self._changed_actions.add(action)
        self._populate_action_table()
        self._restart_preview()

    def _table_durations(self) -> tuple[int, ...]:
        return tuple(spin.value() for spin in self._duration_spins)

    def _pixmaps_for(self, action: str) -> tuple[QPixmap, ...]:
        cached = self._preview_pixmaps.get(action)
        if cached is None:
            cached = tuple(QPixmap(str(path)) for path in self._package.animations[action].frames)
            self._preview_pixmaps[action] = cached
        return cached

    def _restart_preview(self) -> None:
        if self._current_action is None:
            return
        self.preview_frame_index = 0
        self._preview_paused = False
        self.preview_play_button.setText("暂停预览")
        self._render_preview()
        self.preview_timer.start(self._timelines[self._current_action][0])

    def _advance_preview(self) -> None:
        if self._current_action is None:
            return
        self.preview_frame_index = (self.preview_frame_index + 1) % len(self._timelines[self._current_action])
        self._render_preview()
        self.preview_timer.start(self._timelines[self._current_action][self.preview_frame_index])

    def _render_preview(self) -> None:
        if self._current_action is None:
            return
        pixmap = self._pixmaps_for(self._current_action)[self.preview_frame_index]
        if pixmap.isNull():
            self.preview_label.setText("无法读取此帧预览")
            self.preview_label.setPixmap(QPixmap())
        else:
            available = self.preview_label.contentsRect().size()
            self.preview_label.setText("")
            self.preview_label.setPixmap(
                pixmap.scaled(available, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            )
        if self.frame_list.count():
            self.frame_list.setCurrentRow(self.preview_frame_index)

    def _select_preview_frame(self, item: QListWidgetItem) -> None:
        self.preview_timer.stop()
        self._preview_paused = True
        self.preview_play_button.setText("播放预览")
        self.preview_frame_index = int(item.data(Qt.ItemDataRole.UserRole))
        self._render_preview()

    def _toggle_preview(self) -> None:
        if self._current_action is None:
            return
        if self._preview_paused:
            self._preview_paused = False
            self.preview_play_button.setText("暂停预览")
            self.preview_timer.start(self._timelines[self._current_action][self.preview_frame_index])
        else:
            self.preview_timer.stop()
            self._preview_paused = True
            self.preview_play_button.setText("播放预览")

    def closeEvent(self, event: QCloseEvent) -> None:
        self.preview_timer.stop()
        self._preview_pixmaps.clear()
        super().closeEvent(event)


def _source_durations(definition: AnimationDefinition) -> tuple[int, ...]:
    return definition.frame_durations_ms or tuple(round(1000 / definition.fps) for _ in definition.frames)


def _scaled_timeline(source: tuple[int, ...], target_total: int) -> tuple[int, ...]:
    target_total = max(len(source), target_total)
    source_total = sum(source)
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
