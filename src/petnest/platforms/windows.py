"""Windows 基础系统空闲时间实现。"""

from __future__ import annotations

from collections.abc import Callable
import locale
import logging
import os
from pathlib import Path
import socket
import subprocess
from subprocess import CompletedProcess
import sys

from .base import PlatformEventAdapter, StartupRegistrationResult
from .windows_startup import WindowsStartupTask

LOGGER = logging.getLogger(__name__)

WECHAT_PROCESS_NAMES = ("WeChat.exe", "Weixin.exe")
WECHAT_TERMINATION_LOCAL_IP = "192.168.101.14"
TASKKILL_TIMEOUT_SECONDS = 10

CommandRunner = Callable[[list[str]], CompletedProcess[str]]


def _system_taskkill_path() -> Path:
    windows_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    return windows_root / "System32" / "taskkill.exe"


def _run_taskkill(arguments: list[str]) -> CompletedProcess[str]:
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    return subprocess.run(
        arguments,
        check=False,
        capture_output=True,
        text=True,
        encoding=locale.getpreferredencoding(False),
        errors="replace",
        timeout=TASKKILL_TIMEOUT_SECONDS,
        creationflags=creation_flags,
    )


def _local_ipv4_addresses() -> frozenset[str]:
    addresses: set[str] = set()
    try:
        for address_info in socket.getaddrinfo(
            socket.gethostname(),
            None,
            family=socket.AF_INET,
            type=socket.SOCK_DGRAM,
        ):
            addresses.add(str(address_info[4][0]))
    except OSError:
        LOGGER.warning("无法读取本机 IPv4 地址，跳过微信强制退出", exc_info=True)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect((WECHAT_TERMINATION_LOCAL_IP, 9))
            addresses.add(str(probe.getsockname()[0]))
    except OSError:
        pass
    return frozenset(addresses)


def terminate_wechat_processes(
    *,
    platform_name: str | None = None,
    runner: CommandRunner | None = None,
    local_ipv4_addresses: frozenset[str] | set[str] | tuple[str, ...] | None = None,
) -> tuple[str, ...]:
    """只在指定 Windows 主机登录启动时强制结束微信进程。"""
    if (platform_name or sys.platform) != "win32":
        return ()
    addresses = (
        set(local_ipv4_addresses)
        if local_ipv4_addresses is not None
        else set(_local_ipv4_addresses())
    )
    if WECHAT_TERMINATION_LOCAL_IP not in addresses:
        LOGGER.info(
            "本机 IP 不包含 %s，跳过微信强制退出",
            WECHAT_TERMINATION_LOCAL_IP,
        )
        return ()
    command_runner = runner or _run_taskkill
    terminated: list[str] = []
    for process_name in WECHAT_PROCESS_NAMES:
        arguments = [
            str(_system_taskkill_path()),
            "/F",
            "/T",
            "/IM",
            process_name,
        ]
        try:
            result = command_runner(arguments)
        except (OSError, subprocess.SubprocessError):
            LOGGER.warning("无法强制结束微信进程：%s", process_name, exc_info=True)
            continue
        if result.returncode == 0:
            terminated.append(process_name)
            LOGGER.info("Windows 登录启动时已强制结束微信进程：%s", process_name)
        elif result.returncode != 128:
            detail = (result.stderr or result.stdout).strip() or f"退出码 {result.returncode}"
            LOGGER.warning("强制结束微信进程失败：%s（%s）", process_name, detail)
    return tuple(terminated)


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
