"""平台键盘活动监听的隐私边界与生命周期。"""

from __future__ import annotations

from threading import Event
import ctypes

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


class _FakeFunction:
    def __init__(self) -> None:
        self.restype = None
        self.argtypes = None


class _FakeWin32Library:
    def __init__(self) -> None:
        self.GetModuleHandleW = _FakeFunction()
        self.SetWindowsHookExW = _FakeFunction()
        self.CallNextHookEx = _FakeFunction()
        self.UnhookWindowsHookEx = _FakeFunction()
        self.PostThreadMessageW = _FakeFunction()


def test_win32_signatures_preserve_64_bit_module_handle() -> None:
    from petnest.platforms.windows_keyboard import _configure_win32_signatures

    user32 = _FakeWin32Library()
    kernel32 = _FakeWin32Library()
    hook_proc_type = object()

    _configure_win32_signatures(user32, kernel32, hook_proc_type)

    assert kernel32.GetModuleHandleW.restype is ctypes.c_void_p
    assert user32.SetWindowsHookExW.argtypes[2] is ctypes.c_void_p
    assert user32.CallNextHookEx.restype is ctypes.c_ssize_t
    assert user32.UnhookWindowsHookEx.argtypes == [ctypes.c_void_p]
    assert user32.PostThreadMessageW.restype is not None


def test_native_session_remembers_stop_requested_before_hook_is_ready() -> None:
    from petnest.platforms.windows_keyboard import _WindowsHookSession

    session = _WindowsHookSession()

    session.request_stop()

    assert session._stop_requested.is_set()


class StuckHookSession(FakeHookSession):
    def __init__(self) -> None:
        super().__init__()
        self.release = Event()

    def run(self, on_activity) -> None:
        self.activity = on_activity
        self.started.set()
        self.release.wait(2)


def test_stop_timeout_keeps_thread_reference_and_blocks_duplicate_start() -> None:
    from petnest.platforms.windows_keyboard import WindowsKeyboardActivityMonitor

    session = StuckHookSession()
    monitor = WindowsKeyboardActivityMonitor(
        session_factory=lambda: session,
        stop_timeout=0.01,
    )
    assert monitor.start(lambda: None) is True

    monitor.stop()

    assert monitor._thread is not None
    assert monitor._thread.is_alive()
    assert monitor.start(lambda: None) is False
    session.release.set()
    monitor._thread.join(timeout=1)
    monitor.stop()
    assert monitor._thread is None
