"""第一阶段需要的少量显示与交互设置对话框。"""

from __future__ import annotations

from dataclasses import replace
from collections.abc import Callable

from PySide6.QtCore import QTime
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QSpinBox,
    QTimeEdit,
    QPushButton,
    QWidget,
)

from petnest.models.settings import Settings


class SettingsDialog(QDialog):
    """编辑可由应用层持久化的 ``Settings``，不直接写磁盘。"""

    def __init__(
        self,
        settings: Settings,
        parent: QDialog | None = None,
        *,
        on_check_app_update: Callable[[], object] | None = None,
    ) -> None:
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
        self.mouse_follow_input = QCheckBox(self)
        self.mouse_follow_input.setChecked(settings.mouse_follow_enabled)
        self.mouse_follow_scale_input = QDoubleSpinBox(self)
        self.mouse_follow_scale_input.setRange(0.25, 1.0)
        self.mouse_follow_scale_input.setSingleStep(0.05)
        self.mouse_follow_scale_input.setDecimals(2)
        self.mouse_follow_scale_input.setSuffix(" 倍")
        self.mouse_follow_scale_input.setValue(settings.mouse_follow_scale)
        self.mouse_follow_input.toggled.connect(self.mouse_follow_scale_input.setEnabled)
        self.mouse_follow_scale_input.setEnabled(self.mouse_follow_input.isChecked())
        self.lan_interaction_input = QCheckBox(self)
        self.lan_interaction_input.setChecked(settings.lan_interaction_enabled)
        self.system_idle_input = QCheckBox(self)
        self.system_idle_input.setChecked(settings.system_idle_enabled)
        self.system_bored_input = QSpinBox(self)
        self.system_bored_input.setRange(1, 86_400)
        self.system_bored_input.setSuffix(" 秒")
        self.system_bored_input.setValue(settings.system_bored_seconds)
        self.system_sleep_input = QSpinBox(self)
        self.system_sleep_input.setRange(2, 86_400)
        self.system_sleep_input.setSuffix(" 秒")
        self.system_sleep_input.setValue(settings.system_sleep_seconds)
        self.work_countdown_input = QCheckBox(self)
        self.work_countdown_input.setChecked(settings.work_countdown_enabled)
        self.work_start_input = QTimeEdit(QTime.fromString(settings.work_start_time, "HH:mm"), self)
        self.work_start_input.setDisplayFormat("HH:mm")
        self.countdown_gap_input = QSpinBox(self)
        self.countdown_gap_input.setRange(0, 80)
        self.countdown_gap_input.setSuffix(" 像素")
        self.countdown_gap_input.setValue(settings.countdown_gap)
        self.countdown_width_input = QSpinBox(self)
        self.countdown_width_input.setRange(110, 420)
        self.countdown_width_input.setSuffix(" 像素")
        self.countdown_width_input.setValue(settings.countdown_width)
        self.countdown_height_input = QSpinBox(self)
        self.countdown_height_input.setRange(26, 100)
        self.countdown_height_input.setSuffix(" 像素")
        self.countdown_height_input.setValue(settings.countdown_height)
        self.countdown_theme_input = QComboBox(self)
        self.countdown_theme_input.addItem("A · 奶油爪爪", "cream")
        self.countdown_theme_input.addItem("B · 黑猫夜灯", "night")
        self.countdown_theme_input.addItem("C · 毛线便签", "yarn")
        theme_index = self.countdown_theme_input.findData(settings.countdown_theme)
        self.countdown_theme_input.setCurrentIndex(max(0, theme_index))
        self.daily_work_inputs: dict[str, tuple[QCheckBox, QTimeEdit]] = {}
        layout.addRow("缩放", self.scale_input)
        layout.addRow("始终置顶", self.always_on_top_input)
        layout.addRow("启用鼠标交互", self.mouse_interaction_input)
        layout.addRow("跟随鼠标", self.mouse_follow_input)
        layout.addRow("跟随时大小", self.mouse_follow_scale_input)
        layout.addRow("允许局域网互动", self.lan_interaction_input)
        layout.addRow("启用系统空闲动作", self.system_idle_input)
        layout.addRow("无操作后无聊", self.system_bored_input)
        layout.addRow("无操作后睡觉", self.system_sleep_input)
        layout.addRow("显示上下班倒计时", self.work_countdown_input)
        layout.addRow("上班时间", self.work_start_input)
        layout.addRow("倒计时与宠物间距", self.countdown_gap_input)
        layout.addRow("倒计时最小宽度", self.countdown_width_input)
        layout.addRow("倒计时卡片高度", self.countdown_height_input)
        layout.addRow("倒计时主题", self.countdown_theme_input)
        weekday_names = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")
        for index, name in enumerate(weekday_names):
            key = str(index)
            configured = settings.daily_work_end_times.get(key)
            row = QWidget(self)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            enabled_input = QCheckBox("上班", row)
            enabled_input.setChecked(configured is not None)
            end_input = QTimeEdit(QTime.fromString(configured or settings.work_end_time, "HH:mm"), row)
            end_input.setDisplayFormat("HH:mm")
            end_input.setEnabled(enabled_input.isChecked())
            enabled_input.toggled.connect(end_input.setEnabled)
            row_layout.addWidget(enabled_input)
            row_layout.addWidget(end_input)
            self.daily_work_inputs[key] = (enabled_input, end_input)
            layout.addRow(f"{name}下班", row)
        if on_check_app_update is not None:
            self.app_update_button = QPushButton("检查程序更新…", self)
            self.app_update_button.setToolTip("从 PetNest GitHub Releases 检查新的安装包")
            self.app_update_button.clicked.connect(on_check_app_update)
            layout.addRow("程序版本", self.app_update_button)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def updated_settings(self) -> Settings:
        """返回当前表单值，交由调用者决定何时持久化。"""
        daily_end_times = {
            key: end_input.time().toString("HH:mm") if enabled_input.isChecked() else None
            for key, (enabled_input, end_input) in self.daily_work_inputs.items()
        }
        legacy_end = next((value for value in daily_end_times.values() if value is not None), self._settings.work_end_time)
        return replace(
            self._settings,
            scale=self.scale_input.value(),
            always_on_top=self.always_on_top_input.isChecked(),
            mouse_interaction_enabled=self.mouse_interaction_input.isChecked(),
            mouse_follow_enabled=self.mouse_follow_input.isChecked(),
            mouse_follow_scale=self.mouse_follow_scale_input.value(),
            lan_interaction_enabled=self.lan_interaction_input.isChecked(),
            system_idle_enabled=self.system_idle_input.isChecked(),
            system_bored_seconds=self.system_bored_input.value(),
            system_sleep_seconds=max(self.system_sleep_input.value(), self.system_bored_input.value() + 1),
            work_countdown_enabled=self.work_countdown_input.isChecked(),
            work_start_time=self.work_start_input.time().toString("HH:mm"),
            work_end_time=legacy_end,
            daily_work_end_times=daily_end_times,
            countdown_gap=self.countdown_gap_input.value(),
            countdown_width=self.countdown_width_input.value(),
            countdown_height=self.countdown_height_input.value(),
            countdown_theme=str(self.countdown_theme_input.currentData()),
        )
