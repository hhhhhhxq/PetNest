"""Serializable coat recipes. Pattern, white markings and palette are independent."""

from __future__ import annotations

import math
import re
from copy import deepcopy
from pathlib import Path
import sys

# Keep the first two IDs and ordering compatible with existing installations.
COATS = {"black": "纯色", "siamese": "重点色", "shaded": "渐层",
         "tabby": "虎斑", "tortie": "玳瑁", "calico": "三花"}
KEYBOARDS = {"cream": "奶白暖黄", "dark": "暗夜黑", "retro": "复古奶油灰"}
COAT_COLORS = {
    "black": ("#161618", "#161618", "#161618", "#C9F240"),
    "siamese": ("#F1E7D5", "#49372E", "#49372E", "#5EC7FA"),
    "shaded": ("#F4E3BE", "#BA8A49", "#BA8A49", "#A8BB64"),
    "tabby": ("#DEB583", "#AB7949", "#AB7949", "#B4BC73"),
    "tortie": ("#443C36", "#BC895C", "#BC895C", "#CAB377"),
    "calico": ("#F4EBDC", "#D6914D", "#3A3330", "#A7BD67"),
}
KEYBOARD_COLORS = {
    "cream": ("#242429", "#F7F6F0", "#F7B329"),
    "dark": ("#1A1C21", "#363840", "#C4F040"),
    "retro": ("#615C54", "#E6E0D1", "#E06B3D"),
}
COLOR_KEYS = ("fur", "point", "secondary", "eyes", "case", "keys", "accent")
CAT_COLOR_KEYS = COLOR_KEYS[:4]
KEYBOARD_COLOR_KEYS = COLOR_KEYS[4:]
HEX_COLOR = re.compile(r"#[0-9a-fA-F]{6}\Z")
FACE_MARKINGS = {"none": "无", "blaze": "鼻梁白斑", "inverted_v": "倒 V 白脸"}


def asset_root() -> Path:
    return Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[3]


def default_colors(coat="black", keyboard="cream") -> dict[str, str]:
    return dict(zip(COLOR_KEYS, COAT_COLORS.get(coat, COAT_COLORS["black"])
                    + KEYBOARD_COLORS.get(keyboard, KEYBOARD_COLORS["cream"]), strict=True))


def _unit(value, default=0.0):
    if isinstance(value, bool):
        return float(value)
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        return default
    return max(0.0, min(1.0, float(value)))


def appearance_preferences(raw: dict, coat: str, keyboard: str) -> dict:
    # Missing colors preserves the original black/Siamese renderer pixel-for-pixel.
    supplied = raw.get("colors")
    colors = {}
    if isinstance(supplied, dict):
        colors = {key: value.upper() for key, value in supplied.items()
                  if key in COLOR_KEYS and isinstance(value, str) and HEX_COLOR.fullmatch(value)}
    markings = raw.get("white_markings")
    markings = markings if isinstance(markings, dict) else {}
    face = markings.get("face", "none")
    return {
        "colors": colors,
        "white_markings": {
            "face": face if isinstance(face, str) and face in FACE_MARKINGS else "none",
            "chest": _unit(markings.get("chest", 0)),
            "paws": _unit(markings.get("paws", 0)),
            "amount": _unit(markings.get("amount", 0.55), 0.55),
        },
    }


def resolved_colors(options: dict) -> dict[str, str]:
    return {**default_colors(options["coat"], options["keyboard"]), **options.get("colors", {})}


def custom_coat(options: dict) -> bool:
    white = options["white_markings"]
    return (options["coat"] not in ("black", "siamese")
            or any(k in options["colors"] for k in ("fur", "point", "secondary"))
            or white["face"] != "none" or bool(white["chest"] or white["paws"]))


def recipe(coat, *, colors=None, face="none", chest=0.0, paws=0.0):
    return {"coat": coat, "colors": colors or {},
            "white_markings": {"face": face, "chest": chest, "paws": paws, "amount": 0.55}}


