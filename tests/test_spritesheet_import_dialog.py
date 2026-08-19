"""本地精灵图导入对话框的规则提示与导入行为测试。"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
from PySide6.QtGui import QDropEvent
from PySide6.QtWidgets import QDialog, QMessageBox

from tests.test_spritesheet_importer import _spritesheet
from petnest.ui.spritesheet_import_content import SpriteSheetImportContent
from petnest.ui.spritesheet_import_dialog import SpriteSheetImportDialog


def test_dialog_explains_local_only_format_and_default_mapping(qtbot: object, tmp_path: Path) -> None:
    dialog = SpriteSheetImportDialog(tmp_path / "pets")
    qtbot.addWidget(dialog)

    assert isinstance(dialog.content, SpriteSheetImportContent)
    rules = dialog.rules_label.text()
    assert "不上传" in rules
    assert "1536 × 1872" in rules
    assert "WebP" in rules
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


def test_dialog_uses_one_scrollable_content_area_for_manual_mode(qtbot: object, tmp_path: Path) -> None:
    dialog = SpriteSheetImportDialog(tmp_path / "pets")
    qtbot.addWidget(dialog)

    scroll = dialog.findChild(__import__("PySide6").QtWidgets.QScrollArea, "spritesheetContentScroll")

    assert scroll is not None
    assert scroll.widget() is dialog.content_container
    assert dialog.initial_content.parentWidget() is dialog.content_container
    assert dialog.manual_selection_panel.parentWidget() is dialog.content_container
    assert scroll.widgetResizable()
    assert scroll.verticalScrollBarPolicy() == __import__("PySide6").QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded


def test_dialog_initial_height_respects_available_screen_height(qtbot: object, tmp_path: Path) -> None:
    dialog = SpriteSheetImportDialog(tmp_path / "pets")
    qtbot.addWidget(dialog)

    dialog._fit_initial_height(available_height=720)

    assert dialog.height() <= max(dialog.minimumHeight(), 720 - 40)


def test_dialog_initial_height_fits_a_short_screen(qtbot: object, tmp_path: Path) -> None:
    dialog = SpriteSheetImportDialog(tmp_path / "pets")
    qtbot.addWidget(dialog)

    dialog._fit_initial_height(available_height=600)

    assert dialog.height() <= 560
    assert dialog.minimumHeight() <= 560


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


def test_dialog_accepts_a_local_webp_dropped_on_the_source_zone(qtbot: object, tmp_path: Path) -> None:
    source = _spritesheet(tmp_path / "dropped.webp")
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


def test_dialog_warns_without_accepting_when_required_fields_are_missing(
    qtbot: object, tmp_path: Path, monkeypatch: object
) -> None:
    dialog = SpriteSheetImportDialog(tmp_path / "pets")
    qtbot.addWidget(dialog)
    dialog.pet_id_input.setText("draft_cat")
    warnings: list[tuple[str, str]] = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda _parent, title, message: warnings.append((title, message)),
    )

    dialog.import_selected()

    assert warnings == [("无法导入", "请选择 PNG 或 WebP 文件并填写宠物 ID。")]
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert dialog.pet_id_input.text() == "draft_cat"


def test_dialog_warns_and_preserves_form_when_importer_rejects_png(
    qtbot: object, tmp_path: Path, monkeypatch: object
) -> None:
    source = tmp_path / "invalid.png"
    source.write_bytes(b"not a PNG")
    dialog = SpriteSheetImportDialog(tmp_path / "pets")
    qtbot.addWidget(dialog)
    dialog.source_input.setText(str(source))
    dialog.pet_id_input.setText("invalid_cat")
    warnings: list[tuple[str, str]] = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda _parent, title, message: warnings.append((title, message)),
    )

    dialog.import_selected()

    assert len(warnings) == 1
    assert warnings[0][0] == "无法导入"
    assert "无法读取精灵图" in warnings[0][1]
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert dialog.source_input.text() == str(source)
    assert dialog.pet_id_input.text() == "invalid_cat"
