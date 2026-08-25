"""与平台相关的系统能力适配层。"""

from __future__ import annotations

import sys

from .base import PlatformEventAdapter, StartupRegistrationResult
from .macos import MacOSPlatformAdapter
from .unsupported import UnsupportedPlatformAdapter
from .windows import WindowsPlatformAdapter
from .windows_startup import WindowsStartupTask


def create_platform_adapter(platform_name: str | None = None) -> PlatformEventAdapter:
    """根据运行平台选择适配器；未知平台始终安全降级。"""
    name = platform_name or sys.platform
    if name == "win32":
        return WindowsPlatformAdapter()
    if name == "darwin":
        return MacOSPlatformAdapter()
    return UnsupportedPlatformAdapter(name)


def remove_startup_registrations(platform_name: str | None = None) -> StartupRegistrationResult:
    """卸载时清理 PetNest 任务命名空间内的登录启动登记。"""
    name = platform_name or sys.platform
    if name == "win32":
        return WindowsStartupTask().remove_all()
    return create_platform_adapter(name).register_startup(False)


__all__ = [
    "PlatformEventAdapter",
    "StartupRegistrationResult",
    "create_platform_adapter",
    "remove_startup_registrations",
]
