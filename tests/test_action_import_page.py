"""Tests for importing action packs into a target pet."""

from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZipFile

from PIL import Image

from petnest.core.action_pack import export_action_pack
from petnest.core.package_loader import PackageLoader
from petnest.ui.action_import_page import ActionImportPage
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

    assert (target.root / "animations" / "shared" / "001.png").is_file()


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
