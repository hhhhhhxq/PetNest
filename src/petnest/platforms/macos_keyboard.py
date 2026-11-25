"""Listen-only macOS event tap; physical states stay in memory."""

from __future__ import annotations

from petnest.platforms.physical_keys import MAC_KEYS


class MacOSKeyboardActivityMonitor:
    supported = True

    def __init__(self) -> None:
        self.status_message = "已关闭"
        self._tap = self._source = self._callback = None
        self._key_handler = None
        self._quartz = self._cf = None

    def reconcile_keys(self, keys: set[str]) -> set[str]:
        if self._tap is None:
            return set()
        q = self._quartz
        if not q.CGPreflightListenEventAccess():
            self.stop()
            self.status_message = "输入监控权限已关闭，请授权后重新检测"
            return set()
        codes = {name: code for code, name in MAC_KEYS.items()}
        source = q.kCGEventSourceStateCombinedSessionState
        active = {
            key
            for key in keys
            if key in codes and q.CGEventSourceKeyState(source, codes[key])
        }
        for name, button in (("MouseLeft", 0), ("MouseRight", 1)):
            if name in keys and q.CGEventSourceButtonState(source, button):
                active.add(name)
        return active

    def set_key_handler(self, handler) -> None:
        self._key_handler = handler

    def _emit(self, key, down):
        if self._key_handler is not None:
            self._key_handler(key, down)

    def start(self, on_activity) -> bool:
        if self._tap is not None:
            return True
        try:
            import CoreFoundation as cf
            import Quartz as q

            self._quartz, self._cf = q, cf
            if not q.CGPreflightListenEventAccess():
                self.status_message = "需要允许 PetNest 的输入监控；授权后点击重新检测"
                return False

            def callback(proxy, event_type, event, refcon):
                try:
                    if event_type in (
                        q.kCGEventTapDisabledByTimeout,
                        q.kCGEventTapDisabledByUserInput,
                    ):
                        self._emit("reset", False)
                        if self._tap is not None:
                            q.CGEventTapEnable(self._tap, True)
                        return event
                    if event_type in (
                        q.kCGEventLeftMouseDown,
                        q.kCGEventLeftMouseUp,
                        q.kCGEventRightMouseDown,
                        q.kCGEventRightMouseUp,
                    ):
                        key = (
                            "MouseLeft"
                            if event_type
                            in (q.kCGEventLeftMouseDown, q.kCGEventLeftMouseUp)
                            else "MouseRight"
                        )
                        self._emit(
                            key,
                            event_type
                            in (q.kCGEventLeftMouseDown, q.kCGEventRightMouseDown),
                        )
                        return event
                    code = q.CGEventGetIntegerValueField(
                        event, q.kCGKeyboardEventKeycode
                    )
                    key = MAC_KEYS.get(code)
                    if event_type == q.kCGEventFlagsChanged:
                        down = bool(
                            q.CGEventSourceKeyState(
                                q.kCGEventSourceStateCombinedSessionState, code
                            )
                        )
                    else:
                        down = event_type == q.kCGEventKeyDown
                    if down:
                        on_activity()
                    if key is not None:
                        self._emit(key, down)
                except Exception:  # noqa: BLE001 - never unwind across a native callback.
                    # Never log native key data or exceptions containing event objects.
                    self._emit("reset", False)
                return event

            self._callback = callback
            types = [
                q.kCGEventKeyDown,
                q.kCGEventKeyUp,
                q.kCGEventFlagsChanged,
                q.kCGEventLeftMouseDown,
                q.kCGEventLeftMouseUp,
                q.kCGEventRightMouseDown,
                q.kCGEventRightMouseUp,
            ]
            self._tap = q.CGEventTapCreate(
                q.kCGSessionEventTap,
                q.kCGHeadInsertEventTap,
                q.kCGEventTapOptionListenOnly,
                sum(1 << t for t in types),
                callback,
                None,
            )
            if self._tap is None:
                self._callback = None
                self.status_message = (
                    "无法启动输入监听，请检查输入监控权限或重启 PetNest"
                )
                return False
            self._source = cf.CFMachPortCreateRunLoopSource(None, self._tap, 0)
            cf.CFRunLoopAddSource(
                cf.CFRunLoopGetMain(), self._source, cf.kCFRunLoopCommonModes
            )
            q.CGEventTapEnable(self._tap, True)
            self.status_message = "监听正常"
            return True
        except (ImportError, AttributeError, RuntimeError):
            self.stop()
            self.status_message = "输入监听组件不可用，请更新或重新安装 PetNest"
            return False

    def permission_granted(self) -> bool:
        """A passive check; never presents a system prompt."""
        try:
            import Quartz

            return bool(Quartz.CGPreflightListenEventAccess())
        except (ImportError, AttributeError):
            return False

    @staticmethod
    def authorization_target():
        """Return this process's app bundle, or its real source interpreter."""
        import sys
        from pathlib import Path

        executable = Path(sys.executable).resolve()
        return next(
            (path for path in executable.parents if path.suffix == ".app"), executable
        )

    def reveal_authorization_target(self) -> None:
        from AppKit import NSWorkspace
        from Foundation import NSURL
        from PySide6.QtWidgets import QApplication

        target = self.authorization_target()
        QApplication.clipboard().setText(str(target))
        NSWorkspace.sharedWorkspace().activateFileViewerSelectingURLs_(
            [NSURL.fileURLWithPath_(str(target))]
        )

    def request_permission(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        try:
            import Quartz

            Quartz.CGRequestListenEventAccess()
        except (ImportError, AttributeError):
            pass
        if self.permission_granted():
            return
        QDesktopServices.openUrl(
            QUrl(
                "x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent"
            )
        )

    def stop(self) -> None:
        if self._tap is not None:
            self._quartz.CGEventTapEnable(self._tap, False)
            if self._source is not None:
                self._cf.CFRunLoopRemoveSource(
                    self._cf.CFRunLoopGetMain(),
                    self._source,
                    self._cf.kCFRunLoopCommonModes,
                )
            self._cf.CFMachPortInvalidate(self._tap)
        self._tap = self._source = self._callback = None
        self._emit("reset", False)
        self.status_message = "已关闭"
