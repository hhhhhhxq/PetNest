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
from threading import Lock, Thread, current_thread
from time import monotonic
import uuid

from PySide6.QtCore import QObject, QPoint, QRect, QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QAction, QColor, QCursor, QDesktopServices, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication, QDialog, QMenu, QMenuBar, QMessageBox, QWidget

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
    CodexManualAttributionStore,
    CodexDeviceUsageStore,
    CodexUsageClient,
    codex_account_observation_path,
    codex_manual_attribution_path,
    codex_device_usage_path,
)
from petnest.core.codex_usage_sync import CodexUsageSyncCoordinator
from petnest.core.codex_link import (
    CodexHookManager,
    CodexHookStatus,
    CodexLinkCoordinator,
    CodexLinkSnapshot,
)
from petnest.core.codex_discovery import (
    CodexAvailabilityState,
    CodexDiscoveryService,
    CodexHomeDiscovery,
    CodexInstallationDetector,
    CodexLinkAvailability,
    CodexLogSourceProbe,
)
from petnest.core.codex_plugin import CodexPluginManager, CodexPluginStatus
from petnest.core.codex_session_log import CodexSessionLogWatcher
from petnest.core.event_bus import EventBus
from petnest.core.lan_service import LanInteractionService
from petnest.core.lan_firewall_advisor import LanFirewallAdvisorCoordinator
from petnest.core.lan_discovery import qt_interface_ipv4
from petnest.core.lan_pool_roster import PoolRosterStore
from petnest.core.lan_pool_sync import LanPoolSyncService
from petnest.core.lan_peer_discovery_sync import LanPeerDiscoverySyncService
from petnest.core.lan_peer_registry import KnownLanPeerRegistry
from petnest.core.windows_lan_firewall import LanFirewallStatus, WindowsLanFirewallBackend
from petnest.core.lottie_effects import EffectCatalog
from petnest.core.mouse_follow import MouseFollowController
from petnest.core.package_loader import PackageLoader
from petnest.core.pet_visibility_lease import PetVisibilityLease
from petnest.core.pet_library import default_user_pets_directory, prepare_pet_library
from petnest.core.pet_package_importer import PetImportOptions, PetPackageImportError, PetImportResult, import_pet_package
from petnest.core.pet_store_cache import PetStoreCache
from petnest.core.pet_store_service import PetStoreInstallResult, PetStoreService
from petnest.core.pet_store_state import PetStoreStateStore
from petnest.core.remote_resource_cache import RemoteResourceCache
from petnest.core.remote_resource_manifest import RemoteResource
from petnest.core.remote_resource_update import (
    RemoteResourceApplyResult,
    RemoteResourceCheckResult,
    RemoteResourceUpdateCoordinator,
)
from petnest.core.remote_interaction_service import FirebaseRemoteInteractionService
from petnest.core.settings_manager import SettingsManager
from petnest.core.system_idle_monitor import SystemIdleMonitor
from petnest.core.work_finish_state import WorkFinishState, state_from_dict, state_to_dict
from petnest.core.work_activity import WorkActivityCoordinator
from petnest.events.external_event_server import ExternalEventServer
from petnest.logging_config import configure_logging
from petnest.core.device_identity import display_name_for
from petnest.models.event import EventName, PetEvent
from petnest.models.lan_interaction import (
    ChatMessageKind,
    DangerAlert,
    DangerAlertDeliveryResult,
    InteractionKind,
)
from petnest.models.pet_package import PetPackage
from petnest.models.settings import AnimationOverride, Settings
from petnest.ui.app_update_dialog import AppUpdateDialog
from petnest.ui.codex_usage_dialog import CodexUsageDialog
from petnest.ui.danger_alert import DangerAlertConfirmDialog, DangerAlertOverlay
from petnest.platforms import (
    PlatformEventAdapter,
    StartupRegistrationResult,
    create_platform_adapter,
)
from petnest.platforms.cursor import CursorController, create_cursor_controller
from petnest.platforms.keyboard import KeyboardActivityMonitor, create_keyboard_activity_monitor
from petnest.ui.pet_window import PetWindow
from petnest.ui.pet_action_exchange_dialog import PetActionExchangeDialog
from petnest.ui.animation_editor_page import AnimationSaveResult
from petnest.ui.settings_dialog import SettingsDialog
from petnest.ui.lan_interaction_dialog import LanInteractionDialog
from petnest.ui.spritesheet_import_dialog import SpriteSheetImportDialog
from petnest.ui.tray_icon import PetTrayIcon
from petnest.ui.work_countdown import WorkCountdownWindow
from petnest.ui.work_finish_import_dialog import WorkFinishImportDialog
from petnest.ui.work_finish_reminder import WorkFinishReminder

LOGGER = logging.getLogger(__name__)
REMOTE_RESOURCE_BASE_URL = "https://red-lake-ce5a.bbbbbiubiubiu.workers.dev"
REMOTE_RESOURCE_RESULT_POLL_INTERVAL_MS = 200
APP_UPDATE_RESULT_POLL_INTERVAL_MS = 200
APP_UPDATE_STARTUP_DELAY_MS = 2_500
CODEX_DISCOVERY_RETRY_INTERVAL_MS = 30_000
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


def _fetch_codex_home_for_discovery() -> Path:
    return CodexUsageClient().fetch_codex_home()


def _initial_codex_home() -> Path:
    configured = os.environ.get("CODEX_HOME")
    if isinstance(configured, str) and configured.strip():
        return Path(configured).expanduser().absolute()
    return (Path.home() / ".codex").absolute()


def _availability_selects_profile(availability: CodexLinkAvailability) -> bool:
    return availability.selected_home is not None and availability.state in {
        CodexAvailabilityState.WAITING_FOR_SESSIONS,
        CodexAvailabilityState.UNREADABLE,
        CodexAvailabilityState.INCOMPATIBLE,
        CodexAvailabilityState.READY,
        CodexAvailabilityState.ACTIVE,
    }


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


def bundled_codex_plugin_directory() -> Path:
    """定位开发环境或安装包中的 PetNest Codex 插件模板。"""
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root is not None:
        return Path(frozen_root) / "assets" / "codex-plugins" / "petnest-status-link"
    return Path(__file__).resolve().parents[2] / "assets" / "codex-plugins" / "petnest-status-link"


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


class _ExternalEventRelay(QObject):
    """把 socket 工作线程收到的事件排队送回 Qt 主线程。"""

    event_received = Signal(object)


class _KeyboardActivityRelay(QObject):
    """Queue parameterless native keyboard pulses onto the Qt main thread."""

    activity = Signal()


