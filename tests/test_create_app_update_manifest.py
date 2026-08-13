"""发布清单生成器的命令行回归测试。"""

from __future__ import annotations

import json
from pathlib import Path

from tools.create_app_update_manifest import main


def test_main_reads_utf8_release_notes_from_a_file(tmp_path: Path) -> None:
    installer = tmp_path / "PetNest-Setup.exe"
    installer.write_bytes(b"installer")
    notes = tmp_path / "release-notes.txt"
    expected = "修复 Windows 自动更新后应用未重新启动的问题。"
    notes.write_text(expected, encoding="utf-8")
    output = tmp_path / "app-update.json"

    result = main(
        [
            "--version",
            "0.1.5",
            "--installer",
            str(installer),
            "--url",
            "https://github.com/hhhhhhxq/PetNest/releases/download/v0.1.5/PetNest-Setup-0.1.5.exe",
            "--notes-file",
            str(notes),
            "--output",
            str(output),
        ]
    )

    assert result == 0
    assert json.loads(output.read_text(encoding="utf-8"))["release_notes"] == expected
