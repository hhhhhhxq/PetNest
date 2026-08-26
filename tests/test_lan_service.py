"""UDP 服务生命周期和设备登记测试。"""

from __future__ import annotations

from dataclasses import replace
import os
from time import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication
from PySide6.QtNetwork import QHostAddress, QTcpServer
from PySide6.QtTest import QTest

import pytest

import petnest.core.lan_service as lan_service_module
from petnest.core.lan_discovery import InterfaceIPv4
from petnest.core.lan_interaction import LanPacketCodec
from petnest.core.lan_pool_protocol import (
    POOL_ID,
    LanPoolPacketCodec,
    PoolHeartbeat,
    PoolSummary,
)
from petnest.core.lan_peer_registry import KnownLanPeer, KnownLanPeerRegistry
from petnest.core.lan_peer_discovery_protocol import (
    PeerDirectory,
    PeerDirectoryCodec,
    PeerEndpointRecord,
)
from petnest.core.lan_service import LanInteractionService
from petnest.models.lan_interaction import ChatDraft, ChatScope, InteractionDraft, InteractionKind, LanPeer
from petnest.models.lan_interaction import DangerAlert, DangerAlertAck
from petnest.models.lan_pool import PoolMemberRecord, PoolMemberState


class FakeIncomingSocket:
    def __init__(self, frame: bytes, address: str) -> None:
        self.frame = frame
        self.address = QHostAddress(address)
        self.aborted = False

    def readAll(self) -> bytes:
        frame, self.frame = self.frame, b""
        return frame

    def peerAddress(self) -> QHostAddress:
        return self.address

    def abort(self) -> None:
        self.aborted = True


def _pool_record(device_id: str) -> PoolMemberRecord:
    return PoolMemberRecord(
        device_id,
        f"用户-{device_id}",
        PoolMemberState.JOINED,
        1,
        "192.168.1.20",
        18487,
        1,
    )


def test_candidate_ack_is_not_registered_until_token_identity_and_endpoint_match(qtbot) -> None:
    service = LanInteractionService(
        device_id="local", display_name="本机", pet_name="平安", port=18487
    )
    service._running = True
    service._send_packet = lambda *_args: True
    succeeded = []
    service.candidate_probe_succeeded.connect(succeeded.append)

    assert service.probe_candidate("peer", "192.168.20.85", token="a" * 32)
    wrong = LanPacketCodec.hello_ack(
        device_id="peer",
        display_name="同事",
        pet_name="猫",
        port=18487,
        probe_token="b" * 32,
    )
    service._handle_datagram(
        LanPacketCodec.encode(wrong), QHostAddress("192.168.20.85"), 18487
    )
    assert service.peers() == ()
    assert succeeded == []

    valid = LanPacketCodec.hello_ack(
        device_id="peer",
        display_name="同事",
        pet_name="猫",
        port=18487,
        probe_token="a" * 32,
    )
    service._handle_datagram(
        LanPacketCodec.encode(valid), QHostAddress("192.168.20.85"), 18487
    )
    assert [peer.device_id for peer in service.peers()] == ["peer"]
    assert succeeded[0].peer.device_id == "peer"
    assert succeeded[0].assisted is True
    assert succeeded[0].probe_token == "a" * 32


def test_candidate_ack_rejects_wrong_device_ip_source_port_and_advertised_port(qtbot) -> None:
    cases = (
        ("wrong", "192.168.20.85", 18487, 18487),
        ("expected", "192.168.20.86", 18487, 18487),
        ("expected", "192.168.20.85", 18488, 18487),
        ("expected", "192.168.20.85", 18487, 18488),
    )
    for device_id, host, source_port, advertised_port in cases:
        service = LanInteractionService(
            device_id="local", display_name="本机", pet_name="平安", port=18487
        )
        service._running = True
        service._send_packet = lambda *_args: True
        token = "c" * 32
        assert service.probe_candidate("expected", "192.168.20.85", token=token)
        packet = LanPacketCodec.hello_ack(
            device_id=device_id,
            display_name="设备",
            pet_name="猫",
            port=advertised_port,
            probe_token=token,
        )

        service._handle_datagram(
            LanPacketCodec.encode(packet), QHostAddress(host), source_port
        )

        assert service.peers() == ()
        assert token in service._candidate_probe_targets


def test_candidate_hello_echoes_token_and_emits_verified_presence(qtbot) -> None:
    service = LanInteractionService(
        device_id="local", display_name="本机", pet_name="平安", port=18487
    )
    service._running = True
    sent = []
    verified = []
    service._send_packet = (
        lambda packet, address, port: sent.append((packet, address.toString(), port)) or True
    )
    service.presence_verified.connect(verified.append)
    packet = LanPacketCodec.hello(
        device_id="candidate",
        display_name="候选设备",
        pet_name="猫",
        port=18487,
        probe_token="d" * 32,
    )

    service._handle_datagram(
        LanPacketCodec.encode(packet), QHostAddress("192.168.20.85"), 18487
    )

    assert sent[0][0]["kind"] == "hello_ack"
    assert sent[0][0]["probe_token"] == "d" * 32
    assert verified[0].peer.device_id == "candidate"
    assert verified[0].assisted is False


