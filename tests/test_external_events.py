"""本机 TCP 外部事件入口的集成测试。"""

from __future__ import annotations

import json
import socket
import time

from petnest.core.event_bus import EventBus
from petnest.events.external_event_server import ExternalEventServer


def _send(port: int, body: bytes) -> None:
    with socket.create_connection(("127.0.0.1", port), timeout=1) as client:
        client.sendall(body)


def _wait_for(predicate: object, timeout: float = 1.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if callable(predicate) and predicate():
            return
        time.sleep(0.01)
    raise AssertionError("等待服务端处理事件超时")


def test_server_binds_strictly_to_loopback_and_publishes_valid_json() -> None:
    bus = EventBus()
    received = []
    bus.subscribe(received.append)
    server = ExternalEventServer(bus, port=0)

    assert server.host == "127.0.0.1"
    assert server.start()
    try:
        _send(server.port, json.dumps({"event": "agent.working", "source": "test", "payload": {"task": "build"}}).encode() + b"\n")
        _wait_for(lambda: len(received) == 1)
        assert received[0].event_name == "agent.working"
        assert received[0].source == "test"
        assert received[0].payload == {"task": "build"}
    finally:
        server.stop()


def test_unknown_event_is_published_without_crashing_server() -> None:
    bus = EventBus()
    received = []
    bus.subscribe(received.append)
    server = ExternalEventServer(bus, port=0)
    assert server.start()
    try:
        _send(server.port, b'{"event":"custom.future","source":"test"}\n')
        _send(server.port, b'{"event":"agent.success","source":"test"}\n')
        _wait_for(lambda: len(received) == 2)
        assert [event.event_name for event in received] == ["custom.future", "agent.success"]
    finally:
        server.stop()


def test_invalid_json_and_oversized_lines_are_rejected_without_publishing() -> None:
    bus = EventBus()
    received = []
    bus.subscribe(received.append)
    server = ExternalEventServer(bus, port=0, max_message_bytes=32)
    assert server.start()
    try:
        _send(server.port, b"not json\n")
        _send(server.port, b'{"event":"agent.working","payload":"' + b"x" * 64 + b'"}\n')
        time.sleep(0.05)
        assert received == []
    finally:
        server.stop()


def test_rate_limit_drops_excess_events() -> None:
    bus = EventBus()
    received = []
    bus.subscribe(received.append)
    server = ExternalEventServer(bus, port=0, max_events_per_second=1)
    assert server.start()
    try:
        _send(server.port, b'{"event":"agent.working"}\n')
        _send(server.port, b'{"event":"agent.success"}\n')
        _wait_for(lambda: len(received) == 1)
        time.sleep(0.05)
        assert [event.event_name for event in received] == ["agent.working"]
    finally:
        server.stop()


def test_port_in_use_disables_only_the_second_server() -> None:
    first = ExternalEventServer(EventBus(), port=0)
    assert first.start()
    second = ExternalEventServer(EventBus(), port=first.port)
    try:
        assert not second.start()
        assert not second.is_running
        assert second.last_error is not None
    finally:
        second.stop()
        first.stop()
