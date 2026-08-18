"""应用装配与平台安全降级的回归测试。"""

from __future__ import annotations

import json
import hashlib
import os
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PIL import Image
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox
from PySide6.QtCore import QPoint, QRect, Qt

from petnest.app import PetNest, effect_directories_for, resource_directory_for_cache
from petnest.core.animation_action_synchronizer import AnimationActionSyncError
from petnest.core.app_update import AppUpdateCheckResult
from petnest.core.cursor_style_catalog import CursorStyleCatalog
from petnest.core.remote_resource_cache import RemoteResourceCache
from petnest.core.remote_resource_update import RemoteResourceCheckResult
from petnest.core.settings_manager import SettingsManager
from petnest.models.event import PetEvent
from petnest.models.lan_interaction import ChatMessageKind, DangerAlert, LanPeer
from petnest.models.settings import Settings
from petnest.platforms.unsupported import UnsupportedPlatformAdapter
from tools.create_sample_pet import create_sample_pet


class _IdleAdapter:
    def __init__(self, idle_seconds: float = 0) -> None:
        self.idle_seconds = idle_seconds

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def get_idle_seconds(self) -> float:
        return self.idle_seconds


def test_app_wires_peer_registry_alert_action_and_overlay(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    manager = SettingsManager(tmp_path / "config" / "settings.json")
    application = PetNest(
        pets_root=tmp_path / "pets",
        settings_manager=manager,
        enable_tray=False,
    )
    qtbot.addWidget(application.window)

    assert application.peer_registry.path == manager.path.parent / "known-lan-peers.json"
    assert application.danger_alert_action.text() == "⚠  发送危险预警"
    assert application.danger_alert_overlay is not None
    application.shutdown()


def test_app_shows_received_alert_on_pet_screen(qtbot: pytest.QtBot, tmp_path: Path, monkeypatch) -> None:
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    application = PetNest(
        pets_root=tmp_path / "pets",
        settings_manager=SettingsManager(tmp_path / "settings.json"),
        enable_tray=False,
    )
    qtbot.addWidget(application.window)
    shown = []
    monkeypatch.setattr(application.danger_alert_overlay, "show_alert", lambda *args: shown.append(args))
    monkeypatch.setattr(application, "_pet_screen_geometry", lambda: QRect(10, 20, 800, 600))

    application._handle_danger_alert(
        DangerAlert(
            "alert-1",
            "peer",
            "小林",
            application.settings.device_id,
            1_800_000_000,
            "请立即撤离",
        )
    )

    assert shown == [("alert-1", "小林", QRect(10, 20, 800, 600), "请立即撤离")]
    application.shutdown()


def test_app_confirms_context_alert_and_persists_membership(
    qtbot: pytest.QtBot,
    tmp_path: Path,
    monkeypatch,
) -> None:
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    manager = SettingsManager(tmp_path / "settings.json")
    application = PetNest(pets_root=tmp_path / "pets", settings_manager=manager, enable_tray=False)
    qtbot.addWidget(application.window)
    application._set_lan_alert_group_joined(True)
    application.lan_service._peers["peer"] = LanPeer(
        "peer",
        "小林",
        ip_address="127.0.0.1",
        port=19000,
        alert_group_supported=True,
        alert_group_joined=True,
    )
    sent = []
    monkeypatch.setattr(
        application.lan_service,
        "send_danger_alert",
        lambda message="": sent.append(message) or True,
    )
    monkeypatch.setattr(
        "petnest.app.DangerAlertConfirmDialog.exec",
        lambda _dialog: QDialog.DialogCode.Accepted,
    )
    monkeypatch.setattr(
        "petnest.app.DangerAlertConfirmDialog.alert_message",
        lambda _dialog: "请立即撤离",
    )

    application._confirm_danger_alert()

    assert sent == ["请立即撤离"]
    assert manager.load().lan_alert_group_joined is True
    assert application.lan_service.alert_group_joined is True
    application.shutdown()


def test_effect_directories_include_custom_pets_and_installation_resources(tmp_path: Path) -> None:
    pets_root = tmp_path / "custom" / "pets"
    resource_root = tmp_path / "cache" / "resources"
    bundled_root = tmp_path / "bundle"
    application_root = tmp_path / "installed"

    roots = effect_directories_for(
        pets_root=pets_root,
        resource_directory=resource_root,
        bundled_root=bundled_root,
        application_root=application_root,
    )

    assert roots == (
        (pets_root.parent / "effects").resolve(),
        (resource_root / "effects").resolve(),
        (application_root / "effects").resolve(),
        (bundled_root / "effects").resolve(),
    )


def test_settings_and_cursor_entries_reuse_one_settings_center(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    application = PetNest(
        pets_root=tmp_path / "pets",
        settings_manager=SettingsManager(tmp_path / "settings.json"),
        enable_tray=False,
    )
    qtbot.addWidget(application.window)

    application.show_settings_dialog()
    first = application._settings_center_dialog
    assert first is not None

    application.show_cursor_style_dialog()

    assert application._settings_center_dialog is first
    assert first.section_list.currentRow() == 1
    first.reject()
    assert application._settings_center_dialog is None
    application.shutdown()


def test_unlocking_codex_usage_persists_and_shows_tray_action(
    qtbot: pytest.QtBot, tmp_path: Path
) -> None:
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    settings_manager = SettingsManager(tmp_path / "settings.json")
    application = PetNest(
        pets_root=tmp_path / "pets",
        settings_manager=settings_manager,
        enable_tray=True,
    )
    qtbot.addWidget(application.window)
    assert application.tray is not None
    assert not application.tray.codex_usage_action.isVisible()

    application._unlock_codex_usage()

    assert application.settings.codex_usage_unlocked is True
    assert settings_manager.load().codex_usage_unlocked is True
    assert application.tray.codex_usage_action.isVisible()
    application.shutdown()


def test_version_click_unlock_survives_applying_the_open_settings_dialog(
    qtbot: pytest.QtBot, tmp_path: Path
) -> None:
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    settings_manager = SettingsManager(tmp_path / "settings.json")
    application = PetNest(
        pets_root=tmp_path / "pets",
        settings_manager=settings_manager,
        enable_tray=True,
    )
    qtbot.addWidget(application.window)
    application._show_settings_center("app_update")
    dialog = application._settings_center_dialog
    assert dialog is not None

    for _ in range(7):
        qtbot.mouseClick(dialog.current_version_label, Qt.MouseButton.LeftButton)
    dialog.button_box.button(QDialogButtonBox.StandardButton.Ok).click()

    assert application.settings.codex_usage_unlocked is True
    assert settings_manager.load().codex_usage_unlocked is True
    assert application.tray is not None
    assert application.tray.codex_usage_action.isVisible()
    application.shutdown()


def test_codex_usage_unlock_is_restored_when_application_restarts(
    qtbot: pytest.QtBot, tmp_path: Path
) -> None:
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    settings_manager = SettingsManager(tmp_path / "settings.json")
    settings_manager.save(Settings(codex_usage_unlocked=True))

    application = PetNest(
        pets_root=tmp_path / "pets",
        settings_manager=settings_manager,
        enable_tray=True,
    )
    qtbot.addWidget(application.window)

    assert application.tray is not None
    assert application.tray.codex_usage_action.isVisible()
    application.shutdown()


def test_countdown_click_opens_work_countdown_settings(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    application = PetNest(
        pets_root=tmp_path / "pets",
        settings_manager=SettingsManager(tmp_path / "settings.json"),
        enable_tray=False,
    )
    qtbot.addWidget(application.window)

    application.window.countdown_clicked.emit()

    dialog = application._settings_center_dialog
    assert dialog is not None
    assert dialog.section_list.currentRow() == 3
    dialog.reject()
    application.shutdown()


def test_work_finish_choice_persists_and_reminder_closes_on_shutdown(
    qtbot: pytest.QtBot, tmp_path: Path
) -> None:
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    settings_manager = SettingsManager(tmp_path / "settings.json")
    settings_manager.save(Settings(daily_work_end_times={str(day): "18:00" for day in range(7)}))
    application = PetNest(
        pets_root=tmp_path / "pets",
        settings_manager=settings_manager,
        enable_tray=False,
    )
    qtbot.addWidget(application.window)
    qtbot.addWidget(application.work_finish_reminder.animation_window)
    qtbot.addWidget(application.work_finish_reminder.control_window)
    application._configure_work_countdown()

    application.work_countdown.refresh(__import__("datetime").datetime(2026, 8, 14, 17, 59, 59))
    application.work_countdown.refresh(__import__("datetime").datetime(2026, 8, 14, 18, 0))
    assert application.work_finish_reminder.control_window.isVisible()

    application.work_finish_reminder.control_window.continue_button.click()

    assert application.settings.work_finish_state is not None
    assert application.settings.work_finish_state["status"] == "overtime"
    assert not application.work_finish_reminder.control_window.isVisible()
    assert settings_manager.load().work_finish_state == application.settings.work_finish_state

    application.shutdown()
    assert not application.work_finish_reminder.animation_window.isVisible()
    assert not application.work_finish_reminder.control_window.isVisible()


def test_work_finish_prompt_temporarily_hides_and_restores_visible_pet(
    qtbot: pytest.QtBot, tmp_path: Path
) -> None:
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    settings_manager = SettingsManager(tmp_path / "settings.json")
    settings_manager.save(Settings(daily_work_end_times={str(day): "18:00" for day in range(7)}))
    application = PetNest(
        pets_root=tmp_path / "pets",
        settings_manager=settings_manager,
        enable_tray=False,
    )
    qtbot.addWidget(application.window)
    qtbot.addWidget(application.work_finish_reminder.animation_window)
    qtbot.addWidget(application.work_finish_reminder.control_window)
    application._configure_work_countdown()
    application.window.show()

    application.work_countdown.refresh(__import__("datetime").datetime(2026, 8, 14, 17, 59, 59))
    application.work_countdown.refresh(__import__("datetime").datetime(2026, 8, 14, 18, 0))
    assert not application.window.isVisible()

    application.work_finish_reminder.control_window.continue_button.click()

    assert application.window.isVisible()
    application.shutdown()


def test_work_finish_prompt_does_not_restore_pet_hidden_before_prompt(
    qtbot: pytest.QtBot, tmp_path: Path
) -> None:
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    settings_manager = SettingsManager(tmp_path / "settings.json")
    settings_manager.save(Settings(daily_work_end_times={str(day): "18:00" for day in range(7)}))
    application = PetNest(
        pets_root=tmp_path / "pets",
        settings_manager=settings_manager,
        enable_tray=False,
    )
    qtbot.addWidget(application.window)
    qtbot.addWidget(application.work_finish_reminder.animation_window)
    qtbot.addWidget(application.work_finish_reminder.control_window)
    application._configure_work_countdown()
    application.window.hide()

    application.work_countdown.refresh(__import__("datetime").datetime(2026, 8, 14, 17, 59, 59))
    application.work_countdown.refresh(__import__("datetime").datetime(2026, 8, 14, 18, 0))
    application.work_finish_reminder.control_window.finish_button.click()

    assert not application.window.isVisible()
    application.shutdown()


def test_work_finish_timeout_keeps_countdown_running_and_restores_pet(
    qtbot: pytest.QtBot, tmp_path: Path
) -> None:
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    settings_manager = SettingsManager(tmp_path / "settings.json")
    settings_manager.save(Settings(daily_work_end_times={str(day): "18:00" for day in range(7)}))
    application = PetNest(
        pets_root=tmp_path / "pets",
        settings_manager=settings_manager,
        enable_tray=False,
    )
    qtbot.addWidget(application.window)
    qtbot.addWidget(application.work_finish_reminder.animation_window)
    qtbot.addWidget(application.work_finish_reminder.control_window)
    application._configure_work_countdown()
    application.window.show()

    application.work_countdown.refresh(__import__("datetime").datetime(2026, 8, 14, 17, 59, 59))
    application.work_countdown.refresh(__import__("datetime").datetime(2026, 8, 14, 18, 0))
    assert not application.window.isVisible()
    assert application.work_countdown.timer.isActive()

    application.work_countdown.refresh(__import__("datetime").datetime(2026, 8, 14, 18, 30))

    assert application.window.isVisible()
    assert application.work_countdown.work_finish_state is not None
    assert application.work_countdown.work_finish_state.status == "finished"
    application.shutdown()


def test_tray_show_during_prompt_takes_over_restore(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    settings_manager = SettingsManager(tmp_path / "settings.json")
    settings_manager.save(Settings(daily_work_end_times={str(day): "18:00" for day in range(7)}))
    application = PetNest(
        pets_root=tmp_path / "pets",
        settings_manager=settings_manager,
        enable_tray=True,
    )
    qtbot.addWidget(application.window)
    qtbot.addWidget(application.work_finish_reminder.animation_window)
    qtbot.addWidget(application.work_finish_reminder.control_window)
    application._configure_work_countdown()
    application.window.show()

    application.work_countdown.refresh(__import__("datetime").datetime(2026, 8, 14, 17, 59, 59))
    application.work_countdown.refresh(__import__("datetime").datetime(2026, 8, 14, 18, 0))
    assert application.tray is not None
    assert application.tray.toggle_visibility_action.text() == "显示"
    application.tray.toggle_visibility_action.trigger()
    assert application.window.isVisible()

    application.work_finish_reminder.control_window.continue_button.click()

    assert application.window.isVisible()
    assert application.tray.toggle_visibility_action.text() == "隐藏"
    application.shutdown()


def test_repeated_prompt_and_pet_switch_keep_pet_hidden_until_close(
    qtbot: pytest.QtBot, tmp_path: Path
) -> None:
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    second_root = create_sample_pet(tmp_path / "pets" / "second_pet")
    second_config = json.loads((second_root / "pet.json").read_text(encoding="utf-8"))
    second_config["id"] = "second_pet"
    second_config["name"] = "Second Pet"
    (second_root / "pet.json").write_text(json.dumps(second_config), encoding="utf-8")
    settings_manager = SettingsManager(tmp_path / "settings.json")
    settings_manager.save(
        Settings(
            current_pet_id="sample_pet",
            daily_work_end_times={str(day): "18:00" for day in range(7)},
        )
    )
    application = PetNest(
        pets_root=tmp_path / "pets",
        settings_manager=settings_manager,
        enable_tray=False,
    )
    qtbot.addWidget(application.window)
    qtbot.addWidget(application.work_finish_reminder.animation_window)
    qtbot.addWidget(application.work_finish_reminder.control_window)
    application._configure_work_countdown()
    application.window.show()

    application.work_countdown.refresh(__import__("datetime").datetime(2026, 8, 14, 17, 59, 59))
    application.work_countdown.refresh(__import__("datetime").datetime(2026, 8, 14, 18, 0))
    state = application.work_countdown.work_finish_state
    assert state is not None
    application._show_work_finish_prompt(state)
    assert application.switch_pet("second_pet")
    assert not application.window.isVisible()

    application.work_finish_reminder.control_window.finish_button.click()

    assert application.window.isVisible()
    assert application.package.identifier == "second_pet"
    application.shutdown()


def test_restore_failure_leaves_tray_show_action(
    qtbot: pytest.QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    settings_manager = SettingsManager(tmp_path / "settings.json")
    settings_manager.save(Settings(daily_work_end_times={str(day): "18:00" for day in range(7)}))
    application = PetNest(
        pets_root=tmp_path / "pets",
        settings_manager=settings_manager,
        enable_tray=True,
    )
    qtbot.addWidget(application.window)
    qtbot.addWidget(application.work_finish_reminder.animation_window)
    qtbot.addWidget(application.work_finish_reminder.control_window)
    application._configure_work_countdown()
    application.window.show()
    application.work_countdown.refresh(__import__("datetime").datetime(2026, 8, 14, 17, 59, 59))
    application.work_countdown.refresh(__import__("datetime").datetime(2026, 8, 14, 18, 0))
    original = application._apply_pet_visibility

    def fail_only_when_showing(visible: bool, *, sync_countdown: bool = True) -> None:
        if visible:
            raise RuntimeError("simulated restore failure")
        original(visible, sync_countdown=sync_countdown)

    monkeypatch.setattr(application, "_apply_pet_visibility", fail_only_when_showing)

    application.work_finish_reminder.control_window.finish_button.click()

    assert application.tray is not None
    assert application.tray.toggle_visibility_action.text() == "显示"
    application.shutdown()


def test_prompt_show_failure_restores_pet_and_releases_lease(
    qtbot: pytest.QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    settings_manager = SettingsManager(tmp_path / "settings.json")
    settings_manager.save(Settings(daily_work_end_times={str(day): "18:00" for day in range(7)}))
    application = PetNest(
        pets_root=tmp_path / "pets",
        settings_manager=settings_manager,
        enable_tray=False,
    )
    qtbot.addWidget(application.window)
    application._configure_work_countdown()
    application.window.show()
    monkeypatch.setattr(
        application.work_finish_reminder,
        "show_for",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("simulated show failure")),
    )

    application.work_countdown.refresh(__import__("datetime").datetime(2026, 8, 14, 17, 59, 59))
    application.work_countdown.refresh(__import__("datetime").datetime(2026, 8, 14, 18, 0))

    assert application.window.isVisible()
    assert not application._work_finish_visibility_lease.is_active
    application.shutdown()


def test_shutdown_cancels_lease_without_showing_pet(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    settings_manager = SettingsManager(tmp_path / "settings.json")
    settings_manager.save(Settings(daily_work_end_times={str(day): "18:00" for day in range(7)}))
    application = PetNest(
        pets_root=tmp_path / "pets",
        settings_manager=settings_manager,
        enable_tray=False,
    )
    qtbot.addWidget(application.window)
    qtbot.addWidget(application.work_finish_reminder.animation_window)
    qtbot.addWidget(application.work_finish_reminder.control_window)
    application._configure_work_countdown()
    application.window.show()
    application.work_countdown.refresh(__import__("datetime").datetime(2026, 8, 14, 17, 59, 59))
    application.work_countdown.refresh(__import__("datetime").datetime(2026, 8, 14, 18, 0))
    assert not application.window.isVisible()

    application.shutdown()

    assert not application.window.isVisible()
    assert not application._work_finish_visibility_lease.is_active


def test_empty_app_update_check_clears_stale_available_update(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    application = PetNest(
        pets_root=tmp_path / "pets",
        settings_manager=SettingsManager(tmp_path / "settings.json"),
        enable_tray=False,
    )
    qtbot.addWidget(application.window)
    application._pending_app_update = object()  # type: ignore[assignment]
    application._app_update_results.put(("check", AppUpdateCheckResult(True, False)))

    application._drain_app_update_results()

    assert application._pending_app_update is None
    application.shutdown()

    def register_startup(self, enabled: bool) -> bool:
        del enabled
        return False


class _FailingStopAdapter(_IdleAdapter):
    def stop(self) -> None:
        raise RuntimeError("simulated shutdown failure")


class _ExitOrderServer:
    def __init__(self, application: PetNest) -> None:
        self.application = application
        self.stopped_after_ui_hidden = False

    def stop(self) -> None:
        tray = self.application.tray
        self.stopped_after_ui_hidden = not self.application.window.isVisible() and (
            tray is None or not tray.isVisible()
        )


class _CursorController:
    def __init__(self, *, restore_result: bool = True) -> None:
        self.applied_paths: list[Path] = []
        self.applied_roles: list[tuple[str, Path]] = []
        self.restore_calls = 0
        self.restore_system_calls = 0
        self.restored_roles: list[str] = []
        self.restore_result = restore_result

    def apply(self, path: Path) -> bool:
        self.applied_paths.append(path)
        return True

    def apply_role(self, role: str, path: Path) -> bool:
        self.applied_roles.append((role, path))
        return True

    def restore_normal(self) -> bool:
        self.restore_calls += 1
        return self.restore_result

    def restore_role(self, role: str) -> bool:
        self.restored_roles.append(role)
        return self.restore_result

    def restore_system_defaults(self) -> bool:
        self.restore_system_calls += 1
        return self.restore_result


def _create_animation_frames(root: Path, action: str, count: int) -> None:
    directory = root / "animations" / action
    directory.mkdir(parents=True)
    for index in range(count):
        Image.new("RGBA", (16, 16), (index, 0, 0, 255)).save(directory / f"{index + 1:03d}.png")


def _create_reloadable_pet(root: Path) -> Path:
    root.mkdir(parents=True)
    (root / "pet.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "id": "reloadable_pet",
                "name": "Reloadable Pet",
                "version": "1.0.0",
                "canvas": {"width": 16, "height": 16},
                "animations": {
                    "idle": {"path": "animations/idle", "fps": 8, "loop": True, "priority": 10},
                    "hover": {"path": "animations/hover", "fps": 8, "loop": True, "priority": 20},
                },
                "bindings": {"mouse.enter": "hover"},
                "fallbacks": {},
            }
        ),
        encoding="utf-8",
    )
    _create_animation_frames(root, "idle", 1)
    _create_animation_frames(root, "hover", 1)
    return root


def _write_cursor_style(root: Path, identifier: str, roles: tuple[str, ...]) -> None:
    style_root = root / identifier
    style_root.mkdir(parents=True)
    (style_root / "style.json").write_text(
        json.dumps(
            {
                "id": identifier,
                "name": identifier,
                "preview": "arrow.png",
                "arrow": "arrow.cur",
                "hotspot": [0, 0],
            }
        ),
        encoding="utf-8",
    )
    (style_root / "arrow.png").write_bytes(b"preview")
    for role in roles:
        (style_root / f"{role}.cur").write_bytes(role.encode())


def test_resource_directory_uses_verified_current_generation(tmp_path: Path) -> None:
    cache_root = tmp_path / "remote-resources"
    version_root = cache_root / "versions" / "2026.8.12-0123456789ab"
    resources = version_root / "resources"
    (resources / "cursors").mkdir(parents=True)
    manifest_payload = json.dumps(
        {"schema_version": 1, "catalog_version": "2026.8.12", "resources": []}
    ).encode("utf-8")
    (version_root / "manifest.json").write_bytes(manifest_payload)
    cache_root.joinpath("current.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "version_id": version_root.name,
                "catalog_version": "2026.8.12",
                "manifest_sha256": hashlib.sha256(manifest_payload).hexdigest(),
            }
        ),
        encoding="utf-8",
    )

    cache = RemoteResourceCache(cache_root, "https://resources.example")

    assert resource_directory_for_cache(cache) == cache_root / "versions" / version_root.name / "resources"


def test_resource_directory_rejects_linked_current_resource_tree(tmp_path: Path) -> None:
    cache_root = tmp_path / "remote-resources"
    version_root = cache_root / "versions" / "2026.8.12-0123456789ab"
    version_root.mkdir(parents=True)
    external = tmp_path / "external-resources"
    external.mkdir()
    try:
        os.symlink(external, version_root / "resources", target_is_directory=True)
    except (OSError, NotImplementedError) as error:
        pytest.skip(f"当前平台不允许创建目录符号链接: {error}")
    manifest_payload = json.dumps(
        {"schema_version": 1, "catalog_version": "2026.8.12", "resources": []}
    ).encode("utf-8")
    (version_root / "manifest.json").write_bytes(manifest_payload)
    cache_root.joinpath("current.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "version_id": version_root.name,
                "catalog_version": "2026.8.12",
                "manifest_sha256": hashlib.sha256(manifest_payload).hexdigest(),
            }
        ),
        encoding="utf-8",
    )

    assert resource_directory_for_cache(RemoteResourceCache(cache_root, "https://resources.example")) is None


def test_resource_directory_falls_back_when_current_generation_is_missing(tmp_path: Path) -> None:
    cache = RemoteResourceCache(tmp_path / "remote-resources", "https://resources.example")

    assert resource_directory_for_cache(cache) is None


def test_resource_directory_falls_back_when_current_manifest_is_missing(tmp_path: Path) -> None:
    cache_root = tmp_path / "remote-resources"
    version_root = cache_root / "versions" / "2026.8.12-0123456789ab"
    (version_root / "resources" / "cursors").mkdir(parents=True)
    cache_root.joinpath("current.json").write_text(
        json.dumps({"schema_version": 1, "version_id": version_root.name}), encoding="utf-8"
    )

    cache = RemoteResourceCache(cache_root, "https://resources.example")

    assert resource_directory_for_cache(cache) is None


def test_resource_directory_falls_back_when_current_file_hash_is_invalid(tmp_path: Path) -> None:
    cache_root = tmp_path / "remote-resources"
    version_root = cache_root / "versions" / "2026.8.12-0123456789ab"
    relative = "resources/countdown/cream.png"
    (version_root / relative).parent.mkdir(parents=True)
    (version_root / relative).write_bytes(b"corrupt")
    manifest_payload = json.dumps(
        {
            "schema_version": 1,
            "catalog_version": "2026.8.12",
            "resources": [
                {
                    "id": "cream",
                    "type": "countdown_background",
                    "version": "1.0.0",
                    "files": [
                        {
                            "path": relative,
                            "size": 7,
                            "sha256": hashlib.sha256(b"expected").hexdigest(),
                        }
                    ],
                    "metadata": {},
                }
            ],
        },
        separators=(",", ":"),
    ).encode("utf-8")
    (version_root / "manifest.json").write_bytes(manifest_payload)
    cache_root.joinpath("current.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "catalog_version": "2026.8.12",
                "version_id": version_root.name,
                "manifest_sha256": hashlib.sha256(manifest_payload).hexdigest(),
            }
        ),
        encoding="utf-8",
    )

    cache = RemoteResourceCache(cache_root, "https://resources.example")

    assert resource_directory_for_cache(cache) is None


