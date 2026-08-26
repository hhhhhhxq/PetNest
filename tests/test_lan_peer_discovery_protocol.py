from __future__ import annotations

import json

import pytest

from petnest.core.lan_peer_discovery_protocol import (
    PeerDirectory,
    PeerDirectoryCodec,
    PeerDirectoryProtocolError,
    PeerEndpointRecord,
)


def endpoint(device_id: str, ip_address: str, age_seconds: int = 0) -> PeerEndpointRecord:
    return PeerEndpointRecord(device_id, ip_address, 18487, age_seconds)


def test_directory_frame_round_trip_allows_four_endpoints_for_one_device() -> None:
    records = tuple(endpoint("multi", f"192.168.{index}.20", index) for index in range(4))
    directory = PeerDirectory("bridge", records)

    assert PeerDirectoryCodec.decode_frame(PeerDirectoryCodec.encode_frame(directory)) == directory


def test_directory_rejects_public_special_and_nonstandard_endpoints() -> None:
    for address in ("8.8.8.8", "127.0.0.1", "169.254.1.2", "224.0.0.1"):
        with pytest.raises(ValueError):
            endpoint("peer", address)
    with pytest.raises(ValueError):
        PeerEndpointRecord("peer", "192.168.1.20", 22, 0)


def test_directory_rejects_duplicate_endpoint_and_more_than_four_per_device() -> None:
    item = endpoint("peer", "192.168.1.20")
    with pytest.raises(ValueError, match="duplicate"):
        PeerDirectory("bridge", (item, item))
    with pytest.raises(ValueError, match="four"):
        PeerDirectory(
            "bridge",
            tuple(endpoint("peer", f"192.168.{index}.20") for index in range(5)),
        )


def test_directory_decoder_rejects_wrong_size_version_and_extra_fields() -> None:
    frame = PeerDirectoryCodec.encode_frame(
        PeerDirectory("bridge", (endpoint("peer", "10.0.0.8"),))
    )
    with pytest.raises(PeerDirectoryProtocolError):
        PeerDirectoryCodec.decode_frame(frame[:-1])
    with pytest.raises(PeerDirectoryProtocolError):
        PeerDirectoryCodec.decode_frame(b"\x00\x00\x00\x02{}")

    payload = json.loads(frame[4:].decode("utf-8"))
    payload["unexpected"] = True
    encoded = json.dumps(payload).encode("utf-8")
    with pytest.raises(PeerDirectoryProtocolError):
        PeerDirectoryCodec.decode_frame(len(encoded).to_bytes(4, "big") + encoded)


def test_directory_decoder_wraps_deep_json_recursion_as_protocol_error() -> None:
    payload = b"[" * 2_000 + b"0" + b"]" * 2_000

    with pytest.raises(PeerDirectoryProtocolError):
        PeerDirectoryCodec.decode_frame(len(payload).to_bytes(4, "big") + payload)


@pytest.mark.parametrize("version", [True, 1.0, 2])
def test_directory_decoder_requires_exact_integer_version(version: object) -> None:
    payload = {
        "version": version,
        "kind": "peer_directory",
        "sender_device_id": "bridge",
        "records": [],
    }
    encoded = json.dumps(payload).encode("utf-8")

    with pytest.raises(PeerDirectoryProtocolError):
        PeerDirectoryCodec.decode_frame(len(encoded).to_bytes(4, "big") + encoded)


def test_directory_rejects_invalid_age_record_count_and_record_fields() -> None:
    with pytest.raises(ValueError):
        endpoint("peer", "172.16.1.2", 25)
    with pytest.raises(ValueError):
        PeerDirectory(
            "bridge",
            tuple(endpoint(f"peer-{index}", f"10.0.0.{index + 1}") for index in range(65)),
        )

    payload = {
        "version": 1,
        "kind": "peer_directory",
        "sender_device_id": "bridge",
        "records": [
            {
                "device_id": "peer",
                "ip_address": "10.0.0.8",
                "port": 18487,
                "age_seconds": 0,
                "unexpected": True,
            }
        ],
    }
    encoded = json.dumps(payload).encode("utf-8")
    with pytest.raises(PeerDirectoryProtocolError):
        PeerDirectoryCodec.decode_frame(len(encoded).to_bytes(4, "big") + encoded)
