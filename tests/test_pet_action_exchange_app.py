"""Tests for application integration of the exchange center."""

from __future__ import annotations

from pathlib import Path

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
