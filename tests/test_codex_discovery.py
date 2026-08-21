"""Codex 安装证据、数据目录与日志可用性发现测试。"""

from __future__ import annotations

from datetime import date
import json
from pathlib import Path

from petnest.core.codex_discovery import (
    CodexAvailabilityState,
    CodexDiscoveryService,
    CodexHomeCandidate,
    CodexHomeDiscovery,
    CodexInstallationDetector,
    CodexLogSourceProbe,
    normalize_selected_codex_home,
)


TODAY = date(2026, 8, 21)


def _session_path(home: Path, name: str = "rollout-session.jsonl") -> Path:
    path = home / "sessions" / "2026" / "08" / "21" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _write_session(path: Path, *, session_id: str | None = "session-1") -> None:
    payload = {} if session_id is None else {"session_id": session_id}
    path.write_text(
        json.dumps({"type": "session_meta", "payload": payload})
        + "\n"
        + json.dumps(
            {
                "type": "event_msg",
                "payload": {"type": "task_started", "turn_id": "turn-1"},
            }
        )
        + "\n",
        encoding="utf-8",
    )


def test_probe_reports_ready_only_after_validating_session_structure(tmp_path: Path) -> None:
    home = tmp_path / ".codex"
    _write_session(_session_path(home))

    result = CodexLogSourceProbe(today=lambda: TODAY).probe(
        CodexHomeCandidate(home, source="default", manual=False)
    )

    assert result.state is CodexAvailabilityState.READY
    assert result.can_watch is True
    assert result.sessions_path == (home / "sessions").resolve()


def test_probe_distinguishes_waiting_for_sessions_from_not_codex(tmp_path: Path) -> None:
    home = tmp_path / ".codex"
    home.mkdir()

    result = CodexLogSourceProbe(today=lambda: TODAY).probe(
        CodexHomeCandidate(home, source="app-server", manual=False)
    )

    assert result.state is CodexAvailabilityState.WAITING_FOR_SESSIONS
    assert result.can_watch is True


def test_probe_marks_missing_session_id_incompatible(tmp_path: Path) -> None:
    home = tmp_path / ".codex"
    _write_session(_session_path(home, "not-a-uuid.jsonl"), session_id=None)

    result = CodexLogSourceProbe(today=lambda: TODAY).probe(
        CodexHomeCandidate(home, source="default", manual=False)
    )

    assert result.state is CodexAvailabilityState.INCOMPATIBLE
    assert result.can_watch is False
    assert "session_id" in result.technical_reason


def test_probe_accepts_new_session_with_only_valid_metadata(tmp_path: Path) -> None:
    home = tmp_path / ".codex"
    path = _session_path(home)
    path.write_text(
        json.dumps({"type": "session_meta", "payload": {"session_id": "session-new"}}) + "\n",
        encoding="utf-8",
    )

    result = CodexLogSourceProbe(today=lambda: TODAY).probe(
        CodexHomeCandidate(home, source="app-server", manual=False)
    )

    assert result.state is CodexAvailabilityState.READY
    assert result.can_watch is True


def test_probe_distinguishes_unreadable_file_from_incompatible_json(
    tmp_path: Path,
    monkeypatch,
) -> None:
    home = tmp_path / ".codex"
    _write_session(_session_path(home))

    def deny_open(_path: Path, *_args, **_kwargs):
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "open", deny_open)
    result = CodexLogSourceProbe(today=lambda: TODAY).probe(
        CodexHomeCandidate(home, source="default", manual=False)
    )

    assert result.state is CodexAvailabilityState.UNREADABLE
    assert result.can_watch is False


def test_home_discovery_keeps_app_server_candidate_when_stale_default_exists(tmp_path: Path) -> None:
    default = tmp_path / ".codex"
    actual = tmp_path / "profiles" / "current"
    default.mkdir()
    actual.mkdir(parents=True)
    discovery = CodexHomeDiscovery(
        environment={},
        user_home=tmp_path,
        app_home_provider=lambda: actual,
    )

    candidates = discovery.candidates(None)

    assert [item.home for item in candidates] == [actual.resolve(), default.resolve()]
    assert [item.source for item in candidates] == ["app-server", "default"]


def test_environment_home_precedes_app_server_without_hiding_other_candidates(tmp_path: Path) -> None:
    configured = tmp_path / "configured"
    actual = tmp_path / "actual"
    configured.mkdir()
    actual.mkdir()
    discovery = CodexHomeDiscovery(
        environment={"CODEX_HOME": str(configured)},
        user_home=tmp_path,
        app_home_provider=lambda: actual,
    )

    candidates = discovery.candidates(None)

    assert candidates[0] == CodexHomeCandidate(configured.resolve(), "environment", False)
    assert any(item == CodexHomeCandidate(actual.resolve(), "app-server", False) for item in candidates)


