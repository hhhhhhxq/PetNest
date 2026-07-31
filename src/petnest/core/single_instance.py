"""通过本机 Qt 套接字协调同一用户的单个 PetNest 进程。"""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum
import os
from pathlib import Path
import signal
import sys

from PySide6.QtNetwork import QLocalServer, QLocalSocket


class InstanceClaim(Enum):
    """本次启动尝试的结果。"""

    PRIMARY = "primary"
    ACTIVATED_EXISTING = "activated_existing"
    UNRESPONSIVE = "unresponsive"


class SingleInstanceCoordinator:
    """为第一个实例监听“显示宠物”请求，阻止后续实例创建窗口。"""

    _connect_timeout_ms = 400
    _response_timeout_ms = 1_500

    def __init__(
        self,
        server_name: str,
        pid_path: Path,
        *,
        force_restart_enabled: bool | None = None,
        process_stopper: Callable[[int], object] | None = None,
    ) -> None:
        self.server_name = server_name
        self.pid_path = pid_path
        self._activation_handler: Callable[[], object] | None = None
        self._server: QLocalServer | None = None
        self._clients: list[QLocalSocket] = []
        self._force_restart_enabled = sys.platform == "win32" if force_restart_enabled is None else force_restart_enabled
        self._process_stopper = process_stopper or _terminate_process

    def claim(self) -> InstanceClaim:
        """成为主实例，或请求已有实例恢复显示。"""
        existing = self._activate_existing()
        if existing is not None:
            return existing
        QLocalServer.removeServer(self.server_name)
        self._server = QLocalServer()
        self._server.newConnection.connect(self._accept_connection)
        if not self._server.listen(self.server_name):
            return InstanceClaim.UNRESPONSIVE
        self.pid_path.parent.mkdir(parents=True, exist_ok=True)
        self.pid_path.write_text(str(os.getpid()), encoding="utf-8")
        return InstanceClaim.PRIMARY

    def set_activation_handler(self, handler: Callable[[], object]) -> None:
        self._activation_handler = handler

    def force_restart(self) -> bool:
        """在用户确认后结束记录的、无响应的 Windows 旧实例。"""
        if not self._force_restart_enabled:
            return False
        try:
            pid = int(self.pid_path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return False
        if pid <= 0 or pid == os.getpid():
            return False
        try:
            self._process_stopper(pid)
        except OSError:
            return False
        return True

    def release(self) -> None:
        """关闭监听并仅移除本进程写入的 PID 标记。"""
        if self._server is not None:
            self._server.close()
            self._server = None
        QLocalServer.removeServer(self.server_name)
        try:
            if self.pid_path.read_text(encoding="utf-8").strip() == str(os.getpid()):
                self.pid_path.unlink()
        except OSError:
            pass

    def _activate_existing(self) -> InstanceClaim | None:
        socket = QLocalSocket()
        socket.connectToServer(self.server_name)
        if not socket.waitForConnected(self._connect_timeout_ms):
            return None
        socket.write(b"show")
        if not socket.waitForBytesWritten(self._connect_timeout_ms):
            return InstanceClaim.UNRESPONSIVE
        if not socket.waitForReadyRead(self._response_timeout_ms) and not socket.bytesAvailable():
            return InstanceClaim.UNRESPONSIVE
        return InstanceClaim.ACTIVATED_EXISTING if bytes(socket.readAll()) == b"shown" else InstanceClaim.UNRESPONSIVE

    def _accept_connection(self) -> None:
        if self._server is None:
            return
        socket = self._server.nextPendingConnection()
        if socket is None:
            return
        self._clients.append(socket)
        socket.disconnected.connect(lambda: self._discard_client(socket))
        socket.readyRead.connect(lambda: self._handle_request(socket))
        if socket.bytesAvailable():
            self._handle_request(socket)

    def _handle_request(self, socket: QLocalSocket) -> None:
        if bytes(socket.readAll()) != b"show" or self._activation_handler is None:
            return
        self._activation_handler()
        socket.write(b"shown")
        socket.flush()
        socket.disconnectFromServer()

    def _discard_client(self, socket: QLocalSocket) -> None:
        if socket in self._clients:
            self._clients.remove(socket)


def _terminate_process(pid: int) -> None:
    if sys.platform != "win32":
        raise OSError("当前平台不支持强制重启已有实例")
    os.kill(pid, signal.SIGTERM)
