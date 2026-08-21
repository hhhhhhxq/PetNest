"""平台键盘活动监听的隐私边界与生命周期。"""

from __future__ import annotations

from threading import Event

from petnest.platforms.keyboard import (
    UnsupportedKeyboardActivityMonitor,
    create_keyboard_activity_monitor,
)


def test_unsupported_monitor_never_invokes_callback() -> None:
    calls: list[bool] = []
    monitor = UnsupportedKeyboardActivityMonitor("darwin")

    assert monitor.supported is False
    assert monitor.start(lambda: calls.append(True)) is False
    monitor.stop()

    assert calls == []
    assert monitor.status_message == "当前版本仅支持 Windows"


def test_factory_uses_unsupported_monitor_outside_windows() -> None:
    monitor = create_keyboard_activity_monitor("darwin")

    assert isinstance(monitor, UnsupportedKeyboardActivityMonitor)
    assert monitor.supported is False


def test_unknown_platform_reports_same_safe_degradation() -> None:
    monitor = create_keyboard_activity_monitor("plan9")

    assert monitor.start(lambda: None) is False
    assert monitor.status_message == "当前版本仅支持 Windows"


class FakeHookSession:
    def __init__(self, *, install_ok: bool = True) -> None:
        self.install_ok = install_ok
        self.started = Event()
        self.stop_requested = Event()
        self.activity = None
        self.stopped = 0
        self.error_message = "" if install_ok else "无法安装 Windows 键盘监听"

    def run(self, on_activity) -> None:
        self.activity = on_activity
        self.started.set()
        if self.install_ok:
            self.stop_requested.wait(2)

    def request_stop(self) -> None:
        self.stopped += 1
        self.stop_requested.set()


def test_windows_monitor_emits_only_parameterless_activity() -> None:
    from petnest.platforms.windows_keyboard import WindowsKeyboardActivityMonitor

    session = FakeHookSession()
    calls: list[tuple[object, ...]] = []
    monitor = WindowsKeyboardActivityMonitor(session_factory=lambda: session)

    assert monitor.start(lambda *args: calls.append(args)) is True
    assert session.activity is not None
    session.activity()
    monitor.stop()

    assert calls == [()]
    assert session.stopped == 1
    assert monitor.status_message == "已关闭"


def test_windows_monitor_start_is_idempotent() -> None:
    from petnest.platforms.windows_keyboard import WindowsKeyboardActivityMonitor

    sessions: list[FakeHookSession] = []

    def create_session() -> FakeHookSession:
        session = FakeHookSession()
        sessions.append(session)
        return session

    monitor = WindowsKeyboardActivityMonitor(session_factory=create_session)

    assert monitor.start(lambda: None) is True
    assert monitor.start(lambda: None) is True
    monitor.stop()

    assert len(sessions) == 1


def test_windows_monitor_install_failure_is_safe_and_retryable() -> None:
    from petnest.platforms.windows_keyboard import WindowsKeyboardActivityMonitor

    failed = FakeHookSession(install_ok=False)
    succeeded = FakeHookSession()
    sessions = iter((failed, succeeded))
    monitor = WindowsKeyboardActivityMonitor(session_factory=lambda: next(sessions))

    assert monitor.start(lambda: None) is False
    assert monitor.status_message == "无法安装 Windows 键盘监听"
    assert monitor.start(lambda: None) is True
    monitor.stop()

    assert failed.stopped == 1
    assert succeeded.stopped == 1


def test_windows_factory_returns_supported_monitor() -> None:
    monitor = create_keyboard_activity_monitor("win32")

    assert monitor.supported is True
    monitor.stop()