def test_broken_environment_home_does_not_hide_compatible_app_server_profile(tmp_path: Path) -> None:
    configured = tmp_path / "missing-configured"
    actual = tmp_path / "actual"
    _write_session(_session_path(actual))
    service = CodexDiscoveryService(
        CodexInstallationDetector(
            platform_name="linux",
            environment={"CODEX_HOME": str(configured)},
            user_home=tmp_path,
            which=lambda _name: None,
        ),
        CodexHomeDiscovery(
            environment={"CODEX_HOME": str(configured)},
            user_home=tmp_path,
            app_home_provider=lambda: actual,
        ),
        CodexLogSourceProbe(today=lambda: TODAY),
    )

    availability = service.discover(None)

    assert availability.state is CodexAvailabilityState.READY
    assert availability.selected_home == actual.resolve()


def test_windows_detector_prefers_desktop_exe_over_path_cmd(tmp_path: Path) -> None:
    local_app_data = tmp_path / "LocalAppData"
    desktop = local_app_data / "OpenAI" / "Codex" / "bin" / "v1" / "codex.exe"
    desktop.parent.mkdir(parents=True)
    desktop.write_bytes(b"exe")
    detector = CodexInstallationDetector(
        platform_name="win32",
        environment={"LOCALAPPDATA": str(local_app_data)},
        user_home=tmp_path,
        which=lambda _name: str(tmp_path / "node" / "codex.CMD"),
    )

    evidence = detector.detect()

    assert evidence[0].kind == "desktop"
    assert evidence[0].path == desktop.resolve()
    assert any(item.kind == "cli" for item in evidence)


def test_macos_detector_finds_system_and_user_app_bundles(tmp_path: Path) -> None:
    system_root = tmp_path / "Applications"
    user_root = tmp_path / "Users" / "me" / "Applications"
    system_app = system_root / "Codex.app"
    user_app = user_root / "Codex.app"
    system_app.mkdir(parents=True)
    user_app.mkdir(parents=True)
    for app in (system_app, user_app):
        executable = app / "Contents" / "MacOS" / "Codex"
        executable.parent.mkdir(parents=True)
        executable.write_bytes(b"executable")
        executable.chmod(0o755)
    detector = CodexInstallationDetector(
        platform_name="darwin",
        environment={},
        user_home=tmp_path / "Users" / "me",
        application_roots=(system_root, user_root),
        which=lambda _name: None,
    )

    evidence = detector.detect()

    assert {item.path for item in evidence if item.kind == "desktop"} == {
        system_app.resolve(),
        user_app.resolve(),
    }


def test_macos_empty_app_bundle_is_not_strong_install_evidence(tmp_path: Path) -> None:
    app_root = tmp_path / "Applications"
    (app_root / "Codex.app").mkdir(parents=True)
    detector = CodexInstallationDetector(
        platform_name="darwin",
        environment={},
        user_home=tmp_path,
        application_roots=(app_root,),
        which=lambda _name: None,
    )

    assert not any(item.kind == "desktop" for item in detector.detect())


def _service(tmp_path: Path, *, app_home: Path | None) -> CodexDiscoveryService:
    return CodexDiscoveryService(
        CodexInstallationDetector(
            platform_name="linux",
            environment={},
            user_home=tmp_path,
            which=lambda _name: None,
        ),
        CodexHomeDiscovery(
            environment={},
            user_home=tmp_path,
            app_home_provider=lambda: app_home,
        ),
        CodexLogSourceProbe(today=lambda: TODAY),
    )


def test_service_selects_compatible_candidate_instead_of_first_existing_directory(tmp_path: Path) -> None:
    stale = tmp_path / ".codex"
    actual = tmp_path / "profile"
    stale.mkdir()
    _write_session(_session_path(actual))

    availability = _service(tmp_path, app_home=actual).discover(None)

    assert availability.state is CodexAvailabilityState.READY
    assert availability.selected_home == actual.resolve()
    assert availability.codex_detected is True


def test_invalid_manual_home_is_reported_without_switching_to_auto_candidate(tmp_path: Path) -> None:
    actual = tmp_path / "auto"
    _write_session(_session_path(actual))
    manual = tmp_path / "missing-manual"

    availability = _service(tmp_path, app_home=actual).discover(manual)

    assert availability.state is CodexAvailabilityState.NOT_DETECTED
    assert availability.selected_home == manual.resolve()
    assert availability.manual_override is True
    assert "自动查找另有可用目录" in availability.technical_reason


