"""Network-interface selection for LAN broadcast discovery."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from ipaddress import IPv4Address, ip_address

from PySide6.QtNetwork import QAbstractSocket, QNetworkInterface


@dataclass(frozen=True, slots=True)
class InterfaceIPv4:
    """One IPv4 address entry reported by a network interface."""

    name: str
    is_up: bool
    is_running: bool
    is_loopback: bool
    address: str
    broadcast: str | None


def eligible_broadcast_addresses(entries: Iterable[InterfaceIPv4]) -> tuple[str, ...]:
    """Return stable, unique broadcast destinations for usable IPv4 interfaces."""
    broadcasts: set[IPv4Address] = set()
    for entry in entries:
        if not entry.is_up or not entry.is_running or entry.is_loopback or not entry.broadcast:
            continue
        try:
            address = ip_address(entry.address)
            broadcast = ip_address(entry.broadcast)
        except ValueError:
            continue
        if not isinstance(address, IPv4Address) or not isinstance(broadcast, IPv4Address):
            continue
        if address.is_unspecified or address.is_loopback or address.is_link_local:
            continue
        broadcasts.add(broadcast)
    return tuple(str(address) for address in sorted(broadcasts))


def qt_interface_ipv4() -> tuple[InterfaceIPv4, ...]:
    """Read IPv4 address entries from Qt without leaking Qt types into services."""
    entries: list[InterfaceIPv4] = []
    for interface in QNetworkInterface.allInterfaces():
        flags = interface.flags()
        for address_entry in interface.addressEntries():
            address = address_entry.ip()
            if address.protocol() != QAbstractSocket.NetworkLayerProtocol.IPv4Protocol:
                continue
            broadcast = address_entry.broadcast()
            entries.append(
                InterfaceIPv4(
                    name=interface.humanReadableName(),
                    is_up=bool(flags & QNetworkInterface.InterfaceFlag.IsUp),
                    is_running=bool(flags & QNetworkInterface.InterfaceFlag.IsRunning),
                    is_loopback=bool(flags & QNetworkInterface.InterfaceFlag.IsLoopBack),
                    address=address.toString(),
                    broadcast=broadcast.toString() if not broadcast.isNull() else None,
                )
            )
    return tuple(entries)