def test_resource_directory_materializes_bundled_fallbacks_for_old_current_views(tmp_path: Path) -> None:
    cache_root = tmp_path / "remote-resources"
    version_root = cache_root / "versions" / "2026.8.12-0123456789ab"
    relative = "resources/cursors/demo/arrow.cur"
    (version_root / relative).parent.mkdir(parents=True)
    cursor = b"cached cursor"
    (version_root / relative).write_bytes(cursor)
    manifest_payload = json.dumps(
        {
            "schema_version": 1,
            "catalog_version": "2026.8.12",
            "resources": [
                {
                    "id": "demo",
                    "type": "cursor_theme",
                    "version": "1.0.0",
                    "files": [
                        {"path": relative, "size": len(cursor), "sha256": hashlib.sha256(cursor).hexdigest()}
                    ],
                    "metadata": {},
                }
            ],
        },
        separators=(",", ":"),
    ).encode("utf-8")
    (version_root / "manifest.json").write_bytes(manifest_payload)
    cache_root.joinpath("current.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "catalog_version": "2026.8.12",
                "version_id": version_root.name,
                "manifest_sha256": hashlib.sha256(manifest_payload).hexdigest(),
            }
        ),
        encoding="utf-8",
    )
    seed_root = tmp_path / "bundle"
    seed_skin = seed_root / "assets" / "countdown" / "night.png"
    seed_skin.parent.mkdir(parents=True)
    seed_skin.write_bytes(b"bundled night")

    cache = RemoteResourceCache(cache_root, "https://resources.example", seed_root=seed_root)
    directory = resource_directory_for_cache(cache)

    assert directory is not None
    assert (directory / "countdown" / "night.png").read_bytes() == b"bundled night"
    assert cache.current_root is not None and cache.current_root != version_root


