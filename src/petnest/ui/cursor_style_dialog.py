"""独立的鼠标光标主题设置窗口。"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox, QLabel, QPushButton, QVBoxLayout

from petnest.core.cursor_style_catalog import CursorStyle
from petnest.models.settings import Settings
from petnest.ui.theme import dialog_stylesheet


class CursorStyleDialog(QDialog):
    def __init__(
        self,
        settings: Settings,
        cursor_styles: list[CursorStyle],
        parent: QDialog | None = None,
        *,
        supported_roles: Iterable[str] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("鼠标样式")
        self.setStyleSheet(dialog_stylesheet())
        self._settings = settings
        self._styles = cursor_styles
        self._supported_roles = frozenset(supported_roles) if supported_roles is not None else None
        layout = QVBoxLayout(self)
        self.cursor_style_enabled_input = QCheckBox("使用自定义鼠标样式", self)
        self.cursor_style_enabled_input.setChecked(settings.cursor_style_enabled)
        self.cursor_style_input = QComboBox(self)
        self.cursor_style_input.addItem("系统默认", None)
        for style in cursor_styles:
            self.cursor_style_input.addItem(style.display_name, style.identifier)
        self.cursor_style_input.setCurrentIndex(max(0, self.cursor_style_input.findData(settings.cursor_style_id)))
        self.cursor_preview = QLabel(self)
        self.cursor_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cursor_preview.setMinimumSize(120, 120)
        layout.addWidget(self.cursor_style_enabled_input)
        layout.addWidget(self.cursor_style_input)
        layout.addWidget(self.cursor_preview)
        layout.addWidget(QLabel("跟随鼠标时，宠物会按光标可见边缘自动保留间隔。", self))
        restore = QPushButton("恢复系统默认样式", self)
        restore.clicked.connect(lambda: (self.cursor_style_enabled_input.setChecked(False), self.cursor_style_input.setCurrentIndex(0)))
        layout.addWidget(restore)
        roles = QGroupBox("本主题已包含的光标", self)
        role_layout = QFormLayout(roles)
        layout.addWidget(roles)
        self._role_layout = role_layout
        self.cursor_style_enabled_input.toggled.connect(self._update)
        self.cursor_style_input.currentIndexChanged.connect(self._update)
        self._update()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _update(self) -> None:
        enabled = self.cursor_style_enabled_input.isChecked()
        if enabled and self.cursor_style_input.currentData() is None and self.cursor_style_input.count() > 1:
            self.cursor_style_input.setCurrentIndex(1)
        self.cursor_style_input.setEnabled(enabled)
        style = next((item for item in self._styles if item.identifier == self.cursor_style_input.currentData()), None)
        pixmap = QPixmap(str(style.preview_path)) if style else QPixmap()
        self.cursor_preview.setPixmap(pixmap.scaled(108, 108, Qt.AspectRatioMode.KeepAspectRatio) if not pixmap.isNull() else QPixmap())
        self.cursor_preview.setText("使用系统默认样式" if style is None else "")
        while self._role_layout.rowCount():
            self._role_layout.removeRow(0)
        for role, label in (("arrow", "普通箭头"), ("busy", "忙碌中"), ("text", "文本选择"), ("move", "拖拽/移动"), ("resize_horizontal", "水平调整"), ("resize_vertical", "垂直调整"), ("resize_diag_1", "左上↘右下调整"), ("resize_diag_2", "右上↙左下调整")):
            supported = self._supported_roles is None or role in self._supported_roles
            self._role_layout.addRow(
                label,
                QLabel("主题样式" if style and role in style.roles and supported else "使用系统默认", self),
            )

    def updated_settings(self) -> Settings:
        selected = self.cursor_style_input.currentData()
        return replace(self._settings, cursor_style_enabled=self.cursor_style_enabled_input.isChecked(), cursor_style_id=str(selected) if isinstance(selected, str) and self.cursor_style_enabled_input.isChecked() else None)
