"""同一用户只能运行一个 PetNest 实例的回归测试。"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import threading
from uuid import uuid4

import pytest
from PySide6.QtNetwork import QLocalServer

from petnest.core.single_instance import InstanceClaim, SingleInstanceCoordinator


def _server_name() -> str:
    return f"PetNest-test-{uuid4().hex}"


def test_primary_instance_accepts_show_request_and_records_its_pid(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    name = _server_name()
    pid_path = tmp_path / "instance.pid"
    coordinator = SingleInstanceCoordinator(name, pid_path)
    shown: list[bool] = []
    try:
        assert coordinator.claim() is InstanceClaim.PRIMARY
        coordinator.set_activation_handler(lambda: shown.append(True))

        command = (
            "from pathlib import Path; "
            "from petnest.core.single_instance import SingleInstanceCoordinator; "
            f"print(SingleInstanceCoordinator({name!r}, Path({str(pid_path)!r})).claim().value)"
        )
        environment = {**os.environ, "PYTHONPATH": str(Path("src").resolve())}
        second_instance = subprocess.Popen(
            [sys.executable, "-c", command], cwd=Path.cwd(), env=environment, stdout=subprocess.PIPE, text=True
        )
        qtbot.waitUntil(lambda: second_instance.poll() is not None, timeout=3_000)

        assert second_instance.stdout is not None
        assert second_instance.stdout.read().strip() == InstanceClaim.ACTIVATED_EXISTING.value
        assert shown == [True]
        assert pid_path.read_text(encoding="utf-8") == str(os.getpid())
    finally:
        coordinator.release()


def test_unresponsive_existing_instance_is_reported_without_starting_another(tmp_path: Path) -> None:
    name = _server_name()
    server = QLocalServer()
    assert server.listen(name)
    outcome: list[InstanceClaim] = []
    try:
        worker = threading.Thread(
            target=lambda: outcome.append(SingleInstanceCoordinator(name, tmp_path / "instance.pid").claim())
        )
        worker.start()
        worker.join(timeout=3)

        assert outcome == [InstanceClaim.UNRESPONSIVE]
    finally:
        server.close()
        QLocalServer.removeServer(name)


def test_force_restart_uses_the_recorded_existing_pid_only_when_enabled(tmp_path: Path) -> None:
    pid_path = tmp_path / "instance.pid"
    pid_path.write_text("4242", encoding="utf-8")
    stopped: list[int] = []
    coordinator = SingleInstanceCoordinator(
        _server_name(),
        pid_path,
        force_restart_enabled=True,
        process_stopper=stopped.append,
    )

    assert coordinator.force_restart() is True
    assert stopped == [4242]
