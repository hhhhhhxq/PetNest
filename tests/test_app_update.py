"""应用安装包更新协议的安全边界测试。"""

from __future__ import annotations

import hashlib
import io
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError

import pytest

from petnest.core.app_update import (
    AppUpdateClient,
    AppUpdateCheckResult,
    AppUpdateCoordinator,
    AppUpdateError,
    AppUpdateInfo,
    build_updater_command,
    parse_update_manifest,
)
from petnest.core import windows_updater
from petnest.core.windows_updater import UpdaterArguments, parse_updater_args, run_installer


def _manifest(
    *,
    version: str = "0.2.0",
    platform: str = "windows-x64",
    url: str = "https://github.com/hhhhhhxq/PetNest/releases/download/v0.2.0/PetNest-Setup-0.2.0.exe",
    size: int = 4,
    sha256: str = "0" * 64,
) -> bytes:
    return json.dumps(
        {
            "schema_version": 1,
            "version": version,
            "platform": platform,
            "asset": {"url": url, "size": size, "sha256": sha256},
            "release_notes": "修复若干问题",
        }
    ).encode("utf-8")


def test_parse_manifest_accepts_new_windows_release() -> None:
    result = parse_update_manifest(_manifest(), current_version="0.1.0", platform_name="win32")

    assert isinstance(result, AppUpdateInfo)
    assert result.version == "0.2.0"
    assert result.asset.size == 4
    assert result.release_notes == "修复若干问题"


def test_parse_manifest_accepts_new_macos_release() -> None:
    result = parse_update_manifest(
        _manifest(
            platform="macos-x64",
            url="https://github.com/hhhhhhxq/PetNest/releases/download/v0.2.0/PetNest-macOS-x64-0.2.0.zip",
        ),
        current_version="0.1.0",
        platform_name="darwin",
    )

    assert isinstance(result, AppUpdateInfo)
    assert result.platform == "macos-x64"


@pytest.mark.parametrize(
    ("version", "platform"),
    [("0.1.0", "windows-x64"), ("0.0.9", "windows-x64"), ("0.2.0", "darwin")],
)
def test_manifest_ignores_not_new_or_wrong_platform(version: str, platform: str) -> None:
    assert parse_update_manifest(_manifest(version=version, platform=platform), current_version="0.1.0", platform_name="win32") is None


@pytest.mark.parametrize(
    "changes",
    [
        {"asset": {"url": "http://github.com/a.exe"}},
        {"asset": {"url": "https://example.com/a.exe"}},
        {"asset": {"url": "https://github.com:bad-port/a.exe"}},
        {"asset": {"size": 0}},
        {"asset": {"sha256": "not-a-sha"}},
        {"version": "not-semver"},
        {"platform": ["windows-x64"]},
        {"schema_version": 2},
        {"schema_version": True},
    ],
)
def test_manifest_rejects_unsafe_or_malformed_values(changes: dict[str, object]) -> None:
    payload = json.loads(_manifest())
    if "asset" in changes:
        payload["asset"].update(changes["asset"])
        changes = {key: value for key, value in changes.items() if key != "asset"}
    payload.update(changes)

    with pytest.raises(AppUpdateError):
        parse_update_manifest(json.dumps(payload).encode(), current_version="0.1.0", platform_name="win32")


class _Response:
    def __init__(self, data: bytes, *, headers: dict[str, str] | None = None) -> None:
        self._stream = io.BytesIO(data)
        self.headers = headers or {}

    def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)

    def close(self) -> None:
        self._stream.close()

    def geturl(self) -> str:
        return "https://github.com/hhhhhhxq/PetNest/releases/latest/download/app-update.json"


class _BrokenResponse(_Response):
    def read(self, size: int = -1) -> bytes:
        del size
        raise RuntimeError("连接中断")


class _RedirectedResponse(_Response):
    def geturl(self) -> str:
        return "https://example.com/installer.exe"


def test_client_checks_manifest_without_blocking_contract() -> None:
    payload = _manifest()
    calls: list[object] = []

    def opener(request: object, timeout: float) -> _Response:
        calls.append((request, timeout))
        return _Response(payload)

    client = AppUpdateClient(
        manifest_url="https://github.com/hhhhhhxq/PetNest/releases/latest/download/app-update.json",
        current_version="0.1.0",
        platform_name="win32",
        opener=opener,
    )

    assert client.check() is not None
    assert calls


def test_client_explains_when_latest_release_has_no_platform_manifest() -> None:
    def opener(request: object, timeout: float) -> object:
        del request, timeout
        raise HTTPError(
            "https://github.com/hhhhhhxq/PetNest/releases/latest/download/app-update.json",
            404,
            "Not Found",
            hdrs=None,
            fp=io.BytesIO(),
        )

    client = AppUpdateClient(platform_name="win32", opener=opener)

    with pytest.raises(AppUpdateError, match="Windows.*更新清单"):
        client.check()


