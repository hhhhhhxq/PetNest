"""可复用精灵图导入内容组件的行为测试。"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QDialog, QFileDialog, QWidget

from petnest.ui.spritesheet_import_content import SpriteSheetImportContent
from petnest.ui.spritesheet_import_dialog import SpriteSheetImportDialog
from tests.test_spritesheet_importer import _spritesheet


def test_content_imports_without_owning_a_dialog(qtbot: object, tmp_path: Path) -> None:
    source = _spritesheet(tmp_path / "cat.png")
    host = QWidget()
    qtbot.addWidget(host)
    content = SpriteSheetImportContent(tmp_path / "pets", show_source_picker=False, parent=host)
    content.set_source(source)
    content.pet_id_input.setText("content_cat")

    result = content.import_selected()

    assert "isWindow" not in SpriteSheetImportContent.__dict__
    assert content.parentWidget() is host
    assert content.window() is host
    assert not content.isWindow()
    assert not isinstance(content, QDialog)
    assert result is not None
    assert result.package_id == "content_cat"


def test_legacy_dialog_wraps_the_same_content(qtbot: object, tmp_path: Path) -> None:
    dialog = SpriteSheetImportDialog(tmp_path / "pets")
    qtbot.addWidget(dialog)

    assert isinstance(dialog.content, SpriteSheetImportContent)
    assert dialog.source_input is dialog.content.source_input
    assert dialog.manual_selection_panel is dialog.content.manual_selection_panel


def test_dirty_changed_emits_only_for_state_transitions(qtbot: object, tmp_path: Path) -> None:
    source = _spritesheet(tmp_path / "cat.png")
    host = QWidget()
    qtbot.addWidget(host)
    content = SpriteSheetImportContent(tmp_path / "pets", show_source_picker=False, parent=host)
    changes: list[bool] = []
    content.dirty_changed.connect(changes.append)

    assert changes == []
    content.set_source(source)
    assert changes == [True]

    content.name_input.setText("Cat")
    content.manual_select_radio.click()
    assert changes == [True]

    content.source_input.clear()
    content.pet_id_input.clear()
    content.name_input.clear()
    assert changes == [True]

    content.auto_skip_radio.click()
    assert changes == [True, False]


def test_hidden_source_picker_keeps_programmatic_inspection_chain(qtbot: object, tmp_path: Path) -> None:
    source = _spritesheet(tmp_path / "cat.png")
    host = QWidget()
    qtbot.addWidget(host)
    content = SpriteSheetImportContent(tmp_path / "pets", show_source_picker=False, parent=host)

    assert content.source_card.isHidden()
    content.set_source(source)

    assert content.action_list.count() == 9


def test_source_picker_offers_png_and_webp(
    qtbot: object,
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    host = QWidget()
    qtbot.addWidget(host)
    content = SpriteSheetImportContent(tmp_path / "pets", show_source_picker=True, parent=host)
    filters: list[str] = []

    def fake_picker(*args: object) -> tuple[str, str]:
        filters.append(str(args[-1]))
        return "", ""

    monkeypatch.setattr(QFileDialog, "getOpenFileName", fake_picker)

    content.choose_source()

    assert filters == ["精灵图 (*.png *.webp)"]
