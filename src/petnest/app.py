"""PetNest 应用装配：将纯核心、Qt 窗口和本地事件服务连接起来。"""

from __future__ import annotations

from dataclasses import replace
import logging
from pathlib import Path
import sys

from PySide6.QtCore import QPoint, QTimer
from PySide6.QtWidgets import QApplication

from petnest.core.event_bus import EventBus
from petnest.core.package_loader import PackageLoader
from petnest.core.settings_manager import SettingsManager
from petnest.core.system_idle_monitor import SystemIdleMonitor
from petnest.events.external_event_server import ExternalEventServer
from petnest.logging_config import configure_logging
from petnest.models.event import PetEvent
from petnest.models.pet_package import PetPackage
from petnest.models.settings import AnimationOverride, Settings
from petnest.ui.animation_editor_dialog import AnimationEditorDialog
from petnest.platforms import PlatformEventAdapter, create_platform_adapter
from petnest.ui.pet_window import PetWindow
from petnest.ui.settings_dialog import SettingsDialog
from petnest.ui.spritesheet_import_dialog import SpriteSheetImportDialog
from petnest.ui.tray_icon import PetTrayIcon

LOGGER = logging.getLogger(__name__)


def bundled_pets_directory() -> Path:
    """定位开发环境或 PyInstaller onedir 产物内的只读宠物素材。"""
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root is not None:
        return Path(frozen_root) / "pets"
    return Path(__file__).resolve().parents[2] / "pets"


