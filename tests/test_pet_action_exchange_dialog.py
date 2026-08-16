"""Tests for the unified pet/action exchange dialog."""

from __future__ import annotations

from pathlib import Path

from petnest.core.package_loader import PackageLoader
from petnest.ui.pet_action_exchange_dialog import PetActionExchangeDialog
from tests.test_package_validator import _write_package


def test_exchange_dialog_has_three_pages(qtbot: object, tmp_path: Path) -> None:
    package = PackageLoader().load(_write_package(tmp_path / "pet"))
    dialog = PetActionExchangeDialog([package], tmp_path / "pets")
    qtbot.addWidget(dialog)

    assert dialog.page_names() == ["导入宠物", "导入动作", "导出动作"]


def test_exchange_dialog_can_route_to_each_page(qtbot: object, tmp_path: Path) -> None:
    package = PackageLoader().load(_write_package(tmp_path / "pet"))
    dialog = PetActionExchangeDialog([package], tmp_path / "pets")
    qtbot.addWidget(dialog)

    dialog.select_page("导出动作")
    assert dialog.current_page_name() == "导出动作"
    dialog.select_page("导入宠物")
    assert dialog.current_page_name() == "导入宠物"
