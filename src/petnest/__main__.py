"""``python -m petnest`` 命令行入口。"""

from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
import sys

from PySide6.QtWidgets import QApplication

from .app import PetNest
from .logging_config import configure_logging
from .core.settings_manager import SettingsManager
from .ui.tray_icon import petnest_icon


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
    application = QApplication(sys.argv)
    application.setQuitOnLastWindowClosed(False)
    application.setWindowIcon(petnest_icon())
    try:
        petnest = PetNest()
        petnest.start()
        return application.exec()
    except (OSError, RuntimeError, ValueError) as error:
        print(f"PetNest 启动失败：{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
