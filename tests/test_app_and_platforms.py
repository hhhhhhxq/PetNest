"""应用装配与平台安全降级的回归测试。"""

from __future__ import annotations

import json
import hashlib
import os
import socket
from dataclasses import replace
from datetime import date
from pathlib import Path
from threading import Event, Thread
from time import monotonic
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PIL import Image
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox
from PySide6.QtCore import QPoint, QRect, QThread, Qt

from petnest.app import PetNest, effect_directories_for, resource_directory_for_cache
from petnest.core.animation_action_synchronizer import AnimationActionSyncError
from petnest.core.app_update import AppUpdateCheckResult
from petnest.core.cursor_style_catalog import CursorStyleCatalog
from petnest.core.codex_link import CodexHookManager
from petnest.core.codex_discovery import (
    CodexAvailabilityState,
    CodexLinkAvailability,
)
from petnest.core.codex_plugin import CodexPluginStatus
from petnest.core.codex_session_log import CodexLogSourceStatus, CodexSessionLogWatcher
from petnest.core.remote_resource_cache import RemoteResourceCache
from petnest.core.remote_resource_manifest import ResourceManifest
from petnest.core.remote_resource_update import RemoteResourceApplyResult, RemoteResourceCheckResult
from petnest.core.settings_manager import SettingsManager
from petnest.models.event import EventName, PetEvent
from petnest.models.lan_interaction import ChatMessageKind, DangerAlert, InteractionKind, LanPeer
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


class _CodexLogWatcher:
    def __init__(self) -> None:
        self.started = 0
        self.stopped = 0
        self.events: list[PetEvent] = []
        self.status = CodexLogSourceStatus("stopped", "未启动")
        self.configured_home: Path | None = None
        self.root = Path("C:/unused-codex-home/sessions")
        self.global_state_path = self.root.parent / ".codex-global-state.json"

    @property
    def is_running(self) -> bool:
        return self.started > self.stopped

    def start(self) -> None:
        self.started += 1
        self.status = CodexLogSourceStatus("waiting", "等待新的 Codex 任务")

    def reconfigure(self, codex_home: Path) -> None:
        home = codex_home.expanduser().resolve()
        self.configured_home = home
        self.root = home / "sessions"
        self.global_state_path = home / ".codex-global-state.json"

    def stop(self) -> None:
        self.stopped += 1
        self.status = CodexLogSourceStatus("stopped", "未启动")

    def poll(self) -> tuple[PetEvent, ...]:
        events, self.events = tuple(self.events), []
        if events:
            self.status = CodexLogSourceStatus("active", "已联动 · 本地日志回退")
        return events


class _CodexPluginManager:
    def __init__(self, status: CodexPluginStatus | None = None) -> None:
        self.status = status or CodexPluginStatus.missing()
        self.codex_home: Path | None = None
        self.inspected = 0
        self.configured = 0
        self.removed = 0

    def inspect(self) -> CodexPluginStatus:
        self.inspected += 1
        return self.status

    def install_or_repair(self) -> CodexPluginStatus:
        self.configured += 1
        self.status = CodexPluginStatus.pending()
        return self.status

    def remove(self) -> CodexPluginStatus:
        self.removed += 1
        self.status = CodexPluginStatus.missing()
        return self.status

    def has_install_receipt(self) -> bool:
        return self.status.installed

    def set_codex_home(self, codex_home: Path) -> None:
        self.codex_home = codex_home.expanduser().resolve()


class _CodexDiscoveryService:
    def __init__(self, *results: CodexLinkAvailability) -> None:
        self.results = list(results)
        self.calls: list[Path | None] = []

    def discover(self, manual_home: Path | None) -> CodexLinkAvailability:
        self.calls.append(manual_home)
        return self.results.pop(0) if len(self.results) > 1 else self.results[0]


class _KeyboardActivityMonitor:
    def __init__(self, *, supported: bool = True, start_ok: bool = True) -> None:
        self.supported = supported
        self.start_ok = start_ok
        self.started = 0
        self.stopped = 0
        self.callback = None
        self.status_message = "已关闭" if supported else "当前版本仅支持 Windows"

    def start(self, callback) -> bool:
        self.started += 1
        self.callback = callback
        self.status_message = "监听正常" if self.start_ok else "监听不可用"
        return self.start_ok

    def stop(self) -> None:
        self.stopped += 1
        self.callback = None
        self.status_message = "已关闭" if self.supported else "当前版本仅支持 Windows"


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _send_codex_hook(port: int, token: str, event_name: str, *, session: str = "s", turn: str = "t") -> None:
    message = {
        "event": "codex.hook",
        "source": "codex-hook",
        "token": token,
        "payload": {"hook_event_name": event_name, "session_id": session, "turn_id": turn},
    }
    with socket.create_connection(("127.0.0.1", port), timeout=1) as client:
        client.sendall(json.dumps(message).encode() + b"\n")


def _keyboard_test_application(
    tmp_path: Path,
    monitor: _KeyboardActivityMonitor,
    *,
    keyboard_enabled: bool,
    codex_enabled: bool = False,
    platform_adapter: object | None = None,
) -> PetNest:
    manager = SettingsManager(tmp_path / "settings.json")
    manager.save(
        Settings(
            keyboard_working_enabled=keyboard_enabled,
            codex_link_enabled=codex_enabled,
            work_countdown_enabled=False,
            system_idle_enabled=True,
            system_bored_seconds=1,
            system_sleep_seconds=2,
        )
    )
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    return PetNest(
        pets_root=tmp_path / "pets",
        settings_manager=manager,
        platform_adapter=platform_adapter,
        keyboard_activity_monitor=monitor,
        codex_discovery=(
            _CodexDiscoveryService(
                CodexLinkAvailability(
                    CodexAvailabilityState.NOT_DETECTED,
                    "未检测到 Codex",
                    False,
                )
            )
            if codex_enabled
            else None
        ),
        enable_tray=False,
    )


def _codex_log_event(event_name: str) -> PetEvent:
    return PetEvent(
        "codex.hook",
        source="codex-log",
        payload={
            "hook_event_name": event_name,
            "session_id": "session-keyboard",
            "turn_id": "turn-keyboard",
        },
    )


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
    assert application.lan_pool_roster.path == manager.path.parent / "lan-alert-pool-roster.json"
    assert application.lan_pool_sync.roster is application.lan_pool_roster
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
    assert dialog.section_list.currentRow() == 4
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


