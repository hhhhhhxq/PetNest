"""Qt presentation for the Codex account usage report."""

from __future__ import annotations

from dataclasses import asdict, replace
from datetime import UTC, date, datetime, timedelta
import json
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QMessageBox, QProgressBar

from petnest.core.codex_usage import (
    CODEX_USAGE_WEIGHT_VERSION,
    AccountTokenSummary,
    CodexAccount,
    CodexDeviceUsageSnapshot,
    CodexDeviceUsageStore,
    CodexModelUsage,
    CodexReasoningUsage,
    CodexManualAttributionStore,
    CodexRateLimit,
    CodexRateLimitResetAvailability,
    CodexRateLimitResetCredit,
    CodexRateWindow,
    CodexTokenUsage,
    CodexUsageReport,
    CodexUsageHistoryStore,
    DailyTokenUsage,
    LocalCodexUsage,
    codex_device_usage_path,
    codex_manual_attribution_path,
)
from petnest.ui.codex_usage_dialog import CodexUsageDialog


def test_usage_dialog_is_a_movable_non_modal_window(tmp_path, qtbot) -> None:
    dialog = CodexUsageDialog(tmp_path / "usage.json", auto_refresh=False)
    qtbot.addWidget(dialog)

    assert dialog.windowType() is Qt.WindowType.Window
    assert dialog.windowModality() is Qt.WindowModality.NonModal
    assert not dialog.isModal()
    assert dialog.windowFlags() & Qt.WindowType.WindowTitleHint
    assert dialog.claim_pending_button.text() == "补登到当前账号"
    assert "combobox-popup: 0;" in dialog.styleSheet()


def _report(tmp_path: Path) -> CodexUsageReport:
    window = CodexRateWindow(
        used_percent=4,
        window_duration_minutes=10_080,
        resets_at=datetime.now(UTC) + timedelta(days=6),
    )
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
        account=CodexAccount("a" * 24, "pe*****@example.com", "pro"),
        rate_limits=(limit,),
        primary_limit=limit,
        account_tokens=AccountTokenSummary(lifetime_tokens=9_000_000, current_streak_days=3),
        daily_usage=(DailyTokenUsage(date.today(), 123_456),),
        local_usage=LocalCodexUsage(
            tokens=CodexTokenUsage(
                input_tokens=1_000,
                cached_input_tokens=300,
                output_tokens=200,
                total_tokens=1_500,
                requests=1,
            ),
            model_usage=(
                CodexModelUsage(
                    "gpt-5.6-sol",
                    uses=1,
                    total_tokens=1_500,
                    input_tokens=1_000,
                    cached_input_tokens=300,
                    output_tokens=200,
                    weighted_credits=0.24125,
                ),
            ),
            reasoning_usage=(
                CodexReasoningUsage("high", uses=3),
                CodexReasoningUsage("medium", uses=1),
            ),
            weighted_credits=0.24125,
            weighted_complete=True,
            pending_tokens=CodexTokenUsage(total_tokens=250, requests=1),
            anomaly_tokens=CodexTokenUsage(total_tokens=1_500, requests=1),
            fast_uses=3,
            standard_uses=1,
            observed_start_used_percent=1.5,
            observed_end_used_percent=4,
        ),
        fetched_at=datetime.now(UTC),
        codex_home=tmp_path,
        rate_limit_reset_credits=CodexRateLimitResetAvailability(
            available_count=1,
            credits=(
                CodexRateLimitResetCredit(
                    credit_id="RateLimitResetCredit_1",
                    reset_type="codexRateLimits",
                    status="available",
                    expires_at=datetime.now(UTC) + timedelta(days=30),
                    title="Full reset",
                ),
            ),
        ),
    )


def test_account_token_warning_does_not_hide_quota_or_local_tokens(qtbot, tmp_path) -> None:
    dialog = CodexUsageDialog(tmp_path / "history.json", auto_refresh=False)
    qtbot.addWidget(dialog)
    report = _report(tmp_path)
    warning = "账号累计 Token 暂时无法读取"
    dialog._show_report(replace(report, account_tokens=AccountTokenSummary(), daily_usage=(), account_tokens_warning=warning))
    assert dialog.account_lifetime_label.text() == "累计  —"
    assert dialog.account_recent_label.text() == warning
    assert dialog.local_total_label.text() == "Token  1,500"
    assert dialog.findChildren(QLabel, "quotaRemainingLabel")[0].text() == "剩余 96%"
    dialog._show_report(report)
    assert warning not in dialog.account_recent_label.text()
    assert dialog.account_lifetime_label.text() == "累计  9,000,000"


def test_replacing_quota_rows_hides_previous_values_immediately(qtbot, tmp_path) -> None:
    dialog = CodexUsageDialog(tmp_path / "history.json", auto_refresh=False)
    qtbot.addWidget(dialog)
    dialog.show()
    report = _report(tmp_path)
    dialog._show_report(report)
    previous = dialog.quota_rows.itemAt(0).widget()
    assert previous is not None
    qtbot.waitUntil(lambda: not previous.isHidden(), timeout=2_000)

    new_limit = replace(report.primary_limit, primary=replace(report.primary_limit.primary, used_percent=20))
    dialog._show_report(replace(report, rate_limits=(new_limit,), primary_limit=new_limit))

    assert previous.isHidden()
    current = dialog.quota_rows.itemAt(0).widget()
    assert current is not None
    assert current.findChild(QLabel, "quotaRemainingLabel").text() == "剩余 80%"


