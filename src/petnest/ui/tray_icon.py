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
    icon = QIcon(str(root / "assets" / "icons" / "petnest.ico"))
    if not icon.isNull():
        return icon
    return QApplication.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)


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
        on_edit_animations: Callable[[], object] | None = None,
        on_settings: Callable[[], object] | None = None,
        on_quit: Callable[[], object] | None = None,
    ) -> None:
        super().__init__(petnest_icon(), window)
        self.window = window
        self._on_quit = on_quit
        self._on_switch = on_switch
        self._on_reload = on_reload
        self._on_import = on_import
        self._on_edit_animations = on_edit_animations
        self._on_settings = on_settings
        self.menu = QMenu(window)
        self.toggle_visibility_action = QAction("隐藏", self.menu)
        self.toggle_pause_action = QAction("暂停动画", self.menu)
        self.quit_action = QAction("退出", self.menu)
        self.reload_action = QAction("重新加载当前宠物", self.menu)
        self.import_action = QAction("导入精灵图…", self.menu)
        self.edit_animations_action = QAction("编辑动画时长…", self.menu)
        self.settings_action = QAction("设置", self.menu)
        self.toggle_visibility_action.triggered.connect(self._toggle_visibility)
        self.toggle_pause_action.triggered.connect(self._toggle_pause)
        self.quit_action.triggered.connect(self._quit)
        self.reload_action.triggered.connect(self._reload)
        self.import_action.triggered.connect(self._import)
        self.edit_animations_action.triggered.connect(self._edit_animations)
        self.settings_action.triggered.connect(self._settings)
        self.menu.addActions((self.toggle_visibility_action, self.toggle_pause_action))
        if pet_names:
            pet_menu = self.menu.addMenu("切换宠物")
            for identifier, name in pet_names.items():
                action = pet_menu.addAction(name)
                action.triggered.connect(lambda checked=False, value=identifier: self._switch(value))
        self.menu.addAction(self.import_action)
        self.menu.addAction(self.edit_animations_action)
        self.menu.addAction(self.reload_action)
        self.menu.addAction(self.settings_action)
        self.menu.addSeparator()
        self.menu.addAction(self.quit_action)
        self.setContextMenu(self.menu)

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

    def _edit_animations(self) -> None:
        if self._on_edit_animations is not None:
            self._on_edit_animations()

    def _settings(self) -> None:
        if self._on_settings is not None:
            self._on_settings()
