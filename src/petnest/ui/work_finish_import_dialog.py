"""为当前宠物选择并安装 ZIP/文件夹下班动画。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from petnest.core.work_finish_importer import (
    WorkFinishImportError,
    WorkFinishImporter,
    WorkFinishImportResult,
)
from petnest.models.pet_package import PetPackage
from petnest.ui.theme import dialog_stylesheet


class WorkFinishImportDialog(QDialog):
    """导入前展示目标、帧数和画布，避免装到错误宠物。"""

    def __init__(self, package: PetPackage, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.package = package
        self.importer = WorkFinishImporter()
        self.source: Path | None = None
        self.imported_result: WorkFinishImportResult | None = None
        self.setWindowTitle(f"导入下班动画 — {package.name}")
        self.setMinimumWidth(520)
        self.setStyleSheet(dialog_stylesheet())
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"目标宠物：{package.name}", self))
        self.source_label = QLabel("尚未选择 ZIP 或文件夹", self)
        self.summary_label = QLabel("选择后将先完成安全校验，不会立即覆盖现有动画。", self)
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.source_label)
        layout.addWidget(self.summary_label)
        pickers = QHBoxLayout()
        zip_button = QPushButton("选择 ZIP…", self)
        folder_button = QPushButton("选择文件夹…", self)
        zip_button.clicked.connect(self._choose_zip)
        folder_button.clicked.connect(self._choose_folder)
        pickers.addWidget(zip_button)
        pickers.addWidget(folder_button)
        layout.addLayout(pickers)
        actions = QHBoxLayout()
        actions.addStretch(1)
        cancel_button = QPushButton("取消", self)
        self.install_button = QPushButton("安装到当前宠物", self)
        self.install_button.setEnabled(False)
        cancel_button.clicked.connect(self.reject)
        self.install_button.clicked.connect(self.install_selected)
        actions.addWidget(cancel_button)
        actions.addWidget(self.install_button)
        layout.addLayout(actions)

    def set_source(self, source: Path) -> None:
        summary = self.importer.inspect(Path(source))
        self.source = Path(source)
        self.source_label.setText(str(self.source))
        loop_summary = (
            f"循环 {summary.lie_loop_frames} 帧"
            if summary.lie_loop_frames
            else "躺下后保持最后一帧"
        )
        self.summary_label.setText(
            f"{summary.name} · 画布 {summary.canvas[0]} × {summary.canvas[1]} · "
            f"走路 {summary.walk_frames} 帧 · 躺下 {summary.lie_down_frames} 帧 · {loop_summary}"
        )
        self.install_button.setEnabled(True)

    def install_selected(self) -> None:
        if self.source is None:
            return
        has_existing = any(
            (self.package.root / "animations" / action).exists()
            for action in ("work_finish_walk", "work_finish_lie_down", "work_finish_lie_loop")
        )
        if has_existing and QMessageBox.question(
            self,
            "替换下班动画",
            f"{self.package.name} 已有下班动画，确定替换吗？",
        ) != QMessageBox.StandardButton.Yes:
            return
        try:
            self.imported_result = self.importer.install(self.source, self.package.root)
        except WorkFinishImportError as error:
            QMessageBox.critical(self, "无法导入下班动画", str(error))
            return
        self.accept()

    def _choose_zip(self) -> None:
        filename, _filter = QFileDialog.getOpenFileName(self, "选择下班动画 ZIP", "", "ZIP 动画包 (*.zip)")
        if filename:
            self._inspect_selected(Path(filename))

    def _choose_folder(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "选择下班动画文件夹")
        if directory:
            self._inspect_selected(Path(directory))

    def _inspect_selected(self, source: Path) -> None:
        try:
            self.set_source(source)
        except WorkFinishImportError as error:
            self.source = None
            self.install_button.setEnabled(False)
            QMessageBox.warning(self, "动画包无效", str(error))


__all__ = ["WorkFinishImportDialog"]
