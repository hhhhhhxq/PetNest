"""隐私友好的用户目录日志配置。"""

from __future__ import annotations

import logging
import os
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path


LOGGER = logging.getLogger("petnest.diagnostics")
_HOOK_MARKER = "_petnest_diagnostic_hook"
_qt_message_handler_installed = False
_previous_qt_message_handler = None


def default_log_directory(app_name: str = "PetNest") -> Path:
    """返回当前平台惯用的日志目录，不写入安装目录。"""
    if sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Logs"
    else:
        root = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return root / app_name / "logs"


def configure_logging(log_directory: Path | None = None) -> Path:
    """设置轮转日志；重复调用不会重复添加处理器。"""
    directory = log_directory or default_log_directory()
    directory.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("petnest")
    logger.setLevel(logging.INFO)
    log_path = directory / "petnest.log"
    if not any(isinstance(handler, RotatingFileHandler) and Path(handler.baseFilename) == log_path for handler in logger.handlers):
        handler = RotatingFileHandler(log_path, encoding="utf-8", maxBytes=1_000_000, backupCount=3)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logger.addHandler(handler)
    return log_path


def install_diagnostic_hooks(*, install_qt: bool = True) -> None:
    """记录未捕获的 Python/线程异常，并可接管 Qt 消息。"""
    if not getattr(sys.excepthook, _HOOK_MARKER, False):
        previous_hook = sys.excepthook

        def handle_exception(exc_type, exc_value, exc_traceback) -> None:
            LOGGER.critical(
                "未捕获的主线程异常",
                exc_info=(exc_type, exc_value, exc_traceback),
            )
            _delegate_exception_hook(previous_hook, exc_type, exc_value, exc_traceback)

        setattr(handle_exception, _HOOK_MARKER, True)
        sys.excepthook = handle_exception

    if hasattr(threading, "excepthook") and not getattr(threading.excepthook, _HOOK_MARKER, False):
        previous_thread_hook = threading.excepthook

        def handle_thread_exception(args) -> None:
            thread = getattr(args, "thread", None)
            thread_name = getattr(thread, "name", "unknown")
            LOGGER.critical(
                "未捕获的后台线程异常（线程=%s）",
                thread_name,
                exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
            )
            try:
                previous_thread_hook(args)
            except BaseException:  # noqa: BLE001 - 诊断钩子不能掩盖原始异常。
                LOGGER.exception("调用原有后台线程异常钩子失败")

        setattr(handle_thread_exception, _HOOK_MARKER, True)
        threading.excepthook = handle_thread_exception

    if install_qt:
        _install_qt_message_handler()


def _delegate_exception_hook(previous_hook, exc_type, exc_value, exc_traceback) -> None:
    """保留宿主默认异常输出，同时避免宿主钩子异常反向遮蔽原错误。"""
    try:
        previous_hook(exc_type, exc_value, exc_traceback)
    except BaseException:  # noqa: BLE001 - 诊断钩子不能掩盖原始异常。
        LOGGER.exception("调用原有主线程异常钩子失败")


def _install_qt_message_handler() -> None:
    """将 Qt 警告/错误写入 PetNest 日志；Qt 不可用时安全跳过。"""
    global _qt_message_handler_installed, _previous_qt_message_handler
    if _qt_message_handler_installed:
        return
    try:
        from PySide6.QtCore import qInstallMessageHandler
    except Exception:  # noqa: BLE001 - 日志不能阻止无 Qt 的命令行辅助命令。
        LOGGER.debug("Qt 消息钩子不可用", exc_info=True)
        return
    _previous_qt_message_handler = qInstallMessageHandler(_qt_message_handler)
    _qt_message_handler_installed = True


def _qt_message_handler(message_type, context, message: str) -> None:
    """将 Qt 消息转换为 Python 日志，并保留之前安装的 Qt 钩子。"""
    try:
        from PySide6.QtCore import QtMsgType

        levels = {
            QtMsgType.QtDebugMsg: logging.DEBUG,
            QtMsgType.QtInfoMsg: logging.INFO,
            QtMsgType.QtWarningMsg: logging.WARNING,
            QtMsgType.QtCriticalMsg: logging.ERROR,
            QtMsgType.QtFatalMsg: logging.CRITICAL,
        }
        level = levels.get(message_type, logging.WARNING)
    except Exception:  # noqa: BLE001 - 即使 Qt 枚举不可用也要保留消息。
        level = logging.WARNING
    location = ""
    source_file = getattr(context, "file", None)
    source_line = getattr(context, "line", 0)
    if source_file:
        location = f" ({source_file}:{source_line})"
    LOGGER.log(level, "Qt 消息%s：%s", location, message)
    if _previous_qt_message_handler is not None and _previous_qt_message_handler is not _qt_message_handler:
        try:
            _previous_qt_message_handler(message_type, context, message)
        except Exception:  # noqa: BLE001 - 旧钩子异常不能影响 Qt 运行。
            LOGGER.exception("调用原有 Qt 消息钩子失败")
