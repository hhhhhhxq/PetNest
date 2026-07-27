"""Codex 标准精灵图的本地文件导入对话框。"""

from __future__ import annotations

from pathlib import Path
import re

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
)

from petnest.core.spritesheet_importer import SpriteSheetImportError, SpriteSheetImporter, SpriteSheetImportResult


class SpriteSheetImportDialog(QDialog):
    """显示格式规则并把用户明确选择的本地文件导入到宠物目录。"""

    def __init__(self, pets_root: Path, parent: object | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("导入 Codex 精灵图")
        self._pets_root = pets_root
        self._importer = SpriteSheetImporter()
        self.imported_result: SpriteSheetImportResult | None = None

        layout = QFormLayout(self)
        self.rules_label = QLabel(
            "仅读取你在本机选择的文件，不上传或联网。\n"
            "仅支持透明 PNG：1536 × 1872 像素、8 列 × 9 行、每格 192 × 208。\n"
            "默认映射：idle → idle；running-right → drag；waving → click；"
            "jumping → drop；failed → error；waiting → waiting；running → working；review → hover。\n"
            "running-left 会保留为 codex_running_left；success 缺失时回退到 idle。"
        )
        self.rules_label.setWordWrap(True)
        layout.addRow(self.rules_label)

        self.source_input = QLineEdit(self)
        self.source_input.setPlaceholderText("选择本地 PNG 精灵图")
        self.source_input.textChanged.connect(self._suggest_pet_id)
        browse = QPushButton("选择文件…", self)
        browse.clicked.connect(self.choose_source)
        layout.addRow("精灵图", self.source_input)
        layout.addRow("", browse)

        self.pet_id_input = QLineEdit(self)
        self.pet_id_input.setPlaceholderText("例如 codex_cat")
        self.name_input = QLineEdit(self)
        self.name_input.setPlaceholderText("可选，默认使用宠物 ID")
        layout.addRow("宠物 ID", self.pet_id_input)
        layout.addRow("显示名称", self.name_input)

        self.status_label = QLabel("选择文件后会在导入时再次校验。", self)
        self.status_label.setWordWrap(True)
        layout.addRow(self.status_label)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel, self)
        self.import_button = self.buttons.addButton("导入", QDialogButtonBox.ButtonRole.AcceptRole)
        self.import_button.clicked.connect(self.import_selected)
        self.buttons.rejected.connect(self.reject)
        layout.addRow(self.buttons)

    def choose_source(self) -> None:
        """只允许用户通过标准本地文件选择器选择 PNG。"""
        selected, _ = QFileDialog.getOpenFileName(self, "选择 Codex 精灵图", str(Path.home()), "PNG 图像 (*.png)")
        if selected:
            self.source_input.setText(selected)

    def import_selected(self) -> None:
        """校验并导入当前选择；失败时保留对话框和原有宠物目录。"""
        source_text = self.source_input.text().strip()
        identifier = self.pet_id_input.text().strip()
        if not source_text or not identifier:
            self._show_error("请选择 PNG 文件并填写宠物 ID。")
            return
        try:
            self.imported_result = self._importer.import_file(
                Path(source_text), self._pets_root, identifier, name=self.name_input.text().strip() or None
            )
        except (OSError, SpriteSheetImportError) as error:
            self.status_label.setText(f"导入失败：{error}")
            self._show_error(str(error))
            return
        self.status_label.setText(f"导入完成：{self.imported_result.package_root}")
        self.accept()

    def _suggest_pet_id(self, source: str) -> None:
        if self.pet_id_input.text().strip() or not source:
            return
        candidate = re.sub(r"[^a-z0-9_-]+", "_", Path(source).stem.lower()).strip("_-")
        if candidate and candidate[0].isalpha():
            self.pet_id_input.setText(candidate)

    def _show_error(self, message: str) -> None:
        QMessageBox.warning(self, "无法导入精灵图", message)
