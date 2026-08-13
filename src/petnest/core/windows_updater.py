"""Windows 更新器的无 Qt 进程控制逻辑。

主程序将独立的 ``PetNestUpdateHost.exe`` 复制到临时目录后运行，不在更新宿主
仍运行时覆盖安装目录。
该模块保留标准库实现，macOS 不会调用它；参数解析和等待逻辑可在所有平台测试。
"""

from __future__ import annotations

from dataclasses import dataclass
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid

from petnest.core.app_update import AppUpdateError


_SEE_MASK_NOCLOSEPROCESS = 0x00000040
_WAIT_OBJECT_0 = 0x00000000
_WAIT_TIMEOUT = 0x00000102
_INSTALLER_WAIT_TIMEOUT_MS = 30 * 60 * 1000


class InstallerProcessNotExitedError(AppUpdateError):
    """安装器仍可能占用安装目录，此时不能重启 PetNest。"""


class _ShellExecuteInfo(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("fMask", wintypes.ULONG),
        ("hwnd", wintypes.HWND),
        ("lpVerb", wintypes.LPCWSTR),
        ("lpFile", wintypes.LPCWSTR),
        ("lpParameters", wintypes.LPCWSTR),
        ("lpDirectory", wintypes.LPCWSTR),
        ("nShow", wintypes.INT),
        ("hInstApp", wintypes.HINSTANCE),
        ("lpIDList", wintypes.LPVOID),
        ("lpClass", wintypes.LPCWSTR),
        ("hkeyClass", wintypes.HKEY),
        ("dwHotKey", wintypes.DWORD),
        ("hIcon", wintypes.HANDLE),
        ("hProcess", wintypes.HANDLE),
    ]


@dataclass(frozen=True)
class UpdaterArguments:
    wait_pid: int
    installer: Path
    restart: Path | None = None


def stage_windows_updater(source: Path, staging_directory: Path) -> Path:
    """将更新宿主复制到安装目录之外，避免安装器覆盖正在运行的自身。"""

    source = Path(source)
    staging_directory = Path(staging_directory)
    if not source.is_file():
        raise AppUpdateError("安装包缺少 Windows 更新宿主")
    staging_directory.mkdir(parents=True, exist_ok=True)
    for candidate in staging_directory.glob("PetNestUpdateHost-*.exe"):
        try:
            candidate.unlink()
        except OSError:
            # 上一次更新宿主仍在退出时可能暂时无法删除；唯一文件名可避免冲突。
            pass
    destination = staging_directory / f"PetNestUpdateHost-{uuid.uuid4().hex}.exe"
    try:
        shutil.copy2(source, destination)
    except OSError as error:
        raise AppUpdateError(f"无法准备 Windows 更新宿主：{error}") from error
    return destination


def parse_updater_args(argv: list[str]) -> UpdaterArguments:
    """严格解析 updater 参数，拒绝未知参数与相对路径。"""

    values: dict[str, str] = {}
    index = 0
    while index < len(argv):
        flag = argv[index]
        if flag not in {"--wait-pid", "--installer", "--restart"} or index + 1 >= len(argv):
            raise AppUpdateError("updater 参数无效")
        if flag in values:
            raise AppUpdateError("updater 参数重复")
        values[flag] = argv[index + 1]
        index += 2
    try:
        wait_pid = int(values["--wait-pid"])
    except (KeyError, ValueError) as error:
        raise AppUpdateError("updater 父进程 PID 无效") from error
    if wait_pid <= 0:
        raise AppUpdateError("updater 父进程 PID 无效")
    installer = _absolute_path(values.get("--installer"), "安装包")
    restart_value = values.get("--restart")
    restart = _absolute_path(restart_value, "重启路径") if restart_value is not None else None
    return UpdaterArguments(wait_pid, installer, restart)


def _absolute_path(value: str | None, label: str) -> Path:
    if not value:
        raise AppUpdateError(f"updater 缺少{label}")
    path = Path(value)
    if not path.is_absolute() or "\x00" in value:
        raise AppUpdateError(f"updater {label}路径无效")
    return path


