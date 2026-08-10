"""本地鼠标样式包的只读发现与校验。"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path


@dataclass(frozen=True, slots=True)
class CursorStyle:
    """一个可用于 Windows 普通箭头的完整样式。"""

    identifier: str
    display_name: str
    preview_path: Path
    arrow_path: Path
    hotspot: tuple[int, int]
    follow_bounds: tuple[int, int, int, int] | None
    roles: dict[str, Path]


class CursorStyleCatalog:
    """从固定的样式目录中返回安全、完整的样式包。"""

    def __init__(self, root: Path) -> None:
        self.root = root

    def discover(self) -> list[CursorStyle]:
        if not self.root.is_dir():
            return []
        styles = [self._read_style(path) for path in self.root.iterdir() if path.is_dir()]
        return sorted((style for style in styles if style is not None), key=lambda style: style.identifier.casefold())

    def get(self, identifier: str | None) -> CursorStyle | None:
        if identifier is None:
            return None
        return next((style for style in self.discover() if style.identifier == identifier), None)

    @staticmethod
    def _read_style(root: Path) -> CursorStyle | None:
        try:
            raw = json.loads((root / "style.json").read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return None
        if not isinstance(raw, dict):
            return None
        identifier = raw.get("id")
        name = raw.get("name")
        preview_name = raw.get("preview")
        arrow_name = raw.get("arrow")
        hotspot = raw.get("hotspot")
        follow_bounds = raw.get("follow_bounds")
        if (
            not isinstance(identifier, str)
            or identifier != root.name
            or not identifier.replace("-", "").replace("_", "").isalnum()
            or not isinstance(name, str)
            or not name.strip()
            or not isinstance(preview_name, str)
            or not isinstance(arrow_name, str)
            or not isinstance(hotspot, list)
            or len(hotspot) != 2
            or any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in hotspot)
        ):
            return None
        if follow_bounds is not None and (
            not isinstance(follow_bounds, list)
            or len(follow_bounds) != 4
            or any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in follow_bounds)
            or follow_bounds[0] > follow_bounds[2]
            or follow_bounds[1] > follow_bounds[3]
        ):
            return None
        preview_path = root / preview_name
        arrow_path = root / arrow_name
        if (
            Path(preview_name).name != preview_name
            or Path(arrow_name).name != arrow_name
            or preview_path.suffix.lower() != ".png"
            or arrow_path.suffix.lower() != ".cur"
            or not preview_path.is_file()
            or not arrow_path.is_file()
        ):
            return None
        roles = {"arrow": arrow_path}
        for role in ("busy", "text", "move", "resize_horizontal", "resize_vertical", "resize_diag_1", "resize_diag_2"):
            candidate = root / f"{role}.cur"
            if candidate.is_file():
                roles[role] = candidate
        parsed_bounds = tuple(follow_bounds) if follow_bounds is not None else None
        return CursorStyle(identifier, name.strip(), preview_path, arrow_path, (hotspot[0], hotspot[1]), parsed_bounds, roles)
