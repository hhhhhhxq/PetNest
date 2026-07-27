"""当前宠物的动作速度与逐帧时长本地编辑器。"""

from __future__ import annotations

from collections.abc import Mapping

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from petnest.models.pet_package import AnimationDefinition, PetPackage
from petnest.models.settings import AnimationOverride


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
}


class AnimationEditorDialog(QDialog):
    """编辑内存中的覆盖值，由应用在确认后保存到用户设置。"""

    def __init__(self, package: PetPackage, overrides: Mapping[str, AnimationOverride], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"编辑动画速度 — {package.name}")
        self.resize(720, 520)
        self._package = package
        self._overrides = dict(overrides)
        self._current_action: str | None = None
        self._loading = False

        root = QVBoxLayout(self)
        root.addWidget(QLabel("这些设置仅保存在本机，不会修改宠物文件。", self))
        self.action_table = QTableWidget(0, 5, self)
        self.action_table.setHorizontalHeaderLabels(("动作", "展示时机", "帧数", "总时长", "速度"))
        self.action_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.action_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.action_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.action_table.itemSelectionChanged.connect(self._load_selected_action)
        root.addWidget(self.action_table, 1)

        controls = QFormLayout()
        self.speed_spin = QDoubleSpinBox(self)
        self.speed_spin.setRange(0.25, 4.0)
        self.speed_spin.setSingleStep(0.05)
        self.speed_spin.setDecimals(2)
        self.speed_spin.setSuffix(" ×")
        self.speed_spin.valueChanged.connect(self._speed_changed)
        self.total_duration_label = QLabel("—", self)
        controls.addRow("播放速度", self.speed_spin)
        controls.addRow("当前总时长", self.total_duration_label)
        root.addLayout(controls)

        self.duration_table = QTableWidget(0, 2, self)
        self.duration_table.setHorizontalHeaderLabels(("帧", "时长（毫秒）"))
        self.duration_table.hide()
        self.advanced_checkbox = QCheckBox("逐帧时长（高级）", self)
        self.advanced_checkbox.toggled.connect(self.duration_table.setVisible)
        root.addWidget(self.advanced_checkbox)
        root.addWidget(self.duration_table)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self._populate_action_table()
        if self.action_table.rowCount():
            self.action_table.selectRow(0)

    def updated_overrides(self) -> dict[str, AnimationOverride]:
        """返回可直接写入当前宠物设置的动作覆盖副本。"""
        return dict(self._overrides)

    def _populate_action_table(self) -> None:
        self.action_table.setRowCount(len(self._package.animations))
        for row, (action, definition) in enumerate(self._package.animations.items()):
            override = self._overrides.get(action, AnimationOverride())
            durations = _durations(definition, override)
            total = sum(durations) / override.speed_multiplier
            values = (action, _TRIGGER_TEXT.get(action, "自定义动作"), str(len(definition.frames)), f"{round(total)} ms", f"{override.speed_multiplier:.2f} ×")
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
        override = self._overrides.get(action, AnimationOverride())
        self._loading = True
        try:
            with QSignalBlocker(self.speed_spin):
                self.speed_spin.setValue(override.speed_multiplier)
            self._populate_duration_table(_durations(definition, override))
            self._update_total_duration()
        finally:
            self._loading = False

    def _populate_duration_table(self, durations: tuple[int, ...]) -> None:
        self.duration_table.setRowCount(len(durations))
        for row, duration in enumerate(durations):
            self.duration_table.setItem(row, 0, QTableWidgetItem(str(row + 1)))
            spin = QSpinBox(self.duration_table)
            spin.setRange(1, 60_000)
            spin.setValue(duration)
            spin.valueChanged.connect(self._duration_changed)
            self.duration_table.setCellWidget(row, 1, spin)

    def _speed_changed(self, value: float) -> None:
        if self._loading or self._current_action is None:
            return
        self._store_current(float(value))
        self._update_total_duration()
        self._populate_action_table()

    def _duration_changed(self, _value: int) -> None:
        if self._loading or self._current_action is None:
            return
        self._store_current(self.speed_spin.value(), self._table_durations())
        self._update_total_duration()
        self._populate_action_table()

    def _store_current(self, speed: float, durations: tuple[int, ...] | None = None) -> None:
        assert self._current_action is not None
        existing = self._overrides.get(self._current_action, AnimationOverride())
        self._overrides[self._current_action] = AnimationOverride(speed, existing.frame_durations_ms if durations is None else durations)

    def _table_durations(self) -> tuple[int, ...]:
        return tuple(self.duration_table.cellWidget(row, 1).value() for row in range(self.duration_table.rowCount()))  # type: ignore[union-attr]

    def _update_total_duration(self) -> None:
        if self._current_action is None:
            return
        definition = self._package.animations[self._current_action]
        override = self._overrides.get(self._current_action, AnimationOverride())
        total = round(sum(_durations(definition, override)) / override.speed_multiplier)
        self.total_duration_label.setText(f"{total} ms")


def _durations(definition: AnimationDefinition, override: AnimationOverride) -> tuple[int, ...]:
    if override.frame_durations_ms is not None and len(override.frame_durations_ms) == len(definition.frames):
        return override.frame_durations_ms
    if definition.frame_durations_ms is not None:
        return definition.frame_durations_ms
    return tuple(round(1000 / definition.fps) for _ in definition.frames)
