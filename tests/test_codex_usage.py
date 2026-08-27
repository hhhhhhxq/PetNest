"""Codex account quota, local token correlation, and account history."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
from typing import Any

import petnest.core.codex_usage as codex_usage_module
from petnest.core.codex_usage import (
    CodexAccount,
    CodexAccountObservationStore,
    CodexManualAttributionStore,
    CodexDeviceUsageSnapshot,
    CodexDeviceUsageStore,
    CodexModelUsage,
    CodexReasoningUsage,
    CodexRateLimit,
    CodexRateWindow,
    CodexTokenUsage,
    CodexUsageClient,
    CodexUsageError,
    CodexUsageHistoryStore,
    LocalCodexUsage,
    discover_codex_executable,
    locate_codex_home,
    scan_local_codex_usage,
)


def test_codex_home_locator_prefers_environment_override(tmp_path: Path) -> None:
    configured = tmp_path / "portable-codex"

    resolved = locate_codex_home(
        environment={"CODEX_HOME": str(configured)},
        user_home=tmp_path / "user",
        client_factory=lambda: (_ for _ in ()).throw(AssertionError("不应启动 app-server")),
    )

    assert resolved == configured.resolve()


def test_codex_home_locator_uses_existing_default_without_starting_server(tmp_path: Path) -> None:
    default = tmp_path / "user" / ".codex"
    (default / "sessions").mkdir(parents=True)

    resolved = locate_codex_home(
        environment={},
        user_home=tmp_path / "user",
        client_factory=lambda: (_ for _ in ()).throw(AssertionError("不应启动 app-server")),
    )

    assert resolved == default.resolve()


def test_codex_home_locator_uses_app_server_when_default_is_missing(tmp_path: Path) -> None:
    discovered = tmp_path / "managed-codex-home"

    class Client:
        def fetch_codex_home(self) -> Path:
            return discovered

    resolved = locate_codex_home(
        environment={},
        user_home=tmp_path / "user",
        client_factory=Client,
    )

    assert resolved == discovered.resolve()


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
            },
            "rateLimitResetCredits": {
                "availableCount": 1,
                "credits": [
                    {
                        "id": "RateLimitResetCredit_1",
                        "resetType": "codexRateLimits",
                        "status": "available",
                        "grantedAt": int(now.timestamp()),
                        "expiresAt": int((now + timedelta(days=30)).timestamp()),
                        "title": "Rate-limit reset",
                        "description": "Reset an eligible Codex rate-limit window.",
                    }
                ],
            },
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
    limit_id: str = "codex",
    cumulative_tokens: int | None = None,
    include_rate_limits: bool = True,
) -> str:
    event = {
        "timestamp": timestamp.isoformat().replace("+00:00", "Z"),
        "type": "event_msg",
        "payload": {
            "type": "token_count",
            "info": {
                "total_token_usage": {
                    "input_tokens": cumulative_tokens or total_tokens,
                    "cached_input_tokens": 0,
                    "cache_write_input_tokens": 0,
                    "output_tokens": 0,
                    "reasoning_output_tokens": 0,
                    "total_tokens": cumulative_tokens or total_tokens,
                },
                "last_token_usage": {
                    "input_tokens": input_tokens,
                    "cached_input_tokens": cached_input_tokens,
                    "cache_write_input_tokens": 0,
                    "output_tokens": output_tokens,
                    "reasoning_output_tokens": 0,
                    "total_tokens": total_tokens,
                }
            },
            "rate_limits": (
                {
                    "limit_id": limit_id,
                    "primary": {
                        "used_percent": used_percent,
                        "resets_at": int(reset.timestamp()),
                    },
                }
                if include_rate_limits
                else None
            ),
        },
    }
    line = json.dumps(event)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(line + "\n")
    return line


def _write_compaction_event(path: Path, *, timestamp: datetime) -> None:
    event = {
        "timestamp": timestamp.isoformat().replace("+00:00", "Z"),
        "type": "compacted",
        "payload": {},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event) + "\n")


def _weekly_limit(reset: datetime, *, used_percent: float = 4.0) -> CodexRateLimit:
    return CodexRateLimit(
        limit_id="codex",
        limit_name="Codex",
        plan_type="pro",
        primary=CodexRateWindow(used_percent, 10_080, reset),
        secondary=None,
        credit_balance=None,
        has_credits=False,
        unlimited_credits=False,
    )


def test_windows_discovery_prefers_user_codex_binary_over_protected_path(
    tmp_path: Path,
    monkeypatch,
) -> None:
    user_binary = tmp_path / "OpenAI/Codex/bin/revision/codex.exe"
    user_binary.parent.mkdir(parents=True)
    user_binary.write_bytes(b"codex")
    monkeypatch.setattr("petnest.core.codex_usage.sys.platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("PETNEST_CODEX_EXECUTABLE", raising=False)
    monkeypatch.delenv("CODEX_BIN", raising=False)
    monkeypatch.setattr("petnest.core.codex_usage.shutil.which", lambda _name: "C:/protected/codex.exe")

    assert discover_codex_executable() == user_binary


def _write_model_context(
    path: Path,
    *,
    timestamp: datetime,
    model: str,
    turn_id: str = "turn-1",
    reasoning_effort: str | None = None,
) -> None:
    payload: dict[str, Any] = {"model": model, "turn_id": turn_id}
    if reasoning_effort is not None:
        payload["collaboration_mode"] = {
            "settings": {"reasoning_effort": reasoning_effort}
        }
    event = {
        "timestamp": timestamp.isoformat().replace("+00:00", "Z"),
        "type": "turn_context",
        "payload": payload,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event) + "\n")


def _write_speed_setting(
    path: Path,
    *,
    timestamp: datetime,
    service_tier: str,
    reasoning_effort: str | None = None,
) -> None:
    settings = {"service_tier": service_tier}
    if reasoning_effort is not None:
        settings["reasoning_effort"] = reasoning_effort
    event = {
        "timestamp": timestamp.isoformat().replace("+00:00", "Z"),
        "type": "event_msg",
        "payload": {
            "type": "thread_settings_applied",
            "thread_settings": settings,
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event) + "\n")


def _write_session_meta(path: Path, *, timestamp: datetime, parent_thread_id: str) -> None:
    event = {
        "timestamp": timestamp.isoformat().replace("+00:00", "Z"),
        "type": "session_meta",
        "payload": {"parent_thread_id": parent_thread_id},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event) + "\n")


def test_client_reads_weekly_quota_and_only_current_account_window_tokens(tmp_path: Path) -> None:
    responses, reset = _responses(tmp_path)
    event_time = datetime.now(UTC) - timedelta(hours=1)
    session = (
        tmp_path
        / "sessions"
        / event_time.strftime("%Y/%m/%d")
        / f"rollout-{event_time:%Y-%m-%dT%H-%M-%S}-11111111-1111-1111-1111-111111111111.jsonl"
    )
    _write_model_context(
        session,
        timestamp=event_time - timedelta(seconds=1),
        model="gpt-5.6-sol",
        reasoning_effort="high",
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
    _write_speed_setting(
        session,
        timestamp=event_time + timedelta(minutes=2),
        service_tier="priority",
        reasoning_effort="medium",
    )
    _write_model_context(
        session,
        timestamp=event_time + timedelta(minutes=2, seconds=1),
        model="gpt-5.6-sol",
    )
    _write_token_event(
        session,
        timestamp=event_time + timedelta(minutes=2, seconds=2),
        reset=reset,
        used_percent=2,
        total_tokens=500,
        input_tokens=400,
        output_tokens=100,
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
    assert report.rate_limit_reset_credits is not None
    assert report.rate_limit_reset_credits.available_count == 1
    reset_credit = report.rate_limit_reset_credits.credits[0]
    assert reset_credit.credit_id == "RateLimitResetCredit_1"
    assert reset_credit.reset_type == "codexRateLimits"
    assert reset_credit.status == "available"
    assert reset_credit.granted_at is not None
    assert reset_credit.expires_at == reset_credit.granted_at + timedelta(days=30)
    assert report.account_tokens.lifetime_tokens == 9_000_000
    assert report.local_usage.tokens.total_tokens == 2_000
    assert report.local_usage.tokens.input_tokens == 1_400
    assert report.local_usage.tokens.output_tokens == 300
    assert report.local_usage.tokens.cached_input_tokens == 300
    assert report.local_usage.tokens.requests == 2
    assert report.local_usage.model_usage == (
        CodexModelUsage(
            "gpt-5.6-sol",
            uses=2,
            total_tokens=2_000,
            input_tokens=1_400,
            cached_input_tokens=300,
            output_tokens=300,
            weighted_credits=0.55375,
        ),
    )
    assert report.local_usage.fast_uses == 1
    assert report.local_usage.standard_uses == 1
    assert report.local_usage.reasoning_usage == (
        CodexReasoningUsage("high", uses=1),
        CodexReasoningUsage("medium", uses=1),
    )
    assert report.local_usage.scan_status == "matched"
    assert report.local_usage.files_scanned == 1
    assert report.local_usage.observed_quota_change == 2.5


def test_client_distinguishes_no_local_session_files_from_zero_usage(tmp_path: Path) -> None:
    responses, _reset = _responses(tmp_path)

    report = CodexUsageClient(
        Path("/fake/codex"),
        transport=lambda *_args: responses,
    ).fetch_report()

    assert report.local_usage.tokens.total_tokens == 0
    assert report.local_usage.scan_status == "no_session_files"


def test_client_falls_back_to_next_discovered_codex_launcher(tmp_path: Path, monkeypatch) -> None:
    responses, _reset = _responses(tmp_path)
    protected = tmp_path / "WindowsApps" / "codex.exe"
    npm_launcher = tmp_path / "npm" / "codex.cmd"
    attempted: list[Path] = []
    monkeypatch.setattr(
        codex_usage_module,
        "discover_codex_executables",
        lambda: (protected, npm_launcher),
    )

    def transport(executable, *_args):
        attempted.append(executable)
        if executable == protected:
            raise CodexUsageError("WinError 5 拒绝访问")
        return responses

    client = CodexUsageClient(transport=transport)
    report = client.fetch_report()

    assert report.account.label == "pe*****@example.com"
    assert attempted == [protected, npm_launcher]
    assert client.executable == npm_launcher


def test_windows_cmd_launcher_uses_command_processor(tmp_path: Path, monkeypatch) -> None:
    launcher = tmp_path / "Codex CLI" / "codex.cmd"
    monkeypatch.setattr(codex_usage_module.sys, "platform", "win32")
    monkeypatch.setenv("COMSPEC", "C:/Windows/System32/cmd.exe")

    command = codex_usage_module._codex_app_server_command(launcher)

    assert command[:4] == ["C:/Windows/System32/cmd.exe", "/d", "/s", "/c"]
    assert "codex.cmd" in command[4]
    assert "app-server --stdio" in command[4]


def test_lightweight_account_observation_does_not_request_usage(tmp_path: Path) -> None:
    responses, _reset = _responses(tmp_path)
    seen_methods: list[str] = []

    def transport(
        executable: Path,
        messages: list[dict[str, Any]],
        expected_ids: frozenset[int],
        timeout: float,
    ) -> dict[int, dict[str, Any]]:
        del executable, expected_ids, timeout
        seen_methods.extend(str(item.get("method")) for item in messages)
        return {1: responses[1], 2: responses[2]}

    account = CodexUsageClient(
        Path("/fake/codex"),
        transport=transport,
        observation_store=CodexAccountObservationStore(tmp_path / "observations.json"),
    ).observe_account()

    assert account is not None
    assert account.label == "pe*****@example.com"
    assert seen_methods == ["initialize", "initialized", "account/read"]


def test_explicit_model_accepts_codex_sub_limit_and_is_weighted(tmp_path: Path) -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    reset = now + timedelta(days=6)
    event_time = now - timedelta(minutes=10)
    session = (
        tmp_path
        / "sessions"
        / event_time.strftime("%Y/%m/%d")
        / f"rollout-{event_time:%Y-%m-%dT%H-%M-%S}-22222222-2222-2222-2222-222222222222.jsonl"
    )
    _write_speed_setting(session, timestamp=event_time - timedelta(seconds=2), service_tier="fast")
    _write_model_context(
        session,
        timestamp=event_time - timedelta(seconds=1),
        model="gpt-5.6-sol",
    )
    _write_token_event(
        session,
        timestamp=event_time,
        reset=event_time + timedelta(days=7),
        used_percent=0,
        total_tokens=1_500,
        input_tokens=1_000,
        cached_input_tokens=300,
        output_tokens=200,
        limit_id="codex_bengalfox",
    )

    usage = scan_local_codex_usage(tmp_path, _weekly_limit(reset), now=now)

    assert usage.tokens.total_tokens == 1_500
    assert usage.anomaly_tokens.total_tokens == 0
    assert usage.pending_tokens.total_tokens == 0
    assert usage.fast_uses == 1
    assert usage.reasoning_usage == (CodexReasoningUsage("unknown", uses=1),)
    assert usage.weighted_complete
    assert usage.weighted_credits == 0.603125
    assert usage.model_usage == (
        CodexModelUsage(
            "gpt-5.6-sol",
            uses=1,
            total_tokens=1_500,
            input_tokens=1_000,
            cached_input_tokens=300,
            output_tokens=200,
            weighted_credits=0.603125,
        ),
    )


def test_explicit_model_keeps_foreign_limit_label_as_anomaly(tmp_path: Path) -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    reset = now + timedelta(days=6)
    event_time = now - timedelta(minutes=10)
    session = (
        tmp_path
        / "sessions"
        / event_time.strftime("%Y/%m/%d")
        / f"rollout-{event_time:%Y-%m-%dT%H-%M-%S}-24242424-2424-2424-2424-242424242424.jsonl"
    )
    _write_model_context(
        session,
        timestamp=event_time - timedelta(seconds=1),
        model="gpt-5.6-sol",
    )
    _write_token_event(
        session,
        timestamp=event_time,
        reset=reset,
        used_percent=2,
        total_tokens=1_200,
        input_tokens=900,
        output_tokens=300,
        limit_id="chatgpt_other",
    )

    usage = scan_local_codex_usage(tmp_path, _weekly_limit(reset), now=now)

    assert usage.tokens.total_tokens == 1_200
    assert usage.anomaly_tokens.total_tokens == 1_200
    assert usage.pending_tokens.total_tokens == 0


def test_nested_thread_settings_supply_reasoning_effort_to_the_next_turn(tmp_path: Path) -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    reset = now + timedelta(days=6)
    event_time = now - timedelta(minutes=10)
    session = (
        tmp_path
        / "sessions"
        / event_time.strftime("%Y/%m/%d")
        / f"rollout-{event_time:%Y-%m-%dT%H-%M-%S}-23232323-2323-2323-2323-232323232323.jsonl"
    )
    session.parent.mkdir(parents=True, exist_ok=True)
    settings_event = {
        "timestamp": (event_time - timedelta(seconds=2)).isoformat().replace("+00:00", "Z"),
        "type": "event_msg",
        "payload": {
            "type": "thread_settings_applied",
            "thread_settings": {
                "collaboration_mode": {"settings": {"reasoning_effort": "xhigh"}}
            },
        },
    }
    session.write_text(json.dumps(settings_event) + "\n", encoding="utf-8")
    _write_model_context(
        session,
        timestamp=event_time - timedelta(seconds=1),
        model="gpt-5.6-sol",
    )
    _write_token_event(
        session,
        timestamp=event_time,
        reset=reset,
        used_percent=2,
        total_tokens=1_000,
        input_tokens=800,
        output_tokens=200,
    )

    usage = scan_local_codex_usage(tmp_path, _weekly_limit(reset), now=now)

    assert usage.reasoning_usage == (CodexReasoningUsage("xhigh", uses=1),)


def test_replayed_token_event_is_deduplicated_across_session_files(tmp_path: Path) -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    reset = now + timedelta(days=6)
    event_time = reset - timedelta(days=7, hours=1)
    first = tmp_path / "sessions/2026/07/01/rollout-2026-07-01T10-00-00-aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa.jsonl"
    replay = tmp_path / "sessions/2026/08/13/rollout-2026-08-13T11-00-00-bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb.jsonl"
    _write_session_meta(
        replay,
        timestamp=now - timedelta(minutes=6),
        parent_thread_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    )
    for path, timestamp in ((first, event_time), (replay, now - timedelta(minutes=5))):
        _write_model_context(path, timestamp=timestamp - timedelta(seconds=1), model="gpt-5.6-luna")
        _write_token_event(
            path,
            timestamp=timestamp,
            reset=reset,
            used_percent=2,
            total_tokens=900,
            input_tokens=700,
            output_tokens=200,
            cumulative_tokens=12_345,
        )
    old_mtime = (reset - timedelta(days=20)).timestamp()
    os.utime(first, (old_mtime, old_mtime))

    usage = scan_local_codex_usage(tmp_path, _weekly_limit(reset), now=now)

    assert usage.tokens.total_tokens == 0
    assert usage.tokens.requests == 0
    assert usage.duplicate_events == 1


def test_historical_window_stops_at_reset_even_for_wrong_limit_label(tmp_path: Path) -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    reset = now - timedelta(days=1)
    event_time = reset + timedelta(hours=1)
    session = tmp_path / "sessions/2026/08/13/rollout-2026-08-13T12-00-00-ffffffff-ffff-ffff-ffff-ffffffffffff.jsonl"
    _write_model_context(session, timestamp=event_time - timedelta(seconds=1), model="gpt-5.6-sol")
    _write_token_event(
        session,
        timestamp=event_time,
        reset=event_time + timedelta(days=7),
        used_percent=0,
        total_tokens=1_000,
        input_tokens=800,
        output_tokens=200,
        limit_id="codex_bengalfox",
    )

    usage = scan_local_codex_usage(tmp_path, _weekly_limit(reset), now=now)

    assert usage.tokens.total_tokens == 0
    assert usage.pending_tokens.total_tokens == 0


def test_missing_token_breakdown_marks_weighted_result_incomplete(tmp_path: Path) -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    reset = now + timedelta(days=6)
    event_time = now - timedelta(minutes=10)
    session = tmp_path / "sessions/2026/08/13/rollout-2026-08-13T12-00-00-dddddddd-dddd-dddd-dddd-dddddddddddd.jsonl"
    _write_model_context(session, timestamp=event_time - timedelta(seconds=1), model="gpt-5.6-luna")
    _write_token_event(
        session,
        timestamp=event_time,
        reset=reset,
        used_percent=2,
        total_tokens=21_060,
        cumulative_tokens=21_060,
    )

    usage = scan_local_codex_usage(tmp_path, _weekly_limit(reset), now=now)

    assert usage.tokens.total_tokens == 21_060
    assert not usage.weighted_complete
    assert usage.weighted_credits == 0
    assert usage.model_usage[0].weighted_credits is None


def test_compaction_placeholder_is_not_counted_as_token_usage(tmp_path: Path) -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    reset = now + timedelta(days=6)
    event_time = now - timedelta(minutes=10)
    session = tmp_path / "sessions/2026/08/13/rollout-2026-08-13T12-00-00-abababab-abab-abab-abab-abababababab.jsonl"
    _write_model_context(session, timestamp=event_time - timedelta(seconds=3), model="gpt-5.6-luna")
    _write_token_event(
        session,
        timestamp=event_time - timedelta(seconds=2),
        reset=reset,
        used_percent=2,
        total_tokens=1_000,
        input_tokens=800,
        output_tokens=200,
        cumulative_tokens=126_119_490,
    )
    _write_compaction_event(session, timestamp=event_time - timedelta(seconds=1))
    _write_token_event(
        session,
        timestamp=event_time,
        reset=reset,
        used_percent=0,
        total_tokens=21_060,
        cumulative_tokens=126_119_490,
        include_rate_limits=False,
    )

    usage = scan_local_codex_usage(tmp_path, _weekly_limit(reset), now=now)

    assert usage.tokens.total_tokens == 1_000
    assert usage.tokens.requests == 1
    assert usage.weighted_complete
    assert usage.weighted_credits > 0
    assert usage.model_usage[0].weighted_credits is not None


def test_compaction_placeholder_can_follow_replayed_metadata_and_rate_limits(tmp_path: Path) -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    reset = now + timedelta(days=6)
    event_time = now - timedelta(minutes=10)
    session = tmp_path / "sessions/2026/08/13/rollout-2026-08-13T12-00-00-cdcdcdcd-cdcd-cdcd-cdcd-cdcdcdcdcdcd.jsonl"
    _write_model_context(
        session,
        timestamp=event_time - timedelta(seconds=4),
        model="gpt-5.6-sol",
    )
    _write_token_event(
        session,
        timestamp=event_time - timedelta(seconds=3),
        reset=reset,
        used_percent=2,
        total_tokens=1_000,
        input_tokens=800,
        output_tokens=200,
        cumulative_tokens=126_119_490,
    )
    _write_compaction_event(session, timestamp=event_time - timedelta(seconds=2))
    _write_model_context(
        session,
        timestamp=event_time - timedelta(seconds=1),
        model="gpt-5.6-sol",
    )
    _write_token_event(
        session,
        timestamp=event_time,
        reset=event_time + timedelta(days=7),
        used_percent=0,
        total_tokens=31_030,
        cumulative_tokens=126_119_490,
        limit_id="codex_bengalfox",
    )

    usage = scan_local_codex_usage(tmp_path, _weekly_limit(reset), now=now)

    assert usage.tokens.total_tokens == 1_000
    assert usage.tokens.requests == 1
    assert usage.weighted_complete
    assert usage.model_usage[0].weighted_credits is not None


def test_compaction_does_not_hide_real_usage_when_cumulative_total_grows(tmp_path: Path) -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    reset = now + timedelta(days=6)
    event_time = now - timedelta(minutes=10)
    session = tmp_path / "sessions/2026/08/13/rollout-2026-08-13T12-00-00-dededede-dede-dede-dede-dededededede.jsonl"
    _write_model_context(session, timestamp=event_time - timedelta(seconds=3), model="gpt-5.6-sol")
    _write_token_event(
        session,
        timestamp=event_time - timedelta(seconds=2),
        reset=reset,
        used_percent=2,
        total_tokens=1_000,
        input_tokens=800,
        output_tokens=200,
        cumulative_tokens=5_000,
    )
    _write_compaction_event(session, timestamp=event_time - timedelta(seconds=1))
    _write_token_event(
        session,
        timestamp=event_time,
        reset=reset,
        used_percent=3,
        total_tokens=900,
        cumulative_tokens=5_900,
    )

    usage = scan_local_codex_usage(tmp_path, _weekly_limit(reset), now=now)

    assert usage.tokens.total_tokens == 1_900
    assert usage.tokens.requests == 2
    assert not usage.weighted_complete


def test_rollback_placeholder_with_unchanged_cumulative_usage_is_not_counted(tmp_path: Path) -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    reset = now + timedelta(days=6)
    event_time = now - timedelta(minutes=10)
    session = tmp_path / "sessions/2026/08/13/rollout-2026-08-13T12-00-00-efefefef-efef-efef-efef-efefefefefef.jsonl"
    _write_model_context(session, timestamp=event_time - timedelta(seconds=2), model="gpt-5.6-sol")
    _write_token_event(
        session,
        timestamp=event_time - timedelta(seconds=1),
        reset=reset,
        used_percent=2,
        total_tokens=1_000,
        input_tokens=800,
        output_tokens=200,
        cumulative_tokens=5_000,
        limit_id="codex_bengalfox",
    )
    _write_token_event(
        session,
        timestamp=event_time,
        reset=reset,
        used_percent=2,
        total_tokens=175_704,
        cumulative_tokens=5_000,
        limit_id="codex_bengalfox",
    )

    usage = scan_local_codex_usage(tmp_path, _weekly_limit(reset), now=now)

    assert usage.tokens.total_tokens == 1_000
    assert usage.tokens.requests == 1
    assert usage.weighted_complete
    assert usage.model_usage[0].weighted_credits is not None


def test_equal_usage_in_distinct_turns_is_not_mistaken_for_replay(tmp_path: Path) -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    reset = now + timedelta(days=6)
    session = tmp_path / "sessions/2026/08/13/rollout-2026-08-13T12-00-00-eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee.jsonl"
    for index, turn_id in enumerate(("turn-a", "turn-b")):
        timestamp = now - timedelta(minutes=10 - index)
        _write_model_context(
            session,
            timestamp=timestamp - timedelta(seconds=1),
            model="gpt-5.6-luna",
            turn_id=turn_id,
        )
        _write_token_event(
            session,
            timestamp=timestamp,
            reset=reset,
            used_percent=2,
            total_tokens=900,
            input_tokens=700,
            output_tokens=200,
            cumulative_tokens=12_345,
        )

    usage = scan_local_codex_usage(tmp_path, _weekly_limit(reset), now=now)

    assert usage.tokens.total_tokens == 1_800
    assert usage.tokens.requests == 2
    assert usage.duplicate_events == 0


def test_account_observation_gap_becomes_pending_instead_of_wrong_account(tmp_path: Path) -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    reset = now + timedelta(days=6)
    start = reset - timedelta(days=7)
    account_a = "a" * 24
    account_b = "b" * 24
    store = CodexAccountObservationStore(tmp_path / "account-observations.json")
    store.observe(account_a, start + timedelta(hours=1), inferred_started_at=start)
    store.observe(account_a, start + timedelta(hours=2))
    store.observe(account_b, start + timedelta(hours=4))
    store.observe(account_b, now)
    intervals = store.load()
    assert intervals[0].account_key == account_a
    assert intervals[0].ended_at == start + timedelta(hours=2)
    assert intervals[1].account_key == account_b
    assert intervals[1].started_at == start + timedelta(hours=4)

    session = tmp_path / "sessions/2026/08/13/rollout-2026-08-13T12-00-00-cccccccc-cccc-cccc-cccc-cccccccccccc.jsonl"
    _write_model_context(session, timestamp=start + timedelta(hours=3), model="gpt-5.6-sol")
    _write_token_event(
        session,
        timestamp=start + timedelta(hours=3, seconds=1),
        reset=reset,
        used_percent=2,
        total_tokens=700,
        cumulative_tokens=1_000,
    )
    _write_model_context(session, timestamp=start + timedelta(hours=4, minutes=1), model="gpt-5.6-sol")
    _write_token_event(
        session,
        timestamp=start + timedelta(hours=4, minutes=1, seconds=1),
        reset=reset,
        used_percent=3,
        total_tokens=900,
        cumulative_tokens=2_000,
    )

    usage = scan_local_codex_usage(
        tmp_path,
        _weekly_limit(reset),
        account_key=account_b,
        account_intervals=intervals,
        now=now,
    )

    assert usage.tokens.total_tokens == 900
    assert usage.pending_tokens.total_tokens == 700

    store = CodexManualAttributionStore(tmp_path / "manual-attributions.json")
    assert len(usage.pending_event_ids) == 1
    assert store.claim(account_b, int(reset.timestamp()), usage.pending_event_ids) == 1
    assert store.claim(account_b, int(reset.timestamp()), usage.pending_event_ids) == 0

    claimed = scan_local_codex_usage(
        tmp_path,
        _weekly_limit(reset),
        account_key=account_b,
        account_intervals=intervals,
        now=now,
        claimed_event_ids=store.claimed_event_ids(account_b, int(reset.timestamp())),
    )

    assert claimed.tokens.total_tokens == 1_600
    assert claimed.pending_tokens.total_tokens == 0
    assert claimed.pending_event_ids == ()


def test_new_observer_does_not_claim_previous_process_offline_gap(tmp_path: Path) -> None:
    path = tmp_path / "account-observations.json"
    account = "a" * 24
    first_seen = datetime.now(UTC).replace(microsecond=0) - timedelta(hours=2)
    first = CodexAccountObservationStore(path)
    first.observe(account, first_seen, inferred_started_at=first_seen - timedelta(hours=1))

    second = CodexAccountObservationStore(path)
    second.observe(account, first_seen + timedelta(hours=2))
    intervals = second.load()

    assert len(intervals) == 2
    assert intervals[0].last_seen_at == first_seen
    assert intervals[1].started_at == first_seen + timedelta(hours=2)


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
        model_usage=(CodexModelUsage("gpt-5.5", uses=2, total_tokens=1_000),),
        reasoning_usage=(CodexReasoningUsage("high", uses=2),),
    )
    replacement = replace(first, total_tokens=1_500, requests=3)
    other_account = replace(first, account_key="b" * 24, device_id="laptop-b")
    other_window = replace(first, device_id="laptop-c", window_resets_at=2_000_100_000)

    store.save(first)
    store.save(replacement)
    store.save(replace(replacement, window_resets_at=2_000_000_005, total_tokens=1_600))
    store.save(other_account)
    store.save(other_window)

    matching = store.load(
        account_key="a" * 24,
        window_resets_at=2_000_000_000,
    )
    assert len(matching) == 1
    assert matching[0].device_id == "laptop-a"
    assert matching[0].tokens.total_tokens == 1_600
    assert matching[0].tokens.requests == 3
    assert matching[0].model_usage[0].model == "gpt-5.5"
    assert matching[0].reasoning_usage == (CodexReasoningUsage("high", uses=2),)
    assert len(store.load()) == 3


def test_history_treats_small_reset_jitter_as_one_cycle(tmp_path: Path) -> None:
    responses, _reset = _responses(tmp_path)
    report = CodexUsageClient(Path("/fake/codex"), transport=lambda *_args: responses).fetch_report()
    window = report.primary_limit.primary
    assert window is not None and window.resets_at is not None
    jittered_limit = replace(
        report.primary_limit,
        primary=replace(window, resets_at=window.resets_at + timedelta(seconds=1)),
    )
    jittered = replace(
        report,
        rate_limits=(jittered_limit,),
        primary_limit=jittered_limit,
        fetched_at=report.fetched_at + timedelta(seconds=1),
    )
    store = CodexUsageHistoryStore(tmp_path / "history.json")

    store.save_report(report)
    store.save_report(jittered)

    assert len(store.load_cycles(report.account.key)) == 1


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
