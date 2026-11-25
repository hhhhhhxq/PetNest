"""Original MIT KuroCat renderer via a small, packaged Swift C ABI (macOS)."""

from __future__ import annotations

import ctypes
import json
import sys
from functools import lru_cache
from pathlib import Path
from time import monotonic

from PySide6.QtGui import QImage

from petnest.platforms.physical_keys import MAC_KEYS
from petnest.core.cat_appearance import asset_root, custom_coat, resolved_colors

KEY_CODES = {name: code for code, name in MAC_KEYS.items()}
KEY_CODES.update(reset=-1, MouseLeft=-2, MouseRight=-3)


@lru_cache(maxsize=1)
def native_library():
    if getattr(sys, "frozen", False):
        path = Path(sys._MEIPASS) / "native" / "libpetnest_cat.dylib"
    else:
        path = Path(__file__).resolve().parents[3] / "build/native/libpetnest_cat.dylib"
    lib = ctypes.CDLL(str(path))
    lib.petnest_cat_create.argtypes = []
    lib.petnest_cat_create.restype = ctypes.c_void_p
    lib.petnest_cat_destroy.argtypes = [ctypes.c_void_p]
    lib.petnest_cat_destroy.restype = None
    lib.petnest_cat_key.argtypes = [ctypes.c_void_p, ctypes.c_int32, ctypes.c_int32]
    lib.petnest_cat_key.restype = None
    lib.petnest_cat_appearance.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    lib.petnest_cat_appearance.restype = None
    lib.petnest_cat_render.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_double,
        ctypes.c_double,
        ctypes.c_double,
        ctypes.c_int32,
        ctypes.c_int32,
        ctypes.c_int32,
        ctypes.c_int32,
        ctypes.c_double,
    ]
    lib.petnest_cat_render.restype = ctypes.c_int32
    return lib


class NativeCat:
    def __init__(self):
        self.lib = native_library()
        self.handle = self.lib.petnest_cat_create()
        self.pixels = (ctypes.c_ubyte * (360 * 320 * 4))()
        self.held: set[str] = set()
        self.appearance = None

    def __del__(self):
        if getattr(self, "handle", None):
            self.lib.petnest_cat_destroy(self.handle)
            self.handle = None

    def render(self, state, options, cursor, action, dt):
        appearance = {
            "coat": options["coat"], "colors": resolved_colors(options),
            "white_markings": options["white_markings"],
            "custom_coat": custom_coat(options),
            "custom_eyes": "eyes" in options["colors"] or custom_coat(options),
            "custom_keyboard": any(k in options["colors"] for k in ("case", "keys", "accent")),
            "mask_path": str(asset_root() / "assets/cat_coats/tabby-mask.png"),
        }
        if appearance != self.appearance:
            self.lib.petnest_cat_appearance(self.handle, json.dumps(appearance).encode("utf-8"))
            self.appearance = appearance
        # Preserve short taps even when both edges arrive between animation frames.
        for key, down in state.events:
            if key in KEY_CODES:
                self.lib.petnest_cat_key(self.handle, KEY_CODES[key], int(down))
            if key == "reset":
                self.held.clear()
            elif down:
                self.held.add(key)
            else:
                self.held.discard(key)
        state.events.clear()
        # Native reconciliation can clear held keys after lost releases/permission changes.
        for key in self.held - state.keys:
            if key in KEY_CODES:
                self.lib.petnest_cat_key(self.handle, KEY_CODES[key], 0)
        self.held.intersection_update(state.keys)
        age = monotonic() - state.last_activity
        idle = (
            max(0, age - options["sleep_seconds"] + 45)
            if options["sleep_enabled"]
            else 0
        )
        if action == "sleep" and options["sleep_enabled"]:
            idle = max(idle, 80)
        ok = self.lib.petnest_cat_render(
            self.handle,
            self.pixels,
            cursor.x() if cursor is not None else 184,
            cursor.y() if cursor is not None else 124,
            dt,
            int(options["coat"] == "siamese"),
            {"cream": 0, "dark": 1, "retro": 2}[options["keyboard"]],
            int(options["look"] and cursor is not None),
            int(options["petting"]),
            idle,
        )
        if not ok:
            raise RuntimeError("无法绘制键盘猫")
        return QImage(
            self.pixels, 360, 320, 360 * 4, QImage.Format.Format_RGBA8888_Premultiplied
        ).copy()
