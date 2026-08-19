"""Strict codec tests for distributed alert-pool synchronization."""

from __future__ import annotations

import json

import pytest

from petnest.core.lan_pool_protocol import (
    MAX_POOL_RECORDS,
    POOL_ID,
    LanPoolPacketCodec,
    LanPoolProtocolError,
    PoolHeartbeat,
    PoolRecords,
    PoolSummary,
)
from petnest.models.lan_pool import PoolMemberRecord, PoolMemberState


def _record(device_id: str = "peer", revision: int = 3) -> PoolMemberRecord:
    return PoolMemberRecord(
        device_id,
        f"用户-{device_id}",
        PoolMemberState.JOINED,
        revision,
        "192.168.1.20",
        18487,
        1,
    )


def test_pool_protocol_round_trips_heartbeat_summary_and_records() -> None:
    record = _record()
    heartbeat = PoolHeartbeat(POOL_ID, "peer", record, "a" * 64, 2)
    summary = PoolSummary("peer", (("other", 2), ("peer", 3)))
    records = PoolRecords("peer", (record,))

    assert LanPoolPacketCodec.decode_heartbeat(
        LanPoolPacketCodec.encode_heartbeat(heartbeat)
    ) == heartbeat
    assert LanPoolPacketCodec.decode_frame(
        LanPoolPacketCodec.encode_summary(summary)
    ) == summary
    assert LanPoolPacketCodec.decode_frame(
        LanPoolPacketCodec.encode_records(records)
    ) == records


def test_summary_normalizes_revision_order_and_rejects_duplicate_ids() -> None:
    summary = PoolSummary("peer", (("z", 1), ("a", 4)))
    decoded = LanPoolPacketCodec.decode_frame(LanPoolPacketCodec.encode_summary(summary))
    assert decoded.revisions == (("a", 4), ("z", 1))

    with pytest.raises(ValueError, match="duplicate"):
        PoolSummary("peer", (("a", 1), ("a", 2)))


def test_protocol_rejects_more_than_256_records() -> None:
    revisions = tuple((f"peer-{index}", 1) for index in range(MAX_POOL_RECORDS + 1))
    records = tuple(_record(f"peer-{index}") for index in range(MAX_POOL_RECORDS + 1))

    with pytest.raises(ValueError, match="256"):
        PoolSummary("sender", revisions)
    with pytest.raises(ValueError, match="256"):
        PoolRecords("sender", records)


def test_heartbeat_rejects_wrong_pool_digest_count_and_sender() -> None:
    record = _record()
    with pytest.raises(ValueError, match="pool"):
        PoolHeartbeat("other", "peer", record, "a" * 64, 1)
    with pytest.raises(ValueError, match="digest"):
        PoolHeartbeat(POOL_ID, "peer", record, "bad", 1)
    with pytest.raises(ValueError, match="count"):
        PoolHeartbeat(POOL_ID, "peer", record, "a" * 64, 257)
    with pytest.raises(ValueError, match="sender"):
        PoolHeartbeat(POOL_ID, "other", record, "a" * 64, 1)


def test_codec_rejects_unknown_kind_malformed_json_and_length_mismatch() -> None:
    unknown = json.dumps({"version": 1, "kind": "unknown", "pool_id": POOL_ID}).encode("utf-8")
    unknown_frame = len(unknown).to_bytes(4, "big") + unknown

    with pytest.raises(LanPoolProtocolError, match="kind"):
        LanPoolPacketCodec.decode_frame(unknown_frame)
    with pytest.raises(LanPoolProtocolError, match="JSON"):
        LanPoolPacketCodec.decode_heartbeat(b"not-json")
    with pytest.raises(LanPoolProtocolError, match="length"):
        LanPoolPacketCodec.decode_frame((100).to_bytes(4, "big") + b"{}")


def test_records_decoder_rejects_duplicate_ids_and_extra_fields() -> None:
    record = _record()
    packet = json.loads(LanPoolPacketCodec.encode_records(PoolRecords("peer", (record,)))[4:])
    packet["records"].append(dict(packet["records"][0]))
    payload = json.dumps(packet).encode("utf-8")

    with pytest.raises(LanPoolProtocolError, match="duplicate"):
        LanPoolPacketCodec.decode_frame(len(payload).to_bytes(4, "big") + payload)

    packet["records"] = packet["records"][:1]
    packet["unexpected"] = True
    payload = json.dumps(packet).encode("utf-8")
    with pytest.raises(LanPoolProtocolError, match="fields"):
        LanPoolPacketCodec.decode_frame(len(payload).to_bytes(4, "big") + payload)
