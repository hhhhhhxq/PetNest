"""Godot 高级版调用的独立维护窗口。"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QDialog, QMessageBox

from petnest.ui.maintenance_dialog import MaintenanceDialog


def test_maintenance_dialog_rejects_unknown_mode(qtbot) -> None:
    del qtbot
    try:
        MaintenanceDialog("unknown")
    except ValueError:
        pass
    else:
        raise AssertionError("unknown maintenance mode must be rejected")


def test_app_update_launches_verified_updater_then_closes_helper(qtbot, tmp_path: Path, monkeypatch) -> None:
    advanced = (tmp_path / "advanced" / "PetNestGodot.exe").resolve()
    executable = (tmp_path / "PetNest.exe").resolve()
    installer = (tmp_path / "updates" / "PetNest-Setup.exe").resolve()
    launched: list[tuple[list[str], str | None]] = []

    monkeypatch.setattr("petnest.ui.maintenance_dialog.sys.executable", str(executable))
    monkeypatch.setattr(MaintenanceDialog, "_start_check", lambda self: None)
    monkeypatch.setattr(
        "petnest.ui.maintenance_dialog.subprocess.Popen",
        lambda command, cwd=None, **_kwargs: launched.append((command, cwd)),
    )
    monkeypatch.setattr(QMessageBox, "information", lambda *_args, **_kwargs: QMessageBox.StandardButton.Ok)

    dialog = MaintenanceDialog("app-update", parent_pid=4321, restart_path=advanced)
    qtbot.addWidget(dialog)
    dialog._launch_updater(installer)

    assert launched == [
        (
            [
                str(tmp_path / "PetNestUpdater.exe"),
                "--wait-pid",
                "4321",
                "--installer",
                str(installer),
                "--restart",
                str(advanced),
            ],
            str(tmp_path),
        )
    ]
    assert dialog.result() == QDialog.DialogCode.Accepted
