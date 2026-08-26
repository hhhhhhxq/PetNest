"""Qt orchestration for verified peer-assisted LAN discovery."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from secrets import token_hex
from time import monotonic

from PySide6.QtCore import QObject, QTimer

from petnest.core.lan_discovery import InterfaceIPv4
from petnest.core.lan_peer_discovery_protocol import (
    MAX_DIRECTORY_RECORDS,
    PeerDirectory,
    PeerDirectoryCodec,
)
from petnest.core.lan_peer_discovery_state import (
    CandidateKey,
    CandidateQueue,
    DirectEndpointBook,
)

MAX_PENDING_PROBES = 8
MAX_PROBE_STARTS_PER_SECOND = 4
MAX_PROBE_STARTS_PER_MINUTE = 60
MAX_PROBE_STARTS_PER_REFERRER_MINUTE = 20
PROBE_TIMEOUT_SECONDS = 4.0
DIRECTORY_TARGETS_PER_ROUND = 3
RENEWALS_PER_ROUND = 16


class LanPeerDiscoverySyncService(QObject):
    def __init__(
        self,
        lan_service: object,
        *,
        local_device_id: str,
        clock: Callable[[], float] = monotonic,
        token_factory: Callable[[], str] = lambda: token_hex(16),
        interface_provider: Callable[[], tuple[InterfaceIPv4, ...]] = lambda: (),
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.lan_service = lan_service
        self.local_device_id = local_device_id
        self._clock = clock
        self._token_factory = token_factory
        self._interface_provider = interface_provider
        self.endpoint_book = DirectEndpointBook(local_device_id=local_device_id)
        self.candidates = CandidateQueue(local_device_id=local_device_id)
        self._pending: dict[str, tuple[CandidateKey, float]] = {}
        self._sync_cursor = 0
        self._renew_cursor = 0
        self._start_attempts: deque[float] = deque()
        self._global_attempts: deque[float] = deque()
        self._referrer_attempts: dict[str, deque[float]] = {}
        self._running = False

        self._pump_timer = QTimer(self)
        self._pump_timer.setInterval(250)
        self._pump_timer.timeout.connect(self.pump_candidates)
        self._pending_timer = QTimer(self)
        self._pending_timer.setInterval(250)
        self._pending_timer.timeout.connect(self.expire_pending)
        self._sync_timer = QTimer(self)
        self._sync_timer.setInterval(30_000)
        self._sync_timer.timeout.connect(self.sync_reachable_peers)
        self._renew_timer = QTimer(self)
        self._renew_timer.setInterval(8_000)
        self._renew_timer.timeout.connect(self.renew_assisted_peers)
        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(500)
        self._debounce_timer.timeout.connect(self.sync_reachable_peers)

        lan_service.presence_verified.connect(self._on_presence_verified)
        lan_service.candidate_probe_succeeded.connect(self._on_candidate_probe_succeeded)
        lan_service.peer_directory_received.connect(self._on_peer_directory_received)
        lan_service.peer_changed.connect(self._on_peer_changed)
        lan_service.peer_removed.connect(self._on_peer_removed)

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._pump_timer.start()
        self._pending_timer.start()
        self._sync_timer.start()
        self._renew_timer.start()

    def stop(self) -> None:
        self._running = False
        for timer in self.timers():
            timer.stop()
        for token in tuple(self._pending):
            self.lan_service.cancel_candidate_probe(token)
        self._pending.clear()
        self.candidates.clear()
        self.endpoint_book.clear()
        self._start_attempts.clear()
        self._global_attempts.clear()
        self._referrer_attempts.clear()
        self._sync_cursor = 0
        self._renew_cursor = 0

    def timers(self) -> tuple[QTimer, ...]:
        return (
            self._pump_timer,
            self._pending_timer,
            self._sync_timer,
            self._renew_timer,
            self._debounce_timer,
        )

    def pending_tokens(self) -> tuple[str, ...]:
        return tuple(self._pending)

    def offer_candidate(
        self,
        device_id: str,
        ip_address: str,
        port: int,
        *,
        referrer_device_id: str,
    ) -> bool:
        if not self._running:
            return False
        try:
            key = CandidateKey(device_id, ip_address, port)
        except (TypeError, ValueError):
            return False
        if key.ip_address in self._local_and_broadcast_addresses():
            return False
        return self.candidates.offer(
            key,
            referrer_device_id,
            self._clock(),
            already_verified=self.endpoint_book.contains(key),
        )

    def receive_directory(
        self,
        referrer_device_id: str,
        directory: PeerDirectory,
    ) -> None:
        if (
            not self._running
            or not isinstance(directory, PeerDirectory)
            or directory.sender_device_id != referrer_device_id
        ):
            return
        for record in directory.records:
            if record.device_id in {self.local_device_id, referrer_device_id}:
                continue
            self.offer_candidate(
                record.device_id,
                record.ip_address,
                record.port,
                referrer_device_id=referrer_device_id,
            )

    def sync_reachable_peers(self) -> None:
        if not self._running:
            return
        now = self._clock()
        self.endpoint_book.expire(now=now)
        supported_devices = {
            endpoint.key.device_id
            for endpoint in self.endpoint_book.endpoints()
            if "peer_directory_v1" in endpoint.extensions
        }
        peers = tuple(
            sorted(
                (
                    peer
                    for peer in self.lan_service.peers()
                    if peer.device_id != self.local_device_id
                    and peer.online
                    and peer.ip_address
                    and peer.port
                    and peer.device_id in supported_devices
                ),
                key=lambda peer: peer.device_id,
            )
        )
        if not peers:
            self._sync_cursor = 0
            return
        count = min(DIRECTORY_TARGETS_PER_ROUND, len(peers))
        start = self._sync_cursor % len(peers)
        targets = tuple(peers[(start + offset) % len(peers)] for offset in range(count))
        self._sync_cursor = (start + count) % len(peers)
        shareable = self.endpoint_book.shareable_records(now=now)
        for target in targets:
            records = tuple(
                record
                for record in shareable
                if record.device_id not in {self.local_device_id, target.device_id}
            )[:MAX_DIRECTORY_RECORDS]
            frame = PeerDirectoryCodec.encode_frame(
                PeerDirectory(self.local_device_id, records)
            )
            self.lan_service.send_peer_directory(target.device_id, frame)

    def pump_candidates(self) -> None:
        if not self._running or len(self._pending) >= MAX_PENDING_PROBES:
            return
        now = self._clock()
        self._trim_attempt_windows(now)
        if (
            len(self._start_attempts) >= MAX_PROBE_STARTS_PER_SECOND
            or len(self._global_attempts) >= MAX_PROBE_STARTS_PER_MINUTE
        ):
            return
        blocked_referrers = frozenset(
            referrer
            for referrer, attempts in self._referrer_attempts.items()
            if len(attempts) >= MAX_PROBE_STARTS_PER_REFERRER_MINUTE
        )
        selected = self.candidates.take_ready(
            now=now,
            limit=1,
            blocked_referrers=blocked_referrers,
        )
        if not selected:
            return
        key = selected[0]
        referrer = self.candidates.referrer(key)
        if referrer is None:
            self.candidates.mark_failed(key, now=now)
            return
        referrer_attempts = self._referrer_attempts.setdefault(referrer, deque())
        token = self._next_unique_token()
        self._start_attempts.append(now)
        self._global_attempts.append(now)
        referrer_attempts.append(now)
        if not self.lan_service.probe_candidate(
            key.device_id,
            key.ip_address,
            key.port,
            token=token,
        ):
            self.candidates.mark_failed(key, now=now)
            return
        self._pending[token] = (key, now)

    def expire_pending(self) -> None:
        if not self._running:
            return
        now = self._clock()
        expired = tuple(
            (token, key)
            for token, (key, started_at) in self._pending.items()
            if now - started_at >= PROBE_TIMEOUT_SECONDS
        )
        for token, key in expired:
            self._pending.pop(token, None)
            self.lan_service.cancel_candidate_probe(token)
            self.candidates.mark_failed(key, now=now)

    def renew_assisted_peers(self) -> None:
        if not self._running:
            return
        now = self._clock()
        self.endpoint_book.expire(now=now)
        keys = self.endpoint_book.assisted_keys(now=now)
        if not keys:
            self._renew_cursor = 0
            return
        count = min(RENEWALS_PER_ROUND, len(keys))
        start = self._renew_cursor % len(keys)
        selected = tuple(keys[(start + offset) % len(keys)] for offset in range(count))
        self._renew_cursor = (start + count) % len(keys)
        for key in selected:
            self.lan_service.send_direct_hello(key.ip_address, key.port)

    def _next_unique_token(self) -> str:
        for _attempt in range(16):
            token = self._token_factory()
            if token not in self._pending:
                return token
        return self._token_factory()

    def _trim_attempt_windows(self, now: float) -> None:
        while self._start_attempts and now - self._start_attempts[0] >= 1.0:
            self._start_attempts.popleft()
        while self._global_attempts and now - self._global_attempts[0] >= 60.0:
            self._global_attempts.popleft()
        for referrer, attempts in tuple(self._referrer_attempts.items()):
            while attempts and now - attempts[0] >= 60.0:
                attempts.popleft()
            if not attempts:
                self._referrer_attempts.pop(referrer, None)

    def _on_presence_verified(self, received: object) -> None:
        if not self._running or bool(getattr(received, "assisted", False)):
            return
        peer = getattr(received, "peer", None)
        if peer is None:
            return
        address = str(getattr(received, "address", ""))
        source_port = int(getattr(received, "source_port", 0))
        if address != str(peer.ip_address) or source_port != int(peer.port or 0):
            return
        try:
            endpoint = self.endpoint_book.observe(
                peer.device_id,
                address,
                source_port,
                tuple(getattr(received, "extensions", ())),
                self._clock(),
                False,
            )
        except (TypeError, ValueError):
            return
        for token, (key, _started_at) in tuple(self._pending.items()):
            if key == endpoint.key:
                self._pending.pop(token, None)
                self.lan_service.cancel_candidate_probe(token)
        self.candidates.mark_verified(endpoint.key)
        self._schedule_directory_sync()

    def _on_candidate_probe_succeeded(self, received: object) -> None:
        if not self._running:
            return
        token = getattr(received, "probe_token", None)
        if not isinstance(token, str):
            return
        pending = self._pending.get(token)
        peer = getattr(received, "peer", None)
        if pending is None or peer is None:
            return
        key, _started_at = pending
        if (
            not bool(getattr(received, "assisted", False))
            or peer.device_id != key.device_id
            or str(getattr(received, "address", "")) != key.ip_address
            or int(getattr(received, "source_port", 0)) != key.port
            or int(peer.port or 0) != key.port
        ):
            return
        self._pending.pop(token, None)
        self.candidates.mark_verified(key)
        try:
            self.endpoint_book.observe(
                key.device_id,
                key.ip_address,
                key.port,
                tuple(getattr(received, "extensions", ())),
                self._clock(),
                True,
            )
        except (TypeError, ValueError):
            return
        self._schedule_directory_sync()

    def _on_peer_directory_received(self, received: object) -> None:
        message = getattr(received, "message", None)
        if isinstance(message, PeerDirectory):
            self.receive_directory(message.sender_device_id, message)

    def _on_peer_changed(self, _peer: object) -> None:
        self._schedule_directory_sync()

    def _on_peer_removed(self, _device_id: str) -> None:
        self._schedule_directory_sync()

    def _schedule_directory_sync(self) -> None:
        if self._running:
            self._debounce_timer.start()

    def _local_and_broadcast_addresses(self) -> frozenset[str]:
        try:
            interfaces = tuple(self._interface_provider())
        except (OSError, RuntimeError, TypeError):
            return frozenset()
        return frozenset(
            address
            for interface in interfaces
            if interface.is_up and interface.is_running and not interface.is_loopback
            for address in (interface.address, interface.broadcast)
            if address
        )
