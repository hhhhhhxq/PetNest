"""应用装配与平台安全降级的回归测试。"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from petnest.app import PetNest
from petnest.core.settings_manager import SettingsManager
from petnest.models.settings import AnimationOverride, Settings
from petnest.platforms.unsupported import UnsupportedPlatformAdapter
from tools.create_sample_pet import create_sample_pet


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


def test_application_applies_saved_animation_override_to_loaded_package(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    del app
    settings_manager = SettingsManager(tmp_path / "settings.json")
    settings_manager.save(Settings(animation_overrides={"sample_pet": {"idle": AnimationOverride(mode="total", speed_multiplier=1.5)}}))
    create_sample_pet(tmp_path / "pets" / "sample_pet")

    application = PetNest(pets_root=tmp_path / "pets", settings_manager=settings_manager, enable_tray=False)
    qtbot.addWidget(application.window)

    assert application.package.animations["idle"].speed_multiplier == 1.5


def test_per_frame_mode_does_not_also_apply_total_speed(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    del app
    settings_manager = SettingsManager(tmp_path / "settings.json")
    settings_manager.save(Settings(animation_overrides={
        "sample_pet": {"idle": AnimationOverride(mode="per_frame", speed_multiplier=2.0, frame_durations_ms=(200, 80, 120, 160))}
    }))
    create_sample_pet(tmp_path / "pets" / "sample_pet")

    application = PetNest(pets_root=tmp_path / "pets", settings_manager=settings_manager, enable_tray=False)
    qtbot.addWidget(application.window)

    assert application.package.animations["idle"].speed_multiplier == 1.0
    assert application.package.animations["idle"].frame_durations_ms == (200, 80, 120, 160)
