"""宠物与动作交换中心的统一窗口。"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from petnest.core.pet_store_cache import PetStoreCache
from petnest.core.pet_store_service import PetStoreService
from petnest.core.pet_store_state import PetStoreStateStore
from petnest.models.pet_package import PetPackage
from petnest.ui.action_export_page import ActionExportPage
from petnest.ui.action_import_page import ActionImportPage
from petnest.ui.animation_editor_page import AnimationEditorPage, AnimationSaveResult
from petnest.ui.exchange_page import ExchangePage
from petnest.ui.pet_import_page import PetImportPage
from petnest.ui.pet_store_page import PetStorePage
from petnest.ui.theme import dialog_stylesheet


class PetActionExchangeDialog(QDialog):
    """把宠物导入、动作导入、时长编辑和动作导出放在一个窗口。"""

    pet_installed = Signal(str, object)
    store_pet_installed = Signal(str, object)
    actions_installed = Signal(str, object)

    _PAGE_LABELS = ("导入宠物", "宠物商店", "导入动作", "编辑动作", "导出动作")
    _PAGE_SUBTITLES = {
        "导入宠物": "自动识别 PNG、ZIP 或文件夹，并在确认前预览导入内容",
        "宠物商店": "浏览官方精选宠物，领养新伙伴或更新已安装内容",
        "导入动作": "从资源包提取动作，或用图片制作可触发动作",
        "编辑动作": "调整动作节奏，保存后立即应用到当前宠物",
        "导出动作": "预览并选择动作，生成可分享的 ZIP 包",
    }

    def __init__(
        self,
        packages: Sequence[PetPackage] | PetPackage,
        pets_root: Path,
        *,
        current_pet_id: str | None = None,
        save_animation_timelines: Callable[
            [PetPackage, dict[str, tuple[int, ...]]], AnimationSaveResult
        ] | None = None,
        is_pet_locked: Callable[[str], bool] | None = None,
        pet_store_service: PetStoreService | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("petActionExchangeDialog")
        self.setWindowTitle("宠物与动作")
        self.resize(1220, 760)
        self.setMinimumSize(1180, 680)
        self.setStyleSheet(dialog_stylesheet())
        self._packages = _normalise_packages(packages)
        self._pets_root = Path(pets_root)
        self._is_pet_locked = is_pet_locked or (lambda _identifier: False)
        if pet_store_service is None:
            store_root = self._pets_root.parent / "pet-store"
            store_cache = PetStoreCache(store_root, "https://invalid.local")
            pet_store_service = PetStoreService(
                store_cache,
                PetStoreStateStore(store_root / "state.json"),
                self._pets_root,
                is_pet_locked=self._is_pet_locked,
            )
        self._active_index = 0
        self._closing = False
        desired_id = current_pet_id or (self._packages[0].identifier if self._packages else "")
        save_callback = save_animation_timelines or _default_save_animation_timelines

        root = QVBoxLayout(self)
        self.window_shell = QFrame(self)
        self.window_shell.setObjectName("windowShell")
        shell_layout = QVBoxLayout(self.window_shell)
        shell_layout.setContentsMargins(18, 18, 18, 16)

        header = QHBoxLayout()
        self.page_title = QLabel(self.window_shell)
        self.page_title.setObjectName("pageTitle")
        header.addWidget(self.page_title)
        header.addStretch(1)
        self.page_subtitle = QLabel(self.window_shell)
        self.page_subtitle.setObjectName("mutedLabel")
        self.page_subtitle.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        header.addWidget(self.page_subtitle)
        shell_layout.addLayout(header)

        body = QHBoxLayout()
        self.navigation = QListWidget(self.window_shell)
        self.navigation.setObjectName("settingsNavigation")
        self.navigation.setFixedWidth(150)
        for label in self._PAGE_LABELS:
            self.navigation.addItem(QListWidgetItem(label, self.navigation))
        body.addWidget(self.navigation)

        self.stack = QStackedWidget(self.window_shell)
        self.pet_import_page = PetImportPage(
            self._packages,
            self._pets_root,
            is_pet_locked=self._is_pet_locked,
            parent=self.stack,
        )
        self.pet_store_page = PetStorePage(pet_store_service, self.stack)
        self.action_import_page = ActionImportPage(
            self._packages,
            self._pets_root,
            current_pet_id=desired_id,
            is_pet_locked=self._is_pet_locked,
            parent=self.stack,
        )
        self.animation_editor_page = AnimationEditorPage(
            self._packages,
            current_pet_id=desired_id,
            save_timelines=save_callback,
            is_pet_locked=self._is_pet_locked,
            parent=self.stack,
        )
        self.action_export_page = ActionExportPage(
            self._packages,
            self.stack,
            current_pet_id=desired_id,
        )
        self._pages: tuple[ExchangePage, ...] = (
            self.pet_import_page,
            self.pet_store_page,
            self.action_import_page,
            self.animation_editor_page,
            self.action_export_page,
        )
        for page in self._pages:
            self._hide_embedded_header(page)
            self.stack.addWidget(page)
            page.footer_changed.connect(self._sync_footer)
        body.addWidget(self.stack, 1)
        shell_layout.addLayout(body, 1)

        footer = QHBoxLayout()
        self.footer_status_label = QLabel(self.window_shell)
        self.footer_status_label.setObjectName("mutedLabel")
        self.footer_status_label.setWordWrap(True)
        footer.addWidget(self.footer_status_label, 1)
        self.secondary_button = QPushButton(self.window_shell)
        self.secondary_button.setObjectName("secondaryButton")
        self.secondary_button.clicked.connect(self._trigger_secondary)
        footer.addWidget(self.secondary_button)
        self.primary_button = QPushButton(self.window_shell)
        self.primary_button.setObjectName("primaryButton")
        self.primary_button.clicked.connect(self._trigger_primary)
        footer.addWidget(self.primary_button)
        shell_layout.addLayout(footer)
        root.addWidget(self.window_shell)

        self.navigation.currentRowChanged.connect(self._on_navigation_changed)
        self.navigation.setCurrentRow(0)
        self._sync_page_header()
        self._sync_footer()
        self.pet_import_page.pet_installed.connect(self.pet_installed.emit)
        self.pet_store_page.pet_install_ready.connect(self.store_pet_installed.emit)
        self.action_import_page.actions_installed.connect(self.actions_installed.emit)

    def page_names(self) -> list[str]:
        return list(self._PAGE_LABELS)

    def page_by_title(self, title: str) -> ExchangePage:
        try:
            return self._pages[self._PAGE_LABELS.index(title)]
        except ValueError as error:
            raise ValueError(f"未知交换页面：{title}") from error

    def current_page(self) -> ExchangePage:
        if 0 <= self._active_index < len(self._pages):
            return self._pages[self._active_index]
        return self._pages[0]

    def current_page_name(self) -> str:
        return self._PAGE_LABELS[self._active_index] if 0 <= self._active_index < len(self._PAGE_LABELS) else ""

    def select_page(self, name: str) -> None:
        if name not in self._PAGE_LABELS:
            raise ValueError(f"未知交换页面：{name}")
        self.navigation.setCurrentRow(self._PAGE_LABELS.index(name))

    def refresh_packages(self, packages: Sequence[PetPackage], current_pet_id: str) -> bool:
        """Refresh every page atomically after all leave guards agree."""

        # Run every page guard before changing the dialog or any selector.  In
        # particular, AnimationEditorPage may show the save/discard/cancel
        # prompt; Cancel must leave all four pages on their previous packages.
        for page in self._pages:
            if not page.request_leave():
                return False

        next_packages = tuple(packages)
        self._packages = next_packages
        refresh_pet_import = getattr(self.pet_import_page, "refresh_packages", None)
        if callable(refresh_pet_import):
            refresh_pet_import(next_packages, current_pet_id)
        else:
            # PetImportPage predates the shared refresh protocol.  Updating
            # this source of truth keeps its existing ID/update checks correct
            # while it preserves whatever source draft is currently visible.
            self.pet_import_page._packages = next_packages
        self.pet_store_page.refresh_packages(next_packages, current_pet_id)
        self.action_import_page.refresh_packages(next_packages, current_pet_id)
        self.animation_editor_page.refresh_packages(next_packages, current_pet_id)
        self.action_export_page.refresh_packages(next_packages, current_pet_id)
        return True

    def complete_action_install(self, message: str) -> None:
        """确认动作已被运行时采用，并清空本次导入来源。"""

        self.action_import_page.complete_install(message)

    def complete_store_install(self, message: str) -> None:
        """Confirm the runtime accepted a store install and persist its receipt."""

        self.pet_store_page.complete_install(message)

    def complete_store_install_failure(self, message: str) -> None:
        """Return the store page to an actionable state after rollback."""

        self.pet_store_page.complete_install_failure(message)

    def complete_action_install_failure(self, message: str) -> None:
        """结束处理状态但保留来源，让用户可以直接重试。"""

        self.action_import_page.complete_install_failure(message)

    def _on_navigation_changed(self, index: int) -> None:
        if index < 0 or index == self._active_index or self._closing:
            return
        old_index = self._active_index
        old_page = self._pages[old_index]
        if not old_page.request_leave():
            with QSignalBlocker(self.navigation):
                self.navigation.setCurrentRow(old_index)
            return
        old_page.deactivate()
        self._active_index = index
        self.stack.setCurrentIndex(index)
        activate = getattr(self.current_page(), "activate", None)
        if callable(activate):
            activate()
        self._sync_page_header()
        self._sync_footer()

    def _sync_page_header(self) -> None:
        name = self.current_page_name()
        self.page_title.setText(name)
        self.page_subtitle.setText(self._PAGE_SUBTITLES.get(name, ""))

    def _sync_footer(self) -> None:
        state = self.current_page().footer_state()
        self.footer_status_label.setText(state.status)
        self.primary_button.setText(state.primary_text)
        self.primary_button.setEnabled(state.primary_enabled)
        self.secondary_button.setText(state.secondary_text or "")
        self.secondary_button.setVisible(state.secondary_text is not None)
        self.secondary_button.setEnabled(state.secondary_enabled)

    def _trigger_primary(self) -> None:
        self.current_page().trigger_primary()

    def _trigger_secondary(self) -> None:
        if self.secondary_button.isVisible():
            self.current_page().trigger_secondary()

    def _can_close(self) -> bool:
        if self._closing:
            return True
        for page in self._pages:
            if not page.request_close():
                return False
        self._closing = True
        for page in self._pages:
            page.deactivate()
        self.action_import_page.close_pack()
        return True

    def reject(self) -> None:  # noqa: N802 - Qt override
        if self._can_close():
            super().reject()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt override
        if self._can_close():
            event.accept()
            super().closeEvent(event)
        else:
            event.ignore()

    @staticmethod
    def _hide_embedded_header(page: QWidget) -> None:
        for label in page.findChildren(QLabel, "pageTitle"):
            label.hide()


def _normalise_packages(packages: Sequence[PetPackage] | PetPackage) -> tuple[PetPackage, ...]:
    if isinstance(packages, PetPackage):
        return (packages,)
    return tuple(packages)


def _default_save_animation_timelines(
    _package: PetPackage,
    _timelines: dict[str, tuple[int, ...]],
) -> AnimationSaveResult:
    """Compatibility fallback used by old callers before app save wiring."""

    return AnimationSaveResult(True, "已保存并重载")


__all__ = ["PetActionExchangeDialog"]
