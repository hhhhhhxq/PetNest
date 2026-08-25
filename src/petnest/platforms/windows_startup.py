"""Windows 当前用户登录启动任务。"""

from __future__ import annotations

import csv
import io
import locale
import logging
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable
from subprocess import CompletedProcess
from xml.etree import ElementTree

from petnest_startup_host import cancel_running_hosts

from .base import StartupRegistrationResult

LOGGER = logging.getLogger(__name__)

LEGACY_TASK_NAME = r"\PetNest\AutoStart"
TASK_NAME_PREFIX = LEGACY_TASK_NAME + "-"
TASK_NAMESPACE = "http://schemas.microsoft.com/windows/2004/02/mit/task"
COMMAND_TIMEOUT_SECONDS = 15
_SID_PATTERN = re.compile(r"S-\d+(?:-\d+)+")

CommandRunner = Callable[[list[str]], CompletedProcess[str]]
SidProvider = Callable[[], str]
HostCanceller = Callable[[], None]


def task_name_for_sid(user_sid: str) -> str:
    """为每个 Windows 用户生成互不冲突的系统任务名。"""
    if _SID_PATTERN.fullmatch(user_sid) is None:
        raise ValueError("无效的 Windows 用户 SID")
    return TASK_NAME_PREFIX + user_sid


def _add(parent: ElementTree.Element, name: str, text: str | None = None, **attributes: str) -> ElementTree.Element:
    child = ElementTree.SubElement(parent, f"{{{TASK_NAMESPACE}}}{name}", attributes)
    child.text = text
    return child


def build_task_xml(startup_host: Path, user_sid: str) -> str:
    """生成当前用户任务的 XML，避免通过 shell 拼接参数。"""
    ElementTree.register_namespace("", TASK_NAMESPACE)
    root = ElementTree.Element(f"{{{TASK_NAMESPACE}}}Task", {"version": "1.4"})

    registration = _add(root, "RegistrationInfo")
    _add(registration, "Author", "PetNest")
    _add(registration, "Description", "登录 Windows 后自动启动 PetNest")

    triggers = _add(root, "Triggers")
    logon = _add(triggers, "LogonTrigger")
    _add(logon, "Enabled", "true")
    _add(logon, "UserId", user_sid)

    principals = _add(root, "Principals")
    principal = _add(principals, "Principal", id="Author")
    _add(principal, "UserId", user_sid)
    _add(principal, "LogonType", "InteractiveToken")
    _add(principal, "RunLevel", "LeastPrivilege")

    settings = _add(root, "Settings")
    _add(settings, "MultipleInstancesPolicy", "IgnoreNew")
    _add(settings, "DisallowStartIfOnBatteries", "false")
    _add(settings, "StopIfGoingOnBatteries", "false")
    _add(settings, "AllowHardTerminate", "true")
    _add(settings, "StartWhenAvailable", "true")
    _add(settings, "RunOnlyIfNetworkAvailable", "false")
    _add(settings, "AllowStartOnDemand", "true")
    _add(settings, "Enabled", "true")
    _add(settings, "Hidden", "false")
    _add(settings, "RunOnlyIfIdle", "false")
    _add(settings, "WakeToRun", "false")
    _add(settings, "ExecutionTimeLimit", "PT0S")
    _add(settings, "Priority", "7")
    actions = _add(root, "Actions", Context="Author")
    execute = _add(actions, "Exec")
    _add(execute, "Command", str(startup_host))
    _add(execute, "WorkingDirectory", str(startup_host.parent))

    body = ElementTree.tostring(root, encoding="unicode", short_empty_elements=False)
    return f'<?xml version="1.0" encoding="UTF-16"?>\n{body}'


def _system_executable(name: str) -> Path:
    windows_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    return windows_root / "System32" / name


def _run_command(arguments: list[str]) -> CompletedProcess[str]:
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    return subprocess.run(
        arguments,
        check=False,
        capture_output=True,
        text=True,
        encoding=locale.getpreferredencoding(False),
        errors="replace",
        timeout=COMMAND_TIMEOUT_SECONDS,
        creationflags=creation_flags,
    )


def _current_user_sid() -> str:
    command = [str(_system_executable("whoami.exe")), "/user", "/fo", "csv", "/nh"]
    result = _run_command(command)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip() or f"退出码 {result.returncode}"
        raise OSError(f"无法读取当前用户 SID：{detail}")
    rows = list(csv.reader(io.StringIO(result.stdout)))
    if len(rows) != 1 or len(rows[0]) < 2:
        raise ValueError("无法解析当前用户 SID")
    sid = rows[0][1].strip()
    task_name_for_sid(sid)
    return sid


