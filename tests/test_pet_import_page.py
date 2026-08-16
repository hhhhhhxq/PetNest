"""Tests for the auto-detected pet import wizard."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PySide6.QtWidgets import QDialog, QMessageBox

from petnest.core.action_transfer import SourceKind
from petnest.core.package_loader import PackageLoader
from petnest.core.spritesheet_importer import SpriteSheetImporter
from petnest.ui.pet_import_page import PetImportPage, PetImportStep
from petnest.ui.spritesheet_import_content import SpriteSheetImportContent
from tests.test_package_validator import _write_package
from tests.test_spritesheet_importer import _spritesheet


def test_pet_import_page_auto_detects_png_and_keeps_one_window(qtbot: object, tmp_path: Path) -> None:
    source = _spritesheet(tmp_path / "cat.png")
    page = PetImportPage([], tmp_path / "pets")
    qtbot.addWidget(page)
    page.show()

    page.load_source(source)

    assert page.current_step() is PetImportStep.CONFIGURE
    assert page.source_kind_label.text() == "PNG 精灵图"
    assert isinstance(page.spritesheet_content, SpriteSheetImportContent)
    assert not page.findChildren(QDialog)


def test_pet_import_page_does_not_write_before_final_confirmation(qtbot: object, tmp_path: Path) -> None:
    source = _spritesheet(tmp_path / "cat.png")
    pets_root = tmp_path / "pets"
    page = PetImportPage([], pets_root)
    qtbot.addWidget(page)
    page.load_source(source)
    page.spritesheet_content.pet_id_input.setText("wizard_cat")

    page.trigger_primary()

    assert page.current_step() is PetImportStep.REVIEW
    assert not (pets_root / "wizard_cat").exists()
    page.trigger_primary()
    assert (pets_root / "wizard_cat" / "pet.json").is_file()


def test_pet_import_page_auto_detects_complete_pet_folder(qtbot: object, tmp_path: Path) -> None:
    source = _write_package(tmp_path / "source")
    page = PetImportPage([], tmp_path / "pets")
    qtbot.addWidget(page)

    page.load_source(source)

    assert page.current_step() is PetImportStep.CONFIGURE
    assert page.source_kind_label.text() == "完整宠物包"
    assert "test_pet" in page.package_summary_label.text()
    assert "新增宠物" in page.package_summary_label.text()
    assert page.source_summary_label is page.package_summary_label


def test_action_pack_source_stays_on_source_step_with_specific_guidance(qtbot: object, tmp_path: Path) -> None:
    action_pack = tmp_path / "action-pack"
    action_pack.mkdir()
    (action_pack / "petnest-action-pack.json").write_text("{}", encoding="utf-8")
    pets_root = tmp_path / "pets"
    page = PetImportPage([], pets_root)
    qtbot.addWidget(page)

    page.load_source(action_pack)

    assert page.current_step() is PetImportStep.SOURCE
    assert page.source_kind_label.text() == "识别失败"
    assert "动作导入页面" in page.footer_state().status
    assert not pets_root.exists()


def test_review_back_keeps_spritesheet_draft(qtbot: object, tmp_path: Path) -> None:
    source = _spritesheet(tmp_path / "cat.png")
    page = PetImportPage([], tmp_path / "pets")
    qtbot.addWidget(page)
    page.load_source(source)
    page.spritesheet_content.pet_id_input.setText("draft_cat")
    page.spritesheet_content.name_input.setText("草稿猫")
    page.spritesheet_content.manual_select_radio.click()

    page.trigger_primary()
    page.trigger_secondary()

    assert page.current_step() is PetImportStep.CONFIGURE
    assert page.spritesheet_content.pet_id_input.text() == "draft_cat"
    assert page.spritesheet_content.name_input.text() == "草稿猫"
    assert page.spritesheet_content.manual_select_radio.isChecked()


def test_replace_source_no_keeps_old_draft_and_yes_resets_it(
    qtbot: object, tmp_path: Path, monkeypatch: object
) -> None:
    old_source = _spritesheet(tmp_path / "old.png")
    new_source = _spritesheet(tmp_path / "new.png")
    page = PetImportPage([], tmp_path / "pets")
    qtbot.addWidget(page)
    page.load_source(old_source)
    page.spritesheet_content.pet_id_input.setText("custom_draft")
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *_args, **_kwargs: QMessageBox.StandardButton.No))

    page.replace_source(new_source)

    assert page.current_step() is PetImportStep.CONFIGURE
    assert page.spritesheet_content.source_input.text() == str(old_source)
    assert page.spritesheet_content.pet_id_input.text() == "custom_draft"

    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes))
    page.replace_source(new_source)

    assert page.spritesheet_content.source_input.text() == str(new_source)
    assert page.spritesheet_content.pet_id_input.text() == "new"
    assert page.spritesheet_content.name_input.text() == ""
    assert page.spritesheet_content.auto_skip_radio.isChecked()


def test_complete_package_replace_always_prompts_and_no_preserves_all_state(
    qtbot: object, tmp_path: Path, monkeypatch: object
) -> None:
    old_source = _write_package(tmp_path / "old")
    new_source = _write_package(tmp_path / "new", id="new_pet", name="New Pet")
    page = PetImportPage([], tmp_path / "pets")
    qtbot.addWidget(page)
    page.load_source(old_source)
    old_metadata = page._package_metadata
    old_summary = page.package_summary_label.text()
    questions: list[str] = []

    def answer_no(*_args: object, **_kwargs: object) -> QMessageBox.StandardButton:
        questions.append("asked")
        return QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, "question", staticmethod(answer_no))

    page.replace_source(new_source)

    assert questions == ["asked"]
    assert page.current_step() is PetImportStep.CONFIGURE
    assert page._source_path == old_source
    assert page._package_metadata is old_metadata
    assert page.package_summary_label.text() == old_summary
    assert not page.preserve_local_actions.isChecked()

    page.trigger_secondary()
    page.replace_source(new_source)

    assert questions == ["asked", "asked"]
    assert page.current_step() is PetImportStep.SOURCE
    assert page._source_path == old_source
    assert page._package_metadata is old_metadata
    assert page.package_summary_label.text() == old_summary


def test_confirmed_invalid_replacement_restores_old_draft_and_can_still_import(
    qtbot: object, tmp_path: Path, monkeypatch: object
) -> None:
    old_source = _write_package(tmp_path / "old")
    invalid_source = tmp_path / "invalid"
    invalid_source.mkdir()
    (invalid_source / "pet.json").write_text(json.dumps({"id": "broken"}), encoding="utf-8")
    pets_root = tmp_path / "pets"
    page = PetImportPage([], pets_root)
    qtbot.addWidget(page)
    page.load_source(old_source)
    old_metadata = page._package_metadata
    old_summary = page.package_summary_label.text()
    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes),
    )

    page.replace_source(invalid_source)

    assert page.current_step() is PetImportStep.CONFIGURE
    assert page._source_path == old_source
    assert page._package_metadata is old_metadata
    assert page.package_summary_label.text() == old_summary
    assert "无法读取来源" in page.footer_state().status

    page.trigger_primary()
    page.trigger_primary()

    assert (pets_root / "test_pet" / "pet.json").is_file()


def test_complete_pet_update_shows_preserve_option(qtbot: object, tmp_path: Path) -> None:
    source = _write_package(tmp_path / "source")
    pets_root = tmp_path / "pets"
    package = PackageLoader().load(_write_package(pets_root / "test_pet"))
    page = PetImportPage([package], pets_root)
    qtbot.addWidget(page)
    page.show()

    page.load_source(source)

    assert "更新现有宠物" in page.package_summary_label.text()
    assert page.preserve_local_actions.isVisibleTo(page)
    assert not page.preserve_local_actions.isChecked()


def test_complete_package_only_imports_from_review(qtbot: object, tmp_path: Path) -> None:
    source = _write_package(tmp_path / "source")
    pets_root = tmp_path / "pets"
    page = PetImportPage([], pets_root)
    qtbot.addWidget(page)
    page.load_source(source)

    page.trigger_primary()

    assert page.current_step() is PetImportStep.REVIEW
    assert "test_pet" in page.review_summary_label.text()
    assert not (pets_root / "test_pet").exists()
    page.trigger_primary()
    assert (pets_root / "test_pet" / "pet.json").is_file()


def test_complete_package_review_back_keeps_preserve_setting(qtbot: object, tmp_path: Path) -> None:
    source = _write_package(tmp_path / "source")
    pets_root = tmp_path / "pets"
    package = PackageLoader().load(_write_package(pets_root / "test_pet"))
    page = PetImportPage([package], pets_root)
    qtbot.addWidget(page)
    page.load_source(source)
    page.preserve_local_actions.setChecked(True)

    page.trigger_primary()
    page.trigger_secondary()

    assert page.current_step() is PetImportStep.CONFIGURE
    assert page.preserve_local_actions.isChecked()


def test_load_source_failure_is_transactional_for_existing_draft(
    qtbot: object, tmp_path: Path
) -> None:
    source = _write_package(tmp_path / "source")
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "pet.json").write_text(json.dumps({"id": "broken"}), encoding="utf-8")
    page = PetImportPage([], tmp_path / "pets")
    qtbot.addWidget(page)
    page.load_source(source)
    page.preserve_local_actions.setChecked(True)
    old_metadata = page._package_metadata
    old_summary = page.package_summary_label.text()

    page.load_source(bad)

    assert page.current_step() is PetImportStep.CONFIGURE
    assert page.source_kind_label.text() == "完整宠物包"
    assert page._source_path == source
    assert page._package_metadata is old_metadata
    assert page.package_summary_label.text() == old_summary
    assert "无法读取来源" in page.footer_state().status
    assert page.preserve_local_actions.isChecked()


@pytest.mark.parametrize(
    ("marker", "expected"),
    [
        ("petnest-action-pack.json", "动作导入页面"),
        ("manifest.json", "动作导入页面（旧版下班动画）"),
    ],
)
def test_non_pet_source_kinds_report_specific_destination(
    qtbot: object, tmp_path: Path, marker: str, expected: str
) -> None:
    source = tmp_path / marker.replace(".json", "")
    source.mkdir()
    (source / marker).write_text("{}", encoding="utf-8")
    page = PetImportPage([], tmp_path / "pets")
    qtbot.addWidget(page)

    page.load_source(source)

    assert page.current_step() is PetImportStep.SOURCE
    assert expected in page.footer_state().status


def test_spritesheet_directory_reports_single_png_guidance(qtbot: object, tmp_path: Path) -> None:
    source = tmp_path / "spritesheet-folder"
    source.mkdir()
    _spritesheet(source / "cat.png")
    page = PetImportPage([], tmp_path / "pets")
    qtbot.addWidget(page)

    page.load_source(source)

    assert page.current_step() is PetImportStep.SOURCE
    assert "导入宠物页面的 PNG 精灵图" in page.footer_state().status


def test_late_spritesheet_commit_error_restores_existing_png_draft(
    qtbot: object, tmp_path: Path, monkeypatch: object
) -> None:
    old_source = _spritesheet(tmp_path / "old.png")
    new_source = _spritesheet(tmp_path / "new.png")
    page = PetImportPage([], tmp_path / "pets")
    qtbot.addWidget(page)
    page.load_source(old_source)
    page.spritesheet_content.pet_id_input.setText("old_draft")
    page.spritesheet_content.name_input.setText("旧草稿")
    page.spritesheet_content.manual_select_radio.click()
    page.spritesheet_content._set_column_selected("idle", 0, False)
    page.trigger_primary()
    old_review = page.review_summary_label.text()
    old_selection = {
        action: set(columns) for action, columns in page.spritesheet_content._selected_columns.items()
    }
    original_inspect = SpriteSheetImporter.inspect
    calls = 0

    def inspect_then_fail(self: SpriteSheetImporter, source: Path):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("late inspect")
        return original_inspect(self, source)

    monkeypatch.setattr(SpriteSheetImporter, "inspect", inspect_then_fail)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes),
    )

    page.replace_source(new_source)

    assert calls == 2
    assert page.current_step() is PetImportStep.REVIEW
    assert page._source_path == old_source
    assert page._source_kind is SourceKind.SPRITESHEET
    assert page.spritesheet_content.source_input.text() == str(old_source)
    assert page.spritesheet_content.pet_id_input.text() == "old_draft"
    assert page.spritesheet_content.name_input.text() == "旧草稿"
    assert page.spritesheet_content.manual_select_radio.isChecked()
    assert page.spritesheet_content._selected_columns == old_selection
    assert page.review_summary_label.text() == old_review
    assert "late inspect" in page.footer_state().status


def test_late_spritesheet_commit_error_restores_existing_package_draft(
    qtbot: object, tmp_path: Path, monkeypatch: object
) -> None:
    old_source = _write_package(tmp_path / "old")
    new_source = _spritesheet(tmp_path / "new.png")
    pets_root = tmp_path / "pets"
    installed = PackageLoader().load(_write_package(pets_root / "test_pet"))
    page = PetImportPage([installed], pets_root)
    qtbot.addWidget(page)
    page.load_source(old_source)
    page.preserve_local_actions.setChecked(True)
    old_metadata = page._package_metadata
    old_summary = page.package_summary_label.text()
    original_inspect = SpriteSheetImporter.inspect
    calls = 0

    def inspect_then_fail(self: SpriteSheetImporter, source: Path):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("late inspect")
        return original_inspect(self, source)

    monkeypatch.setattr(SpriteSheetImporter, "inspect", inspect_then_fail)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes),
    )

    page.replace_source(new_source)

    assert calls == 2
    assert page.current_step() is PetImportStep.CONFIGURE
    assert page._source_path == old_source
    assert page._source_kind is SourceKind.PET_PACKAGE
    assert page._package_metadata is old_metadata
    assert page.package_summary_label.text() == old_summary
    assert page.preserve_local_actions.isChecked()
    assert "late inspect" in page.footer_state().status


def test_late_spritesheet_commit_error_leaves_first_import_empty(
    qtbot: object, tmp_path: Path, monkeypatch: object
) -> None:
    source = _spritesheet(tmp_path / "new.png")
    page = PetImportPage([], tmp_path / "pets")
    qtbot.addWidget(page)
    original_inspect = SpriteSheetImporter.inspect
    calls = 0

    def inspect_then_fail(self: SpriteSheetImporter, candidate: Path):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("late inspect")
        return original_inspect(self, candidate)

    monkeypatch.setattr(SpriteSheetImporter, "inspect", inspect_then_fail)

    page.load_source(source)

    assert calls == 2
    assert page.current_step() is PetImportStep.SOURCE
    assert page._source_path is None
    assert page._source_kind is None
    assert page._package_metadata is None
    assert page.spritesheet_content.source_input.text() == ""
    assert page.spritesheet_content.pet_id_input.text() == ""
    assert page.source_kind_label.text() == "识别失败"
    assert "late inspect" in page.footer_state().status


def test_rollback_stays_non_throwing_when_old_manual_spritesheet_was_deleted(
    qtbot: object, tmp_path: Path, monkeypatch: object
) -> None:
    old_source = _spritesheet(tmp_path / "old.png")
    new_source = _spritesheet(tmp_path / "new.png")
    page = PetImportPage([], tmp_path / "pets")
    qtbot.addWidget(page)
    page.load_source(old_source)
    page.spritesheet_content.pet_id_input.setText("deleted_draft")
    page.spritesheet_content.name_input.setText("已删除旧图")
    page.spritesheet_content.manual_select_radio.click()
    page.trigger_primary()
    old_source.unlink()
    original_inspect = SpriteSheetImporter.inspect
    calls = 0

    def inspect_then_fail(self: SpriteSheetImporter, source: Path):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("late inspect")
        return original_inspect(self, source)

    monkeypatch.setattr(SpriteSheetImporter, "inspect", inspect_then_fail)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes),
    )

    page.replace_source(new_source)

    assert calls == 2
    assert page.current_step() is PetImportStep.REVIEW
    assert page._source_path == old_source
    assert page._source_kind is SourceKind.SPRITESHEET
    assert page.spritesheet_content.source_input.text() == str(old_source)
    assert page.spritesheet_content.pet_id_input.text() == "deleted_draft"
    assert page.spritesheet_content.manual_select_radio.isChecked()
    assert "late inspect" in page.footer_state().status
