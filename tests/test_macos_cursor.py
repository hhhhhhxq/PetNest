"""macOS 原生系统光标注册适配的无副作用测试。"""

from __future__ import annotations

from pathlib import Path
import struct

from PySide6.QtCore import QPoint

from petnest.platforms.cursor import create_cursor_controller
from petnest.platforms.macos_cursor import MacOSCursorController, _ROLE_IDENTIFIERS, _read_cur_hotspot
from petnest.platforms.windows_cursor import WindowsCursorController


class _FakeCursorApi:
    def __init__(self, *, apply_result: bool = True, restore_result: bool = True) -> None:
        self.applied_roles: list[tuple[str, Path]] = []
        self.restored_roles: list[str] = []
        self.restore_all_calls = 0
        self.apply_result = apply_result
        self.restore_result = restore_result

    def apply_role(self, role: str, cursor_path: Path) -> bool:
        self.applied_roles.append((role, cursor_path))
        return self.apply_result

    def restore_role(self, role: str) -> bool:
        self.restored_roles.append(role)
        return self.restore_result

    def restore_roles(self) -> bool:
        self.restore_all_calls += 1
        return self.restore_result


def test_macos_controller_applies_all_roles_and_restores_native_registrations(tmp_path: Path) -> None:
    api = _FakeCursorApi()
    controller = MacOSCursorController(api=api, platform="darwin")
    arrow = tmp_path / "arrow.cur"

    assert controller.apply(arrow) is True
    for role in controller.supported_roles - {"arrow"}:
        assert controller.apply_role(role, tmp_path / f"{role}.cur") is True
    assert controller.apply_role("unsupported", arrow) is False
    assert controller.restore_role("text") is True
    assert controller.restore_role("unsupported") is False
    assert controller.restore_system_defaults() is True
    assert set(api.applied_roles) == {
        (role, tmp_path / f"{role}.cur") for role in controller.supported_roles - {"arrow"}
    } | {("arrow", arrow)}
    assert api.restored_roles == ["text"]
    assert api.restore_all_calls == 1
    assert controller.supported_roles == set(_ROLE_IDENTIFIERS)


def test_non_macos_controller_never_touches_native_api(tmp_path: Path) -> None:
    api = _FakeCursorApi()
    controller = MacOSCursorController(api=api, platform="linux")

    assert controller.apply(tmp_path / "arrow.cur") is False
    assert controller.apply_role("text", tmp_path / "text.cur") is False
    assert controller.restore_role("text") is False
    assert controller.restore_system_defaults() is False
    assert api.applied_roles == []
    assert api.restored_roles == []
    assert api.restore_all_calls == 0


def test_macos_role_identifiers_match_native_cursor_roles() -> None:
    assert _ROLE_IDENTIFIERS == {
        "arrow": b"com.apple.coregraphics.Arrow",
        "text": b"com.apple.coregraphics.IBeam",
        "busy": b"com.apple.cursor.4",
        "move": b"com.apple.coregraphics.Move",
        "resize_horizontal": b"com.apple.cursor.19",
        "resize_vertical": b"com.apple.cursor.23",
        "resize_diag_1": b"com.apple.cursor.34",
        "resize_diag_2": b"com.apple.cursor.30",
    }


def test_cursor_controller_factory_selects_platform_implementation() -> None:
    assert isinstance(create_cursor_controller("darwin"), MacOSCursorController)
    assert isinstance(create_cursor_controller("win32"), WindowsCursorController)


def test_cur_hotspot_reads_first_directory_entry(tmp_path: Path) -> None:
    path = tmp_path / "arrow.cur"
    path.write_bytes(struct.pack("<HHHBBBBHHII", 0, 2, 1, 32, 32, 0, 0, 4, 7, 10, 22) + b"x" * 10)

    assert _read_cur_hotspot(path) == QPoint(4, 7)


def test_cur_hotspot_falls_back_for_invalid_resource(tmp_path: Path) -> None:
    path = tmp_path / "broken.cur"
    path.write_bytes(b"broken")

    assert _read_cur_hotspot(path) == QPoint()
