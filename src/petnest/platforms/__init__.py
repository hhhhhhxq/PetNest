"""与平台相关的系统能力适配层。"""

from __future__ import annotations

import sys

from .base import PlatformEventAdapter
from .macos import MacOSPlatformAdapter
from .unsupported import UnsupportedPlatformAdapter
from .windows import WindowsPlatformAdapter


def create_platform_adapter(platform_name: str | None = None) -> PlatformEventAdapter:
    """根据运行平台选择适配器；未知平台始终安全降级。"""
    name = platform_name or sys.platform
    if name == "win32":
        return WindowsPlatformAdapter()
    if name == "darwin":
        return MacOSPlatformAdapter()
    return UnsupportedPlatformAdapter(name)


__all__ = ["PlatformEventAdapter", "create_platform_adapter"]
