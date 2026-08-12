"""命令行入口的安装器辅助命令测试。"""

from pathlib import Path
from types import SimpleNamespace

from petnest import __main__ as main_module
from petnest.__main__ import main
from petnest.core import cursor_style_catalog
from petnest.core.settings_manager import SettingsManager
from petnest.platforms import macos_cursor


def test_set_pets_root_persists_an_absolute_custom_library(tmp_path: Path, monkeypatch) -> None:
    settings_path = tmp_path / "settings.json"
    monkeypatch.setattr(SettingsManager, "default_path", staticmethod(lambda app_name="PetNest": settings_path))

    assert main(["--set-pets-root", str(tmp_path / "D" / "PetNestPets")]) == 0

    assert SettingsManager(settings_path).load().pets_root == str((tmp_path / "D" / "PetNestPets").resolve())


def test_macos_cursor_helper_applies_present_roles_and_restores_missing_roles(tmp_path: Path, monkeypatch) -> None:
    style_root = tmp_path / "cursors" / "test-style"
    style_root.mkdir(parents=True)
    arrow = style_root / "arrow.cur"
    arrow.write_bytes(b"cursor")
    calls: list[tuple[str, str]] = []

    class FakeController:
        supported_roles = frozenset({"arrow", "text"})

        def apply_role(self, role: str, path: Path) -> bool:
            calls.append(("apply", f"{role}:{path.name}"))
            return True

        def restore_role(self, role: str) -> bool:
            calls.append(("restore", role))
            return True

    class FakeCatalog:
        def __init__(self, root: Path) -> None:
            assert root == style_root.parent

        def get(self, identifier: str):
            assert identifier == "test-style"
            return SimpleNamespace(roles={"arrow": arrow})

    monkeypatch.setattr(main_module.sys, "platform", "darwin")
    monkeypatch.setattr(macos_cursor, "MacOSCursorController", FakeController)
    monkeypatch.setattr(cursor_style_catalog, "CursorStyleCatalog", FakeCatalog)

    assert main_module._run_cursor_helper("apply", style_root) == 0
    assert set(calls) == {("apply", "arrow:arrow.cur"), ("restore", "text")}
