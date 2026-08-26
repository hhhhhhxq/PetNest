"""局域网互动协议的安全边界测试。"""

from __future__ import annotations

import json

import pytest

from petnest.core.lan_interaction import LanPacketCodec, LanProtocolError
from petnest.models.lan_interaction import (
    ChatScope,
    DangerAlert,
    DangerAlertAck,
    InteractionDraft,
    InteractionKind,
)


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
        "extensions": ["peer_directory_v1", "probe_token_v1"],
    }
    assert "path" not in packet


def test_hello_advertises_peer_discovery_without_changing_interaction_capabilities() -> None:
    packet = LanPacketCodec.hello(
        device_id="local-1",
        display_name="小平安",
        pet_name="平安",
        port=18487,
    )

    assert packet["capabilities"] == ["greeting", "heart", "text", "effect"]
    assert packet["extensions"] == ["peer_directory_v1", "probe_token_v1"]


def test_presence_round_trips_probe_token_and_accepts_legacy_without_extensions() -> None:
    token = "a" * 32
    packet = LanPacketCodec.hello(
        device_id="peer-1",
        display_name="小林",
        pet_name="橘猫",
        port=18487,
        probe_token=token,
    )

    decoded = LanPacketCodec.decode_presence(LanPacketCodec.encode(packet))
    assert decoded["extensions"] == ("peer_directory_v1", "probe_token_v1")
    assert decoded["probe_token"] == token

    packet.pop("extensions")
    packet.pop("probe_token")
    legacy = LanPacketCodec.decode_presence(LanPacketCodec.encode(packet))
    assert legacy["extensions"] == ()
    assert legacy["probe_token"] is None


@pytest.mark.parametrize("token", ["short", "A" * 32, "g" * 32, 123])
def test_presence_rejects_invalid_probe_token(token: object) -> None:
    packet = LanPacketCodec.hello(
        device_id="peer-1", display_name="小林", pet_name="橘猫", port=18487
    )
    packet["probe_token"] = token

    with pytest.raises(LanProtocolError, match="挑战"):
        LanPacketCodec.decode_presence(LanPacketCodec.encode(packet))


def test_presence_ignores_unknown_bounded_top_level_field() -> None:
    packet = LanPacketCodec.hello(
        device_id="peer-1", display_name="小林", pet_name="橘猫", port=18487
    )
    packet["future_field"] = {"value": 1}

    decoded = LanPacketCodec.decode_presence(LanPacketCodec.encode(packet))
    assert decoded["device_id"] == "peer-1"


def test_presence_round_trips_optional_alert_group_membership_and_accepts_legacy() -> None:
    packet = LanPacketCodec.hello(
        device_id="peer-1",
        display_name="小林",
        pet_name="平安",
        port=18487,
        alert_group_joined=True,
    )

    decoded = LanPacketCodec.decode_presence(LanPacketCodec.encode(packet))

    assert packet["capabilities"] == ["greeting", "heart", "text", "effect"]
    assert decoded["alert_group_supported"] is True
    assert decoded["alert_group_joined"] is True

    packet.pop("alert_group_joined")
    legacy = LanPacketCodec.decode_presence(LanPacketCodec.encode(packet))

    assert legacy["alert_group_supported"] is False
    assert legacy["alert_group_joined"] is False


def test_presence_rejects_non_boolean_alert_group_membership() -> None:
    packet = LanPacketCodec.hello(
        device_id="peer-1",
        display_name="小林",
        pet_name="平安",
        port=18487,
    )
    packet["alert_group_joined"] = "yes"

    with pytest.raises(LanProtocolError, match="预警组"):
        LanPacketCodec.decode_presence(LanPacketCodec.encode(packet))


def test_chat_scope_enum_uses_stable_wire_values() -> None:
    assert ChatScope.DIRECT.value == "direct"
    assert ChatScope.LAN_ROOM.value == "lan_room"
    assert ChatScope.ALERT_GROUP.value == "alert_group"


def test_danger_alert_and_ack_round_trip() -> None:
    alert = DangerAlert("alert-1", "sender", "小林", "receiver", 1_800_000_000, "请立即撤离")
    encoded = LanPacketCodec.encode(LanPacketCodec.danger_alert(alert))

    assert LanPacketCodec.decode_danger_alert(
        encoded,
        local_device_id="receiver",
        now=1_800_000_001,
    ) == alert

    ack = DangerAlertAck("alert-1", "receiver", "sender")
    encoded_ack = LanPacketCodec.encode(LanPacketCodec.danger_alert_ack(ack))
    assert LanPacketCodec.decode_danger_alert_ack(
        encoded_ack,
        local_device_id="sender",
    ) == ack


def test_danger_alert_rejects_message_longer_than_thirty_characters() -> None:
    alert = DangerAlert(
        "alert-1",
        "sender",
        "小林",
        "receiver",
        1_800_000_000,
        "过" * 31,
    )

    with pytest.raises(LanProtocolError, match="预警文案"):
        LanPacketCodec.danger_alert(alert)


def test_danger_alert_rejects_expired_and_wrong_target_messages() -> None:
    alert = DangerAlert("alert-1", "sender", "小林", "receiver", 1_800_000_000)
    encoded = LanPacketCodec.encode(LanPacketCodec.danger_alert(alert))

    with pytest.raises(LanProtocolError, match="过期"):
        LanPacketCodec.decode_danger_alert(
            encoded,
            local_device_id="receiver",
            now=1_800_000_020,
        )
    with pytest.raises(LanProtocolError, match="目标设备"):
        LanPacketCodec.decode_danger_alert(
            encoded,
            local_device_id="someone-else",
            now=1_800_000_001,
        )


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
