"""Tests for application integration of the exchange center."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from petnest import app as app_module
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


def test_reload_current_pet_preserves_configured_scale(
    qtbot: object, tmp_path: Path
) -> None:
    application = _application(tmp_path, qtbot)
    application.apply_settings(replace(application.settings, scale=1.2))
    assert application.window.scale == pytest.approx(1.2)

    assert application.reload_current_pet(synchronize=False) is True

    assert application.window.scale == pytest.approx(1.2)
    assert application.settings.scale == pytest.approx(1.2)
    application.shutdown()


def test_reload_current_pet_preserves_visible_runtime_scale_when_settings_lag(
    qtbot: object, tmp_path: Path
) -> None:
    application = _application(tmp_path, qtbot)
    application.window.set_scale(1.1)
    assert application.settings.scale != pytest.approx(1.1)

    assert application.reload_current_pet(synchronize=False) is True

    assert application.window.scale == pytest.approx(1.1)
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
    monkeypatch.setattr(application, "reload_current_pet", lambda **_kwargs: True)
    monkeypatch.setattr(app_module.QMessageBox, "information", lambda *_args: None)

    application._handle_pet_exchange_installed(application.package.identifier, object())
    application._handle_actions_exchange_installed(application.package.identifier, object())

    assert len(calls) == 2
    assert all(current_id == application.package.identifier for _packages, current_id in calls)
    assert closed == []
    application.shutdown()


def test_action_install_handler_finalizes_after_current_pet_reload(
    qtbot: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    application = _application(tmp_path, qtbot)
    calls: list[str] = []
    completion: list[str] = []
    information: list[tuple[str, str]] = []
    result = SimpleNamespace(
        rollback=lambda: calls.append("rollback"),
        finalize=lambda: calls.append("finalize") or (),
        installed=("idle", "click"),
    )
    synchronizations: list[str] = []
    reload_modes: list[bool] = []
    monkeypatch.setattr(application, "_synchronize_pet_library", lambda: synchronizations.append("sync"))
    monkeypatch.setattr(
        application,
        "reload_current_pet",
        lambda *, synchronize=True: reload_modes.append(synchronize) or True,
    )
    application._pet_action_exchange_dialog = SimpleNamespace(
        complete_action_install=completion.append,
        refresh_packages=lambda *_args: True,
        close=lambda: None,
    )  # type: ignore[assignment]
    monkeypatch.setattr(
        app_module.QMessageBox,
        "information",
        lambda _parent, title, message: information.append((title, message)),
    )

    application._handle_actions_exchange_installed(application.package.identifier, result)

    assert calls == ["finalize"]
    assert synchronizations == []
    assert reload_modes == [False]
    assert completion and "2 个动作" in completion[0]
    assert information and information[0][0] == "动作安装完成"
    application.shutdown()


def test_action_install_handler_rolls_back_when_current_pet_reload_fails(
    qtbot: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    application = _application(tmp_path, qtbot)
    calls: list[str] = []
    reload_results = iter((False, True))
    messages: list[tuple[str, str]] = []
    completion: list[str] = []
    failures: list[str] = []
    result = SimpleNamespace(
        rollback=lambda: calls.append("rollback") or (),
        finalize=lambda: calls.append("finalize") or (),
        installed=("idle",),
    )
    monkeypatch.setattr(application, "_synchronize_pet_library", lambda: None)
    monkeypatch.setattr(application, "reload_current_pet", lambda **_kwargs: next(reload_results))
    monkeypatch.setattr(
        app_module.QMessageBox,
        "warning",
        lambda _parent, title, message: messages.append((title, message)),
    )
    application._pet_action_exchange_dialog = SimpleNamespace(
        complete_action_install=completion.append,
        complete_action_install_failure=failures.append,
        refresh_packages=lambda *_args: True,
        close=lambda: None,
    )  # type: ignore[assignment]

    application._handle_actions_exchange_installed(application.package.identifier, result)

    assert calls == ["rollback"]
    assert messages and "已恢复" in messages[0][1]
    assert completion == []
    assert failures and "已恢复" in failures[0]
    application.shutdown()


def test_action_install_handler_finalizes_non_current_pet_without_reload(
    qtbot: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    application = _application(tmp_path, qtbot)
    calls: list[str] = []
    result = SimpleNamespace(
        rollback=lambda: calls.append("rollback") or (),
        finalize=lambda: calls.append("finalize") or (),
        installed=("idle",),
    )
    monkeypatch.setattr(application, "_synchronize_pet_library", lambda: None)
    monkeypatch.setattr(application, "reload_current_pet", lambda **_kwargs: calls.append("reload") or True)
    monkeypatch.setattr(app_module.QMessageBox, "information", lambda *_args: None)

    application._handle_actions_exchange_installed("another_pet", result)

    assert calls == ["finalize"]
    application.shutdown()


def test_action_install_handler_reports_rollback_failure(
    qtbot: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    application = _application(tmp_path, qtbot)
    messages: list[tuple[str, str]] = []

    def fail_rollback() -> tuple[str, ...]:
        raise RuntimeError("config changed")

    result = SimpleNamespace(rollback=fail_rollback, finalize=lambda: ())
    monkeypatch.setattr(application, "_synchronize_pet_library", lambda: None)
    monkeypatch.setattr(application, "reload_current_pet", lambda **_kwargs: False)
    monkeypatch.setattr(
        app_module.QMessageBox,
        "critical",
        lambda _parent, title, message: messages.append((title, message)),
    )
    monkeypatch.setattr(app_module.QMessageBox, "warning", lambda *_args: None)

    application._handle_actions_exchange_installed(application.package.identifier, result)

    assert messages and "config changed" in messages[0][1]
    application.shutdown()


def test_image_action_flow_reloads_current_pet_and_shows_installed_action_after_success(
    qtbot: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    application = _application(tmp_path, qtbot)
    monkeypatch.setattr(app_module.QMessageBox, "information", lambda *_args: None)
    application.show_pet_action_exchange_dialog("导入动作")
    dialog = application._pet_action_exchange_dialog
    assert dialog is not None
    page = dialog.action_import_page
    frame = tmp_path / "new-click.png"
    Image.new("RGBA", (256, 256), (20, 80, 220, 200)).save(frame)
    page.select_image_mode()
    page.image_content.select_slot("mouse_click")
    page.image_content.load_files([frame])

    page.trigger_primary()

    assert "click" in application.package.animations
    assert application.package.bindings["mouse.click"] == "click"
    assert len(page.image_content.ordered_paths()) == 1
    assert page.image_content.ordered_paths()[0].name == "0001.png"
    assert page.image_content.can_install() is False
    dialog.close()
    application.shutdown()


def test_image_action_reload_failure_rolls_back_and_keeps_draft(
    qtbot: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    application = _application(tmp_path, qtbot)
    application.show_pet_action_exchange_dialog("导入动作")
    dialog = application._pet_action_exchange_dialog
    assert dialog is not None
    page = dialog.action_import_page
    frame = tmp_path / "new-click.png"
    Image.new("RGBA", (256, 256), (20, 80, 220, 200)).save(frame)
    before = (application.package.root / "pet.json").read_bytes()
    page.select_image_mode()
    page.image_content.select_slot("mouse_click")
    page.image_content.load_files([frame])
    reload_results = iter((False, True))
    monkeypatch.setattr(application, "reload_current_pet", lambda **_kwargs: next(reload_results))
    monkeypatch.setattr(app_module.QMessageBox, "warning", lambda *_args: None)

    page.trigger_primary()

    assert (application.package.root / "pet.json").read_bytes() == before
    assert page.image_content.ordered_paths() == (frame.resolve(),)
    assert "已恢复" in page.image_content.status_label.text()
    dialog.close()
    application.shutdown()
