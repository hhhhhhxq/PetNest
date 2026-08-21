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
        stop_timeout: float = 1.0,
    ) -> None:
        self._session_factory = session_factory or _WindowsHookSession
        self._start_timeout = max(0.05, float(start_timeout))
        self._stop_timeout = max(0.01, float(stop_timeout))
        self._session: object | None = None
        self._thread: Thread | None = None
        self._stopping = False
        self._status_message = "已关闭"

    @property
    def supported(self) -> bool:
        return True

    @property
    def status_message(self) -> str:
        return self._status_message

    def start(self, on_activity: Callable[[], object]) -> bool:
        if self._thread is not None:
            if self._thread.is_alive():
                if self._stopping:
                    return False
                return bool(self._session is not None and self._session.install_ok)
            self._session = None
            self._thread = None
            self._stopping = False
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
            self._stopping = True
            session.request_stop()
            thread.join(timeout=self._stop_timeout)
            if not thread.is_alive():
                self._session = None
                self._thread = None
                self._stopping = False
            return False
        self._stopping = False
        self._status_message = "监听正常"
        return True

    def stop(self) -> None:
        session, thread = self._session, self._thread
        if session is None and thread is None:
            self._status_message = "已关闭"
            return
        self._stopping = True
        if session is not None:
            session.request_stop()
        if thread is not None:
            thread.join(timeout=self._stop_timeout)
        if thread is not None and thread.is_alive():
            self._status_message = "键盘监听正在停止"
            return
        self._session = None
        self._thread = None
        self._stopping = False
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
        self._stop_requested = Event()
        self._thread_id = 0
        self._hook: object | None = None
        self._callback: object | None = None
        self._post_thread_message: object | None = None

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
        _configure_win32_signatures(user32, kernel32, hook_proc_type)
        self._post_thread_message = user32.PostThreadMessageW

        @hook_proc_type
        def callback(n_code: int, w_param: int, opaque_l_param: int) -> int:
            if n_code >= 0 and int(w_param) in {self.WM_KEYDOWN, self.WM_SYSKEYDOWN}:
                try:
                    on_activity()
                except Exception:  # noqa: BLE001 - native callback must keep the system hook alive.
                    LOGGER.warning("键盘活动通知失败", exc_info=True)
            return int(user32.CallNextHookEx(self._hook, n_code, w_param, opaque_l_param))

        self._callback = callback
        message = wintypes.MSG()
        user32.PeekMessageW(ctypes.byref(message), None, 0, 0, 0)
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
        if self._stop_requested.is_set():
            user32.UnhookWindowsHookEx(self._hook)
            self._hook = None
            return
        try:
            while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(message))
                user32.DispatchMessageW(ctypes.byref(message))
        finally:
            if self._hook:
                if not user32.UnhookWindowsHookEx(self._hook):
                    LOGGER.warning("Windows 键盘 Hook 显式解除失败")
                self._hook = None

    def request_stop(self) -> None:
        self._stop_requested.set()
        if sys.platform != "win32" or not self._thread_id or self._post_thread_message is None:
            return
        try:
            if not self._post_thread_message(self._thread_id, self.WM_QUIT, 0, 0):
                LOGGER.debug("Windows 键盘监听退出消息发送失败，等待取消标记生效")
        except (AttributeError, OSError):
            LOGGER.warning("无法停止 Windows 键盘监听线程", exc_info=True)


def _configure_win32_signatures(user32: object, kernel32: object, hook_proc_type: object) -> None:
    """Prevent pointer truncation when Python calls 64-bit Win32 hook APIs."""
    import ctypes
    from ctypes import wintypes

    kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    kernel32.GetModuleHandleW.restype = ctypes.c_void_p
    user32.SetWindowsHookExW.argtypes = [
        ctypes.c_int,
        hook_proc_type,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    user32.SetWindowsHookExW.restype = ctypes.c_void_p
    user32.CallNextHookEx.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]
    user32.CallNextHookEx.restype = ctypes.c_ssize_t
    user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
    user32.UnhookWindowsHookEx.restype = wintypes.BOOL
    user32.PostThreadMessageW.argtypes = [
        wintypes.DWORD,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]
    user32.PostThreadMessageW.restype = wintypes.BOOL


__all__ = ["WindowsKeyboardActivityMonitor"]