def test_dialog_refreshes_quota_tokens_and_account_selector(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    report = _report(tmp_path)

    class FakeClient:
        def fetch_report(self) -> CodexUsageReport:
            return report

    dialog = CodexUsageDialog(
        tmp_path / "history.json",
        client_factory=FakeClient,  # type: ignore[arg-type]
        auto_refresh=False,
    )
    qtbot.addWidget(dialog)

    dialog.refresh_usage()
    qtbot.waitUntil(lambda: dialog.refresh_button.isEnabled(), timeout=2_000)

    progress_bars = dialog.findChildren(QProgressBar)
    quota_progress = next(item for item in progress_bars if item.maximum() == 100)
    assert "96%" in quota_progress.format()
    remaining_labels = dialog.findChildren(QLabel, "quotaRemainingLabel")
    assert [item.text() for item in remaining_labels] == ["剩余 96%"]
    assert dialog.account_selector.currentData() == "a" * 24
    assert "pe*****@example.com" in dialog.current_account_label.text()
    assert dialog.account_lifetime_label.text() == "累计  9,000,000"
    assert dialog.local_total_label.text() == "Token  1,500"
    assert dialog.local_weighted_label.text() == "加权 0.2413（参考权重）"
    assert "待归属 250 Token" in dialog.local_attribution_label.text()
    assert "标签异常 1,500 Token" in dialog.local_attribution_label.text()
    assert dialog.local_speed_label.text() == "速度占比  极快 75% · 标准 25%"
    assert dialog.local_reasoning_label.text() == "推理强度  高 75% · 中 25%"
    assert "+2.5" in dialog.local_quota_change_label.text()
    assert "已更新" in dialog.status_label.text()
    assert dialog.reset_status_card.property("resetState") == "available"
    assert dialog.reset_status_badge.text() == "可用 1 次"
    assert "完全重置" in dialog.reset_status_detail_label.text()
    assert "Codex 官方客户端" in dialog.reset_status_detail_label.text()
    assert not hasattr(dialog, "reset_action_button")


def test_history_archiving_runs_off_the_ui_thread(qtbot, tmp_path, monkeypatch) -> None:
    from threading import get_ident

    report = _report(tmp_path)
    class FakeClient:
        def fetch_report(self):
            return report

    dialog = CodexUsageDialog(tmp_path / "history.json", client_factory=FakeClient, auto_refresh=False)
    qtbot.addWidget(dialog)
    ui_thread = get_ident()
    saved_on = []
    save_report = dialog._history.save_report

    def record_save(value):
        saved_on.append(get_ident())
        return save_report(value)

    monkeypatch.setattr(dialog._history, "save_report", record_save)
    dialog.refresh_usage()
    qtbot.waitUntil(lambda: dialog.refresh_button.isEnabled(), timeout=2000)
    assert saved_on and saved_on[0] != ui_thread
    assert dialog.local_total_label.text() == "Token  1,500"


def test_reopening_during_refresh_delivers_the_pending_result(qtbot, tmp_path) -> None:
    from threading import Event

    report = _report(tmp_path)
    release = Event()
    class FakeClient:
        def fetch_report(self):
            assert release.wait(3)
            return report

    dialog = CodexUsageDialog(tmp_path / "history.json", client_factory=FakeClient, auto_refresh=False)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.refresh_usage()
    worker = dialog._worker
    try:
        dialog.close()
        release.set()
        dialog.show()
        qtbot.waitUntil(lambda: dialog.refresh_button.isEnabled(), timeout=2000)
        assert dialog.local_total_label.text() == "Token  1,500"
    finally:
        release.set()
        worker.join(timeout=3)


def test_ui_remains_responsive_while_history_is_archived(qtbot, tmp_path, monkeypatch) -> None:
    from threading import Event
    from PySide6.QtCore import QTimer

    report = _report(tmp_path)
    started, release = Event(), Event()
    responded = []
    class FakeClient:
        def fetch_report(self):
            return report

    dialog = CodexUsageDialog(tmp_path / "history.json", client_factory=FakeClient, auto_refresh=False)
    qtbot.addWidget(dialog)
    save_report = dialog._history.save_report
    def slow_save(value):
        started.set()
        responded.append(release.wait(1))
        return save_report(value)

    monkeypatch.setattr(dialog._history, "save_report", slow_save)
    dialog.refresh_usage()
    worker = dialog._worker
    try:
        qtbot.waitUntil(started.is_set, timeout=2000)
        QTimer.singleShot(0, release.set)
        qtbot.waitUntil(lambda: dialog.refresh_button.isEnabled(), timeout=2000)
        assert responded == [True]
    finally:
        release.set()
        worker.join(timeout=3)


def test_completed_worker_is_drained_before_starting_another_refresh(qtbot, tmp_path) -> None:
    report = _report(tmp_path)
    calls = []
    class FakeClient:
        def fetch_report(self):
            calls.append(True)
            return report

    dialog = CodexUsageDialog(tmp_path / "history.json", client_factory=FakeClient, auto_refresh=False)
    qtbot.addWidget(dialog)
    dialog.refresh_usage()
    first = dialog._worker
    first.join(timeout=2)
    assert not first.is_alive()
    dialog.refresh_usage()
    assert dialog._worker is first
    qtbot.waitUntil(lambda: dialog.refresh_button.isEnabled(), timeout=2000)
    assert len(calls) == 1


def test_reopening_reuses_recent_report_and_refreshes_when_stale(qtbot, tmp_path, monkeypatch) -> None:
    now = [100.0]
    monkeypatch.setattr("petnest.ui.codex_usage_dialog.monotonic", lambda: now[0], raising=False)
    report = _report(tmp_path)
    calls = []
    class FakeClient:
        def fetch_report(self):
            calls.append(True)
            return report

    dialog = CodexUsageDialog(tmp_path / "history.json", client_factory=FakeClient)
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitUntil(lambda: len(calls) == 1 and dialog.refresh_button.isEnabled(), timeout=2000)
    dialog.close()
    dialog.show()
    qtbot.wait(150)
    assert len(calls) == 1
    assert dialog.local_total_label.text() == "Token  1,500"
    dialog.close()
    now[0] += 61
    dialog.show()
    qtbot.waitUntil(lambda: len(calls) == 2 and dialog.refresh_button.isEnabled(), timeout=2000)


def test_history_save_failure_keeps_report_visible(qtbot, tmp_path, monkeypatch) -> None:
    report = _report(tmp_path)
    class FakeClient:
        def fetch_report(self):
            return report

    dialog = CodexUsageDialog(tmp_path / "history.json", client_factory=FakeClient, auto_refresh=False)
    qtbot.addWidget(dialog)
    def fail_save(_report):
        raise OSError("disk unavailable")

    monkeypatch.setattr(dialog._history, "save_report", fail_save)
    dialog.refresh_usage()
    qtbot.waitUntil(lambda: dialog.refresh_button.isEnabled(), timeout=2000)
    assert "disk unavailable" in dialog.status_label.text()
    assert dialog.local_total_label.text() == "Token  1,500"


def test_history_save_failure_still_selects_the_current_account(qtbot, tmp_path, monkeypatch) -> None:
    current = _report(tmp_path)
    previous = replace(
        current,
        account=CodexAccount("b" * 24, "ol*****@example.com", "pro"),
        fetched_at=current.fetched_at - timedelta(days=1),
    )
    history_path = tmp_path / "history.json"
    CodexUsageHistoryStore(history_path).save_report(previous)

    class FakeClient:
        def fetch_report(self):
            return current

    dialog = CodexUsageDialog(history_path, client_factory=FakeClient, auto_refresh=False)
    qtbot.addWidget(dialog)

    def fail_save(_report):
        raise OSError("disk unavailable")

    monkeypatch.setattr(dialog._history, "save_report", fail_save)
    dialog.refresh_usage()
    qtbot.waitUntil(lambda: dialog.refresh_button.isEnabled(), timeout=2_000)

    assert dialog.account_selector.currentData() == current.account.key
    assert dialog.cycle_selector.currentData() == "__live__"
    assert current.account.label in dialog.current_account_label.text()
    assert "disk unavailable" in dialog.status_label.text()


def test_dialog_disables_reset_when_account_has_no_credit(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    report = _report(tmp_path)
    report = replace(
        report,
        rate_limit_reset_credits=CodexRateLimitResetAvailability(available_count=0),
    )
    dialog = CodexUsageDialog(tmp_path / "history.json", auto_refresh=False)
    qtbot.addWidget(dialog)

    dialog._show_report(report)

    assert dialog.reset_status_card.property("resetState") == "empty"
    assert dialog.reset_status_badge.text() == "暂无可用"


def test_dialog_explains_unavailable_reset_feature(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    report = replace(_report(tmp_path), rate_limit_reset_credits=None)
    dialog = CodexUsageDialog(tmp_path / "history.json", auto_refresh=False)
    qtbot.addWidget(dialog)

    dialog._show_report(report)

    assert dialog.reset_status_card.property("resetState") == "unknown"
    assert dialog.reset_status_badge.text() == "未提供"
    assert "尚未向该账号提供" in dialog.reset_status_detail_label.text()


def test_claim_pending_button_persists_current_account_claim(
    qtbot: pytest.QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = _report(tmp_path)
    report = replace(
        report,
        local_usage=replace(report.local_usage, pending_event_ids=("event-one", "event-two")),
    )
    history_path = tmp_path / "history.json"
    dialog = CodexUsageDialog(history_path, auto_refresh=False)
    qtbot.addWidget(dialog)
    dialog._live_report = report
    dialog._show_report(report)
    refreshed: list[bool] = []
    monkeypatch.setattr(dialog, "refresh_usage", lambda: refreshed.append(True))
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
    )

    qtbot.mouseClick(dialog.claim_pending_button, Qt.MouseButton.LeftButton)

    reset = report.primary_limit.primary.resets_at
    assert reset is not None
    store = CodexManualAttributionStore(codex_manual_attribution_path(history_path))
    assert store.claimed_event_ids(report.account.key, int(reset.timestamp())) == {
        "event-one",
        "event-two",
    }
    assert refreshed == [True]


def test_historical_account_uses_newer_remote_quota(qtbot, tmp_path):
    report = replace(_report(tmp_path), fetched_at=datetime.now(UTC) - timedelta(hours=1))
    path = tmp_path / "history.json"
    history = CodexUsageHistoryStore(path)
    history.save_report(report)
    snapshot = history.load_cycles(report.account.key)[0]
    remote = CodexDeviceUsageSnapshot.from_report(report, device_id="remote", device_label="Office")
    store = CodexDeviceUsageStore(codex_device_usage_path(path))
    store.save(replace(remote, account_used_percent=87, updated_at=datetime.now(UTC).isoformat()))
    dialog = CodexUsageDialog(path, auto_refresh=False, device_id="local")
    qtbot.addWidget(dialog)
    dialog._show_snapshot(snapshot)
    assert dialog.findChildren(QLabel, "quotaRemainingLabel")[0].text() == "剩余 13%"
    assert "局域网额度" in dialog.current_account_label.text()
    assert dialog.local_total_label.text() == "Token  1,500"
    assert history.load_cycles(report.account.key)[0].used_percent == 4


def test_dialog_adds_synced_peer_without_double_counting_local_device(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    report = _report(tmp_path)
    history_path = tmp_path / "history.json"
    store = CodexDeviceUsageStore(codex_device_usage_path(history_path))
    reset = report.primary_limit.primary.resets_at
    assert reset is not None
    remote = CodexDeviceUsageSnapshot(
        account_key=report.account.key,
        device_id="remote-device",
        device_label="Office PC",
        window_resets_at=int(reset.timestamp()),
        window_duration_minutes=10_080,
        updated_at=datetime.now(UTC).isoformat(),
        input_tokens=1_800,
        cached_input_tokens=0,
        cache_write_input_tokens=0,
        output_tokens=200,
        reasoning_output_tokens=0,
        total_tokens=2_000,
        requests=3,
        model_usage=(CodexModelUsage("gpt-5.5", uses=3, total_tokens=2_000),),
        reasoning_usage=(
            CodexReasoningUsage("medium", uses=2),
            CodexReasoningUsage("low", uses=1),
        ),
        fast_uses=1,
        standard_uses=3,
        weighted_credits=0.75,
        weighted_complete=True,
        weight_version=CODEX_USAGE_WEIGHT_VERSION,
    )
    store.save(remote)

    class FakeClient:
        def fetch_report(self) -> CodexUsageReport:
            return report

    dialog = CodexUsageDialog(
        history_path,
        client_factory=FakeClient,  # type: ignore[arg-type]
        auto_refresh=False,
        device_id="local-device",
        device_label="Home Mac",
    )
    qtbot.addWidget(dialog)
    dialog.refresh_usage()
    qtbot.waitUntil(lambda: dialog.refresh_button.isEnabled(), timeout=2_000)

    assert "已同步 1 台" in dialog.synced_devices_label.text()
    assert "3,500 Token" in dialog.all_devices_total_label.text()
    assert "4 次" in dialog.all_devices_total_label.text()
    ranking = [dialog.device_ranking_list.item(index).text() for index in range(dialog.device_ranking_list.count())]
    assert "Office PC" in ranking[0]
    assert "2,000 Token" in ranking[0]
    assert "3 次模型请求" in ranking[0]
    assert "Home Mac（本机）" in ranking[1]
    assert dialog.device_ranking_title.text() == "同账号设备用量排名（预估）"
    assert "Credit" not in ranking[0]
    assert "加权占比 75.7%" in ranking[0]
    assert "Token 占比 57.1%" in ranking[0]
    assert "约 3% 额度" in ranking[0]
    assert "常用 gpt-5.5（3 次）" in ranking[0]
    assert "速度 极快 25% · 标准 75%" in ranking[0]
    assert "速度 极快 75% · 标准 25%" in ranking[1]
    assert "推理强度 中 66.7% · 低 33.3%" in ranking[0]
    assert "推理强度 高 75% · 中 25%" in ranking[1]
    assert "常用模型  gpt-5.6-sol（1 次）" in dialog.local_models_label.text()
    assert all("预估" in line or "约" in line for line in ranking)
    assert "非单机归因" in dialog.local_quota_change_label.text()

    store.save(
        replace(
            remote,
            total_tokens=3_000,
            weighted_credits=1.125,
            updated_at=datetime.now(UTC).isoformat(),
        )
    )
    dialog.reload_synced_usage(report.account.key)
    refreshed = dialog.device_ranking_list.item(0).text()
    assert "3,000 Token" in refreshed
    assert "约 3.3% 额度" in refreshed


def test_incomplete_weight_is_recalculated_from_available_models(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    report = _report(tmp_path)
    report = replace(
        report,
        local_usage=replace(report.local_usage, weighted_complete=False),
    )

    class FakeClient:
        def fetch_report(self) -> CodexUsageReport:
            return report

    dialog = CodexUsageDialog(
        tmp_path / "history.json",
        client_factory=FakeClient,  # type: ignore[arg-type]
        auto_refresh=False,
        device_id="local-device",
        device_label="Home PC",
    )
    qtbot.addWidget(dialog)
    dialog.refresh_usage()
    qtbot.waitUntil(lambda: dialog.refresh_button.isEnabled(), timeout=2_000)

    ranking = dialog.device_ranking_list.item(0).text()
    assert dialog.local_weighted_label.text() == "加权 0.2413（参考权重）（仅已知部分）"
    assert "Credit" not in ranking
    assert ranking.startswith("👑")
    assert "加权占比 100%（近似）" in ranking
    assert "约 4% 额度" in ranking


def test_ranking_recalculates_legacy_model_data_without_using_stale_weights(
    qtbot: pytest.QtBot, tmp_path: Path,
) -> None:
    report = _report(tmp_path)
    report = replace(
        report,
        local_usage=replace(
            report.local_usage,
            tokens=CodexTokenUsage(input_tokens=1_000_000, total_tokens=1_000_000, requests=1),
            model_usage=(CodexModelUsage("gpt-6.1-terra", uses=1, total_tokens=1_000_000),),
            weighted_credits=25,
        ),
    )
    reset = report.primary_limit.primary.resets_at
    assert reset is not None
    history_path = tmp_path / "history.json"
    store = CodexDeviceUsageStore(codex_device_usage_path(history_path))
    remote = CodexDeviceUsageSnapshot(
        account_key=report.account.key,
        device_id="remote",
        device_label="Astra PC",
        window_resets_at=int(reset.timestamp()),
        window_duration_minutes=10_080,
        updated_at=datetime.now(UTC).isoformat(),
        input_tokens=500_000,
        cached_input_tokens=0,
        cache_write_input_tokens=0,
        output_tokens=0,
        reasoning_output_tokens=0,
        total_tokens=500_000,
        requests=1,
        model_usage=(CodexModelUsage("gpt-6-astra", uses=1, total_tokens=500_000),),
        weighted_credits=125,
        weighted_complete=True,
        weight_version=CODEX_USAGE_WEIGHT_VERSION,
    )
    store.save(remote)

    class FakeClient:
        def fetch_report(self) -> CodexUsageReport:
            return report

    dialog = CodexUsageDialog(
        history_path,
        client_factory=FakeClient,  # type: ignore[arg-type]
        auto_refresh=False,
        device_id="local",
        device_label="Terra PC",
    )
    qtbot.addWidget(dialog)
    dialog.refresh_usage()
    qtbot.waitUntil(lambda: dialog.refresh_button.isEnabled(), timeout=2_000)

    first = dialog.device_ranking_list.item(0).text()
    second = dialog.device_ranking_list.item(1).text()
    assert first.startswith("👑 Astra PC")
    assert "Token 占比 33.3%" in first
    assert "加权占比 83.3%" in first
    assert "约 3.3% 额度" in first
    assert second.startswith("🥈 Terra PC")
    assert "Token 占比 66.7%" in second

    # Ignore the old numerical weight, but reconstruct it from token data.
    store.save(replace(remote, weight_version=None, weighted_credits=1))
    dialog.reload_synced_usage(report.account.key)
    lines = [dialog.device_ranking_list.item(index).text() for index in range(2)]
    assert dialog.device_ranking_title.text() == "同账号设备用量排名（预估）"
    assert lines[0].startswith("👑 Astra PC")
    assert "加权占比 83.3%（近似）" in lines[0]
    assert "约 3.3% 额度" in lines[0]

    # An unpriced auto-review label must not hide the priced model's tokens
    # or disable ranking when enough device data is available to estimate.
    store.save(
        replace(
            remote,
            weight_version=None,
            model_usage=(
                CodexModelUsage("codex-auto-review", uses=99, total_tokens=100_000, input_tokens=100_000),
                CodexModelUsage("gpt-6-astra", uses=1, total_tokens=400_000, input_tokens=400_000),
            ),
        )
    )
    dialog.reload_synced_usage(report.account.key)
    estimated = dialog.device_ranking_list.item(0).text()
    assert estimated.startswith("👑 Astra PC")
    assert "加权占比 83.3%（近似）" in estimated


def test_model_details_show_per_device_tokens_dollars_and_ranking_weights(
    qtbot: pytest.QtBot, tmp_path: Path,
) -> None:
    report = _report(tmp_path)
    report = replace(
        report,
        local_usage=replace(
            report.local_usage,
            tokens=CodexTokenUsage(
                input_tokens=1_000_000, cached_input_tokens=300_000,
                output_tokens=200_000, total_tokens=1_200_000, requests=1,
            ),
            model_usage=(CodexModelUsage(
                "gpt-6.1-sol", uses=1, total_tokens=1_200_000,
                input_tokens=1_000_000, cached_input_tokens=300_000,
                output_tokens=200_000, weighted_credits=25,
            ),),
            weighted_credits=25,
            weighted_complete=True,
        ),
    )
    reset = report.primary_limit.primary.resets_at
    assert reset is not None
    history_path = tmp_path / "history.json"
    store = CodexDeviceUsageStore(codex_device_usage_path(history_path))
    remote = CodexDeviceUsageSnapshot(
        account_key=report.account.key, device_id="remote", device_label="Office PC",
        window_resets_at=int(reset.timestamp()), window_duration_minutes=10_080,
        updated_at=datetime.now(UTC).isoformat(), input_tokens=1_000_000,
        cached_input_tokens=500_000, cache_write_input_tokens=0, output_tokens=100_000,
        reasoning_output_tokens=0, total_tokens=1_100_000, requests=11,
        model_usage=(
            CodexModelUsage("gpt-6-astra", uses=10, total_tokens=850_000,
                            input_tokens=800_000, cached_input_tokens=300_000, output_tokens=50_000),
            CodexModelUsage("codex-auto-review", uses=1, total_tokens=250_000,
                            input_tokens=200_000, cached_input_tokens=200_000, output_tokens=50_000),
        ),
        fast_uses=1, standard_uses=1,
    )
    store.save(remote)
    dialog = CodexUsageDialog(history_path, auto_refresh=False, device_id="local", device_label="Home")
    qtbot.addWidget(dialog)
    dialog._show_report(report)
    assert dialog.model_details_button.isEnabled()
    dialog.model_details_button.click()
    details = dialog._model_details_dialog
    assert details is not None
    qtbot.addWidget(details)
    tree = details.model_tree
    assert tree.topLevelItemCount() == 2
    office = tree.topLevelItem(0)
    home = tree.topLevelItem(1)
    assert office.text(0).startswith("👑 Office PC")
    assert office.text(6) == "约 $7.80（部分）"
    assert office.childCount() == 2
    assert office.child(0).text(0) == "gpt-6-astra"
    assert office.child(0).text(1) == "850,000"
    assert office.child(0).text(2) == "500,000"
    assert office.child(0).text(3) == "300,000"
    assert office.child(0).text(4) == "50,000"
    assert office.child(0).text(6) == "约 $7.80"
    assert office.child(1).text(0) == "codex-auto-review"
    assert office.child(1).text(6) == "无单价"
    assert home.child(0).text(6) == "约 $3.43"
    assert "仅已知模型" in details.summary_label.text()

    # A capped or older peer snapshot can omit model rows. The open detail
    # window updates and shows the unlisted tokens instead of hiding them.
    store.save(replace(remote, input_tokens=1_100_000, total_tokens=1_200_000))
    dialog._show_report(report)
    office = tree.topLevelItem(0)
    assert office.childCount() == 3
    assert office.child(2).text(0) == "其他 / 未记录模型"
    assert office.child(2).text(1) == "100,000"
    assert office.child(2).text(6) == "—"


def test_unknown_only_model_falls_back_to_labelled_token_ranking(
    qtbot: pytest.QtBot, tmp_path: Path,
) -> None:
    report = _report(tmp_path)
    report = replace(
        report,
        local_usage=replace(
            report.local_usage,
            weighted_complete=False,
            model_usage=(CodexModelUsage("codex-auto-review", uses=1, total_tokens=1_500),),
        ),
    )
    dialog = CodexUsageDialog(tmp_path / "history.json", auto_refresh=False)
    qtbot.addWidget(dialog)
    dialog._show_report(report)

    row = dialog.device_ranking_list.item(0).text()
    assert dialog.device_ranking_title.text() == "同账号设备 Token 排名（权重不足）"
    assert row.startswith("👑")
    assert "加权占比 不可用（模型明细不足）" in row
    assert "预估额度 —" in row


def test_zero_weight_is_recalculated_when_token_detail_is_available(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    report = _report(tmp_path)
    report = replace(
        report,
        local_usage=replace(report.local_usage, weighted_credits=0, weighted_complete=True),
    )

    class FakeClient:
        def fetch_report(self) -> CodexUsageReport:
            return report

    dialog = CodexUsageDialog(
        tmp_path / "history.json",
        client_factory=FakeClient,  # type: ignore[arg-type]
        auto_refresh=False,
        device_id="local-device",
        device_label="Home PC",
    )
    qtbot.addWidget(dialog)
    dialog.refresh_usage()
    qtbot.waitUntil(lambda: dialog.refresh_button.isEnabled(), timeout=2_000)

    ranking = dialog.device_ranking_list.item(0).text()
    assert "Credit" not in ranking
    assert "加权占比 100%（近似）" in ranking


def test_remote_only_account_is_visible_without_local_login(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    history_path = tmp_path / "history.json"
    reset = datetime.now(UTC) + timedelta(days=5)
    CodexDeviceUsageStore(codex_device_usage_path(history_path)).save(
        CodexDeviceUsageSnapshot(
            account_key="c" * 24,
            device_id="office-pc",
            device_label="Office PC",
            window_resets_at=int(reset.timestamp()),
            window_duration_minutes=10_080,
            updated_at=datetime.now(UTC).isoformat(),
            input_tokens=4_000,
            cached_input_tokens=0,
            cache_write_input_tokens=0,
            output_tokens=1_000,
            reasoning_output_tokens=0,
            total_tokens=5_000,
            requests=5,
            model_usage=(CodexModelUsage("gpt-5.5", uses=5, total_tokens=5_000),),
            account_label="ne*****@example.com",
            plan_type="pro",
            account_used_percent=12.0,
            fast_uses=5,
            standard_uses=5,
        )
    )

    dialog = CodexUsageDialog(
        history_path,
        auto_refresh=False,
        device_id="local-device",
        device_label="Home Mac",
    )
    qtbot.addWidget(dialog)

    assert dialog.account_selector.currentData() == "c" * 24
    assert "ne*****@example.com" in dialog.account_selector.currentText()
    assert "局域网" in dialog.account_selector.currentText()
    assert "局域网同步" in dialog.current_account_label.text()
    assert "本机未登录" in dialog.local_scan_label.text()
    remaining = next(
        item
        for item in dialog.findChildren(QLabel, "quotaRemainingLabel")
        if item.text() == "剩余 88%"
    )
    assert remaining.text() == "剩余 88%"
    ranking = dialog.device_ranking_list.item(0).text()
    assert "Office PC" in ranking
    assert "约 12% 额度" in ranking
    assert "常用 gpt-5.5（5 次）" in ranking
    assert "速度 极快 50% · 标准 50%" in ranking


def test_newer_peer_cycle_precedes_local_history_and_remains_selectable(qtbot, tmp_path) -> None:
    now = datetime.now(UTC)
    report = _report(tmp_path)
    old_limit = replace(report.primary_limit, primary=CodexRateWindow(78, 10_080, now - timedelta(hours=1)))
    old = replace(
        report,
        rate_limits=(old_limit,),
        primary_limit=old_limit,
        fetched_at=now - timedelta(days=1),
    )
    history_path = tmp_path / "history.json"
    CodexUsageHistoryStore(history_path).save_report(old)
    peer = CodexDeviceUsageSnapshot(
        account_key=old.account.key, device_id="office-pc", device_label="Office PC",
        window_resets_at=int((now + timedelta(days=7)).timestamp()),
        window_duration_minutes=10_080, updated_at=now.isoformat(),
        input_tokens=0, cached_input_tokens=0, cache_write_input_tokens=0,
        output_tokens=0, reasoning_output_tokens=0, total_tokens=0, requests=0,
        account_label=old.account.label, plan_type="pro", account_used_percent=0,
    )
    earlier = replace(
        peer,
        window_resets_at=peer.window_resets_at - 60,
        updated_at=(now - timedelta(minutes=1)).isoformat(),
    )
    # Previously saved empty placeholders must not create duplicate cycles.
    codex_device_usage_path(history_path).write_text(json.dumps({
        "schema_version": 6,
        "devices": {"old": asdict(earlier), "new": asdict(peer)},
    }))

    dialog = CodexUsageDialog(history_path, auto_refresh=False)
    qtbot.addWidget(dialog)
    dialog.resize(920, 730)
    dialog.show()
    qtbot.waitUntil(
        lambda: dialog.content_scroll.widget().width() <= dialog.content_scroll.viewport().width(),
        timeout=2_000,
    )
    assert dialog.cycle_selector.currentData() == f"remote:{peer.window_resets_at}"
    assert dialog.cycle_selector.count() == 2
    assert "局域网同步" in dialog.current_account_label.text()
    assert dialog.findChildren(QLabel, "quotaRemainingLabel")[-1].text() == "剩余 100%"
    quota_row = dialog.quota_rows.itemAt(0).widget()
    assert quota_row is not None
    assert all("历史快照" not in label.text() for label in quota_row.findChildren(QLabel))

    dialog.cycle_selector.setCurrentIndex(1)
    assert "历史快照" in dialog.current_account_label.text()
    dialog.reload_synced_usage(old.account.key)
    assert "往期" in dialog.cycle_selector.currentText()
    assert "历史快照" in dialog.current_account_label.text()


def test_remote_account_follows_latest_cycle_until_user_chooses_history(qtbot, tmp_path) -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    current = _report(tmp_path)
    other = replace(
        current,
        account=CodexAccount("b" * 24, "ot*****@example.com", "pro"),
        fetched_at=now - timedelta(days=1),
    )
    history_path = tmp_path / "history.json"
    CodexUsageHistoryStore(history_path).save_report(other)
    store = CodexDeviceUsageStore(codex_device_usage_path(history_path))
    peer = CodexDeviceUsageSnapshot(
        account_key=other.account.key, device_id="office", device_label="Office",
        window_resets_at=int((now + timedelta(days=7)).timestamp()),
        window_duration_minutes=10_080, updated_at=now.isoformat(),
        input_tokens=0, cached_input_tokens=0, cache_write_input_tokens=0,
        output_tokens=0, reasoning_output_tokens=0, total_tokens=0, requests=0,
        account_label=other.account.label, plan_type="pro", account_used_percent=0,
    )
    store.save(peer)

    class FakeClient:
        def fetch_report(self):
            return current

    dialog = CodexUsageDialog(history_path, client_factory=FakeClient, auto_refresh=False)
    qtbot.addWidget(dialog)
    dialog.refresh_usage()
    qtbot.waitUntil(lambda: dialog.refresh_button.isEnabled(), timeout=2_000)
    assert dialog.account_selector.currentData() == current.account.key
    dialog.account_selector.setCurrentIndex(dialog.account_selector.findData(other.account.key))
    assert dialog.cycle_selector.currentData() == f"remote:{peer.window_resets_at}"
    assert other.account.label in dialog.current_account_label.text()
    assert "当前登录账号已更新" in dialog.status_label.text()
    assert current.account.label in dialog.status_label.text()

    updated = replace(
        peer,
        window_resets_at=peer.window_resets_at + 60,
        updated_at=(now + timedelta(minutes=1)).isoformat(),
    )
    store.save(updated)
    dialog.reload_synced_usage(other.account.key)
    assert dialog.cycle_selector.currentData() == f"remote:{updated.window_resets_at}"
    dialog.refresh_usage()
    qtbot.waitUntil(lambda: dialog.refresh_button.isEnabled(), timeout=2_000)
    assert dialog.account_selector.currentData() == current.account.key
    assert dialog.cycle_selector.currentData() == "__live__"


def test_remote_devices_with_small_reset_differences_share_one_cycle(qtbot, tmp_path) -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    reset = int((now + timedelta(days=6)).timestamp())
    history_path = tmp_path / "history.json"
    store = CodexDeviceUsageStore(codex_device_usage_path(history_path))
    first = CodexDeviceUsageSnapshot(
        account_key="c" * 24, device_id="first", device_label="First",
        window_resets_at=reset, window_duration_minutes=10_080, updated_at=now.isoformat(),
        input_tokens=100, cached_input_tokens=0, cache_write_input_tokens=0,
        output_tokens=0, reasoning_output_tokens=0, total_tokens=100, requests=1,
        account_label="ne*****@example.com", plan_type="pro", account_used_percent=10,
    )
    store.save(first)
    store.save(replace(
        first, device_id="second", device_label="Second", window_resets_at=reset + 5,
        updated_at=(now + timedelta(seconds=1)).isoformat(), input_tokens=200, total_tokens=200,
    ))

    dialog = CodexUsageDialog(history_path, auto_refresh=False)
    qtbot.addWidget(dialog)
    assert dialog.cycle_selector.count() == 1
    assert "已同步 2 台设备" in dialog.synced_devices_label.text()
    assert "300 Token" in dialog.all_devices_total_label.text()


def test_newer_peer_cycle_replaces_an_expired_live_cycle(qtbot, tmp_path) -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    report = _report(tmp_path)
    old_limit = replace(report.primary_limit, primary=CodexRateWindow(78, 10_080, now - timedelta(hours=1)))
    stale = replace(
        report,
        rate_limits=(old_limit,),
        primary_limit=old_limit,
        fetched_at=now - timedelta(hours=2),
    )
    history_path = tmp_path / "history.json"
    peer = CodexDeviceUsageSnapshot(
        account_key=stale.account.key, device_id="office", device_label="Office",
        window_resets_at=int((now + timedelta(days=7)).timestamp()),
        window_duration_minutes=10_080, updated_at=now.isoformat(),
        input_tokens=0, cached_input_tokens=0, cache_write_input_tokens=0,
        output_tokens=0, reasoning_output_tokens=0, total_tokens=0, requests=0,
        account_label=stale.account.label, plan_type="pro", account_used_percent=0,
    )
    CodexDeviceUsageStore(codex_device_usage_path(history_path)).save(peer)

    class FakeClient:
        def fetch_report(self):
            return stale

    dialog = CodexUsageDialog(history_path, client_factory=FakeClient, auto_refresh=False)
    qtbot.addWidget(dialog)
    dialog.refresh_usage()
    qtbot.waitUntil(lambda: dialog.refresh_button.isEnabled(), timeout=2_000)
    assert dialog.account_selector.currentData() == stale.account.key
    assert dialog.cycle_selector.currentData() == f"remote:{peer.window_resets_at}"
    assert "局域网同步" in dialog.current_account_label.text()


def test_remote_zero_snapshot_shows_scan_reason_instead_of_confirmed_zero(
    qtbot: pytest.QtBot,
    tmp_path: Path,
) -> None:
    history_path = tmp_path / "history.json"
    reset = datetime.now(UTC) + timedelta(days=5)
    CodexDeviceUsageStore(codex_device_usage_path(history_path)).save(
        CodexDeviceUsageSnapshot(
            account_key="d" * 24,
            device_id="office-pc",
            device_label="Office PC",
            window_resets_at=int(reset.timestamp()),
            window_duration_minutes=10_080,
            updated_at=datetime.now(UTC).isoformat(),
            input_tokens=0,
            cached_input_tokens=0,
            cache_write_input_tokens=0,
            output_tokens=0,
            reasoning_output_tokens=0,
            total_tokens=0,
            requests=0,
            account_label="ze*****@example.com",
            plan_type="pro",
            account_used_percent=7.0,
            files_scanned=14,
            scan_status="no_matching_events",
        )
    )

    dialog = CodexUsageDialog(history_path, auto_refresh=False)
    qtbot.addWidget(dialog)

    ranking = dialog.device_ranking_list.item(0).text()
    assert "0 Token" not in ranking
    assert "Token —（当前账号/周期无匹配记录）" in ranking
    assert "已扫描 14 个会话文件" in ranking
    assert "已同步设备没有可确认的 Token" in dialog.quota_attribution_label.text()
    assert dialog.all_devices_total_label.text() == "已知设备合计  —（无可确认 Token）"


def test_device_ranking_switches_with_multiple_accounts(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    first = _report(tmp_path)
    second = replace(
        first,
        account=CodexAccount("b" * 24, "ot*****@example.com", "plus"),
        local_usage=LocalCodexUsage(
            tokens=CodexTokenUsage(total_tokens=4_000, requests=4),
            observed_start_used_percent=10,
            observed_end_used_percent=15,
        ),
        fetched_at=first.fetched_at + timedelta(seconds=1),
    )
    history_path = tmp_path / "history.json"
    CodexUsageHistoryStore(history_path).save_report(second)
    reset = first.primary_limit.primary.resets_at
    assert reset is not None
    CodexDeviceUsageStore(codex_device_usage_path(history_path)).save(
        CodexDeviceUsageSnapshot(
            account_key="b" * 24,
            device_id="office-pc",
            device_label="Office PC",
            window_resets_at=int(reset.timestamp()),
            window_duration_minutes=10_080,
            updated_at=datetime.now(UTC).isoformat(),
            input_tokens=5_000,
            cached_input_tokens=0,
            cache_write_input_tokens=0,
            output_tokens=1_000,
            reasoning_output_tokens=0,
            total_tokens=6_000,
            requests=6,
        )
    )

    class FakeClient:
        def fetch_report(self) -> CodexUsageReport:
            return first

    dialog = CodexUsageDialog(
        history_path,
        client_factory=FakeClient,  # type: ignore[arg-type]
        auto_refresh=False,
        device_id="local-device",
        device_label="Home Mac",
    )
    qtbot.addWidget(dialog)
    dialog.refresh_usage()
    qtbot.waitUntil(lambda: dialog.refresh_button.isEnabled(), timeout=2_000)

    second_index = dialog.account_selector.findData("b" * 24)
    assert second_index >= 0
    dialog.account_selector.setCurrentIndex(second_index)

    ranking = [dialog.device_ranking_list.item(index).text() for index in range(dialog.device_ranking_list.count())]
    assert ranking[0].startswith("👑 Office PC")
    assert "6,000 Token" in ranking[0]
    assert "Home Mac（本机）" in ranking[1]
    assert "4,000 Token" in ranking[1]
    assert dialog.device_ranking_title.text() == "同账号设备 Token 排名（权重不足）"
    assert all("预估额度 —" in item for item in ranking)


def test_dialog_moves_expired_tokens_into_a_selectable_cycle_history(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    current = _report(tmp_path)
    current_window = current.primary_limit.primary
    assert current_window is not None and current_window.resets_at is not None
    previous_limit = replace(
        current.primary_limit,
        primary=CodexRateWindow(
            used_percent=88,
            window_duration_minutes=10_080,
            resets_at=current_window.resets_at - timedelta(days=7),
        ),
    )
    previous = replace(
        current,
        rate_limits=(previous_limit,),
        primary_limit=previous_limit,
        local_usage=LocalCodexUsage(
            tokens=CodexTokenUsage(total_tokens=250, requests=2)
        ),
        fetched_at=current_window.resets_at - timedelta(days=7, minutes=1),
    )
    history_path = tmp_path / "history.json"
    CodexUsageHistoryStore(history_path).save_report(previous)

    class FakeClient:
        def fetch_report(self) -> CodexUsageReport:
            return current

    dialog = CodexUsageDialog(
        history_path,
        client_factory=FakeClient,  # type: ignore[arg-type]
        auto_refresh=False,
    )
    qtbot.addWidget(dialog)
    dialog.refresh_usage()
    qtbot.waitUntil(lambda: dialog.refresh_button.isEnabled(), timeout=2_000)

    assert dialog.cycle_selector.count() == 2
    assert dialog.cycle_selector.currentData() == "__live__"
    assert "当前" in dialog.cycle_selector.currentText()
    dialog.cycle_selector.setCurrentIndex(1)
    assert "往期" in dialog.cycle_selector.currentText()
    assert "已归档" in dialog.cycle_selector.currentText()
    assert dialog.local_total_label.text() == "Token  250"
