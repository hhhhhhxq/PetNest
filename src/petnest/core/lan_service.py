"""基于 UDP 广播的局域网发现与互动传输。"""

from __future__ import annotations

import logging
from ipaddress import IPv4Address, ip_address as parse_ip_address
from time import monotonic

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtNetwork import QHostAddress, QUdpSocket

from petnest.core.lan_interaction import (
    LAN_INTERACTION_PORT,
    LanPacketCodec,
    LanProtocolError,
    ReceivedInteraction,
)
from petnest.models.lan_interaction import InteractionDraft, LanPeer

LOGGER = logging.getLogger(__name__)
MANUAL_PROBE_TIMEOUT_MS = 4_000
MANUAL_REFRESH_INTERVAL_MS = 8_000


class LanInteractionService(QObject):
    """不阻塞 GUI 的本地 UDP 服务，只广播身份和安全互动消息。"""

    peer_changed = Signal(object)
    peer_removed = Signal(str)
    interaction_received = Signal(object)
    manual_probe_succeeded = Signal(object)
    error = Signal(str)
    running_changed = Signal(bool)

    def __init__(
        self,
        *,
        device_id: str,
        display_name: str,
        pet_name: str,
        port: int = LAN_INTERACTION_PORT,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.device_id = device_id
        self.display_name = display_name
        self.pet_name = pet_name
        self.requested_port = port
        self._port = port
        self._running = False
        self._peers: dict[str, LanPeer] = {}
        self._peer_seen_at: dict[str, float] = {}
        self._interaction_times: dict[str, list[float]] = {}
        self._manual_peer_targets: dict[str, tuple[str, int]] = {}
        self._manual_probe_target: tuple[str, int] | None = None
        self._socket = QUdpSocket(self)
        self._socket.readyRead.connect(self._read_datagrams)
        self._announce_timer = QTimer(self)
        self._announce_timer.setInterval(8_000)
        self._announce_timer.timeout.connect(self.discover)
        self._expiry_timer = QTimer(self)
        self._expiry_timer.setInterval(4_000)
        self._expiry_timer.timeout.connect(self._expire_peers)
        self._manual_probe_timer = QTimer(self)
        self._manual_probe_timer.setSingleShot(True)
        self._manual_probe_timer.setInterval(MANUAL_PROBE_TIMEOUT_MS)
        self._manual_probe_timer.timeout.connect(self._manual_probe_timeout)
        self._manual_refresh_timer = QTimer(self)
        self._manual_refresh_timer.setInterval(MANUAL_REFRESH_INTERVAL_MS)
        self._manual_refresh_timer.timeout.connect(self._refresh_manual_peers)

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def port(self) -> int:
        return self._port

    def peers(self) -> tuple[LanPeer, ...]:
        return tuple(sorted(self._peers.values(), key=lambda item: item.display_name.casefold()))

    def start(self) -> bool:
        if self._running:
            return True
        flags = QUdpSocket.BindFlag.ShareAddress | QUdpSocket.BindFlag.ReuseAddressHint
        if not self._socket.bind(QHostAddress.SpecialAddress.AnyIPv4, self.requested_port, flags):
            message = f"无法开启局域网互动：{self._socket.errorString()}"
            LOGGER.warning(message)
            self.error.emit(message)
            return False
        self._port = self._socket.localPort()
        self._running = True
        self._announce_timer.start()
        self._expiry_timer.start()
        self._manual_refresh_timer.start()
        self.running_changed.emit(True)
        self.discover()
        return True

    def stop(self) -> None:
        if not self._running:
            return
        self._announce_timer.stop()
        self._expiry_timer.stop()
        self._manual_refresh_timer.stop()
        self._socket.close()
        self._manual_probe_timer.stop()
        self._manual_peer_targets.clear()
        self._manual_probe_target = None
        self._running = False
        self._peers.clear()
        self._peer_seen_at.clear()
        self._interaction_times.clear()
        self.running_changed.emit(False)

    def update_identity(self, *, display_name: str, pet_name: str) -> None:
        self.display_name = display_name
        self.pet_name = pet_name
        if self._running:
            self.discover()

    def discover(self) -> None:
        if not self._running:
            return
        packet = LanPacketCodec.hello(
            device_id=self.device_id,
            display_name=self.display_name,
            pet_name=self.pet_name,
            port=self._port,
        )
        self._send_packet(packet, QHostAddress.SpecialAddress.Broadcast, self._port)

    def _refresh_manual_peers(self) -> None:
        """用定向 hello 续期手动添加的跨网段设备。"""
        if not self._running or not self._manual_peer_targets:
            return
        packet = LanPacketCodec.hello(
            device_id=self.device_id,
            display_name=self.display_name,
            pet_name=self.pet_name,
            port=self._port,
        )
        for ip_address, port in tuple(self._manual_peer_targets.values()):
            self._send_packet(packet, QHostAddress(ip_address), port)

    def probe_peer(self, ip_address: str, port: int = LAN_INTERACTION_PORT) -> bool:
        """向指定 IPv4 发送一次定向握手，绕过跨网段广播不可达的问题。"""
        if not self._running:
            self.error.emit("局域网互动服务尚未启动")
            return False
        try:
            parsed = parse_ip_address(str(ip_address).strip())
        except ValueError:
            self.error.emit("IP 地址格式无效，请输入 IPv4，例如 192.168.21.146")
            return False
        if not isinstance(parsed, IPv4Address):
            self.error.emit("暂只支持 IPv4 地址")
            return False
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65_535:
            self.error.emit("端口无效")
            return False
        if self._manual_probe_target is not None:
            self.error.emit("正在验证另一台设备，请稍候")
            return False

        normalized_ip = str(parsed)
        packet = LanPacketCodec.hello(
            device_id=self.device_id,
            display_name=self.display_name,
            pet_name=self.pet_name,
            port=self._port,
        )
        self._manual_probe_target = (normalized_ip, port)
        if not self._send_packet(packet, QHostAddress(normalized_ip), port):
            self._manual_probe_target = None
            return False
        self._manual_probe_timer.start()
        return True

    def send_interaction(self, draft: InteractionDraft) -> bool:
        if not self._running:
            self.error.emit("局域网互动服务尚未启动")
            return False
        peer = self._peers.get(draft.target_device_id)
        if peer is None or not peer.ip_address or not peer.port:
            self.error.emit("目标设备已离线，请刷新附近设备")
            return False
        packet = LanPacketCodec.interaction(draft, self.device_id, self.display_name)
        return self._send_packet(packet, QHostAddress(peer.ip_address), peer.port)

    def _send_packet(self, packet: dict[str, object], address: QHostAddress, port: int) -> bool:
        try:
            data = LanPacketCodec.encode(packet)
            written = self._socket.writeDatagram(data, address, port)
        except (LanProtocolError, TypeError, ValueError) as error:
            self.error.emit(str(error))
            return False
        if written != len(data):
            message = f"局域网消息发送失败：{self._socket.errorString()}"
            self.error.emit(message)
            return False
        return True

    def _read_datagrams(self) -> None:
        while self._socket.hasPendingDatagrams():
            size = self._socket.pendingDatagramSize()
            if size < 0:
                break
            data, address, source_port = self._socket.readDatagram(size)
            try:
                self._handle_datagram(bytes(data), address, source_port)
            except LanProtocolError as error:
                LOGGER.debug("忽略无效局域网消息：%s", error)

    def _handle_datagram(self, data: bytes, address: QHostAddress, source_port: int) -> None:
        try:
            presence = LanPacketCodec.decode_presence(data)
        except LanProtocolError:
            presence = None
        if presence is not None:
            peer = self._handle_presence(presence, address)
            if peer is not None:
                self._complete_manual_probe(peer)
            if presence["kind"] == "hello" and self._running and self._port > 0:
                packet = LanPacketCodec.hello_ack(
                    device_id=self.device_id,
                    display_name=self.display_name,
                    pet_name=self.pet_name,
                    port=self._port,
                )
                self._send_packet(packet, address, int(presence["port"]))
            return
        received = LanPacketCodec.decode_interaction(data, local_device_id=self.device_id)
        if not self._allow_interaction(received):
            return
        self.interaction_received.emit(received)

    def _handle_presence(self, presence: dict[str, object], address: QHostAddress) -> LanPeer | None:
        device_id = str(presence["device_id"])
        if device_id == self.device_id:
            return
        address = address if isinstance(address, QHostAddress) else QHostAddress(address)
        host = address.toString()
        peer = LanPeer(
            device_id=device_id,
            display_name=str(presence["display_name"]),
            pet_name=str(presence["pet_name"]),
            ip_address=host,
            port=int(presence["port"]),
            online=True,
        )
        previous = self._peers.get(device_id)
        self._peers[device_id] = peer
        self._peer_seen_at[device_id] = monotonic()
        if device_id in self._manual_peer_targets:
            self._manual_peer_targets[device_id] = (host, int(presence["port"]))
        if previous != peer:
            self.peer_changed.emit(peer)
        return peer

    def _complete_manual_probe(self, peer: LanPeer) -> None:
        target = self._manual_probe_target
        if target is None or peer.ip_address != target[0]:
            return
        self._manual_probe_target = None
        self._manual_probe_timer.stop()
        self._manual_peer_targets[peer.device_id] = target
        self.manual_probe_succeeded.emit(peer)

    def _manual_probe_timeout(self) -> None:
        target = self._manual_probe_target
        self._manual_probe_target = None
        if target is None:
            return
        self.error.emit(
            f"无法验证 {target[0]}：4 秒内未收到回应。请确认对方已启动 PetNest、"
            "UDP 18487 已放行，且两个网段允许设备互通。"
        )

    def _expire_peers(self) -> None:
        cutoff = monotonic() - 24
        expired = [device_id for device_id, seen_at in self._peer_seen_at.items() if seen_at < cutoff]
        for device_id in expired:
            self._peer_seen_at.pop(device_id, None)
            self._peers.pop(device_id, None)
            self.peer_removed.emit(device_id)

    def _allow_interaction(self, received: ReceivedInteraction) -> bool:
        """限制单个设备的速率，避免局域网广播被用来刷屏。"""
        now = monotonic()
        recent = [stamp for stamp in self._interaction_times.get(received.sender_device_id, []) if now - stamp < 60]
        if len(recent) >= 30:
            self._interaction_times[received.sender_device_id] = recent
            LOGGER.warning("忽略过于频繁的局域网互动：%s", received.sender_device_id)
            return False
        recent.append(now)
        self._interaction_times[received.sender_device_id] = recent
        return True
