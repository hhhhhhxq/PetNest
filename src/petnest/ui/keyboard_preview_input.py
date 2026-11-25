"""Normalize local Qt key events to the same physical names as global hooks."""

import sys

from PySide6.QtCore import Qt

from petnest.platforms.physical_keys import MAC_KEYS, WINDOWS_KEYS


def preview_key(event):
    native = event.nativeVirtualKey()
    if sys.platform == "darwin" and (native or event.key() == Qt.Key.Key_A):
        # macOS virtual code 0 is a valid A key, not an absent code.
        key = MAC_KEYS.get(native)
        if key is not None:
            return key
    elif sys.platform == "win32" and native:
        key = WINDOWS_KEYS.get(native)
        if key is not None:
            return key
    # Synthetic Qt events and unsupported global-hook platforms still allow previews.
    key = event.key()
    if Qt.Key.Key_A <= key <= Qt.Key.Key_Z or Qt.Key.Key_0 <= key <= Qt.Key.Key_9:
        return chr(key)
    if Qt.Key.Key_F1 <= key <= Qt.Key.Key_F35:
        return f"F{key-Qt.Key.Key_F1+1}"
    names = {
        Qt.Key.Key_Escape: "Esc",
        Qt.Key.Key_Tab: "Tab",
        Qt.Key.Key_Backspace: "Back",
        Qt.Key.Key_Return: "Enter",
        Qt.Key.Key_Enter: "NumEnter",
        Qt.Key.Key_Space: "Space",
        Qt.Key.Key_Shift: "ShiftL",
        Qt.Key.Key_Control: "CtrlL",
        Qt.Key.Key_Alt: "AltL",
        Qt.Key.Key_Meta: "MetaL",
        Qt.Key.Key_CapsLock: "Caps",
        Qt.Key.Key_Delete: "Delete",
        Qt.Key.Key_Left: "Left",
        Qt.Key.Key_Right: "Right",
        Qt.Key.Key_Up: "Up",
        Qt.Key.Key_Down: "Down",
        Qt.Key.Key_Home: "Home",
        Qt.Key.Key_End: "End",
        Qt.Key.Key_PageUp: "PageUp",
        Qt.Key.Key_PageDown: "PageDown",
    }
    if key in names:
        return names[key]
    return chr(key) if key in map(ord, "`-=[]\\;',./") else None
