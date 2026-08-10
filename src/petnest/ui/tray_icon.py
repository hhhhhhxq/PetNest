"""桌宠的最小系统托盘控制入口。"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import sys

from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QStyle, QSystemTrayIcon

from .pet_window import PetWindow


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


class PetTrayIcon(QSystemTrayIcon):
    """提供显示切换、暂停切换和退出动作的托盘图标。"""

    def __init__(
        self,
        window: PetWindow,
        *,
        pet_names: dict[str, str] | None = None,
        on_switch: Callable[[str], object] | None = None,
        on_reload: Callable[[], object] | None = None,
        on_import: Callable[[], object] | None = None,
        on_open_pets_folder: Callable[[], object] | None = None,
        on_refresh_pets: Callable[[], object] | None = None,
        on_edit_animations: Callable[[], object] | None = None,
        on_settings: Callable[[], object] | None = None,
        on_cursor_styles: Callable[[], object] | None = None,
        on_toggle_mouse_follow: Callable[[], object] | None = None,
        on_quit: Callable[[], object] | None = None,
    ) -> None:
        super().__init__(petnest_icon(), window)
        self.window = window
        self._on_quit = on_quit
        self._on_switch = on_switch
        self._on_reload = on_reload
        self._on_import = on_import
        self._on_open_pets_folder = on_open_pets_folder
        self._on_refresh_pets = on_refresh_pets
        self._on_edit_animations = on_edit_animations
        self._on_settings = on_settings
        self._on_cursor_styles = on_cursor_styles
        self._on_toggle_mouse_follow = on_toggle_mouse_follow
        self.menu = QMenu(window)
        self.toggle_visibility_action = QAction("隐藏", self.menu)
        self.toggle_pause_action = QAction("暂停动画", self.menu)
        self.toggle_mouse_follow_action = QAction("跟随鼠标", self.menu)
        self.toggle_mouse_follow_action.setCheckable(True)
        self.quit_action = QAction("退出", self.menu)
        self.reload_action = QAction("重新加载当前宠物", self.menu)
        self.import_action = QAction("导入精灵图…", self.menu)
        self.open_pets_folder_action = QAction("打开宠物文件夹", self.menu)
        self.refresh_pets_action = QAction("刷新宠物列表", self.menu)
        self.edit_animations_action = QAction("编辑动画时长…", self.menu)
        self.settings_action = QAction("设置…", self.menu)
        cursor_styles_supported = sys.platform == "win32"
        cursor_styles_label = "鼠标样式…" if cursor_styles_supported else "鼠标样式…（暂时仅 Windows 支持）"
        self.cursor_styles_action = QAction(cursor_styles_label, self.menu)
        self.cursor_styles_action.setEnabled(cursor_styles_supported)
        self.toggle_visibility_action.triggered.connect(self._toggle_visibility)
        self.toggle_pause_action.triggered.connect(self._toggle_pause)
        self.toggle_mouse_follow_action.triggered.connect(self._toggle_mouse_follow)
        self.quit_action.triggered.connect(self._quit)
        self.reload_action.triggered.connect(self._reload)
        self.import_action.triggered.connect(self._import)
        self.open_pets_folder_action.triggered.connect(self._open_pets_folder)
        self.refresh_pets_action.triggered.connect(self._refresh_pets)
        self.edit_animations_action.triggered.connect(self._edit_animations)
        self.settings_action.triggered.connect(self._settings)
        self.cursor_styles_action.triggered.connect(self._cursor_styles)
        self.menu.addActions((self.toggle_visibility_action, self.toggle_pause_action, self.toggle_mouse_follow_action))
        self.pet_menu = self.menu.addMenu("切换宠物")
        self.set_pet_names(pet_names or {})
        self.menu.addAction(self.import_action)
        self.menu.addAction(self.open_pets_folder_action)
        self.menu.addAction(self.refresh_pets_action)
        self.menu.addAction(self.edit_animations_action)
        self.menu.addAction(self.reload_action)
        self.menu.addAction(self.settings_action)
        self.menu.addAction(self.cursor_styles_action)
        self.menu.addSeparator()
        self.menu.addAction(self.quit_action)
        self.setContextMenu(self.menu)

    def set_pet_names(self, pet_names: dict[str, str]) -> None:
        self.pet_menu.clear()
        for identifier, name in pet_names.items():
            action = self.pet_menu.addAction(name)
            action.triggered.connect(lambda checked=False, value=identifier: self._switch(value))

    def set_mouse_follow_enabled(self, enabled: bool) -> None:
        self.toggle_mouse_follow_action.setChecked(enabled)

    def _toggle_visibility(self) -> None:
        if self.window.isVisible():
            self.window.hide()
            self.toggle_visibility_action.setText("显示")
        else:
            self.window.show()
            self.toggle_visibility_action.setText("隐藏")

    def _toggle_pause(self) -> None:
        paused = not self.window.player.is_paused
        self.window.set_paused(paused)
        self.toggle_pause_action.setText("继续动画" if paused else "暂停动画")

    def _toggle_mouse_follow(self) -> None:
        if self._on_toggle_mouse_follow is not None:
            self._on_toggle_mouse_follow()

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

    def _import(self) -> None:
        if self._on_import is not None:
            self._on_import()

    def _open_pets_folder(self) -> None:
        if self._on_open_pets_folder is not None:
            self._on_open_pets_folder()

    def _refresh_pets(self) -> None:
        if self._on_refresh_pets is not None:
            self._on_refresh_pets()

    def _edit_animations(self) -> None:
        if self._on_edit_animations is not None:
            self._on_edit_animations()

    def _settings(self) -> None:
        if self._on_settings is not None:
            self._on_settings()

    def _cursor_styles(self) -> None:
        if self._on_cursor_styles is not None:
            self._on_cursor_styles()
