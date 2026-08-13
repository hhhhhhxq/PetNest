"""PetNest 应用装配：将纯核心、Qt 窗口和本地事件服务连接起来。"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import replace
from datetime import UTC, datetime
import logging
import os
from pathlib import Path
from queue import Empty, Queue
import re
import sys
import subprocess
import tempfile
from threading import Thread
from time import monotonic
import uuid

from PySide6.QtCore import QPoint, QTimer, QUrl, Qt
from PySide6.QtGui import QAction, QColor, QCursor, QDesktopServices, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication, QMenu, QMenuBar, QMessageBox

from petnest.core.animation_action_synchronizer import AnimationActionSyncError, AnimationActionSynchronizer
from petnest import __version__
from petnest.core.app_update import (
    AppUpdateCheckResult,
    AppUpdateClient,
    AppUpdateCoordinator,
    AppUpdateError,
    AppUpdateInfo,
)
from petnest.core.cursor_style_catalog import CursorStyleCatalog
from petnest.core.codex_usage import (
    CodexAccountObservationStore,
    CodexDeviceUsageStore,
    CodexUsageClient,
    codex_account_observation_path,
    codex_device_usage_path,
)
from petnest.core.codex_usage_sync import CodexUsageSyncCoordinator
from petnest.core.event_bus import EventBus
from petnest.core.lan_service import LanInteractionService
from petnest.core.lottie_effects import EffectCatalog
from petnest.core.mouse_follow import MouseFollowController
from petnest.core.package_loader import PackageLoader
from petnest.core.pet_library import default_user_pets_directory, prepare_pet_library
from petnest.core.remote_resource_cache import RemoteResourceCache
from petnest.core.remote_resource_update import (
    RemoteResourceApplyResult,
    RemoteResourceCheckResult,
    RemoteResourceUpdateCoordinator,
)
from petnest.core.remote_interaction_service import FirebaseRemoteInteractionService
from petnest.core.settings_manager import SettingsManager
from petnest.core.system_idle_monitor import SystemIdleMonitor
from petnest.events.external_event_server import ExternalEventServer
from petnest.logging_config import configure_logging
from petnest.core.device_identity import display_name_for
from petnest.models.event import PetEvent
from petnest.models.lan_interaction import ChatMessageKind, InteractionKind
from petnest.models.pet_package import PetPackage
from petnest.models.settings import AnimationOverride, Settings
from petnest.ui.animation_editor_dialog import AnimationEditorDialog
from petnest.ui.app_update_dialog import AppUpdateDialog
from petnest.ui.codex_usage_dialog import CodexUsageDialog
from petnest.platforms import PlatformEventAdapter, create_platform_adapter
from petnest.platforms.cursor import CursorController, create_cursor_controller
from petnest.ui.pet_window import PetWindow
from petnest.ui.settings_dialog import SettingsDialog
from petnest.ui.lan_interaction_dialog import LanInteractionDialog
from petnest.ui.spritesheet_import_dialog import SpriteSheetImportDialog
from petnest.ui.tray_icon import PetTrayIcon
from petnest.ui.work_countdown import WorkCountdownWindow

LOGGER = logging.getLogger(__name__)
REMOTE_RESOURCE_BASE_URL = "https://red-lake-ce5a.bbbbbiubiubiu.workers.dev"
REMOTE_RESOURCE_CHECK_INTERVAL_MS = 30 * 60 * 1000
REMOTE_RESOURCE_RESULT_POLL_INTERVAL_MS = 200
APP_UPDATE_RESULT_POLL_INTERVAL_MS = 200
APP_UPDATE_STARTUP_DELAY_MS = 2_500
APP_UPDATE_CHECK_INTERVAL_MS = 30 * 60 * 1000
APP_UPDATE_MANIFEST_URLS = {
    "win32": "https://github.com/hhhhhhxq/PetNest/releases/latest/download/app-update.json",
    "darwin": "https://github.com/hhhhhhxq/PetNest/releases/latest/download/app-update-macos.json",
}
APP_UPDATE_PLATFORMS = frozenset(APP_UPDATE_MANIFEST_URLS)
_CURSOR_STYLE_ROLES = (
    "arrow",
    "busy",
    "text",
    "move",
    "resize_horizontal",
    "resize_vertical",
    "resize_diag_1",
    "resize_diag_2",
)


def bundled_pets_directory() -> Path:
    """定位开发环境或 PyInstaller onedir 产物内的只读宠物素材。"""
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root is not None:
        return Path(frozen_root) / "pets"
    return Path(__file__).resolve().parents[2] / "pets"


def bundled_cursor_styles_directory() -> Path:
    """定位开发环境或 PyInstaller onedir 产物内的只读光标样式。"""
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root is not None:
        return Path(frozen_root) / "assets" / "cursors"
    return Path(__file__).resolve().parents[2] / "assets" / "cursors"


def bundled_resource_seed_root() -> Path:
    """定位安装包内可直接复用的默认资源根目录。"""
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root is not None:
        return Path(frozen_root)
    return Path(__file__).resolve().parents[2]


def effect_directories_for(
    *,
    pets_root: Path,
    resource_directory: Path | None = None,
    bundled_root: Path | None = None,
    application_root: Path | None = None,
) -> tuple[Path, ...]:
    """返回动效查找目录，优先用户目录，再回退到安装包资源。"""
    candidates: list[Path] = [pets_root.expanduser().parent / "effects"]
    if resource_directory is not None:
        candidates.append(resource_directory / "effects")
    if application_root is not None:
        candidates.append(application_root / "effects")
    if bundled_root is not None:
        candidates.append(bundled_root / "effects")
    roots: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        if resolved not in seen:
            seen.add(resolved)
            roots.append(resolved)
    return tuple(roots)


def resource_directory_for_cache(cache: RemoteResourceCache, *, verify_files: bool = True) -> Path | None:
    """Return the verified current resource root, or ``None`` for fallback."""
    if verify_files:
        try:
            cache.ensure_bundled_fallbacks()
        except (OSError, RuntimeError) as error:
            LOGGER.warning("无法补齐资源缓存内置回退：%s", error)
    return cache.verified_resource_directory(verify_files=verify_files)


class PetNest:
    """第一阶段桌宠运行时，负责有序启动、宠物切换和有序退出。"""

    def __init__(
        self,
        *,
        pets_root: Path | None = None,
        settings_manager: SettingsManager | None = None,
        platform_adapter: PlatformEventAdapter | None = None,
        cursor_controller: CursorController | None = None,
        enable_tray: bool = True,
    ) -> None:
        if QApplication.instance() is None:
            raise RuntimeError("创建 PetNest 前必须先创建 QApplication")
        self.settings_manager = settings_manager or SettingsManager()
        self.settings = self.settings_manager.load()
        if not self.settings.device_id:
            self.settings = replace(self.settings, device_id=uuid.uuid4().hex)
            self.settings_manager.save(self.settings)
        self.remote_resource_cache = RemoteResourceCache(
            self.settings_manager.path.parent / "remote-resources",
            REMOTE_RESOURCE_BASE_URL,
            seed_root=bundled_resource_seed_root(),
        )
        self.remote_resource_update = RemoteResourceUpdateCoordinator(
            self.remote_resource_cache,
            self.remote_resource_cache.root / "state.json",
        )
        self._resource_results: Queue[tuple[str, bool, object]] = Queue()
        self._resource_worker: Thread | None = None
        self.app_update_client = AppUpdateClient(
            manifest_url=APP_UPDATE_MANIFEST_URLS.get(sys.platform, APP_UPDATE_MANIFEST_URLS["win32"]),
            current_version=__version__,
            platform_name=sys.platform,
        )
        self.app_update_coordinator = AppUpdateCoordinator(
            self.app_update_client,
            self.settings_manager.path.parent / "app-update-state.json",
        )
        self._app_update_results: Queue[tuple[str, object]] = Queue()
        self._app_update_worker: Thread | None = None
        self._app_update_dialog: AppUpdateDialog | None = None
        self._settings_center_dialog: SettingsDialog | None = None
        self._codex_usage_dialog: CodexUsageDialog | None = None
        self._codex_usage_history_path = self.settings_manager.path.parent / "codex-usage-history.json"
        self._codex_account_observations = CodexAccountObservationStore(
            codex_account_observation_path(self._codex_usage_history_path)
        )
        self._codex_client_factory = lambda: CodexUsageClient(
            observation_store=self._codex_account_observations
        )
        self._pending_app_update: AppUpdateInfo | None = None
        self.resource_directory = resource_directory_for_cache(self.remote_resource_cache)
        cursor_root = (
            self.resource_directory / "cursors"
            if self.resource_directory is not None and (self.resource_directory / "cursors").is_dir()
            else bundled_cursor_styles_directory()
        )
        self.cursor_catalog = CursorStyleCatalog(cursor_root)
        self.cursor_controller = cursor_controller or create_cursor_controller()
        self._active_cursor_roles: set[str] = set()
        self._recover_pending_cursor()
        if pets_root is not None:
            self.pets_root = pets_root
        elif getattr(sys, "frozen", False):
            requested_root = Path(self.settings.pets_root) if self.settings.pets_root else default_user_pets_directory()
            self.pets_root = prepare_pet_library(requested_root, bundled_pets_directory())
        else:
            self.pets_root = bundled_pets_directory()
        self.loader = PackageLoader()
        self.action_synchronizer = AnimationActionSynchronizer()
        discovered_packages = self.loader.discover(self.pets_root)
        self._migrate_legacy_animation_overrides(discovered_packages)
        self.packages = self.loader.discover(self.pets_root)
        if not self.packages:
            raise RuntimeError(f"未找到可用宠物包：{self.pets_root}")
        self.package = self._select_package(self.settings.current_pet_id)
        self.event_bus = EventBus()
        countdown_root = self.resource_directory / "countdown" if self.resource_directory is not None else None
        self.window = PetWindow(
            self.package,
            position_saved=self._save_window_position,
            countdown_root=countdown_root,
        )
        self.lan_service = LanInteractionService(
            device_id=self.settings.device_id,
            display_name=display_name_for(self.settings),
            pet_name=self.package.name,
            parent=self.window,
        )
        self.lan_service.interaction_received.connect(self._handle_lan_interaction)
        self.lan_service.chat_message_received.connect(self._handle_lan_chat)
        self.lan_service.error.connect(lambda message: LOGGER.warning("%s", message))
        self.codex_usage_sync = CodexUsageSyncCoordinator(
            self.lan_service,
            CodexDeviceUsageStore(codex_device_usage_path(self._codex_usage_history_path)),
            device_label=lambda: display_name_for(self.settings),
            client_factory=self._codex_client_factory,
            parent=self.window,
        )
        self.codex_usage_sync.snapshots_changed.connect(self._codex_sync_snapshots_changed)
        self.remote_interaction_service = FirebaseRemoteInteractionService(
            display_name=display_name_for(self.settings),
            pet_name=self.package.name,
            config_directory=self.settings_manager.path.parent,
            parent=self.window,
        )
        self.remote_interaction_service.interaction_received.connect(self._handle_lan_interaction)
        self.remote_interaction_service.error.connect(lambda message: LOGGER.warning("%s", message))
        self.work_countdown = WorkCountdownWindow(self.window)
        self.pet_context_menu = QMenu(self.window)
        self.pet_context_menu.setObjectName("petContextMenu")
        self.pet_context_menu.setStyleSheet(_pet_context_menu_stylesheet(QApplication.palette()))
        self.context_header_action = QAction(self.pet_context_menu)
        self.context_header_action.setEnabled(False)
        self.pet_context_menu.addAction(self.context_header_action)
        self.pet_context_menu.addSeparator()
        self.zoom_out_action = self.pet_context_menu.addAction("－  缩小")
        self.zoom_in_action = self.pet_context_menu.addAction("＋  放大")
        self.reset_scale_action = self.pet_context_menu.addAction("↺  恢复默认大小")
        self.pet_context_menu.addSeparator()
        self.pause_context_action = QAction("Ⅱ  暂停动画", self.pet_context_menu)
        self.always_on_top_context_action = QAction("始终置顶", self.pet_context_menu)
        self.always_on_top_context_action.setCheckable(True)
        self.mouse_follow_context_action = QAction("跟随鼠标", self.pet_context_menu)
        self.mouse_follow_context_action.setCheckable(True)
        self.pet_context_menu.addAction(self.pause_context_action)
        self.pet_context_menu.addAction(self.always_on_top_context_action)
        self.pet_context_menu.addAction(self.mouse_follow_context_action)
        self.zoom_in_action.triggered.connect(lambda: self._adjust_context_scale(0.1))
        self.zoom_out_action.triggered.connect(lambda: self._adjust_context_scale(-0.1))
        self.reset_scale_action.triggered.connect(self._reset_context_scale)
        self.pause_context_action.triggered.connect(self._toggle_context_pause)
        self.always_on_top_context_action.triggered.connect(self._toggle_context_always_on_top)
        self.mouse_follow_context_action.triggered.connect(self._toggle_mouse_follow)
        self.pet_context_menu.aboutToShow.connect(self._sync_pet_context_menu)
        self.window.context_menu_requested.connect(self._show_pet_context_menu)
        self.window.countdown_clicked.connect(lambda: self._show_settings_center("countdown"))
        self._restore_window_settings()
        self.event_bus.subscribe(self.window.handle_pet_event)
        self.platform_adapter = platform_adapter or create_platform_adapter()
        self._system_idle_monitor = self._new_system_idle_monitor(self.settings)
        self.system_idle_timer = QTimer(self.window)
        self.system_idle_timer.setInterval(1_000)
        self.system_idle_timer.timeout.connect(self._check_system_idle)
        self.mouse_follow_controller = MouseFollowController()
        self.mouse_follow_timer = QTimer(self.window)
        self.mouse_follow_timer.setInterval(20)
        self.mouse_follow_timer.timeout.connect(self._tick_mouse_follow)
        self.resource_update_timer = QTimer(self.window)
        self.resource_update_timer.setInterval(REMOTE_RESOURCE_CHECK_INTERVAL_MS)
        self.resource_update_timer.timeout.connect(self._resource_timer_tick)
        self.resource_result_timer = QTimer(self.window)
        self.resource_result_timer.setInterval(REMOTE_RESOURCE_RESULT_POLL_INTERVAL_MS)
        self.resource_result_timer.timeout.connect(self._drain_resource_results)
        self.app_update_result_timer = QTimer(self.window)
        self.app_update_result_timer.setInterval(APP_UPDATE_RESULT_POLL_INTERVAL_MS)
        self.app_update_result_timer.timeout.connect(self._drain_app_update_results)
        self.app_update_check_timer = QTimer(self.window)
        self.app_update_check_timer.setInterval(APP_UPDATE_CHECK_INTERVAL_MS)
        self.app_update_check_timer.timeout.connect(self._schedule_app_update_check)
        self.external_server: ExternalEventServer | None = None
        self._shutdown = False
        self.tray: PetTrayIcon | None = (
            PetTrayIcon(
                self.window,
                pet_names={item.identifier: item.name for item in self.packages},
                current_pet_name=self.package.name,
                on_switch=self.switch_pet,
                on_reload=self.reload_current_pet,
                on_import=self.show_spritesheet_import_dialog,
                on_open_pets_folder=self.open_pets_folder,
                on_refresh_pets=self.refresh_pets,
                on_edit_animations=self.show_animation_editor_dialog,
                on_settings=self.show_settings_dialog,
                on_codex_usage=self.show_codex_usage_dialog,
                on_cursor_styles=self.show_cursor_style_dialog,
                on_resource_update=self._handle_resource_update_action,
                on_lan_interactions=self.show_lan_interaction_dialog,
                on_toggle_always_on_top=self._toggle_context_always_on_top,
                on_toggle_mouse_follow=self._toggle_mouse_follow,
                on_visibility_changed=self._set_pet_visibility,
                on_toggle_pause=self._toggle_tray_pause,
                on_quit=self.shutdown,
            )
            if enable_tray
            else None
        )
        if self.tray is not None:
            self.tray.set_always_on_top_enabled(self.settings.always_on_top)
        self.menu_bar: QMenuBar | None = None
        if sys.platform == "darwin" and self.tray is not None:
            # 桌宠没有普通主窗口；显式提供原生全局菜单，避免所有功能只能
            # 从状态栏图标进入。托盘菜单与顶部“桌宠”菜单共享同一组动作。
            self.tray.menu.setTitle("Menu")
            self.menu_bar = QMenuBar()
            self.menu_bar.setNativeMenuBar(True)
            self.menu_bar.addMenu(self.tray.menu)

    @staticmethod
    def check_installation() -> int:
        """执行无需 GUI 窗口的安装完整性检查，供 CI 与 ``--check`` 使用。"""
        try:
            packages = PackageLoader().discover(bundled_pets_directory())
            if not packages:
                raise RuntimeError("未发现任何可用宠物包")
        except (OSError, RuntimeError, ValueError) as error:
            print(f"PetNest 检查失败：{error}", file=sys.stderr)
            return 1
        print(f"PetNest 检查通过：发现 {len(packages)} 个宠物包")
        return 0

    def start(self) -> None:
        """显示窗口并按设置启动可选本地事件服务。"""
        self.platform_adapter.start()
        if self.settings.external_event_server_enabled:
            self._start_external_server()
        self._configure_system_idle_timer()
        self._configure_lan_service()
        self._configure_remote_interaction_service()
        if self.tray is not None:
            self.tray.show()
        self.window.show()
        self._configure_work_countdown()
        self._configure_mouse_follow()
        self._configure_cursor_style(previous_pending=self.settings.cursor_restore_pending)
        self.settings_manager.save(self.settings)
        if self.tray is not None:
            self.tray.set_resource_update_available(self.remote_resource_update.update_available)
        self.resource_result_timer.start()
        self.resource_update_timer.start()
        if sys.platform in APP_UPDATE_PLATFORMS:
            self.app_update_result_timer.start()
            self.app_update_check_timer.start()
            QTimer.singleShot(APP_UPDATE_STARTUP_DELAY_MS, self._schedule_app_update_check)
        self._schedule_resource_check(force=False)
        LOGGER.info("PetNest 已启动，宠物包：%s", self.package.identifier)

    def reveal(self) -> None:
        """供第二次启动请求在主显示器中央找回宠物。"""
        screen = (
            QGuiApplication.primaryScreen()
            or QGuiApplication.screenAt(QCursor.pos())
            or self.window.screen()
        )
        target = self.window.pos()
        if screen is not None:
            available = screen.availableGeometry()
            target = QPoint(
                available.center().x() - self.window.width() // 2,
                available.center().y() - self.window.height() // 2,
            )
        self.window.setWindowState(self.window.windowState() & ~Qt.WindowState.WindowMinimized)
        if self.tray is not None:
            self.tray.show()
        self.window.show()
        self._set_pet_visibility(True)
        self.window.move(self.window.clamp_position(target))
        self._save_window_position(self.window.pos())
        self.window.raise_()
        self.window.activateWindow()
        LOGGER.info("已响应新的启动请求并显示现有宠物")

    def switch_pet(self, identifier: str) -> bool:
        """无重启切换已验证宠物，保留窗口位置；失败不改变当前宠物。"""
        candidate = next((item for item in self.packages if item.identifier == identifier), None)
        if candidate is None:
            return False
        position = self.window.pos()
        try:
            self.window.load_package(candidate)
            self.window.move(self.window.clamp_position(position))
        except (OSError, ValueError, RuntimeError):
            LOGGER.exception("切换宠物包失败：%s", identifier)
            return False
        self.package = candidate
        self.settings = replace(self.settings, current_pet_id=candidate.identifier, scale=candidate.display.default_scale)
        self.settings_manager.save(self.settings)
        self.lan_service.update_identity(display_name=display_name_for(self.settings), pet_name=self.package.name)
        self.remote_interaction_service.update_identity(
            display_name=display_name_for(self.settings),
            pet_name=self.package.name,
        )
        if self.tray is not None:
            self.tray.set_current_pet_name(self.package.name)
        return True

    def reload_current_pet(self) -> bool:
        """重新从磁盘校验并载入当前包，失败时保留现有资源。"""
        previous = self.package
        position = self.window.pos()
        previous_action = self.window.current_action
        previous_paused = self.window.player.is_paused
        window_load_attempted = False
        sync_result = None
        original_config: bytes | None = None
        try:
            original_config = self.action_synchronizer.snapshot_config_bytes(previous.root)
            sync_result = self.action_synchronizer.sync(previous.root)
            reloaded = self.loader.load(previous.root)
            window_load_attempted = True
            self.window.load_package(reloaded)
            self.window.move(self.window.clamp_position(position))
        except (OSError, ValueError, RuntimeError):
            if sync_result is not None and sync_result.changed and original_config is not None:
                try:
                    self.action_synchronizer.restore_config_bytes(previous.root, original_config)
                except (OSError, ValueError, RuntimeError):
                    LOGGER.exception("重新加载失败后恢复宠物包配置失败：%s", previous.identifier)
            if window_load_attempted:
                try:
                    self.window.load_package(previous)
                    self.window.restore_runtime_state(previous_action, paused=previous_paused)
                    self.window.move(self.window.clamp_position(position))
                except (OSError, ValueError, RuntimeError):
                    LOGGER.exception("重新加载失败后恢复旧宠物包失败：%s", previous.identifier)
            LOGGER.exception("重新加载宠物包失败：%s", previous.identifier)
            return False
        self.package = reloaded
        self.packages = [reloaded if item.identifier == reloaded.identifier else item for item in self.packages]
        if self.tray is not None:
            self.tray.set_current_pet_name(self.package.name)
        if sync_result.added and self.tray is not None:
            summary = "、".join(f"{action.name}（{action.frame_count} 帧）" for action in sync_result.added)
            self.tray.showMessage("PetNest", f"已自动登记：{summary}")
        elif sync_result.reconciled and self.tray is not None:
            summary = "、".join(f"{timeline.name}（{timeline.frame_count} 帧）" for timeline in sync_result.reconciled)
            self.tray.showMessage("PetNest", f"已同步逐帧时长：{summary}")
        return True

    def apply_settings(self, settings: Settings) -> None:
        """立即应用可安全即时修改的设置，并持久化其非敏感值。"""
        idle_configuration_changed = (
            settings.system_idle_enabled != self.settings.system_idle_enabled
            or settings.system_bored_seconds != self.settings.system_bored_seconds
            or settings.system_sleep_seconds != self.settings.system_sleep_seconds
        )
        previous_cursor_pending = self.settings.cursor_restore_pending
        self.window.set_scale(settings.scale)
        self.window.set_paused(settings.animation_paused)
        self.window.set_always_on_top(settings.always_on_top)
        self.window.set_mouse_interaction_enabled(settings.mouse_interaction_enabled)
        self.settings = settings
        self.lan_service.update_identity(display_name=display_name_for(self.settings), pet_name=self.package.name)
        self.remote_interaction_service.update_identity(
            display_name=display_name_for(self.settings),
            pet_name=self.package.name,
        )
        self._configure_lan_service()
        self._configure_remote_interaction_service()
        self._configure_work_countdown()
        self._configure_mouse_follow()
        self._configure_cursor_style(previous_pending=previous_cursor_pending)
        if self.tray is not None:
            self.tray.set_always_on_top_enabled(settings.always_on_top)
        if idle_configuration_changed:
            self._system_idle_monitor = self._new_system_idle_monitor(settings)
            self._configure_system_idle_timer()
        self.settings_manager.save(self.settings)

    def _show_pet_context_menu(self, position: QPoint) -> None:
        """在宠物右键位置弹出跨平台快捷菜单。"""
        self._sync_pet_context_menu()
        self.pet_context_menu.popup(position)

    def _sync_pet_context_menu(self) -> None:
        """让快捷菜单文字、勾选状态与当前运行状态保持一致。"""
        scale = self.window.scale
        display = self.package.display
        self.context_header_action.setText(f"{self.package.name}  ·  {round(scale * 100)}%")
        self.zoom_in_action.setEnabled(scale < display.max_scale)
        self.zoom_out_action.setEnabled(scale > display.min_scale)
        self.reset_scale_action.setEnabled(scale != display.default_scale)
        self.pause_context_action.setText("▶  继续动画" if self.window.player.is_paused else "Ⅱ  暂停动画")
        self.always_on_top_context_action.setChecked(self.settings.always_on_top)
        self.mouse_follow_context_action.setChecked(self.settings.mouse_follow_enabled)

    def _adjust_context_scale(self, delta: float) -> None:
        display = self.package.display
        scale = min(display.max_scale, max(display.min_scale, round(self.window.scale + delta, 2)))
        self.apply_settings(replace(self.settings, scale=scale))

    def _reset_context_scale(self) -> None:
        self.apply_settings(replace(self.settings, scale=self.package.display.default_scale))

    def _toggle_context_pause(self) -> None:
        self.apply_settings(replace(self.settings, animation_paused=not self.window.player.is_paused))

    def _toggle_tray_pause(self, paused: bool) -> None:
        """让托盘暂停与设置持久化路径保持一致。"""
        self.apply_settings(replace(self.settings, animation_paused=paused))

    def _set_pet_visibility(self, visible: bool) -> None:
        """同步桌宠及其独立辅助窗口的显示状态。"""
        self.work_countdown.set_pet_visible(visible)

    def _toggle_context_always_on_top(self, enabled: bool) -> None:
        self.apply_settings(replace(self.settings, always_on_top=enabled))

    def _toggle_mouse_follow(self) -> None:
        self.apply_settings(replace(self.settings, mouse_follow_enabled=not self.settings.mouse_follow_enabled))

    def show_settings_dialog(self) -> None:
        """打开或激活统一设置中心。"""
        self._show_settings_center("display")

    def show_codex_usage_dialog(self) -> None:
        """打开或激活按账号隔离的 Codex 用量面板。"""
        dialog = self._codex_usage_dialog
        if dialog is not None:
            dialog.showNormal()
            dialog.raise_()
            dialog.activateWindow()
            return
        dialog = CodexUsageDialog(
            self._codex_usage_history_path,
            self.window,
            device_id=self.settings.device_id,
            device_label=display_name_for(self.settings),
            on_connect_device=self.show_lan_interaction_dialog,
            on_report=self.codex_usage_sync.sync_report,
            client_factory=self._codex_client_factory,
        )
        self._codex_usage_dialog = dialog
        dialog.finished.connect(lambda _result: self._clear_codex_usage_dialog(dialog))
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _clear_codex_usage_dialog(self, dialog: CodexUsageDialog) -> None:
        if self._codex_usage_dialog is dialog:
            self._codex_usage_dialog = None

    def _codex_sync_snapshots_changed(self, account_key: str) -> None:
        if self._codex_usage_dialog is not None:
            self._codex_usage_dialog.reload_synced_usage(account_key)

    def show_cursor_style_dialog(self) -> None:
        """保留托盘独立入口，但定位到设置中心的鼠标分类。"""
        self._show_settings_center("mouse_behavior")

    def _show_settings_center(self, initial_section: str) -> None:
        dialog = self._settings_center_dialog
        if dialog is not None:
            dialog.select_section(initial_section)
            dialog.showNormal()
            dialog.raise_()
            dialog.activateWindow()
            return
        supported_roles = getattr(self.cursor_controller, "supported_roles", frozenset(_CURSOR_STYLE_ROLES))
        preview_path = next(
            (
                frame
                for definition in self.package.animations.values()
                for frame in definition.frames
                if frame.is_file()
            ),
            None,
        )
        dialog = SettingsDialog(
            self.settings,
            self.window,
            on_check_app_update=self._check_app_update_from_settings if sys.platform in APP_UPDATE_PLATFORMS else None,
            on_download_app_update=self._schedule_app_update_download if sys.platform in APP_UPDATE_PLATFORMS else None,
            cursor_styles=self.cursor_catalog.discover(),
            supported_roles=supported_roles,
            pet_preview_path=preview_path,
            initial_section=initial_section,
        )
        self._settings_center_dialog = dialog
        if self._pending_app_update is not None:
            dialog.set_app_update_available(self._pending_app_update)
        dialog.accepted.connect(lambda: self.apply_settings(dialog.updated_settings()))
        dialog.finished.connect(lambda _result: self._clear_settings_center(dialog))
        dialog.open()

    def _clear_settings_center(self, dialog: SettingsDialog) -> None:
        if self._settings_center_dialog is dialog:
            self._settings_center_dialog = None

    def _check_app_update_from_settings(self) -> None:
        """设置中心内联检查更新，不再打开独立更新窗口。"""
        self._schedule_app_update_check(force=True)

    def show_lan_interaction_dialog(self) -> None:
        """打开附近设备与远程伙伴的统一互动入口。"""
        self._configure_lan_service()
        self._configure_remote_interaction_service()
        self.lan_service.discover()
        effects = self._discover_effects()
        dialog = LanInteractionDialog(
            settings=self.settings,
            peers=self.lan_service.peers(),
            remote_peers=self.remote_interaction_service.peers(),
            effects=effects,
            on_send=self.lan_service.send_interaction,
            on_chat_send=self.lan_service.send_chat,
            on_remote_send=(
                self.remote_interaction_service.send_interaction
                if self.remote_interaction_service.is_configured
                else None
            ),
            on_probe=self.lan_service.probe_peer,
            on_remote_pair=(
                self.remote_interaction_service.pair_peer
                if self.remote_interaction_service.is_configured
                else None
            ),
            on_preview=self._preview_lan_effect,
            on_preview_clear=self.window.clear_effect,
            remote_send_async=self.remote_interaction_service.is_configured,
            remote_pair_code=(
                self.remote_interaction_service.pair_code
                if self.remote_interaction_service.is_configured
                else ""
            ),
            remote_status=self.remote_interaction_service.status_message,
            chat_messages=self.lan_service.chat_messages(),
            parent=self.window,
        )
        self.lan_service.peer_changed.connect(dialog.update_peer)
        self.lan_service.manual_probe_succeeded.connect(dialog.manual_probe_succeeded)
        self.lan_service.peer_removed.connect(dialog.remove_peer)
        self.lan_service.chat_message_added.connect(dialog.add_chat_message)
        self.lan_service.error.connect(dialog.set_status_message)
        self.codex_usage_sync.status_changed.connect(dialog.set_status_message)
        self.remote_interaction_service.peer_changed.connect(dialog.update_remote_peer)
        self.remote_interaction_service.peer_removed.connect(dialog.remove_remote_peer)
        self.remote_interaction_service.pairing_succeeded.connect(dialog.remote_pair_succeeded)
        self.remote_interaction_service.pair_code_changed.connect(dialog.set_remote_pair_code)
        self.remote_interaction_service.status_changed.connect(dialog.set_remote_status)
        self.remote_interaction_service.error.connect(dialog.set_status_message)
        self.remote_interaction_service.interaction_send_succeeded.connect(dialog.remote_send_succeeded)
        self.remote_interaction_service.interaction_send_failed.connect(dialog.remote_send_failed)
        dialog.exec()
        updated = dialog.settings
        if (
            updated.nickname != self.settings.nickname
            or updated.lan_interaction_enabled != self.settings.lan_interaction_enabled
            or updated.lan_group_chat_notifications_enabled
            != self.settings.lan_group_chat_notifications_enabled
            or updated.remote_interaction_enabled != self.settings.remote_interaction_enabled
        ):
            self.apply_settings(updated)

    def _preview_lan_effect(self, effect: object) -> bool:
        """在本机宠物上一次性预览局域网动效，不发送网络消息。"""
        try:
            return bool(self.window.play_effect(effect, loop=False))
        except Exception:  # noqa: BLE001 - 预览失败不能影响互动窗口。
            LOGGER.exception("本机预览局域网动效失败")
            return False

    def _discover_effects(self) -> list[object]:
        """合并用户目录、缓存和安装包内的动效，按 ID 去重。"""
        application_root = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else None
        catalog = EffectCatalog()
        by_identifier: dict[str, object] = {}
        for root in effect_directories_for(
            pets_root=self.pets_root,
            resource_directory=self.resource_directory,
            bundled_root=bundled_resource_seed_root(),
            application_root=application_root,
        ):
            # 这里只生成互动选择器的列表；逐帧 Pillow 校验会在打开窗口前
            # 阻塞 GUI（动效帧越多越明显），实际播放时再由 QPixmap 读取帧。
            for effect in catalog.discover(root, verify_frames=False):
                by_identifier.setdefault(effect.identifier, effect)
        return sorted(by_identifier.values(), key=lambda item: str(getattr(item, "identifier", "")).casefold())

    def show_spritesheet_import_dialog(self) -> None:
        """从本机文件导入成功后重新扫描，并立即切换到新宠物包。"""
        dialog = SpriteSheetImportDialog(self.pets_root, self.window)
        if dialog.exec() and dialog.imported_result is not None:
            self.packages = self.loader.discover(self.pets_root)
            self.switch_pet(dialog.imported_result.package_id)

    def open_pets_folder(self) -> None:
        """打开用户放置目录式宠物包的位置。"""
        self.pets_root.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.pets_root)))

    def refresh_pets(self) -> None:
        """重新扫描宠物目录，立即让手动放入的包出现在托盘菜单。"""
        current_id = self.package.identifier
        self._synchronize_pet_library()
        self.packages = self.loader.discover(self.pets_root)
        if self.tray is not None:
            self.tray.set_pet_names({item.identifier: item.name for item in self.packages})
        if not any(item.identifier == current_id for item in self.packages):
            return
        self.reload_current_pet()
        if self.tray is not None:
            self.tray.showMessage("PetNest", f"已发现 {len(self.packages)} 只宠物")

    def _synchronize_pet_library(self) -> None:
        """在发现宠物前对齐手动增删 PNG 后失配的逐帧时长。"""
        root = self.pets_root.expanduser()
        if not root.is_dir():
            return
        for candidate in sorted((item for item in root.iterdir() if item.is_dir()), key=lambda item: item.name.casefold()):
            if not (candidate / "pet.json").exists():
                continue
            try:
                self.action_synchronizer.sync(candidate)
            except AnimationActionSyncError:
                LOGGER.warning("跳过无法同步的宠物包：%s", candidate, exc_info=True)

    def show_animation_editor_dialog(self) -> None:
        """编辑并保存当前宠物包的可分享动画时长。"""
        if not self.reload_current_pet():
            QMessageBox.warning(self.window, "无法编辑动画时长", "当前宠物资源无法重新载入，请检查新增图片后重试。")
            return
        dialog = AnimationEditorDialog(self.package, self.window)
        if dialog.exec():
            try:
                self.action_synchronizer.update_frame_durations(self.package.root, dialog.updated_frame_durations())
            except AnimationActionSyncError as error:
                QMessageBox.critical(
                    self.window,
                    "无法保存动画时长",
                    f"未写入 {self.package.root / 'pet.json'}。\n原因：{error}",
                )
                return
            if self.reload_current_pet() and self.tray is not None:
                self.tray.showMessage("PetNest", dialog.applied_summary())

    def shutdown(self) -> None:
        """按可控顺序停止服务、保存状态并请求 Qt 事件循环退出。"""
        if self._shutdown:
            return
        self._shutdown = True
        LOGGER.info("PetNest 开始正常退出：pid=%s", os.getpid())
        # 首先撤掉用户可见的界面。外部服务的停止可能需要等待 socket
        # 超时，不能让“退出”菜单看起来像没有响应。
        if self.tray is not None:
            self._run_shutdown_step("隐藏托盘图标", self.tray.hide)
        if self._codex_usage_dialog is not None:
            self._run_shutdown_step("关闭 Codex 用量窗口", self._codex_usage_dialog.close)
        self._run_shutdown_step("隐藏互动提示", self.window.clear_interaction_bubble)
        self._run_shutdown_step("停止互动动效", self.window.clear_effect)
        self._run_shutdown_step("隐藏打卡卡片", lambda: self._set_pet_visibility(False))
        self._run_shutdown_step("隐藏宠物窗口", self.window.hide)
        server, self.external_server = self.external_server, None
        if server is not None:
            self._run_shutdown_step("停止外部事件服务", server.stop)
        self._run_shutdown_step("停止系统空闲计时器", self.system_idle_timer.stop)
        self._run_shutdown_step("停止鼠标跟随计时器", self.mouse_follow_timer.stop)
        self._run_shutdown_step("停止远程资源结果计时器", self.resource_result_timer.stop)
        self._run_shutdown_step("停止远程资源检查计时器", self.resource_update_timer.stop)
        self._run_shutdown_step("停止程序更新结果计时器", self.app_update_result_timer.stop)
        self._run_shutdown_step("停止程序更新检查计时器", self.app_update_check_timer.stop)
        self._run_shutdown_step("停止倒计时计时器", self.work_countdown.timer.stop)
        self._run_shutdown_step("停止 Codex 局域网同步", self.codex_usage_sync.stop)
        self._run_shutdown_step(
            "记录 Codex 账号观察结束",
            lambda: self._codex_account_observations.observe(None, datetime.now(UTC)),
        )
        self._run_shutdown_step("停止局域网互动服务", self.lan_service.stop)
        self._run_shutdown_step("停止远程伙伴服务", self.remote_interaction_service.stop)
        self._run_shutdown_step("停止平台适配器", self.platform_adapter.stop)
        self._run_shutdown_step("恢复系统鼠标样式", self._restore_cursor_style)
        if not self.settings.mouse_follow_enabled:
            self._run_shutdown_step("保存窗口位置", lambda: self._save_window_position(self.window.pos()))
        self._run_shutdown_step("退出 Qt 事件循环", QApplication.quit)
        LOGGER.info("PetNest 已请求 Qt 事件循环退出：pid=%s", os.getpid())

    @staticmethod
    def _run_shutdown_step(name: str, operation: Callable[[], object]) -> None:
        """退出清理失败时记录错误，仍继续执行后续退出步骤。"""
        try:
            operation()
        except Exception:  # noqa: BLE001 - 退出必须优先让用户可见的进程结束。
            LOGGER.exception("PetNest 退出时无法%s", name)

    def _start_external_server(self) -> None:
        server = ExternalEventServer(self.event_bus, port=self.settings.external_event_port)
        if server.start():
            self.external_server = server
        else:
            LOGGER.warning("本地外部事件服务未启用，桌宠仍可正常使用")

    def _schedule_resource_check(self, force: bool = False) -> None:
        """在后台检查 manifest，避免网络请求阻塞桌宠主线程。"""
        if self._shutdown or (self._resource_worker is not None and self._resource_worker.is_alive()):
            return
        worker = Thread(
            target=self._resource_check_worker,
            args=(force,),
            daemon=True,
            name="petnest-resource-check",
        )
        self._resource_worker = worker
        if self.tray is not None:
            self.tray.set_resource_update_loading(True, message="正在检查资源…")
        worker.start()

    def _resource_check_worker(self, force: bool) -> None:
        try:
            result = self.remote_resource_update.check(force=force)
        except Exception as error:  # noqa: BLE001 - resource checks must not stop the app.
            LOGGER.exception("远程资源检查线程异常")
            result = RemoteResourceCheckResult(False, False, self.remote_resource_update.update_available, error=str(error))
        self._resource_results.put(("check", force, result))

    def _schedule_resource_apply(self) -> None:
        """在后台下载并校验完整资源版本。"""
        if self._shutdown or (self._resource_worker is not None and self._resource_worker.is_alive()):
            return
        worker = Thread(
            target=self._resource_apply_worker,
            daemon=True,
            name="petnest-resource-apply",
        )
        self._resource_worker = worker
        if self.tray is not None:
            self.tray.set_resource_update_loading(True, message="正在下载资源（0%）…")
        worker.start()

    def _resource_apply_worker(self) -> None:
        def report_progress(progress: int) -> None:
            self._resource_results.put(("progress", False, progress))

        def report_resource_applied(_identifier: str) -> None:
            # The cache switches each verified resource atomically. Queue the
            # refresh so Qt-owned catalogs and windows are touched on the GUI
            # thread while the remaining resources continue downloading.
            self._resource_results.put(("view", False, None))

        try:
            result = self.remote_resource_update.apply(
                progress=report_progress,
                on_resource_applied=report_resource_applied,
            )
        except Exception as error:  # noqa: BLE001 - failed update is reported in the UI.
            LOGGER.exception("远程资源更新线程异常")
            result = RemoteResourceApplyResult(False, error=str(error))
        self._resource_results.put(("apply", False, result))

    def _handle_resource_update_action(self) -> None:
        """托盘动作：有新版本时应用，否则绕过节流立即检查。"""
        if self.remote_resource_update.update_available:
            self._schedule_resource_apply()
        else:
            self._schedule_resource_check(force=True)

    def _resource_timer_tick(self) -> None:
        self._schedule_resource_check(force=False)

    def _drain_resource_results(self) -> None:
        view_refreshed = False
        while True:
            try:
                kind, manual, payload = self._resource_results.get_nowait()
            except Empty:
                return
            if kind == "check" and isinstance(payload, RemoteResourceCheckResult):
                self._handle_resource_check_result(payload, manual=manual)
            elif kind == "apply" and isinstance(payload, RemoteResourceApplyResult):
                self._handle_resource_apply_result(payload, view_already_refreshed=view_refreshed)
                view_refreshed = False
            elif kind == "progress" and isinstance(payload, int):
                self._handle_resource_progress(payload)
            elif kind == "view":
                self._refresh_resource_directories(verify_files=False)
                view_refreshed = True

    def _handle_resource_progress(self, progress: int) -> None:
        if self.tray is not None:
            self.tray.set_resource_update_progress(progress)

    def _handle_resource_check_result(self, result: RemoteResourceCheckResult, *, manual: bool) -> None:
        if self.tray is not None:
            self.tray.set_resource_update_loading(False)
        if self.tray is not None:
            self.tray.set_resource_update_available(result.update_available)
        if result.error:
            LOGGER.warning("远程资源检查失败：%s", result.error)
            if manual and self.tray is not None:
                self.tray.showMessage("PetNest", f"资源检查失败：{result.error}")
        elif result.update_available and result.checked and manual:
            if self.tray is not None:
                self.tray.showMessage("PetNest", "发现新的远程资源，开始下载资源")
            self._schedule_resource_apply()
        elif manual and result.checked and self.tray is not None:
            self.tray.showMessage("PetNest", "资源已是最新")

    def _handle_resource_apply_result(
        self,
        result: RemoteResourceApplyResult,
        *,
        view_already_refreshed: bool = False,
    ) -> None:
        if self.tray is not None:
            self.tray.set_resource_update_loading(False)
        if (result.updated_resource_ids or result.resource_view_changed) and not view_already_refreshed:
            self._refresh_resource_directories()
        if result.applied:
            if self.tray is not None:
                self.tray.set_resource_update_available(False)
                self.tray.showMessage("PetNest", "资源已更新，新的未使用资源已立即可用")
            return
        if result.partial:
            if self.tray is not None:
                self.tray.set_resource_update_available(True)
                updated = "、".join(result.updated_resource_ids)
                failed = "、".join(result.failed_resource_ids)
                if updated:
                    message = f"已更新 {updated}；{failed} 更新失败，可稍后重试"
                else:
                    message = f"部分资源更新失败：{failed}，可稍后重试"
                self.tray.showMessage("PetNest", message)
            return
        if self.tray is not None:
            self.tray.set_resource_update_available(self.remote_resource_update.update_available)
            if result.error:
                self.tray.showMessage("PetNest", f"资源更新失败：{result.error}")
        if result.error:
            LOGGER.warning("远程资源更新失败：%s", result.error)

    def _show_app_update_dialog(self) -> None:
        """从设置页打开应用更新入口；托盘菜单不暴露此动作。"""
        if sys.platform not in APP_UPDATE_PLATFORMS or self._shutdown:
            return
        if self._app_update_dialog is None:
            dialog = AppUpdateDialog(
                __version__,
                on_check=lambda: self._schedule_app_update_check(force=True),
                on_download=self._schedule_app_update_download,
                parent=self.window,
            )
            dialog.finished.connect(lambda _code: self._clear_app_update_dialog(dialog))
            self._app_update_dialog = dialog
        else:
            dialog = self._app_update_dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        self._schedule_app_update_check(force=True)

    def _clear_app_update_dialog(self, dialog: AppUpdateDialog) -> None:
        if self._app_update_dialog is dialog:
            self._app_update_dialog = None

    def _schedule_app_update_check(self, force: bool = False) -> None:
        """后台检查应用安装包；手动入口传 ``force=True`` 绕过 24 小时节流。"""
        if sys.platform not in APP_UPDATE_PLATFORMS or self._shutdown:
            return
        if self._app_update_worker is not None and self._app_update_worker.is_alive():
            return
        # 新检查开始后，旧结果不能继续让新打开的设置页显示“更新”。
        self._pending_app_update = None
        if self._app_update_dialog is not None:
            self._app_update_dialog.set_checking()
        if self._settings_center_dialog is not None:
            self._settings_center_dialog.set_app_update_checking()
        worker = Thread(
            target=self._app_update_check_worker,
            args=(force,),
            daemon=True,
            name="petnest-app-update-check",
        )
        self._app_update_worker = worker
        worker.start()

    def _app_update_check_worker(self, force: bool) -> None:
        try:
            result = self.app_update_coordinator.check(force=force)
        except Exception as error:  # noqa: BLE001 - update checks must not stop the app.
            LOGGER.exception("程序更新检查线程异常")
            result = AppUpdateCheckResult(False, False, error=str(error) or error.__class__.__name__)
        self._app_update_results.put(("check", result))

    def _schedule_app_update_download(self, info: AppUpdateInfo) -> None:
        if sys.platform not in APP_UPDATE_PLATFORMS or self._shutdown:
            return
        if self._app_update_worker is not None and self._app_update_worker.is_alive():
            return
        destination = self._app_update_download_path(info)
        if self._app_update_dialog is not None:
            self._app_update_dialog.set_downloading(0)
        if self._settings_center_dialog is not None:
            self._settings_center_dialog.set_app_update_downloading(0)
        worker = Thread(
            target=self._app_update_download_worker,
            args=(info, destination),
            daemon=True,
            name="petnest-app-update-download",
        )
        self._app_update_worker = worker
        worker.start()

    def _app_update_download_worker(self, info: AppUpdateInfo, destination: Path) -> None:
        try:
            self._cleanup_old_app_update_downloads(destination)
            self.app_update_client.download(
                info,
                destination,
                progress=lambda value: self._app_update_results.put(("progress", value)),
                cancel=lambda: self._shutdown,
            )
        except Exception as error:  # noqa: BLE001 - failed update remains safely installed.
            LOGGER.exception("程序更新下载安装包失败")
            self._app_update_results.put(("download-error", str(error) or error.__class__.__name__))
            return
        self._app_update_results.put(("downloaded", (info, destination)))

    @staticmethod
    def _app_update_download_path(info: AppUpdateInfo) -> Path:
        safe_version = re.sub(r"[^0-9A-Za-z._-]+", "_", info.version)
        filename = (
            f"PetNest-macOS-x64-{safe_version}.zip"
            if info.platform in {"darwin", "macos", "macos-x64", "macos-arm64"}
            else f"PetNest-Setup-{safe_version}.exe"
        )
        return Path(tempfile.gettempdir()) / "PetNest" / filename

    @staticmethod
    def _cleanup_old_app_update_downloads(destination: Path) -> None:
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            for pattern in ("PetNest-Setup-*.exe", "PetNest-macOS-*.zip"):
                for candidate in destination.parent.glob(pattern):
                    if candidate != destination:
                        candidate.unlink(missing_ok=True)
        except OSError:
            LOGGER.warning("无法清理旧的程序更新安装包", exc_info=True)

    def _launch_windows_installer(self, installer: Path) -> None:
        if sys.platform != "win32":
            raise AppUpdateError("当前平台不支持 Windows 安装器")
        if not getattr(sys, "frozen", False):
            raise AppUpdateError("开发模式未打包 PetNestUpdateHost.exe，无法自动安装")
        executable = Path(sys.executable).absolute()
        bundled_updater = executable.with_name("PetNestUpdateHost.exe")
        if not bundled_updater.is_file():
            raise AppUpdateError("安装包缺少 PetNestUpdateHost.exe")
        from petnest.core.app_update import build_updater_command
        from petnest.core.windows_updater import stage_windows_updater

        updater = stage_windows_updater(bundled_updater, installer.parent / "update-hosts")

        command = build_updater_command(
            updater,
            installer,
            os.getpid(),
            restart_path=executable,
        )
        subprocess.Popen(command, cwd=str(updater.parent), close_fds=True)

    def _launch_macos_installer(self, archive: Path) -> None:
        if sys.platform != "darwin":
            raise AppUpdateError("当前平台不支持 macOS 更新器")
        if not getattr(sys, "frozen", False):
            raise AppUpdateError("开发模式未打包 PetNestUpdater，无法自动安装")
        executable = Path(sys.executable).absolute()
        target_app = next((parent for parent in executable.parents if parent.suffix == ".app"), None)
        if target_app is None:
            raise AppUpdateError("无法定位当前 PetNest.app")
        updater = executable.with_name("PetNestUpdater")
        if not updater.is_file():
            raise AppUpdateError("应用包缺少 PetNestUpdater")
        from petnest.core.macos_updater import build_macos_updater_command

        command = build_macos_updater_command(updater, archive, target_app, os.getpid())
        subprocess.Popen(command, cwd=str(updater.parent), close_fds=True)

    def _launch_app_installer(self, installer: Path) -> None:
        if sys.platform == "win32":
            self._launch_windows_installer(installer)
            return
        if sys.platform == "darwin":
            self._launch_macos_installer(installer)
            return
        raise AppUpdateError("当前平台不支持程序自动更新")

    def _drain_app_update_results(self) -> None:
        while True:
            try:
                kind, payload = self._app_update_results.get_nowait()
            except Empty:
                return
            if kind == "check" and isinstance(payload, AppUpdateCheckResult):
                self._app_update_worker = None
                if payload.error:
                    self._pending_app_update = None
                    LOGGER.warning("程序更新检查失败：%s", payload.error)
                    if self._app_update_dialog is not None:
                        self._app_update_dialog.set_error(payload.error)
                    if self._settings_center_dialog is not None:
                        self._settings_center_dialog.set_app_update_error(payload.error)
                elif payload.update is None:
                    self._pending_app_update = None
                    if self._app_update_dialog is not None:
                        self._app_update_dialog.set_no_update()
                    if self._settings_center_dialog is not None:
                        self._settings_center_dialog.set_app_update_no_update()
                else:
                    self._pending_app_update = payload.update
                    LOGGER.info("发现 PetNest 新版本：%s", payload.update.version)
                    if self._app_update_dialog is not None:
                        self._app_update_dialog.set_available(payload.update)
                    if self._settings_center_dialog is not None:
                        self._settings_center_dialog.set_app_update_available(payload.update)
            elif kind == "progress" and isinstance(payload, int):
                if self._app_update_dialog is not None:
                    self._app_update_dialog.set_downloading(payload)
                if self._settings_center_dialog is not None:
                    self._settings_center_dialog.set_app_update_downloading(payload)
            elif kind == "download-error":
                self._app_update_worker = None
                self._pending_app_update = None
                if self._app_update_dialog is not None:
                    self._app_update_dialog.set_error(str(payload))
                if self._settings_center_dialog is not None:
                    self._settings_center_dialog.set_app_update_error(str(payload))
            elif kind == "downloaded" and isinstance(payload, tuple) and len(payload) == 2:
                self._app_update_worker = None
                _info, installer = payload
                try:
                    self._launch_app_installer(Path(installer))
                except Exception as error:  # noqa: BLE001 - current install remains untouched.
                    LOGGER.exception("无法启动 PetNest 更新安装器")
                    self._pending_app_update = None
                    if self._app_update_dialog is not None:
                        self._app_update_dialog.set_error(str(error) or error.__class__.__name__)
                    if self._settings_center_dialog is not None:
                        self._settings_center_dialog.set_app_update_error(str(error) or error.__class__.__name__)
                    continue
                if self._app_update_dialog is not None:
                    self._app_update_dialog.set_finished()
                if self._settings_center_dialog is not None:
                    self._settings_center_dialog.set_app_update_finished()
                self.shutdown()

    def _refresh_resource_directories(self, *, verify_files: bool = True) -> None:
        """切换到新版本目录；当前已应用到系统的光标不在此处强行替换。"""
        self.resource_directory = resource_directory_for_cache(
            self.remote_resource_cache,
            verify_files=verify_files,
        )
        cursor_root = (
            self.resource_directory / "cursors"
            if self.resource_directory is not None and (self.resource_directory / "cursors").is_dir()
            else bundled_cursor_styles_directory()
        )
        self.cursor_catalog = CursorStyleCatalog(cursor_root)
        countdown_root = self.resource_directory / "countdown" if self.resource_directory is not None else None
        self.window.reload_countdown_skins(countdown_root)

    def _configure_lan_service(self) -> None:
        if self.settings.lan_interaction_enabled:
            if not self.lan_service.start():
                LOGGER.warning("局域网互动未启用，桌宠仍可正常使用")
        else:
            self.lan_service.stop()

    def _configure_remote_interaction_service(self) -> None:
        if self.settings.remote_interaction_enabled:
            if not self.remote_interaction_service.start() and self.remote_interaction_service.is_configured:
                LOGGER.warning("远程伙伴未启用，桌宠仍可正常使用")
        else:
            self.remote_interaction_service.stop()

    def _handle_lan_interaction(self, received: object) -> None:
        """把远程安全互动转成宠物旁的提示和本地动效。"""
        sender = getattr(received, "sender_name", "附近设备")
        draft = getattr(received, "draft", None)
        kind = getattr(draft, "kind", None)
        if kind is InteractionKind.GREETING:
            message = f"{sender} 向你打招呼 👋"
        elif kind is InteractionKind.HEART:
            message = f"{sender} 送了你满天爱心 ❤️"
        elif kind is InteractionKind.TEXT:
            message = f"{sender}：{draft.text}"
        elif kind is InteractionKind.EFFECT:
            effects = self._discover_effects()
            effect = next((item for item in effects if item.identifier == draft.effect_id), None)
            if effect is None:
                message = f"{sender} 发送了一个本地未安装的动效"
            else:
                message = f"{sender} 发送了{effect.name}"
                self.window.play_effect(effect, loop=False)
        else:
            return
        self.window.show_interaction_bubble(message)
        LOGGER.info("收到局域网互动：%s", message)

    def _handle_lan_chat(self, message: object) -> None:
        """Show a lightweight notification while the full message stays in chat."""
        is_group = bool(getattr(message, "is_group", False))
        if is_group and not self.settings.lan_group_chat_notifications_enabled:
            LOGGER.info("已静默接收局域网群聊消息")
            return
        sender = str(getattr(message, "sender_name", "附近设备"))
        kind = getattr(message, "kind", None)
        if kind is ChatMessageKind.IMAGE:
            summary = "发来一张图片 🖼"
        elif kind is ChatMessageKind.EMOJI:
            summary = str(getattr(message, "text", "") or "发来一个表情")
        elif kind is ChatMessageKind.TEXT:
            text = str(getattr(message, "text", "") or "")
            summary = text if len(text) <= 48 else text[:48] + "…"
        else:
            return
        prefix = f"群聊 · {sender}" if is_group else sender
        self.window.show_interaction_bubble(f"{prefix}：{summary}")
        LOGGER.info("收到局域网聊天：%s", sender)

    def _configure_system_idle_timer(self) -> None:
        if self.settings.system_idle_enabled:
            self.system_idle_timer.start()
            self._check_system_idle()
        else:
            self.system_idle_timer.stop()
            self._system_idle_monitor.reset()

    def _check_system_idle(self) -> None:
        if not self.settings.system_idle_enabled:
            return
        idle_seconds = self.platform_adapter.get_idle_seconds()
        if idle_seconds is None:
            return
        event_name = self._system_idle_monitor.update(idle_seconds)
        if event_name is not None:
            self.event_bus.publish(PetEvent(event_name, source="system"))

    @staticmethod
    def _new_system_idle_monitor(settings: Settings) -> SystemIdleMonitor:
        return SystemIdleMonitor(
            bored_seconds=settings.system_bored_seconds,
            sleep_seconds=settings.system_sleep_seconds,
        )

    def _restore_window_settings(self) -> None:
        if self.settings.window_x is not None and self.settings.window_y is not None:
            self.window.move(self.window.clamp_position(QPoint(self.settings.window_x, self.settings.window_y)))
        try:
            self.window.set_scale(self.settings.scale)
        except ValueError:
            LOGGER.warning("已保存的缩放不适用于当前宠物包，使用宠物默认值")
        self.window.set_paused(self.settings.animation_paused)
        self.window.set_always_on_top(self.settings.always_on_top)
        self.window.set_mouse_interaction_enabled(self.settings.mouse_interaction_enabled)

    def _configure_work_countdown(self) -> None:
        self.work_countdown.configure(
            enabled=self.settings.work_countdown_enabled,
            start_time=self.settings.work_start_time,
            end_time=self.settings.work_end_time,
            daily_end_times=self.settings.daily_work_end_times,
            gap=self.settings.countdown_gap,
            width=self.settings.countdown_width,
            height=self.settings.countdown_height,
            theme=self.settings.countdown_theme,
            always_on_top=self.settings.always_on_top,
            schedule_mode=self.settings.work_schedule_mode,
            clock_in_start_time=self.settings.clock_in_start_time,
            clock_in_end_time=self.settings.clock_in_end_time,
            work_duration_minutes=self.settings.work_duration_minutes,
            clock_in_date=self.settings.clock_in_date,
            clock_in_time=self.settings.clock_in_time,
            on_clock_in=self._record_clock_in,
        )

    def _record_clock_in(self, recorded_at: datetime) -> None:
        """保存当天的弹性打卡时间，并让控制器继续负责显示。"""
        self.settings = replace(
            self.settings,
            clock_in_date=recorded_at.date().isoformat(),
            clock_in_time=recorded_at.strftime("%H:%M"),
        )
        self.settings_manager.save(self.settings)

    def _configure_mouse_follow(self) -> None:
        enabled = self.settings.mouse_follow_enabled
        self.window.set_follow_mode(enabled, scale_multiplier=self.settings.mouse_follow_scale)
        self.mouse_follow_controller.reset()
        if enabled:
            self.mouse_follow_timer.start()
        else:
            self.mouse_follow_timer.stop()
        if self.tray is not None:
            self.tray.set_mouse_follow_enabled(enabled)

    def _recover_pending_cursor(self) -> None:
        """上次进程未完成退出时，恢复全部可能被主题替换的角色。"""
        if not self.settings.cursor_restore_pending:
            return
        if self._restore_cursor_roles(_CURSOR_STYLE_ROLES):
            self.settings = replace(self.settings, cursor_restore_pending=False)
            self.settings_manager.save(self.settings)

    def _restore_cursor_roles(self, roles: Iterable[str]) -> bool:
        """让当前平台恢复由 PetNest 接管的系统光标。"""
        if not tuple(roles):
            return True
        return self.cursor_controller.restore_system_defaults()

    def _configure_cursor_style(self, *, previous_pending: bool) -> None:
        """根据当前设置应用一个样式，或恢复之前由 PetNest 接管的箭头。"""
        selected = self.cursor_catalog.get(self.settings.cursor_style_id)
        if self.settings.cursor_style_enabled and selected is not None:
            # 新主题没有提供的角色必须立即回到用户原有系统样式，不能继续沿用
            # 上一个主题留下的图标。
            missing_roles = (role for role in _CURSOR_STYLE_ROLES if role not in selected.roles)
            self._restore_cursor_roles(missing_roles)
            applied = {
                role
                for role, path in selected.roles.items()
                if self._apply_cursor_role(role, path)
            }
            if applied:
                self._active_cursor_roles = applied
                self.settings = replace(self.settings, cursor_restore_pending=True)
                return
        if previous_pending or self.settings.cursor_restore_pending:
            restored = self._restore_cursor_roles(_CURSOR_STYLE_ROLES)
            self.settings = replace(self.settings, cursor_restore_pending=not restored)
            if restored:
                self._active_cursor_roles.clear()
            return
        self.settings = replace(self.settings, cursor_restore_pending=False)

    def _apply_cursor_role(self, role: str, path: Path) -> bool:
        """应用带尺寸的光标；兼容旧的控制器替身。"""
        scale = self.settings.cursor_scale / 100
        try:
            if role == "arrow":
                return self.cursor_controller.apply(path, scale=scale)
            return self.cursor_controller.apply_role(role, path, scale=scale)
        except TypeError:
            if role == "arrow":
                return self.cursor_controller.apply(path)
            return self.cursor_controller.apply_role(role, path)

    def _restore_cursor_style(self) -> None:
        """正常退出时恢复由本进程替换的普通箭头。"""
        if not self.settings.cursor_restore_pending:
            return
        restored = self._restore_cursor_roles(_CURSOR_STYLE_ROLES)
        if restored:
            self.settings = replace(self.settings, cursor_restore_pending=False)
            self.settings_manager.save(self.settings)
            self._active_cursor_roles.clear()

    def _tick_mouse_follow(self) -> None:
        self.update_mouse_follow(QCursor.pos(), now_ms=round(monotonic() * 1000))

    def update_mouse_follow(self, cursor: QPoint, *, now_ms: int) -> None:
        """供定时器和测试输入一帧全局光标位置。"""
        if not self.settings.mouse_follow_enabled:
            return
        moving = self.mouse_follow_controller.sample(cursor, now_ms=now_ms)
        screen = QGuiApplication.screenAt(cursor) or self.window.screen() or QGuiApplication.primaryScreen()
        if screen is not None:
            style = self.cursor_catalog.get(self.settings.cursor_style_id) if self.settings.cursor_style_enabled else None
            target = self.mouse_follow_controller.target_position(
                cursor,
                self.window.size(),
                screen.availableGeometry(),
                visible_bounds=style.follow_bounds if style is not None else None,
            )
            if target != self.window.pos():
                self.window.move(target)
        self.window.set_follow_motion(
            moving,
            direction=self.mouse_follow_controller.direction,
            facing_left=self.mouse_follow_controller.facing_left,
        )

    def _save_window_position(self, position: QPoint) -> None:
        self.settings = replace(self.settings, window_x=position.x(), window_y=position.y())
        self.settings_manager.save(self.settings)

    def _select_package(self, identifier: str | None) -> PetPackage:
        return next((item for item in self.packages if item.identifier == identifier), self.packages[0])

    def _migrate_legacy_animation_overrides(self, packages: list[PetPackage]) -> None:
        """将旧版本机动画覆盖一次性写进各宠物包，之后不再从设置读取。"""
        legacy = self.settings.animation_overrides
        if not legacy:
            return
        remaining = {pet_id: dict(actions) for pet_id, actions in legacy.items()}
        for package in packages:
            overrides = remaining.get(package.identifier)
            if not overrides:
                continue
            timelines = {
                action: self._legacy_timeline(package, action, override)
                for action, override in overrides.items()
                if action in package.animations
            }
            try:
                self.action_synchronizer.update_frame_durations(package.root, timelines)
            except AnimationActionSyncError:
                LOGGER.exception("迁移旧动画时长失败：%s", package.identifier)
                continue
            remaining.pop(package.identifier, None)
        self.settings = replace(self.settings, animation_overrides=remaining)
        if not remaining:
            self.settings_manager.save(self.settings)

    @staticmethod
    def _legacy_timeline(package: PetPackage, action: str, override: AnimationOverride) -> tuple[int, ...]:
        definition = package.animations[action]
        source = definition.frame_durations_ms or tuple(round(1000 / definition.fps) for _ in definition.frames)
        if override.mode == "per_frame" and override.frame_durations_ms is not None and len(override.frame_durations_ms) == len(source):
            return override.frame_durations_ms
        target_total = round(sum(source) / override.speed_multiplier)
        return _scaled_timeline(source, target_total)


def _pet_context_menu_stylesheet(palette: QPalette) -> str:
    """生成兼容 macOS/Windows 深浅色主题的紧凑快捷菜单样式。"""
    dark = palette.color(QPalette.ColorRole.Window).lightness() < 128
    background = "#242529" if dark else "#FFFFFF"
    border = "#3A3B40" if dark else "#D9D9DE"
    text = palette.color(QPalette.ColorRole.Text).name(QColor.NameFormat.HexRgb)
    muted = "#9A9BA1" if dark else "#777880"
    selected = "#0A84FF" if dark else "#007AFF"
    return f"""
        QMenu#petContextMenu {{
            background-color: {background};
            color: {text};
            border: 1px solid {border};
            border-radius: 10px;
            padding: 7px;
            font-size: 13px;
        }}
        QMenu#petContextMenu::item {{
            min-width: 190px;
            padding: 7px 28px 7px 12px;
            margin: 1px 0;
            border-radius: 6px;
        }}
        QMenu#petContextMenu::item:selected {{
            background-color: {selected};
            color: #FFFFFF;
        }}
        QMenu#petContextMenu::item:disabled {{
            color: {muted};
            background-color: transparent;
        }}
        QMenu#petContextMenu::separator {{
            height: 1px;
            background-color: {border};
            margin: 6px 8px;
        }}
    """


def _scaled_timeline(source: tuple[int, ...], target_total: int) -> tuple[int, ...]:
    """按原有节奏缩放时间线，并在整数毫秒内尽量保持目标总时长。"""
    if not source:
        return ()
    source_total = sum(source)
    target_total = max(len(source), target_total)
    durations = [max(1, round(duration * target_total / source_total)) for duration in source]
    difference = target_total - sum(durations)
    index = len(durations) - 1
    while difference:
        adjustment = 1 if difference > 0 else -1
        if durations[index] + adjustment > 0:
            durations[index] += adjustment
            difference -= adjustment
        index = (index - 1) % len(durations)
    return tuple(durations)
