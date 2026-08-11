"""局域网互动协议的安全边界测试。"""

from __future__ import annotations

import json

import pytest

from petnest.core.lan_interaction import LanPacketCodec, LanProtocolError
from petnest.models.lan_interaction import InteractionDraft, InteractionKind


def test_hello_packet_contains_identity_but_no_resource_path() -> None:
    packet = LanPacketCodec.hello(
        device_id="local-1",
        display_name="小平安",
        pet_name="平安",
        port=18487,
    )

    assert packet == {
        "version": 1,
        "kind": "hello",
        "device_id": "local-1",
        "display_name": "小平安",
        "pet_name": "平安",
        "port": 18487,
        "capabilities": ["greeting", "heart", "text", "effect"],
    }
    assert "path" not in packet


def test_interaction_packet_round_trips_as_one_validated_message() -> None:
    draft = InteractionDraft.text_message("peer-1", "你好呀")
    encoded = LanPacketCodec.encode(LanPacketCodec.interaction(draft, "local-1", "小平安"))

    received = LanPacketCodec.decode_interaction(encoded, local_device_id="peer-1")

    assert (received.sender_device_id, received.sender_name, received.draft) == ("local-1", "小平安", draft)


def test_protocol_rejects_unknown_types_oversized_text_and_wrong_target() -> None:
    with pytest.raises(LanProtocolError, match="类型"):
        LanPacketCodec.decode_interaction(json.dumps({"version": 1, "kind": "unknown"}).encode(), local_device_id="me")

    with pytest.raises(LanProtocolError, match="文字不能超过"):
        raw = LanPacketCodec.interaction(InteractionDraft.text_message("me", "ok"), "peer", "邻居")
        raw["text"] = "x" * 121
        LanPacketCodec.decode_interaction(LanPacketCodec.encode(raw), local_device_id="me")

    with pytest.raises(LanProtocolError, match="目标设备"):
        raw = LanPacketCodec.interaction(InteractionDraft.quick("other", InteractionKind.HEART), "peer", "邻居")
        LanPacketCodec.decode_interaction(LanPacketCodec.encode(raw), local_device_id="me")


def test_protocol_rejects_malformed_json_and_path_like_effect_id() -> None:
    with pytest.raises(LanProtocolError, match="JSON"):
        LanPacketCodec.decode_interaction(b"not-json", local_device_id="me")

    with pytest.raises(ValueError, match="动效编号"):
        InteractionDraft.effect("me", "C:\\secret")
