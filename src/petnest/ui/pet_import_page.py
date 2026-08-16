"""统一宠物导入页面：完整宠物包与精灵图模式。"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from enum import StrEnum
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
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from petnest.core.action_transfer import SourceKind, detect_source_kind
from petnest.core.exchange_source import ExchangeSource
from petnest.core.package_validator import PackageValidator
from petnest.core.pet_package_importer import PetImportOptions, PetPackageImportError, import_pet_package
from petnest.models.pet_package import PetPackage
from petnest.ui.spritesheet_import_dialog import SpriteSheetImportDialog
from petnest.ui.theme import dialog_stylesheet


class PetImportMode(StrEnum):
    PACKAGE = "package"
    SPRITESHEET = "spritesheet"


class PetImportPage(QWidget):
    """新增/更新宠物；完整文件夹、ZIP 和精灵图统一从这里进入。"""

    pet_installed = Signal(str, object)

    def __init__(
        self,
        packages: Sequence[PetPackage],
        pets_root: Path,
        *,
        is_pet_locked: Callable[[str], bool] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("petImportPage")
        self.setStyleSheet(dialog_stylesheet())
        self._packages = tuple(packages)
        self._pets_root = Path(pets_root)
        self._is_pet_locked = is_pet_locked or (lambda _identifier: False)
        self._source_path: Path | None = None
        self._source_identifier: str | None = None

        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        title = QLabel("导入宠物", self)
        title.setObjectName("pageTitle")
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(QLabel("导入方式", self))
        self.mode_combo = QComboBox(self)
        self.mode_combo.addItem("完整宠物文件夹 / ZIP", PetImportMode.PACKAGE)
        self.mode_combo.addItem("透明精灵图", PetImportMode.SPRITESHEET)
        self.mode_combo.currentIndexChanged.connect(lambda: self.select_mode(self.mode_combo.currentData()))
        header.addWidget(self.mode_combo)
        layout.addLayout(header)

        self.stack = QStackedWidget(self)
        self.package_page = QWidget(self.stack)
        package_layout = QVBoxLayout(self.package_page)
        package_layout.setContentsMargins(0, 0, 0, 0)
        source_row = QHBoxLayout()
        self.source_input = QLineEdit(self.package_page)
        self.source_input.setPlaceholderText("选择别人分享的宠物文件夹或 ZIP（名称无需特殊要求）")
        source_row.addWidget(self.source_input, 1)
        browse = QPushButton("选择文件夹 / ZIP…", self.package_page)
        browse.clicked.connect(self._choose_package_source)
        source_row.addWidget(browse)
        inspect = QPushButton("读取", self.package_page)
        inspect.clicked.connect(lambda: self.load_source(Path(self.source_input.text().strip())))
        source_row.addWidget(inspect)
        package_layout.addLayout(source_row)
        self.source_summary_label = QLabel("完整宠物包会自动识别，不需要手写配置文件。", self.package_page)
        self.source_summary_label.setObjectName("mutedLabel")
        self.source_summary_label.setWordWrap(True)
        package_layout.addWidget(self.source_summary_label)
        self.preserve_local_actions = QCheckBox("更新时保留本地独有动作", self.package_page)
        self.preserve_local_actions.setToolTip("只迁移新包没有的本地动作；更新同名动作仍以导入包为准")
        self.preserve_local_actions.setVisible(False)
        package_layout.addWidget(self.preserve_local_actions)
        package_layout.addStretch(1)
        self.package_import_button = QPushButton("新增 / 更新宠物", self.package_page)
        self.package_import_button.setObjectName("primaryButton")
        self.package_import_button.clicked.connect(self.import_selected)
        package_layout.addWidget(self.package_import_button, 0)
        self.stack.addWidget(self.package_page)

        self.sprite_sheet_page = QWidget(self.stack)
        sprite_layout = QVBoxLayout(self.sprite_sheet_page)
        sprite_layout.setContentsMargins(0, 0, 0, 0)
        self.sprite_sheet_dialog = SpriteSheetImportDialog(self._pets_root, self.sprite_sheet_page)
        self.sprite_sheet_dialog.setWindowFlags(Qt.WindowType.Widget)
        self.sprite_sheet_dialog.setModal(False)
        self.sprite_sheet_dialog.setMinimumSize(0, 0)
        self.sprite_sheet_dialog.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.sprite_sheet_dialog.accepted.connect(
            lambda: self._sprite_imported(self.sprite_sheet_dialog.imported_result)
            if self.sprite_sheet_dialog.imported_result is not None
            else None
        )
        self.sprite_sheet_dialog.rejected.connect(lambda: self.select_mode(PetImportMode.PACKAGE))
        sprite_layout.addWidget(self.sprite_sheet_dialog, 1)
        self.stack.addWidget(self.sprite_sheet_page)
        self.sprite_sheet_dialog.hide()
        layout.addWidget(self.stack, 1)
        self.status_label = QLabel("完整宠物包支持新增和更新；更新前会自动备份。", self)
        self.status_label.setObjectName("mutedLabel")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

    def select_mode(self, mode: PetImportMode | str) -> None:
        selected = PetImportMode(mode)
        self.mode_combo.blockSignals(True)
        try:
            self.mode_combo.setCurrentIndex(0 if selected is PetImportMode.PACKAGE else 1)
        finally:
            self.mode_combo.blockSignals(False)
        if selected is PetImportMode.PACKAGE:
            self.sprite_sheet_dialog.hide()
            self.stack.setCurrentWidget(self.package_page)
        else:
            self.stack.setCurrentWidget(self.sprite_sheet_page)
            self.sprite_sheet_dialog.show()

    def load_source(self, source: Path) -> None:
        path = Path(source).expanduser()
        if path.is_file() and path.suffix.casefold() == ".png":
            self.select_mode(PetImportMode.SPRITESHEET)
            self._source_path = path
            self._source_identifier = None
            self.sprite_sheet_dialog.source_input.setText(str(path))
            self.status_label.setText("打开原精灵图导入器后，可继续使用原有的帧选择设置。")
            return
        try:
            materialized = ExchangeSource.open(path)
            try:
                kind = detect_source_kind(materialized.root)
                if kind is not SourceKind.PET_PACKAGE:
                    raise PetPackageImportError("此来源不是完整宠物包，请到动作导入页面处理动作分享包。")
                config = json.loads((materialized.root / "pet.json").read_text(encoding="utf-8"))
                validation = PackageValidator().validate(materialized.root)
                if not validation.is_valid:
                    raise PetPackageImportError("宠物包校验失败：" + "；".join(validation.errors))
                identifier = str(config.get("id", ""))
                if self._is_pet_locked(identifier):
                    raise PetPackageImportError("当前宠物正在显示下班提醒，请先结束提醒后再更新。")
                name = str(config.get("name", identifier))
                count = len(config.get("animations", {})) if isinstance(config.get("animations"), dict) else 0
                updating = identifier in {package.identifier for package in self._packages} or (self._pets_root / identifier).is_dir()
                self._source_path = path
                self._source_identifier = identifier
                self.source_input.setText(str(path))
                self.source_summary_label.setText(
                    f"{name}（{identifier}） · {count} 个动作 · "
                    f"{'更新现有宠物' if updating else '新增宠物'} · 导入前会自动备份"
                )
                self.preserve_local_actions.setVisible(updating)
                self.status_label.setText("已读取完整宠物来源，不需要编辑 JSON。")
                self.select_mode(PetImportMode.PACKAGE)
            finally:
                materialized.__exit__(None, None, None)
        except Exception as error:
            self._source_path = None
            self._source_identifier = None
            self.source_summary_label.setText(f"读取失败：{error}")
            self.status_label.setText(f"无法读取来源：{error}")

    def import_selected(self) -> None:
        if self.stack.currentWidget() is self.sprite_sheet_page:
            self.sprite_sheet_dialog.import_selected()
            return
        if self._source_path is None:
            self.status_label.setText("请先选择并读取完整宠物文件夹或 ZIP。")
            return
        if self._source_identifier is not None and self._is_pet_locked(self._source_identifier):
            self.status_label.setText("当前宠物正在显示下班提醒，请先结束提醒后再更新。")
            return
        try:
            result = import_pet_package(
                self._source_path,
                self._pets_root,
                PetImportOptions(preserve_local_actions=self.preserve_local_actions.isChecked()),
            )
        except PetPackageImportError as error:
            self.status_label.setText(f"导入失败：{error}")
            return
        self.status_label.setText(f"导入完成：{result.pet_root}")
        self.pet_installed.emit(result.pet_id, result)

    def _choose_package_source(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(self, "选择宠物 ZIP", str(Path.home()), "ZIP 文件 (*.zip);;所有文件 (*.*)")
        if selected:
            self.load_source(Path(selected))
            return
        folder = QFileDialog.getExistingDirectory(self, "选择宠物文件夹", str(Path.home()))
        if folder:
            self.load_source(Path(folder))

    def _sprite_imported(self, result: object) -> None:
        identifier = str(getattr(result, "package_id", ""))
        self.status_label.setText(f"精灵图宠物已导入：{identifier}")
        self.pet_installed.emit(identifier, result)

__all__ = ["PetImportMode", "PetImportPage"]
