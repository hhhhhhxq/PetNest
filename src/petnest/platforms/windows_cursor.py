"""Windows 普通箭头光标的最小、可恢复控制器。"""

from __future__ import annotations

import ctypes
import logging
import os
from pathlib import Path
import sys
from typing import Protocol
from ctypes import wintypes


LOGGER = logging.getLogger(__name__)

OCR_NORMAL = 32_512
_ROLE_CODES = {"arrow": 32512, "text": 32513, "busy": 32514, "resize_diag_1": 32642, "resize_diag_2": 32643, "resize_horizontal": 32644, "resize_vertical": 32645, "move": 32646}
_REGISTRY_VALUES = {"arrow": "Arrow", "text": "IBeam", "busy": "Wait", "resize_diag_1": "SizeNWSE", "resize_diag_2": "SizeNESW", "resize_horizontal": "SizeWE", "resize_vertical": "SizeNS", "move": "SizeAll"}
_IMAGE_CURSOR = 2
_LR_LOADFROMFILE = 0x0010
_IDC_ARROW = 32_512
_SPI_SETCURSORS = 0x0057


class _CursorApi(Protocol):
    def load_file_cursor(self, path: Path) -> int | None: ...

    def load_saved_cursor_or_system_default(self, value_name: str, resource_id: int) -> int | None: ...

    def copy_cursor(self, handle: int) -> int | None: ...

    def set_system_cursor(self, handle: int, role: int) -> bool: ...

    def restore_system_cursors(self) -> bool: ...


class WindowsCursorController:
    """只替换 Windows 的普通箭头，绝不重设其它系统角色。"""

    def __init__(self, *, api: _CursorApi | None = None, platform: str | None = None) -> None:
        self._platform = platform or sys.platform
        self._api = api or _CtypesCursorApi()

    def apply(self, cursor_path: Path) -> bool:
        """将一个 `.cur` 样式应用到 OCR_NORMAL。"""
        if self._platform != "win32":
            return False
        try:
            return self.apply_role("arrow", cursor_path)
        except (OSError, ValueError):
            LOGGER.warning("无法应用 Windows 普通箭头光标：%s", cursor_path, exc_info=True)
            return False

    def restore_normal(self) -> bool:
        """仅从用户保存的 Arrow 设置恢复普通箭头。"""
        if self._platform != "win32":
            return False
        try:
            return self._set_cursor(
                self._api.load_saved_cursor_or_system_default(_REGISTRY_VALUES["arrow"], OCR_NORMAL),
                OCR_NORMAL,
            )
        except (OSError, ValueError):
            LOGGER.warning("无法恢复 Windows 普通箭头光标", exc_info=True)
            return False

    def apply_role(self, role: str, cursor_path: Path) -> bool:
        if self._platform != "win32" or role not in _ROLE_CODES:
            return False
        try:
            return self._set_cursor(self._api.load_file_cursor(cursor_path), _ROLE_CODES[role])
        except (OSError, ValueError):
            LOGGER.warning("无法应用 Windows 光标角色：%s", role, exc_info=True)
            return False

    def restore_role(self, role: str) -> bool:
        if self._platform != "win32" or role not in _ROLE_CODES:
            return False
        try:
            return self._set_cursor(self._api.load_saved_cursor_or_system_default(_REGISTRY_VALUES[role], _ROLE_CODES[role]), _ROLE_CODES[role])
        except (OSError, ValueError):
            LOGGER.warning("无法恢复 Windows 光标角色：%s", role, exc_info=True)
            return False

    def restore_system_defaults(self) -> bool:
        """让 Windows 从当前用户方案一次性重载全部系统光标。"""
        if self._platform != "win32":
            return False
        try:
            return self._api.restore_system_cursors()
        except (OSError, ValueError):
            LOGGER.warning("无法恢复 Windows 系统光标方案", exc_info=True)
            return False

    def _set_cursor(self, loaded_handle: int | None, role: int) -> bool:
        if loaded_handle is None:
            return False
        copied_handle = self._api.copy_cursor(loaded_handle)
        return copied_handle is not None and self._api.set_system_cursor(copied_handle, role)


class _CtypesCursorApi:
    """将 ctypes 和注册表细节封装在可替换边界后。"""

    def __init__(self) -> None:
        self._user32 = ctypes.WinDLL("user32", use_last_error=True) if sys.platform == "win32" else None
        if self._user32 is not None:
            self._user32.LoadImageW.restype = wintypes.HANDLE
            self._user32.LoadImageW.argtypes = [
                wintypes.HANDLE,
                wintypes.LPCWSTR,
                wintypes.UINT,
                ctypes.c_int,
                ctypes.c_int,
                wintypes.UINT,
            ]
            self._user32.LoadCursorW.restype = wintypes.HANDLE
            self._user32.LoadCursorW.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
            self._user32.CopyImage.restype = wintypes.HANDLE
            self._user32.CopyImage.argtypes = [
                wintypes.HANDLE,
                wintypes.UINT,
                ctypes.c_int,
                ctypes.c_int,
                wintypes.UINT,
            ]
            self._user32.SetSystemCursor.restype = wintypes.BOOL
            self._user32.SetSystemCursor.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            self._user32.SystemParametersInfoW.restype = wintypes.BOOL
            self._user32.SystemParametersInfoW.argtypes = [
                wintypes.UINT,
                wintypes.UINT,
                wintypes.LPVOID,
                wintypes.UINT,
            ]

    def load_file_cursor(self, path: Path) -> int | None:
        if self._user32 is None or not path.is_file():
            return None
        handle = self._user32.LoadImageW(None, str(path), _IMAGE_CURSOR, 0, 0, _LR_LOADFROMFILE)
        return int(handle) if handle else None

    def load_saved_cursor_or_system_default(self, value_name: str, resource_id: int) -> int | None:
        saved_path = self._saved_cursor_path(value_name)
        if saved_path is not None:
            loaded = self.load_file_cursor(saved_path)
            if loaded is not None:
                return loaded
        if self._user32 is None:
            return None
        handle = self._user32.LoadCursorW(None, ctypes.c_void_p(resource_id))
        return int(handle) if handle else None

    def copy_cursor(self, handle: int) -> int | None:
        if self._user32 is None:
            return None
        copied = self._user32.CopyImage(handle, _IMAGE_CURSOR, 0, 0, 0)
        return int(copied) if copied else None

    def set_system_cursor(self, handle: int, role: int) -> bool:
        if self._user32 is None:
            return False
        return bool(self._user32.SetSystemCursor(handle, role))

    def restore_system_cursors(self) -> bool:
        if self._user32 is None:
            return False
        return bool(self._user32.SystemParametersInfoW(_SPI_SETCURSORS, 0, None, 0))

    @staticmethod
    def _saved_cursor_path(value_name: str) -> Path | None:
        if sys.platform != "win32":
            return None
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Cursors") as key:
                value, _ = winreg.QueryValueEx(key, value_name)
        except OSError:
            return None
        if not isinstance(value, str) or not value.strip():
            return None
        return Path(os.path.expandvars(value))
