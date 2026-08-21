"""动作来源导入页面：动作包、完整宠物和旧版下班包共用一套流程。"""

from __future__ import annotations

from collections.abc import Callable, Sequence
import json
from pathlib import Path

from PySide6.QtCore import QEventLoop, QSignalBlocker, Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from petnest.core.action_installer import ActionInstallError, ConflictDecision, install_actions
from petnest.core.action_pack import ActionPack, ActionPackError, SourcePetInfo, load_action_pack
from petnest.core.action_transfer import (
    ActionTransferError,
    SourceKind,
    detect_source_kind,
    extract_pet_actions,
    load_legacy_work_finish_pack,
)
from petnest.core.exchange_source import ExchangeSource
from petnest.core.image_action_builder import ImageActionSourceError
from petnest.models.pet_package import PetPackage
from petnest.ui.exchange_page import ExchangePage
from petnest.ui.image_action_import_content import ImageActionImportContent
from petnest.ui.theme import dialog_stylesheet


class ActionImportPage(ExchangePage):
    """选择来源和动作，按目标宠物逐项处理冲突后事务性安装。"""

    actions_installed = Signal(str, object)

    _DEFAULT_STATUS = "导入完整宠物时可只选择其中部分动作。"

    def __init__(
        self,
        packages: Sequence[PetPackage],
        pets_root: Path,
        *,
        current_pet_id: str | None = None,
        is_pet_locked: Callable[[str], bool] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("actionImportPage")
        self.setStyleSheet(dialog_stylesheet())
        self._packages = tuple(packages)
        self._pets_root = Path(pets_root)
        self._is_pet_locked = is_pet_locked or (lambda _identifier: False)
        self._pack: ActionPack | None = None
        self._status_text = self._DEFAULT_STATUS
        self._installing = False
        self._mode = "resource"
        self._active_install_mode: str | None = None

        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        title = QLabel("导入动作", self)
        title.setObjectName("pageTitle")
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(QLabel("目标宠物", self))
        self.target_combo = QComboBox(self)
        for package in self._packages:
            self.target_combo.addItem(package.name, package.identifier)
        target_index = self.target_combo.findData(current_pet_id)
        if target_index < 0 and self.target_combo.count():
            target_index = 0
        self.target_combo.setCurrentIndex(target_index)
        header.addWidget(self.target_combo)
        layout.addLayout(header)

        mode_row = QHBoxLayout()
        self.resource_mode_button = QPushButton("从资源包提取动作", self)
        self.resource_mode_button.setCheckable(True)
        self.resource_mode_button.setChecked(True)
        self.image_mode_button = QPushButton("用图片制作动作", self)
        self.image_mode_button.setCheckable(True)
        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        self.mode_group.addButton(self.resource_mode_button)
        self.mode_group.addButton(self.image_mode_button)
        self.resource_mode_button.clicked.connect(self.select_resource_mode)
        self.image_mode_button.clicked.connect(self.select_image_mode)
        mode_row.addWidget(self.resource_mode_button, 1)
        mode_row.addWidget(self.image_mode_button, 1)
        layout.addLayout(mode_row)

        self.mode_stack = QStackedWidget(self)
        self.resource_container = QWidget(self.mode_stack)
        resource_layout = QVBoxLayout(self.resource_container)
        resource_layout.setContentsMargins(0, 0, 0, 0)
        resource_layout.setSpacing(10)

        source_row = QHBoxLayout()
        self.source_input = QLineEdit(self)
        self.source_input.setPlaceholderText("选择动作分享包、完整宠物包或旧版下班动画包")
        source_row.addWidget(self.source_input, 1)
        browse = QPushButton("选择来源…", self)
        browse.clicked.connect(self._choose_source)
        source_row.addWidget(browse)
        inspect = QPushButton("读取来源", self)
        inspect.clicked.connect(lambda: self.load_source(Path(self.source_input.text().strip())))
        source_row.addWidget(inspect)
        resource_layout.addLayout(source_row)
        info_row = QHBoxLayout()
        self.source_kind_label = QLabel("尚未读取来源", self)
        self.source_kind_label.setObjectName("accentValue")
        info_row.addWidget(self.source_kind_label)
        self.source_summary_label = QLabel("", self)
        self.source_summary_label.setObjectName("mutedLabel")
        info_row.addWidget(self.source_summary_label)
        info_row.addStretch(1)
        resource_layout.addLayout(info_row)

        body = QHBoxLayout()
        self.action_list = QListWidget(self)
        self.action_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        self.action_list.itemSelectionChanged.connect(self._refresh_conflicts)
        body.addWidget(self.action_list, 2)
        self.conflict_table = QTableWidget(0, 3, self)
        self.conflict_table.setHorizontalHeaderLabels(("动作", "处理方式", "重命名为"))
        self.conflict_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.conflict_table.setMinimumWidth(390)
        body.addWidget(self.conflict_table, 3)
        resource_layout.addLayout(body, 1)

        self.import_bindings = QCheckBox("同时导入相关绑定", self)
        info_row.insertWidget(0, self.import_bindings)

        self.image_content = ImageActionImportContent(
            self._packages,
            current_pet_id=current_pet_id,
            embed_target_selector=False,
            parent=self.mode_stack,
        )
        self.image_content.draft_changed.connect(self._sync_footer)
        self.mode_stack.addWidget(self.resource_container)
        self.mode_stack.addWidget(self.image_content)
        layout.addWidget(self.mode_stack, 1)
        self.target_combo.currentIndexChanged.connect(self._target_changed)
        if isinstance(self.target_combo.currentData(), str):
            self.image_content.select_target(str(self.target_combo.currentData()))

        # These controls remain as hidden compatibility attributes for callers
        # that used the old dialog page directly.  The visible command area is
        # owned by PetActionExchangeDialog.
        self.status_label = QLabel(self)
        self.status_label.setObjectName("mutedLabel")
        self.status_label.hide()
        self.install_button = QPushButton("安装选中动作", self)
        self.install_button.setObjectName("legacyInstallButton")
        self.install_button.clicked.connect(self.install_selected)
        self.install_button.hide()
        self._sync_footer()

    def current_mode(self) -> str:
        return self._mode

    def select_resource_mode(self, *_args: object) -> None:
        self._select_mode("resource")

    def select_image_mode(self, *_args: object) -> None:
        self._select_mode("image")

    def _select_mode(self, mode: str) -> None:
        if mode not in {"resource", "image"} or self._installing:
            return
        self._mode = mode
        resource = mode == "resource"
        self.resource_mode_button.setChecked(resource)
        self.image_mode_button.setChecked(not resource)
        self.mode_stack.setCurrentWidget(self.resource_container if resource else self.image_content)
        self._sync_footer()

    def available_action_names(self) -> set[str]:
        return {
            str(self.action_list.item(index).data(Qt.ItemDataRole.UserRole))
            for index in range(self.action_list.count())
        }

    def selected_action_names(self) -> set[str]:
        return {str(item.data(Qt.ItemDataRole.UserRole)) for item in self.action_list.selectedItems()}

    def set_action_selection(self, names: Sequence[str]) -> None:
        selected = set(names)
        self.action_list.blockSignals(True)
        try:
            for index in range(self.action_list.count()):
                item = self.action_list.item(index)
                item.setSelected(str(item.data(Qt.ItemDataRole.UserRole)) in selected)
        finally:
            self.action_list.blockSignals(False)
        self._refresh_conflicts()

    def load_source(self, source: Path) -> None:
        self._close_pack()
        materialized: ExchangeSource | None = None
        adopted = False
        try:
            materialized = ExchangeSource.open(Path(source))
            kind = detect_source_kind(materialized.root)
            if kind is SourceKind.ACTION_PACK:
                pack = load_action_pack(materialized.root)
                pack._source = materialized
            elif kind is SourceKind.PET_PACKAGE:
                actions = extract_pet_actions(materialized.root)
                config = json.loads((materialized.root / "pet.json").read_text(encoding="utf-8"))
                source_id = str(config.get("id", "imported"))
                pack = ActionPack(
                    name=str(config.get("name", source_id)),
                    source_pet=SourcePetInfo(source_id, str(config.get("name", source_id)), str(config.get("version", "0.0.0"))),
                    actions=actions,
                    bindings={str(key): str(value) for key, value in (config.get("bindings") or {}).items()} if isinstance(config.get("bindings"), dict) else {},
                    fallbacks={str(key): [str(item) for item in value] for key, value in (config.get("fallbacks") or {}).items() if isinstance(value, list)} if isinstance(config.get("fallbacks"), dict) else {},
                    root=materialized.root,
                    _source=materialized,
                )
            elif kind is SourceKind.LEGACY_WORK_FINISH:
                pack = load_legacy_work_finish_pack(materialized.root)
                pack._source = materialized
            else:
                raise ActionPackError("精灵图请从“导入宠物”页面导入")
            self._pack = pack
            adopted = True
            self.source_input.setText(str(source))
            self.source_kind_label.setText(_source_kind_label(kind))
            self.source_summary_label.setText(f"{pack.name} · {len(pack.actions)} 个动作")
            self.action_list.clear()
            for name, action in pack.actions.items():
                item = QListWidgetItem(f"{name} · {'全屏动作' if action.scope == 'fullscreen' else '普通动作'} · {len(action.asset_paths)} 帧", self.action_list)
                item.setData(Qt.ItemDataRole.UserRole, name)
                item.setSelected(True)
            self._status_text = self._DEFAULT_STATUS
            self._refresh_conflicts()
        except Exception as error:
            if not adopted and materialized is not None:
                materialized.__exit__(None, None, None)
            self._close_pack()
            self.source_kind_label.setText("读取失败")
            self.source_summary_label.setText(str(error))
            self._sync_footer(f"无法读取来源：{error}")

    def install_selected(self) -> None:
        if self._installing:
            return
        package = self._target_package()
        if self._pack is None or package is None:
            self._sync_footer("请先读取来源并选择目标宠物。")
            return
        if self._is_pet_locked(package.identifier):
            self._sync_footer("当前宠物正在显示下班提醒，请先结束提醒后再导入动作。")
            return
        selected = self.selected_action_names()
        if not selected:
            self._sync_footer("至少选择一个动作。")
            return
        self._installing = True
        self._sync_footer(f"正在安装 {len(selected)} 个动作…")
        QApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
        try:
            selected_pack = self._selected_pack(selected)
            result = install_actions(
                package.root,
                selected_pack,
                decisions=self._conflict_decisions(selected),
                import_bindings=self.import_bindings.isChecked(),
            )
        except (ActionInstallError, ActionPackError) as error:
            self._installing = False
            self._active_install_mode = None
            self._sync_footer(f"安装失败：{error}")
            QMessageBox.warning(self, "动作安装失败", str(error))
            return
        self._active_install_mode = "resource"
        self._sync_footer("动作已写入，正在重新加载目标宠物…")
        self.actions_installed.emit(package.identifier, result)

    def install_image_action(self) -> None:
        if self._installing:
            return
        package = self._target_package()
        if package is None or not self.image_content.can_install():
            self.image_content.finish_failure("请先选择可触发动作、添加图片并确认画布处理。")
            self._sync_footer()
            return
        if self._is_pet_locked(package.identifier):
            self.image_content.finish_failure("当前宠物正在显示下班提醒，请先结束提醒后再安装动作。")
            self._sync_footer()
            return
        self._installing = True
        self._sync_footer("正在处理图片…")
        QApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
        try:
            with self.image_content.build_pack() as pack:
                action_name = next(iter(pack.actions))
                self._sync_footer("正在安装动作…")
                QApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
                result = install_actions(
                    package.root,
                    pack,
                    decisions={action_name: ConflictDecision.replace()},
                    import_bindings=True,
                )
        except (ActionInstallError, ActionPackError, ImageActionSourceError) as error:
            self._installing = False
            self._active_install_mode = None
            message = f"安装失败：{error}"
            self.image_content.finish_failure(message)
            self._sync_footer()
            QMessageBox.warning(self, "动作安装失败", str(error))
            return
        self._active_install_mode = "image"
        self._sync_footer("动作已写入，正在重新加载目标宠物…")
        self.actions_installed.emit(package.identifier, result)

    def complete_install(self, message: str) -> None:
        """运行时确认动作可用后，清空本次来源并保留最终结果。"""
        completed_mode = self._active_install_mode or self._mode
        if completed_mode == "image":
            self.image_content.clear_after_success(message)
        else:
            self._close_pack()
            self.source_input.clear()
            self.source_kind_label.setText("尚未读取来源")
            self.source_summary_label.clear()
            self.action_list.clear()
            self.conflict_table.setRowCount(0)
            self.import_bindings.setChecked(False)
            self._status_text = message
        self._installing = False
        self._active_install_mode = None
        self._sync_footer()

    def complete_install_failure(self, message: str) -> None:
        """运行时应用或回滚失败后恢复操作按钮，并保留来源以便重试。"""

        failed_mode = self._active_install_mode or self._mode
        if failed_mode == "image":
            self.image_content.finish_failure(message)
        else:
            self._status_text = message
        self._installing = False
        self._active_install_mode = None
        self._sync_footer()

    def _selected_pack(self, selected: set[str]) -> ActionPack:
        if self._pack is None:
            raise ActionPackError("尚未读取动作来源")
        actions = {name: self._pack.actions[name] for name in selected if name in self._pack.actions}
        if not actions:
            raise ActionPackError("至少选择一个有效动作")
        return ActionPack(
            name=self._pack.name,
            source_pet=self._pack.source_pet,
            actions=actions,
            bindings={event: action for event, action in self._pack.bindings.items() if action in actions},
            fallbacks={name: list(candidates) for name, candidates in self._pack.fallbacks.items() if name in actions},
            root=self._pack.root,
        )

    def _target_package(self) -> PetPackage | None:
        index = self.target_combo.currentIndex()
        return self._packages[index] if 0 <= index < len(self._packages) else None

    def _refresh_conflicts(self) -> None:
        self.conflict_table.setRowCount(0)
        package = self._target_package()
        selected = self.selected_action_names()
        if package is None or self._pack is None:
            self._sync_footer()
            return
        for name in sorted(selected):
            if not any(_action_name_key(name) == _action_name_key(existing) for existing in package.animations):
                continue
            row = self.conflict_table.rowCount()
            self.conflict_table.insertRow(row)
            self.conflict_table.setItem(row, 0, QTableWidgetItem(name))
            decision = QComboBox(self.conflict_table)
            decision.addItem("替换", "replace")
            decision.addItem("重命名", "rename")
            decision.addItem("跳过", "skip")
            self.conflict_table.setCellWidget(row, 1, decision)
            rename = QLineEdit(name + "_shared", self.conflict_table)
            self.conflict_table.setCellWidget(row, 2, rename)
            decision.currentIndexChanged.connect(
                lambda _index, editor=rename, mode=decision: editor.setEnabled(mode.currentData() == "rename")
            )
            rename.setEnabled(False)
        self._sync_footer()

    def trigger_primary(self) -> None:
        if self._mode == "image":
            self.install_image_action()
        else:
            self.install_selected()

    def refresh_packages(self, packages: Sequence[PetPackage], current_pet_id: str) -> None:
        """Refresh target pets while keeping the currently loaded source pack."""

        previous_id = self.target_combo.currentData()
        self._packages = tuple(packages)
        desired_id = current_pet_id or previous_id
        with QSignalBlocker(self.target_combo):
            self.target_combo.clear()
            for package in self._packages:
                self.target_combo.addItem(package.name, package.identifier)
            index = self.target_combo.findData(desired_id)
            if index < 0 and self.target_combo.count():
                index = 0
            self.target_combo.setCurrentIndex(index)
        self.image_content.refresh_packages(self._packages, str(self.target_combo.currentData() or desired_id))
        self._refresh_conflicts()

    def close_pack(self) -> None:
        """Release a materialized source package before the shell closes."""

        self._close_pack()

    def deactivate(self) -> None:
        return

    def _sync_footer(self, message: str | None = None) -> None:
        if self._mode == "image":
            if message is not None:
                self.image_content.status_label.setText(message)
            status = self.image_content.status_label.text()
            enabled = not self._installing and self.image_content.can_install()
            primary_text = "处理中…" if self._installing else self.image_content.primary_text()
        else:
            if message is not None:
                self._status_text = message
            status = self._status_text
            enabled = (
                not self._installing
                and self._pack is not None
                and bool(self.selected_action_names())
                and self._target_package() is not None
            )
            primary_text = "处理中…" if self._installing else "安装选中动作"
        self.resource_mode_button.setEnabled(not self._installing)
        self.image_mode_button.setEnabled(not self._installing)
        self.status_label.setText(status)
        self.install_button.setEnabled(enabled)
        self.set_footer(
            status=status,
            primary_text=primary_text,
            primary_enabled=enabled,
        )

    def _target_changed(self, *_args: object) -> None:
        identifier = self.target_combo.currentData()
        if isinstance(identifier, str):
            self.image_content.select_target(identifier)
        self._refresh_conflicts()

    def _conflict_decisions(self, selected: set[str]) -> dict[str, ConflictDecision]:
        decisions: dict[str, ConflictDecision] = {}
        for row in range(self.conflict_table.rowCount()):
            name = self.conflict_table.item(row, 0).text()
            mode = self.conflict_table.cellWidget(row, 1)
            rename = self.conflict_table.cellWidget(row, 2)
            if not isinstance(mode, QComboBox) or not isinstance(rename, QLineEdit):
                continue
            if mode.currentData() == "rename":
                decisions[name] = ConflictDecision.rename(rename.text().strip())
            elif mode.currentData() == "skip":
                decisions[name] = ConflictDecision.skip()
            else:
                decisions[name] = ConflictDecision.replace()
        return {name: decision for name, decision in decisions.items() if name in selected}

    def _choose_source(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(self, "选择动作来源", str(Path.home()), "ZIP 或 JSON (*.zip *.json);;所有文件 (*.*)")
        if selected:
            self.load_source(Path(selected))
            return
        folder = QFileDialog.getExistingDirectory(self, "选择动作或宠物文件夹", str(Path.home()))
        if folder:
            self.load_source(Path(folder))

    def _close_pack(self) -> None:
        if self._pack is not None:
            self._pack.close()
            self._pack = None

    def closeEvent(self, event: object) -> None:  # noqa: N802 - Qt override signature.
        self._close_pack()
        super().closeEvent(event)  # type: ignore[arg-type]


def _source_kind_label(kind: SourceKind) -> str:
    return {
        SourceKind.ACTION_PACK: "动作分享包",
        SourceKind.PET_PACKAGE: "完整宠物",
        SourceKind.LEGACY_WORK_FINISH: "旧版下班动画",
        SourceKind.SPRITESHEET: "精灵图",
    }[kind]


def _action_name_key(name: str) -> str:
    return name.rstrip(" .").casefold()


__all__ = ["ActionImportPage"]
