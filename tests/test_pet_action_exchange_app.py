"""Tests for application integration of the exchange center."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from petnest.app import PetNest
from petnest.core.settings_manager import SettingsManager
from tools.create_sample_pet import create_sample_pet


def test_app_opens_unified_exchange_center_and_routes_page(qtbot: object, tmp_path: Path) -> None:
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    application = PetNest(
        pets_root=tmp_path / "pets",
        settings_manager=SettingsManager(tmp_path / "settings.json"),
        enable_tray=True,
    )
    qtbot.addWidget(application.window)

    application.show_pet_action_exchange_dialog("导出动作")

    assert application._pet_action_exchange_dialog is not None
    assert application._pet_action_exchange_dialog.current_page_name() == "导出动作"
    application._pet_action_exchange_dialog.close()
    application.shutdown()


def _application(tmp_path: Path, qtbot: object, *, enable_tray: bool = False) -> PetNest:
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    application = PetNest(
        pets_root=tmp_path / "pets",
        settings_manager=SettingsManager(tmp_path / "settings.json"),
        enable_tray=enable_tray,
    )
    qtbot.addWidget(application.window)
    return application


def test_app_saves_editor_page_timeline_and_reloads_current_pet(qtbot: object, tmp_path: Path) -> None:
    application = _application(tmp_path, qtbot)

    result = application._save_animation_timelines(application.package, {"idle": (180, 90, 120, 160)})

    saved = json.loads((application.package.root / "pet.json").read_text(encoding="utf-8"))
    assert result.success
    assert result.package is application.package
    assert saved["animations"]["idle"]["frame_durations_ms"] == [180, 90, 120, 160]
    application.shutdown()


def test_app_restores_pet_json_when_runtime_reload_fails(
    qtbot: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    application = _application(tmp_path, qtbot)
    config_path = application.package.root / "pet.json"
    before = config_path.read_bytes()
    monkeypatch.setattr(application, "reload_current_pet", lambda: False)

    result = application._save_animation_timelines(application.package, {"idle": (180, 90, 120, 160)})

    assert not result.success
    assert config_path.read_bytes() == before
    assert "保存未生效，已恢复原配置" in result.message
    application.shutdown()


def test_app_reports_double_failure_when_config_restore_fails(
    qtbot: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    application = _application(tmp_path, qtbot)
    monkeypatch.setattr(application, "reload_current_pet", lambda: False)

    def fail_restore(*_args: object) -> None:
        raise RuntimeError("磁盘只读")

    monkeypatch.setattr(application.action_synchronizer, "restore_config_bytes", fail_restore)

    result = application._save_animation_timelines(application.package, {"idle": (180, 90, 120, 160)})

    assert not result.success
    assert result.message == "重载失败且配置恢复失败：磁盘只读"
    application.shutdown()


def test_app_does_not_write_timelines_when_pet_is_locked(
    qtbot: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    application = _application(tmp_path, qtbot)
    monkeypatch.setattr(application, "_is_pet_locked_for_exchange", lambda _identifier: True)
    calls: list[str] = []
    monkeypatch.setattr(application.action_synchronizer, "snapshot_config_bytes", lambda *_: calls.append("snapshot"))
    monkeypatch.setattr(application.action_synchronizer, "update_frame_durations", lambda *_: calls.append("update"))

    result = application._save_animation_timelines(application.package, {"idle": (180, 90, 120, 160)})

    assert not result.success
    assert result.message == "当前宠物正在显示下班提醒，请先结束提醒。"
    assert calls == []
    application.shutdown()


def test_app_refreshes_non_current_package_after_timeline_save(qtbot: object, tmp_path: Path) -> None:
    application = _application(tmp_path, qtbot)
    second_root = create_sample_pet(tmp_path / "pets" / "second_pet")
    second_config = json.loads((second_root / "pet.json").read_text(encoding="utf-8"))
    second_config["id"] = "second_pet"
    second_config["name"] = "Second Pet"
    (second_root / "pet.json").write_text(json.dumps(second_config), encoding="utf-8")
    application.packages = application.loader.discover(application.pets_root)
    second = next(item for item in application.packages if item.identifier == "second_pet")

    result = application._save_animation_timelines(second, {"idle": (180, 90, 120, 160)})

    assert result.success
    assert result.package is not second
    refreshed = next(item for item in application.packages if item.identifier == "second_pet")
    assert refreshed.animations["idle"].frame_durations_ms == (180, 90, 120, 160)
    application.shutdown()


def test_legacy_editor_and_import_methods_route_to_exchange_center(
    qtbot: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    application = _application(tmp_path, qtbot)
    calls: list[str] = []
    monkeypatch.setattr(application, "show_pet_action_exchange_dialog", calls.append)

    application.show_animation_editor_dialog()
    application.show_spritesheet_import_dialog()
    application.show_work_finish_import_dialog()

    assert calls == ["编辑动作", "导入宠物", "导入动作"]
    application.shutdown()


def test_exchange_dialog_receives_current_pet_and_real_save_callback(qtbot: object, tmp_path: Path) -> None:
    application = _application(tmp_path, qtbot)

    application.show_animation_editor_dialog()
    dialog = application._pet_action_exchange_dialog

    assert dialog is not None
    editor_page = dialog.animation_editor_page
    assert editor_page._current_pet_id == application.package.identifier
    assert editor_page._save_timelines.__self__ is application
    assert editor_page._save_timelines.__func__ is PetNest._save_animation_timelines
    assert dialog.current_page_name() == "编辑动作"
    dialog.close()
    application.shutdown()


def test_install_handlers_refresh_open_exchange_center_without_closing(
    qtbot: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    application = _application(tmp_path, qtbot)
    calls: list[tuple[object, str]] = []
    closed: list[bool] = []
    fake_dialog = SimpleNamespace(
        refresh_packages=lambda packages, current_id: calls.append((packages, current_id)),
        close=lambda: closed.append(True),
    )
    application._pet_action_exchange_dialog = fake_dialog  # type: ignore[assignment]
    monkeypatch.setattr(application, "_synchronize_pet_library", lambda: None)
    monkeypatch.setattr(application, "switch_pet", lambda _identifier: True)
    monkeypatch.setattr(application, "reload_current_pet", lambda: True)

    application._handle_pet_exchange_installed(application.package.identifier, object())
    application._handle_actions_exchange_installed(application.package.identifier, object())

    assert len(calls) == 2
    assert all(current_id == application.package.identifier for _packages, current_id in calls)
    assert closed == []
    application.shutdown()
