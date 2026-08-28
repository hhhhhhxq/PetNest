"""Tests for the unified pet/action exchange dialog."""

from __future__ import annotations

from pathlib import Path

from PIL import Image
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QMessageBox

from petnest.core.package_loader import PackageLoader
from petnest.ui.adaptive_navigation import AdaptiveNavigationList
from petnest.ui.pet_action_exchange_dialog import PetActionExchangeDialog
from tests.test_package_validator import _write_package


def test_exchange_dialog_has_store_page_and_single_shell_footer(qtbot: object, tmp_path: Path) -> None:
    package = PackageLoader().load(_write_package(tmp_path / "pet"))
    dialog = PetActionExchangeDialog([package], tmp_path / "pets")
    qtbot.addWidget(dialog)

    assert dialog.page_names() == ["导入宠物", "宠物商店", "导入动作", "编辑动作", "导出动作"]
    dialog.select_page("宠物商店")
    assert dialog.current_page() is dialog.pet_store_page
    assert dialog.primary_button.parentWidget() is dialog.footer_bar
    assert dialog.secondary_button.parentWidget() is dialog.footer_bar
    assert dialog.footer_bar.parentWidget() is dialog.content
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


def test_action_import_page_does_not_force_dialog_taller_than_standard_size(
    qtbot: object, tmp_path: Path
) -> None:
    package = PackageLoader().load(_write_package(tmp_path / "pet"))
    dialog = PetActionExchangeDialog([package], tmp_path / "pets")
    qtbot.addWidget(dialog)
    dialog.select_page("导入动作")
    dialog.action_import_page.select_image_mode()
    dialog.show()
    qtbot.wait(10)

    assert dialog.maximumHeight() == 760
    assert dialog.minimumHeight() == 680
    assert dialog.minimumSizeHint().height() <= 760
    assert dialog.action_import_page.minimumSizeHint().height() <= 632


def test_exchange_dialog_can_route_to_each_page(qtbot: object, tmp_path: Path) -> None:
    package = PackageLoader().load(_write_package(tmp_path / "pet"))
    dialog = PetActionExchangeDialog([package], tmp_path / "pets")
    qtbot.addWidget(dialog)

    dialog.select_page("导出动作")
    assert dialog.current_page_name() == "导出动作"
    assert dialog.page_title.text() == "导出动作"
    dialog.select_page("导入宠物")
    assert dialog.current_page_name() == "导入宠物"


def test_action_import_page_subtitle_explains_both_modes(qtbot: object, tmp_path: Path) -> None:
    package = PackageLoader().load(_write_package(tmp_path / "pet"))
    dialog = PetActionExchangeDialog([package], tmp_path / "pets")
    qtbot.addWidget(dialog)

    dialog.select_page("导入动作")

    assert dialog.page_subtitle.text() == "从资源包提取动作，或用图片制作可触发动作"


def test_exchange_shell_matches_prototype_header_and_page_heading(
    qtbot: object, tmp_path: Path
) -> None:
    package = PackageLoader().load(_write_package(tmp_path / "pet"))
    dialog = PetActionExchangeDialog([package], tmp_path / "pets")
    qtbot.addWidget(dialog)
    dialog.select_page("导入动作")
    dialog.show()
    qtbot.wait(10)

    assert dialog.app_title.text() == "宠物与动作"
    assert dialog.header_target_label.text() == "目标宠物"
    assert dialog.header_target_combo is dialog.action_import_page.target_combo
    app_bottom = dialog.app_title.mapTo(dialog.window_shell, dialog.app_title.rect().bottomLeft()).y()
    page_top = dialog.page_title.mapTo(dialog.window_shell, dialog.page_title.rect().topLeft()).y()
    assert app_bottom < page_top

    dialog.select_page("导出动作")
    assert not dialog.header_target_label.isVisible()
    assert not dialog.header_target_combo.isVisible()


