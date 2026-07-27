"""第一阶段需要的少量显示与交互设置对话框。"""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtWidgets import QCheckBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout

from petnest.models.settings import Settings


class SettingsDialog(QDialog):
    """编辑可由应用层持久化的 ``Settings``，不直接写磁盘。"""

    def __init__(self, settings: Settings, parent: QDialog | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("PetNest 设置")
        self._settings = settings
        layout = QFormLayout(self)
        self.scale_input = QDoubleSpinBox(self)
        self.scale_input.setRange(0.25, 2.0)
        self.scale_input.setSingleStep(0.05)
        self.scale_input.setValue(settings.scale)
        self.always_on_top_input = QCheckBox(self)
        self.always_on_top_input.setChecked(settings.always_on_top)
        self.mouse_interaction_input = QCheckBox(self)
        self.mouse_interaction_input.setChecked(settings.mouse_interaction_enabled)
        layout.addRow("缩放", self.scale_input)
        layout.addRow("始终置顶", self.always_on_top_input)
        layout.addRow("启用鼠标交互", self.mouse_interaction_input)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def updated_settings(self) -> Settings:
        """返回当前表单值，交由调用者决定何时持久化。"""
        return replace(
            self._settings,
            scale=self.scale_input.value(),
            always_on_top=self.always_on_top_input.isChecked(),
            mouse_interaction_enabled=self.mouse_interaction_input.isChecked(),
        )
