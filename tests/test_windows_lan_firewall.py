from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

from petnest.core.windows_lan_firewall import (
    FIREWALL_EXIT_POLICY_BLOCKED,
    LanFirewallStatus,
    WindowsLanFirewallBackend,
    configure_public_firewall_rules,
)


def test_attention_requires_public_network_enabled_firewall_and_both_rules() -> None:
    base = dict(
        applicable=True,
        public_network_active=True,
        public_network_key="key",
        firewall_enabled=True,
        can_repair=True,
    )

    assert LanFirewallStatus(**base, udp_allowed=False, tcp_allowed=True).requires_attention
    assert LanFirewallStatus(**base, udp_allowed=True, tcp_allowed=False).requires_attention
    assert not LanFirewallStatus(**base, udp_allowed=True, tcp_allowed=True).requires_attention
    assert not LanFirewallStatus(**base, udp_allowed=False, tcp_allowed=False, error="failed").requires_attention
    assert not LanFirewallStatus(**{**base, "public_network_active": False}).requires_attention
    assert not LanFirewallStatus(**{**base, "firewall_enabled": False}).requires_attention
    assert not LanFirewallStatus().requires_attention


def test_inspect_parses_json_and_hashes_sorted_network_identities(tmp_path: Path) -> None:
    calls: list[tuple[list[str], dict[str, object]]] = []

    def runner(command: list[str], **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(
            command,
            0,
            json.dumps(
                {
                    "publicNetworks": ["NetworkProfile:7", "NetworkProfile:2"],
                    "firewallEnabled": True,
                    "udpAllowed": True,
                    "tcpAllowed": False,
                    "policyManaged": False,
                }
            ),
            "",
        )

    executable = tmp_path / "Pet Nest" / "PetNest.exe"
    status = WindowsLanFirewallBackend(
        executable=executable,
        platform="win32",
        frozen=True,
        command_runner=runner,
    ).inspect()

    expected_key = hashlib.sha256(
        "NetworkProfile:2\nNetworkProfile:7".encode("utf-8")
    ).hexdigest()
    assert status == LanFirewallStatus(
        applicable=True,
        public_network_active=True,
        public_network_key=expected_key,
        firewall_enabled=True,
        udp_allowed=True,
        tcp_allowed=False,
        can_repair=True,
    )
    command, kwargs = calls[0]
    assert command[0].lower().endswith("powershell.exe")
    assert str(executable.resolve()).casefold() in command[-1].casefold()
    assert kwargs["shell"] is False
    assert kwargs["timeout"] == 8
    assert "Get-NetRoute" in command[-1]
    assert "0.0.0.0/0" in command[-1]


def test_policy_managed_status_keeps_warning_but_disables_repair(tmp_path: Path) -> None:
    payload = {
        "publicNetworks": ["NetworkProfile:7"],
        "firewallEnabled": True,
        "udpAllowed": False,
        "tcpAllowed": False,
        "policyManaged": True,
    }
    backend = WindowsLanFirewallBackend(
        executable=tmp_path / "PetNest.exe",
        platform="win32",
        frozen=True,
        command_runner=lambda command, **_kwargs: subprocess.CompletedProcess(
            command, 0, json.dumps(payload), ""
        ),
    )

    status = backend.inspect()

    assert status.policy_managed is True
    assert status.requires_attention is True
    assert status.can_repair is False


def test_inspect_is_noop_off_windows() -> None:
    def runner(*_args, **_kwargs):
        raise AssertionError("must not run")

    status = WindowsLanFirewallBackend(platform="darwin", command_runner=runner).inspect()

    assert status == LanFirewallStatus()


def test_inspect_returns_error_for_bad_command_results() -> None:
    results = (
        subprocess.CompletedProcess(["powershell"], 1, "", "denied"),
        subprocess.CompletedProcess(["powershell"], 0, "", ""),
        subprocess.CompletedProcess(["powershell"], 0, "not-json", ""),
    )
    for result in results:
        backend = WindowsLanFirewallBackend(
            platform="win32",
            command_runner=lambda *_args, result=result, **_kwargs: result,
        )
        status = backend.inspect()
        assert status.applicable is True
        assert status.error
        assert status.requires_attention is False


def test_configure_public_firewall_rules_uses_fixed_argv_and_program_scope(tmp_path: Path) -> None:
    executable = tmp_path / "Pet Nest" / "PetNest.exe"
    executable.parent.mkdir()
    executable.write_bytes(b"exe")
    calls: list[tuple[list[str], dict[str, object]]] = []

    def runner(command: list[str], **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, "", "")

    assert configure_public_firewall_rules(executable, command_runner=runner) == 0
    assert len(calls) == 4
    assert calls[0][0][-1] == "name=PetNest LAN UDP 18487"
    assert calls[1][0][-1] == "name=PetNest LAN TCP 18487"
    for command, kwargs in calls[2:]:
        assert "profile=private,public" in command
        assert "localport=18487" in command
        assert f"program={executable.resolve()}" in command
        assert kwargs["shell"] is False


def test_configure_public_firewall_rules_stops_when_add_fails(tmp_path: Path) -> None:
    executable = tmp_path / "PetNest.exe"
    executable.write_bytes(b"exe")
    return_codes = iter((0, 0, 5))

    def runner(command: list[str], **_kwargs):
        return subprocess.CompletedProcess(command, next(return_codes), "", "failed")

    assert configure_public_firewall_rules(executable, command_runner=runner) == FIREWALL_EXIT_POLICY_BLOCKED


def test_configure_public_firewall_rules_rejects_missing_executable(tmp_path: Path) -> None:
    assert configure_public_firewall_rules(tmp_path / "missing.exe") == 2