def wait_for_process_exit(pid: int, *, timeout: float = 90.0, poll_interval: float = 0.25) -> bool:
    """等待父进程退出，超时返回 ``False``，不无限阻塞安装。"""

    if pid <= 0 or timeout < 0 or poll_interval <= 0:
        return False
    if sys.platform == "win32":
        waited = _wait_for_windows_process(pid, timeout)
        if waited is not None:
            return waited
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _process_exists(pid):
            return True
        time.sleep(min(poll_interval, max(0.0, deadline - time.monotonic())))
    return not _process_exists(pid)


def _process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # 拒绝访问说明 PID 仍被占用，不能误判为已退出而立刻覆盖安装目录。
        return True
    except OSError:
        return False
    return True


def _wait_for_windows_process(pid: int, timeout: float) -> bool | None:
    if not hasattr(ctypes, "windll"):
        return None
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(0x00100000 | 0x0001, False, pid)
    if not handle:
        return None
    try:
        result = kernel32.WaitForSingleObject(handle, max(0, int(timeout * 1000)))
        return result == 0
    finally:
        kernel32.CloseHandle(handle)


def _run_elevated_installer(installer: Path) -> int:
    """通过 UAC ``runas`` 启动安装器，并等待安装器返回结果。"""

    if sys.platform != "win32":
        raise AppUpdateError("Windows updater 只能在 Windows 上运行")
    windll = getattr(ctypes, "windll", None)
    if windll is None:
        raise AppUpdateError("当前环境无法调用 Windows 安装权限接口")

    log_path = installer.with_name(installer.name + ".log")
    parameters = subprocess.list2cmdline(
        [
            "/VERYSILENT",
            "/SUPPRESSMSGBOXES",
            "/CLOSEAPPLICATIONS",
            "/NORESTART",
            f"/LOG={log_path}",
        ]
    )
    execute_info = _ShellExecuteInfo()
    execute_info.cbSize = ctypes.sizeof(execute_info)
    execute_info.fMask = _SEE_MASK_NOCLOSEPROCESS
    execute_info.lpVerb = "runas"
    execute_info.lpFile = str(installer)
    execute_info.lpParameters = parameters
    execute_info.lpDirectory = str(installer.parent)
    execute_info.nShow = 1

    if not windll.shell32.ShellExecuteExW(ctypes.byref(execute_info)):
        error_code = int(windll.kernel32.GetLastError())
        raise AppUpdateError(f"无法以管理员权限启动安装器（Windows 错误 {error_code}）")
    if not execute_info.hProcess:
        raise InstallerProcessNotExitedError("安装器已启动但未返回进程句柄")

    try:
        wait_result = int(
            windll.kernel32.WaitForSingleObject(
                execute_info.hProcess,
                _INSTALLER_WAIT_TIMEOUT_MS,
            )
        )
        if wait_result == _WAIT_TIMEOUT:
            raise InstallerProcessNotExitedError("安装器运行超时，请查看安装器日志后重试")
        if wait_result != _WAIT_OBJECT_0:
            raise InstallerProcessNotExitedError(f"无法确认安装器已经结束（Windows 状态 {wait_result}）")
        exit_code = wintypes.DWORD()
        if not windll.kernel32.GetExitCodeProcess(
            execute_info.hProcess,
            ctypes.byref(exit_code),
        ):
            raise AppUpdateError("无法读取安装器退出状态")
        return int(exit_code.value)
    finally:
        windll.kernel32.CloseHandle(execute_info.hProcess)


def run_installer(arguments: UpdaterArguments) -> int:
    """等待主程序退出后以静默模式运行 Inno Setup，再按需重启。"""

    if sys.platform != "win32":
        raise AppUpdateError("Windows updater 只能在 Windows 上运行")
    if not arguments.installer.is_file():
        raise AppUpdateError("更新安装包不存在")
    if not wait_for_process_exit(arguments.wait_pid):
        raise AppUpdateError("等待 PetNest 退出超时")
    installer_has_exited = False
    try:
        result = _run_elevated_installer(arguments.installer)
        installer_has_exited = True
        return result
    except InstallerProcessNotExitedError:
        raise
    except Exception:
        # 启动安装器前的 UAC 取消等错误不会留下安装器进程，可以安全恢复应用。
        installer_has_exited = True
        raise
    finally:
        # 安装失败、用户取消 UAC 或安装成功后都恢复应用，避免桌宠无声消失。
        if installer_has_exited and arguments.restart is not None and arguments.restart.is_file():
            subprocess.Popen([str(arguments.restart)], cwd=str(arguments.restart.parent), close_fds=True)
