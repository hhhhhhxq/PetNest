"""动作来源导入页面：动作包、完整宠物和旧版下班包共用一套流程。"""

from __future__ import annotations

from collections.abc import Callable, Sequence
import json
from pathlib import Path

from PySide6.QtCore import QEventLoop, QSignalBlocker, Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from petnest.core.action_installer import ActionInstallError, ConflictDecision, install_actions
from petnest.core.action_pack import ActionPack, ActionPackError, SourcePetInfo, load_action_pack
from petnest.core.action_slots import action_slots
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


class ResourceSourceDropZone(QFrame):
    source_dropped = Signal(Path)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setObjectName("resourceSourceDropZone")

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        urls = event.mimeData().urls()
        if len(urls) == 1 and urls[0].isLocalFile():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        urls = event.mimeData().urls()
        if len(urls) == 1 and urls[0].isLocalFile():
            self.source_dropped.emit(Path(urls[0].toLocalFile()))
            event.acceptProposedAction()
        else:
            event.ignore()


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
        embed_target_selector: bool = True,
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
        self.target_label = QLabel("目标宠物", self)
        header.addWidget(self.target_label)
        self.target_combo = QComboBox(self)
        for package in self._packages:
            self.target_combo.addItem(package.name, package.identifier)
        target_index = self.target_combo.findData(current_pet_id)
        if target_index < 0 and self.target_combo.count():
            target_index = 0
        self.target_combo.setCurrentIndex(target_index)
        header.addWidget(self.target_combo)
        if not embed_target_selector:
            self.target_label.hide()
            self.target_combo.hide()
        layout.addLayout(header)

        mode_switch = QFrame(self)
        mode_switch.setObjectName("modeSwitch")
        mode_row = QHBoxLayout(mode_switch)
        mode_row.setContentsMargins(6, 5, 6, 5)
        self.resource_mode_button = QRadioButton("从资源包提取动作", mode_switch)
        self.resource_mode_button.setChecked(True)
        self.image_mode_button = QRadioButton("用图片制作动作", mode_switch)
        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        self.mode_group.addButton(self.resource_mode_button)
        self.mode_group.addButton(self.image_mode_button)
        self.resource_mode_button.clicked.connect(self.select_resource_mode)
        self.image_mode_button.clicked.connect(self.select_image_mode)
        mode_row.addWidget(self.resource_mode_button, 1)
        mode_row.addWidget(self.image_mode_button, 1)
        layout.addWidget(mode_switch)

        self.mode_stack = QStackedWidget(self)
        self.resource_container = QWidget(self.mode_stack)
        resource_layout = QVBoxLayout(self.resource_container)
        resource_layout.setContentsMargins(0, 0, 0, 0)
        resource_layout.setSpacing(10)

        self.resource_body_layout = QVBoxLayout()
        self.resource_body_layout.setSpacing(12)

        self.resource_source_card = QFrame(self.resource_container)
        self.resource_source_card.setObjectName("settingsCard")
        self.resource_source_card.setMaximumHeight(270)
        source_card_layout = QVBoxLayout(self.resource_source_card)
        source_card_layout.setContentsMargins(12, 10, 12, 10)
        source_card_layout.setSpacing(8)
        source_title = QLabel("动作来源", self.resource_source_card)
        source_title.setObjectName("sectionTitle")
        source_card_layout.addWidget(source_title)

        self.source_input = QLineEdit(self.resource_source_card)
        self.source_input.setPlaceholderText("选择动作分享包、完整宠物包或旧版下班动画包")
        self.source_input.hide()

        self.resource_drop_zone = ResourceSourceDropZone(self.resource_source_card)
        self.resource_drop_zone.setMinimumHeight(96)
        self.resource_drop_zone.setMaximumHeight(112)
        drop_layout = QVBoxLayout(self.resource_drop_zone)
        drop_layout.setContentsMargins(10, 8, 10, 8)
        drop_layout.setSpacing(3)
        drop_title = QLabel("拖入动作资源包", self.resource_drop_zone)
        drop_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        drop_layout.addWidget(drop_title)
        drop_hint = QLabel("支持动作包 ZIP、完整宠物包、旧版下班动画包", self.resource_drop_zone)
        drop_hint.setObjectName("mutedLabel")
        drop_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        drop_layout.addWidget(drop_hint)
        browse = QPushButton("选择来源", self.resource_drop_zone)
        browse.clicked.connect(self._choose_source)
        drop_layout.addWidget(browse, alignment=Qt.AlignmentFlag.AlignHCenter)
        self.resource_drop_zone.source_dropped.connect(self.load_source)
        source_card_layout.addWidget(self.resource_drop_zone)

        self.resource_summary_card = QFrame(self.resource_source_card)
        self.resource_summary_card.setObjectName("resourceSummaryCard")
        summary_layout = QGridLayout(self.resource_summary_card)
        summary_layout.setContentsMargins(9, 7, 9, 7)
        summary_layout.setHorizontalSpacing(12)
        summary_layout.setVerticalSpacing(4)
        self.source_name_label = QLabel("尚未读取来源", self.resource_summary_card)
        self.source_name_label.setObjectName("resourceSummaryName")
        summary_layout.addWidget(self.source_name_label, 0, 0, 1, 2)
        summary_layout.addWidget(QLabel("来源类型", self.resource_summary_card), 1, 0)
        self.source_kind_label = QLabel("尚未读取来源", self.resource_source_card)
        self.source_kind_label.setObjectName("resourceSummaryValue")
        summary_layout.addWidget(self.source_kind_label, 1, 1, alignment=Qt.AlignmentFlag.AlignRight)
        summary_layout.addWidget(QLabel("可提取动作", self.resource_summary_card), 2, 0)
        self.source_action_count_label = QLabel("—", self.resource_summary_card)
        self.source_action_count_label.setObjectName("resourceSummaryValue")
        summary_layout.addWidget(self.source_action_count_label, 2, 1, alignment=Qt.AlignmentFlag.AlignRight)
        summary_layout.addWidget(QLabel("来源宠物", self.resource_summary_card), 3, 0)
        self.source_pet_label = QLabel("—", self.resource_summary_card)
        self.source_pet_label.setObjectName("resourceSummaryValue")
        summary_layout.addWidget(self.source_pet_label, 3, 1, alignment=Qt.AlignmentFlag.AlignRight)
        source_card_layout.addWidget(self.resource_summary_card)

        self.source_summary_label = QLabel("", self.resource_source_card)
        self.source_summary_label.setObjectName("mutedLabel")
        self.source_summary_label.hide()
        self.import_bindings = QCheckBox("同时导入相关绑定", self.resource_source_card)
        source_card_layout.addWidget(self.import_bindings)
        self.resource_body_layout.addWidget(self.resource_source_card)

        self.resource_actions_card = QFrame(self.resource_container)
        self.resource_actions_card.setObjectName("settingsCard")
        actions_card_layout = QVBoxLayout(self.resource_actions_card)
        actions_card_layout.setContentsMargins(12, 10, 12, 10)
        actions_card_layout.setSpacing(7)
        actions_title_row = QHBoxLayout()
        actions_title = QLabel("选择要导入的动作", self.resource_actions_card)
        actions_title.setObjectName("sectionTitle")
        actions_title_row.addWidget(actions_title)
        actions_title_row.addStretch(1)
        self.resource_selection_label = QLabel("尚未读取", self.resource_actions_card)
        self.resource_selection_label.setObjectName("mutedLabel")
        actions_title_row.addWidget(self.resource_selection_label)
        actions_card_layout.addLayout(actions_title_row)
        actions_hint = QLabel("取消不需要的动作；已有同名动作时可选择替换、另存或跳过。", self.resource_actions_card)
        actions_hint.setObjectName("mutedLabel")
        actions_hint.setWordWrap(True)
        actions_card_layout.addWidget(actions_hint)
        self.resource_action_table = QTableWidget(0, 5, self.resource_actions_card)
        self.resource_action_table.setHorizontalHeaderLabels(("选择", "动作", "帧数", "适用范围", "安装方式"))
        self.resource_action_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.resource_action_table.setAlternatingRowColors(True)
        self.resource_action_table.setShowGrid(False)
        self.resource_action_table.verticalHeader().hide()
        self.resource_action_table.verticalHeader().setDefaultSectionSize(48)
        self.resource_action_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.resource_action_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.resource_action_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.resource_action_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.resource_action_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.resource_action_table.itemChanged.connect(self._resource_table_item_changed)
        actions_card_layout.addWidget(self.resource_action_table, 1)
        self.resource_body_layout.addWidget(self.resource_actions_card, 1)
        resource_layout.addLayout(self.resource_body_layout, 1)

        # Hidden compatibility controls retain the older programmatic API.
        self.action_list = QListWidget(self)
        self.action_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        self.action_list.itemSelectionChanged.connect(self._refresh_conflicts)
        self.action_list.hide()
        self.conflict_table = QTableWidget(0, 3, self)
        self.conflict_table.setHorizontalHeaderLabels(("动作", "处理方式", "重命名为"))
        self.conflict_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.conflict_table.hide()

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
        if resource:
            self.image_content.pause_previews()
        else:
            self.image_content.resume_active_preview()
        self._sync_footer()

    def available_action_names(self) -> set[str]:
        return {
            str(self.action_list.item(index).data(Qt.ItemDataRole.UserRole))
            for index in range(self.action_list.count())
        }

    def selected_action_names(self) -> set[str]:
        return {
            str(self.resource_action_table.item(row, 0).data(Qt.ItemDataRole.UserRole))
            for row in range(self.resource_action_table.rowCount())
            if self.resource_action_table.item(row, 0).checkState() == Qt.CheckState.Checked
        }

    def set_action_selection(self, names: Sequence[str]) -> None:
        selected = set(names)
        self.resource_action_table.blockSignals(True)
        self.action_list.blockSignals(True)
        try:
            for index in range(self.action_list.count()):
                item = self.action_list.item(index)
                item.setSelected(str(item.data(Qt.ItemDataRole.UserRole)) in selected)
            for row in range(self.resource_action_table.rowCount()):
                item = self.resource_action_table.item(row, 0)
                name = str(item.data(Qt.ItemDataRole.UserRole))
                item.setCheckState(
                    Qt.CheckState.Checked if name in selected else Qt.CheckState.Unchecked
                )
        finally:
            self.action_list.blockSignals(False)
            self.resource_action_table.blockSignals(False)
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
            self.source_name_label.setText(pack.name)
            self.source_action_count_label.setText(f"{len(pack.actions)} 个")
            if pack.source_pet is None:
                self.source_pet_label.setText("—")
            else:
                self.source_pet_label.setText(
                    f"{pack.source_pet.name} {pack.source_pet.version}"
                )
            self.action_list.clear()
            for name, action in pack.actions.items():
                item = QListWidgetItem(f"{name} · {'全屏动作' if action.scope == 'fullscreen' else '普通动作'} · {len(action.asset_paths)} 帧", self.action_list)
                item.setData(Qt.ItemDataRole.UserRole, name)
                item.setSelected(True)
            self._status_text = self._DEFAULT_STATUS
            self._populate_resource_action_table()
            self._refresh_conflicts()
        except Exception as error:
            if not adopted and materialized is not None:
                materialized.__exit__(None, None, None)
            self._close_pack()
            self.source_kind_label.setText("读取失败")
            self.source_summary_label.setText(str(error))
            self.source_name_label.setText("读取失败")
            self.source_action_count_label.setText("—")
            self.source_pet_label.setText("—")
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
            self.source_name_label.setText("尚未读取来源")
            self.source_action_count_label.setText("—")
            self.source_pet_label.setText("—")
            self.action_list.clear()
            self.conflict_table.setRowCount(0)
            self.resource_action_table.setRowCount(0)
            self.resource_selection_label.setText("尚未读取")
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
        self._refresh_resource_install_modes()
        self._sync_footer()

    def _populate_resource_action_table(self) -> None:
        self.resource_action_table.blockSignals(True)
        try:
            self.resource_action_table.setRowCount(0)
            if self._pack is None:
                self.resource_selection_label.setText("尚未读取")
                return
            for name, action in self._pack.actions.items():
                row = self.resource_action_table.rowCount()
                self.resource_action_table.insertRow(row)
                selected = QTableWidgetItem()
                selected.setFlags(selected.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                selected.setCheckState(Qt.CheckState.Checked)
                selected.setData(Qt.ItemDataRole.UserRole, name)
                self.resource_action_table.setItem(row, 0, selected)
                name_item = QTableWidgetItem()
                name_item.setData(Qt.ItemDataRole.UserRole, name)
                self.resource_action_table.setItem(row, 1, name_item)
                name_cell = QWidget(self.resource_action_table)
                name_layout = QVBoxLayout(name_cell)
                name_layout.setContentsMargins(5, 2, 5, 2)
                name_layout.setSpacing(0)
                name_layout.addWidget(QLabel(name, name_cell))
                description = QLabel(_action_description(name), name_cell)
                description.setObjectName("mutedLabel")
                name_layout.addWidget(description)
                self.resource_action_table.setCellWidget(row, 1, name_cell)
                self.resource_action_table.setItem(row, 2, QTableWidgetItem(str(len(action.asset_paths))))
                scope = "全屏" if action.scope == "fullscreen" else "宠物窗口"
                self.resource_action_table.setItem(row, 3, QTableWidgetItem(scope))
        finally:
            self.resource_action_table.blockSignals(False)
        self._refresh_resource_install_modes()
        self._update_resource_selection_label()

    def _resource_table_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() != 0:
            return
        selected = self.selected_action_names()
        self.action_list.blockSignals(True)
        try:
            for index in range(self.action_list.count()):
                action_item = self.action_list.item(index)
                action_item.setSelected(
                    str(action_item.data(Qt.ItemDataRole.UserRole)) in selected
                )
        finally:
            self.action_list.blockSignals(False)
        self._update_resource_selection_label()
        self._refresh_conflicts()

    def _update_resource_selection_label(self) -> None:
        if self._pack is None:
            self.resource_selection_label.setText("尚未读取")
            return
        self.resource_selection_label.setText(
            f"已选 {len(self.selected_action_names())} / {len(self._pack.actions)}"
        )

    def _refresh_resource_install_modes(self) -> None:
        package = self._target_package()
        if self._pack is None:
            return
        existing_names = tuple(package.animations) if package is not None else ()
        for row in range(self.resource_action_table.rowCount()):
            name = str(self.resource_action_table.item(row, 0).data(Qt.ItemDataRole.UserRole))
            mode = self.resource_action_table.cellWidget(row, 4)
            if not isinstance(mode, QComboBox):
                mode = QComboBox(self.resource_action_table)
                self.resource_action_table.setCellWidget(row, 4, mode)
            current_data = mode.currentData()
            conflict = any(
                _action_name_key(name) == _action_name_key(existing)
                for existing in existing_names
            )
            if conflict:
                options = (
                    ("替换现有动作", "replace"),
                    ("另存为新动作", "rename"),
                    ("跳过", "skip"),
                )
            else:
                options = (("新增动作", "replace"),)
            if tuple(mode.itemData(index) for index in range(mode.count())) != tuple(
                data for _label, data in options
            ):
                with QSignalBlocker(mode):
                    mode.clear()
                    for label, data in options:
                        mode.addItem(label, data)
            index = mode.findData(current_data)
            if index >= 0:
                mode.setCurrentIndex(index)

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

        self.image_content.pause_previews()
        self._close_pack()

    def activate(self) -> None:
        if self._mode == "image":
            self.image_content.resume_active_preview()

    def deactivate(self) -> None:
        self.image_content.pause_previews()

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
        for row in range(self.resource_action_table.rowCount()):
            name = str(
                self.resource_action_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
            )
            if name not in selected:
                continue
            mode = self.resource_action_table.cellWidget(row, 4)
            if not isinstance(mode, QComboBox):
                continue
            if mode.currentData() == "rename":
                decisions[name] = ConflictDecision.rename(self._suggest_renamed_action(name))
            elif mode.currentData() == "skip":
                decisions[name] = ConflictDecision.skip()
            else:
                decisions[name] = ConflictDecision.replace()
        return decisions

    def _suggest_renamed_action(self, name: str) -> str:
        package = self._target_package()
        unavailable = {
            _action_name_key(existing)
            for existing in (package.animations if package is not None else ())
        }
        base = f"{name}_imported"
        candidate = base
        suffix = 2
        while _action_name_key(candidate) in unavailable:
            candidate = f"{base}_{suffix}"
            suffix += 1
        return candidate

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


def _action_description(name: str) -> str:
    slot = next(
        (candidate for candidate in action_slots() if candidate.canonical_action == name),
        None,
    )
    return slot.label if slot is not None else "未绑定到 PetNest 触发时机"


__all__ = ["ActionImportPage"]