def test_tcp_directory_frame_requires_a_verified_sender_and_matching_source_ip(qtbot) -> None:
    service = LanInteractionService(
        device_id="local", display_name="本机", pet_name="平安", port=18487
    )
    service._peers["bridge"] = LanPeer(
        device_id="bridge",
        display_name="桥接设备",
        pet_name="猫",
        ip_address="192.168.101.65",
        port=18487,
        online=True,
    )
    received = []
    service.peer_directory_received.connect(received.append)
    directory = PeerDirectory(
        "bridge", (PeerEndpointRecord("peer", "192.168.20.85", 18487, 0),)
    )
    frame = PeerDirectoryCodec.encode_frame(directory)

    valid = FakeIncomingSocket(frame, "192.168.101.65")
    service._incoming_chat_buffers[valid] = bytearray()
    service._read_chat_stream(valid)
    assert received[0].message == directory
    assert received[0].address == "192.168.101.65"
    assert valid.aborted is False

    unknown_directory = PeerDirectory(
        "unknown", (PeerEndpointRecord("peer", "192.168.20.85", 18487, 0),)
    )
    unknown = FakeIncomingSocket(PeerDirectoryCodec.encode_frame(unknown_directory), "192.168.101.65")
    service._incoming_chat_buffers[unknown] = bytearray()
    service._read_chat_stream(unknown)
    assert unknown.aborted is True
    assert len(received) == 1

    wrong_ip = FakeIncomingSocket(frame, "192.168.101.66")
    service._incoming_chat_buffers[wrong_ip] = bytearray()
    service._read_chat_stream(wrong_ip)
    assert wrong_ip.aborted is True
    assert len(received) == 1


def test_service_dispatches_pool_heartbeat_without_treating_it_as_interaction(qtbot) -> None:
    service = LanInteractionService(device_id="local", display_name="本机", pet_name="平安", port=0)
    pool_messages = []
    interactions = []
    service.pool_heartbeat_received.connect(pool_messages.append)
    service.interaction_received.connect(interactions.append)
    heartbeat = PoolHeartbeat(POOL_ID, "peer", _pool_record("peer"), "a" * 64, 1)

    service._handle_datagram(
        LanPoolPacketCodec.encode_heartbeat(heartbeat),
        QHostAddress("192.168.1.20"),
        18487,
    )

    assert pool_messages[0].message == heartbeat
    assert pool_messages[0].address == "192.168.1.20"
    assert interactions == []


def test_tcp_stream_dispatches_pool_frame_and_keeps_chat_history_unchanged(qtbot) -> None:
    sender = LanInteractionService(
        device_id="sender", display_name="发送方", pet_name="平安", port=0,
        interface_provider=lambda: (),
    )
    receiver = LanInteractionService(
        device_id="receiver", display_name="接收方", pet_name="橘猫", port=0,
        interface_provider=lambda: (),
    )
    frames = []
    receiver.pool_frame_received.connect(frames.append)
    try:
        assert sender.start()
        assert receiver.start()
        assert sender.probe_peer("127.0.0.1", receiver.port)
        qtbot.waitUntil(
            lambda: any(peer.device_id == "receiver" for peer in sender.peers()),
            timeout=2_000,
        )
        frame = LanPoolPacketCodec.encode_summary(PoolSummary("sender", (("sender", 1),)))

        assert sender.send_pool_frame("receiver", frame)
        qtbot.waitUntil(lambda: len(frames) == 1, timeout=2_000)

        assert frames[0].message == PoolSummary("sender", (("sender", 1),))
        assert receiver.chat_messages() == ()
    finally:
        sender.stop()
        receiver.stop()


def test_discovery_and_manual_refresh_advertise_alert_group_membership(qtbot) -> None:
    service = LanInteractionService(
        device_id="local",
        display_name="本机",
        pet_name="平安",
        port=0,
        alert_group_joined=True,
        interface_provider=lambda: (),
    )
    packets: list[dict[str, object]] = []
    service._send_packet = lambda packet, _address, _port: packets.append(packet) or True
    try:
        assert service.start()
        assert packets
        assert all(packet.get("alert_group_joined") is True for packet in packets)

        packets.clear()
        service._manual_peer_targets["peer"] = ("192.168.20.12", 18487)
        service._refresh_manual_peers()

        assert len(packets) == 1
        assert packets[0]["alert_group_joined"] is True
    finally:
        service.stop()


def test_alert_group_chat_requires_both_local_and_sender_membership(qtbot) -> None:
    service = LanInteractionService(
        device_id="local",
        display_name="本机",
        pet_name="平安",
        port=0,
        alert_group_joined=False,
    )
    message = replace(
        ChatDraft.alert_group_text_message("注意安全").to_message(
            sender_device_id="sender",
            sender_name="发送方",
        ),
        target_device_id="local",
    )
    assert message.scope is ChatScope.ALERT_GROUP
    service._peers["sender"] = LanPeer(
        "sender",
        "发送方",
        alert_group_supported=True,
        alert_group_joined=True,
    )

    assert service._allow_chat(message) is False

    service.update_alert_group_membership(True)
    assert service._allow_chat(message) is True

    service._peers["sender"] = replace(service._peers["sender"], alert_group_joined=False)
    assert service._allow_chat(message) is False


def test_presence_updates_peer_alert_group_state(qtbot) -> None:
    service = LanInteractionService(device_id="local", display_name="本机", pet_name="平安", port=0)
    packet = LanPacketCodec.hello(
        device_id="peer",
        display_name="小林",
        pet_name="橘猫",
        port=19000,
        alert_group_joined=True,
    )

    service._handle_datagram(LanPacketCodec.encode(packet), QHostAddress("192.168.1.20"), 19000)

    peer = next(item for item in service.peers() if item.device_id == "peer")
    assert peer.alert_group_supported is True
    assert peer.alert_group_joined is True


