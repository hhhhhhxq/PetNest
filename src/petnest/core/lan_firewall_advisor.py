"""在后台检查 Windows 公用网络防火墙状态。"""

from __future__ import annotations

from queue import Empty, Queue
from threading import Thread

from PySide6.QtCore import QObject, QTimer, Signal

from .windows_lan_firewall import FirewallRepairResult, LanFirewallStatus


class LanFirewallAdvisorCoordinator(QObject):
    status_changed = Signal(object)
    repair_finished = Signal(bool, str)

    def __init__(
        self,
        backend,
        *,
        startup_delay_ms: int = 5_000,
        debounce_delay_ms: int = 1_000,
        poll_interval_ms: int = 100,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._backend = backend
        self._startup_delay_ms = max(0, startup_delay_ms)
        self._enabled = False
        self._stopped = False
        self._generation = 0
        self._status = LanFirewallStatus()
        self._results: Queue[tuple[str, int, object]] = Queue()
        self._inspect_worker: Thread | None = None
        self._next_inspect_id = 0
        self._active_inspect_id: int | None = None
        self._repair_worker: Thread | None = None
        self._pending_check = False
        self._repair_recheck_message: str | None = None
        self._repair_min_inspect_id: int | None = None

        self._startup_timer = QTimer(self)
        self._startup_timer.setSingleShot(True)
        self._startup_timer.timeout.connect(self.request_check)
        self._network_timer = QTimer(self)
        self._network_timer.setSingleShot(True)
        self._network_timer.setInterval(max(1, debounce_delay_ms))
        self._network_timer.timeout.connect(self.request_check)
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(max(1, poll_interval_ms))
        self._poll_timer.timeout.connect(self._drain_results)
        self._connect_network_information()

    @property
    def status(self) -> LanFirewallStatus:
        return self._status

    def start(self, *, enabled: bool) -> None:
        self._stopped = False
        self._poll_timer.start()
        self.set_enabled(enabled)

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)
        self._startup_timer.stop()
        if not self._enabled:
            self._generation += 1
            self._pending_check = False
            self._repair_recheck_message = None
            self._repair_min_inspect_id = None
            self._status = LanFirewallStatus()
            self.status_changed.emit(self._status)
            return
        self._startup_timer.start(self._startup_delay_ms)

    def request_check(self) -> None:
        if self._stopped or not self._enabled:
            return
        if self._inspect_worker is not None and self._inspect_worker.is_alive():
            self._pending_check = True
            return
        generation = self._generation
        self._next_inspect_id += 1
        inspect_id = self._next_inspect_id
        self._active_inspect_id = inspect_id

        def inspect() -> None:
            self._results.put(("inspect", generation, (inspect_id, self._backend.inspect())))

        self._inspect_worker = Thread(target=inspect, name="lan-firewall-inspect", daemon=True)
        self._inspect_worker.start()

    def notify_network_changed(self, *_args: object) -> None:
        if not self._stopped and self._enabled:
            self._network_timer.start()

    def request_repair(self) -> bool:
        if self._stopped or not self._enabled:
            return False
        if self._repair_worker is not None and self._repair_worker.is_alive():
            return False
        generation = self._generation

        def repair() -> None:
            self._results.put(("repair", generation, self._backend.repair()))

        self._repair_worker = Thread(target=repair, name="lan-firewall-repair", daemon=True)
        self._repair_worker.start()
        return True

    def stop(self) -> None:
        self._stopped = True
        self._enabled = False
        self._generation += 1
        self._startup_timer.stop()
        self._network_timer.stop()
        self._poll_timer.stop()
        self._pending_check = False
        self._repair_recheck_message = None
        self._repair_min_inspect_id = None

    def _drain_results(self) -> None:
        while True:
            try:
                kind, generation, payload = self._results.get_nowait()
            except Empty:
                return
            if generation != self._generation or self._stopped:
                if (
                    kind == "inspect"
                    and isinstance(payload, tuple)
                    and len(payload) == 2
                    and isinstance(payload[0], int)
                    and payload[0] == self._active_inspect_id
                ):
                    self._inspect_worker = None
                    self._active_inspect_id = None
                    if not self._stopped and self._enabled and self._pending_check:
                        self._pending_check = False
                        self.request_check()
                continue
            if (
                kind == "inspect"
                and isinstance(payload, tuple)
                and len(payload) == 2
                and isinstance(payload[0], int)
                and isinstance(payload[1], LanFirewallStatus)
            ):
                inspect_id, status = payload
                if inspect_id == self._active_inspect_id:
                    self._inspect_worker = None
                    self._active_inspect_id = None
                is_stale_for_repair = (
                    self._repair_min_inspect_id is not None
                    and inspect_id < self._repair_min_inspect_id
                )
                if is_stale_for_repair:
                    if self._pending_check:
                        self._pending_check = False
                        self.request_check()
                    continue
                self._status = status
                self.status_changed.emit(status)
                is_post_repair_verification = (
                    self._repair_recheck_message is not None
                    and self._repair_min_inspect_id is not None
                    and inspect_id >= self._repair_min_inspect_id
                )
                if is_post_repair_verification:
                    verified = status.udp_allowed and status.tcp_allowed and not status.requires_attention
                    message = self._repair_recheck_message
                    self._repair_recheck_message = None
                    self._repair_min_inspect_id = None
                    self.repair_finished.emit(
                        verified,
                        message if verified else "规则仍未完整生效，请重试或检查系统策略。",
                    )
                if self._pending_check:
                    self._pending_check = False
                    self.request_check()
            elif kind == "repair" and isinstance(payload, FirewallRepairResult):
                self._repair_worker = None
                if not payload.succeeded:
                    self.repair_finished.emit(False, payload.message)
                    self.request_check()
                else:
                    self._repair_recheck_message = payload.message
                    self._repair_min_inspect_id = self._next_inspect_id + 1
                    self.request_check()

    def _connect_network_information(self) -> None:
        try:
            from PySide6.QtNetwork import QNetworkInformation

            QNetworkInformation.loadDefaultBackend()
            information = QNetworkInformation.instance()
            if information is None:
                return
            information.reachabilityChanged.connect(self.notify_network_changed)
            information.transportMediumChanged.connect(self.notify_network_changed)
        except (AttributeError, RuntimeError):
            return
