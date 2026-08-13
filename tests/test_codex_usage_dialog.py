"""Qt presentation for the Codex account usage report."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QProgressBar

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
    CodexUsageHistoryStore,
    DailyTokenUsage,
    LocalCodexUsage,
    codex_device_usage_path,
)
from petnest.ui.codex_usage_dialog import CodexUsageDialog


def test_usage_dialog_is_a_movable_non_modal_window(tmp_path, qtbot) -> None:
    dialog = CodexUsageDialog(tmp_path / "usage.json", auto_refresh=False)
    qtbot.addWidget(dialog)

    assert dialog.windowType() is Qt.WindowType.Window
    assert dialog.windowModality() is Qt.WindowModality.NonModal
    assert not dialog.isModal()
    assert dialog.windowFlags() & Qt.WindowType.WindowTitleHint


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
    )


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
    assert dialog.local_weighted_label.text() == "加权 0.2413 Credit"
    assert "待归属 250 Token" in dialog.local_attribution_label.text()
    assert "标签异常 1,500 Token" in dialog.local_attribution_label.text()
    assert dialog.local_speed_label.text() == "速度占比  极快 75% · 标准 25%"
    assert "+2.5" in dialog.local_quota_change_label.text()
    assert "已更新" in dialog.status_label.text()


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
        fast_uses=1,
        standard_uses=3,
        weighted_credits=0.75,
        weighted_complete=True,
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
    assert "加权 0.7500 Credit" in ranking[0]
    assert "加权占比 75.7%" in ranking[0]
    assert "Token 占比 57.1%" in ranking[0]
    assert "约 3% 额度" in ranking[0]
    assert "常用 gpt-5.5（3 次）" in ranking[0]
    assert "速度 极快 25% · 标准 75%" in ranking[0]
    assert "速度 极快 75% · 标准 25%" in ranking[1]
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


def test_incomplete_weighted_usage_explains_unavailable_share(qtbot: pytest.QtBot, tmp_path: Path) -> None:
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
    assert dialog.local_weighted_label.text() == "加权 0.2413 Credit（仅已知部分）"
    assert "加权 0.2413 Credit（仅已知部分）" in ranking
    assert "加权占比 不可用（明细不完整）" in ranking


def test_zero_weighted_total_explains_unavailable_share(qtbot: pytest.QtBot, tmp_path: Path) -> None:
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
    assert "加权 0.0000 Credit" in ranking
    assert "加权占比 不可用（加权值为 0）" in ranking


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
    assert "本机未登录" in dialog.current_account_label.text()
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
    assert "Office PC" in ranking[0]
    assert "6,000 Token" in ranking[0]
    assert "Home Mac（本机）" in ranking[1]
    assert "4,000 Token" in ranking[1]


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