def test_danger_alert_retries_unacknowledged_peer_and_reports_real_acks(qtbot) -> None:
    service = LanInteractionService(
        device_id="sender",
        display_name="发送方",
        pet_name="平安",
        port=0,
        alert_group_joined=True,
        interface_provider=lambda: (),
    )
    service._danger_retry_ms = 20
    service._danger_completion_ms = 60
    sent: list[tuple[dict[str, object], str, int]] = []
    completed = []
    service.danger_alert_delivery_completed.connect(completed.append)
    try:
        assert service.start()
        service._peers = {
            "acked": LanPeer(
                "acked", "甲", ip_address="127.0.0.1", port=19001,
                alert_group_supported=True, alert_group_joined=True,
            ),
            "silent": LanPeer(
                "silent", "乙", ip_address="127.0.0.1", port=19002,
                alert_group_supported=True, alert_group_joined=True,
            ),
            "left": LanPeer(
                "left", "丙", ip_address="127.0.0.1", port=19003,
                alert_group_supported=True, alert_group_joined=False,
            ),
        }
        service._send_packet = (
            lambda packet, address, port: sent.append((packet, address.toString(), port)) or True
        )

        assert service.send_danger_alert("请立即撤离")
        alert_id = str(sent[0][0]["alert_id"])
        ack = DangerAlertAck(alert_id, "acked", "sender")
        service._handle_datagram(
            LanPacketCodec.encode(LanPacketCodec.danger_alert_ack(ack)),
            QHostAddress("127.0.0.1"),
            19001,
        )
        qtbot.waitUntil(lambda: len(completed) == 1, timeout=500)

        assert set(completed[0].target_device_ids) == {"acked", "silent"}
        assert completed[0].acknowledged_device_ids == ("acked",)
        targets = [
            str(packet["target_device_id"])
            for packet, _host, _port in sent
            if packet.get("kind") == "danger_alert"
        ]
        assert targets.count("acked") == 1
        assert targets.count("silent") == 2
        assert "left" not in targets
        assert all(
            packet.get("message") == "请立即撤离"
            for packet, _host, _port in sent
            if packet.get("kind") == "danger_alert"
        )
    finally:
        service.stop()


def test_received_danger_alert_is_trusted_deduplicated_and_rate_limited(qtbot) -> None:
    service = LanInteractionService(
        device_id="receiver",
        display_name="接收方",
        pet_name="平安",
        alert_group_joined=True,
    )
    service._peers["sender"] = LanPeer(
        "sender", "小林", ip_address="192.168.1.20", port=19000,
        alert_group_supported=True, alert_group_joined=True,
    )
    received = []
    replies = []
    service.danger_alert_received.connect(received.append)
    service._send_packet = lambda packet, address, port: replies.append((packet, address.toString(), port)) or True
    created_at = int(time())

    first = DangerAlert("alert-1", "sender", "小林", "receiver", created_at)
    encoded = LanPacketCodec.encode(LanPacketCodec.danger_alert(first))
    service._handle_datagram(encoded, QHostAddress("192.168.1.20"), 19000)
    service._handle_datagram(encoded, QHostAddress("192.168.1.20"), 19000)
    for index in range(2, 5):
        alert = DangerAlert(f"alert-{index}", "sender", "小林", "receiver", created_at)
        service._handle_datagram(
            LanPacketCodec.encode(LanPacketCodec.danger_alert(alert)),
            QHostAddress("192.168.1.20"),
            19000,
        )

    assert [item.alert_id for item in received] == ["alert-1", "alert-2", "alert-3"]
    assert len(replies) == 4
    assert all(item[0]["kind"] == "danger_alert_ack" for item in replies)


def test_saved_peer_is_projected_as_offline_until_it_reconnects(tmp_path, qtbot) -> None:
    registry = KnownLanPeerRegistry(tmp_path / "known-lan-peers.json")
    registry.upsert(KnownLanPeer("saved", "已保存伙伴", "192.168.1.20", 19000))
    service = LanInteractionService(
        device_id="local",
        display_name="本机",
        pet_name="平安",
        peer_registry=registry,
    )

    assert service.peers() == (
        LanPeer(
            device_id="saved",
            display_name="已保存伙伴",
            ip_address="192.168.1.20",
            port=19000,
            online=False,
            saved=True,
            connection_state="offline",
        ),
    )
    assert service.unavailable_known_peers() == service.peers()


def test_start_probes_each_saved_peer_and_projects_it_as_connecting(tmp_path, qtbot) -> None:
    registry = KnownLanPeerRegistry(tmp_path / "known-lan-peers.json")
    registry.upsert(KnownLanPeer("one", "甲", "192.168.1.20", 19000))
    registry.upsert(KnownLanPeer("two", "乙", "192.168.1.21", 19001))
    service = LanInteractionService(
        device_id="local",
        display_name="本机",
        pet_name="平安",
        port=0,
        interface_provider=lambda: (),
        peer_registry=registry,
    )
    sent = []
    service._send_packet = lambda packet, address, port: sent.append((address.toString(), port)) or True

    assert service.start()

    assert {target for target in sent if target[0].startswith("192.168.1.")} == {
        ("192.168.1.20", 19000),
        ("192.168.1.21", 19001),
    }
    assert {peer.connection_state for peer in service.peers()} == {"connecting"}
    service.stop()
    assert service._saved_probe_targets == {}
    assert registry.load()


