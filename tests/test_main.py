"""命令行入口的安装器辅助命令测试。"""

from pathlib import Path

from petnest.__main__ import main
from petnest.core.settings_manager import SettingsManager


def test_set_pets_root_persists_an_absolute_custom_library(tmp_path: Path, monkeypatch) -> None:
    settings_path = tmp_path / "settings.json"
    monkeypatch.setattr(SettingsManager, "default_path", staticmethod(lambda app_name="PetNest": settings_path))

    assert main(["--set-pets-root", str(tmp_path / "D" / "PetNestPets")]) == 0

    assert SettingsManager(settings_path).load().pets_root == str((tmp_path / "D" / "PetNestPets").resolve())
