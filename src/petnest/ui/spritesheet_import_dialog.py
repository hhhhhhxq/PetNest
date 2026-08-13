"""Codex 标准精灵图的本地文件导入与逐行动作选择对话框。"""

from __future__ import annotations

from pathlib import Path
import re

from PIL import Image
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QDragEnterEvent, QDropEvent, QIcon, QImage, QPainter, QPixmap
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


class SpriteGridHint(QFrame):
    """导入区的 8×9 图集示意，不依赖额外切图资源。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(108, 108)
        self.setMaximumSize(120, 120)

    def paintEvent(self, _event: object) -> None:  # noqa: ARG002 - Qt event signature
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QColor("#D8C5B9"))
        painter.setBrush(QColor("#FBF5F0"))
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 8, 8)
        cell_w = max(1, (self.width() - 12) // 8)
        cell_h = max(1, (self.height() - 12) // 9)
        for row in range(9):
            for col in range(8):
                painter.drawRect(6 + col * cell_w, 6 + row * cell_h, cell_w, cell_h)


class SourceDropZone(QFrame):
    """接收本地 PNG 文件，并将路径交给导入表单。"""

    file_dropped = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)

    @staticmethod
    def _png_path(event: QDragEnterEvent | QDropEvent) -> str | None:
        urls = event.mimeData().urls()
        if not urls:
            return None
        path = urls[0].toLocalFile()
        if not path or Path(path).suffix.lower() != ".png" or not Path(path).is_file():
            return None
        return path

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802 - Qt 覆盖名。
        if self._png_path(event) is not None:
            event.acceptProposedAction()
            return
        event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802 - Qt 覆盖名。
        path = self._png_path(event)
        if path is None:
            event.ignore()
            return
        self.file_dropped.emit(path)
        event.acceptProposedAction()


class SpriteSheetImportDialog(QDialog):
    """从本机选取精灵图，并在需要时逐行动作选择格位。"""

    def __init__(self, pets_root: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("spritesheetImportDialog")
        self.setWindowTitle("导入 Codex 精灵图")
        self.resize(1180, 760)
        self.setMinimumSize(1000, 680)
        self.setStyleSheet(dialog_stylesheet())
        self._pets_root = pets_root
        self._importer = SpriteSheetImporter()
        self._inspection: SpriteSheetInspection | None = None
        self._selected_columns: dict[str, set[int]] = {}
        self.imported_result: SpriteSheetImportResult | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(0)
        window_shell = QFrame(self)
        window_shell.setObjectName("windowShell")
        shell_layout = QVBoxLayout(window_shell)
        shell_layout.setContentsMargins(18, 18, 18, 16)
        shell_layout.setSpacing(14)

        header = QFrame(window_shell)
        header.setObjectName("headerBar")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(18, 13, 18, 13)
        title_column = QVBoxLayout()
        title_column.setSpacing(1)
        title = QLabel("导入 Codex 精灵图", header)
        title.setObjectName("pageTitle")
        subtitle = QLabel("将标准精灵图转换为 PetNest 宠物包", header)
        subtitle.setObjectName("mutedLabel")
        title_column.addWidget(title)
        title_column.addWidget(subtitle)
        header_layout.addLayout(title_column)
        header_layout.addStretch(1)
        header_layout.addWidget(QLabel("×", header))
        shell_layout.addWidget(header)

        step_bar = QFrame(window_shell)
        step_bar.setObjectName("stepBar")
        step_layout = QHBoxLayout(step_bar)
        step_layout.setContentsMargins(20, 11, 20, 11)
        self.step_label = QLabel("1  选择文件", step_bar)
        self.step_label.setStyleSheet("color: #D98663; font-weight: 700;")
        step_layout.addWidget(self.step_label)
        step_layout.addStretch(1)
        step_layout.addWidget(QLabel("2  确认动作帧", step_bar))
        step_layout.addStretch(1)
        step_layout.addWidget(QLabel("3  完成导入", step_bar))
        shell_layout.addWidget(step_bar)

        self.initial_content = QWidget(window_shell)
        initial_layout = QVBoxLayout(self.initial_content)
        initial_layout.setContentsMargins(0, 0, 0, 0)
        initial_layout.setSpacing(14)
        cards_row = QHBoxLayout()
        cards_row.setSpacing(14)
        source_card = QFrame(self.initial_content)
        source_card.setObjectName("sourceCard")
        source_layout = QVBoxLayout(source_card)
        source_layout.setContentsMargins(18, 16, 18, 16)
        source_layout.setSpacing(8)
        source_title = QLabel("选择精灵图", source_card)
        source_title.setStyleSheet("font-size: 17px; font-weight: 700;")
        source_layout.addWidget(source_title)
        source_description = QLabel("从本机选择一张透明 PNG 文件", source_card)
        source_description.setObjectName("mutedLabel")
        source_layout.addWidget(source_description)
        self.source_dropzone = SourceDropZone(source_card)
        self.source_dropzone.setObjectName("sourceDropzone")
        dropzone_layout = QVBoxLayout(self.source_dropzone)
        dropzone_layout.setContentsMargins(16, 14, 16, 14)
        dropzone_layout.setSpacing(6)
        drop_title = QLabel("拖放 PNG 到这里", self.source_dropzone)
        drop_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        drop_title.setStyleSheet("color: #B07962; font-size: 15px; font-weight: 700;")
        dropzone_layout.addWidget(drop_title)
        dropzone_layout.addWidget(SpriteGridHint(self.source_dropzone), 0, Qt.AlignmentFlag.AlignHCenter)
        drop_hint = QLabel("或选择本机文件（不会上传或联网）", self.source_dropzone)
        drop_hint.setObjectName("mutedLabel")
        drop_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dropzone_layout.addWidget(drop_hint)
        self.source_input = QLineEdit(source_card)
        self.source_input.setPlaceholderText("选择本地 PNG 精灵图")
        self.source_dropzone.file_dropped.connect(self.source_input.setText)
        self.source_input.textChanged.connect(self._suggest_pet_id)
        self.source_input.textChanged.connect(self._inspect_source)
        dropzone_layout.addWidget(self.source_input)
        browse = QPushButton("选择文件…", source_card)
        browse.clicked.connect(self.choose_source)
        dropzone_layout.addWidget(browse, 0, Qt.AlignmentFlag.AlignHCenter)
        source_layout.addWidget(self.source_dropzone)
        self.rules_label = QLabel(
            "仅读取本机文件，不上传或联网。透明 PNG：1536 × 1872 像素、8 列 × 9 行、每格 192 × 208。\n"
            "默认映射：running-right → drag；waving → click；jumping → drop；failed → error；"
            "waiting → waiting；running → working；review → hover。\n"
            "自动模式会跳过无内容格位。"
        )
        self.rules_label.setWordWrap(True)
        self.rules_label.setObjectName("mutedLabel")
        source_layout.addWidget(self.rules_label)
        source_layout.addStretch(1)
        cards_row.addWidget(source_card, 3)

        pet_info_card = QFrame(self.initial_content)
        pet_info_card.setObjectName("petInfoCard")
        pet_info_layout = QFormLayout(pet_info_card)
        pet_info_layout.setContentsMargins(18, 16, 18, 16)
        pet_info_layout.setSpacing(12)
        pet_info_title = QLabel("宠物信息", pet_info_card)
        pet_info_title.setStyleSheet("font-size: 17px; font-weight: 700;")
        pet_info_layout.addRow(pet_info_title)
        pet_info_hint = QLabel("导入后会出现在宠物库中", pet_info_card)
        pet_info_hint.setObjectName("mutedLabel")
        pet_info_layout.addRow(pet_info_hint)
        self.pet_id_input = QLineEdit(pet_info_card)
        self.pet_id_input.setPlaceholderText("例如 codex_cat")
        self.name_input = QLineEdit(pet_info_card)
        self.name_input.setPlaceholderText("可选，默认使用宠物 ID")
        pet_info_layout.addRow("宠物 ID", self.pet_id_input)
        pet_info_layout.addRow("显示名称", self.name_input)
        pet_info_layout.addRow(QLabel("ID 支持字母、数字、下划线或短横线", pet_info_card))
        cards_row.addWidget(pet_info_card, 2)
        initial_layout.addLayout(cards_row)

        mode_box = QFrame(self.initial_content)
        mode_box.setObjectName("settingsCard")
        mode_layout = QVBoxLayout(mode_box)
        mode_layout.setContentsMargins(18, 14, 18, 14)
        mode_title = QLabel("导入方式", mode_box)
        mode_title.setStyleSheet("font-size: 17px; font-weight: 700;")
        mode_layout.addWidget(mode_title)
        mode_hint = QLabel("自动识别适合大多数标准精灵图；需要保留透明停顿帧时可手动选择。", mode_box)
        mode_hint.setObjectName("mutedLabel")
        mode_layout.addWidget(mode_hint)
        options_row = QHBoxLayout()
        options_row.setSpacing(12)
        auto_option = QFrame(mode_box)
        auto_option.setObjectName("modeOption")
        auto_option_layout = QVBoxLayout(auto_option)
        auto_option_layout.setContentsMargins(14, 12, 14, 12)
        self.auto_skip_radio = QRadioButton("自动跳过无内容帧", auto_option)
        auto_option_layout.addWidget(self.auto_skip_radio)
        auto_hint = QLabel("扫描透明像素，自动保留有效格位。", auto_option)
        auto_hint.setObjectName("mutedLabel")
        auto_hint.setWordWrap(True)
        auto_option_layout.addWidget(auto_hint)
        manual_option = QFrame(mode_box)
        manual_option.setObjectName("modeOption")
        manual_option_layout = QVBoxLayout(manual_option)
        manual_option_layout.setContentsMargins(14, 12, 14, 12)
        self.manual_select_radio = QRadioButton("手动选择所需帧", manual_option)
        manual_option_layout.addWidget(self.manual_select_radio)
        manual_hint = QLabel("逐个动作确认需要保留的帧。", manual_option)
        manual_hint.setObjectName("mutedLabel")
        manual_hint.setWordWrap(True)
        manual_option_layout.addWidget(manual_hint)
        options_row.addWidget(auto_option, 1)
        options_row.addWidget(manual_option, 1)
        mode_layout.addLayout(options_row)
        self.auto_skip_radio.setChecked(True)
        self.mode_group = QButtonGroup(mode_box)
        self.mode_group.addButton(self.auto_skip_radio)
        self.mode_group.addButton(self.manual_select_radio)
        self.auto_skip_radio.toggled.connect(self._toggle_manual_selection)
        initial_layout.addWidget(mode_box)
        shell_layout.addWidget(self.initial_content, 1)

        self.manual_selection_panel = QFrame(window_shell)
        self.manual_selection_panel.setObjectName("manualSelectionPanel")
        manual_layout = QVBoxLayout(self.manual_selection_panel)
        manual_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout = QHBoxLayout()
        panel_layout.setSpacing(14)
        manual_layout.addLayout(panel_layout)

        manual_action_card = QFrame(self.manual_selection_panel)
        manual_action_card.setObjectName("manualActionCard")
        manual_action_layout = QVBoxLayout(manual_action_card)
        manual_action_layout.setContentsMargins(18, 16, 18, 16)
        manual_action_layout.addWidget(QLabel("动作列表", manual_action_card))
        action_hint = QLabel("选择一个动作查看对应行", manual_action_card)
        action_hint.setObjectName("mutedLabel")
        manual_action_layout.addWidget(action_hint)
        self.action_list = QListWidget(manual_action_card)
        self.action_list.setObjectName("manualActionList")
        self.action_list.currentItemChanged.connect(self._show_selected_action)
        manual_action_layout.addWidget(self.action_list, 1)
        panel_layout.addWidget(manual_action_card, 0)

        manual_frame_card = QFrame(self.manual_selection_panel)
        manual_frame_card.setObjectName("manualFrameCard")
        manual_frame_layout = QVBoxLayout(manual_frame_card)
        manual_frame_layout.setContentsMargins(18, 16, 18, 16)
        self.manual_frame_title = QLabel("请选择一个动作", manual_frame_card)
        manual_frame_title = self.manual_frame_title
        manual_frame_layout.addWidget(manual_frame_title)
        self.manual_frame_hint = QLabel("从左到右保存；点击格位可切换是否保留", manual_frame_card)
        self.manual_frame_hint.setObjectName("mutedLabel")
        manual_frame_layout.addWidget(self.manual_frame_hint)
        self.manual_selected_label = QLabel("", manual_frame_card)
        self.manual_selected_label.setObjectName("selectionBadge")
        manual_frame_layout.addWidget(self.manual_selected_label, 0, Qt.AlignmentFlag.AlignRight)
        self.thumbnail_area = QScrollArea(manual_frame_card)
        self.thumbnail_area.setObjectName("manualThumbnailArea")
        self.thumbnail_area.setWidgetResizable(True)
        self.thumbnail_content = QWidget(self.thumbnail_area)
        self.thumbnail_grid = QGridLayout(self.thumbnail_content)
        self.thumbnail_area.setWidget(self.thumbnail_content)
        manual_frame_layout.addWidget(self.thumbnail_area, 1)
        panel_layout.addWidget(manual_frame_card, 1)
        self.manual_selection_panel.hide()
        shell_layout.addWidget(self.manual_selection_panel, 1)

        footer = QHBoxLayout()
        self.status_label = QLabel("选择文件后会检测图集尺寸与透明格位。", window_shell)
        self.status_label.setObjectName("mutedLabel")
        self.status_label.setWordWrap(True)
        footer.addWidget(self.status_label, 1)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel, window_shell)
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        self.import_button = self.buttons.addButton("导入", QDialogButtonBox.ButtonRole.AcceptRole)
        self.import_button.setObjectName("primaryButton")
        self.import_button.clicked.connect(self.import_selected)
        self.buttons.rejected.connect(self.reject)
        footer.addWidget(self.buttons)
        shell_layout.addLayout(footer)
        root.addWidget(window_shell)

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
            item = QListWidgetItem(
                f"{mapping.action}\n{_TRIGGER_TEXT[mapping.action]} · 已选 "
                f"{len(self._selected_columns[mapping.action])} / {self._inspection.layout.columns} 格"
            )
            item.setData(Qt.ItemDataRole.UserRole, mapping.action)
            self.action_list.addItem(item)
        if self.action_list.count():
            self.action_list.setCurrentRow(0)
        total = sum(len(columns) for columns in self._inspection.nonempty_columns_by_row)
        self.status_label.setText(f"已检测到 {total} 个有内容格位。自动模式会直接导入这些格位。")

    def _toggle_manual_selection(self, automatic: bool) -> None:
        self.manual_selection_panel.setVisible(not automatic)
        # 手动模式仍需保留文件、宠物 ID 和名称输入；选择方式只是追加
        # 一步帧筛选，不能把导入源表单隐藏掉，否则用户会进入无法完成的状态。
        self.initial_content.setVisible(True)
        self.step_label.setText("1  选择文件" if automatic else "2  确认动作帧")

    def _show_selected_action(self, item: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        while self.thumbnail_grid.count():
            child = self.thumbnail_grid.takeAt(0)
            if child.widget() is not None:
                child.widget().deleteLater()
        if item is None or self._inspection is None:
            return
        action = str(item.data(Qt.ItemDataRole.UserRole))
        row = next(index for index, mapping in enumerate(_ROW_MAPPINGS) if mapping.action == action)
        selected = self._selected_columns.get(action, set())
        self.manual_frame_title.setText(f"{action} · {_TRIGGER_TEXT[action]}")
        self.manual_selected_label.setText(f"已选 {len(selected)} / {self._inspection.layout.columns} 格")
        for column in range(self._inspection.layout.columns):
            button = QToolButton(self.thumbnail_content)
            button.setObjectName("frameOption")
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
        if self._inspection is not None and self.action_list.currentItem() is not None:
            self.action_list.currentItem().setText(
                f"{action}\n{_TRIGGER_TEXT[action]} · 已选 {len(columns)} / {self._inspection.layout.columns} 格"
            )
            self.manual_selected_label.setText(f"已选 {len(columns)} / {self._inspection.layout.columns} 格")

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
