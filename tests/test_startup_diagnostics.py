"""冻结版启动失败时的可见诊断测试。"""

from __future__ import annotations

from pathlib import Path

import petnest_startup
from petnest_startup import default_user_log_directory, run_application, write_startup_report


def test_default_user_log_directory_uses_local_app_data_on_windows(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(petnest_startup.sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))

    assert default_user_log_directory() == tmp_path / "LocalAppData" / "PetNest" / "logs"


def test_startup_report_writes_traceback_to_user_and_writable_executable_directories(tmp_path: Path) -> None:
    user_logs = tmp_path / "user" / "logs"
    executable_directory = tmp_path / "installed"

    try:
        raise RuntimeError("Qt platform plugin is unavailable")
    except RuntimeError as error:
        report_paths = write_startup_report(error, user_logs, executable_directory)

    assert report_paths == (
        user_logs / "PetNest-startup.log",
        executable_directory / "PetNest-startup.log",
    )
    for report_path in report_paths:
        content = report_path.read_text(encoding="utf-8")
        assert "PetNest 启动失败诊断" in content
        assert "RuntimeError: Qt platform plugin is unavailable" in content


def test_launcher_catches_import_errors_and_reports_them() -> None:
    reported: list[Exception] = []

    def fail_to_load_main() -> object:
        raise ImportError("PySide6 is missing")

    result = run_application(
        entrypoint_loader=fail_to_load_main,
        failure_reporter=reported.append,
    )

    assert result == 1
    assert len(reported) == 1
    assert isinstance(reported[0], ImportError)
    assert str(reported[0]) == "PySide6 is missing"
