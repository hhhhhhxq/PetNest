"""Ownerless anti-entropy synchronization for the fixed LAN alert pool."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from time import monotonic

from PySide6.QtCore import QObject, QTimer, Signal

from petnest.core.lan_pool_protocol import (
    POOL_ID,
    LanPoolPacketCodec,
    PoolHeartbeat,
    PoolRecords,
    PoolSummary,
)
from petnest.core.lan_pool_roster import PoolRosterStore
from petnest.models.lan_pool import PoolMemberRecord, PoolMemberState, PoolMemberView


class LanPoolSyncService(QObject):
    roster_changed = Signal()
    sync_status_changed = Signal(str)

    def __init__(
        self,
        lan_service: object,
        roster: PoolRosterStore,
        *,
        display_name: Callable[[], str],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.lan_service = lan_service
        self.roster = roster
        self.display_name = display_name
        self._online_seen_at: dict[str, float] = {}
        self._verification_queue: deque[tuple[str, str, int]] = deque()
        self._verification_queued_ids: set[str] = set()
        self._active_verification: tuple[str, str, int] | None = None
        self._sync_cursor = 0
        self._running = False
        self._periodic_timer = QTimer(self)
        self._periodic_timer.setInterval(30_000)
        self._periodic_timer.timeout.connect(self.sync_reachable_peers)
        self._verification_timeout = QTimer(self)
        self._verification_timeout.setSingleShot(True)
        self._verification_timeout.setInterval(4_500)
        self._verification_timeout.timeout.connect(self._expire_active_verification)
        if hasattr(lan_service, "pool_heartbeat_received"):
            lan_service.pool_heartbeat_received.connect(self._on_heartbeat_context)
        if hasattr(lan_service, "pool_frame_received"):
            lan_service.pool_frame_received.connect(self._on_frame_context)
        if hasattr(lan_service, "manual_probe_succeeded"):
            lan_service.manual_probe_succeeded.connect(self._on_probe_succeeded)
        if hasattr(lan_service, "peer_changed"):
            lan_service.peer_changed.connect(self._on_peer_changed)

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._periodic_timer.start()
        self.broadcast_heartbeat()
        self.sync_reachable_peers()

    def stop(self) -> None:
        self._running = False
        self._periodic_timer.stop()
        self._verification_timeout.stop()
        self._verification_queue.clear()
        self._verification_queued_ids.clear()
        self._active_verification = None

    def summary(self) -> PoolSummary:
        return PoolSummary(
            self.roster.local_device_id,
            tuple(self.roster.revisions().items()),
        )

    def send_summary(self, target_device_id: str) -> bool:
        return bool(
            self.lan_service.send_pool_frame(
                target_device_id,
                LanPoolPacketCodec.encode_summary(self.summary()),
            )
        )

    def send_records(self, target_device_id: str, records: tuple[PoolMemberRecord, ...]) -> bool:
        if not records:
            return True
        message = PoolRecords(self.roster.local_device_id, records)
        return bool(
            self.lan_service.send_pool_frame(
                target_device_id,
                LanPoolPacketCodec.encode_records(message),
            )
        )

    def receive_frame(self, sender_device_id: str, message: PoolSummary | PoolRecords) -> None:
        if isinstance(message, PoolSummary):
            self.receive_summary(sender_device_id, message)
        elif isinstance(message, PoolRecords):
            self.receive_records(sender_device_id, message)

    def receive_summary(self, sender_device_id: str, summary: PoolSummary) -> None:
        if summary.sender_device_id != sender_device_id or sender_device_id == self.roster.local_device_id:
            return
        remote = dict(summary.revisions)
        local_records = self.roster.records()
        newer_here = tuple(
            record
            for device_id, record in sorted(local_records.items())
            if remote.get(device_id, 0) < record.revision
        )
        remote_has_newer = any(
            local_records.get(device_id) is None
            or revision > local_records[device_id].revision
            for device_id, revision in remote.items()
        )
        if newer_here:
            self.send_records(sender_device_id, newer_here)
        if remote_has_newer:
            self.send_summary(sender_device_id)

    def receive_records(self, sender_device_id: str, records: PoolRecords) -> None:
        if records.sender_device_id != sender_device_id or sender_device_id == self.roster.local_device_id:
            return
        result = self.roster.merge(
            records.records,
            directly_verified_ids={sender_device_id},
        )
        if result.local_newer_device_ids:
            local = self.roster.records()
            self.send_records(
                sender_device_id,
                tuple(local[device_id] for device_id in result.local_newer_device_ids),
            )
        if result.changed_device_ids:
            changed = self.roster.records()
            for device_id in result.changed_device_ids:
                record = changed[device_id]
                if (
                    device_id != sender_device_id
                    and device_id != self.roster.local_device_id
                    and record.state is PoolMemberState.JOINED
                ):
                    self._queue_verification(record)
            self.roster_changed.emit()
            self.broadcast_heartbeat()
            self.sync_reachable_peers()

    def set_local_joined(
        self,
        joined: bool,
        *,
        ip_address: str,
        port: int,
    ) -> PoolMemberRecord:
        record = self.roster.update_local(
            display_name=self.display_name(),
            state=PoolMemberState.JOINED if joined else PoolMemberState.LEFT,
            ip_address=ip_address,
            port=port,
        )
        self.broadcast_heartbeat()
        self.sync_reachable_peers()
        self.roster_changed.emit()
        return record

    def broadcast_heartbeat(self) -> bool:
        local = self.roster.records().get(self.roster.local_device_id)
        if local is None:
            return False
        heartbeat = PoolHeartbeat(
            POOL_ID,
            self.roster.local_device_id,
            local,
            self.roster.digest(),
            len(self.roster.records()),
        )
        targets = tuple(
            (record.ip_address, record.port)
            for device_id, record in self.roster.records().items()
            if device_id != self.roster.local_device_id and record.state is PoolMemberState.JOINED
        )
        return bool(
            self.lan_service.send_pool_heartbeat(
                LanPoolPacketCodec.encode_heartbeat(heartbeat),
                targets,
            )
        )

    def sync_reachable_peers(self) -> None:
        peers = tuple(
            sorted(
                (
                    peer
                    for peer in tuple(getattr(self.lan_service, "peers", lambda: ())())
                    if getattr(peer, "online", False)
                ),
                key=lambda item: item.device_id,
            )
        )
        if not peers:
            self._sync_cursor = 0
            return
        count = min(3, len(peers))
        start = self._sync_cursor % len(peers)
        selected = tuple(peers[(start + offset) % len(peers)] for offset in range(count))
        self._sync_cursor = (start + count) % len(peers)
        for peer in selected:
            self.send_summary(peer.device_id)

    def member_views(self) -> tuple[PoolMemberView, ...]:
        now = monotonic()
        peers = {
            peer.device_id: peer
            for peer in tuple(getattr(self.lan_service, "peers", lambda: ())())
        }
        views: list[PoolMemberView] = []
        for device_id, record in sorted(self.roster.records().items(), key=lambda item: item[1].display_name.casefold()):
            if record.state is not PoolMemberState.JOINED:
                continue
            peer = peers.get(device_id)
            online = (
                peer is not None and getattr(peer, "online", False)
            ) or now - self._online_seen_at.get(device_id, float("-inf")) < 12
            verified = peer is not None and bool(getattr(peer, "online", False))
            reachable = verified and bool(getattr(peer, "ip_address", None) and getattr(peer, "port", None))
            views.append(PoolMemberView(device_id, record.display_name, True, online, verified, reachable))
        return tuple(views)

    def _on_heartbeat_context(self, context: object) -> None:
        heartbeat = getattr(context, "message", None)
        if not isinstance(heartbeat, PoolHeartbeat):
            return
        sender = heartbeat.sender_device_id
        self._online_seen_at[sender] = monotonic()
        address = str(getattr(context, "address", ""))
        source_port = int(getattr(context, "source_port", 0) or 0)
        direct = (
            heartbeat.sender_record.ip_address == address
            and heartbeat.sender_record.port == source_port
        )
        result = self.roster.merge(
            (heartbeat.sender_record,),
            directly_verified_ids={sender} if direct else frozenset(),
        )
        if result.changed_device_ids:
            self.roster_changed.emit()
            self.sync_reachable_peers()
        if heartbeat.roster_digest != self.roster.digest():
            self.send_summary(sender)

    def _on_frame_context(self, context: object) -> None:
        message = getattr(context, "message", None)
        sender = getattr(message, "sender_device_id", "")
        if sender:
            self.receive_frame(str(sender), message)

    def _queue_verification(self, record: PoolMemberRecord) -> None:
        if record.device_id in self._verification_queued_ids:
            return
        self._verification_queue.append((record.device_id, record.ip_address, record.port))
        self._verification_queued_ids.add(record.device_id)
        self._pump_verification_queue()

    def _pump_verification_queue(self) -> None:
        if self._active_verification is not None or not self._verification_queue:
            return
        candidate = self._verification_queue.popleft()
        device_id, address, port = candidate
        self._active_verification = candidate
        started = self.lan_service.probe_peer(
            address,
            port,
            expected_device_id=device_id,
        )
        if not started:
            self._active_verification = None
            self._verification_queued_ids.discard(device_id)
            self._pump_verification_queue()
            return
        self._verification_timeout.start()

    def _on_probe_succeeded(self, peer: object) -> None:
        active = self._active_verification
        if active is None or getattr(peer, "device_id", None) != active[0]:
            return
        self._active_verification = None
        self._verification_timeout.stop()
        self._verification_queued_ids.discard(active[0])
        self._pump_verification_queue()

    def _on_peer_changed(self, peer: object) -> None:
        device_id = str(getattr(peer, "device_id", ""))
        if not self._running or not device_id or not getattr(peer, "online", False):
            return
        self._online_seen_at[device_id] = monotonic()
        self.send_summary(device_id)

    def _expire_active_verification(self) -> None:
        candidate = self._active_verification
        if candidate is None:
            return
        self._active_verification = None
        self._verification_queued_ids.discard(candidate[0])
        self._pump_verification_queue()
