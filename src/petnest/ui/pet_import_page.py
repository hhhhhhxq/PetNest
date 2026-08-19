"""自动识别 PNG、ZIP 与文件夹的三步宠物导入向导。"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
import re

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from petnest.core.action_transfer import SourceKind, detect_source_kind
from petnest.core.exchange_source import ExchangeSource
from petnest.core.package_validator import PackageValidator
from petnest.core.pet_package_importer import PetImportOptions, PetPackageImportError, import_pet_package
from petnest.core.spritesheet_importer import SpriteSheetImporter
from petnest.models.pet_package import PetPackage
from petnest.ui.exchange_page import ExchangePage
from petnest.ui.spritesheet_import_content import SpriteSheetImportContent
from petnest.ui.theme import dialog_stylesheet


_PET_ID_PATTERN = re.compile(r"[a-z][a-z0-9_-]*\Z")


class PetImportStep(StrEnum):
    SOURCE = "source"
    CONFIGURE = "configure"
    REVIEW = "review"


@dataclass(frozen=True, slots=True)
class _PackageMetadata:
    identifier: str
    name: str
    animation_count: int
    frame_count: int
    version: str
    author: str
    updating: bool


@dataclass(frozen=True, slots=True)
class _SourceCandidate:
    path: Path
    kind: SourceKind
    package_metadata: _PackageMetadata | None = None


@dataclass(frozen=True, slots=True)
class _ImportStateSnapshot:
    source_path: Path | None
    source_kind: SourceKind | None
    package_metadata: _PackageMetadata | None
    step: PetImportStep
    source_kind_text: str
    source_error_text: str
    package_summary_text: str
    review_summary_text: str
    preserve_checked: bool
    preserve_visible: bool
    configure_index: int
    sprite_source: str
    sprite_identifier: str
    sprite_name: str
    sprite_manual: bool
    sprite_inspection: object | None
    sprite_selected_columns: tuple[tuple[str, tuple[int, ...]], ...]
    sprite_action_items: tuple[tuple[str, object], ...]
    sprite_current_row: int
    sprite_status_text: str
    sprite_manual_title: str
    sprite_manual_hint: str
    sprite_selected_text: str
    sprite_last_dirty: bool


class ImportSourceDropZone(QFrame):
    """接收一个本地文件或文件夹，并把路径交给页面识别。"""

    file_dropped = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)

    @staticmethod
    def _local_path(event: QDragEnterEvent | QDropEvent) -> str | None:
        urls = event.mimeData().urls()
        if len(urls) != 1 or not urls[0].isLocalFile():
            return None
        local = urls[0].toLocalFile()
        return local if local and (Path(local).is_file() or Path(local).is_dir()) else None

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802 - Qt override
        if self._local_path(event) is None:
            event.ignore()
            return
        event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802 - Qt override
        local = self._local_path(event)
        if local is None:
            event.ignore()
            return
        self.file_dropped.emit(local)
        event.acceptProposedAction()


class PetImportPage(ExchangePage):
    """在一个页面内识别、配置并确认宠物导入。"""

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
        self._step = PetImportStep.SOURCE
        self._source_path: Path | None = None
        self._source_kind: SourceKind | None = None
        self._package_metadata: _PackageMetadata | None = None

        root = QVBoxLayout(self)
        header = QHBoxLayout()
        title = QLabel("导入宠物", self)
        title.setObjectName("pageTitle")
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(QLabel("识别类型", self))
        self.source_kind_label = QLabel("等待识别", self)
        self.source_kind_label.setObjectName("selectionBadge")
        header.addWidget(self.source_kind_label)
        root.addLayout(header)

        self.stack = QStackedWidget(self)
        root.addWidget(self.stack, 1)
        self._build_source_page()
        self._build_configure_page()
        self._build_review_page()
        self._set_step(PetImportStep.SOURCE)

    def _build_source_page(self) -> None:
        self.source_page = QWidget(self.stack)
        layout = QVBoxLayout(self.source_page)
        layout.setContentsMargins(0, 12, 0, 0)
        self.source_dropzone = ImportSourceDropZone(self.source_page)
        self.source_dropzone.setObjectName("sourceDropzone")
        drop_layout = QVBoxLayout(self.source_dropzone)
        drop_layout.setContentsMargins(24, 28, 24, 28)
        drop_title = QLabel("拖放一个 PNG、ZIP 或宠物文件夹到这里", self.source_dropzone)
        drop_title.setStyleSheet("font-size: 17px; font-weight: 700;")
        drop_layout.addWidget(drop_title)
        drop_hint = QLabel("PetNest 会自动判断来源类型；文件仅在本机读取。", self.source_dropzone)
        drop_hint.setObjectName("mutedLabel")
        drop_layout.addWidget(drop_hint)
        buttons = QHBoxLayout()
        choose_file = QPushButton("选择文件…", self.source_dropzone)
        choose_file.clicked.connect(self._choose_file)
        buttons.addWidget(choose_file)
        choose_folder = QPushButton("选择文件夹…", self.source_dropzone)
        choose_folder.clicked.connect(self._choose_folder)
        buttons.addWidget(choose_folder)
        buttons.addStretch(1)
        drop_layout.addLayout(buttons)
        self.source_dropzone.file_dropped.connect(lambda value: self.replace_source(Path(value)))
        layout.addWidget(self.source_dropzone)
        self.source_error_label = QLabel("", self.source_page)
        self.source_error_label.setObjectName("mutedLabel")
        self.source_error_label.setWordWrap(True)
        layout.addWidget(self.source_error_label)
        self.status_label = self.source_error_label
        layout.addStretch(1)
        self.stack.addWidget(self.source_page)

    def _build_configure_page(self) -> None:
        self.configure_page = QWidget(self.stack)
        layout = QVBoxLayout(self.configure_page)
        layout.setContentsMargins(0, 12, 0, 0)
        self.configure_stack = QStackedWidget(self.configure_page)
        layout.addWidget(self.configure_stack, 1)

        self.package_options = QWidget(self.configure_stack)
        package_layout = QVBoxLayout(self.package_options)
        package_layout.setContentsMargins(0, 0, 0, 0)
        self.package_summary_label = QLabel("", self.package_options)
        self.package_summary_label.setObjectName("mutedLabel")
        self.package_summary_label.setWordWrap(True)
        self.source_summary_label = self.package_summary_label
        package_layout.addWidget(self.package_summary_label)
        self.preserve_local_actions = QCheckBox("更新时保留本地独有动作", self.package_options)
        self.preserve_local_actions.setToolTip("新包没有的本地动作会保留；同名动作仍以导入包为准")
        self.preserve_local_actions.setVisible(False)
        package_layout.addWidget(self.preserve_local_actions)
        package_layout.addStretch(1)
        self.configure_stack.addWidget(self.package_options)

        self.spritesheet_content = SpriteSheetImportContent(
            self._pets_root,
            show_source_picker=False,
            parent=self.configure_stack,
        )
        self.spritesheet_content.error_occurred.connect(self._show_current_error)
        self.configure_stack.addWidget(self.spritesheet_content)
        self.stack.addWidget(self.configure_page)

    def _build_review_page(self) -> None:
        self.review_page = QWidget(self.stack)
        layout = QVBoxLayout(self.review_page)
        layout.setContentsMargins(0, 12, 0, 0)
        review_title = QLabel("确认导入", self.review_page)
        review_title.setStyleSheet("font-size: 17px; font-weight: 700;")
        layout.addWidget(review_title)
        self.review_summary_label = QLabel("", self.review_page)
        self.review_summary_label.setObjectName("mutedLabel")
        self.review_summary_label.setWordWrap(True)
        layout.addWidget(self.review_summary_label)
        layout.addStretch(1)
        self.stack.addWidget(self.review_page)

    def current_step(self) -> PetImportStep:
        return self._step

    def load_source(self, source: Path) -> None:
        """识别来源。供首次选择与测试直接调用；更换已有草稿请用 ``replace_source``。"""
        path = Path(source).expanduser()
        snapshot = self._snapshot_state()
        had_draft = self._has_source_or_draft()
        try:
            if path.is_file() and path.suffix.casefold() in {".png", ".webp"}:
                candidate = self._inspect_spritesheet(path)
            else:
                candidate = self._inspect_package(path)
            self._commit_candidate(candidate)
        except Exception as error:
            self._restore_state(snapshot)
            message = f"无法读取来源：{error}"
            self.source_error_label.setText(message)
            if had_draft:
                self._set_step_footer(message)
            else:
                self.source_kind_label.setText("识别失败")
                self._set_step(PetImportStep.SOURCE, message)
            return

    def replace_source(self, source: Path) -> None:
        if self._has_source_or_draft():
            answer = QMessageBox.question(
                self,
                "更换来源",
                "当前来源有尚未导入的设置。更换来源会清空这些设置，是否继续？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.load_source(source)

    def _inspect_spritesheet(self, path: Path) -> _SourceCandidate:
        if not path.is_file():
            raise ValueError(f"精灵图文件不存在：{path}")
        SpriteSheetImporter().inspect(path)
        return _SourceCandidate(path, SourceKind.SPRITESHEET)

    def _inspect_package(self, path: Path) -> _SourceCandidate:
        with ExchangeSource.open(path) as materialized:
            kind = detect_source_kind(materialized.root)
            if kind is not SourceKind.PET_PACKAGE:
                raise PetPackageImportError(_non_pet_source_guidance(kind))
            manifests = tuple(materialized.root.rglob("pet.json"))
            if len(manifests) != 1 or manifests[0] != materialized.root / "pet.json":
                raise PetPackageImportError("完整宠物包必须只包含一个根级 pet.json。")
            validation = PackageValidator().validate(materialized.root)
            if not validation.is_valid or validation.config is None:
                detail = "；".join(validation.errors) or "未知错误"
                raise PetPackageImportError(f"宠物包校验失败：{detail}")
            config = validation.config
            identifier = str(config.get("id", "")).strip()
            if not _PET_ID_PATTERN.fullmatch(identifier):
                raise PetPackageImportError("宠物 ID 必须以小写字母开头，只能包含小写字母、数字、- 或 _")
            if self._is_pet_locked(identifier):
                raise PetPackageImportError("当前宠物正在显示下班提醒，请先结束提醒后再更新。")
            animations = config.get("animations")
            animation_count = len(animations) if isinstance(animations, Mapping) else 0
            updating = identifier in {package.identifier for package in self._packages} or (
                self._pets_root / identifier
            ).is_dir()
            metadata = _PackageMetadata(
                identifier=identifier,
                name=str(config.get("name") or identifier),
                animation_count=animation_count,
                frame_count=sum(len(frames) for frames in validation.frames.values()),
                version=str(config.get("version") or "未标注"),
                author=_format_author(config.get("author")),
                updating=updating,
            )
        return _SourceCandidate(path, SourceKind.PET_PACKAGE, metadata)

    def _commit_candidate(self, candidate: _SourceCandidate) -> None:
        """仅在候选已完整验证后，原子地替换活动来源及其表单。"""
        metadata = candidate.package_metadata
        if candidate.kind is SourceKind.PET_PACKAGE and metadata is None:
            raise RuntimeError("完整宠物包候选缺少元数据")
        inspection = None
        if candidate.kind is SourceKind.SPRITESHEET:
            inspection = self.spritesheet_content._importer.inspect(candidate.path)
        self._reset_source_state()
        self._source_path = candidate.path
        self._source_kind = candidate.kind
        if candidate.kind is SourceKind.SPRITESHEET:
            self._set_spritesheet_source(candidate.path, inspection)
            self.source_kind_label.setText("PNG / WebP 精灵图")
            self.configure_stack.setCurrentWidget(self.spritesheet_content)
            self._set_step(PetImportStep.CONFIGURE)
            return
        assert metadata is not None
        self._package_metadata = metadata
        self.source_kind_label.setText("完整宠物包")
        operation = "更新现有宠物" if metadata.updating else "新增宠物"
        self.package_summary_label.setText(
            f"{metadata.name}（{metadata.identifier}） · {metadata.animation_count} 个动作 · "
            f"{metadata.frame_count} 帧 · 版本 {metadata.version} · 作者 {metadata.author} · {operation} · "
            "导入前会自动备份"
        )
        self.preserve_local_actions.setVisible(metadata.updating)
        self.configure_stack.setCurrentWidget(self.package_options)
        self._set_step(PetImportStep.CONFIGURE)

    def _set_spritesheet_source(self, path: Path, inspection: object) -> None:
        """让内容组件复用提交前检查结果，避免 Qt 槽内再次访问文件。"""
        importer = self.spritesheet_content._importer
        previous = importer.__dict__.get("inspect")
        had_override = "inspect" in importer.__dict__
        importer.inspect = lambda _source: inspection
        try:
            self.spritesheet_content.set_source(path)
        finally:
            if had_override:
                importer.inspect = previous
            else:
                del importer.inspect

    def _snapshot_state(self) -> _ImportStateSnapshot:
        content = self.spritesheet_content
        items = tuple(
            (
                content.action_list.item(index).text(),
                content.action_list.item(index).data(Qt.ItemDataRole.UserRole),
            )
            for index in range(content.action_list.count())
        )
        return _ImportStateSnapshot(
            source_path=self._source_path,
            source_kind=self._source_kind,
            package_metadata=self._package_metadata,
            step=self._step,
            source_kind_text=self.source_kind_label.text(),
            source_error_text=self.source_error_label.text(),
            package_summary_text=self.package_summary_label.text(),
            review_summary_text=self.review_summary_label.text(),
            preserve_checked=self.preserve_local_actions.isChecked(),
            preserve_visible=not self.preserve_local_actions.isHidden(),
            configure_index=self.configure_stack.currentIndex(),
            sprite_source=content.source_input.text(),
            sprite_identifier=content.pet_id_input.text(),
            sprite_name=content.name_input.text(),
            sprite_manual=content.manual_select_radio.isChecked(),
            sprite_inspection=content._inspection,
            sprite_selected_columns=tuple(
                (action, tuple(sorted(columns))) for action, columns in content._selected_columns.items()
            ),
            sprite_action_items=items,
            sprite_current_row=content.action_list.currentRow(),
            sprite_status_text=content.status_label.text(),
            sprite_manual_title=content.manual_frame_title.text(),
            sprite_manual_hint=content.manual_frame_hint.text(),
            sprite_selected_text=content.manual_selected_label.text(),
            sprite_last_dirty=content._last_dirty,
        )

    def _restore_state(self, snapshot: _ImportStateSnapshot) -> None:
        content = self.spritesheet_content
        self._source_path = snapshot.source_path
        self._source_kind = snapshot.source_kind
        self._package_metadata = snapshot.package_metadata
        self.source_kind_label.setText(snapshot.source_kind_text)
        self.source_error_label.setText(snapshot.source_error_text)
        self.package_summary_label.setText(snapshot.package_summary_text)
        self.review_summary_label.setText(snapshot.review_summary_text)
        self.preserve_local_actions.setChecked(snapshot.preserve_checked)
        self.preserve_local_actions.setVisible(snapshot.preserve_visible)
        self.configure_stack.setCurrentIndex(snapshot.configure_index)
        self._set_step(snapshot.step)

        controls = (
            content.source_input,
            content.pet_id_input,
            content.name_input,
            content.auto_skip_radio,
            content.manual_select_radio,
            content.action_list,
        )
        previous_blocks = tuple(control.blockSignals(True) for control in controls)
        try:
            content.source_input.setText(snapshot.sprite_source)
            content.pet_id_input.setText(snapshot.sprite_identifier)
            content.name_input.setText(snapshot.sprite_name)
            content.auto_skip_radio.setChecked(not snapshot.sprite_manual)
            content.manual_select_radio.setChecked(snapshot.sprite_manual)
            content._inspection = snapshot.sprite_inspection
            content._selected_columns = {
                action: set(columns) for action, columns in snapshot.sprite_selected_columns
            }
            content.action_list.clear()
            for text, data in snapshot.sprite_action_items:
                item = QListWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, data)
                content.action_list.addItem(item)
            content.action_list.setCurrentRow(snapshot.sprite_current_row)
        finally:
            for control, blocked in zip(controls, previous_blocks, strict=True):
                control.blockSignals(blocked)
        content.manual_selection_panel.setVisible(snapshot.sprite_manual)
        content.initial_content.setVisible(True)
        content.manual_frame_title.setText(snapshot.sprite_manual_title)
        content.manual_frame_hint.setText(snapshot.sprite_manual_hint)
        content.manual_selected_label.setText(snapshot.sprite_selected_text)
        content._last_dirty = snapshot.sprite_last_dirty
        current_item = content.action_list.currentItem()
        inspection_source = getattr(snapshot.sprite_inspection, "source", None)
        source_unreadable = current_item is not None and (
            inspection_source is None or not Path(inspection_source).is_file()
        )
        try:
            if source_unreadable:
                raise OSError("原帧文件不存在")
            content._show_selected_action(current_item, None)
        except Exception:
            try:
                content._show_selected_action(None, None)
            except Exception:
                pass
            content.status_label.setText("原帧文件不可读，已保留导入草稿。")
        else:
            content.status_label.setText(snapshot.sprite_status_text)

    def trigger_primary(self) -> None:
        if self._step is PetImportStep.SOURCE:
            self._choose_file()
        elif self._step is PetImportStep.CONFIGURE:
            self._prepare_review()
        else:
            self._perform_import()

    def trigger_secondary(self) -> None:
        if self._step is PetImportStep.REVIEW:
            self._set_step(PetImportStep.CONFIGURE)
        elif self._step is PetImportStep.CONFIGURE:
            self._set_step(PetImportStep.SOURCE)

    def _prepare_review(self) -> None:
        if self._source_path is None or self._source_kind is None:
            self._show_current_error("请先选择可读取的来源。")
            return
        if self._source_kind is SourceKind.SPRITESHEET:
            source_text = self.spritesheet_content.source_input.text().strip()
            identifier = self.spritesheet_content.pet_id_input.text().strip()
            inspection = self.spritesheet_content._inspection
            if not source_text or not identifier or inspection is None:
                self._show_current_error("请选择有效 PNG 或 WebP 文件并填写宠物 ID。")
                return
            if not _PET_ID_PATTERN.fullmatch(identifier):
                self._show_current_error("宠物 ID 必须以小写字母开头，只能包含小写字母、数字、- 或 _。")
                return
            if (self._pets_root / identifier).exists() or identifier in {
                package.identifier for package in self._packages
            }:
                self._show_current_error(f"宠物 ID {identifier} 已存在，请换一个 ID。")
                return
            if self.spritesheet_content.manual_select_radio.isChecked():
                frame_count = sum(len(columns) for columns in self.spritesheet_content._manual_columns().values())
                mode = "手动选择"
            else:
                frame_count = sum(len(columns) for columns in inspection.nonempty_columns_by_row)
                mode = "自动跳过空帧"
            name = self.spritesheet_content.name_input.text().strip() or identifier
            self.review_summary_label.setText(
                f"来源：{self._source_path}\n识别类型：PNG / WebP 精灵图\n目标：{name}（{identifier}）\n"
                f"有效帧：{frame_count} · {mode}\n策略：新增宠物，不覆盖现有目录"
            )
        else:
            metadata = self._package_metadata
            if metadata is None:
                self._show_current_error("完整宠物包元数据已失效，请重新选择来源。")
                return
            operation = "更新现有宠物" if metadata.updating else "新增宠物"
            preservation = (
                "保留本地独有动作" if metadata.updating and self.preserve_local_actions.isChecked()
                else "以导入包为准"
            )
            self.review_summary_label.setText(
                f"来源：{self._source_path}\n识别类型：完整宠物包\n目标：{metadata.name}（{metadata.identifier}）\n"
                f"动作：{metadata.animation_count} 个 · 帧：{metadata.frame_count}\n"
                f"操作：{operation} · 更新前自动备份 · {preservation}"
            )
        self._set_step(PetImportStep.REVIEW)

    def _perform_import(self) -> None:
        if self._source_path is None or self._source_kind is None:
            self._show_current_error("来源状态已失效，请返回重新选择。")
            return
        if self._source_kind is SourceKind.SPRITESHEET:
            result = self.spritesheet_content.import_selected()
            if result is None:
                self._set_step_footer(self.spritesheet_content.status_label.text())
                return
            self.pet_installed.emit(result.package_id, result)
            self._set_step_footer(f"导入完成：{result.package_root}")
            return
        metadata = self._package_metadata
        if metadata is None:
            self._show_current_error("完整宠物包元数据已失效，请返回重新选择。")
            return
        if self._is_pet_locked(metadata.identifier):
            self._show_current_error("当前宠物正在显示下班提醒，请先结束提醒后再更新。")
            return
        try:
            result = import_pet_package(
                self._source_path,
                self._pets_root,
                PetImportOptions(preserve_local_actions=self.preserve_local_actions.isChecked()),
            )
        except (OSError, PetPackageImportError) as error:
            self._show_current_error(f"导入失败：{error}")
            return
        self.pet_installed.emit(result.pet_id, result)
        self._set_step_footer(f"导入完成：{result.pet_root}")

    def _has_source_or_draft(self) -> bool:
        return bool(
            self._source_path is not None
            or self.spritesheet_content.is_dirty()
            or self.package_summary_label.text()
            or self.review_summary_label.text()
            or self.preserve_local_actions.isChecked()
        )

    def _reset_source_state(self) -> None:
        self._source_path = None
        self._source_kind = None
        self._package_metadata = None
        self.source_kind_label.setText("等待识别")
        self.source_error_label.clear()
        self.package_summary_label.clear()
        self.review_summary_label.clear()
        self.preserve_local_actions.setChecked(False)
        self.preserve_local_actions.setVisible(False)
        self.spritesheet_content.source_input.clear()
        self.spritesheet_content.pet_id_input.clear()
        self.spritesheet_content.name_input.clear()
        self.spritesheet_content.auto_skip_radio.setChecked(True)
        self._set_step(PetImportStep.SOURCE)

    def _set_step(self, step: PetImportStep, status_override: str | None = None) -> None:
        self._step = step
        page = {
            PetImportStep.SOURCE: self.source_page,
            PetImportStep.CONFIGURE: self.configure_page,
            PetImportStep.REVIEW: self.review_page,
        }[step]
        self.stack.setCurrentWidget(page)
        self._set_step_footer(status_override)

    def _set_step_footer(self, status_override: str | None = None) -> None:
        if self._step is PetImportStep.SOURCE:
            self.set_footer(
                status=status_override or "支持 PNG、ZIP 和文件夹",
                primary_text="选择来源",
                secondary_text=None,
            )
        elif self._step is PetImportStep.CONFIGURE:
            self.set_footer(
                status=status_override or "设置会保留，返回不会丢失",
                primary_text="下一步",
                secondary_text="上一步",
            )
        else:
            self.set_footer(
                status=status_override or "确认前不会写入宠物目录",
                primary_text="开始导入",
                secondary_text="上一步",
            )

    def _show_current_error(self, message: str) -> None:
        self._set_step_footer(message)

    def _choose_file(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "选择宠物来源",
            str(Path.home()),
            "支持的文件 (*.png *.webp *.zip);;PNG / WebP 精灵图 (*.png *.webp);;ZIP 宠物包 (*.zip)",
        )
        if selected:
            self.replace_source(Path(selected))

    def _choose_folder(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "选择宠物文件夹", str(Path.home()))
        if selected:
            self.replace_source(Path(selected))


def _format_author(value: object) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, Mapping):
        for key in ("name", "display_name", "id"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
    return "未标注"


def _non_pet_source_guidance(kind: SourceKind) -> str:
    return {
        SourceKind.ACTION_PACK: "这是动作包，请使用动作导入页面。",
        SourceKind.LEGACY_WORK_FINISH: "这是旧版下班动画包，请使用动作导入页面（旧版下班动画）。",
        SourceKind.SPRITESHEET: "这是 PNG / WebP 精灵图，请在导入宠物页面选择单个 PNG 或 WebP 文件。",
    }[kind]


__all__ = ["PetImportPage", "PetImportStep"]
