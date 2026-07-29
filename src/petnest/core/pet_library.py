"""冻结版使用的用户可写宠物库初始化。"""

from __future__ import annotations

import shutil
from pathlib import Path

from .package_loader import PackageLoader


class PetLibraryError(RuntimeError):
    """宠物库无法初始化或不包含可用宠物。"""


def default_user_pets_directory(app_name: str = "PetNest") -> Path:
    """返回当前用户可写的默认宠物库位置。"""
    from petnest.core.settings_manager import SettingsManager

    return SettingsManager.default_path(app_name).parent / "pets"


def prepare_pet_library(target: Path, bundled: Path) -> Path:
    """确保可写目标库有宠物；仅在目标库为空时复制内置包。"""
    target = target.expanduser().resolve()
    target.mkdir(parents=True, exist_ok=True)
    loader = PackageLoader()
    if loader.discover(target):
        return target
    for package in loader.discover(bundled):
        destination = target / package.root.name
        if not destination.exists():
            shutil.copytree(package.root, destination)
    if not loader.discover(target):
        raise PetLibraryError("宠物库为空，且无法复制内置示例宠物")
    return target
