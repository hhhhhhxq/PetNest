from __future__ import annotations

from collections import deque
from threading import Event
from time import monotonic

from PySide6.QtWidgets import QApplication

from petnest.core.lan_firewall_advisor import LanFirewallAdvisorCoordinator
from petnest.core.windows_lan_firewall import FirewallRepairResult, LanFirewallStatus


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _wait_until(predicate, timeout: float = 2.0) -> None:
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        QApplication.processEvents()
        if predicate():
            return
    raise AssertionError("condition was not reached")


class FakeBackend:
    def __init__(self, statuses: list[LanFirewallStatus]) -> None:
        self.statuses = deque(statuses)
        self.inspect_calls = 0
        self.repair_calls = 0

    def inspect(self) -> LanFirewallStatus:
        self.inspect_calls += 1
        return self.statuses.popleft()

    def repair(self) -> FirewallRepairResult:
        self.repair_calls += 1
        return FirewallRepairResult(True, "updated")


def test_disabled_coordinator_does_not_inspect() -> None:
    _app()
    backend = FakeBackend([LanFirewallStatus(applicable=True)])
    coordinator = LanFirewallAdvisorCoordinator(backend, startup_delay_ms=0)

    coordinator.start(enabled=False)
    QApplication.processEvents()

    assert backend.inspect_calls == 0
    assert coordinator.status == LanFirewallStatus()
    coordinator.stop()


def test_startup_check_publishes_status() -> None:
    _app()
    expected = LanFirewallStatus(
        applicable=True,
        public_network_active=True,
        public_network_key="key",
        firewall_enabled=True,
        tcp_allowed=False,
        udp_allowed=True,
    )
    backend = FakeBackend([expected])
    coordinator = LanFirewallAdvisorCoordinator(backend, startup_delay_ms=0, poll_interval_ms=5)
    received: list[LanFirewallStatus] = []
    coordinator.status_changed.connect(received.append)

    coordinator.start(enabled=True)
    _wait_until(lambda: received == [expected])

    assert backend.inspect_calls == 1
    coordinator.stop()


def test_successful_repair_is_rechecked_before_completion() -> None:
    _app()
    warning = LanFirewallStatus(
        applicable=True,
        public_network_active=True,
        public_network_key="key",
        firewall_enabled=True,
        tcp_allowed=False,
        udp_allowed=True,
        can_repair=True,
    )
    fixed = LanFirewallStatus(
        applicable=True,
        public_network_active=True,
        public_network_key="key",
        firewall_enabled=True,
        tcp_allowed=True,
        udp_allowed=True,
        can_repair=True,
    )
    backend = FakeBackend([warning, fixed])
    coordinator = LanFirewallAdvisorCoordinator(backend, startup_delay_ms=0, poll_interval_ms=5)
    repairs: list[tuple[bool, str]] = []
    coordinator.repair_finished.connect(lambda ok, message: repairs.append((ok, message)))
    coordinator.start(enabled=True)
    _wait_until(lambda: coordinator.status == warning)

    coordinator.request_repair()
    _wait_until(lambda: coordinator.status == fixed and bool(repairs))

    assert backend.repair_calls == 1
    assert backend.inspect_calls == 2
    assert repairs[-1][0] is True
    coordinator.stop()


def test_network_changes_are_debounced_into_one_check() -> None:
    _app()
    backend = FakeBackend([LanFirewallStatus(applicable=True)])
    coordinator = LanFirewallAdvisorCoordinator(
        backend,
        startup_delay_ms=60_000,
        debounce_delay_ms=10,
        poll_interval_ms=5,
    )
    coordinator.start(enabled=True)

    coordinator.notify_network_changed()
    coordinator.notify_network_changed()
    coordinator.notify_network_changed()
    _wait_until(lambda: backend.inspect_calls == 1)

    assert backend.inspect_calls == 1
    coordinator.stop()


def test_pre_repair_inspection_cannot_complete_post_repair_verification() -> None:
    _app()
    warning = LanFirewallStatus(
        applicable=True,
        public_network_active=True,
        firewall_enabled=True,
        udp_allowed=False,
        tcp_allowed=True,
        can_repair=True,
    )
    fixed = LanFirewallStatus(
        applicable=True,
        public_network_active=True,
        firewall_enabled=True,
        udp_allowed=True,
        tcp_allowed=True,
        can_repair=True,
    )
    old_started = Event()
    release_old = Event()

    class RacingBackend:
        inspect_calls = 0

        def inspect(self) -> LanFirewallStatus:
            self.inspect_calls += 1
            if self.inspect_calls == 1:
                old_started.set()
                release_old.wait(2)
                return warning
            return fixed

        def repair(self) -> FirewallRepairResult:
            return FirewallRepairResult(True, "updated")

    backend = RacingBackend()
    coordinator = LanFirewallAdvisorCoordinator(backend, startup_delay_ms=60_000, poll_interval_ms=5)
    repairs: list[tuple[bool, str]] = []
    coordinator.repair_finished.connect(lambda ok, message: repairs.append((ok, message)))
    coordinator.start(enabled=True)
    coordinator.request_check()
    assert old_started.wait(1)

    coordinator.request_repair()
    _wait_until(lambda: coordinator._repair_recheck_message is not None)
    release_old.set()
    _wait_until(lambda: coordinator.status == fixed and bool(repairs))

    assert repairs == [(True, "updated")]
    assert backend.inspect_calls == 2
    coordinator.stop()


