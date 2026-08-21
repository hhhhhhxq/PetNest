"""Platform keyboard-activity capability without exposing key data."""

from __future__ import annotations

from collections.abc import Callable
import sys
from typing import Protocol


class KeyboardActivityMonitor(Protocol):
    @property
    def supported(self) -> bool:
        raise NotImplementedError

    @property
    def status_message(self) -> str:
        raise NotImplementedError

    def start(self, on_activity: Callable[[], object]) -> bool:
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError


class UnsupportedKeyboardActivityMonitor:
    """Explicitly declines global monitoring on unsupported platforms."""

    def __init__(self, platform_name: str) -> None:
        self.platform_name = platform_name

    @property
    def supported(self) -> bool:
        return False

    @property
    def status_message(self) -> str:
        return "当前版本仅支持 Windows"

    def start(self, on_activity: Callable[[], object]) -> bool:
        del on_activity
        return False

    def stop(self) -> None:
        return None


def create_keyboard_activity_monitor(
    platform_name: str | None = None,
) -> KeyboardActivityMonitor:
    name = platform_name or sys.platform
    if name == "win32":
        from petnest.platforms.windows_keyboard import WindowsKeyboardActivityMonitor

        return WindowsKeyboardActivityMonitor()
    return UnsupportedKeyboardActivityMonitor(name)


__all__ = [
    "KeyboardActivityMonitor",
    "UnsupportedKeyboardActivityMonitor",
    "create_keyboard_activity_monitor",
]
