"""Windows 公用网络与 PetNest 局域网防火墙规则检查。"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Callable


LAN_PORT = 18487
UDP_RULE_NAME = "PetNest LAN UDP 18487"
TCP_RULE_NAME = "PetNest LAN TCP 18487"
FIREWALL_HELPER_ARGUMENT = "--configure-lan-firewall-public"
FIREWALL_EXIT_INVALID_TARGET = 2
FIREWALL_EXIT_FAILED = 10
FIREWALL_EXIT_POLICY_BLOCKED = 20


@dataclass(frozen=True, slots=True)
class LanFirewallStatus:
    applicable: bool = False
    public_network_active: bool = False
    public_network_key: str | None = None
    firewall_enabled: bool = False
    udp_allowed: bool = False
    tcp_allowed: bool = False
    policy_managed: bool = False
    can_repair: bool = False
    error: str | None = None

    @property
    def requires_attention(self) -> bool:
        return (
            self.applicable
            and self.public_network_active
            and self.firewall_enabled
            and not (self.udp_allowed and self.tcp_allowed)
            and self.error is None
        )


@dataclass(frozen=True, slots=True)
class FirewallRepairResult:
    succeeded: bool
    message: str = ""
    cancelled: bool = False


class WindowsLanFirewallBackend:
    def __init__(
        self,
        *,
        executable: Path | None = None,
        platform: str | None = None,
        frozen: bool | None = None,
        command_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        elevated_runner: Callable[[Path], FirewallRepairResult] | None = None,
    ) -> None:
        self.executable = (executable or Path(sys.executable)).resolve()
        self.platform = platform or sys.platform
        self.frozen = bool(getattr(sys, "frozen", False) if frozen is None else frozen)
        self._command_runner = command_runner
        self._elevated_runner = elevated_runner or run_elevated_firewall_helper

    def inspect(self) -> LanFirewallStatus:
        if self.platform != "win32":
            return LanFirewallStatus()
        script = _inspection_script(self.executable)
        powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
        command = [
            str(powershell),
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ]
        try:
            completed = self._command_runner(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=8,
                shell=False,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if completed.returncode != 0:
                raise RuntimeError("PowerShell returned a non-zero exit code")
            if not completed.stdout.strip():
                raise ValueError("PowerShell returned no status")
            payload = json.loads(completed.stdout)
            identities = sorted(
                value for value in payload.get("publicNetworks", []) if isinstance(value, str) and value
            )
            key = None
            if identities:
                key = hashlib.sha256("\n".join(identities).encode("utf-8")).hexdigest()
            return LanFirewallStatus(
                applicable=True,
                public_network_active=bool(identities),
                public_network_key=key,
                firewall_enabled=bool(payload.get("firewallEnabled")),
                udp_allowed=bool(payload.get("udpAllowed")),
                tcp_allowed=bool(payload.get("tcpAllowed")),
                policy_managed=bool(payload.get("policyManaged")),
                can_repair=self.frozen and not bool(payload.get("policyManaged")),
            )
        except (OSError, subprocess.SubprocessError, RuntimeError, ValueError, json.JSONDecodeError) as error:
            return LanFirewallStatus(
                applicable=True,
                can_repair=self.frozen,
                error=f"无法检查 Windows 防火墙：{error.__class__.__name__}",
            )

    def repair(self) -> FirewallRepairResult:
        if self.platform != "win32":
            return FirewallRepairResult(False, "当前系统不使用 Windows 防火墙修复。")
        if not self.frozen:
            return FirewallRepairResult(False, "开发模式不能自动修改防火墙，请使用安装版 PetNest。")
        return self._elevated_runner(self.executable)


def _inspection_script(executable: Path) -> str:
    program = str(executable).replace("'", "''")
    return rf"""
$ErrorActionPreference = 'Stop'
$program = '{program}'
$defaultInterfaces = @(Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue |
    Where-Object {{ $_.State -eq 'Alive' }} | Select-Object -ExpandProperty InterfaceIndex -Unique)
