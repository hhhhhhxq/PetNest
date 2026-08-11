"""Lottie 导入 CLI 的可分享参数测试。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from tests.test_lottie_effects import _lottie_file
from tools.import_lottie_effect import main


def test_lottie_cli_writes_requested_layer(tmp_path: Path, monkeypatch) -> None:
    source = _lottie_file(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "import_lottie_effect.py",
            str(source),
            "--effect-id",
            "heart",
            "--effects-root",
            str(tmp_path / "effects"),
            "--layer",
            "under",
        ],
    )

    assert main() == 0
    assert json.loads((tmp_path / "effects" / "heart" / "effect.json").read_text(encoding="utf-8"))["layer"] == "under"