def test_failed_saved_probe_stays_offline_instead_of_connecting(tmp_path, qtbot) -> None:
    registry = KnownLanPeerRegistry(tmp_path / "known-lan-peers.json")
    registry.upsert(KnownLanPeer("saved", "已保存伙伴", "192.168.1.20", 19000))
    service = LanInteractionService(
        device_id="local",
        display_name="本机",
        pet_name="平安",
        port=0,
        interface_provider=lambda: (),
        peer_registry=registry,
    )
    service._send_packet = lambda *_args: False

    assert service.start()

    assert service.peers()[0].connection_state == "offline"
    assert service._saved_probe_targets == {}
    service.stop()


def test_saved_startup_probe_times_out_to_offline(tmp_path, qtbot, monkeypatch) -> None:
    monkeypatch.setattr(lan_service_module, "MANUAL_PROBE_TIMEOUT_MS", 10)
    registry = KnownLanPeerRegistry(tmp_path / "known-lan-peers.json")
    registry.upsert(KnownLanPeer("saved", "已保存伙伴", "192.168.1.20", 19000))
    service = LanInteractionService(
        device_id="local",
        display_name="本机",
        pet_name="平安",
        port=0,
        interface_provider=lambda: (),
        peer_registry=registry,
    )
    service._send_packet = lambda *_args: True

    assert service.start()
    assert service.peers()[0].connection_state == "connecting"

    QTest.qWait(30)

    assert service._saved_probe_targets == {}
    assert service.peers()[0].connection_state == "offline"
    service.stop()


def test_saved_startup_probe_keeps_refreshing_after_timeout(tmp_path, qtbot, monkeypatch) -> None:
    monkeypatch.setattr(lan_service_module, "MANUAL_PROBE_TIMEOUT_MS", 10)
    registry = KnownLanPeerRegistry(tmp_path / "known-lan-peers.json")
    registry.upsert(KnownLanPeer("saved", "已保存伙伴", "192.168.1.20", 19000))
    service = LanInteractionService(
        device_id="local",
        display_name="本机",
        pet_name="平安",
        port=0,
        interface_provider=lambda: (),
        peer_registry=registry,
    )
    sent = []
    service._send_packet = lambda packet, address, port: sent.append(
        (address.toString(), port)
    ) or True

    assert service.start()
    QTest.qWait(30)
    sent.clear()

    service._refresh_manual_peers()

    assert sent == [("192.168.1.20", 19000)]
    assert service.peers()[0].connection_state == "offline"
    service.stop()


def test_saved_probe_hello_restores_online_peer_and_updates_its_address(tmp_path, qtbot) -> None:
    registry = KnownLanPeerRegistry(tmp_path / "known-lan-peers.json")
    registry.upsert(KnownLanPeer("saved", "旧名字", "192.168.1.20", 19000))
    service = LanInteractionService(
        device_id="local", display_name="本机", pet_name="平安", peer_registry=registry
    )
    service._running = True
    service._saved_probe_targets[("192.168.1.20", 19000)] = "saved"
    packet = LanPacketCodec.hello_ack(
        device_id="saved", display_name="新名字", pet_name="橘猫", port=19001
    )

    service._handle_datagram(LanPacketCodec.encode(packet), QHostAddress("192.168.1.20"), 19000)

    assert registry.load() == (KnownLanPeer("saved", "新名字", "192.168.1.20", 19001),)
    assert service.peers()[0].saved
    assert service.peers()[0].connection_state == "online"
    assert service._saved_probe_targets == {}


def test_saved_reconnect_adds_target_for_periodic_refresh(tmp_path, qtbot) -> None:
    registry = KnownLanPeerRegistry(tmp_path / "known-lan-peers.json")
    registry.upsert(KnownLanPeer("saved", "已保存伙伴", "192.168.1.20", 19000))
    service = LanInteractionService(
        device_id="local", display_name="本机", pet_name="平安", peer_registry=registry
    )
    service._saved_probe_targets[("192.168.1.20", 19000)] = "saved"
    packet = LanPacketCodec.hello_ack(
        device_id="saved", display_name="已保存伙伴", pet_name="橘猫", port=19001
    )

    service._handle_datagram(LanPacketCodec.encode(packet), QHostAddress("192.168.1.20"), 19000)

    assert service._manual_peer_targets == {"saved": ("192.168.1.20", 19001)}


def test_saved_peer_hello_from_new_ip_updates_verified_endpoint(tmp_path, qtbot) -> None:
    registry = KnownLanPeerRegistry(tmp_path / "known-lan-peers.json")
    registry.upsert(KnownLanPeer("saved", "旧名字", "192.168.1.20", 19000))
    service = LanInteractionService(
        device_id="local", display_name="本机", pet_name="平安", peer_registry=registry
    )
    service._saved_probe_targets[("192.168.1.20", 19000)] = "saved"
    packet = LanPacketCodec.hello(
        device_id="saved", display_name="新名字", pet_name="橘猫", port=19001
    )

    service._handle_datagram(LanPacketCodec.encode(packet), QHostAddress("192.168.1.99"), 19001)

    assert registry.load() == (KnownLanPeer("saved", "新名字", "192.168.1.99", 19001),)
    assert service.peers()[0].connection_state == "online"
    assert service._saved_probe_targets == {}


