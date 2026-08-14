"""托盘显隐动作必须以桌宠窗口真实状态为准。"""

from __future__ import annotations

from pathlib import Path

from petnest.ui.pet_window import PetWindow
from petnest.ui.tray_icon import PetTrayIcon
from tests.test_pet_window import _package


def test_tray_visibility_action_uses_actual_window_state(qtbot, tmp_path: Path) -> None:
    window = PetWindow(_package(tmp_path))
    qtbot.addWidget(window)
    requested: list[bool] = []
    tray = PetTrayIcon(window, on_visibility_changed=requested.append)

    window.hide()
    tray.sync_visibility_action()
    assert tray.toggle_visibility_action.text() == "显示"

    tray.toggle_visibility_action.trigger()

    assert requested == [True]
    assert window.isVisible()


def test_tray_visibility_action_labels_visible_window_as_hide(qtbot, tmp_path: Path) -> None:
    window = PetWindow(_package(tmp_path))
    qtbot.addWidget(window)
    tray = PetTrayIcon(window)
    window.show()

    tray.sync_visibility_action()

    assert tray.toggle_visibility_action.text() == "隐藏"
