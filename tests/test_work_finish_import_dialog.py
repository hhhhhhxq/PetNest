"""下班动画本地导入对话框。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QMessageBox

from petnest.core.package_loader import PackageLoader
from petnest.ui.work_finish_import_dialog import WorkFinishImportDialog
from tests.test_package_validator import _write_package, _write_png
from tests.test_work_finish_importer import _bundle


def test_dialog_inspects_and_installs_selected_folder(qtbot, tmp_path: Path) -> None:
    package = PackageLoader().load(_write_package(tmp_path / "pet"))
    dialog = WorkFinishImportDialog(package)
    qtbot.addWidget(dialog)

    dialog.set_source(_bundle(tmp_path / "bundle"))

    assert "平安下班" in dialog.summary_label.text()
    assert "3 帧" in dialog.summary_label.text()
    assert "保持最后一帧" in dialog.summary_label.text()
    assert dialog.install_button.isEnabled()

    dialog.install_selected()

    assert dialog.imported_result is not None
    assert dialog.imported_result.pet_root == package.root


def test_dialog_reports_optional_lie_loop_frames(qtbot, tmp_path: Path) -> None:
    package = PackageLoader().load(_write_package(tmp_path / "pet"))
    dialog = WorkFinishImportDialog(package)
    qtbot.addWidget(dialog)

    dialog.set_source(_bundle(tmp_path / "bundle", include_loop=True))

    assert "循环 3 帧" in dialog.summary_label.text()


def test_existing_lie_loop_also_requires_replace_confirmation(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    package = PackageLoader().load(_write_package(tmp_path / "pet"))
    _write_png(package.root / "animations" / "work_finish_lie_loop" / "001.png")
    dialog = WorkFinishImportDialog(package)
    qtbot.addWidget(dialog)
    dialog.set_source(_bundle(tmp_path / "bundle"))
    prompts: list[bool] = []
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: prompts.append(True) or QMessageBox.StandardButton.No,
    )

    dialog.install_selected()

    assert prompts == [True]
    assert dialog.imported_result is None
