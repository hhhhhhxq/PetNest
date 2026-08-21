"""Windows global keyboard-activity hook that never exposes key data."""

from __future__ import annotations

from collections.abc import Callable
import logging
import sys
from threading import Event, Thread


LOGGER = logging.getLogger(__name__)


class WindowsKeyboardActivityMonitor:
    """Own one hook thread and report only parameterless activity pulses."""

    def __init__(
        self,
        *,
        session_factory: Callable[[], object] | None = None,
        start_timeout: float = 1.0,
    ) -> None:
        self._session_factory = session_factory or _WindowsHookSession
        self._start_timeout = max(0.05, float(start_timeout))
        self._session: object | None = None
        self._thread: Thread | None = None
        self._status_message = "已关闭"

    @property
    def supported(self) -> bool:
        return True

    @property
    def status_message(self) -> str:
        return self._status_message

    def start(self, on_activity: Callable[[], object]) -> bool:
        if self._thread is not None and self._thread.is_alive():
            return True
        session = self._session_factory()
        thread = Thread(
            target=session.run,
            args=(on_activity,),
            daemon=True,
            name="petnest-keyboard-hook",
        )
        self._session = session
        self._thread = thread
        thread.start()
        started = session.started.wait(self._start_timeout)
        if not started or not bool(session.install_ok):
            self._status_message = str(session.error_message or "无法安装 Windows 键盘监听")
            session.request_stop()
            thread.join(timeout=1.0)
            self._session = None
            self._thread = None
            return False
        self._status_message = "监听正常"
        return True

    def stop(self) -> None:
        session, thread = self._session, self._thread
        self._session = None
        self._thread = None
        if session is not None:
            session.request_stop()
        if thread is not None:
            thread.join(timeout=1.0)
        self._status_message = "已关闭"


class _WindowsHookSession:
    """One Win32 hook message loop; lParam remains an opaque forwarded value."""

    WH_KEYBOARD_LL = 13
    WM_KEYDOWN = 0x0100
    WM_SYSKEYDOWN = 0x0104
    WM_QUIT = 0x0012

    def __init__(self) -> None:
        self.started = Event()
        self.install_ok = False
        self.error_message = ""
        self._thread_id = 0
        self._hook: object | None = None
        self._callback: object | None = None

    def run(self, on_activity: Callable[[], object]) -> None:
        if sys.platform != "win32":
            self.error_message = "当前版本仅支持 Windows"
            self.started.set()
            return
        try:
            self._run_windows(on_activity)
        except (AttributeError, OSError):
            self.error_message = "无法安装 Windows 键盘监听"
            self.started.set()
            LOGGER.warning("Windows 键盘监听线程异常", exc_info=True)

    def _run_windows(self, on_activity: Callable[[], object]) -> None:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._thread_id = int(kernel32.GetCurrentThreadId())
        hook_proc_type = ctypes.WINFUNCTYPE(
            ctypes.c_ssize_t,
            ctypes.c_int,
            wintypes.WPARAM,
            wintypes.LPARAM,
        )
        user32.SetWindowsHookExW.restype = ctypes.c_void_p
        user32.CallNextHookEx.restype = ctypes.c_ssize_t

        @hook_proc_type
        def callback(n_code: int, w_param: int, opaque_l_param: int) -> int:
            if n_code >= 0 and int(w_param) in {self.WM_KEYDOWN, self.WM_SYSKEYDOWN}:
                try:
                    on_activity()
                except Exception:  # noqa: BLE001 - native callback must keep the system hook alive.
                    LOGGER.warning("键盘活动通知失败", exc_info=True)
            return int(user32.CallNextHookEx(self._hook, n_code, w_param, opaque_l_param))

        self._callback = callback
        self._hook = user32.SetWindowsHookExW(
            self.WH_KEYBOARD_LL,
            callback,
            kernel32.GetModuleHandleW(None),
            0,
        )
        if not self._hook:
            self.error_message = f"无法安装 Windows 键盘监听（错误码 {ctypes.get_last_error()}）"
            self.started.set()
            return
        self.install_ok = True
        self.started.set()
        message = wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(message))
                user32.DispatchMessageW(ctypes.byref(message))
        finally:
            if self._hook:
                user32.UnhookWindowsHookEx(self._hook)
                self._hook = None

    def request_stop(self) -> None:
        if sys.platform != "win32" or not self._thread_id:
            return
        try:
            import ctypes

            ctypes.windll.user32.PostThreadMessageW(self._thread_id, self.WM_QUIT, 0, 0)
        except (AttributeError, OSError):
            LOGGER.warning("无法停止 Windows 键盘监听线程", exc_info=True)


__all__ = ["WindowsKeyboardActivityMonitor"]
