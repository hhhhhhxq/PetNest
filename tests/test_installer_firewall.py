"""安装器局域网防火墙规则的静态回归检查。"""

from __future__ import annotations

from pathlib import Path


INSTALLER = Path(__file__).parents[1] / "installer" / "PetNest.iss"


def test_installer_declares_scoped_lan_firewall_configuration() -> None:
    script = INSTALLER.read_text(encoding="utf-8")

    assert "PrivilegesRequired=admin" in script
    assert "FirewallPage" in script
    assert "GetFirewallProfiles" in script
    assert "localport=18487" in script
    assert "program=\"' +" in script
    assert "ExpandConstant('{app}\\PetNest.exe')" in script
    assert "Profiles := GetFirewallProfiles('');" in script
    assert "[UninstallRun]" in script
    assert "PetNest LAN UDP 18487" in script
    assert "RunOnceId: \"RemovePetNestLanFirewall\"" in script


def test_installer_warns_when_firewall_rule_cannot_be_created() -> None:
    script = INSTALLER.read_text(encoding="utf-8")

    assert "ConfigureFirewallRule" in script
    assert "防火墙规则创建失败" in script