PRESETS = {
    "经典黑猫": recipe("black"),
    "奶茶重点色": recipe("siamese"),
    "金色渐层": recipe("shaded"),
    "银色渐层": recipe("shaded", colors={"fur": "#E6E5DF", "point": "#969994", "eyes": "#A8BC75"}),
    "橘子虎斑": recipe("tabby"),
    "银灰虎斑": recipe("tabby", colors={"fur": "#D9D5CA", "point": "#8A8982"}),
    "玳瑁琥珀": recipe("tortie"),
    "三花布丁": recipe("calico"),
    "灰棕重点加白": recipe("siamese", colors={"fur": "#E0DCD3", "point": "#756D64", "eyes": "#85BFD8"}, face="inverted_v", chest=0.8, paws=0.65),
    "棕灰虎斑加白": recipe("tabby", colors={"fur": "#B1A18B", "point": "#71624F", "eyes": "#B7BA6F"}, face="blaze", chest=0.8, paws=0.6),
    "黑白奶牛": recipe("black", face="inverted_v", chest=0.8, paws=0.7),
}


def apply_preset(options, name):
    """A coat preset must not reset keyboard colors, input or movement preferences."""
    value = deepcopy(options)
    old = value.get("colors", {})
    value.update(deepcopy(PRESETS[name]))
    value["colors"].update({k: old[k] for k in ("case", "keys", "accent") if k in old})
    return value


def remember_appearance(options):
    """Checkpoint each style without putting UI history in animation preferences."""
    value = deepcopy(options)
    raw = value.get("appearance_memory")
    raw = raw if isinstance(raw, dict) else {}
    memory = {"coats": {}, "keyboards": {}}
    for group, allowed, keys in (("coats", COATS, CAT_COLOR_KEYS),
                                 ("keyboards", KEYBOARDS, KEYBOARD_COLOR_KEYS)):
        entries = raw.get(group)
        if not isinstance(entries, dict):
            continue
        for key in allowed:
            if not isinstance(entries.get(key), dict):
                continue
            entry = appearance_preferences(entries[key], "black", "cream")
            entry["colors"] = {k: v for k, v in entry["colors"].items() if k in keys}
            if group == "keyboards":
                entry.pop("white_markings")
            memory[group][key] = entry
    coat, keyboard = value.get("coat", "black"), value.get("keyboard", "cream")
    coat = coat if isinstance(coat, str) and coat in COATS else "black"
    keyboard = keyboard if isinstance(keyboard, str) and keyboard in KEYBOARDS else "cream"
    current = appearance_preferences(value, coat, keyboard)
    memory["coats"][coat] = {
        "colors": {k: v for k, v in current["colors"].items() if k in CAT_COLOR_KEYS},
        "white_markings": current["white_markings"],
    }
    memory["keyboards"][keyboard] = {
        "colors": {k: v for k, v in current["colors"].items() if k in KEYBOARD_COLOR_KEYS},
    }
    value["appearance_memory"] = memory
    return value


def switch_appearance(options, *, coat=None, keyboard=None):
    """Restore a style's last edits, while keeping the other category unchanged."""
    value = remember_appearance(options)
    current_coat, current_keyboard = value.get("coat", "black"), value.get("keyboard", "cream")
    current = appearance_preferences(value, current_coat, current_keyboard)
    value.update(current)
    memory = value["appearance_memory"]
    if coat is not None and coat != current_coat and coat in COATS:
        stored = memory["coats"].get(coat, {"colors": {}, "white_markings": current["white_markings"]})
        value["coat"] = coat
        value["colors"] = {**{k: v for k, v in value["colors"].items() if k in KEYBOARD_COLOR_KEYS},
                           **stored["colors"]}
        value["white_markings"] = deepcopy(stored["white_markings"])
    if keyboard is not None and keyboard != current_keyboard and keyboard in KEYBOARDS:
        stored = memory["keyboards"].get(keyboard, {"colors": {}})
        value["keyboard"] = keyboard
        value["colors"] = {**{k: v for k, v in value["colors"].items() if k in CAT_COLOR_KEYS},
                           **stored["colors"]}
    return value


def saved_palettes(raw) -> list[dict]:
    """Validate bounded user presets separately from animation-time preferences."""
    if not isinstance(raw, list):
        return []
    result = []
    for item in raw[:24]:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            continue
        name = item["name"].strip()[:32]
        coat, keyboard = item.get("coat"), item.get("keyboard")
        if not name or not isinstance(coat, str) or coat not in COATS:
            continue
        keyboard = keyboard if isinstance(keyboard, str) and keyboard in KEYBOARDS else "cream"
        result.append({"name": name, "coat": coat, "keyboard": keyboard,
                       **appearance_preferences(item, coat, keyboard)})
    return result
