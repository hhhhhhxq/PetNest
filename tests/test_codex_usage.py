"""Codex account quota, local token correlation, and account history."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
from typing import Any

from petnest.core.codex_usage import (
    CodexAccount,
    CodexDeviceUsageSnapshot,
    CodexDeviceUsageStore,
    CodexRateWindow,
    CodexTokenUsage,
    CodexUsageClient,
    CodexUsageHistoryStore,
    LocalCodexUsage,
)


def _responses(codex_home: Path, *, email: str = "person@example.com") -> tuple[dict[int, dict[str, Any]], datetime]:
    now = datetime.now(UTC).replace(microsecond=0)
    reset = now + timedelta(days=6)
    responses = {
        1: {"codexHome": str(codex_home)},
        2: {
            "account": {
                "type": "chatgpt",
                "email": email,
                "planType": "pro",
            }
        },
        3: {
            "rateLimitsByLimitId": {
                "codex": {
                    "limitId": "codex",
                    "limitName": "Codex",
                    "planType": "pro",
                    "primary": {
                        "usedPercent": 4.0,
                        "windowDurationMins": 10_080,
                        "resetsAt": int(reset.timestamp()),
                    },
                    "secondary": None,
                    "credits": {
                        "balance": "0",
                        "hasCredits": False,
                        "unlimited": False,
                    },
                }
            }
        },
        4: {
            "summary": {
                "lifetimeTokens": 9_000_000,
                "peakDailyTokens": 800_000,
                "currentStreakDays": 3,
                "longestStreakDays": 8,
                "longestRunningTurnSec": 120,
            },
            "dailyUsageBuckets": [
                {"startDate": now.date().isoformat(), "tokens": 123_456},
            ],
        },
    }
    return responses, reset


def _write_token_event(
    path: Path,
    *,
    timestamp: datetime,
    reset: datetime,
    used_percent: float,
    total_tokens: int,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cached_input_tokens: int = 0,
) -> str:
    event = {
        "timestamp": timestamp.isoformat().replace("+00:00", "Z"),
        "type": "event_msg",
        "payload": {
            "type": "token_count",
            "info": {
                "last_token_usage": {
                    "input_tokens": input_tokens,
                    "cached_input_tokens": cached_input_tokens,
                    "cache_write_input_tokens": 0,
                    "output_tokens": output_tokens,
                    "reasoning_output_tokens": 0,
                    "total_tokens": total_tokens,
                }
            },
            "rate_limits": {
                "limit_id": "codex",
                "primary": {
                    "used_percent": used_percent,
                    "resets_at": int(reset.timestamp()),
                },
            },
        },
    }
    line = json.dumps(event)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(line + "\n")
    return line


def test_client_reads_weekly_quota_and_only_current_account_window_tokens(tmp_path: Path) -> None:
    responses, reset = _responses(tmp_path)
    event_time = datetime.now(UTC) - timedelta(hours=1)
    session = (
        tmp_path
        / "sessions"
        / event_time.strftime("%Y/%m/%d")
        / f"rollout-{event_time:%Y-%m-%dT%H-%M-%S}-11111111-1111-1111-1111-111111111111.jsonl"
    )
    matching_line = _write_token_event(
        session,
        timestamp=event_time,
        reset=reset,
        used_percent=1.5,
        total_tokens=1_500,
        input_tokens=1_000,
        output_tokens=200,
        cached_input_tokens=300,
    )
    # Repeated identical events and a switched account's different quota window
    # must not increase the current account total.
    with session.open("a", encoding="utf-8") as stream:
        stream.write(matching_line + "\n")
    _write_token_event(
        session,
        timestamp=event_time + timedelta(minutes=1),
        reset=reset + timedelta(hours=3),
        used_percent=70,
        total_tokens=99_999,
    )
    seen_methods: list[str] = []

    def transport(
        executable: Path,
        messages: list[dict[str, Any]],
        expected_ids: frozenset[int],
        timeout: float,
    ) -> dict[int, dict[str, Any]]:
        del executable, expected_ids, timeout
        seen_methods.extend(str(item.get("method")) for item in messages)
        return responses

    report = CodexUsageClient(Path("/fake/codex"), transport=transport).fetch_report()

    assert seen_methods == [
        "initialize",
        "initialized",
        "account/read",
        "account/rateLimits/read",
        "account/usage/read",
    ]
    assert report.account.label == "pe*****@example.com"
    assert report.account.plan_type == "pro"
    assert report.primary_limit.primary is not None
    assert report.primary_limit.primary.remaining_percent == 96
    assert report.account_tokens.lifetime_tokens == 9_000_000
    assert report.local_usage.tokens.total_tokens == 1_500
    assert report.local_usage.tokens.input_tokens == 1_000
    assert report.local_usage.tokens.output_tokens == 200
    assert report.local_usage.tokens.cached_input_tokens == 300
    assert report.local_usage.tokens.requests == 1
    assert report.local_usage.observed_quota_change == 2.5


def test_history_keeps_distinct_masked_snapshots_for_switched_accounts(tmp_path: Path) -> None:
    first_responses, _reset = _responses(tmp_path, email="first.person@example.com")
    second_responses, _reset = _responses(tmp_path, email="second.person@example.com")

    first = CodexUsageClient(
        Path("/fake/codex"),
        transport=lambda *_args: first_responses,
    ).fetch_report()
    second = CodexUsageClient(
        Path("/fake/codex"),
        transport=lambda *_args: second_responses,
    ).fetch_report()
    second = replace(
        second,
        account=CodexAccount(
            key=second.account.key,
            label=second.account.label,
            plan_type="plus",
        ),
        fetched_at=first.fetched_at + timedelta(seconds=1),
    )
    store = CodexUsageHistoryStore(tmp_path / "petnest" / "codex-usage-history.json")

    store.save_report(first)
    store.save_report(second)

    snapshots = store.load()
    persisted = store.path.read_text(encoding="utf-8")
    assert len(snapshots) == 2
    assert snapshots[0].account_key != snapshots[1].account_key
    assert {item.plan_type for item in snapshots} == {"pro", "plus"}
    assert "first.person@example.com" not in persisted
    assert "second.person@example.com" not in persisted
    assert "fi*****@example.com" in persisted
    assert "se*****@example.com" in persisted


def test_device_store_separates_accounts_windows_and_replaces_each_device(tmp_path: Path) -> None:
    store = CodexDeviceUsageStore(tmp_path / "codex-usage-devices.json")
    first = CodexDeviceUsageSnapshot(
        account_key="a" * 24,
        device_id="laptop-a",
        device_label="MacBook",
        window_resets_at=2_000_000_000,
        window_duration_minutes=10_080,
        updated_at=datetime.now(UTC).isoformat(),
        input_tokens=700,
        cached_input_tokens=200,
        cache_write_input_tokens=0,
        output_tokens=300,
        reasoning_output_tokens=0,
        total_tokens=1_000,
        requests=2,
    )
    replacement = replace(first, total_tokens=1_500, requests=3)
    other_account = replace(first, account_key="b" * 24, device_id="laptop-b")
    other_window = replace(first, device_id="laptop-c", window_resets_at=2_000_100_000)

    store.save(first)
    store.save(replacement)
    store.save(other_account)
    store.save(other_window)

    matching = store.load(
        account_key="a" * 24,
        window_resets_at=2_000_000_000,
    )
    assert len(matching) == 1
    assert matching[0].device_id == "laptop-a"
    assert matching[0].tokens.total_tokens == 1_500
    assert matching[0].tokens.requests == 3
    assert len(store.load()) == 3


def test_history_keeps_each_quota_cycle_and_finalizes_the_expired_local_total(tmp_path: Path) -> None:
    responses, current_reset = _responses(tmp_path)
    current = CodexUsageClient(
        Path("/fake/codex"),
        transport=lambda *_args: responses,
    ).fetch_report()
    previous_reset = current_reset - timedelta(days=7)
    previous_limit = replace(
        current.primary_limit,
        primary=CodexRateWindow(90, 10_080, previous_reset),
    )
    previous = replace(
        current,
        rate_limits=(previous_limit,),
        primary_limit=previous_limit,
        local_usage=LocalCodexUsage(tokens=CodexTokenUsage(total_tokens=111, requests=1)),
        fetched_at=previous_reset - timedelta(minutes=1),
    )
    current = replace(
        current,
        local_usage=LocalCodexUsage(tokens=CodexTokenUsage(total_tokens=222, requests=2)),
    )
    store = CodexUsageHistoryStore(tmp_path / "history.json")

    store.save_report(previous)
    store.save_report(current)

    cycles = store.load_cycles(current.account.key)
    assert len(cycles) == 2
    assert cycles[0].local_tokens == 222
    assert not cycles[0].finalized
    assert cycles[1].local_tokens == 111
    assert cycles[1].finalized
    assert store.load() == (cycles[0],)
