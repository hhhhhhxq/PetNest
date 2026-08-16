"""Tests for the unified tray exchange entry."""

from __future__ import annotations

from pathlib import Path

from petnest.ui.pet_window import PetWindow
from petnest.ui.tray_icon import PetTrayIcon
from tests.test_pet_window import _package


def test_tray_exposes_unified_pet_action_entry(qtbot: object, tmp_path: Path) -> None:
    window = PetWindow(_package(tmp_path))
    qtbot.addWidget(window)
    requested: list[bool] = []
    tray = PetTrayIcon(window, on_exchange=lambda: requested.append(True))

    assert tray.exchange_action.text() == "宠物与动作…"
    assert tray.exchange_action in tray.pet_library_menu.actions()
    tray.exchange_action.trigger()
    assert requested == [True]