def test_exchange_shell_uses_v4_geometry_and_lucide_navigation(
    qtbot: object, tmp_path: Path
) -> None:
    package = PackageLoader().load(_write_package(tmp_path / "pet"))
    dialog = PetActionExchangeDialog([package], tmp_path / "pets")
    qtbot.addWidget(dialog)
    dialog.select_page("导入动作")
    dialog.show()
    qtbot.wait(10)

    assert dialog.top_bar.objectName() == "actionExchangeTopBar"
    assert dialog.top_bar.height() == 56
    assert dialog.sidebar.objectName() == "actionExchangeSidebar"
    assert dialog.sidebar.width() == 145
    assert dialog.content.objectName() == "actionExchangeMain"
    assert dialog.content.layout().contentsMargins().left() == 17
    assert dialog.app_icon.text() == ""
    assert dialog.app_icon.pixmap() is not None
    assert not dialog.app_icon.pixmap().isNull()
    assert all(not dialog.navigation.item(index).icon().isNull() for index in range(dialog.navigation.count()))
    footer_left = dialog.footer_status_label.mapTo(dialog.window_shell, dialog.footer_status_label.rect().topLeft()).x()
    sidebar_right = dialog.sidebar.mapTo(dialog.window_shell, dialog.sidebar.rect().topRight()).x()
    assert footer_left > sidebar_right


def test_exchange_navigation_reflows_and_grows_sidebar_for_large_font(
    qtbot: object, tmp_path: Path
) -> None:
    package = PackageLoader().load(_write_package(tmp_path / "pet"))
    dialog = PetActionExchangeDialog([package], tmp_path / "pets")
    qtbot.addWidget(dialog)
    dialog.navigation.setCurrentRow(1)
    original_row_height = dialog.navigation.sizeHintForRow(0)
    font = QFont(dialog.navigation.font())
    font.setPointSize(24)

    dialog.navigation.setFont(font)
    dialog.show()

    qtbot.waitUntil(lambda: dialog.navigation.sizeHintForRow(0) > original_row_height)
    assert isinstance(dialog.navigation, AdaptiveNavigationList)
    assert dialog.navigation.currentRow() == 1
    assert dialog.sidebar.width() > 145
    rects = [
        dialog.navigation.visualItemRect(dialog.navigation.item(row))
        for row in range(dialog.navigation.count())
    ]
    assert all(rect.isValid() and rect.height() > 0 for rect in rects)
    assert all(first.bottom() < second.top() for first, second in zip(rects, rects[1:]))
    assert dialog.navigation.sizeHintForColumn(0) >= max(
        dialog.navigation.fontMetrics().horizontalAdvance(dialog.navigation.item(row).text())
        for row in range(dialog.navigation.count())
    )


def test_action_import_footer_moves_inside_the_active_prototype_panel(
    qtbot: object, tmp_path: Path
) -> None:
    package = PackageLoader().load(_write_package(tmp_path / "pet"))
    dialog = PetActionExchangeDialog([package], tmp_path / "pets")
    qtbot.addWidget(dialog)
    dialog.select_page("导入动作")

    assert dialog.footer_bar.parentWidget() is dialog.action_import_page.resource_footer_host
    assert dialog.action_import_page.resource_footer_host.parentWidget() is dialog.action_import_page.resource_actions_card

    dialog.action_import_page.select_image_mode()

    assert dialog.footer_bar.parentWidget() is dialog.action_import_page.image_content.footer_host

    dialog.select_page("导出动作")

    assert dialog.footer_bar.parentWidget() is dialog.content


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


def test_leaving_or_closing_action_import_page_stops_image_previews(qtbot: object, tmp_path: Path) -> None:
    package = PackageLoader().load(_write_package(tmp_path / "pet"))
    frame = tmp_path / "frame.png"
    Image.new("RGBA", (16, 16), (10, 20, 30, 255)).save(frame)
    dialog = PetActionExchangeDialog([package], tmp_path / "pets")
    qtbot.addWidget(dialog)
    dialog.select_page("导入动作")
    page = dialog.action_import_page
    page.select_image_mode()
    page.image_content.load_files([frame])
    assert page.image_content.preview.preview_timer.isActive()

    dialog.select_page("导出动作")
    assert not page.image_content.preview.preview_timer.isActive()

    dialog.select_page("导入动作")
    assert page.image_content.preview.preview_timer.isActive()
    dialog.reject()
    assert not page.image_content.preview.preview_timer.isActive()


def test_exchange_dialog_checks_background_store_page_before_close(
    qtbot: object, tmp_path: Path, monkeypatch: object
) -> None:
    package = PackageLoader().load(_write_package(tmp_path / "pet"))
    dialog = PetActionExchangeDialog([package], tmp_path / "pets")
    qtbot.addWidget(dialog)
    monkeypatch.setattr(dialog.pet_store_page, "request_close", lambda: False)

    assert dialog._can_close() is False


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
