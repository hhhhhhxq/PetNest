"""macOS 独立更新器的参数和归档安全测试。"""

from pathlib import Path
import stat
from zipfile import ZipFile, ZipInfo

import pytest

from petnest.core.app_update import AppUpdateError
from petnest.core.macos_updater import (
    build_macos_updater_command,
    parse_macos_updater_args,
    validate_macos_archive,
)


def test_macos_updater_command_and_parser_use_absolute_paths(tmp_path: Path) -> None:
    updater = tmp_path / "PetNestUpdater"
    archive = tmp_path / "PetNest.zip"
    target = tmp_path / "PetNest.app"
    command = build_macos_updater_command(updater, archive, target, 123)

    assert command == [
        str(updater),
        "--wait-pid",
        "123",
        "--archive",
        str(archive),
        "--target-app",
        str(target),
    ]
    assert parse_macos_updater_args(command[1:]).target_app == target
    with pytest.raises(AppUpdateError):
        parse_macos_updater_args(["--wait-pid", "1", "--archive", "relative.zip", "--target-app", str(target)])


def test_macos_archive_accepts_petnest_app_root(tmp_path: Path) -> None:
    archive = tmp_path / "PetNest.zip"
    with ZipFile(archive, "w") as package:
        package.writestr("PetNest.app/Contents/Info.plist", b"plist")

    validate_macos_archive(archive)


def test_macos_archive_rejects_path_traversal_and_escaping_symlink(tmp_path: Path) -> None:
    traversal = tmp_path / "traversal.zip"
    with ZipFile(traversal, "w") as package:
        package.writestr("PetNest.app/../outside", b"bad")
    with pytest.raises(AppUpdateError):
        validate_macos_archive(traversal)

    symlink = tmp_path / "symlink.zip"
    link = ZipInfo("PetNest.app/Contents/MacOS/escape")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with ZipFile(symlink, "w") as package:
        package.writestr(link, "../../../outside")
    with pytest.raises(AppUpdateError):
        validate_macos_archive(symlink)
