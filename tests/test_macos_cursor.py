"""macOS 原生普通箭头注册适配的无副作用测试。"""

from __future__ import annotations

from pathlib import Path
import struct

from PySide6.QtCore import QPoint

from petnest.platforms.cursor import create_cursor_controller
from petnest.platforms.macos_cursor import MacOSCursorController, _read_cur_hotspot
from petnest.platforms.windows_cursor import WindowsCursorController


class _FakeCursorApi:
    def __init__(self, *, apply_result: bool = True, restore_result: bool = True) -> None:
        self.applied_paths: list[Path] = []
        self.restore_calls = 0
        self.apply_result = apply_result
        self.restore_result = restore_result

    def apply_arrow(self, cursor_path: Path) -> bool:
        self.applied_paths.append(cursor_path)
        return self.apply_result

    def restore_arrow(self) -> bool:
        self.restore_calls += 1
        return self.restore_result


def test_macos_controller_applies_arrow_and_restores_native_registration(tmp_path: Path) -> None:
    api = _FakeCursorApi()
    controller = MacOSCursorController(api=api, platform="darwin")
    arrow = tmp_path / "arrow.cur"

    assert controller.apply(arrow) is True
    assert controller.apply_role("text", arrow) is False
    assert controller.restore_system_defaults() is True
    assert api.applied_paths == [arrow]
    assert api.restore_calls == 1
    assert controller.supported_roles == {"arrow"}


def test_non_macos_controller_never_touches_native_api(tmp_path: Path) -> None:
    api = _FakeCursorApi()
    controller = MacOSCursorController(api=api, platform="linux")

    assert controller.apply(tmp_path / "arrow.cur") is False
    assert controller.restore_system_defaults() is False
    assert api.applied_paths == []
    assert api.restore_calls == 0


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
