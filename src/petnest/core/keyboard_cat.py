"""Keyboard cat preferences and transient physical-key state (never persisted)."""

from __future__ import annotations

from dataclasses import dataclass, field
from time import monotonic
from petnest.core.cat_appearance import COATS, KEYBOARDS, appearance_preferences

CAT_RENDERER = "keyboard-cat-v1"


def cat_preferences(raw: object) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    options = {
        "coat": raw.get("coat")
        if isinstance(raw.get("coat"), str) and raw.get("coat") in COATS
        else "black",
        "keyboard": raw.get("keyboard")
        if isinstance(raw.get("keyboard"), str) and raw.get("keyboard") in KEYBOARDS
        else "cream",
        "look": raw.get("look", True) is True,
        "petting": raw.get("petting", True) is True,
        "sleep_enabled": raw.get("sleep_enabled", True) is True,
        "sleep_seconds": max(1, min(86400, raw.get("sleep_seconds", 40)))
        if isinstance(raw.get("sleep_seconds", 40), int)
        else 40,
    }
    options.update(appearance_preferences(raw, options["coat"], options["keyboard"]))
    return options


@dataclass
class CatState:
    keys: set[str] = field(default_factory=set)
    last_activity: float = field(default_factory=monotonic)
    last_tick: float = field(default_factory=monotonic)
    events: list[tuple[str, bool]] = field(default_factory=list, repr=False)
    motion: object | None = field(default=None, repr=False, compare=False)

    def key_event(self, key: str, down: bool) -> None:
        if len(self.events) < 512:
            self.events.append((key, down))
        if key == "reset":
            self.keys.clear()
        elif down:
            self.keys.add(key)
        else:
            self.keys.discard(key)
        self.last_activity = monotonic()

    def reset(self) -> None:
        self.keys.clear()
        self.events[:] = [("reset", False)]
        self.last_tick = monotonic()
