from __future__ import annotations

from pathlib import Path
from subprocess import CompletedProcess
from xml.etree import ElementTree

import pytest

from petnest.platforms.windows_startup import (
    LEGACY_TASK_NAME,
    TASK_NAME_PREFIX,
    WindowsStartupTask,
    build_task_xml,
    task_name_for_sid,
)


TASK_NAMESPACE = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}


@pytest.fixture(autouse=True)
def _isolate_startup_host_cancellation(monkeypatch) -> None:
    monkeypatch.setattr(
        "petnest.platforms.windows_startup.cancel_running_hosts",
        lambda: None,
        raising=False,
    )


def test_task_xml_uses_login_trigger_least_privilege_and_startup_host() -> None:
    contents = build_task_xml(
        Path(r"C:\Program Files\PetNest\PetNestStartupHost.exe"),
        "S-1-5-21-1000",
    )
    root = ElementTree.fromstring(contents)

    assert LEGACY_TASK_NAME == r"\PetNest\AutoStart"
    assert task_name_for_sid("S-1-5-21-1000") == r"\PetNest\AutoStart-S-1-5-21-1000"
    assert root.findtext(".//t:LogonTrigger/t:UserId", namespaces=TASK_NAMESPACE) == "S-1-5-21-1000"
    assert root.findtext(".//t:LogonType", namespaces=TASK_NAMESPACE) == "InteractiveToken"
    assert root.findtext(".//t:RunLevel", namespaces=TASK_NAMESPACE) == "LeastPrivilege"
    assert root.findtext(".//t:MultipleInstancesPolicy", namespaces=TASK_NAMESPACE) == "IgnoreNew"
    assert root.findtext(".//t:StartWhenAvailable", namespaces=TASK_NAMESPACE) == "true"
    assert root.findtext(".//t:DisallowStartIfOnBatteries", namespaces=TASK_NAMESPACE) == "false"
    assert root.findtext(".//t:ExecutionTimeLimit", namespaces=TASK_NAMESPACE) == "PT0S"
    assert root.find(".//t:RestartOnFailure", namespaces=TASK_NAMESPACE) is None
    assert (
        root.findtext(".//t:Command", namespaces=TASK_NAMESPACE)
        == r"C:\Program Files\PetNest\PetNestStartupHost.exe"
    )
    assert root.find(".//t:Arguments", namespaces=TASK_NAMESPACE) is None
    assert root.findtext(".//t:WorkingDirectory", namespaces=TASK_NAMESPACE) == r"C:\Program Files\PetNest"


def test_task_names_are_isolated_by_user_sid() -> None:
    assert task_name_for_sid("S-1-5-21-1000") != task_name_for_sid("S-1-5-21-2000")
    assert task_name_for_sid("S-1-5-21-1000").startswith(TASK_NAME_PREFIX)


def test_task_name_rejects_non_sid_input() -> None:
    with pytest.raises(ValueError, match="SID"):
        task_name_for_sid("user-controlled-task-name")


def test_enabling_imports_xml_and_removes_temporary_file(tmp_path: Path) -> None:
    calls: list[list[str]] = []
    captured_xml: list[str] = []

    def runner(arguments: list[str]) -> CompletedProcess[str]:
        calls.append(arguments)
        xml_path = Path(arguments[arguments.index("/XML") + 1])
        captured_xml.append(xml_path.read_text(encoding="utf-16"))
        return CompletedProcess(arguments, 0, "", "")

    executable = tmp_path / "PetNest.exe"
    startup_host = tmp_path / "PetNestStartupHost.exe"
    executable.touch()
    startup_host.touch()
    task = WindowsStartupTask(
        executable=executable,
        startup_host=startup_host,
        frozen=True,
        runner=runner,
        sid_provider=lambda: "S-1-5-21-1000",
        temporary_directory=tmp_path,
    )

    result = task.configure(True)

    assert result.success is True
    assert calls[0][1:4] == ["/Create", "/TN", task_name_for_sid("S-1-5-21-1000")]
    assert str(startup_host.resolve()) in captured_xml[0]
    assert "RestartOnFailure" not in captured_xml[0]
    assert list(tmp_path.glob("*.xml")) == []


def test_enabling_reports_a_missing_startup_host_without_running_commands(tmp_path: Path) -> None:
    calls: list[list[str]] = []
    executable = tmp_path / "PetNest.exe"
    executable.touch()
    task = WindowsStartupTask(
        executable=executable,
        startup_host=tmp_path / "PetNestStartupHost.exe",
        frozen=True,
        runner=lambda arguments: calls.append(arguments),  # type: ignore[arg-type,return-value]
        sid_provider=lambda: "S-1-5-21-1000",
    )

    result = task.configure(True)

    assert result.success is False
    assert "PetNestStartupHost.exe" in result.message
    assert calls == []


