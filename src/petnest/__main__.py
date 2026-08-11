"""``python -m petnest`` 命令行入口。"""

from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
import sys

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication
from PySide6.QtWidgets import QMessageBox

from . import __version__
from .app import PetNest
from .logging_config import configure_logging
from .core.settings_manager import SettingsManager
from .core.single_instance import InstanceClaim, SingleInstanceCoordinator
from .ui.tray_icon import application_icon


def main(arguments: list[str] | None = None) -> int:
    """解析 ``--check``；正常模式启动 Qt 事件循环。"""
    parser = argparse.ArgumentParser(description="PetNest 跨平台轻量桌面宠物")
    parser.add_argument("--check", action="store_true", help="仅校验内置宠物包，不创建 GUI")
    parser.add_argument("--set-pets-root", type=Path, metavar="目录", help="供安装器保存自定义宠物库位置")
    args = parser.parse_args(arguments)
    if args.check:
        return PetNest.check_installation()
    if args.set_pets_root is not None:
        root = args.set_pets_root.expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        manager = SettingsManager()
        manager.save(replace(manager.load(), pets_root=str(root)))
        return 0
    configure_logging()
    # macOS 在 QApplication 构造期间创建全局应用菜单，所以名称必须在
    # QApplication 之前设置，否则菜单会沿用 python / __main__.py。
    QCoreApplication.setApplicationName("PetNest")
    QCoreApplication.setApplicationVersion(__version__)
    QCoreApplication.setOrganizationName("PetNest")
    application = QApplication(sys.argv)
    application.setApplicationDisplayName("PetNest")
    application.setQuitOnLastWindowClosed(False)
    application.setWindowIcon(application_icon())
    coordinator = SingleInstanceCoordinator("PetNest-single-instance", SettingsManager.default_path().with_name("instance.pid"))
    claim = coordinator.claim()
    if claim is InstanceClaim.ACTIVATED_EXISTING:
        return 0
    if claim is InstanceClaim.UNRESPONSIVE:
        choice = QMessageBox.question(
            None,
            "PetNest 已在运行",
            "已有 PetNest 没有响应。为避免出现两只宠物，是否强制重启它？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if choice is not QMessageBox.StandardButton.Yes or not coordinator.force_restart():
            return 1
        claim = coordinator.claim()
        if claim is not InstanceClaim.PRIMARY:
            QMessageBox.warning(None, "无法重启 PetNest", "已有实例仍未退出，请稍后再试。")
            return 1
    try:
        petnest = PetNest()
        coordinator.set_activation_handler(petnest.reveal)
        petnest.start()
        return application.exec()
    finally:
        coordinator.release()


if __name__ == "__main__":
    raise SystemExit(main())
