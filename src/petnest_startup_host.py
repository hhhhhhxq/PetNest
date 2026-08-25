"""Windows 登录启动宿主：正常退出即停止，异常退出时执行有界重试。"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import subprocess
import sys
from threading import Thread
import time
from collections.abc import Callable
from uuid import uuid4


RETRY_DELAY_SECONDS = 60
MAX_RESTARTS = 3
CONTROL_FILE_NAME = "startup-host.generation"


def default_control_path() -> Path:
    root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    return root / "PetNest" / CONTROL_FILE_NAME


def _read_control_generation(control_path: Path) -> str | None:
    try:
        return control_path.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def cancellation_checker(control_path: Path | None = None) -> Callable[[], bool]:
    """返回只对后续代际变更作出响应的宿主取消检查器。"""
    path = control_path or default_control_path()
    initial_generation = _read_control_generation(path)
    return lambda: _read_control_generation(path) != initial_generation


def cancel_running_hosts(control_path: Path | None = None) -> None:
    """原子推进控制代际，使已经运行的宿主停止监督但保留 PetNest。"""
    path = control_path or default_control_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(uuid4().hex, encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def configure_logging(log_directory: Path | None = None) -> logging.Logger:
    """为无窗口启动宿主创建独立的轮转诊断日志。"""
    directory = log_directory or (
        Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        / "PetNest"
        / "logs"
    )
    directory.mkdir(parents=True, exist_ok=True)
    log_path = directory / "startup-host.log"
    logger = logging.getLogger("petnest.startup_host")
    logger.setLevel(logging.INFO)
    if not any(
        isinstance(handler, RotatingFileHandler)
        and Path(handler.baseFilename) == log_path
        for handler in logger.handlers
    ):
        handler = RotatingFileHandler(
            log_path,
            encoding="utf-8",
            maxBytes=500_000,
            backupCount=2,
        )
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
    return logger


def run_supervisor(
    app_path: Path | None = None,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    sleeper: Callable[[float], None] = time.sleep,
    retry_delay_seconds: float = RETRY_DELAY_SECONDS,
    max_restarts: int = MAX_RESTARTS,
    logger: logging.Logger | None = None,
    cancelled: Callable[[], bool] | None = None,
    cancel_poll_seconds: float = 0.25,
) -> int:
    """等待 PetNest 退出；非零退出时冷却后最多重新启动三次。"""
    executable = Path(app_path or Path(sys.executable).with_name("PetNest.exe")).resolve()
    active_logger = logger or logging.getLogger("petnest.startup_host")
    is_cancelled = cancelled or cancellation_checker()
    cancellation_interval = max(cancel_poll_seconds, 0.01)
    restart_count = 0
    while True:
        if is_cancelled():
            active_logger.info("收到自动启动取消信号，结束宿主且不再启动 PetNest")
            return 0
        active_logger.info(
            "启动 PetNest：第 %s 次运行 executable=%s",
            restart_count + 1,
            executable,
        )
        outcome: list[int | OSError] = []

        def invoke() -> None:
            try:
                completed = runner(
                    [str(executable), "--startup"],
                    cwd=str(executable.parent),
                    check=False,
                )
                outcome.append(int(completed.returncode))
            except OSError as error:
                outcome.append(error)

        worker = Thread(target=invoke, daemon=True, name="petnest-startup-child-wait")
        worker.start()
        while worker.is_alive():
            if is_cancelled():
                active_logger.info("收到自动启动取消信号，保留当前 PetNest 并结束宿主")
                return 0
            worker.join(timeout=cancellation_interval)
        if is_cancelled():
            active_logger.info("收到自动启动取消信号，结束宿主且不再重试")
            return 0

        result = outcome[0]
        if isinstance(result, OSError):
            exit_code = 1
            active_logger.warning(
                "无法创建 PetNest 进程：%s",
                result,
                exc_info=(type(result), result, result.__traceback__),
            )
        else:
            exit_code = result

        if exit_code == 0:
            active_logger.info("PetNest 正常退出，启动宿主结束")
            return 0
        if restart_count >= max_restarts:
            active_logger.warning(
                "PetNest 异常退出且已耗尽 %s 次重试：exit_code=%s",
                max_restarts,
                exit_code,
            )
            return exit_code

        restart_count += 1
        active_logger.warning(
            "PetNest 异常退出：exit_code=%s；%s 秒后执行第 %s/%s 次重试",
            exit_code,
            retry_delay_seconds,
            restart_count,
            max_restarts,
        )
        remaining_delay = max(retry_delay_seconds, 0.0)
        while remaining_delay > 0:
            if is_cancelled():
                active_logger.info("重试等待期间收到取消信号，结束宿主")
                return 0
            interval = min(cancellation_interval, remaining_delay)
            sleeper(interval)
            remaining_delay -= interval
        if is_cancelled():
            active_logger.info("重试等待结束时收到取消信号，结束宿主")
            return 0


def main() -> int:
    try:
        logger = configure_logging()
    except OSError:
        logger = logging.getLogger("petnest.startup_host")
        logger.addHandler(logging.NullHandler())
    return run_supervisor(logger=logger)


if __name__ == "__main__":
    raise SystemExit(main())
