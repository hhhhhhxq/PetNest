"""本地精灵图导入对话框的规则提示与导入行为测试。"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tests.test_spritesheet_importer import _spritesheet
from petnest.ui.spritesheet_import_dialog import SpriteSheetImportDialog


def test_dialog_explains_local_only_format_and_default_mapping(qtbot: object, tmp_path: Path) -> None:
    dialog = SpriteSheetImportDialog(tmp_path / "pets")
    qtbot.addWidget(dialog)

    rules = dialog.rules_label.text()
    assert "不上传" in rules
    assert "1536 × 1872" in rules
    assert "running-right → drag" in rules


def test_dialog_imports_selected_local_spritesheet(qtbot: object, tmp_path: Path) -> None:
    source = _spritesheet(tmp_path / "cat.png")
    dialog = SpriteSheetImportDialog(tmp_path / "pets")
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.source_input.setText(str(source))
    dialog.pet_id_input.setText("dialog_cat")

    dialog.import_selected()

    assert dialog.imported_result is not None
    assert dialog.imported_result.package_id == "dialog_cat"
    assert (tmp_path / "pets" / "dialog_cat" / "pet.json").is_file()


def test_manual_mode_alone_shows_thumbnail_frame_selection(qtbot: object, tmp_path: Path) -> None:
    source = _spritesheet(tmp_path / "cat.png")
    dialog = SpriteSheetImportDialog(tmp_path / "pets")
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.source_input.setText(str(source))

    assert dialog.auto_skip_radio.isChecked()
    assert dialog.manual_selection_panel.isHidden()
    dialog.manual_select_radio.click()

    assert dialog.manual_selection_panel.isVisible()
    assert dialog.action_list.count() == 9
