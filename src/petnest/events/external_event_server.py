"""只监听本机回环地址的 newline-delimited JSON 事件服务。"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Mapping
import hmac
import json
import logging
import socket
from threading import Event, Lock, Thread, current_thread
from time import monotonic
from typing import Any

from petnest.core.event_bus import EventBus
from petnest.core.codex_link import CODEX_HOOK_EVENTS
from petnest.models.event import PetEvent

LOGGER = logging.getLogger(__name__)
_LOOPBACK_HOST = "127.0.0.1"
_ALLOWED_FIELDS = frozenset({"event", "source", "payload", "priority"})
_CODEX_ALLOWED_FIELDS = _ALLOWED_FIELDS | {"token"}
_CODEX_PAYLOAD_FIELDS = frozenset(
    {"hook_event_name", "session_id", "turn_id", "tool_name", "tool_failed", "stop_hook_active"}
)


class ExternalEventServer:
    """可启动、可停止的本机 TCP 服务，接收一行一个 JSON 事件。"""

    def __init__(
        self,
        event_bus: EventBus,
        *,
        host: str = _LOOPBACK_HOST,
        port: int = 18486,
        max_message_bytes: int = 4096,
        max_events_per_second: int = 30,
        codex_token: str | None = None,
        event_sink: Callable[[PetEvent], object] | None = None,
    ) -> None:
        if host != _LOOPBACK_HOST:
            raise ValueError("外部事件服务只能绑定 127.0.0.1")
        if not 0 <= port <= 65535:
            raise ValueError("端口必须介于 0 和 65535")
        if max_message_bytes <= 0 or max_events_per_second <= 0:
            raise ValueError("消息大小与速率限制必须大于 0")
        self._event_bus = event_bus
        self.host = _LOOPBACK_HOST
        self.port = port
        self._max_message_bytes = max_message_bytes
        self._max_events_per_second = max_events_per_second
        self._codex_token = codex_token
        self._event_sink = event_sink or event_bus.publish
        self._server_socket: socket.socket | None = None
        self._thread: Thread | None = None
        self._stop_requested = Event()
        self._state_lock = Lock()
        self._rate_lock = Lock()
        self._accepted_at: deque[float] = deque()
        self.last_error: OSError | None = None

    @property
    def is_running(self) -> bool:
        """服务线程和监听 socket 都处于活动状态时为真。"""
        thread = self._thread
        return thread is not None and thread.is_alive() and self._server_socket is not None

    def start(self) -> bool:
        """开始监听；端口占用时返回 ``False`` 而不是令主程序退出。"""
        with self._state_lock:
            if self.is_running:
                return True
            self.last_error = None
            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                listener.bind((self.host, self.port))
                listener.listen(16)
                listener.settimeout(0.1)
            except OSError as error:
                listener.close()
                self.last_error = error
                LOGGER.warning("外部事件服务未启动（%s:%s）：%s", self.host, self.port, error)
                return False
            self.port = int(listener.getsockname()[1])
            self._server_socket = listener
            self._stop_requested.clear()
            # 服务线程只承载可选的本机事件入口；即便某个系统 socket 在
            # 退出时迟迟不返回，也不能阻止用户关闭整个桌宠。
            self._thread = Thread(target=self._serve, name="PetNestExternalEventServer", daemon=True)
            self._thread.start()
            return True

    def stop(self) -> None:
        """停止监听并等待工作线程结束，防止程序退出时遗留线程。"""
        with self._state_lock:
            self._stop_requested.set()
            listener, self._server_socket = self._server_socket, None
            thread = self._thread
        if listener is not None:
            try:
                listener.close()
            except OSError:
                pass
        if thread is not None and thread is not current_thread():
            thread.join(timeout=2)
            if thread.is_alive():
                LOGGER.warning("外部事件服务线程未能在停止期限内退出")
        with self._state_lock:
            if self._thread is thread and (thread is None or not thread.is_alive()):
                self._thread = None

    def _serve(self) -> None:
        while not self._stop_requested.is_set():
            listener = self._server_socket
            if listener is None:
                return
            try:
                connection, _address = listener.accept()
            except TimeoutError:
                continue
            except OSError:
                if not self._stop_requested.is_set():
                    LOGGER.exception("外部事件服务接受连接失败")
                return
            with connection:
                connection.settimeout(0.1)
                self._read_connection(connection)

    def _read_connection(self, connection: socket.socket) -> None:
        pending = bytearray()
        while not self._stop_requested.is_set():
            try:
                data = connection.recv(min(self._max_message_bytes + 1, 4096))
            except TimeoutError:
                return
            except OSError:
                return
            if not data:
                return
            pending.extend(data)
            if len(pending) > self._max_message_bytes and b"\n" not in pending:
                LOGGER.warning("拒绝超出大小限制的外部事件消息")
                return
            while b"\n" in pending:
                raw_line, _, remainder = pending.partition(b"\n")
                pending = bytearray(remainder)
                if len(raw_line) > self._max_message_bytes:
                    LOGGER.warning("拒绝超出大小限制的外部事件消息")
                    continue
                self._publish_line(bytes(raw_line))

    def _publish_line(self, raw_line: bytes) -> None:
        if not raw_line.strip():
            return
        try:
            parsed = json.loads(raw_line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            LOGGER.warning("拒绝格式错误的外部事件 JSON")
            return
        event = self._parse_event(parsed)
        if event is None:
            return
        if not self._allow_event():
            LOGGER.warning("外部事件超过速率限制，已忽略")
            return
        try:
            self._event_sink(event)
        except Exception:  # noqa: BLE001 - 外部输入绝不能结束服务线程。
            LOGGER.exception("分发外部事件失败：%s（来源：%s）", event.event_name, event.source)

    def _parse_event(self, parsed: Any) -> PetEvent | None:
        if not isinstance(parsed, Mapping):
            LOGGER.warning("拒绝非对象的外部事件 JSON")
            return None
        is_codex_hook = parsed.get("event") == "codex.hook"
        unknown_fields = set(parsed) - (_CODEX_ALLOWED_FIELDS if is_codex_hook else _ALLOWED_FIELDS)
        if unknown_fields:
            LOGGER.warning("拒绝包含未知字段的外部事件")
            return None
        name = parsed.get("event")
        source = parsed.get("source", "external")
        payload = parsed.get("payload", {})
        priority = parsed.get("priority", 0)
        if not isinstance(name, str) or not name or len(name) > 128:
            LOGGER.warning("拒绝缺少或无效 event 的外部事件")
            return None
        if not isinstance(source, str) or not source or len(source) > 128:
            LOGGER.warning("拒绝无效 source 的外部事件")
            return None
        if not isinstance(payload, Mapping) or not isinstance(priority, int) or isinstance(priority, bool):
            LOGGER.warning("拒绝 payload 或 priority 类型无效的外部事件")
            return None
        if is_codex_hook and not self._valid_codex_hook(parsed, source, payload):
            return None
        return PetEvent(name=name, source=source, payload=dict(payload), priority=priority)

    def _valid_codex_hook(
        self,
        parsed: Mapping[str, object],
        source: object,
        payload: Mapping[str, object],
    ) -> bool:
        token = parsed.get("token")
        if (
            self._codex_token is None
            or not isinstance(token, str)
            or not hmac.compare_digest(token, self._codex_token)
        ):
            LOGGER.warning("拒绝未通过鉴权的 Codex Hook 事件")
            return False
        if source != "codex-hook" or set(payload) - _CODEX_PAYLOAD_FIELDS:
            LOGGER.warning("拒绝来源或字段无效的 Codex Hook 事件")
            return False
        if payload.get("hook_event_name") not in CODEX_HOOK_EVENTS:
            LOGGER.warning("拒绝事件名无效的 Codex Hook 事件")
            return False
        for name in ("session_id", "turn_id", "tool_name"):
            value = payload.get(name)
            if value is not None and (not isinstance(value, str) or not 0 < len(value) <= 200):
                LOGGER.warning("拒绝标识字段无效的 Codex Hook 事件")
                return False
        for name in ("tool_failed", "stop_hook_active"):
            value = payload.get(name)
            if value is not None and not isinstance(value, bool):
                LOGGER.warning("拒绝状态字段无效的 Codex Hook 事件")
                return False
        return True

    def _allow_event(self) -> bool:
        now = monotonic()
        with self._rate_lock:
            while self._accepted_at and now - self._accepted_at[0] >= 1.0:
                self._accepted_at.popleft()
            if len(self._accepted_at) >= self._max_events_per_second:
                return False
            self._accepted_at.append(now)
            return True
