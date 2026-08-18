"""Tests for the unified pet/action exchange dialog."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QMessageBox

from petnest.core.package_loader import PackageLoader
from petnest.ui.pet_action_exchange_dialog import PetActionExchangeDialog
from tests.test_package_validator import _write_package


def test_exchange_dialog_has_four_pages_and_single_shell_footer(qtbot: object, tmp_path: Path) -> None:
    package = PackageLoader().load(_write_package(tmp_path / "pet"))
    dialog = PetActionExchangeDialog([package], tmp_path / "pets")
    qtbot.addWidget(dialog)

    assert dialog.page_names() == ["导入宠物", "导入动作", "编辑动作", "导出动作"]
    assert dialog.primary_button.parentWidget() is dialog.window_shell
    assert dialog.secondary_button.parentWidget() is dialog.window_shell
    assert len(dialog.window_shell.findChildren(type(dialog.primary_button), "primaryButton")) == 1


def test_exchange_dialog_defaults_pet_selectors_to_current_pet(qtbot: object, tmp_path: Path) -> None:
    first = PackageLoader().load(_write_package(tmp_path / "first", id="first"))
    second = PackageLoader().load(_write_package(tmp_path / "second", id="second"))
    dialog = PetActionExchangeDialog(
        [first, second],
        tmp_path / "pets",
        current_pet_id="second",
    )
    qtbot.addWidget(dialog)

    assert dialog.action_import_page.target_combo.currentData() == "second"
    assert dialog.animation_editor_page.current_package() is second
    assert dialog.action_export_page.pet_combo.currentData() == "second"


def test_exchange_dialog_forwards_action_install_completion(
    qtbot: object, tmp_path: Path, monkeypatch: object
) -> None:
    package = PackageLoader().load(_write_package(tmp_path / "pet"))
    dialog = PetActionExchangeDialog([package], tmp_path / "pets")
    qtbot.addWidget(dialog)
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        dialog.action_import_page,
        "complete_install",
        lambda message: calls.append(("success", message)),
    )
    monkeypatch.setattr(
        dialog.action_import_page,
        "complete_install_failure",
        lambda message: calls.append(("failure", message)),
    )

    dialog.complete_action_install("installed")
    dialog.complete_action_install_failure("rolled back")

    assert calls == [("success", "installed"), ("failure", "rolled back")]


def test_editor_page_keeps_preview_visible_at_standard_dialog_size(qtbot: object, tmp_path: Path) -> None:
    package = PackageLoader().load(_write_package(tmp_path / "pet"))
    dialog = PetActionExchangeDialog([package], tmp_path / "pets")
    qtbot.addWidget(dialog)
    dialog.select_page("编辑动作")
    dialog.show()
    qtbot.wait(10)

    editor = dialog.animation_editor_page.editor
    assert dialog.width() >= 1220
    assert editor is not None
    assert editor.preview_card.isVisible()
    assert editor.preview_card.width() >= 260


def test_exchange_dialog_can_route_to_each_page(qtbot: object, tmp_path: Path) -> None:
    package = PackageLoader().load(_write_package(tmp_path / "pet"))
    dialog = PetActionExchangeDialog([package], tmp_path / "pets")
    qtbot.addWidget(dialog)

    dialog.select_page("导出动作")
    assert dialog.current_page_name() == "导出动作"
    assert dialog.page_title.text() == "导出动作"
    dialog.select_page("导入宠物")
    assert dialog.current_page_name() == "导入宠物"


def test_exchange_dialog_routes_footer_command_to_active_page(qtbot: object, tmp_path: Path, monkeypatch: object) -> None:
    package = PackageLoader().load(_write_package(tmp_path / "pet"))
    dialog = PetActionExchangeDialog([package], tmp_path / "pets")
    qtbot.addWidget(dialog)
    dialog.select_page("导出动作")
    dialog.action_export_page.select_actions(["idle"])
    called: list[bool] = []
    monkeypatch.setattr(dialog.action_export_page, "trigger_primary", lambda: called.append(True))

    dialog.primary_button.click()

    assert called == [True]


def test_exchange_dialog_navigation_and_close_respect_leave_guard(
    qtbot: object, tmp_path: Path, monkeypatch: object
) -> None:
    package = PackageLoader().load(_write_package(tmp_path / "pet"))
    dialog = PetActionExchangeDialog([package], tmp_path / "pets")
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.select_page("编辑动作")
    monkeypatch.setattr(dialog.animation_editor_page, "request_leave", lambda: False)

    dialog.select_page("导出动作")
    assert dialog.current_page_name() == "编辑动作"
    dialog.reject()
    assert dialog.isVisible()


def test_exchange_dialog_refreshes_all_package_selectors_and_deactivates_pages(
    qtbot: object, tmp_path: Path, monkeypatch: object
) -> None:
    first = PackageLoader().load(_write_package(tmp_path / "first", id="first"))
    second = PackageLoader().load(_write_package(tmp_path / "second", id="second"))
    dialog = PetActionExchangeDialog([first], tmp_path / "pets")
    qtbot.addWidget(dialog)
    stopped: list[str] = []
    monkeypatch.setattr(dialog.action_export_page, "deactivate", lambda: stopped.append("export"))

    assert dialog.refresh_packages([first, second], "second") is True
    dialog.action_export_page.deactivate()

    assert dialog.action_import_page.target_combo.currentData() == "second"
    assert dialog.action_export_page.pet_combo.currentData() == "second"
    assert stopped == ["export"]


def test_exchange_dialog_refresh_packages_is_atomic_when_editor_leave_is_cancelled(
    qtbot: object, tmp_path: Path, monkeypatch: object
) -> None:
    first = PackageLoader().load(_write_package(tmp_path / "first", id="first"))
    second = PackageLoader().load(_write_package(tmp_path / "second", id="second"))
    dialog = PetActionExchangeDialog([first], tmp_path / "pets", current_pet_id="first")
    qtbot.addWidget(dialog)
    dialog.select_page("编辑动作")
    assert dialog.animation_editor_page.editor is not None
    dialog.animation_editor_page.editor.total_duration_spin.setValue(100)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *_args, **_kwargs: QMessageBox.StandardButton.Cancel),
    )

    assert dialog.refresh_packages([second], "second") is False

    assert dialog._packages == (first,)
    assert dialog.pet_import_page._packages == (first,)
    assert dialog.action_import_page.target_combo.currentData() == "first"
    assert dialog.animation_editor_page.current_package() is first
    assert dialog.action_export_page.pet_combo.currentData() == "first"
    assert dialog.animation_editor_page.editor.is_dirty()