def test_manual_probe_saves_verified_peer_to_registry(tmp_path, qtbot) -> None:
    registry = KnownLanPeerRegistry(tmp_path / "known-lan-peers.json")
    service = LanInteractionService(
        device_id="local", display_name="本机", pet_name="平安", peer_registry=registry
    )
    service._running = True
    service._send_packet = lambda *_args: True

    assert service.probe_peer("192.168.1.20", 19000)
    packet = LanPacketCodec.hello_ack(
        device_id="saved", display_name="已验证", pet_name="橘猫", port=19000
    )
    service._handle_datagram(LanPacketCodec.encode(packet), QHostAddress("192.168.1.20"), 19000)

    assert registry.load() == (KnownLanPeer("saved", "已验证", "192.168.1.20", 19000),)


def test_manual_probe_ignores_response_with_unexpected_advertised_port(tmp_path, qtbot) -> None:
    registry = KnownLanPeerRegistry(tmp_path / "known-lan-peers.json")
    service = LanInteractionService(
        device_id="local", display_name="本机", pet_name="平安", peer_registry=registry
    )
    completed = []
    service.manual_probe_succeeded.connect(completed.append)
    service._running = True
    service._send_packet = lambda *_args: True

    assert service.probe_peer("192.168.1.20", 19000)
    packet = LanPacketCodec.hello_ack(
        device_id="unexpected", display_name="错误端口", pet_name="橘猫", port=19001
    )

    service._handle_datagram(LanPacketCodec.encode(packet), QHostAddress("192.168.1.20"), 19000)

    assert registry.load() == ()
    assert completed == []
    assert service._manual_probe_target == ("192.168.1.20", 19000)
    assert service._manual_peer_targets == {}


def test_manual_probe_does_not_refresh_saved_peer_from_an_unexpected_port(tmp_path, qtbot) -> None:
    registry = KnownLanPeerRegistry(tmp_path / "known-lan-peers.json")
    saved_peer = KnownLanPeer("saved", "可信伙伴", "192.168.1.20", 19000)
    registry.upsert(saved_peer)
    service = LanInteractionService(
        device_id="local", display_name="本机", pet_name="平安", peer_registry=registry
    )
    completed = []
    service.manual_probe_succeeded.connect(completed.append)
    service._running = True
    service._send_packet = lambda *_args: True

    assert service.probe_peer(saved_peer.ip_address, saved_peer.port)
    packet = LanPacketCodec.hello_ack(
        device_id=saved_peer.device_id,
        display_name="错误端口响应",
        pet_name="橘猫",
        port=19001,
    )

    service._handle_datagram(
        LanPacketCodec.encode(packet), QHostAddress(saved_peer.ip_address), saved_peer.port
    )

    assert registry.load() == (saved_peer,)
    assert service._manual_peer_targets == {}
    assert service._manual_probe_target == (saved_peer.ip_address, saved_peer.port)
    assert completed == []


def test_manual_probe_rejects_an_unexpected_udp_source_port(tmp_path, qtbot) -> None:
    registry = KnownLanPeerRegistry(tmp_path / "known-lan-peers.json")
    service = LanInteractionService(
        device_id="local", display_name="本机", pet_name="平安", peer_registry=registry
    )
    completed = []
    service.manual_probe_succeeded.connect(completed.append)
    service._running = True
    service._send_packet = lambda *_args: True

    assert service.probe_peer("192.168.1.20", 19000)
    packet = LanPacketCodec.hello_ack(
        device_id="unexpected-source",
        display_name="错误来源端口",
        pet_name="橘猫",
        port=19000,
    )

    service._handle_datagram(LanPacketCodec.encode(packet), QHostAddress("192.168.1.20"), 19001)

    assert registry.load() == ()
    assert service.peers() == ()
    assert service._manual_peer_targets == {}
    assert service._manual_probe_target == ("192.168.1.20", 19000)
    assert completed == []


def test_manual_probe_rejects_a_different_device_claiming_a_saved_ip(tmp_path, qtbot) -> None:
    registry = KnownLanPeerRegistry(tmp_path / "known-lan-peers.json")
    trusted = KnownLanPeer("trusted", "可信伙伴", "192.168.1.20", 19000)
    registry.upsert(trusted)
    service = LanInteractionService(
        device_id="local", display_name="本机", pet_name="平安", peer_registry=registry
    )
    errors = []
    completed = []
    service.error.connect(errors.append)
    service.manual_probe_succeeded.connect(completed.append)
    service._running = True
    service._send_packet = lambda *_args: True

    assert service.probe_peer("192.168.1.20", 19000)
    packet = LanPacketCodec.hello_ack(
        device_id="attacker", display_name="冒名者", pet_name="猫", port=19000
    )
    service._handle_datagram(LanPacketCodec.encode(packet), QHostAddress("192.168.1.20"), 19000)

    assert registry.load() == (trusted,)
    assert not completed
    assert errors and "身份" in errors[-1]