class PetNest:
    """第一阶段桌宠运行时，负责有序启动、宠物切换和有序退出。"""

    def __init__(
        self,
        *,
        pets_root: Path | None = None,
        settings_manager: SettingsManager | None = None,
        platform_adapter: PlatformEventAdapter | None = None,
        cursor_controller: CursorController | None = None,
        codex_hook_manager: CodexHookManager | None = None,
        codex_plugin_manager: CodexPluginManager | None = None,
        codex_discovery: CodexDiscoveryService | None = None,
        codex_log_watcher: CodexSessionLogWatcher | None = None,
        keyboard_activity_monitor: KeyboardActivityMonitor | None = None,
        lan_firewall_advisor: LanFirewallAdvisorCoordinator | None = None,
        store_base_url: str = REMOTE_RESOURCE_BASE_URL,
        enable_tray: bool = True,
    ) -> None:
        if QApplication.instance() is None:
            raise RuntimeError("创建 PetNest 前必须先创建 QApplication")
        self.settings_manager = settings_manager or SettingsManager()
        self.settings = self.settings_manager.load()
        located_codex_home = _initial_codex_home()
        self.codex_hook_manager = codex_hook_manager or CodexHookManager(
            located_codex_home,
            self.settings_manager.path.parent,
            port=self.settings.external_event_port,
        )
        self.codex_hook_status = self.codex_hook_manager.inspect()
        self.codex_plugin_manager = codex_plugin_manager or CodexPluginManager(
            bundled_codex_plugin_directory(),
            self.settings_manager.path.parent,
            codex_home=self.codex_hook_manager.codex_home,
            hook_manager=self.codex_hook_manager,
        )
        self.codex_plugin_status = CodexPluginStatus.missing()
        self._uses_default_codex_discovery = codex_discovery is None
        self._codex_app_home_cache: Path | None = None
        self._codex_app_home_probe_complete = False
        self._codex_app_home_probe_after = 0.0
        self._codex_discovery_results: Queue[tuple[Path | None, str | None]] = Queue()
        self._codex_discovery_worker: Thread | None = None
        self._startup_repair_worker: Thread | None = None
        self._startup_registration_lock = Lock()
        self._startup_registration_revision = 0
        self._startup_registration_desired = self.settings.run_at_startup
        self.codex_discovery = codex_discovery or CodexDiscoveryService(
            CodexInstallationDetector(
                platform_name=sys.platform,
                environment=os.environ,
                user_home=Path.home(),
            ),
            CodexHomeDiscovery(
                environment=os.environ,
                user_home=Path.home(),
                app_home_provider=lambda: self._codex_app_home_cache,
            ),
            CodexLogSourceProbe(),
        )
        self.codex_availability = CodexLinkAvailability(
            CodexAvailabilityState.DETECTING,
            "正在查找 Codex",
            False,
        )
        self.codex_log_watcher = codex_log_watcher or CodexSessionLogWatcher(
            self.codex_hook_manager.codex_home / "sessions"
        )
        self.codex_link_source = "none"
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
        self._resource_results: Queue[tuple[str, object, object]] = Queue()
        self._resource_worker: Thread | None = None
        self._deferred_resource_apply: (
            tuple[object, RemoteResourceApplyResult] | None
        ) = None
        self._resource_view_refreshed_worker: object | None = None
        self._resource_status = "idle"
        self._resource_progress: tuple[int, str | None, str | None, bool] = (0, None, None, False)
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
        self._pet_action_exchange_dialog: PetActionExchangeDialog | None = None
        self._codex_usage_dialog: CodexUsageDialog | None = None
        self._codex_usage_history_path = self.settings_manager.path.parent / "codex-usage-history.json"
        self._codex_account_observations = CodexAccountObservationStore(
            codex_account_observation_path(self._codex_usage_history_path)
        )
        self._codex_manual_attributions = CodexManualAttributionStore(
            codex_manual_attribution_path(self._codex_usage_history_path)
        )
        self._codex_client_factory = lambda: CodexUsageClient(
            observation_store=self._codex_account_observations,
            manual_attribution_store=self._codex_manual_attributions,
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
        self.pet_store_cache = PetStoreCache(
            self.settings_manager.path.parent / "pet-store",
            store_base_url,
        )
        self.pet_store_state = PetStoreStateStore(
            self.pet_store_cache.root / "state.json"
        )
        self.pet_store_service = PetStoreService(
            self.pet_store_cache,
            self.pet_store_state,
            self.pets_root,
            is_pet_locked=self._is_pet_locked_for_exchange,
        )
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
        self._external_event_relay = _ExternalEventRelay(self.window)
        self._external_event_relay.event_received.connect(self._publish_external_event)
        self.work_activity = WorkActivityCoordinator(self.event_bus.publish)
        self.codex_link = CodexLinkCoordinator(
            self.work_activity.handle_codex_event,
            self._handle_codex_snapshot,
        )
        self.window.codex_status_activated.connect(self._activate_codex_status)
        self.window.codex_status_bubble.dismissed.connect(self._dismiss_codex_status)
        self._uses_default_lan_firewall_advisor = lan_firewall_advisor is None
        self.lan_firewall_advisor = lan_firewall_advisor or LanFirewallAdvisorCoordinator(
            WindowsLanFirewallBackend(),
            parent=self.window,
        )
        self._lan_firewall_status = self.lan_firewall_advisor.status
        self._lan_firewall_repairing = False
        self._lan_firewall_repair_message = ""
        self._lan_interaction_dialog: LanInteractionDialog | None = None
        self.lan_firewall_advisor.status_changed.connect(self._handle_lan_firewall_status)
        self.lan_firewall_advisor.repair_finished.connect(self._handle_lan_firewall_repair_finished)
        self.window.lan_firewall_notice_activated.connect(self.show_lan_interaction_dialog)
        self.window.lan_firewall_notice_dismissed.connect(self._dismiss_lan_firewall_notice)
        self.peer_registry = KnownLanPeerRegistry(
            self.settings_manager.path.parent / "known-lan-peers.json"
        )
        self.lan_service = LanInteractionService(
            device_id=self.settings.device_id,
            display_name=display_name_for(self.settings),
            pet_name=self.package.name,
            peer_registry=self.peer_registry,
            alert_group_joined=self.settings.lan_alert_group_joined,
            parent=self.window,
        )
        self.lan_service.interaction_received.connect(self._handle_lan_interaction)
        self.lan_service.chat_message_received.connect(self._handle_lan_chat)
        self.lan_service.danger_alert_received.connect(self._handle_danger_alert)
        self.lan_service.danger_alert_delivery_completed.connect(self._handle_danger_alert_delivery)
        self.lan_service.error.connect(lambda message: LOGGER.warning("%s", message))
        self.lan_pool_roster = PoolRosterStore(
            self.settings_manager.path.parent / "lan-alert-pool-roster.json",
            local_device_id=self.settings.device_id,
        )
        self.lan_peer_discovery = LanPeerDiscoverySyncService(
            self.lan_service,
            local_device_id=self.settings.device_id,
            parent=self.window,
        )
        self.lan_pool_sync = LanPoolSyncService(
            self.lan_service,
            self.lan_pool_roster,
            display_name=lambda: display_name_for(self.settings),
            offer_candidate=lambda device_id, ip, port, referrer: (
                self.lan_peer_discovery.offer_candidate(
                    device_id,
                    ip,
                    port,
                    referrer_device_id=referrer,
                )
            ),
            parent=self.window,
        )
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
        self.work_finish_reminder = WorkFinishReminder()
        self.danger_alert_overlay = DangerAlertOverlay()
        self._work_finish_visibility_lease = PetVisibilityLease()
        self.work_finish_reminder.finish_requested.connect(self._finish_work)
        self.work_finish_reminder.continue_requested.connect(self._continue_overtime)
        self.work_finish_reminder.dismissed.connect(self._dismiss_work_finish_reminder)
        self.pet_context_menu = QMenu(self.window)
        self.pet_context_menu.setObjectName("petContextMenu")
        self.pet_context_menu.setStyleSheet(_pet_context_menu_stylesheet(QApplication.palette()))
        self.context_header_action = QAction(self.pet_context_menu)
        self.context_header_action.setEnabled(False)
        self.pet_context_menu.addAction(self.context_header_action)
        self.pet_context_menu.addSeparator()
        self.danger_alert_action = self.pet_context_menu.addAction("⚠  发送危险预警")
        self.danger_alert_action.triggered.connect(self._confirm_danger_alert)
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
        self.event_bus.subscribe(self._handle_codex_hook_event)
        self.platform_adapter = platform_adapter or create_platform_adapter()
        self.keyboard_activity_monitor = keyboard_activity_monitor or create_keyboard_activity_monitor()
        self._keyboard_monitor_running = False
        self._keyboard_activity_relay = _KeyboardActivityRelay(self.window)
        self._keyboard_activity_relay.activity.connect(self._handle_keyboard_activity)
        self.keyboard_activity_timer = QTimer(self.window)
        self.keyboard_activity_timer.setSingleShot(True)
        self.keyboard_activity_timer.setInterval(1_500)
        self.keyboard_activity_timer.timeout.connect(self._finish_keyboard_activity)
        self._system_idle_monitor = self._new_system_idle_monitor(self.settings)
        self.system_idle_timer = QTimer(self.window)
        self.system_idle_timer.setInterval(1_000)
        self.system_idle_timer.timeout.connect(self._check_system_idle)
        self.mouse_follow_controller = MouseFollowController()
        self.mouse_follow_timer = QTimer(self.window)
        self.mouse_follow_timer.setInterval(20)
        self.mouse_follow_timer.timeout.connect(self._tick_mouse_follow)
        self.resource_result_timer = QTimer(self.window)
        self.resource_result_timer.setInterval(REMOTE_RESOURCE_RESULT_POLL_INTERVAL_MS)
        self.resource_result_timer.timeout.connect(self._drain_resource_results)
        self.app_update_result_timer = QTimer(self.window)
        self.app_update_result_timer.setInterval(APP_UPDATE_RESULT_POLL_INTERVAL_MS)
        self.app_update_result_timer.timeout.connect(self._drain_app_update_results)
        self.app_update_check_timer = QTimer(self.window)
        self.app_update_check_timer.setInterval(APP_UPDATE_CHECK_INTERVAL_MS)
        self.app_update_check_timer.timeout.connect(self._schedule_app_update_check)
        self.app_update_startup_timer = QTimer(self.window)
        self.app_update_startup_timer.setSingleShot(True)
        self.app_update_startup_timer.setInterval(APP_UPDATE_STARTUP_DELAY_MS)
        self.app_update_startup_timer.timeout.connect(lambda: self._schedule_app_update_check(force=False))
        self.startup_repair_timer = QTimer(self.window)
        self.startup_repair_timer.setSingleShot(True)
        self.startup_repair_timer.setInterval(0)
        self.startup_repair_timer.timeout.connect(self._repair_startup_registration)
        self.codex_log_timer = QTimer(self.window)
        self.codex_log_timer.setInterval(250)
        self.codex_log_timer.timeout.connect(self._poll_codex_logs)
        self.codex_discovery_timer = QTimer(self.window)
        self.codex_discovery_timer.setInterval(CODEX_DISCOVERY_RETRY_INTERVAL_MS)
        self.codex_discovery_timer.timeout.connect(self._refresh_codex_discovery)
        self.codex_discovery_result_timer = QTimer(self.window)
        self.codex_discovery_result_timer.setInterval(APP_UPDATE_RESULT_POLL_INTERVAL_MS)
        self.codex_discovery_result_timer.timeout.connect(self._drain_codex_discovery_results)
        self.codex_review_animation_timer = QTimer(self.window)
        self.codex_review_animation_timer.setSingleShot(True)
        self.codex_review_animation_timer.timeout.connect(self._finish_codex_review_animation)
        self.external_server: ExternalEventServer | None = None
        self._shutdown = False
        self.tray: PetTrayIcon | None = (
            PetTrayIcon(
                self.window,
                pet_names={item.identifier: item.name for item in self.packages},
                current_pet_name=self.package.name,
                on_switch=self.switch_pet,
                on_reload=self.reload_current_pet,
                on_exchange=self.show_pet_action_exchange_dialog,
                on_open_pets_folder=self.open_pets_folder,
                on_refresh_pets=self.refresh_pets,
                on_settings=self.show_settings_dialog,
                on_codex_usage=self.show_codex_usage_dialog,
                codex_usage_unlocked=self.settings.codex_usage_unlocked,
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
        self._configure_keyboard_activity()
        self._refresh_codex_discovery()
        self._configure_external_event_server()
        self._configure_system_idle_timer()
        self._configure_lan_service()
        self._configure_remote_interaction_service()
        if self.tray is not None:
            self.tray.show()
        self.window.show()
        firewall_enabled = self.settings.lan_interaction_enabled and not (
            self._uses_default_lan_firewall_advisor
            and os.environ.get("PETNEST_TEST_DISABLE_LAN", "").strip() == "1"
        )
        self.lan_firewall_advisor.start(enabled=firewall_enabled)
        self._configure_work_countdown()
        self._configure_mouse_follow()
        self._configure_cursor_style(previous_pending=self.settings.cursor_restore_pending)
        self.settings_manager.save(self.settings)
        if self.settings.run_at_startup:
            self.startup_repair_timer.start()
        self.resource_result_timer.start()
        if sys.platform in APP_UPDATE_PLATFORMS:
            self.app_update_result_timer.start()
            self.app_update_check_timer.start()
            self.app_update_startup_timer.start()
        LOGGER.info("PetNest 已启动，宠物包：%s", self.package.identifier)

    def _repair_startup_registration(self) -> None:
        if (
            self._shutdown
            or not self.settings.run_at_startup
            or (
                self._startup_repair_worker is not None
                and self._startup_repair_worker.is_alive()
            )
        ):
            return
        worker = Thread(
            target=self._startup_repair_worker_task,
            daemon=True,
            name="petnest-startup-repair",
        )
        self._startup_repair_worker = worker
        worker.start()

    def _startup_repair_worker_task(self) -> None:
        try:
            while True:
                with self._startup_registration_lock:
                    revision = self._startup_registration_revision
                    desired = self._startup_registration_desired
                try:
                    startup_result = self.platform_adapter.register_startup(desired)
                except Exception as error:
                    LOGGER.warning("启动时修复自动启动项失败", exc_info=True)
                    startup_result = StartupRegistrationResult(False, message=str(error))
                with self._startup_registration_lock:
                    stale = revision != self._startup_registration_revision
                if stale:
                    continue
                if not startup_result.success:
                    LOGGER.warning("启动时修复自动启动项失败：%s", startup_result.message)
                elif startup_result.requires_approval:
                    LOGGER.info("macOS 自动启动项等待用户批准")
                return
        finally:
            if self._startup_repair_worker is current_thread():
                self._startup_repair_worker = None

    def _set_startup_registration_desired(self, enabled: bool) -> None:
        with self._startup_registration_lock:
            self._startup_registration_revision += 1
            self._startup_registration_desired = enabled

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
        if self._settings_center_dialog is not None:
            self._settings_center_dialog.set_codex_action_availability(
                self._codex_action_availability()
            )
        self.window.handle_pet_event(
            PetEvent(
                self.work_activity.effective_event,
                source="work-activity-restore",
                priority=100,
            )
        )
        self.settings = replace(self.settings, current_pet_id=candidate.identifier, scale=candidate.display.default_scale)
        self.settings_manager.save(self.settings)
        self.lan_service.update_identity(display_name=display_name_for(self.settings), pet_name=self.package.name)
        self.remote_interaction_service.update_identity(
            display_name=display_name_for(self.settings),
            pet_name=self.package.name,
        )
        if self.tray is not None:
            self.tray.set_current_pet_name(self.package.name)
        self._refresh_visible_work_finish_reminder()
        return True

    def reload_current_pet(self, *, synchronize: bool = True) -> bool:
        """重新载入当前包；事务调用方可禁止重载前再次写入配置。"""
        previous = self.package
        position = self.window.pos()
        previous_action = self.window.current_action
        previous_paused = self.window.player.is_paused
        scale_to_restore = (
            self.settings.scale
            if self.settings.mouse_follow_enabled
            else self.window.scale
        )
        window_load_attempted = False
        sync_result = None
        original_config: bytes | None = None
        try:
            if synchronize:
                original_config = self.action_synchronizer.snapshot_config_bytes(previous.root)
                sync_result = self.action_synchronizer.sync(previous.root)
            reloaded = self.loader.load(previous.root)
            window_load_attempted = True
            self.window.load_package(reloaded)
            self.window.set_scale(scale_to_restore)
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
                    self.window.set_scale(scale_to_restore)
                    self.window.restore_runtime_state(previous_action, paused=previous_paused)
                    self.window.move(self.window.clamp_position(position))
                except (OSError, ValueError, RuntimeError):
                    LOGGER.exception("重新加载失败后恢复旧宠物包失败：%s", previous.identifier)
            LOGGER.exception("重新加载宠物包失败：%s", previous.identifier)
            return False
        self.package = reloaded
        self.packages = [reloaded if item.identifier == reloaded.identifier else item for item in self.packages]
        if self._settings_center_dialog is not None:
            self._settings_center_dialog.set_codex_action_availability(
                self._codex_action_availability()
            )
        if self.tray is not None:
            self.tray.set_current_pet_name(self.package.name)
        if sync_result is not None and sync_result.added and self.tray is not None:
            summary = "、".join(f"{action.name}（{action.frame_count} 帧）" for action in sync_result.added)
            self.tray.showMessage("PetNest", f"已自动登记：{summary}")
        elif sync_result is not None and sync_result.reconciled and self.tray is not None:
            summary = "、".join(f"{timeline.name}（{timeline.frame_count} 帧）" for timeline in sync_result.reconciled)
            self.tray.showMessage("PetNest", f"已同步逐帧时长：{summary}")
        self._refresh_visible_work_finish_reminder()
        return True

    def _save_animation_timelines(
        self,
        package: PetPackage,
        timelines: dict[str, tuple[int, ...]],
    ) -> AnimationSaveResult:
        """安全保存动作时长，并在运行时重载成功后返回最新宠物包。"""
        if self._is_pet_locked_for_exchange(package.identifier):
            return AnimationSaveResult(False, "当前宠物正在显示下班提醒，请先结束提醒。")

        try:
            original_config = self.action_synchronizer.snapshot_config_bytes(package.root)
            self.action_synchronizer.update_frame_durations(package.root, timelines)
        except AnimationActionSyncError as error:
            return AnimationSaveResult(False, f"无法保存动画时长：{error}")
        except Exception as error:  # noqa: BLE001 - compatibility with injected synchronizers.
            return AnimationSaveResult(False, f"无法保存动画时长：{error}")

        is_current = package.identifier == self.package.identifier
        try:
            if is_current:
                if not self.reload_current_pet():
                    raise AnimationActionSyncError("当前宠物重新载入失败")
                refreshed = self.package
            else:
                refreshed = self.loader.load(package.root)
                replaced = False
                next_packages: list[PetPackage] = []
                for item in self.packages:
                    if item.identifier == refreshed.identifier:
                        next_packages.append(refreshed)
                        replaced = True
                    else:
                        next_packages.append(item)
                if not replaced:
                    next_packages.append(refreshed)
                self.packages = next_packages
        except Exception as error:  # noqa: BLE001 - reload/load errors must trigger rollback.
            try:
                self.action_synchronizer.restore_config_bytes(package.root, original_config)
            except Exception as restore_error:  # noqa: BLE001 - preserve the explicit double-failure result.
                return AnimationSaveResult(False, f"重载失败且配置恢复失败：{restore_error}")
            if is_current:
                try:
                    self.reload_current_pet()
                except Exception:  # noqa: BLE001 - restored bytes are still reported below.
                    LOGGER.exception("恢复动作时长后重新载入当前宠物失败：%s", package.identifier)
            return AnimationSaveResult(False, f"保存未生效，已恢复原配置：{error}")

        return AnimationSaveResult(True, "已保存并重载", refreshed)

    def apply_settings(self, settings: Settings) -> None:
        """立即应用可安全即时修改的设置，并持久化其非敏感值。"""
        startup_configuration_changed = settings.run_at_startup != self.settings.run_at_startup
        if startup_configuration_changed:
            previous_startup_value = self.settings.run_at_startup
            self._set_startup_registration_desired(settings.run_at_startup)
            try:
                startup_result = self.platform_adapter.register_startup(settings.run_at_startup)
            except Exception as error:
                LOGGER.warning("修改自动启动项失败", exc_info=True)
                startup_result = StartupRegistrationResult(False, message=str(error))
            if not startup_result.success:
                settings = replace(settings, run_at_startup=previous_startup_value)
                self._set_startup_registration_desired(previous_startup_value)
                QMessageBox.warning(
                    self.window,
                    "无法修改自动启动",
                    startup_result.message or "系统未能修改当前用户的登录启动项。",
                )
            elif startup_result.requires_approval:
                QMessageBox.information(
                    self.window,
                    "需要批准自动启动",
                    "请在“系统设置 → 通用 → 登录项”中允许 PetNest。",
                )
        idle_configuration_changed = (
            settings.system_idle_enabled != self.settings.system_idle_enabled
            or settings.system_bored_seconds != self.settings.system_bored_seconds
            or settings.system_sleep_seconds != self.settings.system_sleep_seconds
        )
        keyboard_configuration_changed = (
            settings.keyboard_working_enabled != self.settings.keyboard_working_enabled
        )
        lan_configuration_changed = (
            settings.lan_interaction_enabled != self.settings.lan_interaction_enabled
        )
        alert_membership_changed = settings.lan_alert_group_joined != self.settings.lan_alert_group_joined
        external_event_configuration_changed = (
            settings.external_event_server_enabled != self.settings.external_event_server_enabled
            or settings.external_event_port != self.settings.external_event_port
            or settings.codex_link_enabled != self.settings.codex_link_enabled
        )
        codex_bubble_configuration_changed = (
            settings.codex_link_show_attention_bubbles != self.settings.codex_link_show_attention_bubbles
            or settings.codex_link_show_review_bubbles != self.settings.codex_link_show_review_bubbles
        )
        codex_log_configuration_changed = (
            settings.codex_link_enabled != self.settings.codex_link_enabled
            or settings.codex_link_log_fallback_enabled != self.settings.codex_link_log_fallback_enabled
            or settings.codex_home_override != self.settings.codex_home_override
        )
        previous_cursor_pending = self.settings.cursor_restore_pending
        self.window.set_scale(settings.scale)
        self.window.set_paused(settings.animation_paused)
        self.window.set_always_on_top(settings.always_on_top)
        self.window.set_mouse_interaction_enabled(settings.mouse_interaction_enabled)
        self.settings = settings
        if not settings.codex_link_enabled:
            self.codex_link.clear()
            self.window.clear_codex_status()
        self.lan_service.update_identity(display_name=display_name_for(self.settings), pet_name=self.package.name)
        if alert_membership_changed:
            self.lan_service.update_alert_group_membership(settings.lan_alert_group_joined)
        self.remote_interaction_service.update_identity(
            display_name=display_name_for(self.settings),
            pet_name=self.package.name,
        )
        self._configure_lan_service()
        if lan_configuration_changed:
            self.lan_firewall_advisor.set_enabled(settings.lan_interaction_enabled)
            if not settings.lan_interaction_enabled:
                self._lan_firewall_repairing = False
                self._lan_firewall_repair_message = ""
                self.window.clear_lan_firewall_notice()
        self._configure_remote_interaction_service()
        self._configure_work_countdown()
        self._configure_mouse_follow()
        self._configure_cursor_style(previous_pending=previous_cursor_pending)
        if codex_log_configuration_changed:
            self._refresh_codex_discovery()
        if external_event_configuration_changed:
            self._configure_external_event_server(restart=True)
        elif codex_bubble_configuration_changed:
            self._handle_codex_snapshot(self.codex_link.snapshot)
        if self.tray is not None:
            self.tray.set_always_on_top_enabled(settings.always_on_top)
        if idle_configuration_changed:
            self._system_idle_monitor = self._new_system_idle_monitor(settings)
            self._configure_system_idle_timer()
        if keyboard_configuration_changed:
            self._configure_keyboard_activity()
        self.settings_manager.save(self.settings)

    def _show_pet_context_menu(self, position: QPoint) -> None:
        """在宠物右键位置弹出跨平台快捷菜单。"""
        self._sync_pet_context_menu()
        self.pet_context_menu.popup(position)

    def _set_lan_alert_group_joined(self, joined: bool) -> bool:
        if self.settings.lan_alert_group_joined != joined:
            self.apply_settings(replace(self.settings, lan_alert_group_joined=joined))
        return True

    def _confirm_danger_alert(self) -> None:
        if not self.settings.lan_alert_group_joined:
            QMessageBox.information(
                self.window,
                "尚未加入预警组",
                "请先在“互动”页面加入局域网预警组。",
            )
            return
        dialog = DangerAlertConfirmDialog(
            online=self.lan_service.alert_group_peers(),
            unavailable=self.lan_service.unavailable_known_peers(),
            parent=self.window,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.lan_service.send_danger_alert(dialog.alert_message())

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
        reminder_takeover = self._work_finish_visibility_lease.is_active
        self._work_finish_visibility_lease.user_took_control()
        self._apply_pet_visibility(visible, sync_countdown=not reminder_takeover)

    def _apply_pet_visibility(self, visible: bool, *, sync_countdown: bool = True) -> None:
        """应用真实窗口状态；临时提醒隐藏时保持倒计时引擎继续运行。"""
        try:
            self.window.setVisible(visible)
            if sync_countdown:
                self.work_countdown.set_pet_visible(visible)
        finally:
            if self.tray is not None:
                self.tray.sync_visibility_action()

    def _hide_pet_for_work_finish(self) -> None:
        if self._work_finish_visibility_lease.acquire(was_visible=self.window.isVisible()):
            self._apply_pet_visibility(False, sync_countdown=False)

    def _restore_pet_after_work_finish(self) -> None:
        if not self._work_finish_visibility_lease.release():
            return
        try:
            self._apply_pet_visibility(True, sync_countdown=False)
        except Exception:  # noqa: BLE001 - 托盘“显示”必须在自动恢复失败后继续可用。
            LOGGER.exception("下班提醒结束后恢复宠物失败，可从托盘菜单选择‘显示’")
            if self.tray is not None:
                self.tray.sync_visibility_action()

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

    def _unlock_codex_usage(self) -> None:
        """永久解锁 Codex 用量入口，并立即刷新当前托盘菜单。"""
        if self.settings.codex_usage_unlocked:
            return
        self.settings = replace(self.settings, codex_usage_unlocked=True)
        self.settings_manager.save(self.settings)
        if self.tray is not None:
            self.tray.set_codex_usage_unlocked(True)

    def _clear_codex_usage_dialog(self, dialog: CodexUsageDialog) -> None:
        if self._codex_usage_dialog is dialog:
            self._codex_usage_dialog = None

    def _codex_sync_snapshots_changed(self, account_key: str) -> None:
        if self._codex_usage_dialog is not None:
            self._codex_usage_dialog.reload_synced_usage(account_key)

    def _install_codex_hook(self) -> CodexHookStatus:
        """由设置页显式触发；应用启动绝不自动修改 Codex 配置。"""
        self.codex_hook_manager.set_port(self.settings.external_event_port)
        self.codex_hook_status = self.codex_hook_manager.install()
        self._configure_external_event_server()
        return self.codex_hook_status

    def _remove_codex_hook(self) -> CodexHookStatus:
        self.codex_hook_status = self.codex_hook_manager.remove()
        self._configure_external_event_server()
        self._refresh_codex_discovery()
        return self.codex_hook_status

    def _configure_codex_plugin(self) -> CodexPluginStatus:
        """启用或修复可识别的 PetNest 状态插件。"""
        self.codex_hook_manager.set_port(self.settings.external_event_port)
        self.codex_plugin_status = self.codex_plugin_manager.install_or_repair()
        self._configure_external_event_server()
        return self.codex_plugin_status

    def _recheck_codex_plugin(self) -> CodexPluginStatus:
        """刷新 Codex 实际报告的插件安装与启用状态。"""
        self.codex_plugin_status = self.codex_plugin_manager.inspect()
        return self.codex_plugin_status

    def _remove_codex_plugin(self) -> CodexPluginStatus:
        self.codex_plugin_status = self.codex_plugin_manager.remove()
        self._configure_external_event_server()
        self._refresh_codex_discovery()
        return self.codex_plugin_status

    def _codex_action_availability(self) -> dict[str, str]:
        requested = {
            "working": self.package.bindings.get("agent.working", "working"),
            "waiting": self.package.bindings.get("agent.waiting", "waiting"),
            "error": self.package.bindings.get("agent.error", "error"),
            "review": self.package.bindings.get("agent.success", "review"),
        }
        resolved: dict[str, str] = {}
        for semantic, action in requested.items():
            if action in self.package.animations:
                resolved[semantic] = action
                continue
            fallback = next(
                (candidate for candidate in self.package.fallbacks.get(action, ()) if candidate in self.package.animations),
                "idle",
            )
            resolved[semantic] = fallback if fallback == action else f"{fallback}（回退）"
        return resolved

    def _publish_external_event(self, event: object) -> None:
        if isinstance(event, PetEvent) and not self._shutdown:
            self.event_bus.publish(event)

    def _handle_codex_hook_event(self, event: PetEvent) -> bool:
        if not self.settings.codex_link_enabled:
            return False
        consumed = self.codex_link.consume(event)
        if consumed and event.event_name == "codex.hook":
            if event.source == "codex-hook":
                self.codex_link_source = "hook"
                self.codex_availability = replace(
                    self.codex_availability,
                    state=CodexAvailabilityState.ACTIVE,
                    message="联动正常",
                    codex_detected=True,
                    evidence=tuple(dict.fromkeys((*self.codex_availability.evidence, "plugin-hook"))),
                    selected_home=self.codex_availability.selected_home or self.codex_hook_manager.codex_home,
                )
                self.codex_discovery_timer.stop()
                self.codex_plugin_status = CodexPluginStatus.enabled()
                mark_confirmed = getattr(self.codex_plugin_manager, "mark_confirmed", None)
                if callable(mark_confirmed):
                    try:
                        mark_confirmed()
                    except Exception:  # noqa: BLE001 - 状态事件不能因收据写入失败而丢失。
                        LOGGER.warning("无法记录 Codex 插件确认状态", exc_info=True)
                self.codex_hook_status = CodexHookStatus(
                    "connected",
                    "完整联动 · 官方 Hook",
                    True,
                    self.codex_hook_status.token,
                )
                if self._settings_center_dialog is not None:
                    self._settings_center_dialog.set_codex_plugin_status(self.codex_plugin_status)
            elif event.source == "codex-log":
                self.codex_link_source = "log"
            self._refresh_codex_link_runtime_view()
        return consumed

    def _configure_codex_log_watcher(self) -> None:
        enabled = (
            self.settings.codex_link_enabled
            and self.settings.codex_link_log_fallback_enabled
            and self.codex_availability.can_watch
        )
        if enabled:
            if not self.codex_log_watcher.is_running:
                self.codex_log_watcher.start()
            self.codex_log_timer.start()
            if self.codex_link_source == "none":
                self.codex_link_source = "waiting"
        else:
            self.codex_log_timer.stop()
            if self.codex_log_watcher.is_running:
                self.codex_log_watcher.stop()
            if self.codex_link_source == "log" or not self.settings.codex_link_enabled:
                self.codex_link_source = "none"
        self._refresh_codex_link_runtime_view()

    def _refresh_codex_discovery(self) -> None:
        if self._shutdown:
            return
        if not self.settings.codex_link_enabled:
            self.codex_availability = CodexLinkAvailability(
                CodexAvailabilityState.DISABLED,
                "联动已关闭",
                False,
            )
            self.codex_discovery_timer.stop()
            self._configure_codex_log_watcher()
            return
        raw_override = getattr(self.settings, "codex_home_override", None)
        override = Path(raw_override) if isinstance(raw_override, str) and raw_override else None
        if override is None and not os.environ.get("CODEX_HOME"):
            self._schedule_codex_app_home_probe()
        try:
            availability = self.codex_discovery.discover(override)
        except Exception as error:  # noqa: BLE001 - 自动发现失败不能影响桌宠启动。
            LOGGER.warning("Codex 自动发现失败", exc_info=True)
            availability = CodexLinkAvailability(
                CodexAvailabilityState.NOT_DETECTED,
                "暂时无法检查 Codex，稍后会自动重试",
                False,
                technical_reason=str(error)[:500],
            )
        self.codex_availability = availability
        if _availability_selects_profile(availability):
            assert availability.selected_home is not None
            self._apply_codex_home(availability.selected_home)
        self._configure_codex_log_watcher()
        self._configure_external_event_server()
        if availability.state in {CodexAvailabilityState.READY, CodexAvailabilityState.ACTIVE}:
            self.codex_discovery_timer.stop()
        else:
            self.codex_discovery_timer.start()
        self._refresh_codex_link_runtime_view()

    def _schedule_codex_app_home_probe(self) -> None:
        if (
            not self._uses_default_codex_discovery
            or self._codex_app_home_probe_complete
            or self._codex_discovery_worker is not None
            or monotonic() < self._codex_app_home_probe_after
        ):
            return
        worker = Thread(
            target=self._codex_app_home_probe_worker,
            daemon=True,
            name="petnest-codex-home-probe",
        )
        self._codex_discovery_worker = worker
        self.codex_discovery_result_timer.start()
        worker.start()

    def _codex_app_home_probe_worker(self) -> None:
        try:
            home = _fetch_codex_home_for_discovery().expanduser().absolute()
        except Exception as error:  # noqa: BLE001 - worker returns a bounded diagnostic to the UI thread.
            self._codex_discovery_results.put((None, str(error)[:500]))
        else:
            self._codex_discovery_results.put((home, None))

    def _drain_codex_discovery_results(self) -> None:
        result: tuple[Path | None, str | None] | None = None
        while True:
            try:
                result = self._codex_discovery_results.get_nowait()
            except Empty:
                break
        if result is None:
            return
        self._codex_discovery_worker = None
        self.codex_discovery_result_timer.stop()
        home, error = result
        if home is not None:
            self._codex_app_home_cache = home
            self._codex_app_home_probe_complete = True
        else:
            self._codex_app_home_cache = None
            self._codex_app_home_probe_complete = False
            self._codex_app_home_probe_after = monotonic() + CODEX_DISCOVERY_RETRY_INTERVAL_MS / 1000
            if error:
                LOGGER.debug("Codex app-server Home 探测暂不可用：%s", error)
        if not self._shutdown:
            self._refresh_codex_discovery()

    def _apply_codex_home(self, codex_home: Path) -> None:
        resolved = codex_home.expanduser().resolve()
        self.codex_log_watcher.reconfigure(resolved)
        self.codex_hook_manager.set_codex_home(resolved)
        self.codex_hook_status = self.codex_hook_manager.inspect()
        self.codex_plugin_manager.set_codex_home(resolved)

    def _poll_codex_logs(self) -> None:
        if self._shutdown or not self.settings.codex_link_enabled:
            return
        events = self.codex_log_watcher.poll()
        for event in events:
            self.event_bus.publish(event)
        if events and self.codex_availability.state is not CodexAvailabilityState.ACTIVE:
            self.codex_availability = replace(
                self.codex_availability,
                state=CodexAvailabilityState.ACTIVE,
                message="联动正常",
            )
        if self.codex_log_watcher.status.state == "incompatible":
            reason = self.codex_log_watcher.status.message
            self.codex_availability = replace(
                self.codex_availability,
                state=CodexAvailabilityState.INCOMPATIBLE,
                message="当前 Codex 版本暂不支持基础联动",
                can_watch=False,
                technical_reason=reason,
            )
            self.codex_log_timer.stop()
            self.codex_log_watcher.stop()
            self.codex_discovery_timer.start()
        self._refresh_codex_link_runtime_view()

    def _refresh_codex_link_runtime_view(self) -> None:
        dialog = self._settings_center_dialog
        if dialog is not None and hasattr(dialog, "set_codex_link_runtime"):
            dialog.set_codex_availability(self.codex_availability)
            dialog.set_codex_link_runtime(self.codex_link_source, self.codex_log_watcher.status)

    def _handle_codex_snapshot(self, snapshot: CodexLinkSnapshot) -> None:
        if self._settings_center_dialog is not None:
            self._settings_center_dialog.set_codex_task_state(snapshot.state)
        if not self.settings.codex_link_enabled:
            self.codex_review_animation_timer.stop()
            self.window.clear_codex_status()
            return
        if snapshot.state == "review":
            if not self.codex_review_animation_timer.isActive():
                self.codex_review_animation_timer.start(self._codex_review_animation_duration_ms())
        else:
            self.codex_review_animation_timer.stop()
        if (
            sys.platform == "darwin"
            and self._settings_center_dialog is not None
            and self._settings_center_dialog.isVisible()
        ):
            # macOS 会把气泡的 Qt.Tool 映射为高于普通窗口的 NSPanel。
            # 设置中心开启时不允许它重新置顶，避免抢走对话框焦点。
            self.window.clear_codex_status()
            return
        if snapshot.state in {"waiting", "failed"}:
            if self.settings.codex_link_show_attention_bubbles:
                self.window.show_codex_status(snapshot)
            else:
                self.window.clear_codex_status()
            return
        if snapshot.unread_review_count > 0 and self.settings.codex_link_show_review_bubbles:
            self.window.show_codex_status(snapshot)
        else:
            self.window.clear_codex_status()

    def _activate_codex_status(self) -> None:
        self.codex_review_animation_timer.stop()
        self.codex_link.dismiss_reviews()
        self.window.clear_codex_status()

    def _dismiss_codex_status(self) -> None:
        self.codex_review_animation_timer.stop()
        self.codex_link.dismiss_reviews()
        self.window.clear_codex_status()

    def _codex_review_animation_duration_ms(self) -> int:
        action = self.package.bindings.get("agent.success", "review")
        definition = self.package.animations.get(action)
        if definition is None:
            action = next(
                (candidate for candidate in self.package.fallbacks.get(action, ()) if candidate in self.package.animations),
                "idle",
            )
            definition = self.package.animations.get(action)
        if definition is None or action == "idle":
            return 500
        if definition.frame_durations_ms:
            duration = sum(definition.frame_durations_ms)
        else:
            duration = round(max(1, len(definition.frames)) * 1000 / max(1, definition.fps))
        return max(500, min(duration, 10_000))

    def _finish_codex_review_animation(self) -> None:
        if self.codex_link.snapshot.state == "review":
            self.codex_link.finish_review_animation()

    def show_cursor_style_dialog(self) -> None:
        """保留托盘独立入口，但定位到设置中心的鼠标分类。"""
        self._show_settings_center("mouse_behavior")

    def _show_settings_center(self, initial_section: str) -> None:
        if self.settings.codex_link_enabled:
            self._refresh_codex_discovery()
        if sys.platform == "darwin":
            self.window.clear_codex_status()
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
        self.codex_plugin_status = self.codex_plugin_manager.inspect()
        codex_home = self.codex_hook_manager.codex_home
        # Qt.Tool 在 macOS 上是不可成为 key window 的 NSPanel。不能将
        # window-modal 设置对话框挂在这种窗口上，否则会破坏焦点和退出响应链。
        dialog_parent = None if sys.platform == "darwin" else self.window
        dialog = SettingsDialog(
            self.settings,
            dialog_parent,
            on_check_app_update=self._check_app_update_from_settings if sys.platform in APP_UPDATE_PLATFORMS else None,
            on_download_app_update=self._schedule_app_update_download if sys.platform in APP_UPDATE_PLATFORMS else None,
            on_unlock_codex_usage=self._unlock_codex_usage,
            codex_hook_status=self.codex_hook_status,
            codex_link_source=self.codex_link_source,
            codex_task_state=self.codex_link.snapshot.state,
            codex_log_status=self.codex_log_watcher.status,
            codex_action_availability=self._codex_action_availability(),
            codex_plugin_status=self.codex_plugin_status,
            codex_availability=self.codex_availability,
            codex_home_path=codex_home,
            on_set_codex_home_override=self._set_codex_home_override,
            on_configure_codex_plugin=self._configure_codex_plugin,
            on_recheck_codex_plugin=self._recheck_codex_plugin,
            on_remove_codex_plugin=self._remove_codex_plugin,
            on_open_pet_actions=lambda: self.show_pet_action_exchange_dialog(
                "导入动作",
                parent=self._settings_center_dialog,
            ),
            on_install_codex_hook=self._install_codex_hook,
            on_remove_codex_hook=self._remove_codex_hook,
            on_test_codex_animation=self._test_codex_link_animation,
            on_diagnose_codex_link=self._diagnose_codex_link,
            cursor_styles=self.cursor_catalog.discover(),
            supported_roles=supported_roles,
            keyboard_activity_supported=self.keyboard_activity_monitor.supported,
            keyboard_activity_status=self.keyboard_activity_monitor.status_message,
            auto_start_supported=bool(
                getattr(self.platform_adapter, "startup_supported", False)
            ),
            pet_preview_path=preview_path,
            initial_section=initial_section,
        )
        self._settings_center_dialog = dialog
        dialog.resource_section_opened.connect(self._handle_resource_section_opened)
        if self._pending_app_update is not None:
            dialog.set_app_update_available(self._pending_app_update)
        dialog.accepted.connect(lambda: self.apply_settings(dialog.updated_settings()))
        dialog.finished.connect(lambda _result: self._clear_settings_center(dialog))
        if sys.platform == "darwin":
            dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
            dialog.setWindowModality(Qt.WindowModality.NonModal)
            dialog.show()
            dialog.raise_()
            dialog.activateWindow()
        else:
            dialog.open()
        self._handle_resource_section_opened(initial_section)

    def _set_codex_home_override(self, home: Path | None) -> CodexLinkAvailability:
        if home is not None:
            availability = self.codex_discovery.discover(home)
            self.codex_availability = availability
            if availability.state is CodexAvailabilityState.NOT_DETECTED:
                self._refresh_codex_link_runtime_view()
                raise ValueError(availability.message)
            self.settings = replace(self.settings, codex_home_override=str(home))
            self.settings_manager.save(self.settings)
            if _availability_selects_profile(availability):
                assert availability.selected_home is not None
                self._apply_codex_home(availability.selected_home)
            self._configure_codex_log_watcher()
            self._configure_external_event_server()
            if availability.state in {CodexAvailabilityState.READY, CodexAvailabilityState.ACTIVE}:
                self.codex_discovery_timer.stop()
            else:
                self.codex_discovery_timer.start()
            self._refresh_codex_link_runtime_view()
            return availability
        self.settings = replace(
            self.settings,
            codex_home_override=None,
        )
        self.settings_manager.save(self.settings)
        self._refresh_codex_discovery()
        return self.codex_availability

    def _clear_settings_center(self, dialog: SettingsDialog) -> None:
        if self._settings_center_dialog is dialog:
            self._settings_center_dialog = None
            if sys.platform == "darwin" and not self._shutdown:
                self._handle_codex_snapshot(self.codex_link.snapshot)

    def _test_codex_link_animation(self) -> str:
        self.window.handle_pet_event(PetEvent("agent.working", source="codex-test", priority=100))
        QTimer.singleShot(
            1_500,
            lambda: self.window.handle_pet_event(PetEvent("agent.success", source="codex-test", priority=100)),
        )
        QTimer.singleShot(
            3_000,
            lambda: self.window.handle_pet_event(PetEvent("agent.idle", source="codex-test", priority=100)),
        )
        return "正在播放“任务进行中 → 任务完成 → 待机”；此测试只验证当前宠物动作。"

    def _diagnose_codex_link(self) -> str:
        if not self.settings.codex_link_enabled:
            return "联动已关闭。开启并保存后即可自动使用本地日志回退。"
        source = {
            "hook": "完整联动 · 官方 Hook",
            "log": "已联动 · 本地日志回退",
            "waiting": "等待新的 Codex 任务",
            "none": "尚未收到联动事件",
        }.get(self.codex_link_source, self.codex_log_watcher.status.message)
        plugin = self.codex_plugin_manager.inspect()
        fallback = "已开启" if self.settings.codex_link_log_fallback_enabled else "已关闭（仅精确连接）"
        listener = "监听正常" if self.external_server is not None and self.external_server.is_running else "监听未启动"
        return f"{source}；基础日志监听{fallback}；精确连接：{plugin.state}（{plugin.details}）；本机事件{listener}。"

    def _check_app_update_from_settings(self) -> None:
        """设置中心内联检查更新，不再打开独立更新窗口。"""
        self._schedule_app_update_check(force=True)

    def _handle_lan_firewall_status(self, status: LanFirewallStatus) -> None:
        self._lan_firewall_status = status
        dialog = self._lan_interaction_dialog
        if dialog is not None:
            dialog.set_firewall_status(
                status,
                repairing=self._lan_firewall_repairing,
                repair_message=self._lan_firewall_repair_message,
            )
        self._refresh_lan_firewall_notice()

    def _refresh_lan_firewall_notice(self) -> None:
        status = self._lan_firewall_status
        dismissed = self.settings.lan_firewall_dismissed_public_networks
        should_show = (
            self.settings.lan_interaction_enabled
            and status.requires_attention
            and status.public_network_key not in dismissed
            and self._lan_interaction_dialog is None
        )
        if should_show:
            self.window.show_lan_firewall_notice()
        else:
            self.window.clear_lan_firewall_notice()

    def _dismiss_lan_firewall_notice(self) -> None:
        key = self._lan_firewall_status.public_network_key
        if not key:
            return
        history = list(self.settings.lan_firewall_dismissed_public_networks)
        if key in history:
            history.remove(key)
        history.append(key)
        self.settings = replace(
            self.settings,
            lan_firewall_dismissed_public_networks=tuple(history[-20:]),
        )
        self.settings_manager.save(self.settings)
        self.window.clear_lan_firewall_notice()

    def _request_lan_firewall_repair(self) -> bool:
        if self._lan_firewall_repairing or not self._lan_firewall_status.requires_attention:
            return False
        if not self.lan_firewall_advisor.request_repair():
            return False
        self._lan_firewall_repairing = True
        self._lan_firewall_repair_message = ""
        if self._lan_interaction_dialog is not None:
            self._lan_interaction_dialog.set_firewall_status(
                self._lan_firewall_status,
                repairing=True,
            )
        return True

    def _handle_lan_firewall_repair_finished(self, succeeded: bool, message: str) -> None:
        self._lan_firewall_repairing = False
        self._lan_firewall_repair_message = "" if succeeded else message
        if self._lan_interaction_dialog is not None:
            self._lan_interaction_dialog.set_firewall_status(
                self._lan_firewall_status,
                repair_message=message,
            )
        if succeeded:
            self.settings = replace(
                self.settings,
                lan_firewall_dismissed_public_networks=(),
            )
            self.settings_manager.save(self.settings)
            self.window.clear_lan_firewall_notice()
            self.lan_service.refresh_connections()

    def show_lan_interaction_dialog(self) -> None:
        """打开附近设备与远程伙伴的统一互动入口。"""
        self._configure_lan_service()
        self._configure_remote_interaction_service()
        self.lan_service.discover()
        effects = self._discover_effects()
        dialog = LanInteractionDialog(
            settings=self.settings,
            peers=self.lan_service.peers(),
            pool_members=self.lan_pool_sync.member_views(),
            remote_peers=self.remote_interaction_service.peers(),
            effects=effects,
            on_send=self.lan_service.send_interaction,
            on_chat_send=self.lan_service.send_chat,
            on_nickname_changed=lambda nickname: self.apply_settings(
                replace(self.settings, nickname=nickname)
            ),
            on_alert_membership_changed=self._set_lan_alert_group_joined,
            on_update_peer_address=self._update_lan_peer_address,
            on_forget_peer=lambda device_id: self.lan_service.forget_peer(device_id),
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
            firewall_status=self._lan_firewall_status,
            on_allow_public_firewall=self._request_lan_firewall_repair,
            parent=self.window,
        )
        self._lan_interaction_dialog = dialog
        self.window.clear_lan_firewall_notice()
        self.lan_firewall_advisor.request_check()
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
        pool_refresh = lambda: dialog.set_pool_members(self.lan_pool_sync.member_views())
        self.lan_pool_sync.roster_changed.connect(pool_refresh)
        dialog.exec()
        self._lan_interaction_dialog = None
        self.lan_pool_sync.roster_changed.disconnect(pool_refresh)
        updated = dialog.settings
        if (
            updated.nickname != self.settings.nickname
            or updated.lan_interaction_enabled != self.settings.lan_interaction_enabled
            or updated.lan_group_chat_notifications_enabled
            != self.settings.lan_group_chat_notifications_enabled
            or updated.lan_alert_group_joined != self.settings.lan_alert_group_joined
            or updated.remote_interaction_enabled != self.settings.remote_interaction_enabled
        ):
            self.apply_settings(updated)
        self._refresh_lan_firewall_notice()

    def _update_lan_peer_address(self, device_id: str, ip_address: str) -> bool:
        return self.lan_service.update_saved_peer_address(device_id, ip_address)

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
        """兼容旧托盘调用，定位到统一窗口的精灵图导入页。"""
        self.show_pet_action_exchange_dialog("导入宠物")

    def show_work_finish_import_dialog(self) -> None:
        """兼容旧托盘调用，定位到统一窗口的动作导入页。"""
        self.show_pet_action_exchange_dialog("导入动作")

    def show_pet_action_exchange_dialog(
        self,
        page: str = "导入宠物",
        *,
        parent: QWidget | None = None,
    ) -> None:
        """打开统一宠物/动作交换中心，并连接安装后的运行时重载。"""
        dialog_parent = parent or self.window
        if self._pet_action_exchange_dialog is None:
            dialog = PetActionExchangeDialog(
                self.packages,
                self.pets_root,
                current_pet_id=self.package.identifier,
                save_animation_timelines=self._save_animation_timelines,
                is_pet_locked=self._is_pet_locked_for_exchange,
                pet_store_service=self.pet_store_service,
                parent=dialog_parent,
            )
            dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
            dialog.pet_installed.connect(self._handle_pet_exchange_installed)
            dialog.store_pet_installed.connect(self._handle_store_pet_installed)
            dialog.actions_installed.connect(self._handle_actions_exchange_installed)
            dialog.finished.connect(lambda _result: self._clear_exchange_dialog(dialog))
            dialog.destroyed.connect(lambda *_args: self._clear_exchange_dialog(dialog))
            self._pet_action_exchange_dialog = dialog
        dialog = self._pet_action_exchange_dialog
        if dialog.parentWidget() is not dialog_parent:
            dialog.setParent(dialog_parent, dialog.windowFlags())
        try:
            dialog.select_page(page)
        except ValueError:
            dialog.select_page("导入宠物")
        if parent is not None:
            dialog.open()
        else:
            dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _clear_exchange_dialog(self, dialog: PetActionExchangeDialog) -> None:
        if self._pet_action_exchange_dialog is dialog:
            self._pet_action_exchange_dialog = None

    def _is_pet_locked_for_exchange(self, identifier: str) -> bool:
        return identifier == self.package.identifier and self.work_finish_reminder.is_visible

    def _handle_pet_exchange_installed(self, identifier: str, result: object) -> None:
        """刷新宠物库并在当前宠物更新后安全重载；失败时尝试从导入前备份恢复。"""
        self._synchronize_pet_library()
        self.packages = self.loader.discover(self.pets_root)
        if self.tray is not None:
            self.tray.set_pet_names({item.identifier: item.name for item in self.packages})
        if not self.switch_pet(identifier):
            if identifier == self.package.identifier and isinstance(result, PetImportResult):
                self._restore_pet_from_exchange_backup(result)
            else:
                QMessageBox.warning(self.window, "无法载入宠物", f"宠物 {identifier} 已导入，但当前运行时未能载入。")
        if self._pet_action_exchange_dialog is not None:
            self._pet_action_exchange_dialog.refresh_packages(self.packages, self.package.identifier)

    def _handle_store_pet_installed(self, identifier: str, result: object) -> None:
        """Adopt or update a store pet without switching to a newly adopted pet."""

        if not isinstance(result, PetStoreInstallResult):
            LOGGER.error("宠物商店返回了未知安装结果：%r", result)
            return
        self._synchronize_pet_library()
        discovered = self.loader.discover(self.pets_root)
        installed = next((item for item in discovered if item.identifier == identifier), None)
        is_current = identifier == self.package.identifier
        success = installed is not None
        if success:
            self.packages = discovered
            if is_current:
                success = self.reload_current_pet(synchronize=False)
        if not success:
            try:
                self.pet_store_service.rollback_install(result)
            except Exception as error:  # noqa: BLE001 - report a failed disk rollback explicitly.
                LOGGER.exception("宠物商店安装和回滚均失败：%s", identifier)
                message = f"宠物安装未能载入，且自动恢复失败：{error}"
                if self._pet_action_exchange_dialog is not None:
                    self._pet_action_exchange_dialog.complete_store_install_failure(message)
                QMessageBox.critical(self.window, "无法恢复宠物", message)
                return
            self.packages = self.loader.discover(self.pets_root)
            if is_current:
                self.reload_current_pet(synchronize=False)
            message = "宠物安装未能载入，已恢复安装前内容。"
            if self._pet_action_exchange_dialog is not None:
                self._pet_action_exchange_dialog.complete_store_install_failure(message)
                self._pet_action_exchange_dialog.refresh_packages(
                    self.packages, self.package.identifier
                )
            QMessageBox.warning(self.window, "宠物安装未生效", message)
            return

        if self.tray is not None:
            self.tray.set_pet_names({item.identifier: item.name for item in self.packages})
        message = "宠物更新完成" if result.pet_import.replaced_existing else "宠物领养完成"
        if self._pet_action_exchange_dialog is not None:
            self._pet_action_exchange_dialog.complete_store_install(message)
            self._pet_action_exchange_dialog.refresh_packages(
                self.packages, self.package.identifier
            )
        else:
            self.pet_store_service.confirm_install(result)

    def _handle_actions_exchange_installed(self, identifier: str, result: object) -> None:
        self.packages = self.loader.discover(self.pets_root)
        if self.tray is not None:
            self.tray.set_pet_names({item.identifier: item.name for item in self.packages})
        if identifier == self.package.identifier:
            if self.reload_current_pet(synchronize=False):
                self._finalize_action_install(result)
                self._complete_action_install(identifier, result)
            else:
                rollback = getattr(result, "rollback", None)
                if not callable(rollback):
                    message = "动作已安装，但当前宠物重新载入失败；安装结果不支持自动恢复。"
                    self._complete_action_install_failure(message)
                    QMessageBox.warning(
                        self.window,
                        "无法载入动作",
                        message,
                    )
                else:
                    try:
                        warnings = tuple(rollback())
                    except Exception as error:  # noqa: BLE001 - 必须报告磁盘回滚的真实失败原因。
                        LOGGER.exception("动作安装后的运行时重载和配置回滚均失败")
                        message = f"当前宠物重新载入失败，且旧配置恢复失败：{error}"
                        self._complete_action_install_failure(message)
                        QMessageBox.critical(
                            self.window,
                            "无法恢复动作",
                            message,
                        )
                    else:
                        for warning in warnings:
                            LOGGER.warning("动作安装回滚后的资源清理未完成：%s", warning)
                        self.packages = self.loader.discover(self.pets_root)
                        if self.reload_current_pet(synchronize=False):
                            message = "新动作无法载入，已恢复导入前的宠物配置和运行状态。"
                            self._complete_action_install_failure(message)
                            QMessageBox.warning(
                                self.window,
                                "动作导入未生效",
                                message,
                            )
                        else:
                            message = "旧配置已经恢复，但当前宠物仍无法重新载入；请重新启动 PetNest。"
                            self._complete_action_install_failure(message)
                            QMessageBox.critical(
                                self.window,
                                "无法恢复动作",
                                message,
                            )
        else:
            self._finalize_action_install(result)
            self._complete_action_install(identifier, result)
        if self._pet_action_exchange_dialog is not None:
            self._pet_action_exchange_dialog.refresh_packages(self.packages, self.package.identifier)

    @staticmethod
    def _finalize_action_install(result: object) -> None:
        finalize = getattr(result, "finalize", None)
        if not callable(finalize):
            return
        try:
            warnings = tuple(finalize())
        except Exception:  # noqa: BLE001 - 旧资源清理失败不能推翻已成功的配置提交。
            LOGGER.exception("动作更新已生效，但旧资源清理失败")
            return
        for warning in warnings:
            LOGGER.warning("动作更新已生效，但旧资源清理未完成：%s", warning)

    def _complete_action_install(self, identifier: str, result: object) -> None:
        installed = getattr(result, "installed", ())
        count = len(installed) if isinstance(installed, (tuple, list)) else 0
        package = next((item for item in self.packages if item.identifier == identifier), None)
        pet_name = package.name if package is not None else identifier
        message = f"已导入 {count} 个动作到 {pet_name}。"
        dialog = self._pet_action_exchange_dialog
        complete = getattr(dialog, "complete_action_install", None) if dialog is not None else None
        if callable(complete):
            complete(message)
        QMessageBox.information(self.window, "动作安装完成", message)

    def _complete_action_install_failure(self, message: str) -> None:
        dialog = self._pet_action_exchange_dialog
        complete = getattr(dialog, "complete_action_install_failure", None) if dialog is not None else None
        if callable(complete):
            complete(message)

    def _restore_pet_from_exchange_backup(self, result: PetImportResult) -> None:
        if result.backup_path is None:
            QMessageBox.critical(self.window, "无法恢复宠物", "重载失败且没有可用备份，请从托盘菜单重新显示宠物。")
            return
        try:
            import_pet_package(
                result.backup_path,
                self.pets_root,
                PetImportOptions(create_backup=False),
            )
            self.packages = self.loader.discover(self.pets_root)
            self.reload_current_pet()
        except PetPackageImportError as error:
            LOGGER.exception("从宠物导入备份恢复失败：%s", error)
            QMessageBox.critical(self.window, "无法恢复宠物", f"已保留备份文件：{result.backup_path}\n原因：{error}")

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
        """兼容旧入口，定位到统一中心的动作编辑页。"""
        self.show_pet_action_exchange_dialog("编辑动作")

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
        self._run_shutdown_step("清理 Codex 联动状态", self.codex_link.clear)
        self._run_shutdown_step("隐藏 Codex 状态气泡", self.window.clear_codex_status)
        self._run_shutdown_step("隐藏防火墙提醒", self.window.clear_lan_firewall_notice)
        self._run_shutdown_step("隐藏互动提示", self.window.clear_interaction_bubble)
        self._run_shutdown_step("停止互动动效", self.window.clear_effect)
        self._work_finish_visibility_lease.cancel()
        self._run_shutdown_step("隐藏打卡卡片", lambda: self._apply_pet_visibility(False))
        self._run_shutdown_step("关闭下班全屏提醒", self.work_finish_reminder.shutdown)
        self._run_shutdown_step("关闭危险预警层", self.danger_alert_overlay.stop)
        self._run_shutdown_step("隐藏宠物窗口", self.window.hide)
        server, self.external_server = self.external_server, None
        if server is not None:
            self._run_shutdown_step("停止外部事件服务", server.stop)
        self._run_shutdown_step("停止系统空闲计时器", self.system_idle_timer.stop)
        self._run_shutdown_step("停止键盘活动计时器", self.keyboard_activity_timer.stop)
        if self._keyboard_monitor_running:
            self._run_shutdown_step("停止键盘活动监听", self.keyboard_activity_monitor.stop)
            self._keyboard_monitor_running = False
        self._run_shutdown_step("清理键盘工作状态", self.work_activity.reset_keyboard)
        self._run_shutdown_step("停止鼠标跟随计时器", self.mouse_follow_timer.stop)
        self._run_shutdown_step("停止远程资源结果计时器", self.resource_result_timer.stop)
        self._run_shutdown_step("停止程序更新结果计时器", self.app_update_result_timer.stop)
        self._run_shutdown_step("停止程序更新检查计时器", self.app_update_check_timer.stop)
        self._run_shutdown_step("停止程序启动更新计时器", self.app_update_startup_timer.stop)
        self._run_shutdown_step("停止自动启动修复计时器", self.startup_repair_timer.stop)
        self._run_shutdown_step("停止 Codex 日志轮询计时器", self.codex_log_timer.stop)
        self._run_shutdown_step("停止 Codex 自动发现计时器", self.codex_discovery_timer.stop)
        self._run_shutdown_step("停止 Codex 发现结果计时器", self.codex_discovery_result_timer.stop)
        self._run_shutdown_step("停止 Codex review 动画计时器", self.codex_review_animation_timer.stop)
        self._run_shutdown_step("停止防火墙状态检查", self.lan_firewall_advisor.stop)
        self._run_shutdown_step("停止 Codex 日志回退", self.codex_log_watcher.stop)
        self._run_shutdown_step("停止倒计时计时器", self.work_countdown.timer.stop)
        self._run_shutdown_step("停止 Codex 局域网同步", self.codex_usage_sync.stop)
        self._run_shutdown_step("停止预警池名单同步", self.lan_pool_sync.stop)
        self._run_shutdown_step("停止伙伴辅助发现", self.lan_peer_discovery.stop)
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

    def _configure_external_event_server(self, *, restart: bool = False) -> None:
        precise_source_configured = (
            self.codex_hook_status.installed
            or self.codex_plugin_manager.has_install_receipt()
        )
        needed = self.settings.external_event_server_enabled or (
            self.settings.codex_link_enabled and precise_source_configured
        )
        if self.external_server is not None and (restart or not needed):
            server, self.external_server = self.external_server, None
            server.stop()
        if needed and self.external_server is None:
            self._start_external_server()

    def _start_external_server(self) -> None:
        token: str | None = None
        if self.settings.codex_link_enabled:
            try:
                self.codex_hook_manager.set_port(self.settings.external_event_port)
                token = self.codex_hook_manager.ensure_metadata().token
            except Exception as error:  # noqa: BLE001 - 普通桌宠功能仍需继续运行。
                self.codex_hook_status = CodexHookStatus("error", f"Codex 联动元数据不可用：{error}", False)
                LOGGER.warning("Codex 联动元数据不可用：%s", error)
        server = ExternalEventServer(
            self.event_bus,
            port=self.settings.external_event_port,
            codex_token=token,
            event_sink=self._external_event_relay.event_received.emit,
        )
        if server.start():
            self.external_server = server
            if self.settings.codex_link_enabled and token is not None and server.port != self.settings.external_event_port:
                self.codex_hook_manager.set_port(server.port)
                self.codex_hook_manager.ensure_metadata()
        else:
            if self.settings.codex_link_enabled:
                self.codex_hook_status = CodexHookStatus(
                    "error",
                    f"本机端口 {self.settings.external_event_port} 被占用，Codex 联动未启动",
                    self.codex_hook_status.installed,
                    self.codex_hook_status.token,
                )
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
        self._resource_status = "checking"
        self._render_resource_status()
        worker.start()

    def _resource_check_worker(self, force: bool) -> None:
        try:
            result = self.remote_resource_update.check(force=force)
        except Exception as error:  # noqa: BLE001 - resource checks must not stop the app.
            LOGGER.exception("远程资源检查线程异常")
            result = RemoteResourceCheckResult(False, False, self.remote_resource_update.update_available, error=str(error))
        self._resource_results.put(("check", current_thread(), result))

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
        self._resource_status = "downloading"
        self._resource_progress = (0, None, None, False)
        self._render_resource_status()
        worker.start()

    def _resource_apply_worker(self) -> None:
        worker_token = current_thread()
        resource_type: str | None = None
        display_name: str | None = None
        archive = False
        last_progress = 0

        def report_resource_started(resource: RemoteResource | None) -> None:
            nonlocal resource_type, display_name, archive
            archive = resource is None
            resource_type = resource.type if resource is not None else None
            raw_name = resource.metadata.get("name") if resource is not None else None
            display_name = raw_name if isinstance(raw_name, str) else None
            self._resource_results.put(
                ("progress", worker_token, (last_progress, resource_type, display_name, archive))
            )

        def report_progress(progress: int) -> None:
            nonlocal last_progress
            last_progress = max(last_progress, max(0, min(100, int(progress))))
            self._resource_results.put(
                ("progress", worker_token, (last_progress, resource_type, display_name, archive))
            )

        def report_resource_applied(_identifier: str) -> None:
            # The cache switches each verified resource atomically. Queue the
            # refresh so Qt-owned catalogs and windows are touched on the GUI
            # thread while the remaining resources continue downloading.
            self._resource_results.put(("view", worker_token, None))

        try:
            result = self.remote_resource_update.apply(
                progress=report_progress,
                on_resource_applied=report_resource_applied,
                on_resource_started=report_resource_started,
            )
        except Exception as error:  # noqa: BLE001 - failed update is reported in the UI.
            LOGGER.exception("远程资源更新线程异常")
            result = RemoteResourceApplyResult(False, error=str(error))
        self._resource_results.put(("apply", worker_token, result))

    def _handle_resource_section_opened(self, section: str) -> None:
        if section not in {"mouse_behavior", "countdown"} or self._shutdown:
            return
        if self._resource_worker is not None and self._resource_worker.is_alive():
            self._render_resource_status()
            return
        if self.remote_resource_update.update_available:
            self._schedule_resource_apply()
        else:
            self._schedule_resource_check(force=False)

    def _drain_resource_results(self) -> None:
        deferred_apply = self._deferred_resource_apply
        if deferred_apply is not None:
            self._deferred_resource_apply = None
            worker_token, result = deferred_apply
            if self._resource_worker is worker_token:
                self._resource_worker = None
            view_refreshed = self._resource_view_refreshed_worker is worker_token
            if view_refreshed:
                self._resource_view_refreshed_worker = None
            self._handle_resource_apply_result(result, view_already_refreshed=view_refreshed)
            return

        progress_rendered = False
        for _ in range(self._resource_results.qsize()):
            try:
                kind, worker_token, payload = self._resource_results.get_nowait()
            except Empty:
                return
            if (
                kind == "apply"
                and progress_rendered
                and isinstance(payload, RemoteResourceApplyResult)
            ):
                self._deferred_resource_apply = (worker_token, payload)
                return
            if kind in {"check", "apply"} and self._resource_worker is worker_token:
                self._resource_worker = None
            if kind == "check" and isinstance(payload, RemoteResourceCheckResult):
                self._handle_resource_check_result(payload)
            elif kind == "apply" and isinstance(payload, RemoteResourceApplyResult):
                view_refreshed = self._resource_view_refreshed_worker is worker_token
                if view_refreshed:
                    self._resource_view_refreshed_worker = None
                self._handle_resource_apply_result(payload, view_already_refreshed=view_refreshed)
            elif kind == "progress" and isinstance(payload, tuple) and len(payload) == 4:
                self._handle_resource_progress(payload)
                progress_rendered = True
            elif kind == "view":
                self._refresh_resource_directories(verify_files=False)
                self._resource_view_refreshed_worker = worker_token

    def _handle_resource_progress(
        self,
        progress: tuple[int, str | None, str | None, bool],
    ) -> None:
        self._resource_status = "downloading"
        self._resource_progress = progress
        self._render_resource_status()

    def _handle_resource_check_result(self, result: RemoteResourceCheckResult) -> None:
        if result.error:
            LOGGER.warning("远程资源检查失败：%s", result.error)
            self._resource_status = "error"
            self._render_resource_status()
        elif result.update_available:
            self._schedule_resource_apply()
        else:
            self._resource_status = "ready"
            self._render_resource_status()

    def _handle_resource_apply_result(
        self,
        result: RemoteResourceApplyResult,
        *,
        view_already_refreshed: bool = False,
    ) -> None:
        if (result.updated_resource_ids or result.resource_view_changed) and not view_already_refreshed:
            self._refresh_resource_directories()
        if result.applied:
            self._resource_status = "ready"
            self._render_resource_status()
            return
        if result.partial or result.error:
            self._resource_status = "error"
            self._render_resource_status()
        else:
            self._resource_status = "idle"
            self._render_resource_status()
        if result.error:
            LOGGER.warning("远程资源更新失败：%s", result.error)

    def _render_resource_status(self) -> None:
        dialog = self._settings_center_dialog
        if dialog is None:
            return
        if self._resource_status == "checking":
            dialog.set_resource_checking()
        elif self._resource_status == "downloading":
            percentage, resource_type, display_name, archive = self._resource_progress
            dialog.set_resource_downloading(
                percentage,
                resource_type=resource_type,
                display_name=display_name,
                archive=archive,
            )
        elif self._resource_status == "ready":
            dialog.set_resource_ready()
        elif self._resource_status == "error":
            dialog.set_resource_error()
        else:
            dialog.clear_resource_status()

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
        if self._settings_center_dialog is not None:
            self._settings_center_dialog.set_cursor_styles(self.cursor_catalog.discover())
        countdown_root = self.resource_directory / "countdown" if self.resource_directory is not None else None
        self.window.reload_countdown_skins(countdown_root)

    def _configure_lan_service(self) -> None:
        if os.environ.get("PETNEST_TEST_DISABLE_LAN", "").strip() == "1":
            self.lan_pool_sync.stop()
            self.lan_peer_discovery.stop()
            self.lan_service.stop()
            return
        if self.settings.lan_interaction_enabled:
            if not self.lan_service.start():
                self.lan_pool_sync.stop()
                self.lan_peer_discovery.stop()
                LOGGER.warning("局域网互动未启用，桌宠仍可正常使用")
                return
            self.lan_peer_discovery.start()
            self.lan_pool_sync.start()
            self.lan_pool_sync.set_local_joined(
                self.settings.lan_alert_group_joined,
                ip_address=self._pool_local_ip_address(),
                port=self.lan_service.port,
            )
        else:
            self.lan_pool_sync.stop()
            self.lan_peer_discovery.stop()
            self.lan_service.stop()

    @staticmethod
    def _pool_local_ip_address() -> str:
        for entry in qt_interface_ipv4():
            if (
                entry.is_up
                and entry.is_running
                and not entry.is_loopback
                and not entry.address.startswith("169.254.")
            ):
                return entry.address
        return "127.0.0.1"

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
        self.event_bus.publish(PetEvent(EventName.INTERACTION_MESSAGE, source="interaction"))
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
        self.event_bus.publish(PetEvent(EventName.INTERACTION_MESSAGE, source="chat"))
        LOGGER.info("收到局域网聊天：%s", sender)

    def _pet_screen_geometry(self) -> QRect:
        center = self.window.frameGeometry().center()
        screen = QGuiApplication.screenAt(center) or QGuiApplication.primaryScreen()
        if screen is not None:
            return screen.geometry()
        return self.window.screen().geometry()

    def _handle_danger_alert(self, alert: DangerAlert) -> None:
        self.danger_alert_overlay.show_alert(
            alert.alert_id,
            alert.sender_name,
            self._pet_screen_geometry(),
            alert.message,
        )
        LOGGER.info("收到局域网危险预警：%s", alert.sender_name)

    def _handle_danger_alert_delivery(self, result: DangerAlertDeliveryResult) -> None:
        acknowledged = len(result.acknowledged_device_ids)
        total = len(result.target_device_ids)
        if acknowledged == total:
            message = f"预警已送达 {acknowledged} 人"
        else:
            peers = {peer.device_id: peer.display_name for peer in self.lan_service.peers()}
            missing = [
                peers.get(device_id, device_id[-4:].upper())
                for device_id in result.target_device_ids
                if device_id not in result.acknowledged_device_ids
            ]
            message = f"已送达 {acknowledged}/{total}，{'、'.join(missing)}未响应"
        self.window.show_interaction_bubble(message)

    def _configure_system_idle_timer(self) -> None:
        if self.settings.system_idle_enabled:
            self.system_idle_timer.start()
            self._check_system_idle()
        else:
            self.system_idle_timer.stop()
            self._system_idle_monitor.reset()

    def _configure_keyboard_activity(self) -> None:
        should_run = (
            self.settings.keyboard_working_enabled
            and self.keyboard_activity_monitor.supported
        )
        if should_run and not self._keyboard_monitor_running:
            self._keyboard_monitor_running = self.keyboard_activity_monitor.start(
                self._keyboard_activity_relay.activity.emit
            )
            if not self._keyboard_monitor_running:
                self.keyboard_activity_timer.stop()
                self.work_activity.reset_keyboard()
        elif not should_run and self._keyboard_monitor_running:
            self.keyboard_activity_monitor.stop()
            self._keyboard_monitor_running = False
        if not should_run:
            self.keyboard_activity_timer.stop()
            self.work_activity.reset_keyboard()

    def _handle_keyboard_activity(self) -> None:
        if (
            self._shutdown
            or not self.settings.keyboard_working_enabled
            or not self._keyboard_monitor_running
        ):
            return
        self.work_activity.keyboard_activity_started()
        self.keyboard_activity_timer.start()

    def _finish_keyboard_activity(self) -> None:
        self.keyboard_activity_timer.stop()
        self.work_activity.keyboard_activity_stopped()

    def _check_system_idle(self) -> None:
        if not self.settings.system_idle_enabled:
            return
        idle_seconds = self.platform_adapter.get_idle_seconds()
        if idle_seconds is None:
            return
        if (
            self.work_activity.effective_event != "agent.idle"
            and idle_seconds >= self._system_idle_monitor.bored_seconds
        ):
            return
        event_name = self._system_idle_monitor.update(idle_seconds)
        if event_name is not None:
            if event_name == "system.wake" and self.work_activity.keyboard_active:
                return
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
            work_finish_state=state_from_dict(self.settings.work_finish_state),
            on_work_finish_state=self._record_work_finish_state,
            on_work_finish_prompt=self._show_work_finish_prompt,
        )

    def _record_work_finish_state(self, state: WorkFinishState | None) -> None:
        """原子保存当天的提醒/加班/已下班状态。"""
        serialized = state_to_dict(state)
        if serialized == self.settings.work_finish_state:
            return
        self.settings = replace(self.settings, work_finish_state=serialized)
        self.settings_manager.save(self.settings)
        if state is None or state.status == "finished":
            self._close_work_finish_reminder()

    def _show_work_finish_prompt(self, state: WorkFinishState) -> None:
        """在桌宠所在屏幕显示动画和独立按钮层。"""
        screen = self.window.screen() or QGuiApplication.primaryScreen()
        if screen is None:
            LOGGER.warning("没有可用屏幕，无法显示下班全屏提醒")
            self.work_countdown.set_work_finish_prompt_visible(False)
            return
        prompt_started_at = state.prompt_started_at or datetime.now().astimezone()
        self._hide_pet_for_work_finish()
        try:
            self.work_finish_reminder.show_for(
                self.package,
                screen.geometry(),
                prompt_started_at,
                available_geometry=screen.availableGeometry(),
            )
        except Exception:
            self._close_work_finish_reminder()
            raise
        self.work_countdown.set_work_finish_prompt_visible(True)

    def _continue_overtime(self) -> None:
        self._hide_work_finish_reminder_layers()
        self.work_countdown.continue_overtime()
        self._restore_pet_after_work_finish()

    def _finish_work(self) -> None:
        self._hide_work_finish_reminder_layers()
        self.work_countdown.finish_work()

    def _dismiss_work_finish_reminder(self) -> None:
        """把窗口管理器发起的关闭收敛为当天已下班，避免每秒重弹。"""
        if self._shutdown:
            return
        self._hide_work_finish_reminder_layers()
        self.work_countdown.finish_work()

    def _hide_work_finish_reminder_layers(self) -> None:
        self.work_finish_reminder.hide()
        self.work_countdown.set_work_finish_prompt_visible(False)

    def _close_work_finish_reminder(self) -> None:
        self._hide_work_finish_reminder_layers()
        self._restore_pet_after_work_finish()

    def _refresh_visible_work_finish_reminder(self) -> None:
        state = self.work_countdown.work_finish_state
        if self.work_finish_reminder.is_visible and state is not None and state.status == "prompting":
            self._show_work_finish_prompt(state)

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


def _bring_codex_window_to_front() -> bool:
    """只尝试前置现有 Codex 窗口，不启动程序或打开不稳定深链。"""
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        user32 = ctypes.windll.user32
        found: list[int] = []
        callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        @callback_type
        def visit(window_handle: int, _parameter: int) -> bool:
            if not user32.IsWindowVisible(window_handle):
                return True
            length = user32.GetWindowTextLengthW(window_handle)
            if length <= 0:
                return True
            title = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(window_handle, title, length + 1)
            if "codex" in title.value.casefold():
                found.append(window_handle)
                return False
            return True

        user32.EnumWindows(visit, 0)
        if not found:
            return False
        user32.ShowWindow(found[0], 9)  # SW_RESTORE
        return bool(user32.SetForegroundWindow(found[0]))
    except (AttributeError, OSError):
        LOGGER.debug("无法前置 Codex 窗口", exc_info=True)
        return False


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