$publicProfiles = @(Get-NetConnectionProfile | Where-Object {{
    $_.NetworkCategory -eq 'Public' -and $defaultInterfaces -contains $_.InterfaceIndex
}})
$identities = @($publicProfiles | ForEach-Object {{ "NetworkProfile:$($_.InterfaceIndex):$($_.Name)" }})
$publicFirewall = Get-NetFirewallProfile -Profile Public -PolicyStore ActiveStore
$firewallEnabled = [bool]$publicFirewall.Enabled
$policyManaged = [string]$publicFirewall.AllowLocalFirewallRules -eq 'False'
function Test-PetNestRule([string]$displayName, [string]$protocol) {{
    $rules = @(Get-NetFirewallRule -DisplayName $displayName -ErrorAction SilentlyContinue | Where-Object {{
        $_.Enabled -eq 'True' -and $_.Direction -eq 'Inbound' -and $_.Action -eq 'Allow' -and
        (($_.Profile -band 4) -ne 0 -or $_.Profile -eq 'Any')
    }})
    foreach ($rule in $rules) {{
        $port = $rule | Get-NetFirewallPortFilter
        $app = $rule | Get-NetFirewallApplicationFilter
        if ($port.Protocol -eq $protocol -and "$($port.LocalPort)" -eq '{LAN_PORT}' -and
            [string]::Equals($app.Program, $program, [System.StringComparison]::OrdinalIgnoreCase)) {{ return $true }}
    }}
    return $false
}}
[ordered]@{{
    publicNetworks = $identities
    firewallEnabled = $firewallEnabled
    udpAllowed = [bool](Test-PetNestRule '{UDP_RULE_NAME}' 'UDP')
    tcpAllowed = [bool](Test-PetNestRule '{TCP_RULE_NAME}' 'TCP')
    policyManaged = [bool]$policyManaged
}} | ConvertTo-Json -Compress
""".strip()


def configure_public_firewall_rules(
    executable: Path,
    *,
    command_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> int:
    executable = executable.resolve()
    if not executable.is_file():
        return FIREWALL_EXIT_INVALID_TARGET
    netsh = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "netsh.exe"
    common = dict(
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
        shell=False,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    for name in (UDP_RULE_NAME, TCP_RULE_NAME):
        try:
            command_runner(
                [str(netsh), "advfirewall", "firewall", "delete", "rule", f"name={name}"],
                **common,
            )
        except (OSError, subprocess.SubprocessError):
            pass
    for name, protocol in ((UDP_RULE_NAME, "UDP"), (TCP_RULE_NAME, "TCP")):
        command = [
            str(netsh),
            "advfirewall",
            "firewall",
            "add",
            "rule",
            f"name={name}",
            "dir=in",
            "action=allow",
            f"protocol={protocol}",
            f"localport={LAN_PORT}",
            f"program={executable}",
            "profile=private,public",
            "enable=yes",
        ]
        try:
            completed = command_runner(command, **common)
        except (OSError, subprocess.SubprocessError):
            return FIREWALL_EXIT_FAILED
        if completed.returncode != 0:
            return (
                FIREWALL_EXIT_POLICY_BLOCKED
                if completed.returncode == 5
                else FIREWALL_EXIT_FAILED
            )
    return 0


def run_elevated_firewall_helper(executable: Path) -> FirewallRepairResult:
    if sys.platform != "win32" or not executable.is_file():
        return FirewallRepairResult(False, "无法定位已安装的 PetNest.exe。")
    try:
        exit_code = _shell_execute_and_wait(executable, FIREWALL_HELPER_ARGUMENT)
    except OSError as error:
        if getattr(error, "winerror", None) == 1223:
            return FirewallRepairResult(False, "已取消管理员授权，可稍后重试。", cancelled=True)
        return FirewallRepairResult(False, "无法启动管理员授权。")
    if exit_code != 0:
        if exit_code == FIREWALL_EXIT_POLICY_BLOCKED:
            return FirewallRepairResult(
                False,
                "此设备由组织策略管理，请联系管理员放行 PetNest UDP/TCP 18487。",
            )
        return FirewallRepairResult(False, "防火墙规则配置失败，可稍后重试。")
    return FirewallRepairResult(True, "防火墙规则已更新，正在重新检查。")


def _shell_execute_and_wait(executable: Path, arguments: str) -> int:
    import ctypes
    from ctypes import wintypes

    class SHELLEXECUTEINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("fMask", wintypes.ULONG),
            ("hwnd", wintypes.HWND),
            ("lpVerb", wintypes.LPCWSTR),
            ("lpFile", wintypes.LPCWSTR),
            ("lpParameters", wintypes.LPCWSTR),
            ("lpDirectory", wintypes.LPCWSTR),
            ("nShow", ctypes.c_int),
            ("hInstApp", wintypes.HINSTANCE),
            ("lpIDList", wintypes.LPVOID),
            ("lpClass", wintypes.LPCWSTR),
            ("hkeyClass", wintypes.HKEY),
            ("dwHotKey", wintypes.DWORD),
            ("hIconOrMonitor", wintypes.HANDLE),
            ("hProcess", wintypes.HANDLE),
        ]

    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    info = SHELLEXECUTEINFO()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = 0x00000040  # SEE_MASK_NOCLOSEPROCESS
    info.lpVerb = "runas"
    info.lpFile = str(executable)
    info.lpParameters = arguments
    info.lpDirectory = str(executable.parent)
    info.nShow = 0
    if not shell32.ShellExecuteExW(ctypes.byref(info)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        kernel32.WaitForSingleObject(info.hProcess, 0xFFFFFFFF)
        exit_code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(exit_code)):
            raise ctypes.WinError(ctypes.get_last_error())
        return int(exit_code.value)
    finally:
        kernel32.CloseHandle(info.hProcess)
