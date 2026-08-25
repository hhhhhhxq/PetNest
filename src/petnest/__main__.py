"""``python -m petnest`` 命令行入口。"""

from __future__ import annotations

import argparse
from dataclasses import replace
import logging
import os
from pathlib import Path
import sys

from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication
from PySide6.QtWidgets import QMessageBox

from . import __version__
from .app import PetNest
from .logging_config import configure_logging, install_diagnostic_hooks
from .core.codex_link import forward_codex_hook
from .core.settings_manager import SettingsManager
from .core.single_instance import InstanceClaim, SingleInstanceCoordinator
from .core.windows_lan_firewall import configure_public_firewall_rules
from .platforms import remove_startup_registrations
from .ui.tray_icon import application_icon


LOGGER = logging.getLogger(__name__)


def main(arguments: list[str] | None = None) -> int:
    """解析 ``--check``；正常模式启动 Qt 事件循环。"""
    parser = argparse.ArgumentParser(description="PetNest 跨平台轻量桌面宠物")
    parser.add_argument("--check", action="store_true", help="仅校验内置宠物包，不创建 GUI")
    parser.add_argument("--startup", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--remove-startup", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--set-pets-root", type=Path, metavar="目录", help="供安装器保存自定义宠物库位置")
    parser.add_argument("--codex-hook", type=Path, metavar="元数据", help=argparse.SUPPRESS)
    parser.add_argument("--configure-lan-firewall-public", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(arguments)
    if args.configure_lan_firewall_public:
        if sys.platform != "win32" or not getattr(sys, "frozen", False):
            return 2
        return configure_public_firewall_rules(Path(sys.executable))
    if args.codex_hook is not None:
        input_stream = getattr(sys.stdin, "buffer", sys.stdin)
        raw_input = input_stream.read(65_537)
        if isinstance(raw_input, str):
            raw_input = raw_input.encode("utf-8")
        forward_codex_hook(args.codex_hook.expanduser().resolve(), raw_input)
        # Hook 桥接失败不能阻止 Codex 自身继续运行；PetNest 设置页会报告
        # 尚未收到事件或端口冲突。
        return 0
    if args.check:
        return PetNest.check_installation()
    if args.remove_startup:
        return 0 if remove_startup_registrations().success else 1
    if args.set_pets_root is not None:
        root = args.set_pets_root.expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        manager = SettingsManager()
        manager.save(replace(manager.load(), pets_root=str(root)))
        return 0
    configure_logging()
    install_diagnostic_hooks(install_qt=False)
    LOGGER.info(
        "PetNest 进程启动：pid=%s executable=%s argv=%r version=%s",
        os.getpid(),
        sys.executable,
        sys.argv,
        __version__,
    )
    # macOS 在 QApplication 构造期间创建全局应用菜单，所以名称必须在
    # QApplication 之前设置，否则菜单会沿用 python / __main__.py。
    QCoreApplication.setApplicationName("PetNest")
    QCoreApplication.setApplicationVersion(__version__)
    QCoreApplication.setOrganizationName("PetNest")
    application = QApplication(sys.argv)
    application.setFont(QFont("Microsoft YaHei UI", 10))
    install_diagnostic_hooks()
    application.aboutToQuit.connect(lambda: LOGGER.info("Qt aboutToQuit 信号已触发"))
    application.setApplicationDisplayName("PetNest")
    application.setQuitOnLastWindowClosed(False)
    application.setWindowIcon(application_icon())
    pid_path = SettingsManager.default_path().with_name("instance.pid")
    try:
        previous_pid = pid_path.read_text(encoding="utf-8").strip() if pid_path.exists() else ""
    except OSError:
        previous_pid = "<unreadable>"
    coordinator = SingleInstanceCoordinator("PetNest-single-instance", pid_path)
    claim = coordinator.claim()
    LOGGER.info("单实例检查结果：%s（启动前 PID 标记=%s）", claim.value, previous_pid or "none")
    if claim is InstanceClaim.ACTIVATED_EXISTING:
        LOGGER.info("已有 PetNest 实例已响应，当前进程正常退出")
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
            LOGGER.info("用户未确认强制重启无响应的 PetNest 实例，当前进程退出")
            return 1
        claim = coordinator.claim()
        if claim is not InstanceClaim.PRIMARY:
            QMessageBox.warning(None, "无法重启 PetNest", "已有实例仍未退出，请稍后再试。")
            return 1
    try:
        petnest = PetNest()
        coordinator.set_activation_handler(petnest.reveal)
        petnest.start()
        LOGGER.info("PetNest 进入 Qt 事件循环")
        exit_code = application.exec()
        LOGGER.info("Qt 事件循环结束：返回码=%s", exit_code)
        return exit_code
    finally:
        LOGGER.info("PetNest 进程清理开始")
        coordinator.release()
        LOGGER.info("PetNest 进程清理结束")


if __name__ == "__main__":
    raise SystemExit(main())
