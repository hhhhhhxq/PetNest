"""动作时间编辑对话框的兼容外壳。

实际的动作表、时间线、逐帧编辑和预览都由
:class:`~petnest.ui.animation_timing_editor.AnimationTimingEditor` 提供；此
类只保留旧调用方需要的 QDialog 外壳、按钮和代理属性。
"""

from __future__ import annotations

from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from petnest.models.pet_package import PetPackage
from petnest.ui.animation_preview_widget import CheckerboardLabel
from petnest.ui.animation_timing_editor import (
    AnimationTimingEditor,
    _mode_label,
    _scaled_timeline,
    _source_durations,
)
from petnest.ui.theme import dialog_stylesheet


class AnimationEditorDialog(QDialog):
    """保持旧 ``exec()``/保存按钮行为的动画时间编辑对话框。"""

    def __init__(self, package: PetPackage, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("animationEditorDialog")
        self.setWindowTitle(f"编辑动画时长 — {package.name}")
        self.resize(1280, 780)
        self.setMinimumSize(1080, 700)
        self.setStyleSheet(dialog_stylesheet())
        self._package = package

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(0)
        window_shell = QFrame(self)
        window_shell.setObjectName("windowShell")
        shell_layout = QVBoxLayout(window_shell)
        shell_layout.setContentsMargins(18, 18, 18, 16)
        shell_layout.setSpacing(14)

        header = QFrame(window_shell)
        header.setObjectName("headerBar")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(18, 13, 18, 13)
        title_column = QVBoxLayout()
        title_column.setSpacing(1)
        title = QLabel("编辑动画时长", header)
        title.setObjectName("pageTitle")
        title_column.addWidget(title)
        subtitle = QLabel("调整动作节奏 · 保存后自动重载当前宠物", header)
        subtitle.setObjectName("mutedLabel")
        title_column.addWidget(subtitle)
        header_layout.addLayout(title_column)
        header_layout.addStretch(1)
        pet_label = QLabel(f"当前宠物 · {package.name}", header)
        pet_label.setObjectName("mutedLabel")
        header_layout.addWidget(pet_label)
        header_layout.addSpacing(18)
        header_layout.addWidget(QLabel("×", header))
        shell_layout.addWidget(header)

        self.editor = AnimationTimingEditor(package, window_shell)
        shell_layout.addWidget(self.editor, 1)

        self.apply_hint_label = QLabel("时长会随宠物文件夹一起分享。", window_shell)
        self.apply_hint_label.setObjectName("mutedLabel")
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save,
            window_shell,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("保存并重载")
        buttons.button(QDialogButtonBox.StandardButton.Save).setObjectName("primaryButton")
        footer = QHBoxLayout()
        footer.addWidget(self.apply_hint_label)
        footer.addStretch(1)
        footer.addWidget(buttons)
        shell_layout.addLayout(footer)
        root.addWidget(window_shell)

        # 旧调用方公开的控件属性全部指向同一份内容组件。
        for name in (
            "action_table",
            "action_card",
            "editor_card",
            "preview_card",
            "frame_list",
            "duration_table",
            "total_radio",
            "per_frame_radio",
            "total_duration_spin",
            "total_timeline",
            "total_timeline_layout",
            "total_timeline_heading",
            "total_timeline_hint",
            "base_duration_label",
            "mode_group",
            "mode_status_label",
            "mode_explanation_card",
            "mode_explanation_title",
            "mode_explanation_label",
            "editor_heading_label",
            "editor_description_label",
            "preview",
            "preview_label",
            "preview_frame_label",
            "preview_timer",
            "preview_play_button",
        ):
            setattr(self, name, getattr(self.editor, name))

    @property
    def preview_frame_index(self) -> int:
        """实时委托给内容组件，避免复制一个过期索引。"""

        return self.editor.preview_frame_index

    @preview_frame_index.setter
    def preview_frame_index(self, value: int) -> None:
        self.editor.preview_frame_index = value

    @property
    def _highlighted_frame_index(self) -> int | None:
        return self.editor._highlighted_frame_index

    def updated_frame_durations(self) -> dict[str, tuple[int, ...]]:
        return self.editor.updated_frame_durations()

    def is_dirty(self) -> bool:
        return self.editor.is_dirty()

    def mark_saved(self, package: PetPackage) -> None:
        self.editor.mark_saved(package)
        self._package = package

    def applied_summary(self) -> str:
        return self.editor.applied_summary()

    def restore_current_action(self) -> None:
        self.editor.restore_current_action()

    def stop_preview(self) -> None:
        self.editor.stop_preview()

    def _advance_preview(self) -> None:
        self.editor._advance_preview()

    def _render_preview(self) -> None:
        self.editor._render_preview()

    def _toggle_preview(self) -> None:
        self.editor._toggle_preview()

    def _select_preview_frame(self, item: object) -> None:
        self.editor._select_preview_frame(item)  # type: ignore[arg-type]

    def resizeEvent(self, event: object) -> None:  # noqa: N802 - Qt override signature.
        super().resizeEvent(event)  # type: ignore[arg-type]
        self._sync_responsive_preview()

    def _sync_responsive_preview(self) -> None:
        self.editor._sync_responsive_preview()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt override signature.
        self.editor._cleanup_preview()
        super().closeEvent(event)


__all__ = [
    "AnimationEditorDialog",
    "AnimationTimingEditor",
    "CheckerboardLabel",
    "_mode_label",
    "_scaled_timeline",
    "_source_durations",
]
