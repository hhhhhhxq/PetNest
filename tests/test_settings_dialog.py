"""设置窗口中鼠标样式表单的交互测试。"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTime
from PySide6.QtWidgets import QApplication

from petnest.models.settings import Settings
from petnest.ui.settings_dialog import SettingsDialog


def test_regular_settings_dialog_has_no_cursor_controls(qtbot, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    del app
    dialog = SettingsDialog(Settings(cursor_style_enabled=False))
    qtbot.addWidget(dialog)

    assert not hasattr(dialog, "cursor_style_enabled_input")


def test_settings_dialog_persists_remote_partner_toggle(qtbot) -> None:
    dialog = SettingsDialog(Settings(remote_interaction_enabled=True))
    qtbot.addWidget(dialog)

    dialog.remote_interaction_input.setChecked(False)

    assert dialog.updated_settings().remote_interaction_enabled is False


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


def test_settings_dialog_has_no_work_start_time_control(qtbot) -> None:
    dialog = SettingsDialog(Settings())
    qtbot.addWidget(dialog)

    assert not hasattr(dialog, "work_start_input")


def test_settings_dialog_uses_one_daily_work_end_time(qtbot) -> None:
    dialog = SettingsDialog(Settings(work_end_time="18:00"))
    qtbot.addWidget(dialog)

    dialog.work_end_input.setTime(QTime(20, 15))

    assert dialog.updated_settings().work_end_time == "20:15"
    assert not hasattr(dialog, "daily_work_inputs")
