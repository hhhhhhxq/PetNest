"""Mutual Codex usage synchronization over a manually connected LAN peer."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication
import pytest

from petnest.core.codex_usage import (
    AccountTokenSummary,
    CodexAccount,
    CodexDeviceUsageSnapshot,
    CodexDeviceUsageStore,
    CodexModelUsage,
    CodexRateLimit,
    CodexRateWindow,
    CodexTokenUsage,
    CodexUsageReport,
    LocalCodexUsage,
)
from petnest.core.codex_usage_sync import CodexUsageSyncCoordinator
from petnest.core.lan_interaction import LanPacketCodec, LanProtocolError
from petnest.core.lan_service import LanInteractionService
from petnest.models.lan_interaction import LanPeer


def _report(tmp_path, *, total_tokens: int, reset: datetime) -> CodexUsageReport:
    window = CodexRateWindow(4, 10_080, reset)
    limit = CodexRateLimit(
        limit_id="codex",
        limit_name="Codex",
        plan_type="pro",
        primary=window,
        secondary=None,
        credit_balance=None,
        has_credits=False,
        unlimited_credits=False,
    )
    return CodexUsageReport(
        account=CodexAccount("a" * 24, "us*****@example.com", "pro"),
        rate_limits=(limit,),
        primary_limit=limit,
        account_tokens=AccountTokenSummary(),
        daily_usage=(),
        local_usage=LocalCodexUsage(
            tokens=CodexTokenUsage(
                input_tokens=total_tokens - 100,
                output_tokens=100,
                total_tokens=total_tokens,
                requests=2,
            ),
            model_usage=(CodexModelUsage("gpt-5.6-sol", uses=2, total_tokens=total_tokens),),
            fast_uses=1,
            standard_uses=1,
        ),
        fetched_at=datetime.now(UTC),
        codex_home=tmp_path,
    )


def test_sync_packet_round_trip_keeps_only_validated_numeric_snapshot() -> None:
    snapshot = CodexDeviceUsageSnapshot(
        account_key="a" * 24,
        device_id="sender",
        device_label="MacBook",
        window_resets_at=2_000_000_000,
        window_duration_minutes=10_080,
        updated_at=datetime.now(UTC).replace(microsecond=0).isoformat(),
        input_tokens=900,
        cached_input_tokens=400,
        cache_write_input_tokens=0,
        output_tokens=100,
        reasoning_output_tokens=0,
        total_tokens=1_000,
        requests=2,
        model_usage=(CodexModelUsage("gpt-5.6-sol", uses=2, total_tokens=1_000),),
        account_label="us*****@example.com",
        plan_type="pro",
        account_used_percent=12.5,
        fast_uses=7,
        standard_uses=3,
        files_scanned=12,
        files_skipped=1,
        scan_status="matched",
        weighted_credits=1.25,
        weighted_complete=True,
        pending_tokens=250,
        anomaly_tokens=1_000,
    )
    packet = LanPacketCodec.codex_usage_sync(
        kind="codex_usage_sync_request",
        request_id="request-1",
        target_device_id="receiver",
        snapshot=snapshot,
    )

    decoded = LanPacketCodec.decode_codex_usage_sync(
        LanPacketCodec.encode(packet),
        local_device_id="receiver",
    )

    assert decoded.request_id == "request-1"
    assert decoded.snapshot == snapshot

    packet["usage"]["total_tokens"] = -1
    with pytest.raises(LanProtocolError, match="Token"):
        LanPacketCodec.decode_codex_usage_sync(
            LanPacketCodec.encode(packet),
            local_device_id="receiver",
        )
    packet["usage"]["total_tokens"] = 1_000
    packet["usage"]["scan_status"] = "invented"
    with pytest.raises(LanProtocolError, match="扫描状态"):
        LanPacketCodec.decode_codex_usage_sync(
            LanPacketCodec.encode(packet),
            local_device_id="receiver",
        )


def test_first_discovered_lan_peer_triggers_sync_once(qtbot, tmp_path, monkeypatch) -> None:
    service = LanInteractionService(
        device_id="local-device",
        display_name="Local Mac",
        pet_name="Pet",
        port=0,
    )
    coordinator = CodexUsageSyncCoordinator(
        service,
        CodexDeviceUsageStore(tmp_path / "devices.json"),
        device_label=lambda: "Local Mac",
        auto_sync_discovered=True,
    )
    started: list[tuple[str, object]] = []
    monkeypatch.setattr(
        coordinator,
        "_start_fetch",
        lambda action, context: started.append((action, context)),
    )
    peer = LanPeer("peer-device", "Office PC", "Pet", "192.168.1.20", 18_487)

    service.peer_changed.emit(peer)
    service.peer_changed.emit(peer)

    assert started == [("initiate", ("peer-device",))]
    assert coordinator._periodic_timer.isActive()
    coordinator.stop()


def test_periodic_check_observes_account_without_lan_peers(qtbot, tmp_path, monkeypatch) -> None:
    service = LanInteractionService(
        device_id="local-device",
        display_name="Local Mac",
        pet_name="Pet",
        port=0,
    )
    coordinator = CodexUsageSyncCoordinator(
        service,
        CodexDeviceUsageStore(tmp_path / "devices.json"),
        device_label=lambda: "Local Mac",
    )
    started: list[tuple[str, object]] = []
    monkeypatch.setattr(
        coordinator,
        "_start_fetch",
        lambda action, context: started.append((action, context)),
    )

    coordinator.sync_now()

    assert started == [("observe", ())]
    assert coordinator._periodic_timer.isActive()
    coordinator.stop()



def test_manual_ip_connection_mutually_syncs_same_account_device_totals(qtbot, tmp_path) -> None:
    app = QCoreApplication.instance() or QCoreApplication([])
    del app
    reset = (datetime.now(UTC) + timedelta(days=6)).replace(microsecond=0)
    first_report = _report(tmp_path / "first-home", total_tokens=1_000, reset=reset)
    second_report = _report(tmp_path / "second-home", total_tokens=2_000, reset=reset)

    class FirstClient:
        def fetch_report(self) -> CodexUsageReport:
            return first_report

    class SecondClient:
        def fetch_report(self) -> CodexUsageReport:
            return second_report

    first_service = LanInteractionService(
        device_id="first-device",
        display_name="First Mac",
        pet_name="Pet",
        port=0,
    )
    second_service = LanInteractionService(
        device_id="second-device",
        display_name="Second PC",
        pet_name="Pet",
        port=0,
    )
    first_store = CodexDeviceUsageStore(tmp_path / "first-devices.json")
    second_store = CodexDeviceUsageStore(tmp_path / "second-devices.json")
    first_sync = CodexUsageSyncCoordinator(
        first_service,
        first_store,
        device_label=lambda: "First Mac",
        client_factory=FirstClient,  # type: ignore[arg-type]
    )
    second_sync = CodexUsageSyncCoordinator(
        second_service,
        second_store,
        device_label=lambda: "Second PC",
        client_factory=SecondClient,  # type: ignore[arg-type]
    )
    assert first_service.start()
    assert second_service.start()

    assert first_service.probe_peer("127.0.0.1", second_service.port)
    qtbot.waitUntil(
        lambda: bool(first_store.load()) and bool(second_store.load()),
        timeout=5_000,
    )

    first_remote = first_store.load(
        account_key="a" * 24,
        window_resets_at=int(reset.timestamp()),
    )
    second_remote = second_store.load(
        account_key="a" * 24,
        window_resets_at=int(reset.timestamp()),
    )
    assert [(item.device_id, item.total_tokens) for item in first_remote] == [
        ("second-device", 2_000)
    ]
    assert [(item.device_id, item.total_tokens) for item in second_remote] == [
        ("first-device", 1_000)
    ]
    reopened = CodexDeviceUsageStore(tmp_path / "first-devices.json")
    assert reopened.load()[0].device_id == "second-device"

    first_sync.stop()
    second_sync.stop()
    first_service.stop()
    second_service.stop()


def test_lan_peers_exchange_different_accounts_without_merging_them(qtbot, tmp_path) -> None:
    app = QCoreApplication.instance() or QCoreApplication([])
    del app
    reset = (datetime.now(UTC) + timedelta(days=6)).replace(microsecond=0)
    first_report = _report(tmp_path / "first-home", total_tokens=1_000, reset=reset)
    second_report = replace(
        _report(tmp_path / "second-home", total_tokens=2_000, reset=reset),
        account=CodexAccount("b" * 24, "ot*****@example.com", "pro"),
    )

    class FirstClient:
        def fetch_report(self) -> CodexUsageReport:
            return first_report

    class SecondClient:
        def fetch_report(self) -> CodexUsageReport:
            return second_report

    first_service = LanInteractionService(
        device_id="first-device",
        display_name="First Mac",
        pet_name="Pet",
        port=0,
    )
    second_service = LanInteractionService(
        device_id="second-device",
        display_name="Second PC",
        pet_name="Pet",
        port=0,
    )
    first_store = CodexDeviceUsageStore(tmp_path / "first-devices.json")
    second_store = CodexDeviceUsageStore(tmp_path / "second-devices.json")
    first_sync = CodexUsageSyncCoordinator(
        first_service,
        first_store,
        device_label=lambda: "First Mac",
        client_factory=FirstClient,  # type: ignore[arg-type]
    )
    second_sync = CodexUsageSyncCoordinator(
        second_service,
        second_store,
        device_label=lambda: "Second PC",
        client_factory=SecondClient,  # type: ignore[arg-type]
    )
    assert first_service.start()
    assert second_service.start()

    assert first_service.probe_peer("127.0.0.1", second_service.port)
    qtbot.waitUntil(
        lambda: bool(first_store.load(account_key="b" * 24))
        and bool(second_store.load(account_key="a" * 24)),
        timeout=5_000,
    )

    assert first_store.load(account_key="a" * 24) == ()
    assert second_store.load(account_key="b" * 24) == ()
    assert first_store.load(account_key="b" * 24)[0].device_id == "second-device"
    assert first_store.load(account_key="b" * 24)[0].account_label == "ot*****@example.com"
    assert first_store.load(account_key="b" * 24)[0].account_used_percent == 4
    assert second_store.load(account_key="a" * 24)[0].device_id == "first-device"

    first_sync.stop()
    second_sync.stop()
    first_service.stop()
    second_service.stop()