def test_saved_ip_rejects_a_different_device_even_from_another_source_port(tmp_path, qtbot) -> None:
    registry = KnownLanPeerRegistry(tmp_path / "known-lan-peers.json")
    trusted = KnownLanPeer("trusted", "可信伙伴", "192.168.1.20", 19000)
    registry.upsert(trusted)
    service = LanInteractionService(
        device_id="local", display_name="本机", pet_name="平安", peer_registry=registry
    )
    errors = []
    service.error.connect(errors.append)
    service._saved_probe_targets[(trusted.ip_address, trusted.port)] = trusted.device_id
    packet = LanPacketCodec.hello_ack(
        device_id="attacker", display_name="冒名者", pet_name="猫", port=trusted.port
    )

    service._handle_datagram(
        LanPacketCodec.encode(packet), QHostAddress(trusted.ip_address), 19001
    )

    assert registry.load() == (trusted,)
    assert all(peer.device_id != "attacker" for peer in service.peers())
    assert errors and "身份" in errors[-1]


def test_saved_peer_allows_another_device_on_the_same_ip_with_a_different_port(
    tmp_path,
    qtbot,
) -> None:
    registry = KnownLanPeerRegistry(tmp_path / "known-lan-peers.json")
    trusted = KnownLanPeer("trusted", "可信伙伴", "192.168.1.20", 19000)
    registry.upsert(trusted)
    service = LanInteractionService(
        device_id="local",
        display_name="本机",
        pet_name="平安",
        peer_registry=registry,
    )
    packet = LanPacketCodec.hello(
        device_id="other-device",
        display_name="同机伙伴",
        pet_name="猫",
        port=19001,
    )

    service._handle_datagram(
        LanPacketCodec.encode(packet),
        QHostAddress(trusted.ip_address),
        19001,
    )

    assert {peer.device_id for peer in service.peers()} == {"trusted", "other-device"}


def test_forget_peer_removes_saved_projection_and_runtime_state(tmp_path, qtbot) -> None:
    registry = KnownLanPeerRegistry(tmp_path / "known-lan-peers.json")
    registry.upsert(KnownLanPeer("saved", "已保存", "192.168.1.20", 19000))
    service = LanInteractionService(
        device_id="local", display_name="本机", pet_name="平安", peer_registry=registry
    )
    service._saved_probe_targets[("192.168.1.20", 19000)] = "saved"
    packet = LanPacketCodec.hello_ack(
        device_id="saved", display_name="已保存", pet_name="猫", port=19000
    )
    service._handle_datagram(LanPacketCodec.encode(packet), QHostAddress("192.168.1.20"), 19000)

    service.forget_peer("saved")

    assert registry.load() == ()
    assert service.peers() == ()
    assert service.unavailable_known_peers() == ()
    assert "saved" not in service._peer_seen_at


def test_expiring_saved_peer_emits_offline_change_and_preserves_refresh_target(
    tmp_path, qtbot
) -> None:
    registry = KnownLanPeerRegistry(tmp_path / "known-lan-peers.json")
    saved_peer = KnownLanPeer("saved", "已保存伙伴", "192.168.1.20", 19000)
    registry.upsert(saved_peer)
    service = LanInteractionService(
        device_id="local", display_name="本机", pet_name="平安", peer_registry=registry
    )
    packet = LanPacketCodec.hello(
        device_id="saved", display_name="已保存伙伴", pet_name="橘猫", port=19000
    )
    service._handle_datagram(LanPacketCodec.encode(packet), QHostAddress("192.168.1.20"), 19000)
    ephemeral_packet = LanPacketCodec.hello(
        device_id="ephemeral", display_name="临时伙伴", pet_name="白猫", port=19001
    )
    service._handle_datagram(
        LanPacketCodec.encode(ephemeral_packet), QHostAddress("192.168.1.21"), 19001
    )
    service._manual_peer_targets["saved"] = ("192.168.1.20", 19000)
    service._peer_seen_at["saved"] = 0
    service._peer_seen_at["ephemeral"] = 0
    changed = []
    removed = []
    service.peer_changed.connect(changed.append)
    service.peer_removed.connect(removed.append)

    service._expire_peers()

    assert "saved" not in service._peers
    assert "ephemeral" not in service._peers
    assert registry.load() == (saved_peer,)
    assert service._manual_peer_targets == {"saved": ("192.168.1.20", 19000)}
    assert removed == ["ephemeral"]
    assert changed == [service.peers()[0]]
    assert changed[0].saved is True
    assert changed[0].online is False
    assert changed[0].connection_state == "offline"


def test_service_binds_an_ephemeral_port_and_stops_cleanly(qtbot) -> None:
    app = QCoreApplication.instance() or QCoreApplication([])
    del app
    service = LanInteractionService(device_id="local", display_name="本机", pet_name="平安", port=0)

    assert service.start()
    assert service.is_running
    assert service.chat_is_available
    assert service.port > 0
    service.stop()
    assert not service.is_running


def test_service_keeps_udp_interactions_when_tcp_chat_port_is_occupied(qtbot) -> None:
    app = QCoreApplication.instance() or QCoreApplication([])
    del app
    occupied = QTcpServer()
    assert occupied.listen(QHostAddress.SpecialAddress.AnyIPv4, 0)
    service = LanInteractionService(
        device_id="local",
        display_name="本机",
        pet_name="平安",
        port=occupied.serverPort(),
    )

    assert service.start()
    assert service.is_running
    assert not service.chat_is_available

    service.stop()
    occupied.close()


def test_service_registers_a_remote_presence_with_ip_and_port(qtbot) -> None:
    app = QCoreApplication.instance() or QCoreApplication([])
    del app
    service = LanInteractionService(device_id="local", display_name="本机", pet_name="平安", port=0)
    changed = []
    service.peer_changed.connect(changed.append)
    packet = LanPacketCodec.hello(device_id="remote", display_name="邻居", pet_name="橘猫", port=19000)

    service._handle_datagram(LanPacketCodec.encode(packet), QHostAddress("192.168.1.20"), 19000)

    assert changed[0].device_id == "remote"
    assert (changed[0].ip_address, changed[0].port, changed[0].pet_name) == ("192.168.1.20", 19000, "橘猫")