def test_resource_directory_repairs_stale_unlisted_files_from_old_views(tmp_path: Path) -> None:
    cache_root = tmp_path / "remote-resources"
    version_root = cache_root / "versions" / "2026.8.12-0123456789ab"
    stale_relative = "resources/countdown/night.png"
    extra_relative = "resources/countdown/removed.png"
    (version_root / stale_relative).parent.mkdir(parents=True)
    (version_root / stale_relative).write_bytes(b"stale remote bytes")
    (version_root / extra_relative).write_bytes(b"removed extra")
    manifest_payload = json.dumps(
        {"schema_version": 1, "catalog_version": "2026.8.12", "resources": []}
    ).encode("utf-8")
    (version_root / "manifest.json").write_bytes(manifest_payload)
    cache_root.joinpath("current.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "version_id": version_root.name,
                "catalog_version": "2026.8.12",
                "manifest_sha256": hashlib.sha256(manifest_payload).hexdigest(),
            }
        ),
        encoding="utf-8",
    )
    seed_root = tmp_path / "bundle"
    seed_file = seed_root / "assets" / "countdown" / "night.png"
    seed_file.parent.mkdir(parents=True)
    seed_file.write_bytes(b"bundled night")

    cache = RemoteResourceCache(cache_root, "https://resources.example", seed_root=seed_root)
    directory = resource_directory_for_cache(cache)

    assert directory is not None
    assert (directory / "countdown" / "night.png").read_bytes() == b"bundled night"
    assert not (directory / "countdown" / "removed.png").exists()


