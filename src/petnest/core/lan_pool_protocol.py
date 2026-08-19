"""Strict wire protocol for distributed LAN alert-pool roster synchronization."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import re
from typing import Any

from petnest.models.lan_pool import PoolMemberRecord


POOL_ID = "petnest_lan_alert_pool_v1"
POOL_PROTOCOL_VERSION = 1
MAX_POOL_RECORDS = 256
MAX_POOL_UDP_BYTES = 8 * 1024
MAX_POOL_FRAME_BYTES = 256 * 1024


class LanPoolProtocolError(ValueError):
    pass


def _identity(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")
    value = value.strip()
    if not value or len(value) > 64 or any(char in value for char in "\\/\r\n\x00"):
        raise ValueError(f"{label} is invalid")
    return value


@dataclass(frozen=True, slots=True)
class PoolHeartbeat:
    pool_id: str
    sender_device_id: str
    sender_record: PoolMemberRecord
    roster_digest: str
    record_count: int

    def __post_init__(self) -> None:
        if self.pool_id != POOL_ID:
            raise ValueError("pool_id is invalid")
        sender = _identity(self.sender_device_id, "sender_device_id")
        if not isinstance(self.sender_record, PoolMemberRecord) or self.sender_record.device_id != sender:
            raise ValueError("sender_record must belong to sender")
        if not isinstance(self.roster_digest, str) or re.fullmatch(r"[0-9a-f]{64}", self.roster_digest) is None:
            raise ValueError("roster_digest is invalid")
        if (
            isinstance(self.record_count, bool)
            or not isinstance(self.record_count, int)
            or not 0 <= self.record_count <= MAX_POOL_RECORDS
        ):
            raise ValueError("record_count must be from 0 to 256")
        object.__setattr__(self, "sender_device_id", sender)


@dataclass(frozen=True, slots=True)
class PoolSummary:
    sender_device_id: str
    revisions: tuple[tuple[str, int], ...]

    def __post_init__(self) -> None:
        sender = _identity(self.sender_device_id, "sender_device_id")
        revisions = tuple(self.revisions)
        if len(revisions) > MAX_POOL_RECORDS:
            raise ValueError("summary cannot contain more than 256 records")
        normalized: list[tuple[str, int]] = []
        seen: set[str] = set()
        for item in revisions:
            if not isinstance(item, (tuple, list)) or len(item) != 2:
                raise ValueError("revision entries must contain device_id and revision")
            device_id = _identity(item[0], "device_id")
            revision = item[1]
            if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
                raise ValueError("revision must be a positive integer")
            if device_id in seen:
                raise ValueError("duplicate device_id in summary")
            seen.add(device_id)
            normalized.append((device_id, revision))
        object.__setattr__(self, "sender_device_id", sender)
        object.__setattr__(self, "revisions", tuple(sorted(normalized)))


@dataclass(frozen=True, slots=True)
class PoolRecords:
    sender_device_id: str
    records: tuple[PoolMemberRecord, ...]

    def __post_init__(self) -> None:
        sender = _identity(self.sender_device_id, "sender_device_id")
        records = tuple(self.records)
        if len(records) > MAX_POOL_RECORDS:
            raise ValueError("records cannot contain more than 256 records")
        if any(not isinstance(record, PoolMemberRecord) for record in records):
            raise ValueError("records must contain PoolMemberRecord values")
        ids = [record.device_id for record in records]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate device_id in records")
        object.__setattr__(self, "sender_device_id", sender)
        object.__setattr__(self, "records", tuple(sorted(records, key=lambda item: item.device_id)))


class LanPoolPacketCodec:
    @classmethod
    def encode_heartbeat(cls, heartbeat: PoolHeartbeat) -> bytes:
        if not isinstance(heartbeat, PoolHeartbeat):
            raise TypeError("heartbeat must be PoolHeartbeat")
        packet = {
            "version": POOL_PROTOCOL_VERSION,
            "kind": "pool_heartbeat",
            "pool_id": heartbeat.pool_id,
            "sender_device_id": heartbeat.sender_device_id,
            "sender_record": _record_to_dict(heartbeat.sender_record),
            "roster_digest": heartbeat.roster_digest,
            "record_count": heartbeat.record_count,
        }
        payload = _encode_json(packet)
        if len(payload) > MAX_POOL_UDP_BYTES:
            raise LanPoolProtocolError("heartbeat exceeds UDP size limit")
        return payload

    @classmethod
    def decode_heartbeat(cls, payload: bytes) -> PoolHeartbeat:
        raw = _decode_json(payload, maximum=MAX_POOL_UDP_BYTES)
        expected = {
            "version", "kind", "pool_id", "sender_device_id", "sender_record",
            "roster_digest", "record_count",
        }
        _require_fields(raw, expected)
        if raw["version"] != POOL_PROTOCOL_VERSION or raw["kind"] != "pool_heartbeat":
            raise LanPoolProtocolError("heartbeat version or kind is invalid")
        try:
            return PoolHeartbeat(
                raw["pool_id"],
                raw["sender_device_id"],
                _record_from_dict(raw["sender_record"]),
                raw["roster_digest"],
                raw["record_count"],
            )
        except (TypeError, ValueError) as error:
            raise LanPoolProtocolError(str(error)) from error

    @classmethod
    def encode_summary(cls, summary: PoolSummary) -> bytes:
        if not isinstance(summary, PoolSummary):
            raise TypeError("summary must be PoolSummary")
        return _encode_frame({
            "version": POOL_PROTOCOL_VERSION,
            "kind": "pool_summary",
            "pool_id": POOL_ID,
            "sender_device_id": summary.sender_device_id,
            "revisions": [[device_id, revision] for device_id, revision in summary.revisions],
        })

    @classmethod
    def encode_records(cls, records: PoolRecords) -> bytes:
        if not isinstance(records, PoolRecords):
            raise TypeError("records must be PoolRecords")
        return _encode_frame({
            "version": POOL_PROTOCOL_VERSION,
            "kind": "pool_records",
            "pool_id": POOL_ID,
            "sender_device_id": records.sender_device_id,
            "records": [_record_to_dict(record) for record in records.records],
        })

    @classmethod
    def decode_frame(cls, frame: bytes) -> PoolSummary | PoolRecords:
        if not isinstance(frame, (bytes, bytearray)) or len(frame) < 4:
            raise LanPoolProtocolError("frame length is invalid")
        size = int.from_bytes(frame[:4], "big")
        if size <= 0 or size > MAX_POOL_FRAME_BYTES or len(frame) - 4 != size:
            raise LanPoolProtocolError("frame length is invalid")
        raw = _decode_json(bytes(frame[4:]), maximum=MAX_POOL_FRAME_BYTES)
        if raw.get("version") != POOL_PROTOCOL_VERSION or raw.get("pool_id") != POOL_ID:
            raise LanPoolProtocolError("pool frame version or pool_id is invalid")
        kind = raw.get("kind")
        try:
            if kind == "pool_summary":
                _require_fields(raw, {"version", "kind", "pool_id", "sender_device_id", "revisions"})
                if not isinstance(raw["revisions"], list):
                    raise ValueError("revisions must be a list")
                return PoolSummary(raw["sender_device_id"], tuple(tuple(item) for item in raw["revisions"]))
            if kind == "pool_records":
                _require_fields(raw, {"version", "kind", "pool_id", "sender_device_id", "records"})
                if not isinstance(raw["records"], list):
                    raise ValueError("records must be a list")
                return PoolRecords(
                    raw["sender_device_id"],
                    tuple(_record_from_dict(item) for item in raw["records"]),
                )
        except (TypeError, ValueError) as error:
            raise LanPoolProtocolError(str(error)) from error
        raise LanPoolProtocolError("pool frame kind is invalid")


def _record_to_dict(record: PoolMemberRecord) -> dict[str, Any]:
    raw = asdict(record)
    raw["state"] = record.state.value
    return raw


def _record_from_dict(raw: object) -> PoolMemberRecord:
    required = {"device_id", "display_name", "state", "revision", "ip_address", "port", "protocol_version"}
    if not isinstance(raw, dict) or set(raw) != required:
        raise ValueError("member record fields are invalid")
    return PoolMemberRecord(**raw)


def _encode_json(raw: dict[str, Any]) -> bytes:
    try:
        return json.dumps(raw, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise LanPoolProtocolError("JSON encoding failed") from error


def _encode_frame(raw: dict[str, Any]) -> bytes:
    payload = _encode_json(raw)
    if not payload or len(payload) > MAX_POOL_FRAME_BYTES:
        raise LanPoolProtocolError("pool frame exceeds size limit")
    return len(payload).to_bytes(4, "big") + payload


def _decode_json(payload: bytes, *, maximum: int) -> dict[str, Any]:
    if not isinstance(payload, (bytes, bytearray)) or not payload or len(payload) > maximum:
        raise LanPoolProtocolError("payload size is invalid")
    try:
        raw = json.loads(bytes(payload).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise LanPoolProtocolError("JSON payload is invalid") from error
    if not isinstance(raw, dict):
        raise LanPoolProtocolError("JSON root must be an object")
    return raw


def _require_fields(raw: dict[str, Any], expected: set[str]) -> None:
    if set(raw) != expected:
        raise LanPoolProtocolError("message fields are invalid")
