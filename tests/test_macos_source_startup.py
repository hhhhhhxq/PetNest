from __future__ import annotations

import plistlib
import subprocess
from pathlib import Path

import pytest

from petnest.platforms.macos_source_startup import MacOSSourceLoginItem, SOURCE_STARTUP_LABEL


@pytest.fixture
def source_item(tmp_path):
    root = tmp_path / "项目 with spaces & quotes'"
    entry = root / "src" / "petnest" / "__main__.py"
    entry.parent.mkdir(parents=True)
    entry.touch()
    (root / "pyproject.toml").touch()
    python = root / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.touch()
    python.chmod(0o700)
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, "", "")

    item = MacOSSourceLoginItem(
        project_root=root, python_executable=python, home=tmp_path / "user",
        uid=501, runner=runner,
    )
    return item, calls


def test_source_plist_uses_absolute_venv_and_no_shell_or_keepalive(source_item):
    item, calls = source_item
    assert item.supported
    assert item.configure(True).success
    definition = plistlib.loads(item.plist_path.read_bytes())
    assert definition["ProgramArguments"] == [str(item.python_executable), "-m", "petnest"]
    assert definition["WorkingDirectory"] == str(item.project_root)
    assert definition["EnvironmentVariables"] == {"PYTHONPATH": str(item.project_root / "src")}
    assert definition["RunAtLoad"] is True
    assert definition["LimitLoadToSessionType"] == "Aqua"
    assert "KeepAlive" not in definition
    assert item.plist_path.stat().st_mode & 0o777 == 0o600
    assert Path(definition["StandardErrorPath"]).parent.is_dir()
    assert calls[0][0] == ["/bin/launchctl", "enable", f"gui/501/{SOURCE_STARTUP_LABEL}"]
    assert calls[0][1]["timeout"] == 10


def test_registration_is_idempotent_and_disable_never_kills_current_app(source_item):
    item, calls = source_item
    assert item.configure(True).success
    contents = item.plist_path.read_bytes()
    assert item.configure(True).success
    assert item.plist_path.read_bytes() == contents
    unrelated = item.plist_path.parent / "another-app.plist"
    unrelated.write_bytes(b"untouched")
    assert item.configure(False).success
    assert not item.plist_path.exists()
    assert item.configure(False).success
    assert unrelated.read_bytes() == b"untouched"
    assert [command[1] for command, _ in calls] == ["enable", "enable", "disable", "disable"]


def test_missing_runtime_can_still_unregister(source_item):
    item, calls = source_item
    assert item.configure(True).success
    item.python_executable.unlink()
    assert not item.supported
    assert not item.configure(True).success
    assert item.configure(False).success
    assert len(calls) == 2


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("failure", ["returncode", "timeout", "oserror"])
def test_failed_enable_restores_previous_registration(source_item, existing, failure):
    item, _ = source_item
    if existing:
        item.plist_path.parent.mkdir(parents=True)
        item.plist_path.write_bytes(b"previous registration")

    def fail(command, **kwargs):
        if failure == "timeout":
            raise subprocess.TimeoutExpired(command, 10)
        if failure == "oserror":
            raise OSError("permission denied")
        return subprocess.CompletedProcess(command, 1, "", "permission denied")

    item._runner = fail
    assert not item.configure(True).success
    if existing:
        assert item.plist_path.read_bytes() == b"previous registration"
    else:
        assert not item.plist_path.exists()


def test_failed_disable_keeps_registration_file(source_item):
    item, _ = source_item
    assert item.configure(True).success
    original = item.plist_path.read_bytes()
    item._runner = lambda command, **kwargs: subprocess.CompletedProcess(command, 1, "", "denied")
    assert not item.configure(False).success
    assert item.plist_path.read_bytes() == original


def test_venv_symlink_is_not_resolved_to_global_python(source_item):
    item, _ = source_item
    original_path = item.python_executable
    actual = item.project_root / "global-python"
    item.python_executable.rename(actual)
    original_path.symlink_to(actual)
    assert item.configure(True).success
    assert plistlib.loads(item.plist_path.read_bytes())["ProgramArguments"][0] == str(original_path)


def test_filesystem_failure_returns_actionable_error(source_item, monkeypatch):
    item, calls = source_item

    def fail(_contents):
        raise PermissionError("LaunchAgents not writable")

    monkeypatch.setattr(item, "_write", fail)
    result = item.configure(True)
    assert not result.success
    assert "LaunchAgents not writable" in result.message
    assert calls == []