def test_resource_directory_uses_verified_legacy_cache(tmp_path: Path) -> None:
    relative = "resources/countdown/cream.png"
    content = b"legacy countdown"
    legacy_file = tmp_path / relative
    legacy_file.parent.mkdir(parents=True)
    legacy_file.write_bytes(content)
    manifest = {
        "schema_version": 1,
        "catalog_version": "2026.8.11",
        "resources": [
            {
                "id": "cream",
                "type": "countdown_background",
                "version": "1.0.0",
                "files": [{"path": relative, "size": len(content), "sha256": hashlib.sha256(content).hexdigest()}],
                "metadata": {},
            }
        ],
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    cache = RemoteResourceCache(tmp_path, "https://resources.example")

    assert resource_directory_for_cache(cache) == tmp_path / "resources"


def test_tray_resource_update_action_shows_and_clears_blue_badge(
    qtbot: pytest.QtBot, tmp_path: Path
) -> None:
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    application = PetNest(
        pets_root=tmp_path / "pets",
        settings_manager=SettingsManager(tmp_path / "settings.json"),
        enable_tray=True,
    )
    assert application.tray is not None
    qtbot.addWidget(application.window)

    application.tray.set_resource_update_available(True)
    assert not application.tray.resource_update_action.text().startswith("●")
    assert application.tray.resource_update_action.text() == "立即检查资源更新"
    assert not application.tray.resource_update_action.icon().isNull()

    application.tray.set_resource_update_available(False)
    assert not application.tray.resource_update_action.text().startswith("●")
    assert application.tray.resource_update_action.icon().isNull()

    application.tray.set_resource_update_loading(True)
    assert not application.tray.resource_update_action.isEnabled()
    assert "正在下载" in application.tray.resource_update_action.text()
    application.tray.set_resource_update_progress(43)
    assert "43%" in application.tray.resource_update_action.text()
    application.tray.set_resource_update_loading(False)
    assert application.tray.resource_update_action.isEnabled()
    application.shutdown()


def test_manual_resource_action_bypasses_check_throttle(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    application = PetNest(
        pets_root=tmp_path / "pets",
        settings_manager=SettingsManager(tmp_path / "settings.json"),
        enable_tray=False,
    )
    qtbot.addWidget(application.window)
    checks: list[bool] = []
    application._schedule_resource_check = lambda force: checks.append(force)  # type: ignore[method-assign]

    application._handle_resource_update_action()

    assert checks == [True]
    application.shutdown()


def test_manual_resource_check_starts_download_when_update_is_found(
    qtbot: pytest.QtBot, tmp_path: Path
) -> None:
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    application = PetNest(
        pets_root=tmp_path / "pets",
        settings_manager=SettingsManager(tmp_path / "settings.json"),
        enable_tray=False,
    )
    qtbot.addWidget(application.window)
    applies: list[bool] = []
    application._schedule_resource_apply = lambda: applies.append(True)  # type: ignore[method-assign]

    application._handle_resource_check_result(
        RemoteResourceCheckResult(True, False, True, catalog_version="2026.8.13"),
        manual=True,
    )

    assert applies == [True]
    application.shutdown()


def test_unsupported_adapter_is_a_safe_noop(caplog: pytest.LogCaptureFixture) -> None:
    adapter = UnsupportedPlatformAdapter("test")

    adapter.start()
    adapter.start()

    assert adapter.get_idle_seconds() is None
    assert adapter.register_startup(True) is False
    assert adapter.register_startup(False) is False
    assert sum("暂不支持" in record.message for record in caplog.records) == 1


def test_application_shutdown_stops_server_and_persists_window_position(
    qtbot: pytest.QtBot, tmp_path: Path
) -> None:
    app = QApplication.instance() or QApplication([])
    del app  # Qt 应用由 pytest-qt 生命周期管理。
    settings_manager = SettingsManager(tmp_path / "settings.json")
    settings_manager.save(Settings(work_countdown_enabled=False))
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    application = PetNest(
        pets_root=tmp_path / "pets",
        settings_manager=settings_manager,
        enable_tray=False,
    )
    qtbot.addWidget(application.window)
    application.window.move(123, 234)
    application.start()

    assert application.window.isVisible()
    application.shutdown()

    saved = settings_manager.load()
    assert (saved.window_x, saved.window_y) == (123, 234)
    assert application.external_server is None


def test_tray_quit_still_hides_window_when_cleanup_fails(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    del app
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    application = PetNest(
        pets_root=tmp_path / "pets",
        settings_manager=SettingsManager(tmp_path / "settings.json"),
        platform_adapter=_FailingStopAdapter(),
        enable_tray=True,
    )
    qtbot.addWidget(application.window)
    application.start()

    application.tray.quit_action.trigger()

    assert application._shutdown is True
    assert not application.window.isVisible()
    assert not application.tray.isVisible()


def test_tray_quit_hides_the_ui_before_stopping_external_services(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    del app
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    application = PetNest(
        pets_root=tmp_path / "pets",
        settings_manager=SettingsManager(tmp_path / "settings.json"),
        enable_tray=True,
    )
    qtbot.addWidget(application.window)
    application.start()
    server = _ExitOrderServer(application)
    application.external_server = server  # type: ignore[assignment]

    application.tray.quit_action.trigger()

    assert server.stopped_after_ui_hidden is True


def test_application_restores_pending_cursor_before_showing_window(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    del app
    settings_manager = SettingsManager(tmp_path / "settings.json")
    settings_manager.save(Settings(cursor_restore_pending=True))
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    cursor_controller = _CursorController()

    application = PetNest(
        pets_root=tmp_path / "pets",
        settings_manager=settings_manager,
        cursor_controller=cursor_controller,
        enable_tray=False,
    )
    qtbot.addWidget(application.window)

    assert cursor_controller.restore_system_calls == 1
    assert settings_manager.load().cursor_restore_pending is False


def test_application_applies_selected_cursor_and_restores_it_on_shutdown(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    del app
    settings_manager = SettingsManager(tmp_path / "settings.json")
    settings_manager.save(Settings(cursor_style_enabled=True, cursor_style_id="petnest-paw"))
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    cursor_controller = _CursorController()
    application = PetNest(
        pets_root=tmp_path / "pets",
        settings_manager=settings_manager,
        cursor_controller=cursor_controller,
        enable_tray=False,
    )
    qtbot.addWidget(application.window)

    application.start()
    application.shutdown()

    assert [path.name for path in cursor_controller.applied_paths] == ["arrow.cur"]
    assert {role for role, _path in cursor_controller.applied_roles} == {
        "busy",
        "move",
        "resize_diag_1",
        "resize_diag_2",
        "resize_horizontal",
        "resize_vertical",
        "text",
    }
    assert cursor_controller.restore_system_calls == 1
    assert settings_manager.load().cursor_restore_pending is False


def test_switching_to_theme_without_busy_restores_system_busy_cursor(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    del app
    settings_manager = SettingsManager(tmp_path / "settings.json")
    settings_manager.save(Settings(cursor_style_enabled=True, cursor_style_id="complete"))
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    styles_root = tmp_path / "cursor_styles"
    _write_cursor_style(styles_root, "complete", ("arrow", "busy"))
    _write_cursor_style(styles_root, "partial", ("arrow",))
    cursor_controller = _CursorController()
    application = PetNest(
        pets_root=tmp_path / "pets",
        settings_manager=settings_manager,
        cursor_controller=cursor_controller,
        enable_tray=False,
    )
    qtbot.addWidget(application.window)
    application.cursor_catalog = CursorStyleCatalog(styles_root)
    application.start()

    restore_calls_before_switch = cursor_controller.restore_system_calls
    application.apply_settings(replace(application.settings, cursor_style_id="partial"))

    assert cursor_controller.restore_system_calls == restore_calls_before_switch + 1


def test_failed_cursor_recovery_keeps_the_pending_marker_for_the_next_start(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    del app
    settings_manager = SettingsManager(tmp_path / "settings.json")
    settings_manager.save(Settings(cursor_restore_pending=True))
    create_sample_pet(tmp_path / "pets" / "sample_pet")

    application = PetNest(
        pets_root=tmp_path / "pets",
        settings_manager=settings_manager,
        cursor_controller=_CursorController(restore_result=False),
        enable_tray=False,
    )
    qtbot.addWidget(application.window)
    application.start()

    assert application.settings.cursor_restore_pending is True
    assert settings_manager.load().cursor_restore_pending is True


def test_application_reveal_restores_a_hidden_pet_window(
    qtbot: pytest.QtBot,
    tmp_path: Path,
) -> None:
    app = QApplication.instance() or QApplication([])
    del app
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    application = PetNest(
        pets_root=tmp_path / "pets", settings_manager=SettingsManager(tmp_path / "settings.json"), enable_tray=False
    )
    qtbot.addWidget(application.window)
    application.start()
    screen = QApplication.primaryScreen()
    assert screen is not None
    cursor_position = screen.availableGeometry().center()
    application.window.move(screen.availableGeometry().topLeft())
    application.window.hide()

    application.reveal()

    assert application.window.isVisible()
    assert application.window.frameGeometry().contains(cursor_position)
    saved = application.settings_manager.load()
    assert (saved.window_x, saved.window_y) == (
        application.window.pos().x(),
        application.window.pos().y(),
    )


def test_pet_context_menu_updates_scale_pause_and_always_on_top(
    qtbot: pytest.QtBot, tmp_path: Path
) -> None:
    app = QApplication.instance() or QApplication([])
    del app
    settings_manager = SettingsManager(tmp_path / "settings.json")
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    application = PetNest(
        pets_root=tmp_path / "pets", settings_manager=settings_manager, enable_tray=False
    )
    qtbot.addWidget(application.window)

    application._sync_pet_context_menu()
    application.zoom_in_action.trigger()
    application.pause_context_action.trigger()
    application.always_on_top_context_action.trigger()

    assert application.window.scale == 1.1
    assert application.window.player.is_paused
    assert application.settings.always_on_top is False
    assert settings_manager.load().scale == 1.1
    assert settings_manager.load().animation_paused is True
    assert settings_manager.load().always_on_top is False


def test_mouse_follow_moves_pet_without_replacing_its_saved_resting_position(
    qtbot: pytest.QtBot, tmp_path: Path
) -> None:
    app = QApplication.instance() or QApplication([])
    del app
    settings_manager = SettingsManager(tmp_path / "settings.json")
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    application = PetNest(pets_root=tmp_path / "pets", settings_manager=settings_manager, enable_tray=False)
    qtbot.addWidget(application.window)
    application.window.move(100, 100)
    application.start()

    application.apply_settings(replace(application.settings, mouse_follow_enabled=True, mouse_follow_scale=0.55))
    application.update_mouse_follow(QPoint(500, 400), now_ms=0)
    application.update_mouse_follow(QPoint(510, 400), now_ms=33)

    assert application.mouse_follow_timer.isActive()
    assert application.window.pos() != QPoint(100, 100)

    application.apply_settings(replace(application.settings, mouse_follow_enabled=False))

    assert not application.mouse_follow_timer.isActive()
    assert application.window.pos() == QPoint(100, 100)


def test_mouse_follow_does_not_move_window_when_target_is_unchanged(
    qtbot: pytest.QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = QApplication.instance() or QApplication([])
    del app
    settings_manager = SettingsManager(tmp_path / "settings.json")
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    application = PetNest(pets_root=tmp_path / "pets", settings_manager=settings_manager, enable_tray=False)
    qtbot.addWidget(application.window)
    application.start()
    application.apply_settings(replace(application.settings, mouse_follow_enabled=True, mouse_follow_scale=0.55))

    move_calls: list[QPoint] = []
    original_move = application.window.move

    def record_move(position: QPoint) -> None:
        move_calls.append(QPoint(position))
        original_move(position)

    monkeypatch.setattr(application.window, "move", record_move)
    cursor = QPoint(500, 400)
    application.update_mouse_follow(cursor, now_ms=0)
    move_calls.clear()
    application.update_mouse_follow(cursor, now_ms=20)

    assert move_calls == []


def test_application_clamps_saved_position_that_is_outside_all_screens(
    qtbot: pytest.QtBot, tmp_path: Path
) -> None:
    app = QApplication.instance() or QApplication([])
    del app
    settings_manager = SettingsManager(tmp_path / "settings.json")
    settings_manager.save(Settings(window_x=1_000_000, window_y=1_000_000))
    create_sample_pet(tmp_path / "pets" / "sample_pet")

    application = PetNest(
        pets_root=tmp_path / "pets",
        settings_manager=settings_manager,
        enable_tray=False,
    )
    qtbot.addWidget(application.window)
    available = QApplication.primaryScreen().availableGeometry()

    assert application.window.x() <= available.right()
    assert application.window.y() <= available.bottom()


def test_check_mode_can_load_bundled_sample_package() -> None:
    assert PetNest.check_installation() == 0


def test_application_assigns_a_stable_device_id_for_lan_identity(
    qtbot: pytest.QtBot, tmp_path: Path
) -> None:
    app = QApplication.instance() or QApplication([])
    del app
    settings_manager = SettingsManager(tmp_path / "settings.json")
    create_sample_pet(tmp_path / "pets" / "sample_pet")

    application = PetNest(pets_root=tmp_path / "pets", settings_manager=settings_manager, enable_tray=False)
    qtbot.addWidget(application.window)

    first_id = application.settings.device_id
    assert len(first_id) == 32
    assert SettingsManager(tmp_path / "settings.json").load().device_id == first_id

    application.shutdown()
    second = SettingsManager(tmp_path / "settings.json").load()
    assert second.device_id == first_id


def test_lan_service_follows_the_user_presence_toggle(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    del app
    settings_manager = SettingsManager(tmp_path / "settings.json")
    settings_manager.save(Settings(lan_interaction_enabled=True))
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    application = PetNest(pets_root=tmp_path / "pets", settings_manager=settings_manager, enable_tray=False)
    qtbot.addWidget(application.window)
    application.start()

    assert application.lan_service.is_running
    application.apply_settings(replace(application.settings, lan_interaction_enabled=False))
    assert not application.lan_service.is_running


def test_shutdown_clears_remote_interaction_overlay(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    del app
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    application = PetNest(pets_root=tmp_path / "pets", settings_manager=SettingsManager(tmp_path / "settings.json"), enable_tray=False)
    qtbot.addWidget(application.window)
    application.window.show_interaction_bubble("测试提示")

    application.shutdown()

    assert application.window.interaction_bubble_text is None


def test_group_chat_pet_bubble_can_be_disabled_without_silencing_private_chat(
    qtbot: pytest.QtBot,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    application = PetNest(
        pets_root=tmp_path / "pets",
        settings_manager=SettingsManager(tmp_path / "settings.json"),
        enable_tray=False,
    )
    qtbot.addWidget(application.window)
    bubbles: list[str] = []
    monkeypatch.setattr(application.window, "show_interaction_bubble", bubbles.append)
    application.settings = replace(
        application.settings,
        lan_group_chat_notifications_enabled=False,
    )

    application._handle_lan_chat(
        SimpleNamespace(
            sender_name="小林",
            kind=ChatMessageKind.TEXT,
            text="群里见",
            is_group=True,
        )
    )
    application._handle_lan_chat(
        SimpleNamespace(
            sender_name="小林",
            kind=ChatMessageKind.TEXT,
            text="私聊仍提醒",
            is_group=False,
        )
    )

    assert bubbles == ["小林：私聊仍提醒"]
    application.settings = replace(
        application.settings,
        lan_group_chat_notifications_enabled=True,
    )
    application._handle_lan_chat(
        SimpleNamespace(
            sender_name="小林",
            kind=ChatMessageKind.EMOJI,
            text="😊",
            is_group=True,
        )
    )
    assert bubbles[-1] == "群聊 · 小林：😊"
    application.shutdown()


def test_frozen_application_bootstraps_the_configured_writable_pets_root(
    qtbot: pytest.QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = QApplication.instance() or QApplication([])
    del app
    bundled = tmp_path / "bundled"
    create_sample_pet(bundled / "sample_pet")
    custom_root = tmp_path / "custom-pets"
    settings_manager = SettingsManager(tmp_path / "settings.json")
    settings_manager.save(Settings(pets_root=str(custom_root)))
    monkeypatch.setattr("petnest.app.bundled_pets_directory", lambda: bundled)
    monkeypatch.setattr("petnest.app.sys.frozen", True, raising=False)

    application = PetNest(settings_manager=settings_manager, enable_tray=False)
    qtbot.addWidget(application.window)

    assert application.pets_root == custom_root
    assert application.package.identifier == "sample_pet"
    assert (custom_root / "sample_pet" / "pet.json").exists()


def test_application_migrates_legacy_animation_override_into_shareable_pet_json(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    del app
    settings_manager = SettingsManager(tmp_path / "settings.json")
    settings_manager.path.write_text(json.dumps({
        "schema_version": 5,
        "animation_overrides": {
            "sample_pet": {
                "idle": {"mode": "per_frame", "speed_multiplier": 1.0, "frame_durations_ms": [200, 80, 120, 160]}
            }
        },
    }), encoding="utf-8")
    create_sample_pet(tmp_path / "pets" / "sample_pet")

    application = PetNest(pets_root=tmp_path / "pets", settings_manager=settings_manager, enable_tray=False)
    qtbot.addWidget(application.window)

    saved_package = json.loads((tmp_path / "pets" / "sample_pet" / "pet.json").read_text(encoding="utf-8"))
    saved_settings = json.loads(settings_manager.path.read_text(encoding="utf-8"))

    assert application.package.animations["idle"].frame_durations_ms == (200, 80, 120, 160)
    assert saved_package["animations"]["idle"]["frame_durations_ms"] == [200, 80, 120, 160]
    assert "animation_overrides" not in saved_settings


def test_animation_editor_shows_a_clear_error_when_pet_json_cannot_be_written(
    qtbot: pytest.QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = QApplication.instance() or QApplication([])
    del app
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    application = PetNest(
        pets_root=tmp_path / "pets", settings_manager=SettingsManager(tmp_path / "settings.json"), enable_tray=False
    )
    qtbot.addWidget(application.window)

    monkeypatch.setattr(
        application.action_synchronizer,
        "update_frame_durations",
        lambda *_args: (_ for _ in ()).throw(AnimationActionSyncError("访问被拒绝")),
    )

    result = application._save_animation_timelines(application.package, {"idle": (200, 80, 120, 160)})

    assert not result.success
    assert result.message == "无法保存动画时长：访问被拒绝"
    application.shutdown()


def test_reload_current_pet_syncs_new_action_and_notifies_tray(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    del app
    package_root = _create_reloadable_pet(tmp_path / "pets" / "reloadable_pet")
    _create_animation_frames(package_root, "sleep", 1)
    application = PetNest(
        pets_root=tmp_path / "pets", settings_manager=SettingsManager(tmp_path / "settings.json"), enable_tray=True
    )
    qtbot.addWidget(application.window)
    messages: list[tuple[str, str]] = []
    assert application.tray is not None
    application.tray.showMessage = lambda title, message: messages.append((title, message))

    assert application.reload_current_pet() is True

    assert "sleep" in application.package.animations
    assert messages == [("PetNest", "已自动登记：sleep（1 帧）")]


def test_reload_current_pet_notifies_added_actions_in_sync_order(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    del app
    package_root = _create_reloadable_pet(tmp_path / "pets" / "reloadable_pet")
    _create_animation_frames(package_root, "sleep", 6)
    _create_animation_frames(package_root, "bored", 2)
    application = PetNest(
        pets_root=tmp_path / "pets", settings_manager=SettingsManager(tmp_path / "settings.json"), enable_tray=True
    )
    qtbot.addWidget(application.window)
    messages: list[tuple[str, str]] = []
    assert application.tray is not None
    application.tray.showMessage = lambda title, message: messages.append((title, message))

    assert application.reload_current_pet() is True

    assert messages == [("PetNest", "已自动登记：bored（2 帧）、sleep（6 帧）")]


def test_reload_current_pet_without_added_actions_does_not_notify_tray(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    del app
    _create_reloadable_pet(tmp_path / "pets" / "reloadable_pet")
    application = PetNest(
        pets_root=tmp_path / "pets", settings_manager=SettingsManager(tmp_path / "settings.json"), enable_tray=True
    )
    qtbot.addWidget(application.window)
    messages: list[tuple[str, str]] = []
    assert application.tray is not None
    application.tray.showMessage = lambda title, message: messages.append((title, message))

    assert application.reload_current_pet() is True

    assert messages == []


def test_animation_editor_legacy_entry_routes_to_exchange_page(
    qtbot: pytest.QtBot, tmp_path: Path
) -> None:
    app = QApplication.instance() or QApplication([])
    del app
    package_root = _create_reloadable_pet(tmp_path / "pets" / "reloadable_pet")
    config = json.loads((package_root / "pet.json").read_text(encoding="utf-8"))
    config["animations"]["idle"]["frame_durations_ms"] = [120]
    (package_root / "pet.json").write_text(json.dumps(config), encoding="utf-8")
    application = PetNest(
        pets_root=tmp_path / "pets", settings_manager=SettingsManager(tmp_path / "settings.json"), enable_tray=False
    )
    qtbot.addWidget(application.window)
    application.show_animation_editor_dialog()

    assert application._pet_action_exchange_dialog is not None
    assert application._pet_action_exchange_dialog.current_page_name() == "编辑动作"
    application._pet_action_exchange_dialog.close()
    application.shutdown()


def test_refresh_pets_syncs_frames_added_to_a_newly_copied_pet_before_discovery(
    qtbot: pytest.QtBot, tmp_path: Path
) -> None:
    app = QApplication.instance() or QApplication([])
    del app
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    application = PetNest(
        pets_root=tmp_path / "pets", settings_manager=SettingsManager(tmp_path / "settings.json"), enable_tray=False
    )
    qtbot.addWidget(application.window)
    package_root = _create_reloadable_pet(tmp_path / "pets" / "pingan")
    config = json.loads((package_root / "pet.json").read_text(encoding="utf-8"))
    config["id"] = "pingan"
    config["name"] = "平安"
    config["animations"]["idle"]["frame_durations_ms"] = [120]
    (package_root / "pet.json").write_text(json.dumps(config), encoding="utf-8")
    Image.new("RGBA", (16, 16), (1, 0, 0, 255)).save(package_root / "animations" / "idle" / "002.png")

    application.refresh_pets()

    assert {package.identifier for package in application.packages} == {"sample_pet", "pingan"}
    saved = json.loads((package_root / "pet.json").read_text(encoding="utf-8"))
    assert saved["animations"]["idle"]["frame_durations_ms"] == [120, 120]


def test_reload_current_pet_preserves_current_package_when_sync_fails(qtbot: pytest.QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app = QApplication.instance() or QApplication([])
    del app
    _create_reloadable_pet(tmp_path / "pets" / "reloadable_pet")
    application = PetNest(
        pets_root=tmp_path / "pets", settings_manager=SettingsManager(tmp_path / "settings.json"), enable_tray=False
    )
    qtbot.addWidget(application.window)
    previous_package = application.package
    monkeypatch.setattr(
        application.action_synchronizer,
        "sync",
        lambda root: (_ for _ in ()).throw(AnimationActionSyncError(f"cannot sync {root}")),
    )

    assert application.reload_current_pet() is False

    assert application.package is previous_package
    assert application.window.package is previous_package


def test_reload_current_pet_rolls_back_window_and_stays_silent_when_loading_partially_fails(
    qtbot: pytest.QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = QApplication.instance() or QApplication([])
    del app
    package_root = _create_reloadable_pet(tmp_path / "pets" / "reloadable_pet")
    _create_animation_frames(package_root, "sleep", 1)
    config_path = package_root / "pet.json"
    original_config = config_path.read_bytes()
    application = PetNest(
        pets_root=tmp_path / "pets", settings_manager=SettingsManager(tmp_path / "settings.json"), enable_tray=True
    )
    qtbot.addWidget(application.window)
    application.window.move(123, 234)
    application.window.handle_pet_event(PetEvent("mouse.enter", source="test"))
    application.window.set_paused(True)
    previous_package = application.package
    previous_position = application.window.pos()
    messages: list[tuple[str, str]] = []
    assert application.tray is not None
    application.tray.showMessage = lambda title, message: messages.append((title, message))
    original_load_package = application.window.load_package
    calls = 0

    def partially_failing_load_package(package: object) -> None:
        nonlocal calls
        calls += 1
        original_load_package(package)
        if calls == 1:
            raise RuntimeError("simulated partial load failure")

    monkeypatch.setattr(application.window, "load_package", partially_failing_load_package)

    assert application.reload_current_pet() is False

    assert calls == 2
    assert application.package is previous_package
    assert application.window.package is previous_package
    assert application.window.pos() == previous_position
    assert application.window.current_action == "hover"
    assert application.window.player.current_frame is not None
    assert application.window.player.is_paused
    assert messages == []
    assert config_path.read_bytes() == original_config

    assert application.reload_current_pet() is True

    assert messages == [("PetNest", "已自动登记：sleep（1 帧）")]


def test_reload_current_pet_rolls_back_window_when_position_move_fails(
    qtbot: pytest.QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = QApplication.instance() or QApplication([])
    del app
    package_root = _create_reloadable_pet(tmp_path / "pets" / "reloadable_pet")
    _create_animation_frames(package_root, "sleep", 1)
    application = PetNest(
        pets_root=tmp_path / "pets", settings_manager=SettingsManager(tmp_path / "settings.json"), enable_tray=False
    )
    qtbot.addWidget(application.window)
    application.window.move(123, 234)
    application.window.handle_pet_event(PetEvent("mouse.enter", source="test"))
    application.window.set_paused(True)
    previous_package = application.package
    previous_position = application.window.pos()
    original_move = application.window.move
    calls = 0

    def move_then_fail(position: object) -> None:
        nonlocal calls
        calls += 1
        original_move(position)
        if calls == 2:
            raise RuntimeError("simulated position failure")

    monkeypatch.setattr(application.window, "move", move_then_fail)

    assert application.reload_current_pet() is False

    assert calls == 4
    assert application.package is previous_package
    assert application.window.package is previous_package
    assert application.window.pos() == previous_position
    assert application.window.current_action == "hover"
    assert application.window.player.is_paused


def test_application_publishes_system_idle_events_only_on_boundaries(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    del app
    settings_manager = SettingsManager(tmp_path / "settings.json")
    settings_manager.save(Settings(system_idle_enabled=True, system_bored_seconds=30, system_sleep_seconds=180))
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    adapter = _IdleAdapter()
    application = PetNest(
        pets_root=tmp_path / "pets", settings_manager=settings_manager, platform_adapter=adapter, enable_tray=False
    )
    qtbot.addWidget(application.window)
    events: list[str] = []
    application.event_bus.subscribe(lambda event: events.append(event.event_name))

    adapter.idle_seconds = 30
    application._check_system_idle()
    adapter.idle_seconds = 180
    application._check_system_idle()
    adapter.idle_seconds = 1
    application._check_system_idle()

    assert events == ["system.bored", "system.sleep", "system.wake"]


def test_enabling_system_idle_in_settings_starts_monitor_immediately(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    del app
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    settings_manager = SettingsManager(tmp_path / "settings.json")
    settings_manager.save(Settings(system_idle_enabled=False))
    application = PetNest(
        pets_root=tmp_path / "pets", settings_manager=settings_manager,
        platform_adapter=_IdleAdapter(), enable_tray=False,
    )
    qtbot.addWidget(application.window)

    application.apply_settings(replace(application.settings, system_idle_enabled=True))

    assert application.system_idle_timer.isActive()


def test_unrelated_settings_change_does_not_republish_current_idle_state(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    del app
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    adapter = _IdleAdapter(30)
    settings_manager = SettingsManager(tmp_path / "settings.json")
    settings_manager.save(Settings(system_idle_enabled=False))
    application = PetNest(
        pets_root=tmp_path / "pets", settings_manager=settings_manager,
        platform_adapter=adapter, enable_tray=False,
    )
    qtbot.addWidget(application.window)
    events: list[str] = []
    application.event_bus.subscribe(lambda event: events.append(event.event_name))
    application.apply_settings(replace(application.settings, system_idle_enabled=True))

    application.apply_settings(replace(application.settings, scale=1.1))

    assert events == ["system.bored"]
