"""本地精灵图导入对话框的规则提示与导入行为测试。"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
from PySide6.QtGui import QDropEvent

from tests.test_spritesheet_importer import _spritesheet
from petnest.ui.spritesheet_import_dialog import SpriteSheetImportDialog


def test_dialog_explains_local_only_format_and_default_mapping(qtbot: object, tmp_path: Path) -> None:
    dialog = SpriteSheetImportDialog(tmp_path / "pets")
    qtbot.addWidget(dialog)

    rules = dialog.rules_label.text()
    assert "不上传" in rules
    assert "1536 × 1872" in rules
    assert "running-right → drag" in rules
    assert dialog.findChild(__import__("PySide6").QtWidgets.QFrame, "windowShell") is not None
    assert dialog.findChild(__import__("PySide6").QtWidgets.QFrame, "stepBar") is not None
    assert dialog.findChild(__import__("PySide6").QtWidgets.QFrame, "sourceCard") is not None
    assert dialog.findChild(__import__("PySide6").QtWidgets.QFrame, "petInfoCard") is not None
    assert dialog.buttons.button(__import__("PySide6").QtWidgets.QDialogButtonBox.StandardButton.Cancel).text() == "取消"
    assert dialog.findChild(__import__("PySide6").QtWidgets.QFrame, "sourceDropzone") is not None
    assert dialog.findChildren(__import__("PySide6").QtWidgets.QFrame, "modeOption")


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
    assert dialog.findChild(__import__("PySide6").QtWidgets.QFrame, "manualActionCard") is not None
    assert dialog.findChild(__import__("PySide6").QtWidgets.QFrame, "manualFrameCard") is not None
    assert dialog.step_label.text() == "2  确认动作帧"
    assert "已选" in dialog.action_list.item(0).text()


def test_manual_mode_keeps_source_and_pet_details_available(qtbot: object, tmp_path: Path) -> None:
    dialog = SpriteSheetImportDialog(tmp_path / "pets")
    qtbot.addWidget(dialog)
    dialog.show()

    dialog.manual_select_radio.click()

    assert dialog.initial_content.isVisible()
    assert dialog.source_input.isVisible()
    assert dialog.pet_id_input.isVisible()
    assert dialog.manual_selection_panel.isVisible()


def test_dialog_accepts_a_local_png_dropped_on_the_source_zone(qtbot: object, tmp_path: Path) -> None:
    source = _spritesheet(tmp_path / "dropped.png")
    dialog = SpriteSheetImportDialog(tmp_path / "pets")
    qtbot.addWidget(dialog)

    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(source))])
    event = QDropEvent(
        QPointF(10, 10),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    dialog.source_dropzone.show()
    dialog.source_dropzone.dropEvent(event)

    assert Path(dialog.source_input.text()).resolve() == source.resolve()
