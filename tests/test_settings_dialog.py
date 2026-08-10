"""设置窗口中鼠标样式表单的交互测试。"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from petnest.models.settings import Settings
from petnest.ui.settings_dialog import SettingsDialog


def test_regular_settings_dialog_has_no_cursor_controls(qtbot, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    del app
    dialog = SettingsDialog(Settings(cursor_style_enabled=False))
    qtbot.addWidget(dialog)

    assert not hasattr(dialog, "cursor_style_enabled_input")
