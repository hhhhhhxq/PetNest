"""桌宠的最小系统托盘控制入口。"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QStyle, QSystemTrayIcon

from .pet_window import PetWindow


class PetTrayIcon(QSystemTrayIcon):
    """提供显示切换、暂停切换和退出动作的托盘图标。"""

    def __init__(self, window: PetWindow, *, on_quit: Callable[[], object] | None = None) -> None:
        icon = QApplication.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
        super().__init__(QIcon(icon), window)
        self.window = window
        self._on_quit = on_quit
        self.menu = QMenu(window)
        self.toggle_visibility_action = QAction("隐藏", self.menu)
        self.toggle_pause_action = QAction("暂停动画", self.menu)
        self.quit_action = QAction("退出", self.menu)
        self.toggle_visibility_action.triggered.connect(self._toggle_visibility)
        self.toggle_pause_action.triggered.connect(self._toggle_pause)
        self.quit_action.triggered.connect(self._quit)
        self.menu.addActions((self.toggle_visibility_action, self.toggle_pause_action))
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
