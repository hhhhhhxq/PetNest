"""IPv4 broadcast address selection for LAN discovery."""

from petnest.core.lan_discovery import InterfaceIPv4, eligible_broadcast_addresses


def test_eligible_broadcast_addresses_returns_each_active_lan_once_in_ip_order() -> None:
    entries = (
        InterfaceIPv4("Ethernet", True, True, False, "192.168.101.42", "192.168.101.255"),
        InterfaceIPv4("Wi-Fi", True, True, False, "192.168.20.10", "192.168.20.255"),
        InterfaceIPv4("VPN alias", True, True, False, "10.0.0.8", "192.168.20.255"),
    )

    assert eligible_broadcast_addresses(entries) == ("192.168.20.255", "192.168.101.255")


def test_eligible_broadcast_addresses_excludes_unusable_interface_addresses() -> None:
    entries = (
        InterfaceIPv4("Tailscale", True, True, False, "169.254.2.1", "169.254.255.255"),
        InterfaceIPv4("Loopback", True, True, True, "127.0.0.1", "127.255.255.255"),
        InterfaceIPv4("Disconnected", False, False, False, "192.168.1.8", "192.168.1.255"),
        InterfaceIPv4("No broadcast", True, True, False, "192.168.2.8", None),
        InterfaceIPv4("Invalid broadcast", True, True, False, "192.168.3.8", "not-an-ip"),
        InterfaceIPv4("Unspecified", True, True, False, "0.0.0.0", "255.255.255.255"),
    )

    assert eligible_broadcast_addresses(entries) == ()
