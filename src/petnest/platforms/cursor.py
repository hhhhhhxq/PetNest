"""跨平台鼠标样式控制器选择。"""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Protocol

from .macos_cursor import MacOSCursorController
from .windows_cursor import WindowsCursorController


class CursorController(Protocol):
    supported_roles: frozenset[str]

    def apply(self, cursor_path: Path) -> bool: ...

    def apply_role(self, role: str, cursor_path: Path) -> bool: ...

    def restore_system_defaults(self) -> bool: ...


def create_cursor_controller(platform_name: str | None = None) -> CursorController:
    name = platform_name or sys.platform
    if name == "darwin":
        return MacOSCursorController(platform=name)
    return WindowsCursorController(platform=name)
