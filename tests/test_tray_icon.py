"""托盘显隐动作必须以桌宠窗口真实状态为准。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QAction, QKeySequence

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


def test_tray_refreshes_visibility_label_before_menu_opens(qtbot, tmp_path: Path) -> None:
    window = PetWindow(_package(tmp_path))
    qtbot.addWidget(window)
    tray = PetTrayIcon(window)
    assert tray.toggle_visibility_action.text() == "显示"

    window.show()
    tray.menu.aboutToShow.emit()

    assert tray.toggle_visibility_action.text() == "隐藏"


def test_tray_omits_cursor_style_and_manual_resource_update_entries(qtbot, tmp_path: Path) -> None:
    window = PetWindow(_package(tmp_path))
    qtbot.addWidget(window)
    tray = PetTrayIcon(window)

    texts = [action.text() for action in tray.menu.actions()]

    assert all("鼠标样式" not in text and "资源更新" not in text for text in texts)
    assert not hasattr(tray, "cursor_styles_action")
    assert not hasattr(tray, "resource_update_action")


def test_macos_quit_action_owns_the_native_quit_role(qtbot, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("petnest.ui.tray_icon.sys.platform", "darwin")
    window = PetWindow(_package(tmp_path))
    qtbot.addWidget(window)

    tray = PetTrayIcon(window)

    assert tray.quit_action.menuRole() is QAction.MenuRole.QuitRole
    assert tray.quit_action.shortcut() == QKeySequence(QKeySequence.StandardKey.Quit)
