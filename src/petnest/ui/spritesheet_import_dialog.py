"""精灵图导入内容的兼容对话框外壳。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from petnest.core.spritesheet_importer import SpriteSheetImportResult
from petnest.ui.spritesheet_import_content import (
    SourceDropZone,
    SpriteGridHint,
    SpriteSheetImportContent,
)
from petnest.ui.theme import dialog_stylesheet

__all__ = ["SourceDropZone", "SpriteGridHint", "SpriteSheetImportDialog"]


class SpriteSheetImportDialog(QDialog):
    """为旧调用方保留的顶层窗口，并组合可复用导入内容。"""

    _CONTENT_ALIASES = (
        "source_input",
        "source_dropzone",
        "rules_label",
        "pet_id_input",
        "name_input",
        "auto_skip_radio",
        "manual_select_radio",
        "mode_group",
        "manual_selection_panel",
        "action_list",
        "manual_frame_title",
        "manual_frame_hint",
        "manual_selected_label",
        "thumbnail_area",
        "thumbnail_content",
        "thumbnail_grid",
        "content_scroll",
        "content_container",
        "initial_content",
        "status_label",
    )

    def __init__(self, pets_root: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("spritesheetImportDialog")
        self.setWindowTitle("导入 Codex 精灵图")
        self.resize(1180, 760)
        self.setMinimumSize(1000, 680)
        self._preferred_minimum_height = 680
        self.setStyleSheet(dialog_stylesheet())
        self.imported_result: SpriteSheetImportResult | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(0)
        self.window_shell = QFrame(self)
        self.window_shell.setObjectName("windowShell")
        shell_layout = QVBoxLayout(self.window_shell)
        shell_layout.setContentsMargins(18, 18, 18, 16)
        shell_layout.setSpacing(14)

        header = QFrame(self.window_shell)
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

        step_bar = QFrame(self.window_shell)
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

        self.content = SpriteSheetImportContent(pets_root, show_source_picker=True, parent=self.window_shell)
        shell_layout.addWidget(self.content, 1)
        for name in self._CONTENT_ALIASES:
            setattr(self, name, getattr(self.content, name))
        self.auto_skip_radio.toggled.connect(self._update_step)
        self.content.error_occurred.connect(self._show_error)

        footer = QHBoxLayout()
        footer.addWidget(self.status_label, 1)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel, self.window_shell)
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        self.import_button = self.buttons.addButton("导入", QDialogButtonBox.ButtonRole.AcceptRole)
        self.import_button.setObjectName("primaryButton")
        self.import_button.clicked.connect(self.import_selected)
        self.buttons.rejected.connect(self.reject)
        footer.addWidget(self.buttons)
        shell_layout.addLayout(footer)
        root.addWidget(self.window_shell)
        self._fit_initial_height()

    def _fit_initial_height(self, available_height: int | None = None) -> None:
        """在打开时尽量容纳初始表单，同时为屏幕边缘预留空间。"""
        if available_height is None:
            screen = self.screen()
            if screen is None and self.parentWidget() is not None:
                screen = self.parentWidget().screen()
            if screen is None:
                screen = QApplication.primaryScreen()
            if screen is None:
                return
            available_height = screen.availableGeometry().height()

        available_height = max(1, int(available_height))
        self.setMinimumHeight(min(self._preferred_minimum_height, available_height - 40))
        content_height = self.content_container.sizeHint().height()
        chrome_height = self.layout().sizeHint().height() - self.content_scroll.sizeHint().height()
        natural_height = max(self.minimumHeight(), content_height + max(0, chrome_height))
        maximum_height = max(self.minimumHeight(), available_height - 40)
        self.resize(self.width(), min(natural_height, maximum_height))

    def choose_source(self) -> None:
        self.content.choose_source()

    def import_selected(self) -> None:
        result = self.content.import_selected()
        if result is None:
            return
        self.imported_result = result
        self.accept()

    def _update_step(self, automatic: bool) -> None:
        self.step_label.setText("1  选择文件" if automatic else "2  确认动作帧")

    def _show_error(self, message: str) -> None:
        QMessageBox.warning(self, "无法导入", message)