class WindowsStartupTask:
    """管理以当前用户 SID 隔离的 PetNest 计划任务。"""

    def __init__(
        self,
        *,
        executable: Path | None = None,
        startup_host: Path | None = None,
        frozen: bool | None = None,
        runner: CommandRunner | None = None,
        sid_provider: SidProvider | None = None,
        temporary_directory: Path | None = None,
        host_canceller: HostCanceller | None = None,
    ) -> None:
        self.executable = Path(executable or sys.executable).resolve()
        self.startup_host = Path(
            startup_host or self.executable.with_name("PetNestStartupHost.exe")
        ).resolve()
        self.frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
        self._runner = runner or _run_command
        self._sid_provider = sid_provider or _current_user_sid
        self._temporary_directory = temporary_directory
        self._host_canceller = host_canceller or cancel_running_hosts
        self._schtasks = _system_executable("schtasks.exe")

    @property
    def supported(self) -> bool:
        return self.frozen

    def configure(self, enabled: bool) -> StartupRegistrationResult:
        if enabled and not self.supported:
            return StartupRegistrationResult(False, message="源码运行模式不登记自动启动")
        try:
            if enabled:
                return self._enable()
            return self._disable()
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            LOGGER.warning("无法修改 Windows 自动启动任务", exc_info=True)
            return StartupRegistrationResult(False, message=str(error))

    def remove_all(self) -> StartupRegistrationResult:
        """以提升权限卸载时删除 PetNest 命名空间内的全部登录任务。"""
        try:
            self._host_canceller()
            result = self._runner(self._remove_all_command())
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            LOGGER.warning("无法清理 Windows 自动启动任务", exc_info=True)
            return StartupRegistrationResult(False, message=str(error))
        if result.returncode in {0, 3}:
            return StartupRegistrationResult(True)
        return self._command_result(result, "清理自动启动任务")

    def _enable(self) -> StartupRegistrationResult:
        if not self.executable.is_file():
            raise OSError(f"找不到 PetNest 主程序：{self.executable}")
        if not self.startup_host.is_file():
            raise OSError(f"找不到自动启动守护程序：{self.startup_host}")
        sid = self._sid_provider()
        task_name = task_name_for_sid(sid)
        xml_contents = build_task_xml(self.startup_host, sid)
        xml_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-16",
                suffix=".xml",
                prefix="petnest-autostart-",
                dir=self._temporary_directory,
                delete=False,
            ) as handle:
                handle.write(xml_contents)
                xml_path = Path(handle.name)
            result = self._runner(
                [str(self._schtasks), "/Create", "/TN", task_name, "/XML", str(xml_path), "/F"]
            )
            return self._command_result(result, "创建自动启动任务")
        finally:
            if xml_path is not None:
                try:
                    xml_path.unlink(missing_ok=True)
                except OSError:
                    LOGGER.warning("无法清理临时任务 XML：%s", xml_path, exc_info=True)

    def _disable(self) -> StartupRegistrationResult:
        self._host_canceller()
        task_name = task_name_for_sid(self._sid_provider())
        probe = self._runner(self._probe_command(task_name))
        if probe.returncode == 3:
            return StartupRegistrationResult(True)
        if probe.returncode != 0:
            return self._command_result(probe, "查询自动启动任务")
        deleted = self._runner([str(self._schtasks), "/Delete", "/TN", task_name, "/F"])
        return self._command_result(deleted, "删除自动启动任务")

    @staticmethod
    def _probe_command(task_name: str) -> list[str]:
        escaped_name = task_name.replace("'", "''")
        script = (
            "$ErrorActionPreference='Stop';"
            "try{$service=New-Object -ComObject 'Schedule.Service';"
            "$service.Connect();"
            f"$null=$service.GetFolder('\\').GetTask('{escaped_name}');exit 0}}"
            "catch [System.Runtime.InteropServices.COMException]{"
            "if($_.Exception.HResult -eq -2147024894){exit 3};"
            "[Console]::Error.Write($_.Exception.Message);exit 1}"
            "catch{[Console]::Error.Write($_.Exception.Message);exit 1}"
        )
        powershell = _system_executable(r"WindowsPowerShell\v1.0\powershell.exe")
        return [
            str(powershell),
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            script,
        ]

    @staticmethod
    def _remove_all_command() -> list[str]:
        script = (
            "$ErrorActionPreference='Stop';"
            "try{$service=New-Object -ComObject 'Schedule.Service';"
            "$service.Connect();"
            "$folder=$service.GetFolder('\\PetNest');"
            "$pattern='^AutoStart(?:-S-\\d+(?:-\\d+)+)?$';"
            "foreach($task in @($folder.GetTasks(0))){"
            "if($task.Name -match $pattern){"
            "try{$folder.DeleteTask($task.Name,0)}"
            "catch [System.Runtime.InteropServices.COMException]{"
            "if($_.Exception.HResult -ne -2147024894){throw}}}};"
            "exit 0}"
            "catch [System.Runtime.InteropServices.COMException]{"
            "if($_.Exception.HResult -eq -2147024894){exit 3};"
            "[Console]::Error.Write($_.Exception.Message);exit 1}"
            "catch{[Console]::Error.Write($_.Exception.Message);exit 1}"
        )
        powershell = _system_executable(r"WindowsPowerShell\v1.0\powershell.exe")
        return [
            str(powershell),
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            script,
        ]

    @staticmethod
    def _command_result(result: CompletedProcess[str], action: str) -> StartupRegistrationResult:
        if result.returncode == 0:
            return StartupRegistrationResult(True)
        detail = (result.stderr or result.stdout).strip() or f"退出码 {result.returncode}"
        return StartupRegistrationResult(False, message=f"{action}失败：{detail}")

__all__ = [
    "LEGACY_TASK_NAME",
    "TASK_NAME_PREFIX",
    "WindowsStartupTask",
    "build_task_xml",
    "task_name_for_sid",
]