def test_queued_pre_repair_result_cannot_complete_post_repair_verification() -> None:
    _app()
    warning = LanFirewallStatus(
        applicable=True,
        public_network_active=True,
        firewall_enabled=True,
        udp_allowed=False,
        tcp_allowed=True,
        can_repair=True,
    )
    fixed = LanFirewallStatus(
        applicable=True,
        public_network_active=True,
        firewall_enabled=True,
        udp_allowed=True,
        tcp_allowed=True,
        can_repair=True,
    )
    release_old = Event()
    old_finished = Event()

    class QueuedBackend:
        inspect_calls = 0

        def inspect(self) -> LanFirewallStatus:
            self.inspect_calls += 1
            if self.inspect_calls == 1:
                release_old.wait(2)
                old_finished.set()
                return warning
            return fixed

        def repair(self) -> FirewallRepairResult:
            return FirewallRepairResult(True, "updated")

    backend = QueuedBackend()
    coordinator = LanFirewallAdvisorCoordinator(backend, startup_delay_ms=60_000, poll_interval_ms=5)
    repairs: list[tuple[bool, str]] = []
    coordinator.repair_finished.connect(lambda ok, message: repairs.append((ok, message)))
    coordinator.start(enabled=True)
    coordinator._poll_timer.stop()
    coordinator.request_check()
    assert coordinator.request_repair() is True
    _wait_until(lambda: coordinator._results.qsize() == 1)
    release_old.set()
    assert old_finished.wait(1)
    _wait_until(lambda: coordinator._inspect_worker is not None and not coordinator._inspect_worker.is_alive())

    coordinator._drain_results()
    _wait_until(lambda: coordinator.status == fixed and repairs == [(True, "updated")])

    assert backend.inspect_calls == 2
    coordinator.stop()


def test_repair_request_reports_rejection_while_previous_uac_is_still_running() -> None:
    _app()
    release_repair = Event()
    repair_started = Event()

    class BlockingRepairBackend:
        def inspect(self) -> LanFirewallStatus:
            return LanFirewallStatus()

        def repair(self) -> FirewallRepairResult:
            repair_started.set()
            release_repair.wait(2)
            return FirewallRepairResult(False, "cancelled", cancelled=True)

    coordinator = LanFirewallAdvisorCoordinator(
        BlockingRepairBackend(), startup_delay_ms=60_000, poll_interval_ms=5
    )
    coordinator.start(enabled=True)

    assert coordinator.request_repair() is True
    assert repair_started.wait(1)
    coordinator.set_enabled(False)
    coordinator.set_enabled(True)
    assert coordinator.request_repair() is False

    release_repair.set()
    _wait_until(lambda: coordinator._repair_worker is not None and not coordinator._repair_worker.is_alive())
    assert coordinator.request_repair() is True
    coordinator.stop()


def test_reenable_runs_check_after_old_generation_inspection_finishes() -> None:
    _app()
    old_started = Event()
    release_old = Event()
    current = LanFirewallStatus(applicable=True, public_network_key="current")

    class BlockingInspectBackend:
        inspect_calls = 0

        def inspect(self) -> LanFirewallStatus:
            self.inspect_calls += 1
            if self.inspect_calls == 1:
                old_started.set()
                release_old.wait(2)
                return LanFirewallStatus(applicable=True, public_network_key="old")
            return current

        def repair(self) -> FirewallRepairResult:
            return FirewallRepairResult(False, "unused")

    backend = BlockingInspectBackend()
    coordinator = LanFirewallAdvisorCoordinator(
        backend, startup_delay_ms=60_000, poll_interval_ms=5
    )
    coordinator.start(enabled=True)
    coordinator.request_check()
    assert old_started.wait(1)

    coordinator.set_enabled(False)
    coordinator._startup_delay_ms = 0
    coordinator.set_enabled(True)
    _wait_until(lambda: coordinator._pending_check)
    release_old.set()
    _wait_until(lambda: coordinator.status == current)

    assert backend.inspect_calls == 2
    coordinator.stop()
