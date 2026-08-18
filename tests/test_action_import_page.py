"""Tests for importing action packs into a target pet."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import pytest
from PIL import Image
from PySide6.QtCore import QEventLoop
from PySide6.QtWidgets import QMessageBox

from petnest.core.action_installer import ActionInstallError
from petnest.core.action_pack import export_action_pack
from petnest.core.package_loader import PackageLoader
from petnest.ui import action_import_page as action_import_page_module
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


def test_action_import_page_shows_progress_before_install(
    qtbot: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = build_source(tmp_path)
    target = PackageLoader().load(_write_package(tmp_path / "target"))
    page = ActionImportPage([target], tmp_path / "pets")
    qtbot.addWidget(page)
    page.load_source(source)
    page.set_action_selection(["shared"])
    observed: list[tuple[str, str, bool]] = []
    processed: list[object] = []

    def inspect_install(*_args: object, **_kwargs: object) -> object:
        state = page.footer_state()
        observed.append((state.status, state.primary_text, state.primary_enabled))
        return SimpleNamespace(installed=("shared",))

    monkeypatch.setattr(action_import_page_module, "install_actions", inspect_install)
    monkeypatch.setattr(
        action_import_page_module.QApplication,
        "processEvents",
        lambda *args, **_kwargs: processed.append(args[0] if args else None),
    )

    page.install_selected()

    assert processed == [QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents]
    assert observed == [("正在安装 1 个动作…", "处理中…", False)]
    assert page.footer_state().status == "动作已写入，正在重新加载目标宠物…"
    assert not page.footer_state().primary_enabled


def test_action_import_page_shows_warning_when_install_fails(
    qtbot: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = build_source(tmp_path)
    target = PackageLoader().load(_write_package(tmp_path / "target"))
    page = ActionImportPage([target], tmp_path / "pets")
    qtbot.addWidget(page)
    page.load_source(source)
    warnings: list[tuple[str, str]] = []

    monkeypatch.setattr(
        action_import_page_module,
        "install_actions",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ActionInstallError("disk locked")),
    )
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda _parent, title, message: warnings.append((title, message)),
    )

    page.install_selected()

    assert "disk locked" in page.footer_state().status
    assert warnings == [("动作安装失败", "disk locked")]
    assert page._pack is not None
    assert page.footer_state().primary_enabled


def test_action_import_page_clears_source_after_apply_success(qtbot: object, tmp_path: Path) -> None:
    source = build_source(tmp_path)
    target = PackageLoader().load(_write_package(tmp_path / "target"))
    page = ActionImportPage([target], tmp_path / "pets", current_pet_id=target.identifier)
    qtbot.addWidget(page)
    page.load_source(source)
    page.import_bindings.setChecked(True)
    selected_target = page.target_combo.currentData()

    page.complete_install("已导入 1 个动作到 Target。")

    assert page._pack is None
    assert page.source_input.text() == ""
    assert page.source_kind_label.text() == "尚未读取来源"
    assert page.source_summary_label.text() == ""
    assert page.action_list.count() == 0
    assert page.conflict_table.rowCount() == 0
    assert not page.import_bindings.isChecked()
    assert page.target_combo.currentData() == selected_target
    assert page.footer_state().status == "已导入 1 个动作到 Target。"
    assert not page.footer_state().primary_enabled


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
