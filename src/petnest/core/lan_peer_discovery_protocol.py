"""Strict wire protocol for sharing recently verified LAN peer endpoints."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from ipaddress import IPv4Address, IPv4Network, ip_address
import json
from typing import Any

from petnest.core.lan_interaction import LAN_INTERACTION_PORT

DIRECTORY_PROTOCOL_VERSION = 1
MAX_DIRECTORY_RECORDS = 64
MAX_ENDPOINTS_PER_DEVICE = 4
MAX_DIRECTORY_FRAME_BYTES = 32 * 1024

_PRIVATE_NETWORKS = (
    IPv4Network("10.0.0.0/8"),
    IPv4Network("172.16.0.0/12"),
    IPv4Network("192.168.0.0/16"),
)
_TOP_LEVEL_FIELDS = {"version", "kind", "sender_device_id", "records"}
_RECORD_FIELDS = {"device_id", "ip_address", "port", "age_seconds"}


class PeerDirectoryProtocolError(ValueError):
    """Raised when a directory frame cannot be trusted or decoded."""


def _identity(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("device identity must be a string")
    normalized = value.strip()
    if (
        not normalized
        or len(normalized) > 64
        or any(character in normalized for character in "\\/\r\n\x00")
    ):
        raise ValueError("device identity is invalid")
    return normalized


def _private_ipv4(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("endpoint must be an RFC 1918 IPv4 address")
    try:
        parsed = ip_address(value)
    except ValueError as error:
        raise ValueError("endpoint must be an RFC 1918 IPv4 address") from error
    if not isinstance(parsed, IPv4Address) or not any(parsed in network for network in _PRIVATE_NETWORKS):
        raise ValueError("endpoint must be an RFC 1918 IPv4 address")
    return str(parsed)


@dataclass(frozen=True, slots=True)
class PeerEndpointRecord:
    device_id: str
    ip_address: str
    port: int
    age_seconds: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "device_id", _identity(self.device_id))
        object.__setattr__(self, "ip_address", _private_ipv4(self.ip_address))
        if isinstance(self.port, bool) or self.port != LAN_INTERACTION_PORT:
            raise ValueError("automatic discovery port must be 18487")
        if isinstance(self.age_seconds, bool) or not isinstance(self.age_seconds, int):
            raise ValueError("age_seconds must be an integer")
        if not 0 <= self.age_seconds <= 24:
            raise ValueError("age_seconds must be from 0 to 24")


@dataclass(frozen=True, slots=True)
class PeerDirectory:
    sender_device_id: str
    records: tuple[PeerEndpointRecord, ...]

    def __post_init__(self) -> None:
        sender = _identity(self.sender_device_id)
        try:
            records = tuple(self.records)
        except TypeError as error:
            raise ValueError("directory records must be iterable") from error
        if len(records) > MAX_DIRECTORY_RECORDS:
            raise ValueError("directory cannot contain more than 64 endpoints")
        if any(not isinstance(item, PeerEndpointRecord) for item in records):
            raise ValueError("directory contains an invalid endpoint")
        keys = [(item.device_id, item.ip_address, item.port) for item in records]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate endpoint")
        counts = Counter(item.device_id for item in records)
        if any(count > MAX_ENDPOINTS_PER_DEVICE for count in counts.values()):
            raise ValueError("one device cannot contain more than four endpoints")
        object.__setattr__(self, "sender_device_id", sender)
        object.__setattr__(
            self,
            "records",
            tuple(sorted(records, key=lambda item: (item.device_id, item.ip_address, item.port))),
        )


class PeerDirectoryCodec:
    """Encode and decode one length-prefixed peer directory frame."""

    @staticmethod
    def encode_frame(directory: PeerDirectory) -> bytes:
        if not isinstance(directory, PeerDirectory):
            raise PeerDirectoryProtocolError("directory object is invalid")
        document: dict[str, Any] = {
            "version": DIRECTORY_PROTOCOL_VERSION,
            "kind": "peer_directory",
            "sender_device_id": directory.sender_device_id,
            "records": [
                {
                    "device_id": item.device_id,
                    "ip_address": item.ip_address,
                    "port": item.port,
                    "age_seconds": item.age_seconds,
                }
                for item in directory.records
            ],
        }
        try:
            payload = json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        except (TypeError, ValueError) as error:
            raise PeerDirectoryProtocolError("directory cannot be encoded") from error
        if len(payload) > MAX_DIRECTORY_FRAME_BYTES:
            raise PeerDirectoryProtocolError("directory frame exceeds the size limit")
        return len(payload).to_bytes(4, "big") + payload

    @classmethod
    def decode_frame(cls, frame: bytes | bytearray) -> PeerDirectory:
        try:
            return cls._decode_frame(frame)
        except PeerDirectoryProtocolError:
            raise
        except (TypeError, ValueError, json.JSONDecodeError, UnicodeDecodeError) as error:
            raise PeerDirectoryProtocolError("directory frame is invalid") from error

    @staticmethod
    def _decode_frame(frame: bytes | bytearray) -> PeerDirectory:
        if not isinstance(frame, (bytes, bytearray)) or len(frame) < 4:
            raise PeerDirectoryProtocolError("directory frame is invalid")
        raw_frame = bytes(frame)
        declared_size = int.from_bytes(raw_frame[:4], "big")
        if declared_size > MAX_DIRECTORY_FRAME_BYTES or len(raw_frame) != declared_size + 4:
            raise PeerDirectoryProtocolError("directory frame length is invalid")
        document = json.loads(raw_frame[4:].decode("utf-8"))
        if not isinstance(document, dict) or set(document) != _TOP_LEVEL_FIELDS:
            raise PeerDirectoryProtocolError("directory fields are invalid")
        if (
            type(document["version"]) is not int
            or document["version"] != DIRECTORY_PROTOCOL_VERSION
        ):
            raise PeerDirectoryProtocolError("directory version is incompatible")
        if document["kind"] != "peer_directory":
            raise PeerDirectoryProtocolError("directory kind is invalid")
        raw_records = document["records"]
        if not isinstance(raw_records, list):
            raise PeerDirectoryProtocolError("directory records are invalid")
        records: list[PeerEndpointRecord] = []
        for raw_record in raw_records:
            if not isinstance(raw_record, dict) or set(raw_record) != _RECORD_FIELDS:
                raise PeerDirectoryProtocolError("directory record fields are invalid")
            records.append(
                PeerEndpointRecord(
                    device_id=raw_record["device_id"],
                    ip_address=raw_record["ip_address"],
                    port=raw_record["port"],
                    age_seconds=raw_record["age_seconds"],
                )
            )
        return PeerDirectory(document["sender_device_id"], tuple(records))
