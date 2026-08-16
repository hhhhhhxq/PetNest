"""Tests for selecting, previewing and exporting pet actions."""

from __future__ import annotations

from pathlib import Path

from petnest.ui.action_export_page import ActionExportPage
from petnest.core.package_loader import PackageLoader
from tests.test_package_validator import _write_package


def test_export_page_lists_every_animation(qtbot: object, tmp_path: Path) -> None:
    package = PackageLoader().load(_write_package(tmp_path / "pet"))
    page = ActionExportPage([package])
    qtbot.addWidget(page)

    assert page.visible_action_names() == set(package.animations)
    assert page.selected_action_names() == set()


def test_filter_does_not_clear_selected_actions(qtbot: object, tmp_path: Path) -> None:
    package = PackageLoader().load(_write_package(tmp_path / "pet"))
    page = ActionExportPage([package])
    qtbot.addWidget(page)

    page.select_actions(["idle", "click"])
    page.scope_combo.setCurrentIndex(page.scope_combo.findData("fullscreen"))

    assert page.selected_action_names() == {"idle", "click"}


def test_selected_actions_export_to_zip(qtbot: object, tmp_path: Path) -> None:
    package = PackageLoader().load(_write_package(tmp_path / "pet"))
    page = ActionExportPage([package])
    qtbot.addWidget(page)
    page.select_actions(["idle"])
    output = tmp_path / "share.zip"

    page.export_selected(output)

    assert output.is_file()
