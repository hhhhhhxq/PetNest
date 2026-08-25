from __future__ import annotations

import logging
from pathlib import Path
from subprocess import CompletedProcess
from threading import Event

import petnest_startup_host as startup_host


class _Logger:
    def __init__(self) -> None:
        self.messages: list[tuple[str, tuple[object, ...]]] = []

    def info(self, message: str, *args: object) -> None:
        self.messages.append((message, args))

    def warning(self, message: str, *args: object, **_kwargs: object) -> None:
        self.messages.append((message, args))


def _runner_for(*outcomes: int | OSError):
    pending = list(outcomes)
    calls: list[tuple[list[str], dict[str, object]]] = []

    def runner(arguments: list[str], **kwargs: object) -> CompletedProcess[str]:
        calls.append((arguments, kwargs))
        outcome = pending.pop(0)
        if isinstance(outcome, OSError):
            raise outcome
        return CompletedProcess(arguments, outcome)

    return runner, calls


def test_normal_exit_stops_without_retry(tmp_path: Path) -> None:
    app_path = tmp_path / "PetNest.exe"
    runner, calls = _runner_for(0)
    sleeps: list[float] = []

    result = startup_host.run_supervisor(
        app_path,
        runner=runner,
        sleeper=sleeps.append,
        logger=_Logger(),
    )

    assert result == 0
    assert calls == [
        ([str(app_path), "--startup"], {"cwd": str(tmp_path), "check": False})
    ]
    assert sleeps == []


def test_abnormal_exit_retries_after_one_minute_until_success(tmp_path: Path) -> None:
    runner, calls = _runner_for(7, 3, 0)
    sleeps: list[float] = []

    result = startup_host.run_supervisor(
        tmp_path / "PetNest.exe",
        runner=runner,
        sleeper=sleeps.append,
        cancel_poll_seconds=60,
        logger=_Logger(),
    )

    assert result == 0
    assert len(calls) == 3
    assert sleeps == [60, 60]


def test_abnormal_exit_stops_after_three_restarts(tmp_path: Path) -> None:
    runner, calls = _runner_for(1, 2, 3, 4, 0)
    sleeps: list[float] = []

    result = startup_host.run_supervisor(
        tmp_path / "PetNest.exe",
        runner=runner,
        sleeper=sleeps.append,
        cancel_poll_seconds=60,
        logger=_Logger(),
    )

    assert result == 4
    assert len(calls) == 4
    assert sleeps == [60, 60, 60]


def test_process_creation_failure_uses_the_same_bounded_retry(tmp_path: Path) -> None:
    runner, calls = _runner_for(OSError("missing executable"), 0)
    sleeps: list[float] = []
    logger = _Logger()

    result = startup_host.run_supervisor(
        tmp_path / "PetNest.exe",
        runner=runner,
        sleeper=sleeps.append,
        cancel_poll_seconds=60,
        logger=logger,
    )

    assert result == 0
    assert len(calls) == 2
    assert sleeps == [60]
    assert any("missing executable" in repr(args) for _message, args in logger.messages)


def test_cancellation_stops_the_host_without_waiting_for_petnest_to_exit(tmp_path: Path) -> None:
    started = Event()
    release = Event()
    calls: list[list[str]] = []

    def runner(arguments: list[str], **_kwargs: object) -> CompletedProcess[str]:
        calls.append(arguments)
        started.set()
        release.wait(timeout=5)
        return CompletedProcess(arguments, 0)

    def cancelled() -> bool:
        if not calls:
            return False
        assert started.wait(timeout=1)
        return True

    try:
        result = startup_host.run_supervisor(
            tmp_path / "PetNest.exe",
            runner=runner,
            cancelled=cancelled,
            logger=_Logger(),
        )
    finally:
        release.set()

    assert result == 0
    assert calls == [[str(tmp_path / "PetNest.exe"), "--startup"]]


def test_control_generation_change_cancels_an_existing_host(tmp_path: Path) -> None:
    control_path = tmp_path / "startup-host.generation"
    cancelled = startup_host.cancellation_checker(control_path)

    startup_host.cancel_running_hosts(control_path)

    assert cancelled() is True


def test_cancellation_during_retry_delay_prevents_the_next_launch(tmp_path: Path) -> None:
    runner, calls = _runner_for(1, 0)
    cancelled_state = False
    sleeps: list[float] = []

    def sleeper(seconds: float) -> None:
        nonlocal cancelled_state
        sleeps.append(seconds)
        cancelled_state = True

    result = startup_host.run_supervisor(
        tmp_path / "PetNest.exe",
        runner=runner,
        sleeper=sleeper,
        cancelled=lambda: cancelled_state,
        cancel_poll_seconds=0.25,
        logger=_Logger(),
    )

    assert result == 0
    assert len(calls) == 1
    assert sleeps == [0.25]


def test_default_app_is_the_sibling_petnest_executable(monkeypatch, tmp_path: Path) -> None:
    runner, calls = _runner_for(0)
    monkeypatch.setattr(startup_host.sys, "executable", str(tmp_path / "PetNestStartupHost.exe"))

    assert startup_host.run_supervisor(runner=runner, sleeper=lambda _seconds: None) == 0
    assert calls[0][0] == [str(tmp_path / "PetNest.exe"), "--startup"]


def test_configure_logging_writes_a_local_diagnostic_file(tmp_path: Path) -> None:
    logger = startup_host.configure_logging(tmp_path)

    logger.info("startup host test marker")
    for handler in logger.handlers:
        handler.flush()

    assert "startup host test marker" in (tmp_path / "startup-host.log").read_text(encoding="utf-8")


def test_main_passes_the_file_logger_to_the_supervisor(monkeypatch) -> None:
    marker = object()
    calls: list[object] = []
    monkeypatch.setattr(startup_host, "configure_logging", lambda: marker)
    monkeypatch.setattr(
        startup_host,
        "run_supervisor",
        lambda *, logger: calls.append(logger) or 9,
    )

    assert startup_host.main() == 9
    assert calls == [marker]


def test_main_still_starts_supervisor_when_file_logging_is_unavailable(monkeypatch) -> None:
    calls: list[logging.Logger] = []
    monkeypatch.setattr(
        startup_host,
        "configure_logging",
        lambda: (_ for _ in ()).throw(PermissionError("read only")),
    )
    monkeypatch.setattr(
        startup_host,
        "run_supervisor",
        lambda *, logger: calls.append(logger) or 0,
    )

    assert startup_host.main() == 0
    assert len(calls) == 1
    assert any(isinstance(handler, logging.NullHandler) for handler in calls[0].handlers)
