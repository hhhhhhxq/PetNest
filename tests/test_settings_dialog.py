"""设置窗口中鼠标样式表单的交互测试。"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from petnest.models.settings import Settings
from petnest.ui.settings_dialog import SettingsCenterDialog, SettingsDialog


def test_settings_dialog_is_the_shared_five_section_center(qtbot, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    del app
    dialog = SettingsDialog(Settings(cursor_style_enabled=False), initial_section="mouse_behavior")
    qtbot.addWidget(dialog)

    assert isinstance(dialog, SettingsCenterDialog)
    assert dialog.section_list.currentRow() == 1
    assert dialog.page_title.text() == "鼠标与行为"
    assert dialog.cursor_scale_slider.value() == 100


def test_settings_dialog_persists_remote_partner_toggle(qtbot) -> None:
    dialog = SettingsDialog(Settings(remote_interaction_enabled=True))
    qtbot.addWidget(dialog)

    dialog.remote_interaction_input.setChecked(False)

    assert dialog.updated_settings().remote_interaction_enabled is False


def test_mouse_follow_and_cursor_scale_controls_are_linked(qtbot) -> None:
    dialog = SettingsDialog(Settings(mouse_follow_enabled=True, cursor_style_enabled=True))
    qtbot.addWidget(dialog)

    dialog.mouse_follow_input.setChecked(False)
    assert not dialog.mouse_follow_scale_input.isEnabled()
    dialog.mouse_follow_input.setChecked(True)
    assert dialog.mouse_follow_scale_input.isEnabled()

    dialog.cursor_scale_slider.setValue(112)
    dialog.cursor_scale_slider.snap_to_node()
    assert dialog.cursor_scale_slider.value() in {80, 100, 125, 150}
    assert dialog.updated_settings().cursor_scale == dialog.cursor_scale_slider.value()


def test_workday_choice_is_shared_by_fixed_and_elastic_modes(qtbot) -> None:
    dialog = SettingsDialog(Settings(), initial_section="countdown")
    qtbot.addWidget(dialog)

    assert len(dialog.workday_inputs) == 7
    dialog.workday_inputs["5"].setChecked(True)
    dialog.schedule_mode_input.setCurrentIndex(dialog.schedule_mode_input.findData("elastic"))
    dialog.clock_in_start_input.setTime(__import__("PySide6").QtCore.QTime(9, 30))
    dialog.clock_in_end_input.setTime(__import__("PySide6").QtCore.QTime(10, 0))

    updated = dialog.updated_settings()
    assert updated.work_schedule_mode == "elastic"
    assert updated.daily_work_end_times["5"] is not None
    assert updated.daily_work_end_times["6"] is None
    assert updated.clock_in_start_time == "09:30"


def test_invalid_clock_in_window_disables_apply_without_extra_persistent_notice(qtbot) -> None:
    dialog = SettingsDialog(Settings(), initial_section="countdown")
    qtbot.addWidget(dialog)

    dialog.schedule_mode_input.setCurrentIndex(dialog.schedule_mode_input.findData("elastic"))
    dialog.clock_in_start_input.setTime(__import__("PySide6").QtCore.QTime(10, 0))
    dialog.clock_in_end_input.setTime(__import__("PySide6").QtCore.QTime(9, 30))

    assert not dialog.button_box.button(__import__("PySide6").QtWidgets.QDialogButtonBox.StandardButton.Ok).isEnabled()
    assert "必须早于" in dialog.schedule_error_label.text()


def test_application_update_entry_is_opt_in_for_platform_owner(qtbot) -> None:
    called: list[bool] = []
    dialog = SettingsDialog(Settings(), on_check_app_update=lambda: called.append(True))
    qtbot.addWidget(dialog)

    assert dialog.app_update_button.text() == "检查程序更新…"
    qtbot.mouseClick(dialog.app_update_button, __import__("PySide6").QtCore.Qt.MouseButton.LeftButton)
    assert called == [True]


def test_application_update_entry_is_absent_without_platform_support(qtbot) -> None:
    dialog = SettingsDialog(Settings())
    qtbot.addWidget(dialog)

    assert not hasattr(dialog, "app_update_button")
