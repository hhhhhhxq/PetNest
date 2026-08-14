"""下班动画本地导入对话框。"""

from __future__ import annotations

from pathlib import Path

from petnest.core.package_loader import PackageLoader
from petnest.ui.work_finish_import_dialog import WorkFinishImportDialog
from tests.test_package_validator import _write_package
from tests.test_work_finish_importer import _bundle


def test_dialog_inspects_and_installs_selected_folder(qtbot, tmp_path: Path) -> None:
    package = PackageLoader().load(_write_package(tmp_path / "pet"))
    dialog = WorkFinishImportDialog(package)
    qtbot.addWidget(dialog)

    dialog.set_source(_bundle(tmp_path / "bundle"))

    assert "平安下班" in dialog.summary_label.text()
    assert "3 帧" in dialog.summary_label.text()
    assert dialog.install_button.isEnabled()

    dialog.install_selected()

    assert dialog.imported_result is not None
    assert dialog.imported_result.pet_root == package.root
