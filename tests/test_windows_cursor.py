"""Windows 普通箭头光标控制器的无副作用测试。"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from pathlib import Path

from petnest.platforms.windows_cursor import OCR_NORMAL, WindowsCursorController, _CtypesCursorApi


class _FakeCursorApi:
    def __init__(self, *, registry_arrow: str | None = None) -> None:
        self.registry_arrow = registry_arrow
        self.loaded_paths: list[Path] = []
        self.loaded_system_default = 0
        self.set_calls: list[tuple[int, int]] = []
        self.system_cursor_restore_calls = 0

    def load_file_cursor(self, path: Path) -> int | None:
        self.loaded_paths.append(path)
        return 101

    def load_saved_cursor_or_system_default(self, value_name: str, resource_id: int) -> int | None:
        assert value_name == "Arrow"
        assert resource_id == OCR_NORMAL
        if self.registry_arrow is not None:
            self.loaded_paths.append(Path(self.registry_arrow))
        else:
            self.loaded_system_default += 1
        return 102

    @staticmethod
    def copy_cursor(handle: int) -> int | None:
        return handle + 1_000

    def set_system_cursor(self, handle: int, role: int) -> bool:
        self.set_calls.append((handle, role))
        return True

    def restore_system_cursors(self) -> bool:
        self.system_cursor_restore_calls += 1
        return True


def test_apply_sets_only_normal_cursor(tmp_path: Path) -> None:
    api = _FakeCursorApi()
    controller = WindowsCursorController(api=api, platform="win32")

    assert controller.apply(tmp_path / "arrow.cur") is True
    assert api.loaded_paths == [tmp_path / "arrow.cur"]
    assert api.set_calls == [(1_101, OCR_NORMAL)]


def test_restore_loads_only_users_saved_arrow() -> None:
    api = _FakeCursorApi(registry_arrow="C:/Users/me/arrow.cur")
    controller = WindowsCursorController(api=api, platform="win32")

    assert controller.restore_normal() is True
    assert api.loaded_paths == [Path("C:/Users/me/arrow.cur")]
    assert api.set_calls == [(1_102, OCR_NORMAL)]


def test_restore_system_defaults_reloads_the_saved_windows_cursor_scheme() -> None:
    api = _FakeCursorApi()
    controller = WindowsCursorController(api=api, platform="win32")

    assert controller.restore_system_defaults() is True
    assert api.system_cursor_restore_calls == 1
    assert api.set_calls == []


def test_non_windows_controller_never_calls_the_system_api(tmp_path: Path) -> None:
    api = _FakeCursorApi()
    controller = WindowsCursorController(api=api, platform="darwin")

    assert controller.apply(tmp_path / "arrow.cur") is False
    assert controller.restore_normal() is False
    assert controller.restore_system_defaults() is False
    assert api.set_calls == []


def test_ctypes_cursor_api_declares_pointer_sized_handle_parameters(monkeypatch) -> None:
    class _Function:
        restype = None
        argtypes = None

    class _User32:
        LoadImageW = _Function()
        LoadCursorW = _Function()
        CopyImage = _Function()
        SetSystemCursor = _Function()
        SystemParametersInfoW = _Function()

    user32 = _User32()
    monkeypatch.setattr(
        "petnest.platforms.windows_cursor.ctypes.WinDLL",
        lambda *_args, **_kwargs: user32,
        raising=False,
    )
    monkeypatch.setattr("petnest.platforms.windows_cursor.sys.platform", "win32")

    api = _CtypesCursorApi()

    assert api._user32 is user32
    assert user32.CopyImage.argtypes[0] is wintypes.HANDLE
    assert user32.SetSystemCursor.argtypes == [wintypes.HANDLE, wintypes.DWORD]
    assert user32.SystemParametersInfoW.argtypes == [wintypes.UINT, wintypes.UINT, wintypes.LPVOID, wintypes.UINT]