class PetNest:
    """第一阶段桌宠运行时，负责有序启动、宠物切换和有序退出。"""

    def __init__(
        self,
        *,
        pets_root: Path | None = None,
        settings_manager: SettingsManager | None = None,
        platform_adapter: PlatformEventAdapter | None = None,
        enable_tray: bool = True,
    ) -> None:
        if QApplication.instance() is None:
            raise RuntimeError("创建 PetNest 前必须先创建 QApplication")
        self.settings_manager = settings_manager or SettingsManager()
        self.settings = self.settings_manager.load()
        self.pets_root = pets_root or bundled_pets_directory()
        self.loader = PackageLoader()
        self.packages = [self._apply_animation_overrides(item) for item in self.loader.discover(self.pets_root)]
        if not self.packages:
            raise RuntimeError(f"未找到可用宠物包：{self.pets_root}")
        self.package = self._select_package(self.settings.current_pet_id)
        self.event_bus = EventBus()
        self.window = PetWindow(self.package, position_saved=self._save_window_position)
        self._restore_window_settings()
        self.event_bus.subscribe(self.window.handle_pet_event)
        self.platform_adapter = platform_adapter or create_platform_adapter()
        self._system_idle_monitor = self._new_system_idle_monitor(self.settings)
        self.system_idle_timer = QTimer(self.window)
        self.system_idle_timer.setInterval(1_000)
        self.system_idle_timer.timeout.connect(self._check_system_idle)
        self.external_server: ExternalEventServer | None = None
        self._shutdown = False
        self.tray: PetTrayIcon | None = (
            PetTrayIcon(
                self.window,
                pet_names={item.identifier: item.name for item in self.packages},
                on_switch=self.switch_pet,
                on_reload=self.reload_current_pet,
                on_import=self.show_spritesheet_import_dialog,
                on_edit_animations=self.show_animation_editor_dialog,
                on_settings=self.show_settings_dialog,
                on_quit=self.shutdown,
            )
            if enable_tray
            else None
        )

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
        if self.tray is not None:
            self.tray.show()
        self.window.show()
        LOGGER.info("PetNest 已启动，宠物包：%s", self.package.identifier)

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
        return True

    def reload_current_pet(self) -> bool:
        """重新从磁盘校验并载入当前包，失败时保留现有资源。"""
        previous = self.package
        position = self.window.pos()
        try:
            reloaded = self._apply_animation_overrides(self.loader.load(previous.root))
            self.window.load_package(reloaded)
            self.window.move(self.window.clamp_position(position))
        except (OSError, ValueError, RuntimeError):
            LOGGER.exception("重新加载宠物包失败：%s", previous.identifier)
            return False
        self.package = reloaded
        self.packages = [reloaded if item.identifier == reloaded.identifier else item for item in self.packages]
        return True

    def apply_settings(self, settings: Settings) -> None:
        """立即应用可安全即时修改的设置，并持久化其非敏感值。"""
        idle_configuration_changed = (
            settings.system_idle_enabled != self.settings.system_idle_enabled
            or settings.system_bored_seconds != self.settings.system_bored_seconds
            or settings.system_sleep_seconds != self.settings.system_sleep_seconds
        )
        self.window.set_scale(settings.scale)
        self.window.set_paused(settings.animation_paused)
        self.window.set_always_on_top(settings.always_on_top)
        self.window.set_mouse_interaction_enabled(settings.mouse_interaction_enabled)
        self.settings = settings
        if idle_configuration_changed:
            self._system_idle_monitor = self._new_system_idle_monitor(settings)
            self._configure_system_idle_timer()
        self.settings_manager.save(settings)

    def show_settings_dialog(self) -> None:
        """打开简单设置窗；确认后立即将安全的显示偏好写入用户目录。"""
        dialog = SettingsDialog(self.settings, self.window)
        if dialog.exec():
            self.apply_settings(dialog.updated_settings())

    def show_spritesheet_import_dialog(self) -> None:
        """从本机文件导入成功后重新扫描，并立即切换到新宠物包。"""
        dialog = SpriteSheetImportDialog(self.pets_root, self.window)
        if dialog.exec() and dialog.imported_result is not None:
            self.packages = [self._apply_animation_overrides(item) for item in self.loader.discover(self.pets_root)]
            self.switch_pet(dialog.imported_result.package_id)

    def show_animation_editor_dialog(self) -> None:
        """编辑当前包的本地播放覆盖，并在保存后立即重新载入。"""
        dialog = AnimationEditorDialog(self.package, self.settings.animation_overrides.get(self.package.identifier, {}), self.window)
        if dialog.exec():
            overrides = {pet_id: dict(actions) for pet_id, actions in self.settings.animation_overrides.items()}
            overrides[self.package.identifier] = dialog.updated_overrides()
            self.settings = replace(self.settings, animation_overrides=overrides)
            self.settings_manager.save(self.settings)
            if self.reload_current_pet() and self.tray is not None:
                self.tray.showMessage("PetNest", dialog.applied_summary())

    def shutdown(self) -> None:
        """按可控顺序停止服务、保存状态并请求 Qt 事件循环退出。"""
        if self._shutdown:
            return
        self._shutdown = True
        if self.external_server is not None:
            self.external_server.stop()
            self.external_server = None
        self.system_idle_timer.stop()
        self.platform_adapter.stop()
        self._save_window_position(self.window.pos())
        if self.tray is not None:
            self.tray.hide()
        self.window.hide()
        QApplication.quit()

    def _start_external_server(self) -> None:
        server = ExternalEventServer(self.event_bus, port=self.settings.external_event_port)
        if server.start():
            self.external_server = server
        else:
            LOGGER.warning("本地外部事件服务未启用，桌宠仍可正常使用")

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

    def _save_window_position(self, position: QPoint) -> None:
        self.settings = replace(self.settings, window_x=position.x(), window_y=position.y())
        self.settings_manager.save(self.settings)

    def _select_package(self, identifier: str | None) -> PetPackage:
        return next((item for item in self.packages if item.identifier == identifier), self.packages[0])

    def _apply_animation_overrides(self, package: PetPackage) -> PetPackage:
        overrides = self.settings.animation_overrides.get(package.identifier, {})
        if not overrides:
            return package
        animations = {
            name: replace(
                definition,
                speed_multiplier=1.0 if override.mode == "per_frame" else override.speed_multiplier,
                frame_durations_ms=(
                    override.frame_durations_ms
                    if (
                        override.mode == "per_frame"
                        and override.frame_durations_ms is not None
                        and len(override.frame_durations_ms) == len(definition.frames)
                    )
                    else definition.frame_durations_ms
                ),
            )
            if (override := overrides.get(name)) is not None
            else definition
            for name, definition in package.animations.items()
        }
        return replace(package, animations=animations)
