"""以互斥播放模式编辑当前宠物的动作时长。"""

from __future__ import annotations

from collections.abc import Mapping

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QRadioButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from petnest.models.pet_package import AnimationDefinition, PetPackage
from petnest.models.settings import AnimationOverride


_TRIGGER_TEXT = {
    "idle": "默认待机", "drag": "拖动宠物时", "click": "鼠标点击时", "drop": "结束拖动时",
    "error": "任务报错时", "waiting": "任务等待时", "working": "任务工作时",
    "hover": "鼠标移入时", "codex_running_left": "外部事件可触发",
    "bored": "系统长时间无输入时", "sleep": "系统无人操作更久时", "wake": "系统恢复输入时",
}


class AnimationEditorDialog(QDialog):
    """编辑本地覆盖；每个动作在总时长和逐帧模式间二选一。"""

    def __init__(self, package: PetPackage, overrides: Mapping[str, AnimationOverride], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"编辑动画时长 — {package.name}")
        self.resize(720, 560)
        self._package = package
        self._overrides = dict(overrides)
        self._current_action: str | None = None
        self._loading = False

        root = QVBoxLayout(self)
        root.addWidget(QLabel("选择一种播放方式；保存后会自动应用到当前宠物。", self))
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
        self.duration_table = QTableWidget(0, 2, self)
        self.duration_table.setHorizontalHeaderLabels(("帧", "时长（毫秒）"))
        root.addWidget(self.duration_table)

        self.apply_hint_label = QLabel("保存后会自动重载当前宠物。", self)
        root.addWidget(self.apply_hint_label)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self._populate_action_table()
        if self.action_table.rowCount():
            self.action_table.selectRow(0)

    def updated_overrides(self) -> dict[str, AnimationOverride]:
        return dict(self._overrides)

    def applied_summary(self) -> str:
        if self._current_action is None:
            return ""
        override = self._effective_override(self._current_action)
        return f"已应用：{self._current_action}，{_mode_label(override.mode)}，{_effective_total(self._package.animations[self._current_action], override)} ms"

    def _populate_action_table(self) -> None:
        self.action_table.setRowCount(len(self._package.animations))
        for row, (action, definition) in enumerate(self._package.animations.items()):
            override = self._effective_override(action)
            values = (
                action, _TRIGGER_TEXT.get(action, "自定义动作"), str(len(definition.frames)),
                _mode_label(override.mode), f"{_effective_total(definition, override)} ms",
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
        override = self._effective_override(action)
        self._loading = True
        try:
            with QSignalBlocker(self.total_radio), QSignalBlocker(self.per_frame_radio), QSignalBlocker(self.total_duration_spin):
                self.total_radio.setChecked(override.mode == "total")
                self.per_frame_radio.setChecked(override.mode == "per_frame")
                self.total_duration_spin.setValue(_effective_total(definition, override))
            self.base_duration_label.setText(f"{sum(_source_durations(definition))} ms")
            self._populate_duration_table(_manual_durations(definition, override))
            self._update_mode_widgets()
        finally:
            self._loading = False

    def _mode_changed(self, checked: bool) -> None:
        if self._loading or not checked or self._current_action is None:
            return
        action = self._current_action
        existing = self._effective_override(action)
        mode = "total" if self.total_radio.isChecked() else "per_frame"
        frames = existing.frame_durations_ms or _source_durations(self._package.animations[action])
        self._overrides[action] = AnimationOverride(existing.speed_multiplier, frames, mode)
        self._update_mode_widgets()
        self._populate_action_table()

    def _update_mode_widgets(self) -> None:
        total_mode = self.total_radio.isChecked()
        self.total_duration_spin.setEnabled(total_mode)
        self.base_duration_label.setVisible(total_mode)
        self.duration_table.setVisible(not total_mode)
        self.mode_status_label.setText(
            "当前方式：按总时长播放（仅缩放原有节奏）" if total_mode else "当前方式：手动逐帧播放（忽略总时长缩放）"
        )

    def _populate_duration_table(self, durations: tuple[int, ...]) -> None:
        self.duration_table.setRowCount(len(durations))
        for row, duration in enumerate(durations):
            self.duration_table.setItem(row, 0, QTableWidgetItem(str(row + 1)))
            spin = QSpinBox(self.duration_table)
            spin.setRange(1, 60_000)
            spin.setValue(duration)
            spin.valueChanged.connect(self._duration_changed)
            self.duration_table.setCellWidget(row, 1, spin)

    def _total_duration_changed(self, total_duration: int) -> None:
        if self._loading or self._current_action is None or not self.total_radio.isChecked():
            return
        action = self._current_action
        existing = self._effective_override(action)
        speed = sum(_source_durations(self._package.animations[action])) / total_duration
        self._overrides[action] = AnimationOverride(speed, existing.frame_durations_ms, "total")
        self._populate_action_table()

    def _duration_changed(self, _value: int) -> None:
        if self._loading or self._current_action is None or not self.per_frame_radio.isChecked():
            return
        action = self._current_action
        existing = self._effective_override(action)
        self._overrides[action] = AnimationOverride(1.0, self._table_durations(), "per_frame")
        self._populate_action_table()

    def _effective_override(self, action: str) -> AnimationOverride:
        return self._overrides.get(action, AnimationOverride())

    def _table_durations(self) -> tuple[int, ...]:
        return tuple(self.duration_table.cellWidget(row, 1).value() for row in range(self.duration_table.rowCount()))  # type: ignore[union-attr]


def _source_durations(definition: AnimationDefinition) -> tuple[int, ...]:
    return definition.frame_durations_ms or tuple(round(1000 / definition.fps) for _ in definition.frames)


def _manual_durations(definition: AnimationDefinition, override: AnimationOverride) -> tuple[int, ...]:
    if override.frame_durations_ms is not None and len(override.frame_durations_ms) == len(definition.frames):
        return override.frame_durations_ms
    return _source_durations(definition)


def _effective_total(definition: AnimationDefinition, override: AnimationOverride) -> int:
    durations = _manual_durations(definition, override) if override.mode == "per_frame" else _source_durations(definition)
    return round(sum(durations) / (1 if override.mode == "per_frame" else override.speed_multiplier))


def _mode_label(mode: str) -> str:
    return "总时长" if mode == "total" else "逐帧"
