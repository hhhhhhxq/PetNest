"""``python -m petnest`` 命令行入口。"""

from __future__ import annotations

import argparse
import sys

from PySide6.QtWidgets import QApplication

from .app import PetNest
from .logging_config import configure_logging
from .ui.tray_icon import petnest_icon


def main(arguments: list[str] | None = None) -> int:
    """解析 ``--check``；正常模式启动 Qt 事件循环。"""
    parser = argparse.ArgumentParser(description="PetNest 跨平台轻量桌面宠物")
    parser.add_argument("--check", action="store_true", help="仅校验内置宠物包，不创建 GUI")
    args = parser.parse_args(arguments)
    if args.check:
        return PetNest.check_installation()
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
