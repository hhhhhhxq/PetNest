from __future__ import annotations

from pathlib import Path

from petnest.core.cursor_style_catalog import CursorStyle
from petnest.models.settings import Settings
from petnest.ui.cursor_style_dialog import CursorStyleDialog


def test_cursor_style_dialog_round_trips_selected_theme(qtbot, tmp_path: Path) -> None:
    preview = tmp_path / "arrow.png"
    arrow = tmp_path / "arrow.cur"
    preview.write_bytes(b"preview")
    arrow.write_bytes(b"cursor")
    style = CursorStyle("petnest-paw", "深灰肉垫", preview, arrow, (0, 0), (1, 0, 31, 32), {"arrow": arrow})
    dialog = CursorStyleDialog(Settings(), [style])
    qtbot.addWidget(dialog)

    dialog.cursor_style_enabled_input.setChecked(True)

    assert dialog.updated_settings().cursor_style_id == "petnest-paw"