def test_client_rejects_redirect_outside_github_release_hosts() -> None:
    client = AppUpdateClient(
        platform_name="win32",
        opener=lambda request, timeout: _RedirectedResponse(_manifest()),
    )

    with pytest.raises(AppUpdateError):
        client.check()


def test_unsupported_platform_client_is_a_noop_and_does_not_open_network() -> None:
    def fail_opener(*args: object, **kwargs: object) -> object:
        raise AssertionError("不支持的平台不应请求 Release")

    client = AppUpdateClient(platform_name="linux", opener=fail_opener)

    assert client.check() is None


def test_download_verifies_sha_and_replaces_atomically(tmp_path: Path) -> None:
    body = b"setup"
    digest = hashlib.sha256(body).hexdigest()
    info = parse_update_manifest(
        _manifest(size=len(body), sha256=digest), current_version="0.1.0", platform_name="win32"
    )
    assert info is not None
    destination = tmp_path / "PetNest-Setup.exe"

    client = AppUpdateClient(
        current_version="0.1.0",
        platform_name="win32",
        opener=lambda request, timeout: _Response(body),
    )
    client.download(info, destination)

    assert destination.read_bytes() == body
    assert not destination.with_name(destination.name + ".part").exists()


def test_download_rejects_oversize_and_cleans_partial_file(tmp_path: Path) -> None:
    body = b"too large"
    info = parse_update_manifest(
        _manifest(size=1, sha256=hashlib.sha256(body).hexdigest()),
        current_version="0.1.0",
        platform_name="win32",
    )
    assert info is not None
    destination = tmp_path / "PetNest-Setup.exe"
    client = AppUpdateClient(
        current_version="0.1.0",
        platform_name="win32",
        opener=lambda request, timeout: _Response(body),
    )

    with pytest.raises(AppUpdateError):
        client.download(info, destination)

    assert not destination.exists()
    assert not destination.with_name(destination.name + ".part").exists()


def test_download_cleans_partial_file_when_stream_raises_unexpected_error(tmp_path: Path) -> None:
    body = b"setup"
    info = parse_update_manifest(
        _manifest(size=len(body), sha256=hashlib.sha256(body).hexdigest()),
        current_version="0.1.0",
        platform_name="win32",
    )
    assert info is not None
    destination = tmp_path / "PetNest-Setup.exe"
    client = AppUpdateClient(
        current_version="0.1.0",
        platform_name="win32",
        opener=lambda request, timeout: _BrokenResponse(body),
    )

    with pytest.raises(AppUpdateError):
        client.download(info, destination)

    assert not destination.with_name(destination.name + ".part").exists()


def test_updater_command_uses_argument_list_and_validates_pid(tmp_path: Path) -> None:
    command = build_updater_command(
        tmp_path / "PetNestUpdater.exe",
        tmp_path / "PetNest-Setup.exe",
        parent_pid=123,
        restart_path=tmp_path / "PetNest.exe",
    )

    assert command == [
        str(tmp_path / "PetNestUpdater.exe"),
        "--wait-pid",
        "123",
        "--installer",
        str(tmp_path / "PetNest-Setup.exe"),
        "--restart",
        str(tmp_path / "PetNest.exe"),
    ]
    assert build_updater_command(tmp_path / "u.exe", tmp_path / "i.exe", parent_pid=123) == [
        str(tmp_path / "u.exe"),
        "--wait-pid",
        "123",
        "--installer",
        str(tmp_path / "i.exe"),
    ]
    with pytest.raises(AppUpdateError):
        build_updater_command(tmp_path / "u.exe", tmp_path / "i.exe", parent_pid=0)


def test_updater_args_reject_relative_paths_and_invalid_pid(tmp_path: Path) -> None:
    parsed = parse_updater_args(
        [
            "--wait-pid",
            "123",
            "--installer",
            str(tmp_path / "PetNest-Setup.exe"),
            "--restart",
            str(tmp_path / "PetNest.exe"),
        ]
    )
    assert parsed.wait_pid == 123
    assert parsed.installer == tmp_path / "PetNest-Setup.exe"
    assert parsed.restart == tmp_path / "PetNest.exe"
    with pytest.raises(AppUpdateError):
        parse_updater_args(["--wait-pid", "0", "--installer", str(tmp_path / "i.exe")])
    with pytest.raises(AppUpdateError):
        parse_updater_args(["--wait-pid", "1", "--installer", "relative.exe"])


