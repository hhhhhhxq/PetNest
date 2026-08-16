"""动作来源导入页面：动作包、完整宠物和旧版下班包共用一套流程。"""

from __future__ import annotations

from collections.abc import Callable, Sequence
import json
from pathlib import Path

from PySide6.QtCore import Qt, Signal
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
from petnest.models.pet_package import PetPackage
from petnest.ui.theme import dialog_stylesheet


class ActionImportPage(QWidget):
    """选择来源和动作，按目标宠物逐项处理冲突后事务性安装。"""

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
        self.setObjectName("actionImportPage")
        self.setStyleSheet(dialog_stylesheet())
        self._packages = tuple(packages)
        self._pets_root = Path(pets_root)
        self._is_pet_locked = is_pet_locked or (lambda _identifier: False)
        self._pack: ActionPack | None = None

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
        self.target_combo.currentIndexChanged.connect(self._refresh_conflicts)
        header.addWidget(self.target_combo)
        layout.addLayout(header)

        source_row = QHBoxLayout()
        self.source_input = QLineEdit(self)
        self.source_input.setPlaceholderText("选择动作 ZIP、完整宠物文件夹或旧版下班动画包")
        source_row.addWidget(self.source_input, 1)
        browse = QPushButton("选择来源…", self)
        browse.clicked.connect(self._choose_source)
        source_row.addWidget(browse)
        inspect = QPushButton("读取来源", self)
        inspect.clicked.connect(lambda: self.load_source(Path(self.source_input.text().strip())))
        source_row.addWidget(inspect)
        layout.addLayout(source_row)
        info_row = QHBoxLayout()
        self.source_kind_label = QLabel("尚未读取来源", self)
        self.source_kind_label.setObjectName("accentValue")
        info_row.addWidget(self.source_kind_label)
        self.source_summary_label = QLabel("", self)
        self.source_summary_label.setObjectName("mutedLabel")
        info_row.addWidget(self.source_summary_label)
        info_row.addStretch(1)
        layout.addLayout(info_row)

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
        layout.addLayout(body, 1)

        footer = QHBoxLayout()
        self.import_bindings = QCheckBox("同时导入相关绑定", self)
        footer.addWidget(self.import_bindings)
        self.status_label = QLabel("导入完整宠物时可只选择其中部分动作。", self)
        self.status_label.setObjectName("mutedLabel")
        self.status_label.setWordWrap(True)
        footer.addWidget(self.status_label, 1)
        self.install_button = QPushButton("安装选中动作", self)
        self.install_button.setObjectName("primaryButton")
        self.install_button.setEnabled(False)
        self.install_button.clicked.connect(self.install_selected)
        footer.addWidget(self.install_button)
        layout.addLayout(footer)

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
            self._refresh_conflicts()
        except Exception as error:
            if not adopted and materialized is not None:
                materialized.__exit__(None, None, None)
            self._close_pack()
            self.source_kind_label.setText("读取失败")
            self.source_summary_label.setText(str(error))
            self.status_label.setText(f"无法读取来源：{error}")
            self.install_button.setEnabled(False)

    def install_selected(self) -> None:
        package = self._target_package()
        if self._pack is None or package is None:
            self.status_label.setText("请先读取来源并选择目标宠物。")
            return
        if self._is_pet_locked(package.identifier):
            self.status_label.setText("当前宠物正在显示下班提醒，请先结束提醒后再导入动作。")
            return
        selected = self.selected_action_names()
        if not selected:
            self.status_label.setText("至少选择一个动作。")
            return
        try:
            selected_pack = self._selected_pack(selected)
            result = install_actions(
                package.root,
                selected_pack,
                decisions=self._conflict_decisions(selected),
                import_bindings=self.import_bindings.isChecked(),
            )
        except (ActionInstallError, ActionPackError) as error:
            self.status_label.setText(f"安装失败：{error}")
            return
        self.status_label.setText(f"已导入 {len(result.installed)} 个动作。")
        self.actions_installed.emit(package.identifier, result)

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
            self.install_button.setEnabled(False)
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
        self.install_button.setEnabled(bool(selected))

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
