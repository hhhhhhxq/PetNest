"""冻结版程序最外层的启动诊断。仅依赖标准库，确保导入主程序失败时也可用。"""

from __future__ import annotations

from collections.abc import Callable
import os
from pathlib import Path
import sys
import traceback


STARTUP_LOG_NAME = "PetNest-startup.log"


def default_user_log_directory() -> Path:
    if sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return root / "PetNest" / "logs"
    return Path.home() / ".local" / "state" / "PetNest" / "logs"


def _executable_directory() -> Path | None:
    """仅对冻结程序写入安装目录副本，开发运行不会污染源码目录。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return None


def write_startup_report(
    error: BaseException,
    user_log_directory: Path | None = None,
    executable_directory: Path | None = None,
) -> tuple[Path, ...]:
    """将完整异常写入用户日志，并在可写时复制到安装目录。"""
    report = "PetNest 启动失败诊断\n\n" + "".join(traceback.format_exception(error))
    directories = [user_log_directory or default_user_log_directory()]
    if executable_directory is not None and executable_directory not in directories:
        directories.append(executable_directory)

    written: list[Path] = []
    for directory in directories:
        report_path = directory / STARTUP_LOG_NAME
        try:
            directory.mkdir(parents=True, exist_ok=True)
            report_path.write_text(report, encoding="utf-8")
        except OSError:
            continue
        written.append(report_path)
    return tuple(written)


def report_startup_failure(error: BaseException) -> tuple[Path, ...]:
    """写入诊断并在 Windows 上显示不依赖 Qt 的错误对话框。"""
    report_paths = write_startup_report(error, executable_directory=_executable_directory())
    log_location = "\n".join(str(path) for path in report_paths) or "未能写入诊断日志。"
    message = f"PetNest 未能启动：\n{error}\n\n诊断日志：\n{log_location}"
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, message, "PetNest 启动失败", 0x10)
        except (AttributeError, OSError):
            pass
    print(message, file=sys.stderr)
    return report_paths


def _load_main() -> Callable[[list[str] | None], int]:
    from petnest.__main__ import main

    return main


def run_application(
    arguments: list[str] | None = None,
    *,
    entrypoint_loader: Callable[[], Callable[[list[str] | None], int]] = _load_main,
    failure_reporter: Callable[[BaseException], object] = report_startup_failure,
) -> int:
    """在导入 Qt 和启动应用的整个过程外层提供故障可见性。"""
    try:
        return entrypoint_loader()(arguments)
    except Exception as error:
        failure_reporter(error)
        return 1
