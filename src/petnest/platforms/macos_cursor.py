"""macOS 系统光标角色的原生注册与可恢复替换。"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
import logging
from pathlib import Path
import struct
import sys
from typing import Protocol

from PySide6.QtCore import QBuffer, QIODevice, QPoint
from PySide6.QtGui import QImage


LOGGER = logging.getLogger(__name__)
_APPLICATION_SERVICES_PATH = "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
_CORE_FOUNDATION_PATH = "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
_IMAGE_IO_PATH = "/System/Library/Frameworks/ImageIO.framework/ImageIO"
_CG_SUCCESS = 0
_ROLE_IDENTIFIERS = {
    "arrow": b"com.apple.coregraphics.Arrow",
    "text": b"com.apple.coregraphics.IBeam",
    "busy": b"com.apple.cursor.4",
    "move": b"com.apple.coregraphics.Move",
    "resize_horizontal": b"com.apple.cursor.19",
    "resize_vertical": b"com.apple.cursor.23",
    "resize_diag_1": b"com.apple.cursor.34",
    "resize_diag_2": b"com.apple.cursor.30",
}
_CORE_CURSOR_IDS = {
    "busy": 4,
    "resize_horizontal": 19,
    "resize_vertical": 23,
    "resize_diag_1": 34,
    "resize_diag_2": 30,
}
_BACKUP_PREFIX = b"com.petnest.cursorbackup."


class _MacCursorApi(Protocol):
    def apply_role(self, role: str, cursor_path: Path) -> bool: ...

    def restore_role(self, role: str) -> bool: ...

    def restore_roles(self) -> bool: ...


class MacOSCursorController:
    """通过 WindowServer 注册表替换系统光标，不绘制额外光标。"""

    supported_roles = frozenset(_ROLE_IDENTIFIERS)

    def __init__(self, *, api: _MacCursorApi | None = None, platform: str | None = None) -> None:
        self._platform = platform or sys.platform
        self._api = api

    def apply(self, cursor_path: Path) -> bool:
        return self.apply_role("arrow", cursor_path)

    def apply_role(self, role: str, cursor_path: Path) -> bool:
        if self._platform != "darwin" or role not in _ROLE_IDENTIFIERS:
            return False
        try:
            return self._get_api().apply_role(role, cursor_path)
        except (OSError, RuntimeError, ValueError):
            LOGGER.warning("无法应用 macOS 光标角色 %s：%s", role, cursor_path, exc_info=True)
            return False

    def restore_normal(self) -> bool:
        return self.restore_system_defaults()

    def restore_role(self, role: str) -> bool:
        if self._platform != "darwin" or role not in _ROLE_IDENTIFIERS:
            return False
        try:
            return self._get_api().restore_role(role)
        except (OSError, RuntimeError, ValueError):
            LOGGER.warning("无法恢复 macOS 系统光标角色：%s", role, exc_info=True)
            return False

    def restore_system_defaults(self) -> bool:
        if self._platform != "darwin":
            return False
        try:
            return self._get_api().restore_roles()
        except (OSError, RuntimeError, ValueError):
            LOGGER.warning("无法恢复 macOS 系统光标", exc_info=True)
            return False

    def _get_api(self) -> _MacCursorApi:
        if self._api is None:
            self._api = _CtypesMacCursorApi()
        return self._api


@dataclass(slots=True)
class _RegisteredCursor:
    size: _CGSize
    hotspot: _CGPoint
    frame_count: int
    frame_duration: float
    images: int
    owned_objects: tuple[int, ...]


class _CGPoint(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


class _CGSize(ctypes.Structure):
    _fields_ = [("width", ctypes.c_double), ("height", ctypes.c_double)]


class _CtypesMacCursorApi:
    """封装 Mousecape 同类项目使用的 WindowServer 光标注册接口。

    这里只使用接口签名和备份思路，未复制 Mousecape 的业务实现。接口属于
    macOS 私有 API，因此任何失败都必须安全回退到原系统光标。
    """

    def __init__(self) -> None:
        self._application_services = ctypes.CDLL(_APPLICATION_SERVICES_PATH)
        self._core_foundation = ctypes.CDLL(_CORE_FOUNDATION_PATH)
        self._image_io = ctypes.CDLL(_IMAGE_IO_PATH)
        self._declare_functions()
        self._connection = int(self._application_services.CGSMainConnectionID())

    def apply_role(self, role: str, cursor_path: Path) -> bool:
        identifier = _ROLE_IDENTIFIERS.get(role)
        if identifier is None:
            return False
        custom = self._cursor_from_file(cursor_path)
        if custom is None:
            return False
        try:
            if not self._ensure_backup(role):
                return False
            if self._register(identifier, custom, instantly=True):
                return True
            self.restore_role(role)
            return False
        finally:
            self._release_cursor(custom)

    def restore_role(self, role: str) -> bool:
        identifier = _ROLE_IDENTIFIERS.get(role)
        if identifier is None:
            return False
        backup_identifier = self._backup_identifier(identifier)
        backup = self._copy_registered(backup_identifier)
        if backup is None:
            return True
        try:
            if not self._register(identifier, backup, instantly=True):
                return False
            removed = self._application_services.CGSRemoveRegisteredCursor(
                self._connection,
                backup_identifier,
                True,
            )
            return removed == _CG_SUCCESS
        finally:
            self._release_cursor(backup)

    def restore_roles(self) -> bool:
        restored = True
        for role in _ROLE_IDENTIFIERS:
            restored = self.restore_role(role) and restored
        return restored

    def _ensure_backup(self, role: str) -> bool:
        identifier = _ROLE_IDENTIFIERS[role]
        backup_identifier = self._backup_identifier(identifier)
        existing_backup = self._copy_registered(backup_identifier)
        if existing_backup is not None:
            self._release_cursor(existing_backup)
            return True
        current = self._copy_current(role)
        if current is None:
            return False
        try:
            return self._register(backup_identifier, current, instantly=False)
        finally:
            self._release_cursor(current)

    def _copy_current(self, role: str) -> _RegisteredCursor | None:
        core_cursor_id = _CORE_CURSOR_IDS.get(role)
        if core_cursor_id is not None:
            return self._copy_core_cursor(core_cursor_id)
        return self._copy_registered(_ROLE_IDENTIFIERS[role])

    @staticmethod
    def _backup_identifier(identifier: bytes) -> bytes:
        return _BACKUP_PREFIX + identifier

    def _copy_registered(self, identifier: bytes) -> _RegisteredCursor | None:
        size = _CGSize()
        hotspot = _CGPoint()
        frame_count = ctypes.c_ulong()
        frame_duration = ctypes.c_double()
        images = ctypes.c_void_p()
        error = self._application_services.CGSCopyRegisteredCursorImages(
            self._connection,
            identifier,
            ctypes.byref(size),
            ctypes.byref(hotspot),
            ctypes.byref(frame_count),
            ctypes.byref(frame_duration),
            ctypes.byref(images),
        )
        if error != _CG_SUCCESS or not images.value or frame_count.value < 1:
            if images.value:
                self._core_foundation.CFRelease(images)
            return None
        return _RegisteredCursor(
            size,
            hotspot,
            int(frame_count.value),
            float(frame_duration.value),
            int(images.value),
            (int(images.value),),
        )

    def _copy_core_cursor(self, cursor_id: int) -> _RegisteredCursor | None:
        size = _CGSize()
        hotspot = _CGPoint()
        frame_count = ctypes.c_ulong()
        frame_duration = ctypes.c_double()
        images = ctypes.c_void_p()
        error = self._application_services.CoreCursorCopyImages(
            self._connection,
            cursor_id,
            ctypes.byref(images),
            ctypes.byref(size),
            ctypes.byref(hotspot),
            ctypes.byref(frame_count),
            ctypes.byref(frame_duration),
        )
        if error != _CG_SUCCESS or not images.value or frame_count.value < 1:
            if images.value:
                self._core_foundation.CFRelease(images)
            return None
        return _RegisteredCursor(
            size,
            hotspot,
            int(frame_count.value),
            float(frame_duration.value),
            int(images.value),
            (int(images.value),),
        )

    def _cursor_from_file(self, cursor_path: Path) -> _RegisteredCursor | None:
        if not cursor_path.is_file():
            return None
        image = QImage(str(cursor_path))
        if image.isNull():
            return None
        buffer = QBuffer()
        if not buffer.open(QIODevice.OpenModeFlag.WriteOnly):
            return None
        saved = image.save(buffer, "PNG")
        png = bytes(buffer.data())
        buffer.close()
        if not saved:
            return None
        raw = ctypes.create_string_buffer(png)
        data = self._core_foundation.CFDataCreate(None, raw, len(png))
        if not data:
            return None
        source = self._image_io.CGImageSourceCreateWithData(data, None)
        if not source:
            self._core_foundation.CFRelease(data)
            return None
        cg_image = self._image_io.CGImageSourceCreateImageAtIndex(source, 0, None)
        if not cg_image:
            self._core_foundation.CFRelease(source)
            self._core_foundation.CFRelease(data)
            return None
        values = (ctypes.c_void_p * 1)(cg_image)
        images = self._core_foundation.CFArrayCreate(None, values, 1, None)
        if not images:
            self._core_foundation.CFRelease(cg_image)
            self._core_foundation.CFRelease(source)
            self._core_foundation.CFRelease(data)
            return None
        hotspot = _read_cur_hotspot(cursor_path)
        return _RegisteredCursor(
            _CGSize(float(image.width()), float(image.height())),
            _CGPoint(float(hotspot.x()), float(hotspot.y())),
            1,
            0.0,
            int(images),
            (int(images), int(cg_image), int(source), int(data)),
        )

    def _register(self, identifier: bytes, cursor: _RegisteredCursor, *, instantly: bool) -> bool:
        seed = ctypes.c_int32()
        error = self._application_services.CGSRegisterCursorWithImages(
            self._connection,
            identifier,
            True,
            instantly,
            cursor.size,
            cursor.hotspot,
            cursor.frame_count,
            cursor.frame_duration,
            cursor.images,
            ctypes.byref(seed),
        )
        return error == _CG_SUCCESS

    def _release_cursor(self, cursor: _RegisteredCursor) -> None:
        for item in cursor.owned_objects:
            self._core_foundation.CFRelease(item)

    def _declare_functions(self) -> None:
        app = self._application_services
        app.CGSMainConnectionID.restype = ctypes.c_int32
        app.CGSMainConnectionID.argtypes = []
        app.CGSCopyRegisteredCursorImages.restype = ctypes.c_int32
        app.CGSCopyRegisteredCursorImages.argtypes = [
            ctypes.c_int32,
            ctypes.c_char_p,
            ctypes.POINTER(_CGSize),
            ctypes.POINTER(_CGPoint),
            ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_void_p),
        ]
        app.CGSRegisterCursorWithImages.restype = ctypes.c_int32
        app.CGSRegisterCursorWithImages.argtypes = [
            ctypes.c_int32,
            ctypes.c_char_p,
            ctypes.c_bool,
            ctypes.c_bool,
            _CGSize,
            _CGPoint,
            ctypes.c_ulong,
            ctypes.c_double,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_int32),
        ]
        app.CGSRemoveRegisteredCursor.restype = ctypes.c_int32
        app.CGSRemoveRegisteredCursor.argtypes = [ctypes.c_int32, ctypes.c_char_p, ctypes.c_bool]
        app.CoreCursorCopyImages.restype = ctypes.c_int32
        app.CoreCursorCopyImages.argtypes = [
            ctypes.c_int32,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(_CGSize),
            ctypes.POINTER(_CGPoint),
            ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(ctypes.c_double),
        ]
        cf = self._core_foundation
        cf.CFDataCreate.restype = ctypes.c_void_p
        cf.CFDataCreate.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_long]
        cf.CFArrayCreate.restype = ctypes.c_void_p
        cf.CFArrayCreate.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.c_long,
            ctypes.c_void_p,
        ]
        cf.CFRelease.restype = None
        cf.CFRelease.argtypes = [ctypes.c_void_p]
        image_io = self._image_io
        image_io.CGImageSourceCreateWithData.restype = ctypes.c_void_p
        image_io.CGImageSourceCreateWithData.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        image_io.CGImageSourceCreateImageAtIndex.restype = ctypes.c_void_p
        image_io.CGImageSourceCreateImageAtIndex.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p]


def _read_cur_hotspot(path: Path) -> QPoint:
    """读取 CUR 第一帧的热点；损坏资源安全回退到左上角。"""
    try:
        header = path.read_bytes()[:22]
        reserved, image_type, count = struct.unpack_from("<HHH", header)
        if reserved != 0 or image_type != 2 or count < 1:
            return QPoint()
        hotspot_x, hotspot_y = struct.unpack_from("<HH", header, 10)
        return QPoint(hotspot_x, hotspot_y)
    except (OSError, struct.error):
        return QPoint()
