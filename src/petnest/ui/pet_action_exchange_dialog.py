"""宠物与动作交换中心的统一窗口。"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from petnest.models.pet_package import PetPackage
from petnest.ui.action_export_page import ActionExportPage
from petnest.ui.action_import_page import ActionImportPage
from petnest.ui.pet_import_page import PetImportPage
from petnest.ui.theme import dialog_stylesheet


class PetActionExchangeDialog(QDialog):
    """把三种导入/导出能力放到同一窗口，旧入口可定位到指定页面。"""

    pet_installed = Signal(str, object)
    actions_installed = Signal(str, object)

    def __init__(
        self,
        packages: Sequence[PetPackage],
        pets_root: Path,
        *,
        is_pet_locked: Callable[[str], bool] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("petActionExchangeDialog")
        self.setWindowTitle("宠物与动作")
        self.resize(1100, 720)
        self.setMinimumSize(900, 600)
        self.setStyleSheet(dialog_stylesheet())
        self._page_labels = ["导入宠物", "导入动作", "导出动作"]

        root = QVBoxLayout(self)
        shell = QFrame(self)
        shell.setObjectName("windowShell")
        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(18, 18, 18, 16)
        header = QHBoxLayout()
        title = QLabel("宠物与动作", shell)
        title.setObjectName("pageTitle")
        header.addWidget(title)
        header.addStretch(1)
        subtitle = QLabel("导入、更新、预览和分享都在这里完成", shell)
        subtitle.setObjectName("mutedLabel")
        header.addWidget(subtitle)
        shell_layout.addLayout(header)

        body = QHBoxLayout()
        self.navigation = QListWidget(shell)
        self.navigation.setObjectName("settingsNavigation")
        for label in self._page_labels:
            self.navigation.addItem(QListWidgetItem(label, self.navigation))
        self.navigation.setFixedWidth(150)
        body.addWidget(self.navigation)
        self.stack = QStackedWidget(shell)
        self.pet_import_page = PetImportPage(
            packages,
            pets_root,
            is_pet_locked=is_pet_locked,
            parent=self.stack,
        )
        self.action_import_page = ActionImportPage(
            packages,
            pets_root,
            is_pet_locked=is_pet_locked,
            parent=self.stack,
        )
        self.action_export_page = ActionExportPage(packages, self.stack)
        self.stack.addWidget(self.pet_import_page)
        self.stack.addWidget(self.action_import_page)
        self.stack.addWidget(self.action_export_page)
        body.addWidget(self.stack, 1)
        shell_layout.addLayout(body, 1)

        footer = QHBoxLayout()
        footer.addStretch(1)
        close_button = QPushButton("关闭", shell)
        close_button.clicked.connect(self.reject)
        footer.addWidget(close_button)
        shell_layout.addLayout(footer)
        root.addWidget(shell)
        self.navigation.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.navigation.setCurrentRow(0)
        self.pet_import_page.pet_installed.connect(self.pet_installed.emit)
        self.action_import_page.actions_installed.connect(self.actions_installed.emit)

    def page_names(self) -> list[str]:
        return list(self._page_labels)

    def current_page_name(self) -> str:
        index = self.stack.currentIndex()
        return self._page_labels[index] if 0 <= index < len(self._page_labels) else ""

    def select_page(self, name: str) -> None:
        if name not in self._page_labels:
            raise ValueError(f"未知交换页面：{name}")
        self.navigation.setCurrentRow(self._page_labels.index(name))


__all__ = ["PetActionExchangeDialog"]
