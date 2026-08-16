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


def test_pet_library_menu_only_exposes_unified_pet_and_action_management(
    qtbot: object, tmp_path: Path
) -> None:
    window = PetWindow(_package(tmp_path))
    qtbot.addWidget(window)
    tray = PetTrayIcon(window)

    labels = [
        action.text()
        for action in tray.pet_library_menu.actions()
        if not action.isSeparator()
    ]

    assert labels == [
        "宠物与动作…",
        "打开宠物文件夹",
        "刷新宠物列表",
        "重新加载当前宠物",
    ]
    assert all("导入精灵图" not in label for label in labels)
    assert all("下班动画" not in label for label in labels)
    assert all("编辑动画时长" not in label for label in labels)
    assert not hasattr(tray, "import_action")
    assert not hasattr(tray, "import_work_finish_action")
    assert not hasattr(tray, "edit_animations_action")
