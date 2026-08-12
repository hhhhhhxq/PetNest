"""macOS 应用包更新器的无 Qt 替换与回滚逻辑。"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path, PurePosixPath
import plistlib
import shutil
import stat
import subprocess
import sys
import tempfile
import uuid
from zipfile import BadZipFile, ZipFile, ZipInfo

from petnest.core.app_update import AppUpdateError
from petnest.core.windows_updater import wait_for_process_exit


MAX_ARCHIVE_FILES = 20_000
MAX_UNCOMPRESSED_BYTES = 2 * 1024 * 1024 * 1024
EXPECTED_BUNDLE_ID = "com.petnest.app"


@dataclass(frozen=True)
class MacUpdaterArguments:
    wait_pid: int
    archive: Path
    target_app: Path


def parse_macos_updater_args(argv: list[str]) -> MacUpdaterArguments:
    """严格解析 macOS updater 参数，拒绝未知参数与相对路径。"""

    values: dict[str, str] = {}
    index = 0
    while index < len(argv):
        flag = argv[index]
        if flag not in {"--wait-pid", "--archive", "--target-app"} or index + 1 >= len(argv):
            raise AppUpdateError("macOS updater 参数无效")
        if flag in values:
            raise AppUpdateError("macOS updater 参数重复")
        values[flag] = argv[index + 1]
        index += 2
    try:
        wait_pid = int(values["--wait-pid"])
    except (KeyError, ValueError) as error:
        raise AppUpdateError("updater 父进程 PID 无效") from error
    if wait_pid <= 0:
        raise AppUpdateError("updater 父进程 PID 无效")
    archive = _absolute_path(values.get("--archive"), "更新包")
    target_app = _absolute_path(values.get("--target-app"), "目标应用")
    if target_app.suffix.casefold() != ".app":
        raise AppUpdateError("updater 目标应用路径无效")
    return MacUpdaterArguments(wait_pid, archive, target_app)


def build_macos_updater_command(
    updater_path: Path,
    archive_path: Path,
    target_app: Path,
    parent_pid: int,
) -> list[str]:
    if isinstance(parent_pid, bool) or not isinstance(parent_pid, int) or parent_pid <= 0:
        raise AppUpdateError("父进程 PID 无效")
    updater = Path(updater_path)
    archive = Path(archive_path)
    target = Path(target_app)
    if not updater.is_absolute() or not archive.is_absolute() or not target.is_absolute():
        raise AppUpdateError("macOS updater 路径必须是绝对路径")
    if target.suffix.casefold() != ".app":
        raise AppUpdateError("updater 目标应用路径无效")
    return [
        str(updater),
        "--wait-pid",
        str(parent_pid),
        "--archive",
        str(archive),
        "--target-app",
        str(target),
    ]


def _absolute_path(value: str | None, label: str) -> Path:
    if not value or "\x00" in value:
        raise AppUpdateError(f"updater {label}路径无效")
    path = Path(value)
    if not path.is_absolute():
        raise AppUpdateError(f"updater {label}路径无效")
    return path


def _safe_archive_member(info: ZipInfo) -> None:
    path = PurePosixPath(info.filename)
    if not info.filename or path.is_absolute() or ".." in path.parts or "\x00" in info.filename:
        raise AppUpdateError("macOS 更新包包含不安全路径")
    if not path.parts or path.parts[0] != "PetNest.app":
        raise AppUpdateError("macOS 更新包根目录必须是 PetNest.app")
    mode = info.external_attr >> 16
    file_type = stat.S_IFMT(mode)
    if file_type not in {0, stat.S_IFREG, stat.S_IFDIR, stat.S_IFLNK}:
        raise AppUpdateError("macOS 更新包包含不支持的文件类型")


def validate_macos_archive(archive: Path) -> None:
    """在交给系统解压前限制路径、类型、文件数和展开大小。"""

    try:
        with ZipFile(archive) as package:
            infos = package.infolist()
            if not infos or len(infos) > MAX_ARCHIVE_FILES:
                raise AppUpdateError("macOS 更新包文件数量无效")
            total = 0
            for info in infos:
                _safe_archive_member(info)
                total += info.file_size
                if total > MAX_UNCOMPRESSED_BYTES:
                    raise AppUpdateError("macOS 更新包展开后过大")
                mode = info.external_attr >> 16
                if stat.S_IFMT(mode) == stat.S_IFLNK:
                    target = package.read(info).decode("utf-8", errors="strict")
                    link = PurePosixPath(target)
                    if link.is_absolute() or "\x00" in target:
                        raise AppUpdateError("macOS 更新包包含不安全符号链接")
                    resolved = list(PurePosixPath(info.filename).parent.parts)
                    for part in link.parts:
                        if part in {"", "."}:
                            continue
                        if part == "..":
                            if len(resolved) <= 1:
                                raise AppUpdateError("macOS 更新包包含越界符号链接")
                            resolved.pop()
                        else:
                            resolved.append(part)
    except AppUpdateError:
        raise
    except (BadZipFile, OSError, UnicodeError) as error:
        raise AppUpdateError(f"macOS 更新包无效：{error}") from error


def _verify_app_bundle(app_path: Path) -> None:
    plist_path = app_path / "Contents" / "Info.plist"
    try:
        with plist_path.open("rb") as stream:
            info = plistlib.load(stream)
    except (OSError, plistlib.InvalidFileException) as error:
        raise AppUpdateError("更新包缺少有效的应用信息") from error
    if not isinstance(info, dict) or info.get("CFBundleIdentifier") != EXPECTED_BUNDLE_ID:
        raise AppUpdateError("更新包应用标识不匹配")
    executable_name = info.get("CFBundleExecutable")
    if not isinstance(executable_name, str) or not executable_name:
        raise AppUpdateError("更新包缺少主程序信息")
    executable = app_path / "Contents" / "MacOS" / executable_name
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise AppUpdateError("更新包主程序不可执行")
    try:
        result = subprocess.run(
            ["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app_path)],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise AppUpdateError("无法校验更新包代码签名") from error
    if result.returncode != 0:
        raise AppUpdateError("更新包代码签名校验失败")


def run_macos_update(arguments: MacUpdaterArguments) -> int:
    """等待主程序退出，替换 `.app`；任何失败都尽力恢复旧版本。"""

    if sys.platform != "darwin":
        raise AppUpdateError("macOS updater 只能在 macOS 上运行")
    if not arguments.archive.is_file():
        raise AppUpdateError("macOS 更新包不存在")
    if not arguments.target_app.is_dir():
        raise AppUpdateError("当前 PetNest.app 不存在")
    validate_macos_archive(arguments.archive)
    if not wait_for_process_exit(arguments.wait_pid):
        raise AppUpdateError("等待 PetNest 退出超时")

    target = arguments.target_app
    parent = target.parent
    staging = Path(tempfile.mkdtemp(prefix=".PetNest-update-", dir=parent))
    backup = parent / f".PetNest-backup-{uuid.uuid4().hex}.app"
    try:
        try:
            result = subprocess.run(
                ["/usr/bin/ditto", "-x", "-k", str(arguments.archive), str(staging)],
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise AppUpdateError("无法解压 macOS 更新包") from error
        if result.returncode != 0:
            raise AppUpdateError("无法解压 macOS 更新包")
        replacement = staging / "PetNest.app"
        _verify_app_bundle(replacement)
        target.replace(backup)
        try:
            replacement.replace(target)
        except Exception:
            backup.replace(target)
            raise
        arguments.archive.unlink(missing_ok=True)
        try:
            subprocess.Popen(["/usr/bin/open", "-n", str(target)], close_fds=True)
        except OSError as error:
            failed = staging / "failed-PetNest.app"
            target.replace(failed)
            backup.replace(target)
            raise AppUpdateError("新版本已写入但无法重新启动，已恢复旧版本") from error
        shutil.rmtree(backup, ignore_errors=True)
        return 0
    except AppUpdateError:
        raise
    except OSError as error:
        if backup.exists() and not target.exists():
            backup.replace(target)
        raise AppUpdateError(f"无法替换 PetNest.app：{error}") from error
    finally:
        shutil.rmtree(staging, ignore_errors=True)
