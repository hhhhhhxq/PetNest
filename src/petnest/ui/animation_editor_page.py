"""统一宠物与动作中心中的动作时长编辑页面。"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QStackedWidget,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from petnest.models.pet_package import PetPackage
from petnest.ui.animation_timing_editor import AnimationTimingEditor
from petnest.ui.exchange_page import ExchangePage


@dataclass(frozen=True, slots=True)
class AnimationSaveResult:
    """保存动作时长后的结果。"""

    success: bool
    message: str
    package: PetPackage | None = None


class AnimationEditorPage(ExchangePage):
    """把动作时长编辑器嵌入宠物与动作中心。"""

    def __init__(
        self,
        packages: Sequence[PetPackage],
        *,
        current_pet_id: str,
        save_timelines: Callable[[PetPackage, dict[str, tuple[int, ...]]], AnimationSaveResult],
        is_pet_locked: Callable[[str], bool] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("animationEditorPage")
        self._packages: tuple[PetPackage, ...] = tuple(packages)
        self._save_timelines = save_timelines
        self._is_pet_locked = is_pet_locked or (lambda _identifier: False)
        self._current_pet_id: str | None = None
        self._selection_guard = False
        self._status_text = "选择动作开始编辑"

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        selector_row = QHBoxLayout()
        selector_row.setSpacing(16)
        selector_copy = QVBoxLayout()
        selector_copy.setSpacing(4)
        title = QLabel("编辑动作时长", self)
        title.setObjectName("pageTitle")
        selector_copy.addWidget(title)
        subtitle = QLabel("调整每个动作的播放节奏，保存后立即应用到当前宠物。", self)
        subtitle.setObjectName("mutedLabel")
        selector_copy.addWidget(subtitle)
        selector_row.addLayout(selector_copy, 1)
        pet_row = QVBoxLayout()
        pet_row.setSpacing(4)
        pet_label = QLabel("当前宠物", self)
        pet_label.setObjectName("mutedLabel")
        pet_row.addWidget(pet_label)
        self.pet_combo = QComboBox(self)
        self.pet_combo.setObjectName("animationEditorPetCombo")
        self.pet_combo.setMinimumWidth(180)
        self.pet_combo.setMaximumWidth(260)
        self.pet_combo.currentIndexChanged.connect(self._on_pet_combo_changed)
        pet_row.addWidget(self.pet_combo)
        selector_row.addLayout(pet_row)
        root.addLayout(selector_row)

        self.editor_stack = QStackedWidget(self)
        self.editor_stack.setObjectName("animationEditorStack")
        self.editor_stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._empty_label = QLabel("暂无可编辑的宠物动作", self.editor_stack)
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setObjectName("mutedLabel")
        self.editor_stack.addWidget(self._empty_label)
        root.addWidget(self.editor_stack, 1)

        self.editor: AnimationTimingEditor | None = None
        self._rebuild_selector(current_pet_id)
        self._sync_footer()

    def current_package(self) -> PetPackage | None:
        """返回选择器当前对应的宠物包。"""

        if self._current_pet_id is None:
            return None
        return next(
            (package for package in self._packages if package.identifier == self._current_pet_id),
            None,
        )

    def set_current_pet(self, identifier: str) -> bool:
        """切换当前宠物；有未保存草稿时先请求离开。"""

        package = self._find_package(identifier)
        if package is None:
            return False
        if identifier == self._current_pet_id:
            return True
        if self._has_dirty_editor() and not self.request_leave():
            self._restore_combo_selection()
            return False
        self._activate_package(package)
        return True

    def refresh_packages(self, packages: Sequence[PetPackage], current_pet_id: str) -> bool:
        """刷新宠物列表并保留可保留的选择。"""

        if self._has_dirty_editor() and not self.request_leave():
            return False

        previous_id = self._current_pet_id
        self._packages = tuple(packages)
        desired_id = current_pet_id
        if self._find_package(desired_id) is None:
            desired_id = previous_id or ""
        if self._find_package(desired_id) is None and self._packages:
            desired_id = self._packages[0].identifier

        self._rebuild_selector(desired_id)
        return True

    def trigger_primary(self) -> None:
        """保存当前宠物的动作时长草稿。"""

        package = self.current_package()
        editor = self.editor
        if package is None or editor is None or not editor.is_dirty():
            return
        try:
            if self._is_pet_locked(package.identifier):
                self._status_text = "下班提醒显示中，请先结束提醒。"
                self._sync_footer()
                return
        except Exception as error:  # pragma: no cover - defensive callback boundary.
            self._status_text = f"保存失败：{error}"
            self._sync_footer()
            return

        timelines = editor.updated_frame_durations()
        try:
            result = self._save_timelines(package, timelines)
        except Exception as error:  # pragma: no cover - defensive callback boundary.
            self._status_text = f"保存失败：{error}"
            self._sync_footer()
            return
        if not isinstance(result, AnimationSaveResult):
            result = AnimationSaveResult(bool(getattr(result, "success", False)), str(result))
        if not result.success:
            self._status_text = result.message
            self._sync_footer()
            return

        saved_package = result.package or _package_with_timelines(package, timelines)
        self._replace_package(saved_package)
        self._status_text = result.message
        editor.mark_saved(saved_package)
        self._sync_footer()

    def trigger_secondary(self) -> None:
        """恢复当前选中的动作到保存前的时长。"""

        if self.editor is None:
            return
        self.editor.restore_current_action()
        self._status_text = "已恢复当前动作"
        self._sync_footer()

    def request_leave(self) -> bool:
        """在离开页面前处理未保存草稿。"""

        if not self._has_dirty_editor():
            return True
        answer = QMessageBox.question(
            self,
            "保存动作修改？",
            "当前动作时长有未保存修改，要保存后再离开吗？",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Yes,
        )
        if answer == QMessageBox.StandardButton.Cancel:
            return False
        if answer == QMessageBox.StandardButton.Yes:
            self.trigger_primary()
            return not self._has_dirty_editor()

        self._discard_editor_draft()
        return True

    def deactivate(self) -> None:
        """页面切走时停止动作预览计时器。"""

        if self.editor is not None:
            self.editor.stop_preview()

    def _find_package(self, identifier: str) -> PetPackage | None:
        return next(
            (package for package in self._packages if package.identifier == identifier),
            None,
        )

    def _has_dirty_editor(self) -> bool:
        return self.editor is not None and self.editor.is_dirty()

    def _rebuild_selector(self, desired_id: str) -> None:
        with QSignalBlocker(self.pet_combo):
            self.pet_combo.clear()
            for package in self._packages:
                self.pet_combo.addItem(package.name, package.identifier)
            index = self.pet_combo.findData(desired_id)
            if index < 0 and self.pet_combo.count():
                index = 0
            self.pet_combo.setCurrentIndex(index)
        package = self._find_package(str(self.pet_combo.currentData())) if self.pet_combo.count() else None
        if package is None:
            self._clear_editor()
        else:
            self._activate_package(package)

    def _activate_package(self, package: PetPackage) -> None:
        with QSignalBlocker(self.pet_combo):
            index = self.pet_combo.findData(package.identifier)
            if index >= 0:
                self.pet_combo.setCurrentIndex(index)
        self._clear_editor()
        self._current_pet_id = package.identifier
        editor = AnimationTimingEditor(package, self.editor_stack)
        editor.dirty_changed.connect(self._on_editor_dirty_changed)
        self.editor = editor
        self.editor_stack.addWidget(editor)
        self.editor_stack.setCurrentWidget(editor)
        self._status_text = "选择动作开始编辑"
        self._sync_footer()

    def _clear_editor(self) -> None:
        old_editor = self.editor
        if old_editor is None:
            self.editor_stack.setCurrentWidget(self._empty_label)
            return
        old_editor.stop_preview()
        self.editor_stack.removeWidget(old_editor)
        old_editor.deleteLater()
        self.editor = None
        self.editor_stack.setCurrentWidget(self._empty_label)

    def _replace_package(self, package: PetPackage) -> None:
        self._packages = tuple(
            package if item.identifier == package.identifier else item for item in self._packages
        )
        self._current_pet_id = package.identifier
        with QSignalBlocker(self.pet_combo):
            index = self.pet_combo.findData(package.identifier)
            if index >= 0:
                self.pet_combo.setItemText(index, package.name)

    def _discard_editor_draft(self) -> None:
        package = self.current_package()
        if package is None:
            return
        self._activate_package(package)

    def _restore_combo_selection(self) -> None:
        if self._current_pet_id is None:
            return
        with QSignalBlocker(self.pet_combo):
            index = self.pet_combo.findData(self._current_pet_id)
            if index >= 0:
                self.pet_combo.setCurrentIndex(index)

    def _on_pet_combo_changed(self, index: int) -> None:
        if self._selection_guard or index < 0:
            return
        identifier = self.pet_combo.itemData(index)
        if identifier is None or str(identifier) == self._current_pet_id:
            return
        if not self.set_current_pet(str(identifier)):
            self._restore_combo_selection()

    def _on_editor_dirty_changed(self, dirty: bool) -> None:
        if dirty:
            self._status_text = "有未保存的修改"
        elif self._status_text == "有未保存的修改":
            self._status_text = "选择动作开始编辑"
        self._sync_footer()

    def _sync_footer(self) -> None:
        dirty = self._has_dirty_editor()
        self.set_footer(
            status=self._status_text,
            primary_text="保存并重载",
            primary_enabled=dirty,
            secondary_text="恢复当前动作",
            secondary_enabled=self.editor is not None,
        )


__all__ = ["AnimationEditorPage", "AnimationSaveResult"]


def _package_with_timelines(
    package: PetPackage,
    timelines: dict[str, tuple[int, ...]],
) -> PetPackage:
    """在保存回调未返回重载包时，把已保存时长折叠进当前包快照。"""

    animations = {
        name: replace(definition, frame_durations_ms=tuple(timelines[name]))
        if name in timelines
        else definition
        for name, definition in package.animations.items()
    }
    return replace(package, animations=animations)
