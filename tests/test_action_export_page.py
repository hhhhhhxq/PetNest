"""Tests for selecting, previewing and exporting pet actions."""

from __future__ import annotations

from pathlib import Path

from petnest.ui.action_export_page import ActionExportPage
from petnest.core.package_loader import PackageLoader
from petnest.ui.exchange_page import ExchangePage
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


def test_export_page_uses_shared_footer_and_routes_primary(qtbot: object, tmp_path: Path, monkeypatch: object) -> None:
    package = PackageLoader().load(_write_package(tmp_path / "pet"))
    page = ActionExportPage([package])
    qtbot.addWidget(page)
    page.show()

    assert isinstance(page, ExchangePage)
    assert page.footer_state().status == "选择要分享的动作"
    assert page.footer_state().primary_text == "导出 ZIP…"
    assert not page.export_button.isVisible()
    assert not page.status_label.isVisible()

    called: list[bool] = []
    monkeypatch.setattr(page, "_choose_output", lambda: called.append(True))
    page.trigger_primary()

    assert called == [True]


def test_export_page_footer_tracks_selection_and_refreshes_packages(qtbot: object, tmp_path: Path) -> None:
    first = PackageLoader().load(_write_package(tmp_path / "first", id="first"))
    second = PackageLoader().load(_write_package(tmp_path / "second", id="second"))
    page = ActionExportPage([first])
    qtbot.addWidget(page)
    page.select_actions(["idle"])

    assert page.footer_state().status == "已选 1 项"
    assert page.footer_state().primary_enabled

    page.refresh_packages([first, second], "second")

    assert page.pet_combo.currentData() == "second"
    assert page.footer_state().status == "选择要分享的动作"
    assert not page.footer_state().primary_enabled