def test_same_endpoint_replaces_an_older_unsaved_identity(qtbot) -> None:
    service = LanInteractionService(device_id="local", display_name="本机", pet_name="平安")
    removed: list[str] = []
    service.peer_removed.connect(removed.append)
    for device_id in ("ghost-a", "ghost-b"):
        packet = LanPacketCodec.hello(
            device_id=device_id,
            display_name=device_id,
            pet_name="猫",
            port=18487,
        )
        service._handle_datagram(
            LanPacketCodec.encode(packet),
            QHostAddress("192.168.1.20"),
            18487,
        )

    assert [peer.device_id for peer in service.peers()] == ["ghost-b"]
    assert removed == ["ghost-a"]
    assert "ghost-a" not in service._peer_seen_at


@pytest.mark.parametrize(
    ("second_ip", "second_port"),
    (("192.168.1.21", 18487), ("192.168.1.20", 18488)),
)
def test_different_endpoints_keep_both_unsaved_identities(
    qtbot,
    second_ip: str,
    second_port: int,
) -> None:
    service = LanInteractionService(device_id="local", display_name="本机", pet_name="平安")
    first = LanPacketCodec.hello(
        device_id="peer-a",
        display_name="甲",
        pet_name="猫",
        port=18487,
    )
    second = LanPacketCodec.hello(
        device_id="peer-b",
        display_name="乙",
        pet_name="猫",
        port=second_port,
    )

    service._handle_datagram(
        LanPacketCodec.encode(first),
        QHostAddress("192.168.1.20"),
        18487,
    )
    service._handle_datagram(
        LanPacketCodec.encode(second),
        QHostAddress(second_ip),
        second_port,
    )

    assert {peer.device_id for peer in service.peers()} == {"peer-a", "peer-b"}


def test_service_sends_a_targeted_interaction_over_local_udp(qtbot) -> None:
    app = QCoreApplication.instance() or QCoreApplication([])
    del app
    sender = LanInteractionService(device_id="sender", display_name="发送方", pet_name="平安", port=0)
    receiver = LanInteractionService(device_id="receiver", display_name="接收方", pet_name="橘猫", port=0)
    assert sender.start()
    assert receiver.start()
    received = []
    receiver.interaction_received.connect(received.append)
    presence = LanPacketCodec.hello(
        device_id="receiver", display_name="接收方", pet_name="橘猫", port=receiver.port
    )
    sender._handle_datagram(LanPacketCodec.encode(presence), QHostAddress.LocalHost, receiver.port)

    assert sender.send_interaction(InteractionDraft.quick("receiver", InteractionKind.HEART))
    QTest.qWait(40)

    assert received[0].draft.kind is InteractionKind.HEART
    sender.stop()
    receiver.stop()


def test_service_manual_probe_registers_a_peer_over_direct_ip(qtbot) -> None:
    app = QCoreApplication.instance() or QCoreApplication([])
    del app
    sender = LanInteractionService(device_id="sender", display_name="发送方", pet_name="平安", port=0)
    receiver = LanInteractionService(device_id="receiver", display_name="接收方", pet_name="橘猫", port=0)
    assert sender.start()
    assert receiver.start()
    added = []
    sender.manual_probe_succeeded.connect(added.append)

    assert sender.probe_peer("127.0.0.1", receiver.port)
    QTest.qWait(80)

    assert added[0].device_id == "receiver"
    assert added[0].ip_address == "127.0.0.1"
    sender.stop()
    receiver.stop()


def test_service_manual_probe_rejects_invalid_ip(qtbot) -> None:
    app = QCoreApplication.instance() or QCoreApplication([])
    del app
    service = LanInteractionService(device_id="local", display_name="本机", pet_name="平安", port=0)
    errors = []
    service.error.connect(errors.append)
    assert service.start()

    assert not service.probe_peer("not-an-ip")
    assert "IP" in errors[0]
    service.stop()


def test_pool_probe_can_pin_an_unknown_roster_device_identity(qtbot) -> None:
    service = LanInteractionService(
        device_id="local",
        display_name="本机",
        pet_name="平安",
        port=0,
        interface_provider=lambda: (),
    )
    sent = []
    try:
        assert service.start()
        service._send_packet = lambda packet, address, port: sent.append((address.toString(), port)) or True

        assert service.probe_peer("192.168.20.12", 18487, expected_device_id="roster-peer")

        assert service._manual_probe_expected_device_id == "roster-peer"
        assert sent == [("192.168.20.12", 18487)]
    finally:
        service.stop()


def test_manual_peer_is_refreshed_by_direct_hello_without_broadcast(qtbot) -> None:
    app = QCoreApplication.instance() or QCoreApplication([])
    del app
    sender = LanInteractionService(device_id="sender", display_name="发送方", pet_name="平安", port=0)
    receiver = LanInteractionService(device_id="receiver", display_name="接收方", pet_name="橘猫", port=0)
    assert sender.start()
    assert receiver.start()
    added = []
    sender.manual_probe_succeeded.connect(added.append)

    assert sender.probe_peer("127.0.0.1", receiver.port)
    QTest.qWait(80)
    assert added and added[0].device_id == "receiver"
    assert "receiver" in sender._manual_peer_targets
    before = sender._peer_seen_at["receiver"]

    sender._refresh_manual_peers()
    QTest.qWait(80)

    assert sender._peer_seen_at["receiver"] > before
    sender.stop()
    receiver.stop()


