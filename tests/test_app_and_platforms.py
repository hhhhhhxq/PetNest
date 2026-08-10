"""应用装配与平台安全降级的回归测试。"""

from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PIL import Image
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QPoint

from petnest.app import PetNest
from petnest.core.animation_action_synchronizer import AnimationActionSyncError
from petnest.core.settings_manager import SettingsManager
from petnest.models.event import PetEvent
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

    def register_startup(self, enabled: bool) -> bool:
        del enabled
        return False


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


def test_application_reveal_restores_a_hidden_pet_window(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    del app
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    application = PetNest(
        pets_root=tmp_path / "pets", settings_manager=SettingsManager(tmp_path / "settings.json"), enable_tray=False
    )
    qtbot.addWidget(application.window)
    application.start()
    application.window.hide()

    application.reveal()

    assert application.window.isVisible()


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

    class _AcceptedEditor:
        def __init__(self, *_args: object) -> None:
            pass

        def exec(self) -> bool:
            return True

        def updated_frame_durations(self) -> dict[str, tuple[int, ...]]:
            return {"idle": (200, 80, 120, 160)}

        def applied_summary(self) -> str:
            return "unused"

    messages: list[tuple[str, str]] = []
    monkeypatch.setattr("petnest.app.AnimationEditorDialog", _AcceptedEditor)
    monkeypatch.setattr(
        application.action_synchronizer,
        "update_frame_durations",
        lambda *_args: (_ for _ in ()).throw(AnimationActionSyncError("访问被拒绝")),
    )
    monkeypatch.setattr("petnest.app.QMessageBox.critical", lambda _parent, title, message: messages.append((title, message)))

    application.show_animation_editor_dialog()

    assert messages == [("无法保存动画时长", f"未写入 {application.package.root / 'pet.json'}。\n原因：访问被拒绝")]


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


def test_animation_editor_reloads_and_syncs_frames_added_while_the_app_is_running(
    qtbot: pytest.QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
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
    Image.new("RGBA", (16, 16), (1, 0, 0, 255)).save(package_root / "animations" / "idle" / "002.png")

    received_packages = []

    class _CancelledEditor:
        def __init__(self, package: object, _parent: object) -> None:
            received_packages.append(package)

        def exec(self) -> bool:
            return False

    monkeypatch.setattr("petnest.app.AnimationEditorDialog", _CancelledEditor)

    application.show_animation_editor_dialog()

    assert len(received_packages[0].animations["idle"].frames) == 2
    saved = json.loads((package_root / "pet.json").read_text(encoding="utf-8"))
    assert saved["animations"]["idle"]["frame_durations_ms"] == [120, 120]


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