def test_disabling_deletes_an_existing_task(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def runner(arguments: list[str]) -> CompletedProcess[str]:
        calls.append(arguments)
        return CompletedProcess(arguments, 0, "", "")

    task = WindowsStartupTask(
        executable=tmp_path / "PetNest.exe",
        frozen=True,
        runner=runner,
        sid_provider=lambda: "S-1-5-21-1000",
    )

    assert task.configure(False).success is True
    assert calls[-1][1] == "/Delete"
    assert calls[-1][3] == task_name_for_sid("S-1-5-21-1000")


def test_disabling_signals_the_running_host_before_querying_the_task(tmp_path: Path) -> None:
    events: list[str] = []

    def runner(arguments: list[str]) -> CompletedProcess[str]:
        assert events == ["cancel"]
        return CompletedProcess(arguments, 3, "", "")

    task = WindowsStartupTask(
        executable=tmp_path / "PetNest.exe",
        frozen=True,
        runner=runner,
        host_canceller=lambda: events.append("cancel"),
        sid_provider=lambda: "S-1-5-21-1000",
    )

    assert task.configure(False).success is True
    assert events == ["cancel"]


def test_disabling_is_idempotent_when_task_does_not_exist(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def runner(arguments: list[str]) -> CompletedProcess[str]:
        calls.append(arguments)
        return CompletedProcess(arguments, 3, "", "")

    task = WindowsStartupTask(
        executable=tmp_path / "PetNest.exe",
        frozen=True,
        runner=runner,
        sid_provider=lambda: "S-1-5-21-1000",
    )

    assert task.configure(False).success is True
    assert len(calls) == 1
    assert "-Command" in calls[0]
    script = calls[0][-1]
    assert "Schedule.Service" in script
    assert "-2147024894" in script
    assert task_name_for_sid("S-1-5-21-1000") in script


def test_disabling_reports_query_errors_other_than_a_missing_task(tmp_path: Path) -> None:
    task = WindowsStartupTask(
        executable=tmp_path / "PetNest.exe",
        frozen=True,
        runner=lambda arguments: CompletedProcess(arguments, 1, "", "Access is denied."),
        sid_provider=lambda: "S-1-5-21-1000",
    )

    result = task.configure(False)

    assert result.success is False
    assert "Access is denied" in result.message


def test_source_mode_is_unsupported_and_does_not_execute_commands(tmp_path: Path) -> None:
    calls: list[list[str]] = []
    task = WindowsStartupTask(
        executable=tmp_path / "python.exe",
        frozen=False,
        runner=lambda arguments: calls.append(arguments),  # type: ignore[arg-type,return-value]
    )

    assert task.supported is False
    assert task.configure(True).success is False
    assert calls == []


def test_source_mode_can_remove_a_stale_packaged_task(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def runner(arguments: list[str]) -> CompletedProcess[str]:
        calls.append(arguments)
        return CompletedProcess(arguments, 0, "", "")

    task = WindowsStartupTask(
        executable=tmp_path / "python.exe",
        frozen=False,
        runner=runner,
        sid_provider=lambda: "S-1-5-21-1000",
    )

    assert task.configure(False).success is True
    assert "-Command" in calls[0]
    assert calls[1][1] == "/Delete"


def test_remove_all_uses_an_elevated_safe_namespace_cleanup(tmp_path: Path) -> None:
    calls: list[list[str]] = []
    cancellations: list[bool] = []

    def runner(arguments: list[str]) -> CompletedProcess[str]:
        calls.append(arguments)
        return CompletedProcess(arguments, 0, "", "")

    task = WindowsStartupTask(
        executable=tmp_path / "PetNest.exe",
        frozen=True,
        runner=runner,
        host_canceller=lambda: cancellations.append(True),
    )

    assert task.remove_all().success is True
    assert cancellations == [True]
    assert len(calls) == 1
    assert "-Command" in calls[0]
    script = calls[0][-1]
    assert "GetFolder('\\PetNest')" in script
    assert "GetTasks(0)" in script
    assert "^AutoStart(?:-S-\\d+(?:-\\d+)+)?$" in script
    assert "DeleteTask" in script
    assert "if($_.Exception.HResult -ne -2147024894){throw}" in script
    assert "whoami" not in script.casefold()


def test_remove_all_is_idempotent_when_the_task_folder_is_missing(tmp_path: Path) -> None:
    task = WindowsStartupTask(
        executable=tmp_path / "PetNest.exe",
        frozen=True,
        runner=lambda arguments: CompletedProcess(arguments, 3, "", ""),
    )

    assert task.remove_all().success is True


def test_create_failure_returns_diagnostic_and_cleans_xml(tmp_path: Path) -> None:
    def runner(arguments: list[str]) -> CompletedProcess[str]:
        return CompletedProcess(arguments, 1, "", "access denied")

    executable = tmp_path / "PetNest.exe"
    startup_host = tmp_path / "PetNestStartupHost.exe"
    executable.touch()
    startup_host.touch()
    task = WindowsStartupTask(
        executable=executable,
        startup_host=startup_host,
        frozen=True,
        runner=runner,
        sid_provider=lambda: "S-1-5-21-1000",
        temporary_directory=tmp_path,
    )

    result = task.configure(True)

    assert result.success is False
    assert "access denied" in result.message
    assert list(tmp_path.glob("*.xml")) == []


def test_os_error_returns_failure_and_cleans_xml(tmp_path: Path) -> None:
    def runner(arguments: list[str]) -> CompletedProcess[str]:
        raise OSError("schtasks unavailable")

    executable = tmp_path / "PetNest.exe"
    startup_host = tmp_path / "PetNestStartupHost.exe"
    executable.touch()
    startup_host.touch()
    task = WindowsStartupTask(
        executable=executable,
        startup_host=startup_host,
        frozen=True,
        runner=runner,
        sid_provider=lambda: "S-1-5-21-1000",
        temporary_directory=tmp_path,
    )

    result = task.configure(True)

    assert result.success is False
    assert "schtasks unavailable" in result.message
    assert list(tmp_path.glob("*.xml")) == []
