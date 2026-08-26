"""UDP discovery/interactions and framed TCP chat for trusted LAN peers."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
import logging
from ipaddress import IPv4Address, ip_address as parse_ip_address
from time import monotonic, time
import uuid

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
from petnest.core.lan_peer_discovery_protocol import (
    MAX_DIRECTORY_FRAME_BYTES,
    PeerDirectory,
    PeerDirectoryCodec,
    PeerDirectoryProtocolError,
    PeerEndpointRecord,
)
from petnest.core.lan_peer_registry import KnownLanPeer, KnownLanPeerRegistry
from petnest.core.lan_pool_protocol import (
    MAX_POOL_FRAME_BYTES,
    MAX_POOL_UDP_BYTES,
    LanPoolPacketCodec,
    LanPoolProtocolError,
    PoolHeartbeat,
    PoolRecords,
    PoolSummary,
)
from petnest.models.lan_interaction import (
    ChatDraft,
    ChatMessageKind,
    ChatScope,
    DangerAlert,
    DangerAlertAck,
    DangerAlertDeliveryResult,
    InteractionDraft,
    LanChatMessage,
    LanPeer,
)

LOGGER = logging.getLogger(__name__)
MANUAL_PROBE_TIMEOUT_MS = 4_000
MANUAL_REFRESH_INTERVAL_MS = 8_000
MAX_LAN_FRAME_BYTES = max(
    MAX_CHAT_PACKET_BYTES,
    MAX_POOL_FRAME_BYTES,
    MAX_DIRECTORY_FRAME_BYTES,
)


@dataclass(slots=True)
class _PendingDangerAlert:
    target_device_ids: tuple[str, ...]
    endpoints: dict[str, tuple[str, int]]
    packets: dict[str, dict[str, object]]
    acknowledged: set[str]


@dataclass(frozen=True, slots=True)
class ReceivedPoolMessage:
    message: PoolHeartbeat | PoolSummary | PoolRecords
    address: str
    source_port: int


@dataclass(frozen=True, slots=True)
class VerifiedPresenceContext:
    peer: LanPeer
    address: str
    source_port: int
    extensions: tuple[str, ...]
    probe_token: str | None
    assisted: bool


@dataclass(frozen=True, slots=True)
class ReceivedPeerDirectory:
    message: PeerDirectory
    address: str


@dataclass(frozen=True, slots=True)
class _CandidateProbeTarget:
    device_id: str
    ip_address: str
    port: int


class LanInteractionService(QObject):
    """不阻塞 GUI 的局域网发现、互动与聊天服务。"""

    peer_changed = Signal(object)
    peer_removed = Signal(str)
    interaction_received = Signal(object)
    manual_probe_succeeded = Signal(object)
    presence_verified = Signal(object)
    candidate_probe_succeeded = Signal(object)
    peer_directory_received = Signal(object)
    codex_usage_sync_requested = Signal(object)
    codex_usage_sync_received = Signal(object)
    chat_message_added = Signal(object)
    chat_message_received = Signal(object)
    danger_alert_received = Signal(object)
    danger_alert_delivery_completed = Signal(object)
    pool_heartbeat_received = Signal(object)
    pool_frame_received = Signal(object)
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
        alert_group_joined: bool = False,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.device_id = device_id
        self.display_name = display_name
        self.pet_name = pet_name
        self.requested_port = port
        self._interface_provider = interface_provider or qt_interface_ipv4
        self._peer_registry = peer_registry
        self.alert_group_joined = bool(alert_group_joined)
        self._port = port
        self._running = False
        self._peers: dict[str, LanPeer] = {}
        self._peer_seen_at: dict[str, float] = {}
        self._interaction_times: dict[str, list[float]] = {}
        self._usage_sync_times: dict[str, list[float]] = {}
        self._chat_times: dict[tuple[str, str], list[float]] = {}
        self._chat_messages: list[LanChatMessage] = []
        self._chat_message_ids: set[str] = set()
        self._danger_alert_times: dict[str, list[float]] = {}
        self._seen_danger_alert_ids: dict[str, float] = {}
        self._pending_danger_alerts: dict[str, _PendingDangerAlert] = {}
        self._last_danger_alert_sent_at = float("-inf")
        self._danger_retry_ms = 300
        self._danger_completion_ms = 1_500
        self._manual_peer_targets: dict[str, tuple[str, int]] = {}
        self._manual_probe_target: tuple[str, int] | None = None
        self._manual_probe_expected_device_id: str | None = None
        self._saved_probe_targets: dict[tuple[str, int], str] = {}
        self._candidate_probe_targets: dict[str, _CandidateProbeTarget] = {}
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
        self._manual_probe_expected_device_id = None
        self._saved_probe_targets.clear()
        self._candidate_probe_targets.clear()
        self._running = False
        self._peers.clear()
        self._peer_seen_at.clear()
        self._interaction_times.clear()
        self._usage_sync_times.clear()
        self._chat_times.clear()
        self._danger_alert_times.clear()
        self._seen_danger_alert_ids.clear()
        self._pending_danger_alerts.clear()
        self.running_changed.emit(False)

    def update_identity(self, *, display_name: str, pet_name: str) -> None:
        self.display_name = display_name
        self.pet_name = pet_name
        if self._running:
            self.discover()

    def update_alert_group_membership(self, joined: bool) -> None:
        if not isinstance(joined, bool):
            raise ValueError("预警组加入状态无效")
        if self.alert_group_joined == joined:
            return
        self.alert_group_joined = joined
        if self._running:
            self.discover()
            self._refresh_manual_peers()

    def discover(self) -> None:
        if not self._running:
            return
        packet = LanPacketCodec.hello(
            device_id=self.device_id,
            display_name=self.display_name,
            pet_name=self.pet_name,
            port=self._port,
            alert_group_joined=self.alert_group_joined,
        )
        try:
            broadcasts = eligible_broadcast_addresses(self._interface_provider())
        except Exception:
            LOGGER.warning("无法枚举局域网接口广播地址", exc_info=True)
            broadcasts = ()
        for broadcast in dict.fromkeys((*broadcasts, "255.255.255.255")):
            self._send_packet(packet, QHostAddress(broadcast), self._port)

    def refresh_connections(self) -> None:
        """立即重新广播，并定向探测所有已保存伙伴。"""
        if not self._running:
            return
        self.discover()
        self._probe_saved_peers()

    def _refresh_manual_peers(self) -> None:
        """用定向 hello 续期手动添加的跨网段设备。"""
        if not self._running or not self._manual_peer_targets:
            return
        packet = LanPacketCodec.hello(
            device_id=self.device_id,
            display_name=self.display_name,
            pet_name=self.pet_name,
            port=self._port,
            alert_group_joined=self.alert_group_joined,
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
            alert_group_joined=self.alert_group_joined,
        )
        for saved_peer in saved_peers:
            target = (saved_peer.ip_address, saved_peer.port)
            self._manual_peer_targets[saved_peer.device_id] = target
            if self._send_packet(packet, QHostAddress(saved_peer.ip_address), saved_peer.port):
                self._saved_probe_targets[target] = saved_peer.device_id
        if self._saved_probe_targets:
            self._saved_probe_timer.start()

    def probe_peer(
        self,
        ip_address: str,
        port: int = LAN_INTERACTION_PORT,
        *,
        expected_device_id: str | None = None,
    ) -> bool:
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
        if expected_device_id is not None:
            expected_device_id = str(expected_device_id).strip()
            if (
                not expected_device_id
                or len(expected_device_id) > 64
                or any(char in expected_device_id for char in "\\/\r\n\x00")
            ):
                self.error.emit("预期设备 ID 无效")
                return False

        normalized_ip = str(parsed)
        packet = LanPacketCodec.hello(
            device_id=self.device_id,
            display_name=self.display_name,
            pet_name=self.pet_name,
            port=self._port,
            alert_group_joined=self.alert_group_joined,
        )
        self._manual_probe_target = (normalized_ip, port)
        self._manual_probe_expected_device_id = expected_device_id
        if not self._send_packet(packet, QHostAddress(normalized_ip), port):
            self._manual_probe_target = None
            self._manual_probe_expected_device_id = None
            return False
        self._manual_probe_timer.start()
        return True

    def probe_candidate(
        self,
        expected_device_id: str,
        ip_address: str,
        port: int = LAN_INTERACTION_PORT,
        *,
        token: str,
    ) -> bool:
        """Challenge one relayed endpoint without exposing it before verification."""
        if not self._running or token in self._candidate_probe_targets:
            return False
        try:
            endpoint = PeerEndpointRecord(expected_device_id, ip_address, port, 0)
            packet = LanPacketCodec.hello(
                device_id=self.device_id,
                display_name=self.display_name,
                pet_name=self.pet_name,
                port=self._port,
                alert_group_joined=self.alert_group_joined,
                probe_token=token,
            )
        except (LanProtocolError, TypeError, ValueError):
            return False
        target = _CandidateProbeTarget(
            endpoint.device_id,
            endpoint.ip_address,
            endpoint.port,
        )
        self._candidate_probe_targets[token] = target
        if not self._send_packet(packet, QHostAddress(target.ip_address), target.port):
            self._candidate_probe_targets.pop(token, None)
            return False
        return True

    def cancel_candidate_probe(self, token: str) -> None:
        self._candidate_probe_targets.pop(token, None)

    def send_direct_hello(
        self,
        ip_address: str,
        port: int = LAN_INTERACTION_PORT,
    ) -> bool:
        if not self._running:
            return False
        try:
            endpoint = PeerEndpointRecord("direct-target", ip_address, port, 0)
            packet = LanPacketCodec.hello(
                device_id=self.device_id,
                display_name=self.display_name,
                pet_name=self.pet_name,
                port=self._port,
                alert_group_joined=self.alert_group_joined,
            )
        except (LanProtocolError, TypeError, ValueError):
            return False
        return self._send_packet(packet, QHostAddress(endpoint.ip_address), endpoint.port)

    def update_saved_peer_address(
        self,
        device_id: str,
        ip_address: str,
        port: int = LAN_INTERACTION_PORT,
    ) -> bool:
        if device_id not in self._known_peers():
            self.error.emit("要更新地址的伙伴不存在")
            return False
        return self.probe_peer(ip_address, port, expected_device_id=device_id)

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

    def alert_group_peers(self) -> tuple[LanPeer, ...]:
        return tuple(
            sorted(
                (
                    peer
                    for peer in self._peers.values()
                    if peer.online
                    and peer.ip_address
                    and peer.port
                    and peer.alert_group_supported
                    and peer.alert_group_joined
                ),
                key=lambda item: item.display_name.casefold(),
            )
        )

    def send_danger_alert(self, message: str = "") -> bool:
        if not self._running:
            self.error.emit("局域网互动服务尚未启动")
            return False
        if not self.alert_group_joined:
            self.error.emit("请先加入局域网预警组")
            return False
        now = monotonic()
        if now - self._last_danger_alert_sent_at < 5.0:
            self.error.emit("预警发送过于频繁，请稍候")
            return False
        peers = self.alert_group_peers()
        if not peers:
            self.error.emit("预警组当前没有其他在线成员")
            return False
        alert_id = uuid.uuid4().hex
        created_at = int(time())
        endpoints = {peer.device_id: (str(peer.ip_address), int(peer.port or 0)) for peer in peers}
        packets = {
            peer.device_id: LanPacketCodec.danger_alert(
                DangerAlert(
                    alert_id,
                    self.device_id,
                    self.display_name,
                    peer.device_id,
                    created_at,
                    message,
                )
            )
            for peer in peers
        }
        pending = _PendingDangerAlert(tuple(endpoints), endpoints, packets, set())
        self._pending_danger_alerts[alert_id] = pending
        for device_id in pending.target_device_ids:
            host, port = pending.endpoints[device_id]
            self._send_packet(pending.packets[device_id], QHostAddress(host), port)
        self._last_danger_alert_sent_at = now
        QTimer.singleShot(self._danger_retry_ms, lambda: self._retry_danger_alert(alert_id))
        QTimer.singleShot(self._danger_completion_ms, lambda: self._complete_danger_alert(alert_id))
        return True

    def _retry_danger_alert(self, alert_id: str) -> None:
        pending = self._pending_danger_alerts.get(alert_id)
        if pending is None or not self._running:
            return
        for device_id in pending.target_device_ids:
            if device_id in pending.acknowledged:
                continue
            host, port = pending.endpoints[device_id]
            self._send_packet(pending.packets[device_id], QHostAddress(host), port)

    def _complete_danger_alert(self, alert_id: str) -> None:
        pending = self._pending_danger_alerts.pop(alert_id, None)
        if pending is None:
            return
        acknowledged = tuple(
            device_id for device_id in pending.target_device_ids if device_id in pending.acknowledged
        )
        self.danger_alert_delivery_completed.emit(
            DangerAlertDeliveryResult(alert_id, pending.target_device_ids, acknowledged)
        )

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
        if draft.scope in {ChatScope.LAN_ROOM, ChatScope.ALERT_GROUP}:
            peers = tuple(
                peer
                for peer in self._peers.values()
                if peer.ip_address and peer.port and peer.online
                and (
                    draft.scope is ChatScope.LAN_ROOM
                    or (peer.alert_group_supported and peer.alert_group_joined)
                )
            )
            if not peers:
                self.error.emit(
                    "预警组暂无其他在线成员"
                    if draft.scope is ChatScope.ALERT_GROUP
                    else "局域网群聊暂无其他在线设备"
                )
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

    def send_pool_heartbeat(
        self,
        packet: bytes,
        targets: Iterable[tuple[str, int]] = (),
    ) -> bool:
        if not self._running or not isinstance(packet, bytes) or not packet or len(packet) > MAX_POOL_UDP_BYTES:
            return False
        try:
            broadcasts = eligible_broadcast_addresses(self._interface_provider())
        except Exception:
            LOGGER.warning("无法枚举预警池心跳广播地址", exc_info=True)
            broadcasts = ()
        endpoints = {
            *((address, self._port) for address in broadcasts),
            ("255.255.255.255", self._port),
            *((str(address), int(port)) for address, port in targets),
            *((str(address), int(port)) for address, port in self._manual_peer_targets.values()),
        }
        results: list[bool] = []
        for address, port in sorted(endpoints):
            try:
                results.append(self._socket.writeDatagram(packet, QHostAddress(address), port) == len(packet))
            except (TypeError, ValueError):
                results.append(False)
        return any(results)

    def send_pool_frame(self, target_device_id: str, frame: bytes) -> bool:
        if (
            not isinstance(frame, bytes)
            or len(frame) < 5
            or len(frame) > MAX_POOL_FRAME_BYTES + 4
        ):
            return False
        return self._send_peer_frame(target_device_id, frame, report_errors=False)

    def send_peer_directory(self, target_device_id: str, frame: bytes) -> bool:
        if (
            not isinstance(frame, bytes)
            or len(frame) < 5
            or len(frame) > MAX_DIRECTORY_FRAME_BYTES + 4
        ):
            return False
        return self._send_peer_frame(target_device_id, frame, report_errors=False)

    def _send_peer_frame(
        self,
        target_device_id: str,
        frame: bytes,
        *,
        report_errors: bool,
    ) -> bool:
        peer = self._peers.get(str(target_device_id))
        if (
            not self._running
            or not self.chat_is_available
            or peer is None
            or not peer.online
            or not peer.ip_address
            or not peer.port
            or not isinstance(frame, bytes)
            or len(frame) < 5
            or len(frame) > MAX_LAN_FRAME_BYTES + 4
        ):
            return False
        self._start_frame_send(
            peer,
            frame,
            history_message=None,
            report_errors=report_errors,
        )
        return True

    def _start_chat_send(self, peer: LanPeer, frame: bytes, history_message: LanChatMessage) -> None:
        self._start_frame_send(
            peer,
            frame,
            history_message=history_message,
            report_errors=True,
        )

    def _start_frame_send(
        self,
        peer: LanPeer,
        frame: bytes,
        *,
        history_message: LanChatMessage | None,
        report_errors: bool,
    ) -> None:
        socket = QTcpSocket(self)
        self._outgoing_chat_sockets.add(socket)
        socket.connected.connect(
            lambda: self._write_frame(socket, frame, history_message, report_errors)
        )
        socket.disconnected.connect(lambda: self._cleanup_chat_socket(socket))
        socket.errorOccurred.connect(
            lambda _error: self._chat_socket_failed(socket, peer.display_name, report_errors)
        )
        timeout = QTimer(socket)
        timeout.setSingleShot(True)
        timeout.timeout.connect(
            lambda: self._chat_connect_timeout(socket, peer.display_name, report_errors)
        )
        timeout.start(5_000)
        socket.connectToHost(str(peer.ip_address), int(peer.port or 0))

    def _write_frame(
        self,
        socket: QTcpSocket,
        frame: bytes,
        message: LanChatMessage | None,
        report_errors: bool,
    ) -> None:
        if socket not in self._outgoing_chat_sockets:
            return
        written = socket.write(frame)
        if written != len(frame):
            if report_errors:
                self.error.emit(f"聊天消息发送失败：{socket.errorString()}")
            socket.abort()
            return
        if message is not None:
            self._remember_chat_message(message)
        socket.disconnectFromHost()

    def _chat_socket_failed(
        self,
        socket: QTcpSocket,
        peer_name: str,
        report_errors: bool,
    ) -> None:
        if socket not in self._outgoing_chat_sockets:
            return
        if report_errors:
            self.error.emit(f"无法发送给 {peer_name}：{socket.errorString()}")
        self._cleanup_chat_socket(socket)

    def _chat_connect_timeout(
        self,
        socket: QTcpSocket,
        peer_name: str,
        report_errors: bool,
    ) -> None:
        if socket not in self._outgoing_chat_sockets:
            return
        if report_errors:
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
            if payload_size <= 0 or payload_size > MAX_LAN_FRAME_BYTES:
                LOGGER.warning("拒绝超过安全大小的局域网帧")
                socket.abort()
                return
            if len(buffer) < 4 + payload_size:
                return
            payload = bytes(buffer[4 : 4 + payload_size])
            del buffer[: 4 + payload_size]
            frame = payload_size.to_bytes(4, "big") + payload
            try:
                directory = PeerDirectoryCodec.decode_frame(frame)
            except PeerDirectoryProtocolError:
                directory = None
            if directory is not None:
                if not self._trusted_frame_sender(directory.sender_device_id, socket):
                    LOGGER.warning("忽略来自未握手设备的伙伴目录帧")
                    socket.abort()
                    return
                self.peer_directory_received.emit(
                    ReceivedPeerDirectory(
                        directory,
                        socket.peerAddress().toString(),
                    )
                )
                continue
            try:
                pool_message = LanPoolPacketCodec.decode_frame(frame)
            except LanPoolProtocolError:
                pool_message = None
            if pool_message is not None:
                if not self._trusted_frame_sender(pool_message.sender_device_id, socket):
                    LOGGER.warning("忽略来自未握手设备的预警池名单帧")
                    socket.abort()
                    return
                sender = self._peers[pool_message.sender_device_id]
                self.pool_frame_received.emit(
                    ReceivedPoolMessage(
                        pool_message,
                        socket.peerAddress().toString(),
                        int(sender.port or 0),
                    )
                )
                continue
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

    def _trusted_frame_sender(self, sender_device_id: str, socket: QTcpSocket) -> bool:
        peer = self._peers.get(sender_device_id)
        return bool(
            peer is not None
            and peer.online
            and peer.ip_address
            and socket.peerAddress().toString() == peer.ip_address
        )

    def _allow_chat(self, message: LanChatMessage) -> bool:
        if message.scope is ChatScope.ALERT_GROUP:
            sender = self._peers.get(message.sender_device_id)
            if (
                not self.alert_group_joined
                or sender is None
                or not sender.alert_group_supported
                or not sender.alert_group_joined
            ):
                return False
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
            pool_heartbeat = LanPoolPacketCodec.decode_heartbeat(data)
        except LanPoolProtocolError:
            pool_heartbeat = None
        if pool_heartbeat is not None:
            if pool_heartbeat.sender_device_id == self.device_id:
                return
            self.pool_heartbeat_received.emit(
                ReceivedPoolMessage(
                    pool_heartbeat,
                    address.toString(),
                    int(source_port),
                )
            )
            return
        try:
            presence = LanPacketCodec.decode_presence(data)
        except LanProtocolError:
            presence = None
        if presence is not None:
            presence_address = (
                address if isinstance(address, QHostAddress) else QHostAddress(address)
            )
            probe_token = presence["probe_token"]
            host = presence_address.toString()
            candidate_challenge: tuple[str, _CandidateProbeTarget] | None = None
            if presence["kind"] == "hello_ack":
                candidate_challenges = tuple(
                    (active_token, target)
                    for active_token, target in self._candidate_probe_targets.items()
                    if host == target.ip_address
                )
                candidate_challenge = next(
                    (
                        challenge
                        for challenge in candidate_challenges
                        if challenge[1].device_id == str(presence["device_id"])
                    ),
                    candidate_challenges[0] if candidate_challenges else None,
                )
            if candidate_challenge is not None:
                expected_token, target = candidate_challenge
                if (
                    probe_token != expected_token
                    or str(presence["device_id"]) != target.device_id
                    or int(source_port) != target.port
                    or int(presence["port"]) != target.port
                ):
                    return
                if self._reject_unexpected_probe_identity(
                    presence, presence_address, source_port
                ):
                    return
                peer = self._handle_presence(presence, presence_address)
                if peer is None:
                    return
                self._candidate_probe_targets.pop(expected_token, None)
                context = VerifiedPresenceContext(
                    peer=peer,
                    address=host,
                    source_port=int(source_port),
                    extensions=tuple(presence["extensions"]),
                    probe_token=str(probe_token),
                    assisted=True,
                )
                self.presence_verified.emit(context)
                self.candidate_probe_succeeded.emit(context)
                return
            if presence["kind"] == "hello_ack" and probe_token is not None:
                return
            if self._reject_unexpected_probe_identity(
                presence, presence_address, source_port
            ):
                return
            peer = self._handle_presence(presence, presence_address)
            if peer is not None:
                self._complete_manual_probe(peer, source_port)
                self._complete_saved_probe(peer, source_port)
                self.presence_verified.emit(
                    VerifiedPresenceContext(
                        peer=peer,
                        address=presence_address.toString(),
                        source_port=int(source_port),
                        extensions=tuple(presence["extensions"]),
                        probe_token=str(probe_token) if probe_token is not None else None,
                        assisted=False,
                    )
                )
            if presence["kind"] == "hello" and self._running and self._port > 0:
                packet = LanPacketCodec.hello_ack(
                    device_id=self.device_id,
                    display_name=self.display_name,
                    pet_name=self.pet_name,
                    port=self._port,
                    alert_group_joined=self.alert_group_joined,
                    probe_token=str(probe_token) if probe_token is not None else None,
                )
                self._send_packet(packet, presence_address, int(presence["port"]))
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
        try:
            alert = LanPacketCodec.decode_danger_alert(
                data,
                local_device_id=self.device_id,
                now=int(time()),
            )
        except LanProtocolError:
            alert = None
        if alert is not None:
            self._handle_danger_alert(alert, address, source_port)
            return
        try:
            ack = LanPacketCodec.decode_danger_alert_ack(data, local_device_id=self.device_id)
        except LanProtocolError:
            ack = None
        if ack is not None:
            self._handle_danger_alert_ack(ack, address, source_port)
            return
        received = LanPacketCodec.decode_interaction(data, local_device_id=self.device_id)
        if not self._allow_interaction(received):
            return
        self.interaction_received.emit(received)

    def _handle_danger_alert(self, alert: DangerAlert, address: QHostAddress, source_port: int) -> None:
        peer = self._peers.get(alert.sender_device_id)
        if (
            not self.alert_group_joined
            or peer is None
            or not peer.ip_address
            or not peer.port
            or address.toString() != peer.ip_address
            or int(source_port) != int(peer.port)
            or not peer.alert_group_supported
            or not peer.alert_group_joined
        ):
            return
        if alert.alert_id in self._seen_danger_alert_ids:
            self._send_danger_alert_ack(alert, address, source_port)
            return
        now = monotonic()
        recent = [stamp for stamp in self._danger_alert_times.get(alert.sender_device_id, []) if now - stamp < 60]
        if len(recent) >= 3:
            self._danger_alert_times[alert.sender_device_id] = recent
            LOGGER.warning("忽略过于频繁的危险预警：%s", alert.sender_device_id)
            return
        recent.append(now)
        self._danger_alert_times[alert.sender_device_id] = recent
        self._seen_danger_alert_ids = {
            alert_id: stamp for alert_id, stamp in self._seen_danger_alert_ids.items() if now - stamp < 60
        }
        self._seen_danger_alert_ids[alert.alert_id] = now
        while len(self._seen_danger_alert_ids) > 256:
            self._seen_danger_alert_ids.pop(next(iter(self._seen_danger_alert_ids)))
        self._send_danger_alert_ack(alert, address, source_port)
        self.danger_alert_received.emit(alert)

    def _send_danger_alert_ack(self, alert: DangerAlert, address: QHostAddress, source_port: int) -> None:
        ack = DangerAlertAck(alert.alert_id, self.device_id, alert.sender_device_id)
        self._send_packet(LanPacketCodec.danger_alert_ack(ack), address, int(source_port))

    def _handle_danger_alert_ack(
        self,
        ack: DangerAlertAck,
        address: QHostAddress,
        source_port: int,
    ) -> None:
        pending = self._pending_danger_alerts.get(ack.alert_id)
        if pending is None or ack.sender_device_id not in pending.endpoints:
            return
        host, port = pending.endpoints[ack.sender_device_id]
        if address.toString() != host or int(source_port) != port:
            return
        pending.acknowledged.add(ack.sender_device_id)

    def _handle_presence(self, presence: dict[str, object], address: QHostAddress) -> LanPeer | None:
        device_id = str(presence["device_id"])
        if device_id == self.device_id:
            return
        address = address if isinstance(address, QHostAddress) else QHostAddress(address)
        host = address.toString()
        port = int(presence["port"])
        known_peers = self._known_peers()
        is_saved = device_id in known_peers
        duplicate_ids = tuple(
            peer_id
            for peer_id, existing_peer in self._peers.items()
            if peer_id != device_id
            and peer_id not in known_peers
            and peer_id not in self._manual_peer_targets
            and existing_peer.ip_address == host
            and existing_peer.port == port
        )
        for duplicate_id in duplicate_ids:
            self._peers.pop(duplicate_id, None)
            self._peer_seen_at.pop(duplicate_id, None)
            self._interaction_times.pop(duplicate_id, None)
            self._usage_sync_times.pop(duplicate_id, None)
            self.peer_removed.emit(duplicate_id)
        peer = LanPeer(
            device_id=device_id,
            display_name=str(presence["display_name"]),
            pet_name=str(presence["pet_name"]),
            ip_address=host,
            port=port,
            online=True,
            saved=is_saved,
            connection_state="online",
            alert_group_supported=bool(presence["alert_group_supported"]),
            alert_group_joined=bool(presence["alert_group_joined"]),
        )
        previous = self._peers.get(device_id)
        self._peers[device_id] = peer
        self._peer_seen_at[device_id] = monotonic()
        if is_saved:
            self._save_verified_peer(peer)
        if device_id in self._manual_peer_targets:
            self._manual_peer_targets[device_id] = (host, port)
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
        self._manual_probe_expected_device_id = None
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
        advertised_port = int(presence["port"])
        expected_device_id = self._saved_probe_targets.get((host, int(source_port)))
        if expected_device_id is not None and expected_device_id != device_id:
            self.error.emit("已保存伙伴身份不匹配，已拒绝此次重连")
            return True
        target = self._manual_probe_target
        if target is not None and target[0] == host:
            if int(source_port) != target[1] or int(presence["port"]) != target[1]:
                return True
            expected = self._manual_probe_expected_device_id
            if expected is not None and device_id != expected:
                self._manual_probe_target = None
                self._manual_probe_expected_device_id = None
                self._manual_probe_timer.stop()
                self.error.emit("伙伴身份不匹配，已拒绝更新地址")
                return True
        if target is None or target[0] != host:
            if (
                self._peer_registry is not None
                and not self._peer_registry.matches_expected_identity(
                    host,
                    advertised_port,
                    device_id,
                )
            ):
                self.error.emit("已保存伙伴身份不匹配，已拒绝此次重连")
                return True
            return False
        if self._peer_registry is None or self._peer_registry.matches_expected_identity(
            host,
            advertised_port,
            device_id,
        ):
            return False
        self._manual_probe_target = None
        self._manual_probe_expected_device_id = None
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
        self._manual_probe_expected_device_id = None
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
