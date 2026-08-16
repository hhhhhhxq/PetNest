"""动作分享包导出页面。"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from petnest.core.action_pack import ActionPackError, export_action_pack
from petnest.models.pet_package import PetPackage
from petnest.ui.animation_preview_widget import AnimationPreviewWidget
from petnest.ui.theme import dialog_stylesheet


class ActionExportPage(QWidget):
    """列出宠物全部动作，支持筛选、多选、预览和 ZIP 导出。"""

    def __init__(self, packages: Sequence[PetPackage], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("actionExportPage")
        self.setStyleSheet(dialog_stylesheet())
        self._packages = tuple(packages)
        self._rows: dict[str, QListWidgetItem] = {}
        self._selected_names: set[str] = set()
        self._filtering = False

        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        title = QLabel("导出动作分享包", self)
        title.setObjectName("pageTitle")
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(QLabel("宠物", self))
        self.pet_combo = QComboBox(self)
        for package in self._packages:
            self.pet_combo.addItem(package.name, package.identifier)
        self.pet_combo.currentIndexChanged.connect(self._load_package_actions)
        header.addWidget(self.pet_combo)
        layout.addLayout(header)

        hint = QLabel("选择要分享的动作，可预览全屏动作和逐帧时长；导出时会自动生成 ZIP。", self)
        hint.setObjectName("mutedLabel")
        layout.addWidget(hint)

        filters = QHBoxLayout()
        self.search_input = QLineEdit(self)
        self.search_input.setPlaceholderText("搜索动作名称")
        self.search_input.textChanged.connect(self._apply_filter)
        filters.addWidget(self.search_input, 1)
        self.scope_combo = QComboBox(self)
        self.scope_combo.addItem("全部动作", "all")
        self.scope_combo.addItem("普通动作", "pet")
        self.scope_combo.addItem("全屏动作", "fullscreen")
        self.scope_combo.currentIndexChanged.connect(self._apply_filter)
        filters.addWidget(self.scope_combo)
        select_all = QPushButton("全选可见", self)
        select_all.clicked.connect(lambda: self._select_visible(True))
        filters.addWidget(select_all)
        clear = QPushButton("清空选择", self)
        clear.clicked.connect(lambda: self._select_visible(False))
        filters.addWidget(clear)
        layout.addLayout(filters)

        body = QHBoxLayout()
        self.action_list = QListWidget(self)
        self.action_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        self.action_list.itemSelectionChanged.connect(self._on_selection_changed)
        body.addWidget(self.action_list, 2)
        self.preview = AnimationPreviewWidget(self)
        self.preview.setMinimumWidth(260)
        body.addWidget(self.preview, 1)
        layout.addLayout(body, 1)

        footer = QHBoxLayout()
        self.include_bindings = QCheckBox("同时分享相关绑定", self)
        self.include_bindings.setToolTip("默认关闭，避免覆盖接收方已有快捷绑定")
        footer.addWidget(self.include_bindings)
        self.selection_label = QLabel("已选 0 项", self)
        self.selection_label.setObjectName("mutedLabel")
        footer.addWidget(self.selection_label)
        footer.addStretch(1)
        self.status_label = QLabel("", self)
        self.status_label.setObjectName("mutedLabel")
        footer.addWidget(self.status_label)
        self.export_button = QPushButton("导出 ZIP…", self)
        self.export_button.setObjectName("primaryButton")
        self.export_button.clicked.connect(self._choose_output)
        self.export_button.setEnabled(False)
        footer.addWidget(self.export_button)
        layout.addLayout(footer)
        self._load_package_actions()

    def current_package(self) -> PetPackage | None:
        index = self.pet_combo.currentIndex()
        return self._packages[index] if 0 <= index < len(self._packages) else None

    def visible_action_names(self) -> set[str]:
        return {
            str(item.data(Qt.ItemDataRole.UserRole))
            for item in (self.action_list.item(index) for index in range(self.action_list.count()))
            if item is not None and not item.isHidden()
        }

    def selected_action_names(self) -> set[str]:
        return set(self._selected_names)

    def select_actions(self, names: Sequence[str]) -> None:
        selected = set(names)
        self._selected_names = selected
        self.action_list.blockSignals(True)
        try:
            for index in range(self.action_list.count()):
                item = self.action_list.item(index)
                item.setSelected(str(item.data(Qt.ItemDataRole.UserRole)) in selected)
        finally:
            self.action_list.blockSignals(False)
        self._refresh_preview()

    def export_selected(self, output: Path) -> Path:
        package = self.current_package()
        names = tuple(self.selected_action_names())
        if package is None or not names:
            raise ActionPackError("至少选择一个动作")
        result = export_action_pack(
            package.root,
            names,
            Path(output),
            include_bindings=self.include_bindings.isChecked(),
        )
        self.status_label.setText(f"已导出：{result}")
        return result

    def _load_package_actions(self) -> None:
        self.action_list.clear()
        self._rows.clear()
        self._selected_names.clear()
        package = self.current_package()
        if package is None:
            self.export_button.setEnabled(False)
            self.preview.clear()
            return
        for name, definition in package.animations.items():
            label = f"{name} · {'全屏动作' if definition.scope == 'fullscreen' else '普通动作'} · {len(definition.frames)} 帧"
            item = QListWidgetItem(label, self.action_list)
            item.setData(Qt.ItemDataRole.UserRole, name)
            item.setData(Qt.ItemDataRole.UserRole + 1, definition.scope)
            self._rows[name] = item
        self._apply_filter()

    def _apply_filter(self) -> None:
        preserved = set(self._selected_names)
        query = self.search_input.text().strip().casefold()
        scope = self.scope_combo.currentData()
        self._filtering = True
        try:
            for name, item in self._rows.items():
                item_scope = item.data(Qt.ItemDataRole.UserRole + 1)
                item.setHidden(bool(query and query not in name.casefold()) or (scope != "all" and item_scope != scope))
        finally:
            self._filtering = False
        self._selected_names = preserved
        self._refresh_preview()

    def _select_visible(self, selected: bool) -> None:
        visible = self.visible_action_names()
        if selected:
            self._selected_names.update(visible)
        else:
            self._selected_names.difference_update(visible)
        self.action_list.blockSignals(True)
        try:
            for index in range(self.action_list.count()):
                item = self.action_list.item(index)
                if not item.isHidden():
                    item.setSelected(selected)
        finally:
            self.action_list.blockSignals(False)
        self._refresh_preview()

    def _on_selection_changed(self) -> None:
        if not self._filtering:
            visible = self.visible_action_names()
            self._selected_names.difference_update(visible)
            self._selected_names.update(
                str(item.data(Qt.ItemDataRole.UserRole)) for item in self.action_list.selectedItems()
            )
        self._refresh_preview()

    def _refresh_preview(self) -> None:
        package = self.current_package()
        selected_names = self.selected_action_names()
        self.selection_label.setText(f"已选 {len(selected_names)} 项")
        self.export_button.setEnabled(bool(selected_names) and package is not None)
        if package is None or not selected_names:
            self.preview.clear()
            return
        visible_selected = [
            str(item.data(Qt.ItemDataRole.UserRole)) for item in self.action_list.selectedItems()
        ]
        name = visible_selected[0] if visible_selected else next(iter(selected_names))
        definition = package.animations[name]
        self.preview.set_frames(
            definition.frames,
            frame_durations_ms=definition.frame_durations_ms,
            fps=definition.fps,
        )

    def _choose_output(self) -> None:
        selected, _ = QFileDialog.getSaveFileName(self, "导出动作分享包", "动作分享包.zip", "ZIP 文件 (*.zip)")
        if not selected:
            return
        try:
            self.export_selected(Path(selected))
        except ActionPackError as error:
            self.status_label.setText(f"导出失败：{error}")


__all__ = ["ActionExportPage"]
