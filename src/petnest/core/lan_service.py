"""UDP discovery/interactions and framed TCP chat for trusted LAN peers."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import replace
import logging
from ipaddress import IPv4Address, ip_address as parse_ip_address
from time import monotonic

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtNetwork import QHostAddress, QTcpServer, QTcpSocket, QUdpSocket

from petnest.core.codex_usage import CodexDeviceUsageSnapshot
from petnest.core.lan_discovery import InterfaceIPv4, eligible_broadcast_addresses, qt_interface_ipv4
from petnest.core.lan_interaction import (
    LAN_INTERACTION_PORT,
    MAX_CHAT_PACKET_BYTES,
    LanPacketCodec,
    LanProtocolError,
    ReceivedCodexUsageSync,
    ReceivedInteraction,
)
from petnest.core.lan_peer_registry import KnownLanPeer, KnownLanPeerRegistry
from petnest.models.lan_interaction import ChatDraft, ChatMessageKind, InteractionDraft, LanChatMessage, LanPeer

LOGGER = logging.getLogger(__name__)
MANUAL_PROBE_TIMEOUT_MS = 4_000
MANUAL_REFRESH_INTERVAL_MS = 8_000


class LanInteractionService(QObject):
    """不阻塞 GUI 的局域网发现、互动与聊天服务。"""

    peer_changed = Signal(object)
    peer_removed = Signal(str)
    interaction_received = Signal(object)
    manual_probe_succeeded = Signal(object)
    codex_usage_sync_requested = Signal(object)
    codex_usage_sync_received = Signal(object)
    chat_message_added = Signal(object)
    chat_message_received = Signal(object)
    error = Signal(str)
    running_changed = Signal(bool)

    def __init__(
        self,
        *,
        device_id: str,
        display_name: str,
        pet_name: str,
        port: int = LAN_INTERACTION_PORT,
        interface_provider: Callable[[], Iterable[InterfaceIPv4]] | None = None,
        peer_registry: KnownLanPeerRegistry | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.device_id = device_id
        self.display_name = display_name
        self.pet_name = pet_name
        self.requested_port = port
        self._interface_provider = interface_provider or qt_interface_ipv4
        self._peer_registry = peer_registry
        self._port = port
        self._running = False
        self._peers: dict[str, LanPeer] = {}
        self._peer_seen_at: dict[str, float] = {}
        self._interaction_times: dict[str, list[float]] = {}
        self._usage_sync_times: dict[str, list[float]] = {}
        self._chat_times: dict[tuple[str, str], list[float]] = {}
        self._chat_messages: list[LanChatMessage] = []
        self._chat_message_ids: set[str] = set()
        self._manual_peer_targets: dict[str, tuple[str, int]] = {}
        self._manual_probe_target: tuple[str, int] | None = None
        self._saved_probe_targets: dict[tuple[str, int], str] = {}
        self._socket = QUdpSocket(self)
        self._socket.readyRead.connect(self._read_datagrams)
        self._tcp_server = QTcpServer(self)
        self._tcp_server.newConnection.connect(self._accept_chat_connections)
        self._incoming_chat_buffers: dict[QTcpSocket, bytearray] = {}
        self._outgoing_chat_sockets: set[QTcpSocket] = set()
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
        self._saved_probe_timer = QTimer(self)
        self._saved_probe_timer.setSingleShot(True)
        self._saved_probe_timer.setInterval(MANUAL_PROBE_TIMEOUT_MS)
        self._saved_probe_timer.timeout.connect(self._saved_probe_timeout)
        self._manual_refresh_timer = QTimer(self)
        self._manual_refresh_timer.setInterval(MANUAL_REFRESH_INTERVAL_MS)
        self._manual_refresh_timer.timeout.connect(self._refresh_manual_peers)

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def port(self) -> int:
        return self._port

    @property
    def chat_is_available(self) -> bool:
        return self._running and self._tcp_server.isListening()

    def peers(self) -> tuple[LanPeer, ...]:
        peers = dict(self._peers)
        for saved_peer in self._known_peers().values():
            current = peers.get(saved_peer.device_id)
            if current is not None:
                peers[saved_peer.device_id] = replace(current, saved=True, connection_state="online")
                continue
            connecting = saved_peer.device_id in self._saved_probe_targets.values()
            peers[saved_peer.device_id] = LanPeer(
                device_id=saved_peer.device_id,
                display_name=saved_peer.display_name,
                ip_address=saved_peer.ip_address,
                port=saved_peer.port,
                online=False,
                saved=True,
                connection_state="connecting" if connecting else "offline",
            )
        return tuple(sorted(peers.values(), key=lambda item: item.display_name.casefold()))

    def unavailable_known_peers(self) -> tuple[LanPeer, ...]:
        """Return saved peers that do not currently have a live LAN presence."""
        return tuple(peer for peer in self.peers() if peer.saved and not peer.online)

    def forget_peer(self, device_id: str) -> None:
        """Forget one locally saved peer without contacting the remote device."""
        if self._peer_registry is not None:
            self._peer_registry.forget(device_id)
        self._peers.pop(device_id, None)
        self._peer_seen_at.pop(device_id, None)
        self._manual_peer_targets.pop(device_id, None)
        self._saved_probe_targets = {
            target: expected_device_id
            for target, expected_device_id in self._saved_probe_targets.items()
            if expected_device_id != device_id
        }
        self._interaction_times.pop(device_id, None)
        self._usage_sync_times.pop(device_id, None)
        self.peer_removed.emit(device_id)

    def _known_peers(self) -> dict[str, KnownLanPeer]:
        if self._peer_registry is None:
            return {}
        return {peer.device_id: peer for peer in self._peer_registry.load()}

    def manual_peer_ids(self) -> tuple[str, ...]:
        return tuple(self._manual_peer_targets)

    def chat_messages(self, peer_device_id: str | None = None) -> tuple[LanChatMessage, ...]:
        if peer_device_id is None:
            return tuple(self._chat_messages)
        return tuple(
            message
            for message in self._chat_messages
            if message.peer_device_id(self.device_id) == peer_device_id
        )

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
        if not self._tcp_server.listen(QHostAddress.SpecialAddress.AnyIPv4, self._port):
            message = f"局域网聊天暂不可用：{self._tcp_server.errorString()}"
            LOGGER.warning(message)
            self.error.emit(message)
        self._running = True
        self._announce_timer.start()
        self._expiry_timer.start()
        self._manual_refresh_timer.start()
        self.running_changed.emit(True)
        self.discover()
        self._probe_saved_peers()
        return True

    def stop(self) -> None:
        if not self._running:
            return
        self._announce_timer.stop()
        self._expiry_timer.stop()
        self._manual_refresh_timer.stop()
        self._socket.close()
        self._tcp_server.close()
        for socket in tuple(self._incoming_chat_buffers) + tuple(self._outgoing_chat_sockets):
            socket.abort()
            socket.deleteLater()
        self._incoming_chat_buffers.clear()
        self._outgoing_chat_sockets.clear()
        self._manual_probe_timer.stop()
        self._saved_probe_timer.stop()
        self._manual_peer_targets.clear()
        self._manual_probe_target = None
        self._saved_probe_targets.clear()
        self._running = False
        self._peers.clear()
        self._peer_seen_at.clear()
        self._interaction_times.clear()
        self._usage_sync_times.clear()
        self._chat_times.clear()
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
        try:
            broadcasts = eligible_broadcast_addresses(self._interface_provider())
        except Exception:
            LOGGER.warning("无法枚举局域网接口广播地址", exc_info=True)
            broadcasts = ()
        for broadcast in dict.fromkeys((*broadcasts, "255.255.255.255")):
            self._send_packet(packet, QHostAddress(broadcast), self._port)

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

    def _probe_saved_peers(self) -> None:
        """Probe all persisted peers concurrently after the local socket is running."""
        if not self._running:
            return
        saved_peers = tuple(self._known_peers().values())
        if not saved_peers:
            return
        packet = LanPacketCodec.hello(
            device_id=self.device_id,
            display_name=self.display_name,
            pet_name=self.pet_name,
            port=self._port,
        )
        for saved_peer in saved_peers:
            target = (saved_peer.ip_address, saved_peer.port)
            self._manual_peer_targets[saved_peer.device_id] = target
            if self._send_packet(packet, QHostAddress(saved_peer.ip_address), saved_peer.port):
                self._saved_probe_targets[target] = saved_peer.device_id
        if self._saved_probe_targets:
            self._saved_probe_timer.start()

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

    def send_chat(self, draft: ChatDraft) -> bool:
        """Send one direct message or fan a room message out to current peers."""
        if not self._running:
            self.error.emit("局域网互动服务尚未启动")
            return False
        if not self.chat_is_available:
            self.error.emit("本机 TCP 聊天端口被占用，请关闭其他 PetNest 进程后重试")
            return False
        try:
            message = draft.to_message(
                sender_device_id=self.device_id,
                sender_name=self.display_name,
            )
        except (LanProtocolError, TypeError, ValueError) as error:
            self.error.emit(str(error))
            return False
        if draft.is_group:
            peers = tuple(
                peer
                for peer in self._peers.values()
                if peer.ip_address and peer.port and peer.online
            )
            if not peers:
                self.error.emit("局域网群聊暂无其他在线设备")
                return False
            try:
                deliveries = tuple(
                    (
                        peer,
                        LanPacketCodec.encode_chat_frame(
                            replace(message, target_device_id=peer.device_id)
                        ),
                    )
                    for peer in peers
                )
            except (LanProtocolError, TypeError, ValueError) as error:
                self.error.emit(str(error))
                return False
            for peer, frame in deliveries:
                self._start_chat_send(peer, frame, message)
            return True
        peer = self._peers.get(draft.target_device_id)
        if peer is None or not peer.ip_address or not peer.port:
            self.error.emit("聊天对象已离线，请刷新附近设备")
            return False
        try:
            frame = LanPacketCodec.encode_chat_frame(message)
        except (LanProtocolError, TypeError, ValueError) as error:
            self.error.emit(str(error))
            return False
        self._start_chat_send(peer, frame, message)
        return True

    def _start_chat_send(self, peer: LanPeer, frame: bytes, history_message: LanChatMessage) -> None:
        socket = QTcpSocket(self)
        self._outgoing_chat_sockets.add(socket)
        socket.connected.connect(lambda: self._write_chat_frame(socket, frame, history_message))
        socket.disconnected.connect(lambda: self._cleanup_chat_socket(socket))
        socket.errorOccurred.connect(lambda _error: self._chat_socket_failed(socket, peer.display_name))
        timeout = QTimer(socket)
        timeout.setSingleShot(True)
        timeout.timeout.connect(lambda: self._chat_connect_timeout(socket, peer.display_name))
        timeout.start(5_000)
        socket.connectToHost(str(peer.ip_address), int(peer.port or 0))

    def _write_chat_frame(self, socket: QTcpSocket, frame: bytes, message: LanChatMessage) -> None:
        if socket not in self._outgoing_chat_sockets:
            return
        written = socket.write(frame)
        if written != len(frame):
            self.error.emit(f"聊天消息发送失败：{socket.errorString()}")
            socket.abort()
            return
        self._remember_chat_message(message)
        socket.disconnectFromHost()

    def _chat_socket_failed(self, socket: QTcpSocket, peer_name: str) -> None:
        if socket not in self._outgoing_chat_sockets:
            return
        self.error.emit(f"无法发送给 {peer_name}：{socket.errorString()}")
        self._cleanup_chat_socket(socket)

    def _chat_connect_timeout(self, socket: QTcpSocket, peer_name: str) -> None:
        if socket not in self._outgoing_chat_sockets:
            return
        self.error.emit(f"连接 {peer_name} 超时，聊天消息未发送")
        socket.abort()
        self._cleanup_chat_socket(socket)

    def _accept_chat_connections(self) -> None:
        while self._tcp_server.hasPendingConnections():
            socket = self._tcp_server.nextPendingConnection()
            if socket is None:
                break
            self._incoming_chat_buffers[socket] = bytearray()
            timeout = QTimer(socket)
            timeout.setSingleShot(True)
            timeout.setInterval(10_000)
            timeout.timeout.connect(socket.abort)
            timeout.start()
            socket.readyRead.connect(lambda socket=socket: self._read_chat_stream(socket))
            socket.disconnected.connect(lambda socket=socket: self._cleanup_chat_socket(socket))
            socket.errorOccurred.connect(lambda _error, socket=socket: self._cleanup_chat_socket(socket))

    def _read_chat_stream(self, socket: QTcpSocket) -> None:
        buffer = self._incoming_chat_buffers.get(socket)
        if buffer is None:
            return
        buffer.extend(bytes(socket.readAll()))
        while len(buffer) >= 4:
            payload_size = int.from_bytes(buffer[:4], "big")
            if payload_size <= 0 or payload_size > MAX_CHAT_PACKET_BYTES:
                LOGGER.warning("拒绝超过安全大小的局域网聊天消息")
                socket.abort()
                return
            if len(buffer) < 4 + payload_size:
                return
            payload = bytes(buffer[4 : 4 + payload_size])
            del buffer[: 4 + payload_size]
            try:
                message = LanPacketCodec.decode_chat_message(payload, local_device_id=self.device_id)
            except LanProtocolError as error:
                LOGGER.debug("忽略无效局域网聊天消息：%s", error)
                socket.abort()
                return
            if not self._trusted_chat_sender(message, socket.peerAddress()):
                LOGGER.warning("忽略来自未握手设备的局域网聊天消息")
                socket.abort()
                return
            if not self._allow_chat(message):
                continue
            if self._remember_chat_message(message):
                self.chat_message_received.emit(message)

    def _cleanup_chat_socket(self, socket: QTcpSocket) -> None:
        self._incoming_chat_buffers.pop(socket, None)
        self._outgoing_chat_sockets.discard(socket)
        socket.deleteLater()

    def _trusted_chat_sender(self, message: LanChatMessage, address: QHostAddress) -> bool:
        peer = self._peers.get(message.sender_device_id)
        if peer is None or not peer.ip_address:
            return False
        return address.toString() == peer.ip_address

    def _allow_chat(self, message: LanChatMessage) -> bool:
        now = monotonic()
        rate_kind = "image" if message.kind is ChatMessageKind.IMAGE else "small"
        key = (message.sender_device_id, rate_kind)
        recent = [stamp for stamp in self._chat_times.get(key, []) if now - stamp < 60]
        limit = 12 if message.kind is ChatMessageKind.IMAGE else 60
        if len(recent) >= limit:
            self._chat_times[key] = recent
            LOGGER.warning("忽略过于频繁的局域网聊天：%s", message.sender_device_id)
            return False
        recent.append(now)
        self._chat_times[key] = recent
        return True

    def _remember_chat_message(self, message: LanChatMessage) -> bool:
        if message.message_id in self._chat_message_ids:
            return False
        self._chat_messages.append(message)
        self._chat_message_ids.add(message.message_id)
        image_bytes = sum(len(item.image_data or b"") for item in self._chat_messages)
        while len(self._chat_messages) > 200 or image_bytes > 30 * 1024 * 1024:
            removed = self._chat_messages.pop(0)
            self._chat_message_ids.discard(removed.message_id)
            image_bytes -= len(removed.image_data or b"")
        self.chat_message_added.emit(message)
        return True

    def send_codex_usage_sync(
        self,
        *,
        target_device_id: str,
        request_id: str,
        snapshot: CodexDeviceUsageSnapshot,
        response: bool = False,
    ) -> bool:
        """Send one local-only contribution to an already discovered peer."""
        if not self._running:
            self.error.emit("局域网互动服务尚未启动")
            return False
        peer = self._peers.get(target_device_id)
        if peer is None or not peer.ip_address or not peer.port:
            self.error.emit("同步目标设备已离线")
            return False
        packet = LanPacketCodec.codex_usage_sync(
            kind="codex_usage_sync_response" if response else "codex_usage_sync_request",
            request_id=request_id,
            target_device_id=target_device_id,
            snapshot=snapshot,
        )
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
            if self._reject_unexpected_probe_identity(presence, address, source_port):
                return
            peer = self._handle_presence(presence, address)
            if peer is not None:
                self._complete_manual_probe(peer, source_port)
                self._complete_saved_probe(peer, source_port)
            if presence["kind"] == "hello" and self._running and self._port > 0:
                packet = LanPacketCodec.hello_ack(
                    device_id=self.device_id,
                    display_name=self.display_name,
                    pet_name=self.pet_name,
                    port=self._port,
                )
                self._send_packet(packet, address, int(presence["port"]))
            return
        try:
            usage_sync = LanPacketCodec.decode_codex_usage_sync(
                data,
                local_device_id=self.device_id,
            )
        except LanProtocolError:
            usage_sync = None
        if usage_sync is not None:
            if not self._trusted_sync_sender(usage_sync, address, source_port):
                return
            if not self._allow_usage_sync(usage_sync.snapshot.device_id):
                return
            if usage_sync.kind == "codex_usage_sync_request":
                self.codex_usage_sync_requested.emit(usage_sync)
            else:
                self.codex_usage_sync_received.emit(usage_sync)
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
        is_saved = device_id in self._known_peers()
        peer = LanPeer(
            device_id=device_id,
            display_name=str(presence["display_name"]),
            pet_name=str(presence["pet_name"]),
            ip_address=host,
            port=int(presence["port"]),
            online=True,
            saved=is_saved,
            connection_state="online",
        )
        previous = self._peers.get(device_id)
        self._peers[device_id] = peer
        self._peer_seen_at[device_id] = monotonic()
        if is_saved:
            self._save_verified_peer(peer)
        if device_id in self._manual_peer_targets:
            self._manual_peer_targets[device_id] = (host, int(presence["port"]))
        if previous != peer:
            self.peer_changed.emit(peer)
        return peer

    def _complete_manual_probe(self, peer: LanPeer, source_port: int) -> None:
        target = self._manual_probe_target
        if (
            target is None
            or (peer.ip_address, int(source_port)) != target
            or peer.port != target[1]
        ):
            return
        self._manual_probe_target = None
        self._manual_probe_timer.stop()
        self._manual_peer_targets[peer.device_id] = (peer.ip_address, int(peer.port or target[1]))
        self._save_verified_peer(peer)
        self.manual_probe_succeeded.emit(peer)

    def _complete_saved_probe(self, peer: LanPeer, source_port: int) -> None:
        target = (peer.ip_address, int(source_port))
        expected_device_id = self._saved_probe_targets.get(target)
        if expected_device_id is not None and expected_device_id != peer.device_id:
            return
        if expected_device_id is None and not peer.saved:
            return
        self._saved_probe_targets = {
            saved_target: saved_device_id
            for saved_target, saved_device_id in self._saved_probe_targets.items()
            if saved_device_id != peer.device_id
        }
        if not self._saved_probe_targets:
            self._saved_probe_timer.stop()
        self._manual_peer_targets[peer.device_id] = (
            peer.ip_address,
            int(peer.port or source_port),
        )

    def _reject_unexpected_probe_identity(
        self,
        presence: dict[str, object],
        address: QHostAddress,
        source_port: int,
    ) -> bool:
        host = (
            address.toString()
            if isinstance(address, QHostAddress)
            else QHostAddress(address).toString()
        )
        device_id = str(presence["device_id"])
        expected_device_id = self._saved_probe_targets.get((host, int(source_port)))
        if expected_device_id is not None and expected_device_id != device_id:
            self.error.emit("已保存伙伴身份不匹配，已拒绝此次重连")
            return True
        target = self._manual_probe_target
        if target is not None and target[0] == host:
            if int(source_port) != target[1] or int(presence["port"]) != target[1]:
                return True
        if target is None or target[0] != host:
            if (
                self._peer_registry is not None
                and not self._peer_registry.matches_expected_identity(host, device_id)
            ):
                self.error.emit("已保存伙伴身份不匹配，已拒绝此次重连")
                return True
            return False
        if self._peer_registry is None or self._peer_registry.matches_expected_identity(host, device_id):
            return False
        self._manual_probe_target = None
        self._manual_probe_timer.stop()
        self.error.emit("已保存伙伴身份不匹配，已拒绝覆盖")
        return True

    def _save_verified_peer(self, peer: LanPeer) -> None:
        if self._peer_registry is None or not peer.ip_address or not peer.port:
            return
        try:
            self._peer_registry.upsert(
                KnownLanPeer(
                    device_id=peer.device_id,
                    display_name=peer.display_name,
                    ip_address=peer.ip_address,
                    port=peer.port,
                )
            )
        except (OSError, ValueError) as error:
            self.error.emit(f"无法保存局域网伙伴：{error}")

    def _manual_probe_timeout(self) -> None:
        target = self._manual_probe_target
        self._manual_probe_target = None
        if target is None:
            return
        self.error.emit(
            f"无法验证 {target[0]}：4 秒内未收到回应。请确认对方已启动 PetNest、"
            "UDP 18487 已放行，且两个网段允许设备互通。"
            "如需聊天，还需放行 TCP 18487。"
        )

    def _saved_probe_timeout(self) -> None:
        pending_device_ids = set(self._saved_probe_targets.values())
        self._saved_probe_targets.clear()
        for peer in self.peers():
            if peer.device_id in pending_device_ids and not peer.online:
                self.peer_changed.emit(peer)

    def _expire_peers(self) -> None:
        cutoff = monotonic() - 24
        expired = [device_id for device_id, seen_at in self._peer_seen_at.items() if seen_at < cutoff]
        known_peers = self._known_peers()
        for device_id in expired:
            self._peer_seen_at.pop(device_id, None)
            self._peers.pop(device_id, None)
            saved_peer = known_peers.get(device_id)
            if saved_peer is None:
                self.peer_removed.emit(device_id)
                continue
            self.peer_changed.emit(
                LanPeer(
                    device_id=saved_peer.device_id,
                    display_name=saved_peer.display_name,
                    ip_address=saved_peer.ip_address,
                    port=saved_peer.port,
                    online=False,
                    saved=True,
                    connection_state="offline",
                )
            )

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

    def _trusted_sync_sender(
        self,
        received: ReceivedCodexUsageSync,
        address: QHostAddress,
        source_port: int,
    ) -> bool:
        """Only accept sync packets from the address registered by hello."""
        peer = self._peers.get(received.snapshot.device_id)
        if peer is None or not peer.ip_address or not peer.port:
            return False
        host = address.toString() if isinstance(address, QHostAddress) else QHostAddress(address).toString()
        return host == peer.ip_address and int(source_port) == peer.port

    def _allow_usage_sync(self, device_id: str) -> bool:
        now = monotonic()
        recent = [stamp for stamp in self._usage_sync_times.get(device_id, []) if now - stamp < 60]
        if len(recent) >= 12:
            self._usage_sync_times[device_id] = recent
            LOGGER.warning("忽略过于频繁的 Codex 用量同步：%s", device_id)
            return False
        recent.append(now)
        self._usage_sync_times[device_id] = recent
        return True