def test_startup_update_delay_is_owned_and_stopped_with_application(
    qtbot: pytest.QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    application = PetNest(
        pets_root=tmp_path / "pets",
        settings_manager=SettingsManager(tmp_path / "settings.json"),
        enable_tray=False,
    )
    qtbot.addWidget(application.window)
    monkeypatch.setattr(application, "_schedule_resource_check", lambda force=False: None)

    application.start()

    assert application.app_update_startup_timer.parent() is application.window
    assert application.app_update_startup_timer.isSingleShot()
    assert application.app_update_startup_timer.isActive()
    application.shutdown()
    assert not application.app_update_startup_timer.isActive()


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


def test_tray_omits_resource_update_and_cursor_style_actions(
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

    texts = [action.text() for action in application.tray.menu.actions()]
    assert all("鼠标样式" not in text and "资源更新" not in text for text in texts)
    assert not hasattr(application.tray, "cursor_styles_action")
    assert not hasattr(application.tray, "resource_update_action")
    application.shutdown()


def test_only_resource_sections_schedule_a_throttled_check(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    application = PetNest(
        pets_root=tmp_path / "pets",
        settings_manager=SettingsManager(tmp_path / "settings.json"),
        enable_tray=False,
    )
    qtbot.addWidget(application.window)
    checks: list[bool] = []
    application._schedule_resource_check = lambda force=False: checks.append(force)  # type: ignore[method-assign]

    application._handle_resource_section_opened("display")
    application._handle_resource_section_opened("mouse_behavior")

    assert checks == [False]
    application.shutdown()


def test_contextual_resource_check_starts_download_when_update_is_found(
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
    )

    assert applies == [True]
    application.shutdown()


def test_draining_a_check_result_releases_its_worker_before_scheduling_apply(
    qtbot: pytest.QtBot, tmp_path: Path
) -> None:
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    application = PetNest(
        pets_root=tmp_path / "pets",
        settings_manager=SettingsManager(tmp_path / "settings.json"),
        enable_tray=False,
    )
    qtbot.addWidget(application.window)
    worker_token = object()
    application._resource_worker = worker_token  # type: ignore[assignment]
    released_before_apply: list[bool] = []
    application._schedule_resource_apply = lambda: released_before_apply.append(  # type: ignore[method-assign]
        application._resource_worker is None
    )
    application._resource_results.put(
        (
            "check",
            worker_token,
            RemoteResourceCheckResult(True, False, True, catalog_version="2026.8.13"),
        )
    )

    application._drain_resource_results()

    assert released_before_apply == [True]
    application.shutdown()


def test_resource_stage_changes_keep_overall_progress_monotonic(
    qtbot: pytest.QtBot, tmp_path: Path
) -> None:
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    application = PetNest(
        pets_root=tmp_path / "pets",
        settings_manager=SettingsManager(tmp_path / "settings.json"),
        enable_tray=False,
    )
    qtbot.addWidget(application.window)
    resource = ResourceManifest.from_dict(
        {
            "schema_version": 1,
            "catalog_version": "2026.8.13",
            "resources": [
                {
                    "id": "spark",
                    "type": "interaction_effect",
                    "version": "1.0.0",
                    "files": [
                        {
                            "path": "resources/effects/spark/frame.png",
                            "size": 1,
                            "sha256": "0" * 64,
                        }
                    ],
                    "metadata": {"name": "星光"},
                }
            ],
        }
    ).resources[0]

    class _ProgressCoordinator:
        def apply(self, *, progress, on_resource_applied, on_resource_started):
            del on_resource_applied
            progress(65)
            on_resource_started(resource)
            progress(70)
            return RemoteResourceApplyResult(True, "2026.8.13")

    application.remote_resource_update = _ProgressCoordinator()  # type: ignore[assignment]

    application._resource_apply_worker()

    percentages: list[int] = []
    while not application._resource_results.empty():
        kind, _worker, payload = application._resource_results.get_nowait()
        if kind == "progress":
            percentages.append(payload[0])
    assert percentages == [65, 65, 70]
    application.shutdown()


def test_resource_section_applies_an_already_known_update_without_checking(
    qtbot: pytest.QtBot, tmp_path: Path
) -> None:
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    application = PetNest(
        pets_root=tmp_path / "pets",
        settings_manager=SettingsManager(tmp_path / "settings.json"),
        enable_tray=False,
    )
    qtbot.addWidget(application.window)
    checks: list[bool] = []
    applies: list[bool] = []
    application.remote_resource_update.state = replace(
        application.remote_resource_update.state,
        update_available=True,
    )
    application._schedule_resource_check = lambda force=False: checks.append(force)  # type: ignore[method-assign]
    application._schedule_resource_apply = lambda: applies.append(True)  # type: ignore[method-assign]

    application._handle_resource_section_opened("countdown")

    assert checks == []
    assert applies == [True]
    application.shutdown()


def test_resource_progress_updates_the_open_settings_page_with_resource_context(
    qtbot: pytest.QtBot, tmp_path: Path
) -> None:
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    application = PetNest(
        pets_root=tmp_path / "pets",
        settings_manager=SettingsManager(tmp_path / "settings.json"),
        enable_tray=False,
    )
    qtbot.addWidget(application.window)
    application._schedule_resource_check = lambda force=False: None  # type: ignore[method-assign]
    application.show_cursor_style_dialog()
    dialog = application._settings_center_dialog
    assert dialog is not None

    application._handle_resource_progress((43, "interaction_effect", "星光", False))

    assert dialog.resource_status_label.text() == "正在获取互动动效「星光」… 43%"
    application.shutdown()


def test_reopening_settings_replays_an_active_resource_download(
    qtbot: pytest.QtBot, tmp_path: Path
) -> None:
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    application = PetNest(
        pets_root=tmp_path / "pets",
        settings_manager=SettingsManager(tmp_path / "settings.json"),
        enable_tray=False,
    )
    qtbot.addWidget(application.window)

    class _AliveWorker:
        @staticmethod
        def is_alive() -> bool:
            return True

    application._resource_worker = _AliveWorker()  # type: ignore[assignment]
    application._resource_status = "downloading"
    application._resource_progress = (43, "interaction_effect", "星光", False)
    application.show_cursor_style_dialog()
    first = application._settings_center_dialog
    assert first is not None
    first.reject()
    assert application._settings_center_dialog is None

    application.show_cursor_style_dialog()
    reopened = application._settings_center_dialog

    assert reopened is not None and reopened is not first
    assert reopened.resource_status_label.text() == "正在获取互动动效「星光」… 43%"
    application._resource_worker = None
    application.shutdown()


def test_start_does_not_check_resources_until_a_relevant_page_opens(
    qtbot: pytest.QtBot, tmp_path: Path
) -> None:
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    application = PetNest(
        pets_root=tmp_path / "pets",
        settings_manager=SettingsManager(tmp_path / "settings.json"),
        enable_tray=False,
    )
    qtbot.addWidget(application.window)
    checks: list[bool] = []
    application._schedule_resource_check = lambda force=False: checks.append(force)  # type: ignore[method-assign]

    application.start()

    assert checks == []
    assert not hasattr(application, "resource_update_timer")
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


def test_codex_link_alone_does_not_start_hook_server_or_edit_hooks(
    qtbot: pytest.QtBot, tmp_path: Path
) -> None:
    port = _free_loopback_port()
    settings_manager = SettingsManager(tmp_path / "settings.json")
    settings_manager.save(
        Settings(
            work_countdown_enabled=False,
            external_event_server_enabled=False,
            external_event_port=port,
            codex_link_enabled=True,
        )
    )
    hook_manager = CodexHookManager(
        tmp_path / "codex-home",
        settings_manager.path.parent,
        port=port,
        command_prefix=("PetNest.exe",),
    )
    hook_manager.hooks_path.parent.mkdir(parents=True)
    original_hooks = '{"hooks":{"Stop":[]},"keep":true}\n'
    hook_manager.hooks_path.write_text(original_hooks, encoding="utf-8")
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    application = PetNest(
        pets_root=tmp_path / "pets",
        settings_manager=settings_manager,
        codex_hook_manager=hook_manager,
        enable_tray=False,
    )
    qtbot.addWidget(application.window)

    application.start()

    assert application.external_server is None
    assert hook_manager.hooks_path.read_text(encoding="utf-8") == original_hooks
    assert not hook_manager.metadata_path.exists()
    application.shutdown()


def test_codex_hook_reaches_pet_and_ui_on_qt_main_thread(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    port = _free_loopback_port()
    settings_manager = SettingsManager(tmp_path / "settings.json")
    settings_manager.save(Settings(external_event_port=port, codex_link_enabled=True, work_countdown_enabled=False))
    hook_manager = CodexHookManager(
        tmp_path / "codex-home",
        settings_manager.path.parent,
        port=port,
        command_prefix=("PetNest.exe",),
    )
    hook_manager.install()
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    application = PetNest(
        pets_root=tmp_path / "pets",
        settings_manager=settings_manager,
        codex_hook_manager=hook_manager,
        enable_tray=False,
    )
    qtbot.addWidget(application.window)
    handled_on: list[QThread] = []
    application.event_bus.subscribe(
        lambda event: handled_on.append(QThread.currentThread()) if event.event_name == "codex.hook" else None
    )
    application.start()
    token = hook_manager.ensure_metadata().token

    _send_codex_hook(port, token, "PermissionRequest")
    qtbot.waitUntil(lambda: application.codex_link.snapshot.state == "waiting", timeout=2_000)

    assert handled_on and handled_on[-1] == application.window.thread()
    assert application.window.current_action == "waiting"
    assert application.window.codex_status_text == "Codex 正在等待你处理"
    assert application.codex_hook_status.state == "connected"
    assert application.codex_availability.state is CodexAvailabilityState.ACTIVE
    application.shutdown()


def test_disabling_codex_link_clears_state_and_stops_unneeded_server(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    port = _free_loopback_port()
    settings_manager = SettingsManager(tmp_path / "settings.json")
    settings_manager.save(Settings(external_event_port=port, codex_link_enabled=True, work_countdown_enabled=False))
    hook_manager = CodexHookManager(
        tmp_path / "codex-home",
        settings_manager.path.parent,
        port=port,
        command_prefix=("PetNest.exe",),
    )
    hook_manager.install()
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    application = PetNest(
        pets_root=tmp_path / "pets",
        settings_manager=settings_manager,
        codex_hook_manager=hook_manager,
        enable_tray=False,
    )
    qtbot.addWidget(application.window)
    application.start()
    _send_codex_hook(port, hook_manager.ensure_metadata().token, "PermissionRequest")
    qtbot.waitUntil(lambda: application.codex_link.snapshot.state == "waiting", timeout=2_000)

    application.apply_settings(replace(application.settings, codex_link_enabled=False))

    assert application.codex_link.snapshot.state == "idle"
    assert application.window.codex_status_text is None
    assert application.external_server is None
    assert application.window.current_action == "idle"
    application.shutdown()


def test_settings_center_detects_configures_and_removes_petnest_codex_plugin(
    qtbot: pytest.QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings_manager = SettingsManager(tmp_path / "settings.json")
    port = _free_loopback_port()
    hook_manager = CodexHookManager(
        tmp_path / "codex-home",
        settings_manager.path.parent,
        port=port,
        command_prefix=("PetNest.exe",),
    )
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    plugin_manager = _CodexPluginManager()
    application = PetNest(
        pets_root=tmp_path / "pets",
        settings_manager=settings_manager,
        codex_hook_manager=hook_manager,
        codex_plugin_manager=plugin_manager,
        enable_tray=False,
    )
    qtbot.addWidget(application.window)

    application._show_settings_center("codex_link")
    dialog = application._settings_center_dialog
    assert dialog is not None
    assert plugin_manager.inspected == 1
    assert dialog.codex_plugin_primary_button.text() == "启用精确连接"
    qtbot.mouseClick(dialog.codex_plugin_primary_button, Qt.MouseButton.LeftButton)
    assert plugin_manager.configured == 1
    assert dialog.codex_plugin_primary_button.text() == "我已完成，重新检查"
    monkeypatch.setattr(
        "petnest.ui.settings_center_dialog.QMessageBox.question",
        lambda *_args, **_kwargs: __import__("PySide6").QtWidgets.QMessageBox.StandardButton.Yes,
    )
    dialog.codex_advanced_details_button.click()
    qtbot.mouseClick(dialog.codex_plugin_remove_button, Qt.MouseButton.LeftButton)
    assert plugin_manager.removed == 1
    assert dialog.codex_plugin_primary_button.text() == "启用精确连接"
    dialog.reject()
    application.shutdown()


def test_keyboard_monitor_default_off_and_enable_disable_lifecycle(
    qtbot: pytest.QtBot,
    tmp_path: Path,
) -> None:
    monitor = _KeyboardActivityMonitor()
    application = _keyboard_test_application(
        tmp_path,
        monitor,
        keyboard_enabled=False,
    )
    qtbot.addWidget(application.window)
    application.start()

    assert monitor.started == 0
    application.apply_settings(replace(application.settings, keyboard_working_enabled=True))
    assert monitor.started == 1
    application.apply_settings(replace(application.settings, keyboard_working_enabled=False))
    assert monitor.stopped == 1
    application.shutdown()


def test_keyboard_activity_uses_1500ms_window(
    qtbot: pytest.QtBot,
    tmp_path: Path,
) -> None:
    monitor = _KeyboardActivityMonitor()
    application = _keyboard_test_application(tmp_path, monitor, keyboard_enabled=True)
    qtbot.addWidget(application.window)
    application.start()
    assert monitor.callback is not None

    monitor.callback()
    qtbot.waitUntil(lambda: application.window.current_action == "working")
    assert application.keyboard_activity_timer.interval() == 1_500
    monitor.callback()
    assert application.window.current_action == "working"

    application._finish_keyboard_activity()
    assert application.window.current_action == "idle"
    application.shutdown()


def test_second_keypress_restarts_the_full_1500ms_window(
    qtbot: pytest.QtBot,
    tmp_path: Path,
) -> None:
    monitor = _KeyboardActivityMonitor()
    application = _keyboard_test_application(tmp_path, monitor, keyboard_enabled=True)
    qtbot.addWidget(application.window)
    application.start()
    assert monitor.callback is not None

    monitor.callback()
    qtbot.wait(1_000)
    monitor.callback()
    qtbot.wait(700)
    assert application.window.current_action == "working"

    qtbot.waitUntil(lambda: application.window.current_action == "idle", timeout=1_200)
    application.shutdown()


def test_worker_thread_keyboard_pulse_is_handled_on_qt_thread(
    qtbot: pytest.QtBot,
    tmp_path: Path,
) -> None:
    monitor = _KeyboardActivityMonitor()
    application = _keyboard_test_application(tmp_path, monitor, keyboard_enabled=True)
    qtbot.addWidget(application.window)
    handled_on: list[QThread] = []
    application.event_bus.subscribe(
        lambda event: handled_on.append(QThread.currentThread())
        if event.source == "work-activity"
        else None
    )
    application.start()
    assert monitor.callback is not None

    worker = Thread(target=monitor.callback)
    worker.start()
    worker.join(timeout=1)
    qtbot.waitUntil(lambda: application.window.current_action == "working")

    assert handled_on[-1] == application.window.thread()
    application.shutdown()


def test_keyboard_monitor_failure_does_not_activate_working(
    qtbot: pytest.QtBot,
    tmp_path: Path,
) -> None:
    monitor = _KeyboardActivityMonitor(start_ok=False)
    application = _keyboard_test_application(tmp_path, monitor, keyboard_enabled=True)
    qtbot.addWidget(application.window)

    application.start()

    assert monitor.started == 1
    assert application._keyboard_monitor_running is False
    assert application.work_activity.keyboard_active is False
    assert application.window.current_action == "idle"
    application.shutdown()


def test_shutdown_stops_running_keyboard_monitor(
    qtbot: pytest.QtBot,
    tmp_path: Path,
) -> None:
    monitor = _KeyboardActivityMonitor()
    application = _keyboard_test_application(tmp_path, monitor, keyboard_enabled=True)
    qtbot.addWidget(application.window)
    application.start()

    application.shutdown()

    assert monitor.stopped == 1
    assert application._keyboard_monitor_running is False


def test_keyboard_timeout_does_not_cancel_codex_working(
    qtbot: pytest.QtBot,
    tmp_path: Path,
) -> None:
    monitor = _KeyboardActivityMonitor()
    application = _keyboard_test_application(
        tmp_path,
        monitor,
        keyboard_enabled=True,
        codex_enabled=True,
    )
    qtbot.addWidget(application.window)
    application.start()
    application.codex_link.consume(_codex_log_event("UserPromptSubmit"))
    assert monitor.callback is not None
    monitor.callback()
    qtbot.waitUntil(lambda: application.window.current_action == "working")

    application._finish_keyboard_activity()

    assert application.window.current_action == "working"
    application.shutdown()


def test_codex_review_finishes_back_to_active_keyboard(
    qtbot: pytest.QtBot,
    tmp_path: Path,
) -> None:
    monitor = _KeyboardActivityMonitor()
    application = _keyboard_test_application(
        tmp_path,
        monitor,
        keyboard_enabled=True,
        codex_enabled=True,
    )
    qtbot.addWidget(application.window)
    application.start()
    assert monitor.callback is not None
    monitor.callback()
    application.codex_link.consume(_codex_log_event("Stop"))
    assert application.window.current_action == application.package.bindings.get("agent.success", "review")
    assert application.work_activity.keyboard_active is True
    assert application.work_activity.effective_event == "agent.success"

    qtbot.wait(60)
    application._finish_codex_review_animation()

    assert application.work_activity.effective_event == "agent.working"
    assert application.window.current_action == "working"
    assert application.codex_link.snapshot.unread_review_count == 0
    application.shutdown()


def test_keyboard_activity_from_sleep_suppresses_duplicate_wake(
    qtbot: pytest.QtBot,
    tmp_path: Path,
) -> None:
    adapter = _IdleAdapter(idle_seconds=3)
    monitor = _KeyboardActivityMonitor()
    application = _keyboard_test_application(
        tmp_path,
        monitor,
        keyboard_enabled=True,
        platform_adapter=adapter,
    )
    qtbot.addWidget(application.window)
    system_events: list[str] = []
    application.event_bus.subscribe(
        lambda event: system_events.append(event.event_name) if event.source == "system" else None
    )
    application.start()
    assert "system.sleep" in system_events
    system_events.clear()
    adapter.idle_seconds = 0
    assert monitor.callback is not None

    monitor.callback()
    application._check_system_idle()

    assert application.window.current_action == "working"
    assert "system.wake" not in system_events
    application.shutdown()


def test_mouse_recovery_without_keyboard_still_plays_wake(
    qtbot: pytest.QtBot,
    tmp_path: Path,
) -> None:
    adapter = _IdleAdapter(idle_seconds=3)
    monitor = _KeyboardActivityMonitor()
    application = _keyboard_test_application(
        tmp_path,
        monitor,
        keyboard_enabled=True,
        platform_adapter=adapter,
    )
    qtbot.addWidget(application.window)
    system_events: list[str] = []
    application.event_bus.subscribe(
        lambda event: system_events.append(event.event_name) if event.source == "system" else None
    )
    application.start()
    assert "system.sleep" in system_events
    system_events.clear()
    adapter.idle_seconds = 0

    application._check_system_idle()

    assert system_events == ["system.wake"]
    application.shutdown()


def test_codex_working_suppresses_system_bored_and_sleep(
    qtbot: pytest.QtBot,
    tmp_path: Path,
) -> None:
    adapter = _IdleAdapter(idle_seconds=0)
    monitor = _KeyboardActivityMonitor()
    application = _keyboard_test_application(
        tmp_path,
        monitor,
        keyboard_enabled=False,
        codex_enabled=True,
        platform_adapter=adapter,
    )
    qtbot.addWidget(application.window)
    application.start()
    application.codex_link.consume(_codex_log_event("UserPromptSubmit"))
    assert application.window.current_action == "working"
    adapter.idle_seconds = 3

    application._check_system_idle()

    assert application.window.current_action == "working"
    assert application._system_idle_monitor.state.value == "active"
    application.shutdown()


def test_settings_pet_action_entry_opens_interactive_child_dialog(
    qtbot: pytest.QtBot, tmp_path: Path
) -> None:
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    application = PetNest(
        pets_root=tmp_path / "pets",
        settings_manager=SettingsManager(tmp_path / "settings.json"),
        codex_plugin_manager=_CodexPluginManager(),
        enable_tray=False,
    )
    qtbot.addWidget(application.window)
    application._show_settings_center("codex_link")
    settings_dialog = application._settings_center_dialog
    assert settings_dialog is not None
    assert settings_dialog.windowModality() == Qt.WindowModality.WindowModal

    settings_dialog.codex_open_pet_actions_button.click()

    action_dialog = application._pet_action_exchange_dialog
    assert action_dialog is not None
    assert action_dialog.parentWidget() is settings_dialog
    assert action_dialog.isVisible()
    assert action_dialog.isEnabled()
    destroyed: list[bool] = []
    action_dialog.destroyed.connect(lambda *_args: destroyed.append(True))
    action_dialog.reject()
    qtbot.waitUntil(lambda: bool(destroyed))
    assert application._pet_action_exchange_dialog is None

    application.show_pet_action_exchange_dialog("导入动作")
    tray_dialog = application._pet_action_exchange_dialog
    assert tray_dialog is not None
    assert tray_dialog.parentWidget() is application.window
    assert tray_dialog.windowModality() == Qt.WindowModality.NonModal
    tray_dialog.reject()
    settings_dialog.reject()
    application.shutdown()


def test_failed_precise_connection_does_not_stop_basic_codex_log_link(
    qtbot: pytest.QtBot, tmp_path: Path
) -> None:
    watcher = _CodexLogWatcher()
    plugin = _CodexPluginManager(CodexPluginStatus.error("CET 不兼容"))
    home = tmp_path / "codex-home"
    discovery = _CodexDiscoveryService(
        CodexLinkAvailability(
            CodexAvailabilityState.READY,
            "联动已准备好，等待新的任务",
            True,
            ("app-server",),
            home,
            home / "sessions",
            False,
            True,
        )
    )
    settings_manager = SettingsManager(tmp_path / "settings.json")
    settings_manager.save(Settings(codex_link_enabled=True, codex_link_log_fallback_enabled=True))
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    application = PetNest(
        pets_root=tmp_path / "pets",
        settings_manager=settings_manager,
        codex_log_watcher=watcher,
        codex_plugin_manager=plugin,
        codex_discovery=discovery,
        enable_tray=False,
    )
    qtbot.addWidget(application.window)

    application.start()
    application._show_settings_center("codex_link")

    assert watcher.is_running
    assert application.codex_log_timer.isActive()
    assert application._settings_center_dialog is not None
    assert "基础联动仍可使用" in application._settings_center_dialog.codex_plugin_summary_label.text()
    watcher.events.append(
        PetEvent(
            "codex.hook",
            source="codex-log",
            payload={"hook_event_name": "UserPromptSubmit", "session_id": "s", "turn_id": "t"},
        )
    )
    application._poll_codex_logs()
    assert application._settings_center_dialog.codex_link_runtime_label.text() == "Codex 正在工作"
    application._settings_center_dialog.reject()
    application.shutdown()


def test_codex_discovery_starts_only_verified_log_source(
    qtbot: pytest.QtBot,
    tmp_path: Path,
) -> None:
    home = tmp_path / "verified-codex-home"
    availability = CodexLinkAvailability(
        CodexAvailabilityState.READY,
        "联动已准备好，等待新的任务",
        True,
        ("app-server",),
        home,
        home / "sessions",
        False,
        True,
    )
    discovery = _CodexDiscoveryService(availability)
    watcher = _CodexLogWatcher()
    manager = SettingsManager(tmp_path / "settings.json")
    manager.save(
        Settings(
            codex_link_enabled=True,
            external_event_port=_free_loopback_port(),
            work_countdown_enabled=False,
        )
    )
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    application = PetNest(
        pets_root=tmp_path / "pets",
        settings_manager=manager,
        codex_discovery=discovery,
        codex_log_watcher=watcher,
        enable_tray=False,
    )
    qtbot.addWidget(application.window)

    application.start()

    assert discovery.calls == [None]
    assert watcher.configured_home == home.resolve()
    assert watcher.started == 1
    assert application.codex_log_timer.isActive()
    assert not application.codex_discovery_timer.isActive()
    assert application.external_server is None
    application.shutdown()


def test_codex_not_detected_retries_without_fast_log_poll_or_hook_server(
    qtbot: pytest.QtBot,
    tmp_path: Path,
) -> None:
    availability = CodexLinkAvailability(
        CodexAvailabilityState.NOT_DETECTED,
        "未检测到 Codex，安装或启动后会自动连接",
        False,
    )
    discovery = _CodexDiscoveryService(availability)
    watcher = _CodexLogWatcher()
    manager = SettingsManager(tmp_path / "settings.json")
    manager.save(Settings(codex_link_enabled=True, work_countdown_enabled=False))
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    application = PetNest(
        pets_root=tmp_path / "pets",
        settings_manager=manager,
        codex_discovery=discovery,
        codex_log_watcher=watcher,
        enable_tray=False,
    )
    qtbot.addWidget(application.window)

    application.start()

    assert application.codex_discovery_timer.interval() == 30_000
    assert application.codex_discovery_timer.isActive()
    assert watcher.started == 0
    assert not application.codex_log_timer.isActive()
    assert application.external_server is None
    assert application.window.codex_status_text is None
    application.shutdown()


def test_default_app_home_probe_does_not_block_qt_startup(
    qtbot: pytest.QtBot,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CODEX_HOME", raising=False)
    home = tmp_path / "app-server-home"
    current = date.today()
    day = home / "sessions" / f"{current:%Y}" / f"{current:%m}" / f"{current:%d}"
    day.mkdir(parents=True)
    (day / "rollout-current.jsonl").write_text(
        json.dumps({"type": "session_meta", "payload": {"session_id": "session-current"}})
        + "\n"
        + json.dumps(
            {
                "type": "event_msg",
                "payload": {"type": "task_started", "turn_id": "turn-current"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    entered = Event()
    release = Event()

    def slow_app_home() -> Path:
        entered.set()
        release.wait(5.0)
        return home

    monkeypatch.setattr("petnest.app._fetch_codex_home_for_discovery", slow_app_home)
    manager = SettingsManager(tmp_path / "settings.json")
    manager.save(Settings(codex_link_enabled=True, work_countdown_enabled=False))
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    started_at = monotonic()
    application = PetNest(
        pets_root=tmp_path / "pets",
        settings_manager=manager,
        enable_tray=False,
    )
    qtbot.addWidget(application.window)
    application.start()
    elapsed = monotonic() - started_at

    assert elapsed < 1.5
    assert entered.wait(1.0)
    release.set()
    qtbot.waitUntil(
        lambda: application.codex_availability.selected_home == home.resolve(),
        timeout=3_000,
    )
    assert application.codex_availability.state is CodexAvailabilityState.READY
    application.shutdown()


def test_codex_waiting_for_sessions_runs_watcher_and_keeps_discovery_retry(
    qtbot: pytest.QtBot,
    tmp_path: Path,
) -> None:
    home = tmp_path / "empty-codex-home"
    availability = CodexLinkAvailability(
        CodexAvailabilityState.WAITING_FOR_SESSIONS,
        "已检测到 Codex，等待创建本地任务",
        True,
        ("desktop",),
        home,
        home / "sessions",
        False,
        True,
    )
    discovery = _CodexDiscoveryService(availability)
    watcher = _CodexLogWatcher()
    manager = SettingsManager(tmp_path / "settings.json")
    manager.save(Settings(codex_link_enabled=True, work_countdown_enabled=False))
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    application = PetNest(
        pets_root=tmp_path / "pets",
        settings_manager=manager,
        codex_discovery=discovery,
        codex_log_watcher=watcher,
        enable_tray=False,
    )
    qtbot.addWidget(application.window)

    application.start()

    assert watcher.started == 1
    assert application.codex_log_timer.isActive()
    assert application.codex_discovery_timer.isActive()
    application.shutdown()


def test_disabled_codex_link_does_not_run_discovery(
    qtbot: pytest.QtBot,
    tmp_path: Path,
) -> None:
    discovery = _CodexDiscoveryService(
        CodexLinkAvailability(
            CodexAvailabilityState.NOT_DETECTED,
            "未检测到 Codex",
            False,
        )
    )
    manager = SettingsManager(tmp_path / "settings.json")
    manager.save(Settings(codex_link_enabled=False, work_countdown_enabled=False))
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    application = PetNest(
        pets_root=tmp_path / "pets",
        settings_manager=manager,
        codex_discovery=discovery,
        enable_tray=False,
    )
    qtbot.addWidget(application.window)

    application.start()

    assert discovery.calls == []
    assert not application.codex_discovery_timer.isActive()
    assert not application.codex_log_timer.isActive()
    application.shutdown()


def test_manual_codex_home_is_persisted_applied_and_restored(
    qtbot: pytest.QtBot,
    tmp_path: Path,
) -> None:
    manual = tmp_path / "manual-home"
    automatic = tmp_path / "automatic-home"
    discovery = _CodexDiscoveryService(
        CodexLinkAvailability(
            CodexAvailabilityState.NOT_DETECTED,
            "未检测到 Codex",
            False,
        ),
        CodexLinkAvailability(
            CodexAvailabilityState.READY,
            "联动已准备好，等待新的任务",
            True,
            ("manual",),
            manual,
            manual / "sessions",
            True,
            True,
        ),
        CodexLinkAvailability(
            CodexAvailabilityState.READY,
            "联动已准备好，等待新的任务",
            True,
            ("app-server",),
            automatic,
            automatic / "sessions",
            False,
            True,
        ),
    )
    watcher = _CodexLogWatcher()
    manager = SettingsManager(tmp_path / "settings.json")
    manager.save(Settings(codex_link_enabled=True, work_countdown_enabled=False))
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    application = PetNest(
        pets_root=tmp_path / "pets",
        settings_manager=manager,
        codex_discovery=discovery,
        codex_log_watcher=watcher,
        enable_tray=False,
    )
    qtbot.addWidget(application.window)
    application.start()

    selected = application._set_codex_home_override(manual)

    assert selected.manual_override is True
    assert discovery.calls[-1] == manual
    assert watcher.configured_home == manual.resolve()
    assert manager.load().codex_home_override == str(manual)

    restored = application._set_codex_home_override(None)

    assert restored.manual_override is False
    assert discovery.calls[-1] is None
    assert watcher.configured_home == automatic.resolve()
    assert manager.load().codex_home_override is None
    application.shutdown()


def test_invalid_manual_codex_home_is_not_persisted(
    qtbot: pytest.QtBot,
    tmp_path: Path,
) -> None:
    invalid = tmp_path / "ordinary-folder"
    invalid.mkdir()
    unavailable = CodexLinkAvailability(
        CodexAvailabilityState.NOT_DETECTED,
        "所选目录不是 Codex 数据目录",
        False,
        ("manual",),
        invalid,
        invalid / "sessions",
        True,
        False,
        "未找到 sessions 或 Codex 配置标记",
    )
    discovery = _CodexDiscoveryService(unavailable)
    manager = SettingsManager(tmp_path / "settings.json")
    manager.save(Settings(codex_link_enabled=True, work_countdown_enabled=False))
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    application = PetNest(
        pets_root=tmp_path / "pets",
        settings_manager=manager,
        codex_discovery=discovery,
        enable_tray=False,
    )
    qtbot.addWidget(application.window)
    application.start()

    with pytest.raises(ValueError, match="Codex 数据目录"):
        application._set_codex_home_override(invalid)

    assert manager.load().codex_home_override is None
    assert application.settings.codex_home_override is None
    application.shutdown()


def test_discovered_profile_rechecks_legacy_hook_before_starting_server(
    qtbot: pytest.QtBot,
    tmp_path: Path,
) -> None:
    port = _free_loopback_port()
    first = tmp_path / "first-home"
    second = tmp_path / "second-home"
    manager = SettingsManager(tmp_path / "settings.json")
    manager.save(
        Settings(
            codex_link_enabled=True,
            external_event_port=port,
            work_countdown_enabled=False,
        )
    )
    hook_manager = CodexHookManager(
        first,
        manager.path.parent,
        port=port,
        command_prefix=("PetNest.exe",),
    )
    hook_manager.set_codex_home(second)
    hook_manager.install()
    hook_manager.set_codex_home(first)
    availability = CodexLinkAvailability(
        CodexAvailabilityState.READY,
        "联动已准备好，等待新的任务",
        True,
        ("app-server",),
        second,
        second / "sessions",
        False,
        True,
    )
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    application = PetNest(
        pets_root=tmp_path / "pets",
        settings_manager=manager,
        codex_hook_manager=hook_manager,
        codex_discovery=_CodexDiscoveryService(availability),
        codex_log_watcher=_CodexLogWatcher(),
        enable_tray=False,
    )
    qtbot.addWidget(application.window)

    application.start()

    assert application.codex_hook_status.installed is True
    assert application.external_server is not None
    assert application.external_server.is_running
    application.shutdown()


def test_incompatible_manual_profile_still_syncs_hook_and_plugin_home(
    qtbot: pytest.QtBot,
    tmp_path: Path,
) -> None:
    selected = tmp_path / "incompatible-home"
    selected.mkdir()
    unavailable = CodexLinkAvailability(
        CodexAvailabilityState.NOT_DETECTED,
        "未检测到 Codex",
        False,
    )
    incompatible = CodexLinkAvailability(
        CodexAvailabilityState.INCOMPATIBLE,
        "当前 Codex 版本暂不支持基础联动",
        True,
        ("manual",),
        selected,
        selected / "sessions",
        True,
        False,
        "未知格式",
    )
    discovery = _CodexDiscoveryService(unavailable, incompatible)
    watcher = _CodexLogWatcher()
    plugin = _CodexPluginManager()
    manager = SettingsManager(tmp_path / "settings.json")
    manager.save(Settings(codex_link_enabled=True, work_countdown_enabled=False))
    hook = CodexHookManager(
        tmp_path / "initial-home",
        manager.path.parent,
        port=_free_loopback_port(),
        command_prefix=("PetNest.exe",),
    )
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    application = PetNest(
        pets_root=tmp_path / "pets",
        settings_manager=manager,
        codex_hook_manager=hook,
        codex_plugin_manager=plugin,
        codex_discovery=discovery,
        codex_log_watcher=watcher,
        enable_tray=False,
    )
    qtbot.addWidget(application.window)
    application.start()

    availability = application._set_codex_home_override(selected)

    assert availability.state is CodexAvailabilityState.INCOMPATIBLE
    assert watcher.configured_home == selected.resolve()
    assert watcher.started == 0
    assert hook.codex_home == selected.resolve()
    assert plugin.codex_home == selected.resolve()
    assert manager.load().codex_home_override == str(selected)
    application.shutdown()


def test_removing_precise_plugin_restores_basic_discovery(
    qtbot: pytest.QtBot,
    tmp_path: Path,
) -> None:
    not_detected = CodexLinkAvailability(
        CodexAvailabilityState.NOT_DETECTED,
        "未检测到 Codex，安装或启动后会自动连接",
        False,
    )
    discovery = _CodexDiscoveryService(not_detected)
    plugin = _CodexPluginManager(CodexPluginStatus.pending())
    manager = SettingsManager(tmp_path / "settings.json")
    manager.save(
        Settings(
            codex_link_enabled=True,
            external_event_port=_free_loopback_port(),
            work_countdown_enabled=False,
        )
    )
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    application = PetNest(
        pets_root=tmp_path / "pets",
        settings_manager=manager,
        codex_plugin_manager=plugin,
        codex_discovery=discovery,
        enable_tray=False,
    )
    qtbot.addWidget(application.window)
    application.start()
    application.codex_availability = replace(
        not_detected,
        state=CodexAvailabilityState.ACTIVE,
        message="联动正常",
        codex_detected=True,
    )
    application.codex_discovery_timer.stop()
    calls_before = len(discovery.calls)

    status = application._remove_codex_plugin()

    assert status.installed is False
    assert len(discovery.calls) == calls_before + 1
    assert application.codex_availability.state is CodexAvailabilityState.NOT_DETECTED
    assert application.codex_discovery_timer.isActive()
    application.shutdown()


def test_discovery_and_log_events_drive_plain_runtime_states(
    qtbot: pytest.QtBot,
    tmp_path: Path,
) -> None:
    home = tmp_path / "codex-home"
    availability = CodexLinkAvailability(
        CodexAvailabilityState.READY,
        "联动已准备好，等待新的任务",
        True,
        ("app-server",),
        home,
        home / "sessions",
        False,
        True,
    )
    watcher = _CodexLogWatcher()
    manager = SettingsManager(tmp_path / "settings.json")
    manager.save(Settings(codex_link_enabled=True, work_countdown_enabled=False))
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    application = PetNest(
        pets_root=tmp_path / "pets",
        settings_manager=manager,
        codex_discovery=_CodexDiscoveryService(availability),
        codex_log_watcher=watcher,
        enable_tray=False,
    )
    qtbot.addWidget(application.window)
    application.start()
    application._show_settings_center("codex_link")
    dialog = application._settings_center_dialog
    assert dialog is not None
    assert dialog.codex_link_runtime_label.text() == "联动已准备好，等待新的任务"

    watcher.events.append(
        PetEvent(
            "codex.hook",
            source="codex-log",
            payload={
                "hook_event_name": "UserPromptSubmit",
                "session_id": "session-1",
                "turn_id": "turn-1",
            },
        )
    )
    application._poll_codex_logs()
    assert dialog.codex_link_runtime_label.text() == "Codex 正在工作"
    assert application.codex_availability.state is CodexAvailabilityState.ACTIVE

    watcher.events.append(
        PetEvent(
            "codex.hook",
            source="codex-log",
            payload={
                "hook_event_name": "Stop",
                "session_id": "session-1",
                "turn_id": "turn-1",
            },
        )
    )
    application._poll_codex_logs()
    assert dialog.codex_link_runtime_label.text() == "任务已完成"
    assert application.codex_link.snapshot.unread_review_count == 0
    assert application.window.codex_status_text is None

    watcher.events.append(
        PetEvent(
            "codex.hook",
            source="codex-log",
            payload={
                "hook_event_name": "ThreadUnread",
                "session_id": "session-1",
            },
        )
    )
    application._poll_codex_logs()
    assert application.codex_link.snapshot.unread_review_count == 1
    assert application.window.codex_status_text == "Codex 任务已完成，等待查看"

    application._finish_codex_review_animation()
    assert application.codex_link.snapshot.state == "idle"
    assert application.codex_link.snapshot.unread_review_count == 1

    watcher.events.append(
        PetEvent(
            "codex.hook",
            source="codex-log",
            payload={"hook_event_name": "ThreadRead", "session_id": "session-1"},
        )
    )
    application._poll_codex_logs()
    assert application.codex_link.snapshot.unread_review_count == 0
    assert application.window.codex_status_text is None
    application._settings_center_dialog.reject()
    application.shutdown()


def test_runtime_incompatible_log_stops_fast_poll_and_retries_discovery(
    qtbot: pytest.QtBot,
    tmp_path: Path,
) -> None:
    today = date(2026, 8, 20)
    home = tmp_path / "codex-home"
    discovery = _CodexDiscoveryService(
        CodexLinkAvailability(
            CodexAvailabilityState.READY,
            "联动已准备好，等待新的任务",
            True,
            ("app-server",),
            home,
            home / "sessions",
            False,
            True,
        )
    )
    watcher = CodexSessionLogWatcher(home / "sessions", today=lambda: today)
    manager = SettingsManager(tmp_path / "settings.json")
    manager.save(Settings(codex_link_enabled=True, work_countdown_enabled=False))
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    application = PetNest(
        pets_root=tmp_path / "pets",
        settings_manager=manager,
        codex_discovery=discovery,
        codex_log_watcher=watcher,
        enable_tray=False,
    )
    qtbot.addWidget(application.window)
    application.start()
    day = home / "sessions" / "2026" / "08" / "20"
    day.mkdir(parents=True)
    (day / "rollout-bad.jsonl").write_text(
        json.dumps({"type": "session_meta", "payload": {"session_id": "session-1"}})
        + "\n"
        + json.dumps({"type": "event_msg", "payload": {"type": "task_started"}})
        + "\n",
        encoding="utf-8",
    )

    application._poll_codex_logs()

    assert application.codex_availability.state is CodexAvailabilityState.INCOMPATIBLE
    assert not application.codex_log_timer.isActive()
    assert application.codex_discovery_timer.isActive()
    assert application.codex_link.snapshot.state == "idle"
    application.shutdown()


def test_codex_log_fallback_starts_with_link_and_stops_when_disabled(
    qtbot: pytest.QtBot, tmp_path: Path
) -> None:
    port = _free_loopback_port()
    settings_manager = SettingsManager(tmp_path / "settings.json")
    settings_manager.save(
        Settings(
            external_event_port=port,
            codex_link_enabled=True,
            codex_link_log_fallback_enabled=True,
            work_countdown_enabled=False,
        )
    )
    watcher = _CodexLogWatcher()
    home = tmp_path / "codex-home"
    discovery = _CodexDiscoveryService(
        CodexLinkAvailability(
            CodexAvailabilityState.READY,
            "联动已准备好，等待新的任务",
            True,
            ("app-server",),
            home,
            home / "sessions",
            False,
            True,
        )
    )
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    application = PetNest(
        pets_root=tmp_path / "pets",
        settings_manager=settings_manager,
        codex_log_watcher=watcher,
        codex_discovery=discovery,
        enable_tray=False,
    )
    qtbot.addWidget(application.window)

    application.start()
    assert watcher.started == 1
    assert application.codex_log_timer.isActive()

    application.apply_settings(replace(application.settings, codex_link_log_fallback_enabled=False))
    assert watcher.stopped == 1
    assert not application.codex_log_timer.isActive()
    application.shutdown()


def test_codex_log_events_drive_pet_and_hook_upgrades_runtime_source(
    qtbot: pytest.QtBot, tmp_path: Path
) -> None:
    port = _free_loopback_port()
    settings_manager = SettingsManager(tmp_path / "settings.json")
    settings_manager.save(
        Settings(
            external_event_port=port,
            codex_link_enabled=True,
            codex_link_log_fallback_enabled=True,
            work_countdown_enabled=False,
        )
    )
    watcher = _CodexLogWatcher()
    home = tmp_path / "codex-home"
    discovery = _CodexDiscoveryService(
        CodexLinkAvailability(
            CodexAvailabilityState.READY,
            "联动已准备好，等待新的任务",
            True,
            ("app-server",),
            home,
            home / "sessions",
            False,
            True,
        )
    )
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    application = PetNest(
        pets_root=tmp_path / "pets",
        settings_manager=settings_manager,
        codex_log_watcher=watcher,
        codex_discovery=discovery,
        enable_tray=False,
    )
    qtbot.addWidget(application.window)
    application.start()
    watcher.events.append(
        PetEvent(
            "codex.hook",
            source="codex-log",
            payload={"hook_event_name": "UserPromptSubmit", "session_id": "s", "turn_id": "t"},
        )
    )

    application._poll_codex_logs()
    assert application.window.current_action == "working"
    assert application.codex_link_source == "log"

    application._handle_codex_hook_event(
        PetEvent(
            "codex.hook",
            source="codex-hook",
            payload={"hook_event_name": "PermissionRequest", "session_id": "s"},
        )
    )
    assert application.window.current_action == "waiting"
    assert application.codex_link_source == "hook"
    application.shutdown()


def test_codex_log_fallback_does_not_scan_in_hook_only_mode(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    settings_manager = SettingsManager(tmp_path / "settings.json")
    settings_manager.save(Settings(codex_link_enabled=True, codex_link_log_fallback_enabled=False))
    watcher = _CodexLogWatcher()
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    application = PetNest(
        pets_root=tmp_path / "pets",
        settings_manager=settings_manager,
        codex_log_watcher=watcher,
        enable_tray=False,
    )
    qtbot.addWidget(application.window)

    application.start()

    assert watcher.started == 0
    assert not application.codex_log_timer.isActive()
    application.shutdown()


def test_default_codex_log_watcher_honors_codex_home_override(
    qtbot: pytest.QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configured_home = tmp_path / "portable-codex"
    monkeypatch.setenv("CODEX_HOME", str(configured_home))
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    application = PetNest(
        pets_root=tmp_path / "pets",
        settings_manager=SettingsManager(tmp_path / "settings.json"),
        enable_tray=False,
    )
    qtbot.addWidget(application.window)

    assert application.codex_log_watcher.root == (configured_home / "sessions").resolve()
    assert application.codex_log_watcher.global_state_path == (
        configured_home / ".codex-global-state.json"
    ).resolve()
    assert application.codex_hook_manager.codex_home == configured_home.resolve()
    assert application.codex_plugin_manager.codex_home == configured_home.resolve()
    application.shutdown()


def test_clicking_codex_bubble_only_marks_read_without_title_based_window_activation(
    qtbot: pytest.QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[bool] = []
    monkeypatch.setattr("petnest.app._bring_codex_window_to_front", lambda: calls.append(True) or True)
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    settings_manager = SettingsManager(tmp_path / "settings.json")
    settings_manager.save(Settings(codex_link_enabled=True))
    application = PetNest(
        pets_root=tmp_path / "pets",
        settings_manager=settings_manager,
        enable_tray=False,
    )
    qtbot.addWidget(application.window)
    application.codex_link.consume(
        PetEvent(
            "codex.hook",
            source="codex-log",
            payload={"hook_event_name": "Stop", "session_id": "s", "turn_id": "t"},
        )
    )

    application._activate_codex_status()

    assert application.codex_link.snapshot.state == "idle"
    assert application.codex_link.snapshot.unread_review_count == 0
    assert calls == []
    application.shutdown()


def test_review_animation_returns_to_context_after_one_cycle_while_unread_remains(
    qtbot: pytest.QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    settings_manager = SettingsManager(tmp_path / "settings.json")
    settings_manager.save(Settings(codex_link_enabled=True))
    application = PetNest(
        pets_root=tmp_path / "pets",
        settings_manager=settings_manager,
        enable_tray=False,
    )
    qtbot.addWidget(application.window)
    monkeypatch.setattr(application, "_codex_review_animation_duration_ms", lambda: 20)

    application.codex_link.consume(
        PetEvent(
            "codex.hook",
            source="codex-log",
            payload={"hook_event_name": "Stop", "session_id": "s", "turn_id": "t"},
        )
    )
    assert application.codex_review_animation_timer.isActive()
    qtbot.waitUntil(lambda: application.window.current_action == "idle", timeout=500)

    assert application.codex_link.snapshot.state == "review"
    assert application.codex_link.snapshot.unread_review_count == 1
    application.shutdown()


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


def test_received_lan_interaction_publishes_message_pet_event(
    qtbot: pytest.QtBot,
    tmp_path: Path,
) -> None:
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    application = PetNest(
        pets_root=tmp_path / "pets",
        settings_manager=SettingsManager(tmp_path / "settings.json"),
        enable_tray=False,
    )
    qtbot.addWidget(application.window)
    events: list[str] = []
    application.event_bus.subscribe(lambda event: events.append(event.event_name))

    application._handle_lan_interaction(
        SimpleNamespace(
            sender_name="小林",
            draft=SimpleNamespace(kind=InteractionKind.GREETING),
        )
    )

    assert events == [EventName.INTERACTION_MESSAGE]
    application.shutdown()


def test_received_lan_chat_publishes_message_pet_event(
    qtbot: pytest.QtBot,
    tmp_path: Path,
) -> None:
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    application = PetNest(
        pets_root=tmp_path / "pets",
        settings_manager=SettingsManager(tmp_path / "settings.json"),
        enable_tray=False,
    )
    qtbot.addWidget(application.window)
    events: list[str] = []
    application.event_bus.subscribe(lambda event: events.append(event.event_name))

    application._handle_lan_chat(
        SimpleNamespace(
            sender_name="小林",
            kind=ChatMessageKind.TEXT,
            text="收到一条消息",
            is_group=False,
        )
    )

    assert events == [EventName.INTERACTION_MESSAGE]
    application.shutdown()


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

    # Reload and rollback both restore the visible scale, and set_scale()
    # reclamps the window before the explicit saved-position restore.
    assert calls == 5
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
