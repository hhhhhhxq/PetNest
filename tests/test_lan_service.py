"""UDP 服务生命周期和设备登记测试。"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication
from PySide6.QtNetwork import QHostAddress, QTcpServer
from PySide6.QtTest import QTest

from petnest.core.lan_interaction import LanPacketCodec
from petnest.core.lan_service import LanInteractionService
from petnest.models.lan_interaction import InteractionDraft, InteractionKind


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
