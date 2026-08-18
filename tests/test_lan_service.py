"""UDP 服务生命周期和设备登记测试。"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication
from PySide6.QtNetwork import QHostAddress, QTcpServer
from PySide6.QtTest import QTest

import petnest.core.lan_service as lan_service_module
from petnest.core.lan_discovery import InterfaceIPv4
from petnest.core.lan_interaction import LanPacketCodec
from petnest.core.lan_peer_registry import KnownLanPeer, KnownLanPeerRegistry
from petnest.core.lan_service import LanInteractionService
from petnest.models.lan_interaction import InteractionDraft, InteractionKind, LanPeer


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
        device_id="attacker", display_name="冒名者", pet_name="猫", port=19001
    )

    service._handle_datagram(
        LanPacketCodec.encode(packet), QHostAddress(trusted.ip_address), 19001
    )

    assert registry.load() == (trusted,)
    assert all(peer.device_id != "attacker" for peer in service.peers())
    assert errors and "身份" in errors[-1]


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
