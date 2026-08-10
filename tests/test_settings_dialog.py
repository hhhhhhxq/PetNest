"""设置窗口中鼠标样式表单的交互测试。"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from petnest.core.cursor_style_catalog import CursorStyle
from petnest.models.settings import Settings
from petnest.ui.settings_dialog import SettingsDialog


def _style(tmp_path: Path) -> CursorStyle:
    preview = tmp_path / "arrow.png"
    arrow = tmp_path / "arrow.cur"
    preview.write_bytes(b"preview")
    arrow.write_bytes(b"cursor")
    return CursorStyle("petnest-paw", "深灰肉垫", preview, arrow, (0, 0))


def test_cursor_style_controls_enable_cleanly_and_show_advanced_placeholders(qtbot, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    del app
    dialog = SettingsDialog(Settings(cursor_style_enabled=False), cursor_styles=[_style(tmp_path)])
    qtbot.addWidget(dialog)

    assert dialog.cursor_style_input.isEnabled() is False
    assert dialog.cursor_advanced_group.title() == "高级光标设置（暂未添加其它样式）"

    dialog.cursor_style_enabled_input.setChecked(True)

    assert dialog.cursor_style_input.isEnabled() is True
    assert dialog.updated_settings().cursor_style_id == "petnest-paw"