def test_selecting_sessions_directory_normalizes_to_codex_home(tmp_path: Path) -> None:
    home = tmp_path / ".codex"
    (home / "sessions").mkdir(parents=True)

    normalized = normalize_selected_codex_home(home / "sessions")

    assert normalized == home.resolve()


def test_stale_data_without_install_evidence_is_not_reported_as_detected_codex(tmp_path: Path) -> None:
    (tmp_path / ".codex").mkdir()

    availability = _service(tmp_path, app_home=None).discover(None)

    assert availability.state is CodexAvailabilityState.DATA_ONLY
    assert availability.codex_detected is False
    assert availability.can_watch is False


def test_manual_home_without_sessions_is_accepted_and_waits_for_first_task(tmp_path: Path) -> None:
    manual = tmp_path / "manual-home"
    manual.mkdir()
    (manual / "config.toml").write_text("model = 'test'\n", encoding="utf-8")

    availability = _service(tmp_path, app_home=None).discover(manual)

    assert availability.state is CodexAvailabilityState.WAITING_FOR_SESSIONS
    assert availability.can_watch is True
    assert availability.message == "已选择 Codex 数据目录，等待 Codex 创建本地任务"


def test_arbitrary_empty_manual_folder_is_rejected_as_not_codex_home(tmp_path: Path) -> None:
    manual = tmp_path / "ordinary-folder"
    manual.mkdir()

    availability = _service(tmp_path, app_home=None).discover(manual)

    assert availability.state is CodexAvailabilityState.NOT_DETECTED
    assert availability.manual_override is True
    assert availability.can_watch is False
    assert "Codex 配置标记" in availability.technical_reason


def test_newest_incompatible_session_is_not_hidden_by_older_compatible_file(tmp_path: Path) -> None:
    home = tmp_path / ".codex"
    yesterday = home / "sessions" / "2026" / "08" / "20" / "rollout-old.jsonl"
    yesterday.parent.mkdir(parents=True)
    _write_session(yesterday)
    newest = _session_path(home, "rollout-new.jsonl")
    newest.write_text(
        json.dumps({"type": "session_meta", "payload": {}}) + "\n",
        encoding="utf-8",
    )

    availability = CodexLogSourceProbe(today=lambda: TODAY).probe(
        CodexHomeCandidate(home, "default", False)
    )

    assert availability.state is CodexAvailabilityState.INCOMPATIBLE
    assert "rollout-new.jsonl" in availability.technical_reason


def test_probe_reports_unreadable_when_session_directory_cannot_be_enumerated(
    tmp_path: Path,
    monkeypatch,
) -> None:
    home = tmp_path / ".codex"
    day = home / "sessions" / "2026" / "08" / "21"
    day.mkdir(parents=True)

    def deny_glob(_path: Path, _pattern: str):
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "glob", deny_glob)
    availability = CodexLogSourceProbe(today=lambda: TODAY).probe(
        CodexHomeCandidate(home, "default", False)
    )

    assert availability.state is CodexAvailabilityState.UNREADABLE


def test_probe_rejects_codex_home_symlink(tmp_path: Path) -> None:
    actual = tmp_path / "actual"
    _write_session(_session_path(actual))
    linked = tmp_path / "linked"
    try:
        linked.symlink_to(actual, target_is_directory=True)
    except OSError:
        return

    availability = CodexLogSourceProbe(today=lambda: TODAY).probe(
        CodexHomeCandidate(linked, "manual", True)
    )

    assert availability.state is CodexAvailabilityState.UNREADABLE
    assert "链接" in availability.technical_reason


def test_probe_rejects_intermediate_session_symlink(tmp_path: Path) -> None:
    home = tmp_path / ".codex"
    outside = tmp_path / "outside-year"
    target_day = outside / "08" / "21"
    target_day.mkdir(parents=True)
    _write_session(target_day / "rollout-outside.jsonl")
    sessions = home / "sessions"
    sessions.mkdir(parents=True)
    try:
        (sessions / "2026").symlink_to(outside, target_is_directory=True)
    except OSError:
        return

    availability = CodexLogSourceProbe(today=lambda: TODAY).probe(
        CodexHomeCandidate(home, "default", False)
    )

    assert availability.state is CodexAvailabilityState.UNREADABLE
    assert "链接" in availability.technical_reason
