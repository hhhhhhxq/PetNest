"""应用装配与平台安全降级的回归测试。"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from petnest.app import PetNest
from petnest.core.settings_manager import SettingsManager
from petnest.models.settings import Settings
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


def test_check_mode_can_load_bundled_sample_package() -> None:
    assert PetNest.check_installation() == 0
