"""鼠标样式目录发现的行为测试。"""

from __future__ import annotations

import json
from pathlib import Path

from petnest.core.cursor_style_catalog import CursorStyleCatalog


def _write_style(root: Path, identifier: str, *, with_cursor: bool) -> None:
    style_root = root / identifier
    style_root.mkdir()
    (style_root / "style.json").write_text(
        json.dumps(
            {
                "id": identifier,
                "name": "深灰肉垫" if identifier == "paw" else identifier,
                "preview": "arrow.png",
                "arrow": "arrow.cur",
                "hotspot": [0, 0],
            }
        ),
        encoding="utf-8",
    )
    (style_root / "arrow.png").write_bytes(b"preview")
    if with_cursor:
        (style_root / "arrow.cur").write_bytes(b"cursor")


def test_catalog_only_returns_complete_cursor_styles(tmp_path: Path) -> None:
    _write_style(tmp_path, "paw", with_cursor=True)
    _write_style(tmp_path, "broken", with_cursor=False)

    styles = CursorStyleCatalog(tmp_path).discover()

    assert [(style.identifier, style.display_name) for style in styles] == [("paw", "深灰肉垫")]
    assert styles[0].hotspot == (0, 0)
