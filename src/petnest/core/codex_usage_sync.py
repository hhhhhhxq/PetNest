"""Direct-LAN synchronization of per-device Codex token contributions."""

from __future__ import annotations

from dataclasses import dataclass
from queue import Empty, Queue
from threading import Thread
from time import monotonic
from typing import Callable
import uuid

from PySide6.QtCore import QObject, QTimer, Signal

from petnest.core.codex_usage import (
    CodexDeviceUsageSnapshot,
    CodexDeviceUsageStore,
    CodexUsageClient,
    CodexUsageReport,
)
from petnest.core.lan_interaction import ReceivedCodexUsageSync
from petnest.core.lan_service import LanInteractionService
from petnest.models.lan_interaction import LanPeer


ClientFactory = Callable[[], CodexUsageClient]
DeviceLabelFactory = Callable[[], str]


@dataclass(frozen=True, slots=True)
class _PendingRequest:
    peer_id: str
    account_key: str
    window_resets_at: int
    deadline: float


class CodexUsageSyncCoordinator(QObject):
    """Fetch local usage off-thread and exchange direct device snapshots."""

    status_changed = Signal(str)
    snapshots_changed = Signal(str)

    def __init__(
        self,
        service: LanInteractionService,
        store: CodexDeviceUsageStore,
        *,
        device_label: DeviceLabelFactory,
        client_factory: ClientFactory = CodexUsageClient,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.store = store
        self._device_label = device_label
        self._client_factory = client_factory
        self._trusted_peer_ids: set[str] = set()
        self._workers: set[Thread] = set()
        self._results: Queue[tuple[str, object, object]] = Queue()
        self._pending: dict[str, _PendingRequest] = {}
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(100)
        self._poll_timer.timeout.connect(self._drain_results)
        self._poll_timer.start()
        self._periodic_timer = QTimer(self)
        self._periodic_timer.setInterval(5 * 60 * 1000)
        self._periodic_timer.timeout.connect(self.sync_now)

        service.manual_probe_succeeded.connect(self._manual_peer_connected)
        service.peer_removed.connect(self._peer_removed)
        service.codex_usage_sync_requested.connect(self._sync_requested)
        service.codex_usage_sync_received.connect(self._sync_received)

    def stop(self) -> None:
        self._poll_timer.stop()
        self._periodic_timer.stop()
        self._trusted_peer_ids.clear()
        self._pending.clear()

    def sync_now(self) -> None:
        peer_ids = tuple(
            peer_id
            for peer_id in self._trusted_peer_ids
            if any(peer.device_id == peer_id for peer in self.service.peers())
        )
        if peer_ids:
            self._start_fetch("initiate", peer_ids)

    def sync_report(self, report: CodexUsageReport) -> None:
        """Reuse a report already fetched by the usage dialog."""
        peer_ids = tuple(
            peer_id
            for peer_id in self._trusted_peer_ids
            if any(peer.device_id == peer_id for peer in self.service.peers())
        )
        if peer_ids:
            self._send_report(report, peer_ids)

    def _manual_peer_connected(self, peer: LanPeer) -> None:
        self._trusted_peer_ids.add(peer.device_id)
        if not self._periodic_timer.isActive():
            self._periodic_timer.start()
        self.status_changed.emit(f"已连接 {peer.display_name}，正在同步 Codex 用量…")
        self._start_fetch("initiate", (peer.device_id,))

    def _peer_removed(self, device_id: str) -> None:
        self._trusted_peer_ids.discard(device_id)
        if not self._trusted_peer_ids:
            self._periodic_timer.stop()

    def _sync_requested(self, received: ReceivedCodexUsageSync) -> None:
        self._start_fetch("respond", received)

    def _sync_received(self, received: ReceivedCodexUsageSync) -> None:
        pending = self._pending.pop(received.request_id, None)
        snapshot = received.snapshot
        if pending is None:
            return
        if (
            snapshot.device_id != pending.peer_id
            or snapshot.account_key != pending.account_key
            or abs(snapshot.window_resets_at - pending.window_resets_at) > 10
        ):
            self.status_changed.emit("已忽略账号或额度周期不匹配的同步结果")
            return
        try:
            self.store.save(snapshot)
        except (OSError, ValueError) as error:
            self.status_changed.emit(f"无法保存 Codex 同步结果：{error}")
            return
        self.snapshots_changed.emit(snapshot.account_key)
        self.status_changed.emit(f"已与 {snapshot.device_label} 同步 Codex 用量")

    def _start_fetch(self, action: str, context: object) -> None:
        self._workers = {worker for worker in self._workers if worker.is_alive()}
        if len(self._workers) >= 4:
            self.status_changed.emit("Codex 用量同步请求较多，将在下次刷新时重试")
            return
        worker = Thread(
            target=self._fetch_worker,
            args=(action, context),
            daemon=True,
            name="petnest-codex-lan-sync",
        )
        self._workers.add(worker)
        worker.start()

    def _fetch_worker(self, action: str, context: object) -> None:
        try:
            report: object = self._client_factory().fetch_report()
        except Exception as error:  # noqa: BLE001 - delivered safely to the Qt thread.
            report = error
        self._results.put((action, context, report))

    def _drain_results(self) -> None:
        self._workers = {worker for worker in self._workers if worker.is_alive()}
        now = monotonic()
        expired = [request_id for request_id, item in self._pending.items() if item.deadline <= now]
        for request_id in expired:
            self._pending.pop(request_id, None)
        if expired:
            self.status_changed.emit("对方未返回相同 Codex 账号和额度周期的用量")
        while True:
            try:
                action, context, result = self._results.get_nowait()
            except Empty:
                return
            if not isinstance(result, CodexUsageReport):
                message = str(result) or result.__class__.__name__
                self.status_changed.emit(f"Codex 用量同步失败：{message}")
                continue
            if action == "respond" and isinstance(context, ReceivedCodexUsageSync):
                self._respond_with_report(result, context)
                continue
            if action == "initiate" and isinstance(context, tuple):
                self._send_report(result, tuple(str(item) for item in context))

    def _send_report(self, report: CodexUsageReport, peer_ids: tuple[str, ...]) -> None:
        try:
            snapshot = CodexDeviceUsageSnapshot.from_report(
                report,
                device_id=self.service.device_id,
                device_label=self._device_label(),
            )
        except ValueError as error:
            self.status_changed.emit(f"Codex 用量同步失败：{error}")
            return
        for peer_id in peer_ids:
            request_id = uuid.uuid4().hex
            self._pending[request_id] = _PendingRequest(
                peer_id=peer_id,
                account_key=snapshot.account_key,
                window_resets_at=snapshot.window_resets_at,
                deadline=monotonic() + 6,
            )
            if not self.service.send_codex_usage_sync(
                target_device_id=peer_id,
                request_id=request_id,
                snapshot=snapshot,
            ):
                self._pending.pop(request_id, None)

    def _respond_with_report(
        self,
        report: CodexUsageReport,
        received: ReceivedCodexUsageSync,
    ) -> None:
        incoming = received.snapshot
        window = report.primary_limit.primary
        if (
            window is None
            or window.resets_at is None
            or report.account.key != incoming.account_key
            or abs(int(window.resets_at.timestamp()) - incoming.window_resets_at) > 10
        ):
            self.status_changed.emit(
                f"{incoming.device_label} 请求同步，但两台电脑的 Codex 账号或额度周期不同"
            )
            return
        try:
            self.store.save(incoming)
            local = CodexDeviceUsageSnapshot.from_report(
                report,
                device_id=self.service.device_id,
                device_label=self._device_label(),
            )
        except (OSError, ValueError) as error:
            self.status_changed.emit(f"Codex 用量同步失败：{error}")
            return
        self._trusted_peer_ids.add(incoming.device_id)
        if not self._periodic_timer.isActive():
            self._periodic_timer.start()
        self.snapshots_changed.emit(incoming.account_key)
        if self.service.send_codex_usage_sync(
            target_device_id=incoming.device_id,
            request_id=received.request_id,
            snapshot=local,
            response=True,
        ):
            self.status_changed.emit(f"已与 {incoming.device_label} 互换 Codex 用量")


__all__ = ["CodexUsageSyncCoordinator"]
