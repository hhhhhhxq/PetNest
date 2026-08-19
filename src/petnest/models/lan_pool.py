"""Models for the ownerless distributed LAN alert pool."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from ipaddress import IPv4Address, ip_address


class PoolMemberState(StrEnum):
    JOINED = "joined"
    LEFT = "left"


@dataclass(frozen=True, slots=True)
class PoolMemberRecord:
    device_id: str
    display_name: str
    state: PoolMemberState
    revision: int
    ip_address: str
    port: int
    protocol_version: int = 1

    def __post_init__(self) -> None:
        if (
            not isinstance(self.device_id, str)
            or not self.device_id.strip()
            or len(self.device_id) > 64
            or any(char in self.device_id for char in "\\/\r\n\x00")
        ):
            raise ValueError("device_id must be a non-empty safe string of at most 64 characters")
        if (
            not isinstance(self.display_name, str)
            or not self.display_name.strip()
            or len(self.display_name) > 40
            or any(char in self.display_name for char in "\r\n\x00")
        ):
            raise ValueError("display_name must be a non-empty string of at most 40 characters")
        try:
            state = self.state if isinstance(self.state, PoolMemberState) else PoolMemberState(self.state)
        except (TypeError, ValueError) as error:
            raise ValueError("state must be joined or left") from error
        object.__setattr__(self, "state", state)
        if isinstance(self.revision, bool) or not isinstance(self.revision, int) or self.revision < 1:
            raise ValueError("revision must be a positive integer")
        if not isinstance(self.ip_address, str):
            raise ValueError("ip_address must be an IPv4 address")
        try:
            parsed = ip_address(self.ip_address)
        except ValueError as error:
            raise ValueError("ip_address must be an IPv4 address") from error
        if not isinstance(parsed, IPv4Address):
            raise ValueError("ip_address must be an IPv4 address")
        object.__setattr__(self, "ip_address", str(parsed))
        if isinstance(self.port, bool) or not isinstance(self.port, int) or not 1 <= self.port <= 65_535:
            raise ValueError("port must be an integer from 1 to 65535")
        if (
            isinstance(self.protocol_version, bool)
            or not isinstance(self.protocol_version, int)
            or self.protocol_version != 1
        ):
            raise ValueError("protocol_version must be 1")


@dataclass(frozen=True, slots=True)
class PoolMergeResult:
    changed_device_ids: tuple[str, ...] = ()
    local_newer_device_ids: tuple[str, ...] = ()
    conflicted_device_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PoolMemberView:
    device_id: str
    display_name: str
    joined: bool
    online: bool
    verified: bool
    reachable: bool
