"""应用更新对话框的状态和按钮行为。"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt

from petnest.core.app_update import AppUpdateAsset, AppUpdateInfo
from petnest.ui.app_update_dialog import AppUpdateDialog


def _info() -> AppUpdateInfo:
    return AppUpdateInfo(
        version="0.2.0",
        platform="windows-x64",
        asset=AppUpdateAsset("https://github.com/hhhhhhxq/PetNest/releases/download/v0.2.0/a.exe", 4, "0" * 64),
        release_notes="更稳定的更新流程",
    )


def test_update_dialog_exposes_check_and_download_states(qtbot) -> None:
    checked: list[bool] = []
    downloads: list[AppUpdateInfo] = []
    dialog = AppUpdateDialog(
        "0.1.0",
        on_check=lambda: checked.append(True),
        on_download=lambda info: downloads.append(info),
    )
    qtbot.addWidget(dialog)

    assert "PingFang SC" in dialog.styleSheet()
    assert dialog.download_button.isHidden()
    qtbot.mouseClick(dialog.check_button, Qt.MouseButton.LeftButton)
    assert checked == [True]

    dialog.set_available(_info())
    assert dialog.version_label.text() == "发现新版本 0.2.0"
    assert not dialog.download_button.isHidden()
    qtbot.mouseClick(dialog.download_button, Qt.MouseButton.LeftButton)
    assert downloads and downloads[0].version == "0.2.0"


def test_update_dialog_error_and_progress_are_safe(qtbot) -> None:
    dialog = AppUpdateDialog("0.1.0")
    qtbot.addWidget(dialog)

    dialog.set_checking()
    assert not dialog.check_button.isEnabled()
    dialog.set_error("网络不可用")
    assert dialog.check_button.isEnabled()
    assert "网络不可用" in dialog.status_label.text()
    dialog.set_downloading(43)
    assert dialog.progress_bar.value() == 43
    dialog.set_finished()
    assert dialog.progress_bar.value() == 100
