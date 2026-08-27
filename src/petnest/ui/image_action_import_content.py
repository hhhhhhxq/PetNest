"""“用图片制作动作”模式的草稿、排序、预览和安装参数组件。"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
from typing import ContextManager
from uuid import uuid4

from PySide6.QtCore import QSize, QSignalBlocker, Qt, Signal
from PySide6.QtGui import QColor, QDragEnterEvent, QDropEvent, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListView,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from petnest.core.action_pack import ActionPack
from petnest.core.action_slots import (
    ActionSlot,
    action_slot,
    action_slots,
    resolve_slot_import_target,
)
from petnest.core.image_action_builder import (
    ImageActionDraft,
    ImageActionFrame,
    ImageActionSourceError,
    OversizedFrameConfirmationRequired,
    build_image_action_pack,
    image_action_canvas,
    inspect_image_files,
    inspect_image_folder,
)
from petnest.models.pet_package import PetPackage
from petnest.core.package_validator import MAX_TIMELINE_DURATION_MS
from petnest.ui.animation_preview_widget import AnimationPreviewWidget, CheckerboardLabel
from petnest.ui.lucide_icons import lucide_icon


@dataclass(frozen=True, slots=True)
class _ImageActionDraftState:
    draft: ImageActionDraft
    fps: float
    frame_durations_ms: tuple[int, ...] | None
    entrance_direction: str | None
    dirty: bool


class ImageSourceDropZone(QFrame):
    files_dropped = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setObjectName("imageActionDropZone")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        self.hint_label = QLabel("拖动缩略图调整顺序；也可以把 PNG / WebP 拖到帧区域。", self)
        self.hint_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.hint_label.setObjectName("mutedLabel")
        layout.addWidget(self.hint_label)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        urls = event.mimeData().urls()
        if urls and all(url.isLocalFile() for url in urls):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        paths = tuple(Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile())
        if paths:
            self.files_dropped.emit(paths)
            event.acceptProposedAction()
        else:
            event.ignore()


class ImageFrameCard(QFrame):
    """帧网格中的单张图片卡片。"""

    delete_requested = Signal(Path)

    def __init__(
        self,
        frame: ImageActionFrame,
        index: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._path = frame.path
        self.setObjectName("imageFrameCard")
        self.setFixedSize(142, 82)

        layout = QGridLayout(self)
        layout.setContentsMargins(5, 5, 5, 4)
        layout.setHorizontalSpacing(2)
        layout.setVerticalSpacing(2)

        self.thumbnail = CheckerboardLabel("", self)
        self.thumbnail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumbnail.setMinimumSize(118, 58)
        self.thumbnail.tile_size = 15
        self.thumbnail.light_color = QColor("#fffaf7")
        self.thumbnail.dark_color = QColor("#f1e6e0")
        pixmap = QPixmap(str(frame.path))
        if not pixmap.isNull():
            self.thumbnail.setPixmap(
                pixmap.scaled(
                    106,
                    58,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        layout.addWidget(self.thumbnail, 0, 0, 1, 3)

        self.delete_button = QToolButton(self)
        self.delete_button.setObjectName("frameDeleteButton")
        self.delete_button.setText("×")
        self.delete_button.setToolTip("删除这一帧")
        self.delete_button.setFixedSize(20, 20)
        self.delete_button.clicked.connect(lambda: self.delete_requested.emit(self._path))
        layout.addWidget(
            self.delete_button,
            0,
            2,
            alignment=Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight,
        )

        self.index_label = QLabel(self)
        self.index_label.setObjectName("frameIndexLabel")
        self.index_label.setText(f"{index:03d}")
        layout.addWidget(
            self.index_label,
            0,
            0,
            alignment=Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft,
        )
        name_label = QLabel(frame.path.name, self)
        name_label.setObjectName("mutedLabel")
        name_label.setToolTip(str(frame.path))
        name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(name_label, 1, 0, 1, 3)

class ImageActionImportContent(QWidget):
    draft_changed = Signal()

    def __init__(
        self,
        packages: Sequence[PetPackage],
        *,
        current_pet_id: str | None = None,
        embed_target_selector: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("imageActionImportContent")
        self._packages = tuple(packages)
        self._draft_workspace = TemporaryDirectory(prefix="petnest-image-drafts-")
        self._draft_workspace_root = Path(self._draft_workspace.name)
        self._draft: ImageActionDraft | None = None
        self._draft_states: dict[tuple[str, str], _ImageActionDraftState] = {}
        self._active_draft_key: tuple[str, str] | None = None
        self._preview_frame_durations_ms: tuple[int, ...] | None = None
        self._draft_dirty = False
        self._preview_pixmaps: tuple[QPixmap, ...] = ()
        self._canvas_error: str | None = None
        self._syncing_duration = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        self.target_combo = QComboBox(self)
        self._populate_targets(current_pet_id)
        self._last_target_id = self.target_combo.currentData()
        self.target_combo.currentIndexChanged.connect(self._target_changed)
        if embed_target_selector:
            target_row = QHBoxLayout()
            target_row.addWidget(QLabel("目标宠物", self))
            target_row.addWidget(self.target_combo, 1)
            root.addLayout(target_row)
        else:
            self.target_combo.hide()

        self.action_section = QFrame(self)
        self.action_section.setObjectName("actionImportPanel")
        action_section_layout = QVBoxLayout(self.action_section)
        action_section_layout.setContentsMargins(11, 11, 11, 11)
        action_section_layout.setSpacing(7)

        action_row = QHBoxLayout()
        action_row.setSpacing(7)
        self.action_icon = QLabel(self.action_section)
        self.action_icon.setPixmap(
            lucide_icon("list-tree", color="#4c423d", size=16).pixmap(16, 16)
        )
        action_row.addWidget(self.action_icon)
        action_title = QLabel("选择动作", self.action_section)
        action_title.setObjectName("actionImportPanelTitle")
        action_row.addWidget(action_title)
        self.slot_combo = QComboBox(self)
        self._populate_slots()
        self.slot_combo.currentIndexChanged.connect(self._slot_changed)
        action_row.addWidget(self.slot_combo, 1)
        self.action_target_label = QLabel(self)
        self.action_target_label.setObjectName("actionImportTarget")
        action_row.addWidget(self.action_target_label)
        action_section_layout.addLayout(action_row)

        fullscreen_row = QHBoxLayout()
        self.fullscreen_hint_label = QLabel(self)
        self.fullscreen_hint_label.setObjectName("mutedLabel")
        self.fullscreen_hint_label.setWordWrap(True)
        self.fullscreen_hint_label.hide()
        fullscreen_row.addWidget(self.fullscreen_hint_label, 1)
        self.entrance_direction_combo = QComboBox(self)
        self.entrance_direction_combo.addItem("从右侧进入", "right")
        self.entrance_direction_combo.addItem("从左侧进入", "left")
        self.entrance_direction_combo.addItem("原地显示", "none")
        self.entrance_direction_combo.currentIndexChanged.connect(
            self._entrance_direction_changed
        )
        self.entrance_direction_combo.hide()
        fullscreen_row.addWidget(self.entrance_direction_combo)
        action_section_layout.addLayout(fullscreen_row)
        root.addWidget(self.action_section)

        self.frame_section = QFrame(self)
        self.frame_section.setObjectName("actionImportPanel")
        frame_section_layout = QVBoxLayout(self.frame_section)
        frame_section_layout.setContentsMargins(11, 11, 11, 11)
        frame_section_layout.setSpacing(7)
        frames_heading = QHBoxLayout()
        frames_heading.setSpacing(7)
        self.frame_icon = QLabel(self.frame_section)
        self.frame_icon.setPixmap(
            lucide_icon("gallery-horizontal", color="#4c423d", size=16).pixmap(16, 16)
        )
        frames_heading.addWidget(self.frame_icon)
        frame_title = QLabel("动作帧", self.frame_section)
        frame_title.setObjectName("actionImportPanelTitle")
        frames_heading.addWidget(frame_title)
        frames_heading.addStretch(1)
        self.frame_count_label = QLabel("0 帧", self.frame_section)
        self.frame_count_label.setObjectName("actionImportCount")
        frames_heading.addWidget(self.frame_count_label)
        self.add_files_button = QPushButton("添加图片", self)
        self.add_files_button.setObjectName("actionImportSecondary")
        self.add_files_button.setIcon(lucide_icon("images", color="#4c423d", size=14))
        self.add_files_button.clicked.connect(self._choose_files)
        frames_heading.addWidget(self.add_files_button)
        self.choose_folder_button = QPushButton("选择文件夹", self)
        self.choose_folder_button.setObjectName("actionImportSecondary")
        self.choose_folder_button.setIcon(
            lucide_icon("folder-open", color="#4c423d", size=14)
        )
        self.choose_folder_button.clicked.connect(self._choose_folder)
        frames_heading.addWidget(self.choose_folder_button)
        frame_section_layout.addLayout(frames_heading)

        self.drop_zone = ImageSourceDropZone(self)
        self.drop_zone.setObjectName("actionImportFrameHint")
        self.drop_zone.setMaximumHeight(30)
        self.drop_zone.files_dropped.connect(self._load_dropped)
        frame_section_layout.addWidget(self.drop_zone)

        self.remove_frame_button = QPushButton("删除选中帧", self)
        self.remove_frame_button.clicked.connect(self._remove_selected_frame)
        self.remove_frame_button.hide()
        self.frame_list = QListWidget(self)
        self.frame_list.setObjectName("imageActionFrameList")
        self.frame_list.setViewMode(QListView.ViewMode.IconMode)
        self.frame_list.setResizeMode(QListView.ResizeMode.Adjust)
        self.frame_list.setFlow(QListView.Flow.LeftToRight)
        self.frame_list.setWrapping(True)
        self.frame_list.setMovement(QListView.Movement.Snap)
        self.frame_list.setGridSize(QSize(150, 89))
        self.frame_list.setSpacing(7)
        self.frame_list.setMinimumHeight(106)
        self.frame_list.setMaximumHeight(198)
        self.frame_list.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.frame_list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.frame_list.model().rowsMoved.connect(self._sync_draft_from_list)
        frame_section_layout.addWidget(self.frame_list, 1)
        timing_row = QHBoxLayout()
        self.fps_input = QDoubleSpinBox(self)
        self.fps_input.setRange(0.5, 60.0)
        self.fps_input.setDecimals(1)
        self.fps_input.setSingleStep(0.5)
        self.fps_input.valueChanged.connect(self._fps_changed)
        timing_row.addWidget(QLabel("播放速度", self))
        timing_row.addWidget(self.fps_input, 1)
        self.total_duration_input = QSpinBox(self)
        self.total_duration_input.setRange(50, 600_000)
        self.total_duration_input.setSuffix(" ms")
        self.total_duration_input.valueChanged.connect(self._duration_changed)
        timing_row.addWidget(QLabel("总时长", self))
        timing_row.addWidget(self.total_duration_input, 1)
        frame_section_layout.addLayout(timing_row)
        self.fit_oversized_checkbox = QCheckBox("等比缩小超出画布的图片", self)
        self.fit_oversized_checkbox.toggled.connect(self._rebuild_preview)
        self.fit_oversized_checkbox.hide()
        frame_section_layout.addWidget(self.fit_oversized_checkbox)
        root.addWidget(self.frame_section, 1)

        self.preview_section = QFrame(self)
        self.preview_section.setObjectName("actionImportPanel")
        self.preview_section.setMaximumHeight(245)
        preview_section_layout = QVBoxLayout(self.preview_section)
        preview_section_layout.setContentsMargins(11, 11, 11, 11)
        preview_section_layout.setSpacing(7)
        preview_heading = QHBoxLayout()
        preview_heading.setSpacing(7)
        self.preview_icon = QLabel(self.preview_section)
        self.preview_icon.setPixmap(
            lucide_icon("play", color="#4c423d", size=16).pixmap(16, 16)
        )
        preview_heading.addWidget(self.preview_icon)
        preview_title = QLabel("实时预览", self.preview_section)
        preview_title.setObjectName("actionImportPanelTitle")
        preview_heading.addWidget(preview_title)
        preview_heading.addStretch(1)
        preview_section_layout.addLayout(preview_heading)
        self.preview = AnimationPreviewWidget(self.preview_section)
        self.preview.preview_label.setMinimumSize(220, 170)
        self.preview.preview_label.setMaximumHeight(170)
        self.preview.preview_label.tile_size = 20
        self.preview.preview_label.light_color = QColor("#fffaf7")
        self.preview.preview_label.dark_color = QColor("#f0e4de")
        self.preview.preview_play_button.hide()
        preview_section_layout.addWidget(self.preview, 1)
        root.addWidget(self.preview_section)

        self.footer_host = QWidget(self)
        footer_host_layout = QHBoxLayout(self.footer_host)
        footer_host_layout.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self.footer_host)

        self.status_label = QLabel("请先选择动作并添加图片。", self)
        self.status_label.setObjectName("mutedLabel")
        self.status_label.setWordWrap(True)
        if not embed_target_selector:
            self.status_label.hide()
        root.addWidget(self.status_label)

        self._slot_changed()

    def pause_previews(self) -> None:
        self.preview.set_playing(False)

    def resume_active_preview(self) -> None:
        if self.preview.frame_count:
            self.preview.set_playing(True)

    def selected_package(self) -> PetPackage | None:
        identifier = self.target_combo.currentData()
        return next((package for package in self._packages if package.identifier == identifier), None)

    def selected_slot(self) -> ActionSlot | None:
        key = self.slot_combo.currentData()
        if not isinstance(key, str):
            return None
        return action_slot(key)

    def select_slot(self, key: str) -> None:
        index = self.slot_combo.findData(key)
        if index < 0:
            raise ValueError(f"图片导入页不支持动作槽位：{key}")
        self.slot_combo.setCurrentIndex(index)

    def select_target(self, identifier: str) -> None:
        index = self.target_combo.findData(identifier)
        if index < 0:
            raise ValueError(f"图片导入页找不到目标宠物：{identifier}")
        self.target_combo.setCurrentIndex(index)

    def action_name(self) -> str | None:
        package, slot = self.selected_package(), self.selected_slot()
        return (
            resolve_slot_import_target(package, slot).action_name
            if package is not None and slot is not None
            else None
        )

    def ordered_paths(self) -> tuple[Path, ...]:
        return tuple(frame.path for frame in self._draft.frames) if self._draft is not None else ()

    def fps(self) -> float:
        return float(self.fps_input.value())

    def fit_oversized(self) -> bool:
        return self.fit_oversized_checkbox.isChecked()

    def entrance_direction(self) -> str | None:
        value = self.entrance_direction_combo.currentData()
        return str(value) if not self.entrance_direction_combo.isHidden() and isinstance(value, str) else None

    def load_files(self, paths: Sequence[Path]) -> None:
        self._set_draft(inspect_image_files(paths))

    def add_files(self, paths: Sequence[Path]) -> None:
        if self._draft is None:
            self.load_files(paths)
            return
        existing = self.ordered_paths()
        combined = inspect_image_files((*existing, *tuple(Path(path) for path in paths)))
        new_paths = tuple(frame.path for frame in combined.frames if frame.path not in set(existing))
        ordered = (*existing, *new_paths)
        self._set_draft(combined.reordered(ordered))

    def load_folder(self, folder: Path) -> None:
        self._set_draft(inspect_image_folder(folder))

    def move_frame(self, source_row: int, target_row: int) -> None:
        if not 0 <= source_row < self.frame_list.count() or not 0 <= target_row < self.frame_list.count():
            raise IndexError("帧移动位置超出范围")
        item = self.frame_list.takeItem(source_row)
        self.frame_list.insertItem(target_row, item)
        self.frame_list.setCurrentRow(target_row)
        self._sync_draft_from_list()

    def can_install(self) -> bool:
        return (
            self._draft is not None
            and bool(self._draft.frames)
            and self._draft_dirty
            and self.selected_package() is not None
            and self.selected_slot() is not None
            and (not self._has_oversized_frames() or self.fit_oversized())
            and self._canvas_error is None
        )

    def primary_text(self) -> str:
        package = self.selected_package()
        action_name = self.action_name()
        return "替换动作" if package is not None and action_name in package.animations else "安装动作"

    def build_pack(self) -> ContextManager[ActionPack]:
        package, slot = self.selected_package(), self.selected_slot()
        if package is None or slot is None or self._draft is None:
            raise ImageActionSourceError("请先选择目标宠物、动作和图片")
        return build_image_action_pack(
            package,
            slot,
            self._draft,
            fps=self.fps(),
            frame_durations_ms=self._preview_frame_durations_ms,
            fit_oversized=self.fit_oversized(),
            entrance_direction=self.entrance_direction(),
        )

    def clear_after_success(self, message: str) -> None:
        if self._active_draft_key is not None:
            self._draft_states.pop(self._active_draft_key, None)
        self._draft = None
        self._preview_frame_durations_ms = None
        self._draft_dirty = False
        self._preview_pixmaps = ()
        self.frame_list.clear()
        self.frame_count_label.setText("0 帧")
        self.preview.set_frames(())
        self.fit_oversized_checkbox.setChecked(False)
        self.fit_oversized_checkbox.hide()
        self.status_label.setText(message)
        self.draft_changed.emit()

    def finish_failure(self, message: str) -> None:
        self.status_label.setText(message)

    def refresh_packages(self, packages: Sequence[PetPackage], current_pet_id: str) -> None:
        self._draft_states = {
            key: state for key, state in self._draft_states.items() if state.dirty
        }
        if not self._draft_dirty:
            self._draft = None
            self._preview_frame_durations_ms = None
        self._packages = tuple(packages)
        self._populate_targets(current_pet_id)
        self._target_changed()

    def _populate_targets(self, selected_id: str | None) -> None:
        with QSignalBlocker(self.target_combo):
            self.target_combo.clear()
            for package in self._packages:
                self.target_combo.addItem(package.name, package.identifier)
            index = self.target_combo.findData(selected_id)
            self.target_combo.setCurrentIndex(index if index >= 0 else (0 if self.target_combo.count() else -1))

    def _populate_slots(self) -> None:
        category_order = {
            "基础": 0,
            "鼠标": 1,
            "Codex": 2,
            "系统空闲": 3,
            "下班提醒": 4,
            "移动": 5,
        }
        slots = tuple(action_slots())
        indexed = {slot.key: index for index, slot in enumerate(slots)}
        ordered = sorted(
            slots,
            key=lambda slot: (category_order.get(slot.category, 99), indexed[slot.key]),
        )
        popup = QListView(self.slot_combo)
        popup.setMinimumWidth(420)
        self.slot_combo.setView(popup)
        self.slot_combo.setMaxVisibleItems(len(ordered))
        for slot in ordered:
            self.slot_combo.addItem(f"{slot.category} · {slot.label}", slot.key)
        self.slot_combo.setCurrentIndex(0 if self.slot_combo.count() else -1)

    def _set_draft(self, draft: ImageActionDraft) -> None:
        self._draft = draft
        self._preview_frame_durations_ms = None
        self._draft_dirty = True
        self._populate_frame_list()
        self._update_fit_visibility()
        self._sync_total_from_fps()
        self.status_label.setText(f"已读取 {len(draft.frames)} 帧，可调整顺序和播放速度。")
        self._rebuild_preview()
        self._save_active_draft_state()
        self.draft_changed.emit()

    def _populate_frame_list(self) -> None:
        self.frame_list.clear()
        self.frame_count_label.setText("0 帧")
        if self._draft is None:
            return
        for index, frame in enumerate(self._draft.frames, start=1):
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, frame.path)
            item.setSizeHint(QSize(142, 82))
            self.frame_list.addItem(item)
            card = ImageFrameCard(frame, index, self.frame_list)
            card.delete_requested.connect(self._delete_frame)
            self.frame_list.setItemWidget(item, card)
        self.frame_count_label.setText(f"{len(self._draft.frames)} 帧")

    def _sync_draft_from_list(self, *_args: object) -> None:
        if self._draft is None or self.frame_list.count() != len(self._draft.frames):
            return
        paths = tuple(
            Path(self.frame_list.item(index).data(Qt.ItemDataRole.UserRole))
            for index in range(self.frame_list.count())
        )
        self._draft = self._draft.reordered(paths)
        self._preview_frame_durations_ms = None
        self._draft_dirty = True
        self._populate_frame_list()
        self._rebuild_preview()
        self._save_active_draft_state()
        self.draft_changed.emit()

    def _remove_selected_frame(self) -> None:
        if self._draft is None or self.frame_list.currentItem() is None:
            return
        self._delete_frame(Path(self.frame_list.currentItem().data(Qt.ItemDataRole.UserRole)))

    def _delete_frame(self, path: Path) -> None:
        if self._draft is None:
            return
        try:
            self._draft = self._draft.without(path)
        except ImageActionSourceError as error:
            self.status_label.setText(str(error))
            return
        self._populate_frame_list()
        self._preview_frame_durations_ms = None
        self._draft_dirty = True
        self._sync_total_from_fps()
        self._rebuild_preview()
        self._save_active_draft_state()
        self.draft_changed.emit()

    def _slot_changed(self, *_args: object) -> None:
        self._save_active_draft_state()
        slot = self.selected_slot()
        if slot is None:
            return
        self._update_action_target()
        self._update_fullscreen_controls()
        self._activate_selected_draft()
        self.draft_changed.emit()

    def _target_changed(self, *_args: object) -> None:
        self._save_active_draft_state()
        current_id = self.target_combo.currentData()
        changed = self._last_target_id is not None and current_id != self._last_target_id
        if changed:
            self.fit_oversized_checkbox.setChecked(False)
        self._last_target_id = current_id
        self._update_action_target()
        self._update_fullscreen_controls()
        self._activate_selected_draft()
        self._update_fit_visibility()
        self.draft_changed.emit()

    def _selected_draft_key(self) -> tuple[str, str] | None:
        package = self.selected_package()
        action_name = self.action_name()
        if package is None or action_name is None:
            return None
        return package.identifier, action_name

    def _save_active_draft_state(self) -> None:
        if self._active_draft_key is None or self._draft is None:
            return
        self._draft_states[self._active_draft_key] = _ImageActionDraftState(
            self._draft,
            self.fps(),
            self._preview_frame_durations_ms,
            self.entrance_direction(),
            self._draft_dirty,
        )

    def _activate_selected_draft(self) -> None:
        key = self._selected_draft_key()
        self._active_draft_key = key
        if key is None:
            self._clear_draft_for_selection("请选择目标宠物和动作。")
            return
        cached = self._draft_states.get(key)
        if cached is not None:
            self._apply_draft_state(cached, "已恢复这个动作尚未安装的编辑内容。")
            return
        package = self.selected_package()
        slot = self.selected_slot()
        action_name = self.action_name()
        definition = (
            package.animations.get(action_name)
            if package is not None and action_name is not None
            else None
        )
        if definition is None or not definition.frames:
            fallback_fps = slot.fps if slot is not None else 10.0
            self._clear_draft_for_selection(
                "当前动作还没有图片，请添加动作帧。",
                fps=fallback_fps,
            )
            return
        try:
            editable_frames = self._copy_existing_frames(definition.frames)
            inspected = inspect_image_files(editable_frames)
            draft = ImageActionDraft(
                inspected.reordered(editable_frames).frames,
                f"当前动作 {action_name}",
            )
        except ImageActionSourceError as error:
            self._clear_draft_for_selection(f"无法读取当前动作帧：{error}", fps=definition.fps)
            return
        state = _ImageActionDraftState(
            draft,
            definition.fps,
            definition.frame_durations_ms,
            definition.entrance_direction if definition.scope == "fullscreen" else None,
            False,
        )
        self._draft_states[key] = state
        self._apply_draft_state(
            state,
            f"已载入当前动作的 {len(draft.frames)} 帧，可直接预览或继续编辑。",
        )

    def _apply_draft_state(self, state: _ImageActionDraftState, message: str) -> None:
        if state.frame_durations_ms is not None and (
            any(item > MAX_TIMELINE_DURATION_MS for item in state.frame_durations_ms)
            or sum(state.frame_durations_ms) > MAX_TIMELINE_DURATION_MS
        ):
            self._clear_draft_for_selection(
                f"当前动作逐帧时长超过安全上限 {MAX_TIMELINE_DURATION_MS} ms。",
                fps=state.fps,
            )
            return
        self._draft = state.draft
        self._preview_frame_durations_ms = state.frame_durations_ms
        self._draft_dirty = state.dirty
        with QSignalBlocker(self.fps_input):
            self.fps_input.setValue(state.fps)
        slot = self.selected_slot()
        direction = state.entrance_direction or (
            slot.entrance_direction if slot is not None else None
        )
        index = self.entrance_direction_combo.findData(direction or "none")
        if index >= 0:
            with QSignalBlocker(self.entrance_direction_combo):
                self.entrance_direction_combo.setCurrentIndex(index)
        self._populate_frame_list()
        self._update_fit_visibility()
        self._sync_total_from_fps()
        self.status_label.setText(message)
        self._rebuild_preview()

    def _clear_draft_for_selection(self, message: str, *, fps: float = 10.0) -> None:
        self._draft = None
        self._preview_frame_durations_ms = None
        self._preview_pixmaps = ()
        self._draft_dirty = False
        slot = self.selected_slot()
        direction = slot.entrance_direction if slot is not None else None
        direction_index = self.entrance_direction_combo.findData(direction or "none")
        if direction_index >= 0:
            with QSignalBlocker(self.entrance_direction_combo):
                self.entrance_direction_combo.setCurrentIndex(direction_index)
        with QSignalBlocker(self.fps_input):
            self.fps_input.setValue(fps)
        self._populate_frame_list()
        self.preview.set_frames(())
        self._update_fit_visibility()
        self._sync_total_from_fps()
        self.status_label.setText(message)

    def _copy_existing_frames(self, frames: Sequence[Path]) -> tuple[Path, ...]:
        destination = self._draft_workspace_root / uuid4().hex
        destination.mkdir(parents=True)
        copied: list[Path] = []
        try:
            for source in frames:
                target = destination / source.name
                shutil.copy2(source, target)
                copied.append(target)
        except OSError as error:
            shutil.rmtree(destination, ignore_errors=True)
            raise ImageActionSourceError(f"无法准备当前动作编辑副本：{error}") from error
        return tuple(copied)

    def _update_action_target(self) -> None:
        package = self.selected_package()
        action_name = self.action_name()
        definition = package.animations.get(action_name) if package is not None and action_name is not None else None
        if definition is None:
            self.action_target_label.setText(f"将创建：{action_name or '—'}")
            return
        self.action_target_label.setText(f"将替换：{action_name}")

    def _has_oversized_frames(self) -> bool:
        self._canvas_error = None
        package, slot = self.selected_package(), self.selected_slot()
        if self._draft is None or package is None or slot is None:
            return False
        try:
            canvas = image_action_canvas(package, slot, self._draft)
        except ImageActionSourceError as error:
            self._canvas_error = str(error)
            self.status_label.setText(self._canvas_error)
            return False
        return any(
            frame.width > canvas[0] or frame.height > canvas[1]
            for frame in self._draft.frames
        )

    def _update_fullscreen_controls(self) -> None:
        slot = self.selected_slot()
        if slot is None or slot.scope != "fullscreen":
            self.fullscreen_hint_label.hide()
            self.entrance_direction_combo.hide()
            return
        if slot.key == "work_finish_lie_loop":
            message = "躺下循环仅在“进入画面”和“躺下过渡”前两项齐全时播放。"
        else:
            message = "全屏下班动画需同时安装“进入画面”和“躺下过渡”；缺少任一项时会使用普通动作。"
        self.fullscreen_hint_label.setText(message)
        self.fullscreen_hint_label.show()
        self.entrance_direction_combo.setVisible(slot.key == "work_finish_walk")

    def _update_fit_visibility(self) -> None:
        required = self._has_oversized_frames()
        self.fit_oversized_checkbox.setVisible(required)
        if not required:
            self.fit_oversized_checkbox.setChecked(False)

    def _rebuild_preview(self, *_args: object) -> None:
        if self._draft is None:
            self._preview_pixmaps = ()
            self.preview.set_frames(())
            return
        try:
            with self.build_pack() as pack:
                action = next(iter(pack.actions.values()))
                self._preview_pixmaps = tuple(_scaled_preview_pixmap(path) for path in action.asset_paths)
            self._refresh_preview_timing()
        except OversizedFrameConfirmationRequired as error:
            self._preview_pixmaps = tuple(_scaled_preview_pixmap(frame.path) for frame in self._draft.frames)
            self._refresh_preview_timing()
            self.status_label.setText(str(error))
        except ImageActionSourceError as error:
            self._preview_pixmaps = ()
            self.preview.set_frames(())
            self.status_label.setText(str(error))

    def _refresh_preview_timing(self) -> None:
        durations = self._preview_frame_durations_ms
        if durations is not None and len(durations) != len(self._preview_pixmaps):
            durations = None
        self.preview.set_frames(
            self._preview_pixmaps,
            frame_durations_ms=durations,
            fps=self.fps(),
        )

    def _fps_changed(self, *_args: object) -> None:
        if self._syncing_duration:
            return
        self._preview_frame_durations_ms = None
        if self._draft is not None:
            self._draft_dirty = True
        self._sync_total_from_fps()
        self._refresh_preview_timing()
        self._save_active_draft_state()
        self.draft_changed.emit()

    def _duration_changed(self, value: int) -> None:
        if self._syncing_duration or self._draft is None or not self._draft.frames:
            return
        self._preview_frame_durations_ms = None
        self._draft_dirty = True
        self._syncing_duration = True
        try:
            self.fps_input.setValue(len(self._draft.frames) * 1000 / max(1, value))
        finally:
            self._syncing_duration = False
        self._sync_total_from_fps()
        self._refresh_preview_timing()
        self._save_active_draft_state()
        self.draft_changed.emit()

    def _sync_total_from_fps(self) -> None:
        frame_count = len(self._draft.frames) if self._draft is not None else 1
        minimum = max(1, round(frame_count * 1000 / self.fps_input.maximum()))
        maximum = max(minimum, round(frame_count * 1000 / self.fps_input.minimum()))
        durations = self._preview_frame_durations_ms
        duration = (
            sum(durations)
            if durations is not None and len(durations) == frame_count
            else round(frame_count * 1000 / max(0.5, self.fps()))
        )
        minimum = max(1, min(minimum, duration))
        maximum = max(maximum, duration)
        self._syncing_duration = True
        try:
            with QSignalBlocker(self.total_duration_input):
                self.total_duration_input.setRange(minimum, maximum)
                self.total_duration_input.setValue(duration)
        finally:
            self._syncing_duration = False

    def _entrance_direction_changed(self, *_args: object) -> None:
        if self._draft is not None:
            self._draft_dirty = True
            self._save_active_draft_state()
        self._rebuild_preview()
        self.draft_changed.emit()

    def _choose_files(self) -> None:
        selected, _filter = QFileDialog.getOpenFileNames(
            self,
            "选择动作图片",
            str(Path.home()),
            "动作图片 (*.png *.webp)",
        )
        if selected:
            self._load_safely(lambda: self.add_files(tuple(Path(path) for path in selected)))

    def _choose_folder(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "选择图片文件夹", str(Path.home()))
        if selected:
            self._load_safely(lambda: self.load_folder(Path(selected)))

    def _load_dropped(self, paths: object) -> None:
        if not isinstance(paths, tuple) or not paths:
            return
        if len(paths) == 1 and isinstance(paths[0], Path) and paths[0].is_dir():
            self._load_safely(lambda: self.load_folder(paths[0]))
        else:
            self._load_safely(lambda: self.add_files(tuple(Path(path) for path in paths)))

    def _load_safely(self, operation: object) -> None:
        if not callable(operation):
            return
        try:
            operation()
        except ImageActionSourceError as error:
            self.status_label.setText(str(error))


def _scaled_preview_pixmap(path: Path) -> QPixmap:
    pixmap = QPixmap(str(path))
    if pixmap.isNull():
        return pixmap
    return pixmap.scaled(
        360,
        360,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


__all__ = ["ImageActionImportContent", "ImageFrameCard", "ImageSourceDropZone"]
