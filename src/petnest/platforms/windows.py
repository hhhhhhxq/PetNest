"""Windows 基础系统空闲时间实现。"""

from __future__ import annotations

import logging
import sys

from .base import PlatformEventAdapter, StartupRegistrationResult
from .windows_startup import WindowsStartupTask

LOGGER = logging.getLogger(__name__)


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