def test_run_installer_delegates_to_elevated_launcher(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    installer = tmp_path / "PetNest-Setup.exe"
    installer.write_bytes(b"installer")
    launched: list[Path] = []
    monkeypatch.setattr("petnest.core.windows_updater.sys.platform", "win32")
    monkeypatch.setattr("petnest.core.windows_updater.wait_for_process_exit", lambda _pid: True)
    monkeypatch.setattr(
        "petnest.core.windows_updater._run_elevated_installer",
        lambda path: launched.append(path) or 0,
        raising=False,
    )

    assert run_installer(UpdaterArguments(123, installer)) == 0
    assert launched == [installer]


def test_stage_windows_updater_copies_it_outside_the_install_directory(tmp_path: Path) -> None:
    install_directory = tmp_path / "installed" / "PetNest"
    install_directory.mkdir(parents=True)
    source = install_directory / "PetNestUpdateHost.exe"
    source.write_bytes(b"updater")
    staging_directory = tmp_path / "downloads"
    staging_directory.mkdir()
    stale = staging_directory / "PetNestUpdateHost-stale.exe"
    stale.write_bytes(b"stale")

    staged = windows_updater.stage_windows_updater(source, staging_directory)

    assert staged.parent == staging_directory
    assert staged != source
    assert staged.name.startswith("PetNestUpdateHost-")
    assert staged.read_bytes() == b"updater"
    assert source.read_bytes() == b"updater"
    assert not stale.exists()


def test_run_installer_restarts_petnest_after_a_failed_install(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    installer = tmp_path / "PetNest-Setup.exe"
    installer.write_bytes(b"installer")
    restart = tmp_path / "PetNest.exe"
    restart.write_bytes(b"application")
    restarted: list[tuple[list[str], str]] = []
    monkeypatch.setattr("petnest.core.windows_updater.sys.platform", "win32")
    monkeypatch.setattr("petnest.core.windows_updater.wait_for_process_exit", lambda _pid: True)
    monkeypatch.setattr("petnest.core.windows_updater._run_elevated_installer", lambda _path: 2)
    monkeypatch.setattr(
        "petnest.core.windows_updater.subprocess.Popen",
        lambda command, **kwargs: restarted.append((command, kwargs["cwd"])),
    )

    assert run_installer(UpdaterArguments(123, installer, restart)) == 2
    assert restarted == [([str(restart)], str(restart.parent))]


def test_run_installer_does_not_restart_while_the_installer_is_still_running(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    installer = tmp_path / "PetNest-Setup.exe"
    installer.write_bytes(b"installer")
    restart = tmp_path / "PetNest.exe"
    restart.write_bytes(b"application")
    restarted: list[list[str]] = []
    monkeypatch.setattr("petnest.core.windows_updater.sys.platform", "win32")
    monkeypatch.setattr("petnest.core.windows_updater.wait_for_process_exit", lambda _pid: True)
    monkeypatch.setattr(
        "petnest.core.windows_updater._run_elevated_installer",
        lambda _path: (_ for _ in ()).throw(windows_updater.InstallerProcessNotExitedError("still running")),
    )
    monkeypatch.setattr(
        "petnest.core.windows_updater.subprocess.Popen",
        lambda command, **_kwargs: restarted.append(command),
    )

    with pytest.raises(windows_updater.InstallerProcessNotExitedError):
        run_installer(UpdaterArguments(123, installer, restart))
    assert restarted == []


def test_run_installer_restarts_petnest_when_uac_launch_is_cancelled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    installer = tmp_path / "PetNest-Setup.exe"
    installer.write_bytes(b"installer")
    restart = tmp_path / "PetNest.exe"
    restart.write_bytes(b"application")
    restarted: list[list[str]] = []
    monkeypatch.setattr("petnest.core.windows_updater.sys.platform", "win32")
    monkeypatch.setattr("petnest.core.windows_updater.wait_for_process_exit", lambda _pid: True)
    monkeypatch.setattr(
        "petnest.core.windows_updater._run_elevated_installer",
        lambda _path: (_ for _ in ()).throw(AppUpdateError("UAC cancelled")),
    )
    monkeypatch.setattr(
        "petnest.core.windows_updater.subprocess.Popen",
        lambda command, **_kwargs: restarted.append(command),
    )

    with pytest.raises(AppUpdateError, match="UAC cancelled"):
        run_installer(UpdaterArguments(123, installer, restart))
    assert restarted == [[str(restart)]]


class _FakeUpdateClient:
    def __init__(self, info: AppUpdateInfo | None) -> None:
        self.info = info
        self.calls = 0

    def check(self) -> AppUpdateInfo | None:
        self.calls += 1
        return self.info


def test_update_coordinator_throttles_background_checks_but_force_bypasses(tmp_path: Path) -> None:
    now = datetime(2026, 8, 11, tzinfo=UTC)
    client = _FakeUpdateClient(
        parse_update_manifest(_manifest(), current_version="0.1.0", platform_name="win32")
    )
    coordinator = AppUpdateCoordinator(
        client,
        tmp_path / "app-update-state.json",
        now=lambda: now,
    )

    first = coordinator.check()
    skipped = coordinator.check()
    forced = coordinator.check(force=True)

    assert isinstance(first, AppUpdateCheckResult)
    assert first.checked and first.update is not None
    assert skipped.skipped and not skipped.checked
    assert forced.checked and forced.update is not None
    assert client.calls == 2

    later = now + timedelta(hours=24)
    coordinator.now = lambda: later
    assert coordinator.should_check()
