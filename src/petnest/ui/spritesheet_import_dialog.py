"""Codex 标准精灵图的本地文件导入与逐行动作选择对话框。"""

from __future__ import annotations

from pathlib import Path
import re

from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from petnest.core.spritesheet_importer import (
    SpriteSheetImportError,
    SpriteSheetImporter,
    SpriteSheetImportResult,
    SpriteSheetInspection,
    _ROW_MAPPINGS,
)
from petnest.ui.theme import dialog_stylesheet


_TRIGGER_TEXT = {
    "idle": "默认待机",
    "drag": "拖动宠物时",
    "codex_running_left": "可由外部事件触发",
    "click": "鼠标点击时",
    "drop": "结束拖动时",
    "error": "任务报错时",
    "waiting": "任务等待时",
    "working": "任务工作时",
    "hover": "鼠标移入时",
}


class SpriteSheetImportDialog(QDialog):
    """从本机选取精灵图，并在需要时逐行动作选择格位。"""

    def __init__(self, pets_root: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("spritesheetImportDialog")
        self.setWindowTitle("导入 Codex 精灵图")
        self.resize(920, 680)
        self.setMinimumSize(820, 620)
        self.setStyleSheet(dialog_stylesheet())
        self._pets_root = pets_root
        self._importer = SpriteSheetImporter()
        self._inspection: SpriteSheetInspection | None = None
        self._selected_columns: dict[str, set[int]] = {}
        self.imported_result: SpriteSheetImportResult | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 16)
        root.setSpacing(14)
        header = QHBoxLayout()
        title = QLabel("导入精灵图", self)
        title.setObjectName("pageTitle")
        self.step_label = QLabel("1  选择精灵图", self)
        self.step_label.setStyleSheet("color: #D98663; font-weight: 700;")
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self.step_label)
        root.addLayout(header)
        form = QFormLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)
        self.rules_label = QLabel(
            "仅读取你在本机选择的文件，不上传或联网。\n"
            "仅支持透明 PNG：1536 × 1872 像素、8 列 × 9 行、每格 192 × 208。\n"
            "PetNest 宠物包可使用任意数量的 PNG 帧；此 8×9 图集的每行最多有 8 个格位。"
            "自动模式按透明像素跳过无内容格位。\n"
            "默认映射：idle → idle；running-right → drag；waving → click；"
            "jumping → drop；failed → error；waiting → waiting；running → working；review → hover。"
        )
        self.rules_label.setWordWrap(True)
        self.rules_label.setObjectName("mutedLabel")
        form.addRow(self.rules_label)

        self.source_input = QLineEdit(self)
        self.source_input.setPlaceholderText("选择本地 PNG 精灵图")
        self.source_input.textChanged.connect(self._suggest_pet_id)
        self.source_input.textChanged.connect(self._inspect_source)
        browse = QPushButton("选择文件…", self)
        browse.clicked.connect(self.choose_source)
        form.addRow("精灵图", self.source_input)
        form.addRow("", browse)
        self.pet_id_input = QLineEdit(self)
        self.pet_id_input.setPlaceholderText("例如 codex_cat")
        self.name_input = QLineEdit(self)
        self.name_input.setPlaceholderText("可选，默认使用宠物 ID")
        form.addRow("宠物 ID", self.pet_id_input)
        form.addRow("显示名称", self.name_input)
        root.addLayout(form)

        mode_box = QFrame(self)
        mode_box.setObjectName("settingsCard")
        mode_layout = QVBoxLayout(mode_box)
        mode_layout.setContentsMargins(8, 8, 8, 8)
        self.auto_skip_radio = QRadioButton("自动跳过无内容帧", mode_box)
        self.manual_select_radio = QRadioButton("手动选择所需帧", mode_box)
        self.auto_skip_radio.setChecked(True)
        self.mode_group = QButtonGroup(mode_box)
        self.mode_group.addButton(self.auto_skip_radio)
        self.mode_group.addButton(self.manual_select_radio)
        mode_layout.addWidget(self.auto_skip_radio)
        mode_layout.addWidget(QLabel("扫描每格 alpha 像素，按从左到右顺序直接保存；原图不会被修改。", mode_box))
        mode_layout.addWidget(self.manual_select_radio)
        mode_layout.addWidget(QLabel("仅在此模式显示缩略图。检测到有内容的格位会预选，也可保留透明停顿帧。", mode_box))
        self.auto_skip_radio.toggled.connect(self._toggle_manual_selection)
        root.addWidget(mode_box)

        self.manual_selection_panel = QFrame(self)
        self.manual_selection_panel.setObjectName("settingsCard")
        panel_layout = QHBoxLayout(self.manual_selection_panel)
        self.action_list = QListWidget(self.manual_selection_panel)
        self.action_list.setMaximumWidth(220)
        self.action_list.currentItemChanged.connect(self._show_selected_action)
        panel_layout.addWidget(self.action_list)
        self.thumbnail_area = QScrollArea(self.manual_selection_panel)
        self.thumbnail_area.setWidgetResizable(True)
        self.thumbnail_content = QWidget(self.thumbnail_area)
        self.thumbnail_grid = QGridLayout(self.thumbnail_content)
        self.thumbnail_area.setWidget(self.thumbnail_content)
        panel_layout.addWidget(self.thumbnail_area, 1)
        root.addWidget(self.manual_selection_panel, 1)
        self.manual_selection_panel.hide()

        self.status_label = QLabel("选择文件后会检测每一格是否含有像素。", self)
        self.status_label.setObjectName("mutedLabel")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel, self)
        self.import_button = self.buttons.addButton("导入", QDialogButtonBox.ButtonRole.AcceptRole)
        self.import_button.setObjectName("primaryButton")
        self.import_button.clicked.connect(self.import_selected)
        self.buttons.rejected.connect(self.reject)
        root.addWidget(self.buttons)

    def choose_source(self) -> None:
        """只允许用户通过标准本地文件选择器选择 PNG。"""
        selected, _ = QFileDialog.getOpenFileName(self, "选择 Codex 精灵图", str(Path.home()), "PNG 图像 (*.png)")
        if selected:
            self.source_input.setText(selected)

    def import_selected(self) -> None:
        """校验并导入当前选择；失败时保留对话框与已有宠物目录。"""
        source_text = self.source_input.text().strip()
        identifier = self.pet_id_input.text().strip()
        if not source_text or not identifier:
            self._show_error("请选择 PNG 文件并填写宠物 ID。")
            return
        try:
            self.imported_result = self._importer.import_file(
                Path(source_text), self._pets_root, identifier, name=self.name_input.text().strip() or None,
                selected_columns_by_action=self._manual_columns() if self.manual_select_radio.isChecked() else None,
            )
        except (OSError, SpriteSheetImportError) as error:
            self.status_label.setText(f"导入失败：{error}")
            self._show_error(str(error))
            return
        self.status_label.setText(f"导入完成：{self.imported_result.package_root}")
        self.accept()

    def _inspect_source(self, source: str) -> None:
        """在有效本地路径出现时预先检测格位，以便手动模式立即可编辑。"""
        self._inspection = None
        self._selected_columns.clear()
        self.action_list.clear()
        path = Path(source.strip()) if source.strip() else None
        if path is None or not path.is_file():
            return
        try:
            self._inspection = self._importer.inspect(path)
        except SpriteSheetImportError as error:
            self.status_label.setText(f"无法使用此图片：{error}")
            return
        for row, mapping in enumerate(_ROW_MAPPINGS):
            self._selected_columns[mapping.action] = set(self._inspection.nonempty_columns_by_row[row])
            item = QListWidgetItem(f"{mapping.action}\n{_TRIGGER_TEXT[mapping.action]}")
            item.setData(Qt.ItemDataRole.UserRole, mapping.action)
            self.action_list.addItem(item)
        if self.action_list.count():
            self.action_list.setCurrentRow(0)
        total = sum(len(columns) for columns in self._inspection.nonempty_columns_by_row)
        self.status_label.setText(f"已检测到 {total} 个有内容格位。自动模式会直接导入这些格位。")

    def _toggle_manual_selection(self, automatic: bool) -> None:
        self.manual_selection_panel.setVisible(not automatic)

    def _show_selected_action(self, item: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        while self.thumbnail_grid.count():
            child = self.thumbnail_grid.takeAt(0)
            if child.widget() is not None:
                child.widget().deleteLater()
        if item is None or self._inspection is None:
            return
        action = str(item.data(Qt.ItemDataRole.UserRole))
        row = next(index for index, mapping in enumerate(_ROW_MAPPINGS) if mapping.action == action)
        heading = QLabel(f"{action} — {_TRIGGER_TEXT[action]}（从左到右保存）", self.thumbnail_content)
        self.thumbnail_grid.addWidget(heading, 0, 0, 1, 4)
        for column in range(self._inspection.layout.columns):
            button = QToolButton(self.thumbnail_content)
            button.setCheckable(True)
            button.setChecked(column in self._selected_columns[action])
            button.setText(f"第 {column + 1} 格")
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            button.setIcon(self._thumbnail(row, column))
            button.setIconSize(QPixmap(96, 104).size())
            button.clicked.connect(lambda checked, value=column, name=action: self._set_column_selected(name, value, checked))
            self.thumbnail_grid.addWidget(button, 1 + column // 4, column % 4)

    def _thumbnail(self, row: int, column: int) -> QIcon:
        if self._inspection is None:
            return QIcon()
        with Image.open(self._inspection.source) as source:
            image = source.convert("RGBA")
            left = column * self._inspection.layout.cell_width
            top = row * self._inspection.layout.cell_height
            frame = image.crop((left, top, left + self._inspection.layout.cell_width, top + self._inspection.layout.cell_height))
            frame.thumbnail((96, 104))
            qimage = QImage(frame.tobytes("raw", "RGBA"), frame.width, frame.height, QImage.Format.Format_RGBA8888).copy()
        return QIcon(QPixmap.fromImage(qimage))

    def _set_column_selected(self, action: str, column: int, selected: bool) -> None:
        columns = self._selected_columns[action]
        if selected:
            columns.add(column)
        else:
            columns.discard(column)

    def _manual_columns(self) -> dict[str, tuple[int, ...]]:
        return {action: tuple(sorted(columns)) for action, columns in self._selected_columns.items()}

    def _suggest_pet_id(self, source: str) -> None:
        if self.pet_id_input.text().strip() or not source:
            return
        candidate = re.sub(r"[^a-z0-9_-]+", "_", Path(source).stem.lower()).strip("_-")
        if candidate and candidate[0].isalpha():
            self.pet_id_input.setText(candidate)

    def _show_error(self, message: str) -> None:
        QMessageBox.warning(self, "无法导入精灵图", message)