def test_three_services_keep_alert_group_chat_and_danger_alerts_inside_membership(qtbot) -> None:
    sender = LanInteractionService(
        device_id="sender", display_name="发送方", pet_name="平安", port=0,
        alert_group_joined=True, interface_provider=lambda: (),
    )
    joined = LanInteractionService(
        device_id="joined", display_name="已加入", pet_name="橘猫", port=0,
        alert_group_joined=True, interface_provider=lambda: (),
    )
    left = LanInteractionService(
        device_id="left", display_name="未加入", pet_name="白猫", port=0,
        alert_group_joined=False, interface_provider=lambda: (),
    )
    joined_chat = []
    left_chat = []
    joined_alerts = []
    left_alerts = []
    deliveries = []
    joined.chat_message_received.connect(joined_chat.append)
    left.chat_message_received.connect(left_chat.append)
    joined.danger_alert_received.connect(joined_alerts.append)
    left.danger_alert_received.connect(left_alerts.append)
    sender.danger_alert_delivery_completed.connect(deliveries.append)
    sender._danger_retry_ms = 30
    sender._danger_completion_ms = 100
    try:
        assert sender.start()
        assert joined.start()
        assert left.start()
        assert sender.probe_peer("127.0.0.1", joined.port)
        qtbot.waitUntil(
            lambda: any(peer.device_id == "joined" and peer.alert_group_joined for peer in sender.peers()),
            timeout=2_000,
        )
        assert sender.probe_peer("127.0.0.1", left.port)
        qtbot.waitUntil(
            lambda: any(peer.device_id == "left" for peer in sender.peers()),
            timeout=2_000,
        )

        assert sender.send_chat(ChatDraft.alert_group_text_message("预警组消息"))
        qtbot.waitUntil(lambda: len(joined_chat) == 1, timeout=2_000)
        assert left_chat == []
        assert joined_chat[0].scope is ChatScope.ALERT_GROUP

        assert sender.send_danger_alert()
        qtbot.waitUntil(lambda: len(joined_alerts) == 1 and len(deliveries) == 1, timeout=2_000)

        assert left_alerts == []
        assert deliveries[0].acknowledged_device_ids == ("joined",)
    finally:
        sender.stop()
        joined.stop()
        left.stop()


def test_discover_sends_to_each_active_interface_broadcast_and_limited_broadcast(qtbot) -> None:
    app = QCoreApplication.instance() or QCoreApplication([])
    del app
    service = LanInteractionService(
        device_id="local",
        display_name="本机",
        pet_name="平安",
        port=19000,
        interface_provider=lambda: (
            InterfaceIPv4("Ethernet", True, True, False, "192.168.101.42", "192.168.101.255"),
            InterfaceIPv4("Wi-Fi", True, True, False, "192.168.20.10", "192.168.20.255"),
        ),
    )
    sent = []
    service._running = True
    service._send_packet = lambda packet, address, port: sent.append((packet, address.toString(), port)) or True

    service.discover()

    assert [address for _, address, _ in sent] == ["192.168.20.255", "192.168.101.255", "255.255.255.255"]
    assert {port for _, _, port in sent} == {19000}
    assert {packet["kind"] for packet, _, _ in sent} == {"hello"}


def test_discover_deduplicates_broadcasts_and_continues_after_a_send_failure(qtbot) -> None:
    app = QCoreApplication.instance() or QCoreApplication([])
    del app
    service = LanInteractionService(
        device_id="local",
        display_name="本机",
        pet_name="平安",
        port=19000,
        interface_provider=lambda: (
            InterfaceIPv4("Ethernet", True, True, False, "192.168.20.10", "192.168.20.255"),
            InterfaceIPv4("Alias", True, True, False, "10.0.0.8", "192.168.20.255"),
            InterfaceIPv4("Wide net", True, True, False, "10.1.2.3", "255.255.255.255"),
            InterfaceIPv4("Tailscale", True, True, False, "169.254.2.1", "169.254.255.255"),
            InterfaceIPv4("Loopback", True, True, True, "127.0.0.1", "127.255.255.255"),
            InterfaceIPv4("Disconnected", False, False, False, "192.168.1.8", "192.168.1.255"),
        ),
    )
    sent = []
    service._running = True

    def send(packet, address, port):
        sent.append(address.toString())
        return False

    service._send_packet = send
    service.discover()

    assert sent == ["192.168.20.255", "255.255.255.255"]


def test_refresh_connections_discovers_and_probes_saved_peers(qtbot) -> None:
    service = LanInteractionService(device_id="local", display_name="本机", pet_name="平安")
    calls: list[str] = []
    service._running = True
    service.discover = lambda: calls.append("discover")
    service._probe_saved_peers = lambda: calls.append("saved")

    service.refresh_connections()

    assert calls == ["discover", "saved"]


def test_refresh_connections_is_noop_while_stopped(qtbot) -> None:
    service = LanInteractionService(device_id="local", display_name="本机", pet_name="平安")
    calls: list[str] = []
    service.discover = lambda: calls.append("discover")
    service._probe_saved_peers = lambda: calls.append("saved")

    service.refresh_connections()

    assert calls == []
