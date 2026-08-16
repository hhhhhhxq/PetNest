"""桌宠的最小系统托盘控制入口。"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import sys

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QStyle, QSystemTrayIcon

from .pet_window import PetWindow
from .theme import menu_stylesheet


def petnest_icon() -> QIcon:
    """加载项目图标；缺失资源时安全回退为 Qt 默认图标。"""
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[3]))
    # macOS 状态栏对 PNG 的显示比 Windows ICO 更可靠；其他平台保留
    # 多尺寸 ICO，避免改变已有 Windows 行为。
    icon_name = "petnest.png" if sys.platform == "darwin" else "petnest.ico"
    icon = QIcon(str(root / "assets" / "icons" / icon_name))
    if not icon.isNull():
        return icon
    return QApplication.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)


def application_icon() -> QIcon:
    """加载安装包与窗口使用的图标；托盘图标保持独立。"""
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[3]))
    icon = QIcon(str(root / "assets" / "icons" / "petnest-app.ico"))
    if not icon.isNull():
        return icon
    return petnest_icon()


def _apply_menu_skin(menu: QMenu, object_name: str) -> None:
    """为可控的平台应用皮肤；Windows/macOS 使用原生菜单避免透明黑边。"""
    menu.setObjectName(object_name)
    if sys.platform in {"win32", "darwin"}:
        menu.setStyleSheet("")
        menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        return
    menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    menu.setStyleSheet(menu_stylesheet(object_name))


class PetTrayIcon(QSystemTrayIcon):
    """提供显示切换、暂停切换和退出动作的托盘图标。"""

    def __init__(
        self,
        window: PetWindow,
        *,
        pet_names: dict[str, str] | None = None,
        current_pet_name: str | None = None,
        on_switch: Callable[[str], object] | None = None,
        on_reload: Callable[[], object] | None = None,
        on_exchange: Callable[[], object] | None = None,
        on_open_pets_folder: Callable[[], object] | None = None,
        on_refresh_pets: Callable[[], object] | None = None,
        on_settings: Callable[[], object] | None = None,
        on_codex_usage: Callable[[], object] | None = None,
        codex_usage_unlocked: bool = False,
        on_cursor_styles: Callable[[], object] | None = None,
        on_resource_update: Callable[[], object] | None = None,
        on_lan_interactions: Callable[[], object] | None = None,
        on_toggle_always_on_top: Callable[[bool], object] | None = None,
        on_toggle_mouse_follow: Callable[[], object] | None = None,
        on_visibility_changed: Callable[[bool], object] | None = None,
        on_toggle_pause: Callable[[bool], object] | None = None,
        on_quit: Callable[[], object] | None = None,
    ) -> None:
        super().__init__(petnest_icon(), window)
        self.window = window
        self._on_quit = on_quit
        self._on_switch = on_switch
        self._on_reload = on_reload
        self._on_exchange = on_exchange
        self._on_open_pets_folder = on_open_pets_folder
        self._on_refresh_pets = on_refresh_pets
        self._on_settings = on_settings
        self._on_codex_usage = on_codex_usage
        self._on_cursor_styles = on_cursor_styles
        self._on_resource_update = on_resource_update
        self._on_lan_interactions = on_lan_interactions
        self._on_toggle_always_on_top = on_toggle_always_on_top
        self._on_toggle_mouse_follow = on_toggle_mouse_follow
        self._on_visibility_changed = on_visibility_changed
        self._on_toggle_pause = on_toggle_pause
        self._resource_update_available = False
        self._resource_update_loading = False
        self._current_pet_name = current_pet_name or "未选择"
        self._resource_loading_phase = 0
        self._resource_loading_timer = QTimer(self)
        self._resource_loading_timer.setInterval(120)
        self._resource_loading_timer.timeout.connect(self._advance_resource_loading)
        self.menu = QMenu(window)
        _apply_menu_skin(self.menu, "trayMenu")
        self.menu.setSeparatorsCollapsible(False)
        self.application_title_action = QAction("PetNest", self.menu)
        self.application_title_action.setIcon(petnest_icon())
        self.application_title_action.setEnabled(False)
        self.current_pet_action = QAction(f"当前宠物：{self._current_pet_name}", self.menu)
        self.current_pet_action.setEnabled(False)
        self.toggle_visibility_action = QAction("隐藏", self.menu)
        self.toggle_pause_action = QAction("暂停动画", self.menu)
        self.toggle_always_on_top_action = QAction("始终置顶", self.menu)
        self.toggle_always_on_top_action.setCheckable(True)
        self.toggle_mouse_follow_action = QAction("跟随鼠标", self.menu)
        self.toggle_mouse_follow_action.setCheckable(True)
        self.quit_action = QAction("退出 PetNest", self.menu)
        self.reload_action = QAction("重新加载当前宠物", self.menu)
        self.exchange_action = QAction("宠物与动作…", self.menu)
        self.open_pets_folder_action = QAction("打开宠物文件夹", self.menu)
        self.refresh_pets_action = QAction("刷新宠物列表", self.menu)
        self.settings_action = QAction("设置…", self.menu)
        self.codex_usage_action = QAction("Codex 用量…", self.menu)
        self.lan_interactions_action = QAction("互动…", self.menu)
        cursor_styles_supported = sys.platform in {"win32", "darwin"}
        cursor_styles_label = "鼠标样式…" if cursor_styles_supported else "鼠标样式…（当前平台暂不支持）"
        self.cursor_styles_action = QAction(cursor_styles_label, self.menu)
        self.cursor_styles_action.setEnabled(cursor_styles_supported)
        self.resource_update_action = QAction("立即检查资源更新", self.menu)
        self.toggle_visibility_action.triggered.connect(self._toggle_visibility)
        self.toggle_pause_action.triggered.connect(self._toggle_pause)
        self.toggle_mouse_follow_action.triggered.connect(self._toggle_mouse_follow)
        self.toggle_always_on_top_action.triggered.connect(self._toggle_always_on_top)
        self.quit_action.triggered.connect(self._quit)
        self.reload_action.triggered.connect(self._reload)
        self.exchange_action.triggered.connect(self._exchange)
        self.open_pets_folder_action.triggered.connect(self._open_pets_folder)
        self.refresh_pets_action.triggered.connect(self._refresh_pets)
        self.settings_action.triggered.connect(self._settings)
        self.codex_usage_action.triggered.connect(self._codex_usage)
        self.lan_interactions_action.triggered.connect(self._lan_interactions)
        self.cursor_styles_action.triggered.connect(self._cursor_styles)
        self.resource_update_action.triggered.connect(self._resource_update)
        self.menu.addActions((self.toggle_visibility_action, self.toggle_pause_action, self.toggle_always_on_top_action, self.toggle_mouse_follow_action))
        self.menu.insertAction(self.toggle_visibility_action, self.application_title_action)
        self.menu.insertAction(self.toggle_visibility_action, self.current_pet_action)
        self.menu.insertSeparator(self.toggle_visibility_action)
        self.menu.addSeparator()
        self.pet_menu = self.menu.addMenu("切换宠物")
        _apply_menu_skin(self.pet_menu, "traySubmenu")
        self.set_pet_names(pet_names or {})
        self.menu.addAction(self.lan_interactions_action)
        self.menu.addSeparator()
        self.pet_library_menu = self.menu.addMenu("宠物库")
        _apply_menu_skin(self.pet_library_menu, "traySubmenu")
        self.pet_library_menu.addAction(self.exchange_action)
        self.pet_library_menu.addAction(self.open_pets_folder_action)
        self.pet_library_menu.addAction(self.refresh_pets_action)
        self.pet_library_menu.addAction(self.reload_action)
        self.menu.addAction(self.settings_action)
        self.menu.addAction(self.codex_usage_action)
        self.set_codex_usage_unlocked(codex_usage_unlocked)
        self.menu.addAction(self.cursor_styles_action)
        self.menu.addAction(self.resource_update_action)
        self.menu.addSeparator()
        self.menu.addAction(self.quit_action)
        self.setContextMenu(self.menu)
        self.sync_visibility_action()

    def set_current_pet_name(self, name: str) -> None:
        """同步菜单顶部的当前宠物标题。"""
        self._current_pet_name = name or "未选择"
        self.current_pet_action.setText(f"当前宠物：{self._current_pet_name}")

    def set_pet_names(self, pet_names: dict[str, str]) -> None:
        self.pet_menu.clear()
        for identifier, name in pet_names.items():
            action = self.pet_menu.addAction(name)
            action.triggered.connect(lambda checked=False, value=identifier: self._switch(value))

    def set_mouse_follow_enabled(self, enabled: bool) -> None:
        self.toggle_mouse_follow_action.setChecked(enabled)

    def set_always_on_top_enabled(self, enabled: bool) -> None:
        self.toggle_always_on_top_action.setChecked(enabled)

    def sync_visibility_action(self) -> None:
        """让动作文字始终反映桌宠窗口的真实可见状态。"""
        self.toggle_visibility_action.setText("隐藏" if self.window.isVisible() else "显示")

    def set_codex_usage_unlocked(self, unlocked: bool) -> None:
        """按本地解锁状态显示或隐藏 Codex 用量入口。"""
        self.codex_usage_action.setVisible(bool(unlocked))

    def set_resource_update_available(self, available: bool) -> None:
        """在资源动作旁显示或清除蓝色更新提示点。"""
        self._resource_update_available = available
        if self._resource_update_loading:
            return
        self.resource_update_action.setEnabled(True)
        self.resource_update_action.setText("立即检查资源更新")
        self.resource_update_action.setIcon(_blue_dot_icon() if available else QIcon())

    def set_resource_update_loading(self, loading: bool, *, message: str = "正在下载资源…") -> None:
        """将资源动作切换为不可重复点击的动态 loading 状态。"""
        self._resource_update_loading = loading
        self.resource_update_action.setEnabled(not loading)
        if not loading:
            self._resource_loading_timer.stop()
            self.set_resource_update_available(self._resource_update_available)
            return
        self._resource_loading_phase = 0
        self.resource_update_action.setText(message)
        self.resource_update_action.setIcon(_loading_icon(self._resource_loading_phase))
        self._resource_loading_timer.start()

    def set_resource_update_progress(self, progress: int) -> None:
        """更新下载百分比；只有 loading 状态才改变动作文案。"""
        if not self._resource_update_loading:
            return
        percentage = max(0, min(100, int(progress)))
        self.resource_update_action.setText(f"正在下载资源（{percentage}%）…")

    def _toggle_visibility(self) -> None:
        target_visible = not self.window.isVisible()
        self.window.setVisible(target_visible)
        if self._on_visibility_changed is not None:
            self._on_visibility_changed(target_visible)
        self.sync_visibility_action()

    def _toggle_pause(self) -> None:
        paused = not self.window.player.is_paused
        if self._on_toggle_pause is not None:
            self._on_toggle_pause(paused)
        else:
            self.window.set_paused(paused)
        self.toggle_pause_action.setText("继续动画" if paused else "暂停动画")

    def _toggle_mouse_follow(self) -> None:
        if self._on_toggle_mouse_follow is not None:
            self._on_toggle_mouse_follow()

    def _toggle_always_on_top(self, enabled: bool) -> None:
        if self._on_toggle_always_on_top is not None:
            self._on_toggle_always_on_top(enabled)

    def _quit(self) -> None:
        if self._on_quit is not None:
            self._on_quit()
        else:
            QApplication.quit()

    def _switch(self, identifier: str) -> None:
        if self._on_switch is not None:
            self._on_switch(identifier)

    def _reload(self) -> None:
        if self._on_reload is not None:
            self._on_reload()

    def _exchange(self) -> None:
        if self._on_exchange is not None:
            self._on_exchange()

    def _open_pets_folder(self) -> None:
        if self._on_open_pets_folder is not None:
            self._on_open_pets_folder()

    def _refresh_pets(self) -> None:
        if self._on_refresh_pets is not None:
            self._on_refresh_pets()

    def _settings(self) -> None:
        if self._on_settings is not None:
            self._on_settings()

    def _codex_usage(self) -> None:
        if self._on_codex_usage is not None:
            self._on_codex_usage()

    def _cursor_styles(self) -> None:
        if self._on_cursor_styles is not None:
            self._on_cursor_styles()

    def _lan_interactions(self) -> None:
        if self._on_lan_interactions is not None:
            self._on_lan_interactions()

    def _resource_update(self) -> None:
        if self._on_resource_update is not None:
            self._on_resource_update()

    def _advance_resource_loading(self) -> None:
        if not self._resource_update_loading:
            return
        self._resource_loading_phase = (self._resource_loading_phase + 1) % 12
        self.resource_update_action.setIcon(_loading_icon(self._resource_loading_phase))


def _blue_dot_icon() -> QIcon:
    pixmap = QPixmap(10, 10)
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QColor("#1677ff"))
    painter.setBrush(QColor("#1677ff"))
    painter.drawEllipse(1, 1, 8, 8)
    painter.end()
    return QIcon(pixmap)


def _loading_icon(phase: int) -> QIcon:
    pixmap = QPixmap(16, 16)
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QColor("#1677ff"))
    painter.drawArc(2, 2, 12, 12, phase * 30 * 16, 270 * 16)
    painter.end()
    return QIcon(pixmap)
