"""宠物包选择对话框。"""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QListWidget, QVBoxLayout

from petnest.models.pet_package import PetPackage
from petnest.ui.theme import dialog_stylesheet


class PetSelectorDialog(QDialog):
    """显示已加载的宠物包并返回用户选中的包。"""

    def __init__(self, packages: Sequence[PetPackage], parent: QDialog | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("选择宠物")
        self.setStyleSheet(dialog_stylesheet())
        self._packages = tuple(packages)
        layout = QVBoxLayout(self)
        self.package_list = QListWidget(self)
        for package in self._packages:
            self.package_list.addItem(package.name)
        if self._packages:
            self.package_list.setCurrentRow(0)
        layout.addWidget(self.package_list)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @property
    def selected_package(self) -> PetPackage | None:
        """当前选择；没有可选包或未选择时为 ``None``。"""
        index = self.package_list.currentRow()
        return self._packages[index] if 0 <= index < len(self._packages) else None
