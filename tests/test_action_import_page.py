"""Tests for importing action packs into a target pet."""

from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZipFile

from PIL import Image

from petnest.core.action_pack import export_action_pack
from petnest.core.package_loader import PackageLoader
from petnest.ui.action_import_page import ActionImportPage
from petnest.ui.exchange_page import ExchangePage
from tests.test_package_validator import _write_package, _write_png


def build_source(tmp_path: Path) -> Path:
    source = _write_package(tmp_path / "source")
    _write_png(source / "animations" / "shared" / "001.png")
    config = json.loads((source / "pet.json").read_text(encoding="utf-8"))
    config["animations"]["shared"] = {"path": "animations/shared", "fps": 10, "loop": True}
    (source / "pet.json").write_text(json.dumps(config), encoding="utf-8")
    return source


def test_action_import_page_loads_complete_pet_source(qtbot: object, tmp_path: Path) -> None:
    source = build_source(tmp_path)
    target = PackageLoader().load(_write_package(tmp_path / "target"))
    page = ActionImportPage([target], tmp_path / "pets")
    qtbot.addWidget(page)

    page.load_source(source)

    assert "shared" in page.available_action_names()
    assert page.source_kind_label.text() == "完整宠物"


def test_action_import_page_installs_selected_action(qtbot: object, tmp_path: Path) -> None:
    source = build_source(tmp_path)
    target = PackageLoader().load(_write_package(tmp_path / "target"))
    page = ActionImportPage([target], tmp_path / "pets")
    qtbot.addWidget(page)
    page.load_source(source)
    page.set_action_selection(["shared"])

    page.install_selected()

    config = json.loads((target.root / "pet.json").read_text(encoding="utf-8"))
    assert (target.root / config["animations"]["shared"]["path"] / "001.png").is_file()


def test_action_import_page_does_not_install_unselected_actions(qtbot: object, tmp_path: Path) -> None:
    source = build_source(tmp_path)
    source_config = json.loads((source / "pet.json").read_text(encoding="utf-8"))
    source_config["animations"]["idle"]["fps"] = 4
    (source / "pet.json").write_text(json.dumps(source_config), encoding="utf-8")
    target = PackageLoader().load(_write_package(tmp_path / "target"))
    page = ActionImportPage([target], tmp_path / "pets")
    qtbot.addWidget(page)
    page.load_source(source)
    page.set_action_selection(["shared"])

    page.install_selected()

    target_config = json.loads((target.root / "pet.json").read_text(encoding="utf-8"))
    assert target_config["animations"]["idle"]["fps"] == 8
    assert "shared" in target_config["animations"]


def test_action_import_page_blocks_locked_current_pet(qtbot: object, tmp_path: Path) -> None:
    source = build_source(tmp_path)
    target = PackageLoader().load(_write_package(tmp_path / "target"))
    page = ActionImportPage([target], tmp_path / "pets", is_pet_locked=lambda _: True)
    qtbot.addWidget(page)
    page.load_source(source)

    page.install_selected()

    assert "提醒" in page.status_label.text()


def test_action_import_page_uses_shared_footer_and_routes_primary(qtbot: object, tmp_path: Path, monkeypatch: object) -> None:
    target = PackageLoader().load(_write_package(tmp_path / "target"))
    page = ActionImportPage([target], tmp_path / "pets")
    qtbot.addWidget(page)
    page.show()

    assert isinstance(page, ExchangePage)
    assert page.footer_state().status == "导入完整宠物时可只选择其中部分动作。"
    assert page.footer_state().primary_text == "安装选中动作"
    assert not page.install_button.isVisible()
    assert not page.status_label.isVisible()

    called: list[bool] = []
    monkeypatch.setattr(page, "install_selected", lambda: called.append(True))
    page.trigger_primary()

    assert called == [True]


def test_action_import_page_refresh_packages_rebuilds_target_selector(qtbot: object, tmp_path: Path) -> None:
    first = PackageLoader().load(_write_package(tmp_path / "first", id="first"))
    second = PackageLoader().load(_write_package(tmp_path / "second", id="second"))
    page = ActionImportPage([first], tmp_path / "pets")
    qtbot.addWidget(page)

    page.refresh_packages([first, second], "second")

    assert page.target_combo.currentData() == "second"
    assert [page.target_combo.itemData(i) for i in range(page.target_combo.count())] == ["first", "second"]
    assert page.footer_state().primary_text == "安装选中动作"
