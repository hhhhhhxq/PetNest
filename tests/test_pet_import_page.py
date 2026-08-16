"""Tests for the unified pet import page."""

from __future__ import annotations

import json
from pathlib import Path

from petnest.core.package_loader import PackageLoader
from petnest.ui.pet_import_page import PetImportMode, PetImportPage
from petnest.ui.spritesheet_import_dialog import SpriteSheetImportDialog
from tests.test_package_validator import _write_package


def test_pet_import_page_switches_source_mode(qtbot: object, tmp_path: Path) -> None:
    page = PetImportPage([], tmp_path / "pets")
    qtbot.addWidget(page)

    page.select_mode(PetImportMode.SPRITESHEET)

    assert page.sprite_sheet_page.isVisibleTo(page)


def test_pet_import_page_embeds_original_spritesheet_dialog(qtbot: object, tmp_path: Path) -> None:
    page = PetImportPage([], tmp_path / "pets")
    qtbot.addWidget(page)

    page.select_mode(PetImportMode.SPRITESHEET)

    assert isinstance(page.sprite_sheet_dialog, SpriteSheetImportDialog)
    assert page.sprite_sheet_dialog.parentWidget() is page.sprite_sheet_page
    assert not page.sprite_sheet_dialog.isWindow()
    assert page.sprite_sheet_dialog.source_dropzone is not None
    assert page.sprite_sheet_dialog.manual_selection_panel is not None


def test_pet_import_page_previews_complete_pet_update(qtbot: object, tmp_path: Path) -> None:
    source = _write_package(tmp_path / "source")
    pets_root = tmp_path / "pets"
    package = PackageLoader().load(_write_package(pets_root / "test_pet"))
    page = PetImportPage([package], pets_root)
    qtbot.addWidget(page)

    page.load_source(source)

    assert page.source_summary_label.text()
    assert page.preserve_local_actions.isVisibleTo(page)
    assert not page.preserve_local_actions.isChecked()


def test_pet_import_page_imports_complete_package(qtbot: object, tmp_path: Path) -> None:
    source = _write_package(tmp_path / "source")
    pets_root = tmp_path / "pets"
    page = PetImportPage([], pets_root)
    qtbot.addWidget(page)
    page.load_source(source)

    page.import_selected()

    assert (pets_root / "test_pet" / "pet.json").is_file()
