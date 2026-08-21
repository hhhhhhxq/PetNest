"""“用图片制作动作”模式的草稿、排序、预览和安装参数组件。"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import ContextManager

from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QIcon, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from petnest.core.action_pack import ActionPack
from petnest.core.action_slots import ActionSlot, action_slot, action_slots, resolve_slot
from petnest.core.image_action_builder import (
    ImageActionDraft,
    ImageActionSourceError,
    OversizedFrameConfirmationRequired,
    build_image_action_pack,
    image_action_canvas,
    inspect_image_files,
    inspect_image_folder,
)
from petnest.models.pet_package import PetPackage
from petnest.ui.animation_preview_widget import AnimationPreviewWidget


class ImageSourceDropZone(QFrame):
    files_dropped = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setObjectName("imageActionDropZone")
        layout = QVBoxLayout(self)
        label = QLabel("也可以把多张 PNG / WebP 拖到这里", self)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setObjectName("mutedLabel")
        layout.addWidget(label)

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
        self._draft: ImageActionDraft | None = None
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

        action_row = QHBoxLayout()
        action_row.addWidget(QLabel("要制作的动作", self))
        self.slot_combo = QComboBox(self)
        self._populate_slots()
        self.slot_combo.currentIndexChanged.connect(self._slot_changed)
        action_row.addWidget(self.slot_combo, 1)
        self.action_target_label = QLabel(self)
        self.action_target_label.setObjectName("mutedLabel")
        action_row.addWidget(self.action_target_label)
        root.addLayout(action_row)

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
        self.entrance_direction_combo.currentIndexChanged.connect(self._rebuild_preview)
        self.entrance_direction_combo.hide()
        fullscreen_row.addWidget(self.entrance_direction_combo)
        root.addLayout(fullscreen_row)

        source_row = QHBoxLayout()
        self.add_files_button = QPushButton("添加多张图片…", self)
        self.add_files_button.clicked.connect(self._choose_files)
        source_row.addWidget(self.add_files_button)
        self.choose_folder_button = QPushButton("选择图片文件夹…", self)
        self.choose_folder_button.clicked.connect(self._choose_folder)
        source_row.addWidget(self.choose_folder_button)
        source_row.addStretch(1)
        root.addLayout(source_row)

        self.drop_zone = ImageSourceDropZone(self)
        self.drop_zone.files_dropped.connect(self._load_dropped)
        root.addWidget(self.drop_zone)

        body = QHBoxLayout()
        frames_column = QVBoxLayout()
        frames_header = QHBoxLayout()
        frames_header.addWidget(QLabel("动作帧", self))
        frames_header.addStretch(1)
        self.remove_frame_button = QPushButton("删除选中帧", self)
        self.remove_frame_button.clicked.connect(self._remove_selected_frame)
        frames_header.addWidget(self.remove_frame_button)
        frames_column.addLayout(frames_header)
        self.frame_list = QListWidget(self)
        self.frame_list.setObjectName("imageActionFrameList")
        self.frame_list.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.frame_list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.frame_list.model().rowsMoved.connect(self._sync_draft_from_list)
        frames_column.addWidget(self.frame_list, 1)
        timing_form = QFormLayout()
        self.fps_input = QDoubleSpinBox(self)
        self.fps_input.setRange(0.5, 60.0)
        self.fps_input.setDecimals(1)
        self.fps_input.setSingleStep(0.5)
        self.fps_input.valueChanged.connect(self._fps_changed)
        timing_form.addRow("播放速度", self.fps_input)
        self.total_duration_input = QSpinBox(self)
        self.total_duration_input.setRange(50, 600_000)
        self.total_duration_input.setSuffix(" ms")
        self.total_duration_input.valueChanged.connect(self._duration_changed)
        timing_form.addRow("总时长", self.total_duration_input)
        frames_column.addLayout(timing_form)
        self.fit_oversized_checkbox = QCheckBox("等比缩小超出画布的图片", self)
        self.fit_oversized_checkbox.toggled.connect(self._rebuild_preview)
        self.fit_oversized_checkbox.hide()
        frames_column.addWidget(self.fit_oversized_checkbox)
        body.addLayout(frames_column, 2)

        current_column = QVBoxLayout()
        current_column.addWidget(QLabel("当前动作", self))
        self.current_preview = AnimationPreviewWidget(self)
        self.current_preview.preview_label.setMinimumSize(180, 220)
        current_column.addWidget(self.current_preview, 1)
        body.addLayout(current_column, 2)

        preview_column = QVBoxLayout()
        preview_column.addWidget(QLabel("新动作预览", self))
        self.preview = AnimationPreviewWidget(self)
        self.preview.preview_label.setMinimumSize(180, 220)
        preview_column.addWidget(self.preview, 1)
        body.addLayout(preview_column, 2)
        root.addLayout(body, 1)

        self.status_label = QLabel("请先选择动作并添加图片。", self)
        self.status_label.setObjectName("mutedLabel")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

        self._slot_changed()

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
        return resolve_slot(package, slot).action_name if package is not None and slot is not None else None

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
            fit_oversized=self.fit_oversized(),
            entrance_direction=self.entrance_direction(),
        )

    def clear_after_success(self, message: str) -> None:
        self._draft = None
        self._preview_pixmaps = ()
        self.frame_list.clear()
        self.preview.set_frames(())
        self.fit_oversized_checkbox.setChecked(False)
        self.fit_oversized_checkbox.hide()
        self.status_label.setText(message)
        self.draft_changed.emit()

    def finish_failure(self, message: str) -> None:
        self.status_label.setText(message)

    def refresh_packages(self, packages: Sequence[PetPackage], current_pet_id: str) -> None:
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
        previous_category: str | None = None
        for slot in action_slots():
            if slot.category != previous_category:
                self.slot_combo.addItem(slot.category, None)
                model_item = self.slot_combo.model().item(self.slot_combo.count() - 1)
                if model_item is not None:
                    model_item.setEnabled(False)
                previous_category = slot.category
            self.slot_combo.addItem(slot.label, slot.key)
        first_slot = next((index for index in range(self.slot_combo.count()) if isinstance(self.slot_combo.itemData(index), str)), -1)
        self.slot_combo.setCurrentIndex(first_slot)

    def _set_draft(self, draft: ImageActionDraft) -> None:
        self._draft = draft
        self._populate_frame_list()
        self._update_fit_visibility()
        self._sync_total_from_fps()
        self.status_label.setText(f"已读取 {len(draft.frames)} 帧，可调整顺序和播放速度。")
        self._rebuild_preview()
        self.draft_changed.emit()

    def _populate_frame_list(self) -> None:
        self.frame_list.clear()
        if self._draft is None:
            return
        for index, frame in enumerate(self._draft.frames, start=1):
            item = QListWidgetItem(f"{index:03d}  {frame.path.name}  ·  {frame.width}×{frame.height}")
            item.setData(Qt.ItemDataRole.UserRole, frame.path)
            pixmap = QPixmap(str(frame.path))
            if not pixmap.isNull():
                item.setIcon(QIcon(pixmap.scaled(48, 48, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)))
            self.frame_list.addItem(item)

    def _sync_draft_from_list(self, *_args: object) -> None:
        if self._draft is None or self.frame_list.count() != len(self._draft.frames):
            return
        paths = tuple(
            Path(self.frame_list.item(index).data(Qt.ItemDataRole.UserRole))
            for index in range(self.frame_list.count())
        )
        self._draft = self._draft.reordered(paths)
        self._populate_frame_list()
        self._rebuild_preview()
        self.draft_changed.emit()

    def _remove_selected_frame(self) -> None:
        if self._draft is None or self.frame_list.currentItem() is None:
            return
        try:
            self._draft = self._draft.without(Path(self.frame_list.currentItem().data(Qt.ItemDataRole.UserRole)))
        except ImageActionSourceError as error:
            self.status_label.setText(str(error))
            return
        self._populate_frame_list()
        self._sync_total_from_fps()
        self._rebuild_preview()
        self.draft_changed.emit()

    def _slot_changed(self, *_args: object) -> None:
        slot = self.selected_slot()
        if slot is None:
            return
        with QSignalBlocker(self.fps_input):
            self.fps_input.setValue(slot.fps)
        self._update_current_preview()
        self._update_fullscreen_controls()
        self._update_fit_visibility()
        self._sync_total_from_fps()
        self._rebuild_preview()
        self.draft_changed.emit()

    def _target_changed(self, *_args: object) -> None:
        current_id = self.target_combo.currentData()
        changed = self._last_target_id is not None and current_id != self._last_target_id
        if changed:
            self.fit_oversized_checkbox.setChecked(False)
        self._last_target_id = current_id
        self._update_current_preview()
        self._update_fit_visibility()
        self._rebuild_preview()
        if changed and self._draft is not None:
            self.status_label.setText("目标宠物已更换，请重新确认动作预览和画布处理。")
        self.draft_changed.emit()

    def _update_current_preview(self) -> None:
        package = self.selected_package()
        action_name = self.action_name()
        definition = package.animations.get(action_name) if package is not None and action_name is not None else None
        if definition is None:
            self.current_preview.set_frames(())
            self.action_target_label.setText(f"将创建：{action_name or '—'}")
            return
        self.current_preview.set_frames(
            tuple(_scaled_preview_pixmap(path) for path in definition.frames),
            frame_durations_ms=definition.frame_durations_ms,
            fps=definition.fps,
        )
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
        self.preview.set_frames(self._preview_pixmaps, fps=self.fps())

    def _fps_changed(self, *_args: object) -> None:
        if self._syncing_duration:
            return
        self._sync_total_from_fps()
        self._refresh_preview_timing()
        self.draft_changed.emit()

    def _duration_changed(self, value: int) -> None:
        if self._syncing_duration or self._draft is None or not self._draft.frames:
            return
        self._syncing_duration = True
        try:
            self.fps_input.setValue(len(self._draft.frames) * 1000 / max(1, value))
        finally:
            self._syncing_duration = False
        self._sync_total_from_fps()
        self._refresh_preview_timing()
        self.draft_changed.emit()

    def _sync_total_from_fps(self) -> None:
        frame_count = len(self._draft.frames) if self._draft is not None else 1
        minimum = max(1, round(frame_count * 1000 / self.fps_input.maximum()))
        maximum = max(minimum, round(frame_count * 1000 / self.fps_input.minimum()))
        duration = round(frame_count * 1000 / max(0.5, self.fps()))
        self._syncing_duration = True
        try:
            with QSignalBlocker(self.total_duration_input):
                self.total_duration_input.setRange(minimum, maximum)
                self.total_duration_input.setValue(duration)
        finally:
            self._syncing_duration = False

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


__all__ = ["ImageActionImportContent", "ImageSourceDropZone"]
