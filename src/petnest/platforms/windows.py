"""Windows 基础系统空闲时间实现。"""

from __future__ import annotations

from collections.abc import Callable
import csv
from dataclasses import dataclass
import getpass
import logging
import os
from pathlib import Path
import subprocess
import sys

from .base import PlatformEventAdapter, StartupRegistrationResult
from .windows_startup import WindowsStartupTask

LOGGER = logging.getLogger(__name__)

WECHAT_PROCESS_NAMES = frozenset({"WeChat.exe", "Weixin.exe"})
WECHAT_PROCESS_QUERY_ACCOUNT = "覃师傅-安装包"


@dataclass(frozen=True, slots=True)
class WechatProcess:
    name: str
    pid: int


ProcessQueryRunner = Callable[..., subprocess.CompletedProcess[str]]


def terminate_wechat_processes(
    *,
    platform_name: str | None = None,
    runner: object | None = None,
    local_ipv4_addresses: frozenset[str] | set[str] | tuple[str, ...] | None = None,
) -> tuple[str, ...]:
    """保留兼容入口；进程终止功能已停用。"""
    del platform_name, runner, local_ipv4_addresses
    return ()


def find_wechat_processes(
    *,
    platform_name: str | None = None,
    account_name: str | None = None,
    runner: ProcessQueryRunner | None = None,
) -> tuple[WechatProcess, ...]:
    """只读返回正在运行的微信进程，不改变其状态。"""
    if (platform_name or sys.platform) != "win32":
        return ()
    if (account_name or getpass.getuser()) != WECHAT_PROCESS_QUERY_ACCOUNT:
        return ()

    command_runner = runner or subprocess.run
    windows_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    try:
        completed = command_runner(
            [str(windows_root / "System32" / "tasklist.exe"), "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError) as error:
        LOGGER.warning("无法查询 Windows 进程：%s", error)
        return ()

    if completed.returncode != 0:
        LOGGER.warning("Windows 进程查询失败：退出码 %s", completed.returncode)
        return ()

    wanted_names = {name.casefold() for name in WECHAT_PROCESS_NAMES}
    matches: list[WechatProcess] = []
    seen_pids: set[int] = set()
    for row in csv.reader(completed.stdout.splitlines()):
        if len(row) < 2 or row[0].casefold() not in wanted_names:
            continue
        try:
            pid = int(row[1])
        except ValueError:
            continue
        if pid <= 0 or pid in seen_pids:
            continue
        seen_pids.add(pid)
        matches.append(WechatProcess(name=row[0], pid=pid))
    return tuple(matches)


class WindowsPlatformAdapter(PlatformEventAdapter):
    """Win32 最后输入时间和任务计划登录启动。"""

    def __init__(self, *, startup_task: WindowsStartupTask | None = None) -> None:
        self._startup_task = startup_task or WindowsStartupTask()

    def start(self) -> None:
        """第一阶段无需注册后台监听器。"""

    def stop(self) -> None:
        """第一阶段无需释放后台监听器。"""

    def get_idle_seconds(self) -> float | None:
        if sys.platform != "win32":
            return None
        try:
            import ctypes
            from ctypes import wintypes

            class LastInputInfo(ctypes.Structure):
                _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

            info = LastInputInfo()
            info.cbSize = ctypes.sizeof(LastInputInfo)
            if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
                return None
            get_tick_count = ctypes.windll.kernel32.GetTickCount
            get_tick_count.restype = wintypes.DWORD
            tick_count = get_tick_count()
            return _elapsed_milliseconds(int(tick_count), int(info.dwTime)) / 1000.0
        except (AttributeError, OSError):
            LOGGER.warning("无法读取 Windows 系统空闲时间", exc_info=True)
            return None

    @property
    def startup_supported(self) -> bool:
        return self._startup_task.supported

    def register_startup(self, enabled: bool) -> StartupRegistrationResult:
        return self._startup_task.configure(enabled)


def _elapsed_milliseconds(current_tick: int, last_input_tick: int) -> int:
    """以无符号 32 位减法计算 GetTickCount 的回绕间隔。"""
    return (current_tick - last_input_tick) & 0xFFFFFFFF
