"""精灵图 CLI 工具的端到端入口测试。"""

from __future__ import annotations

from pathlib import Path

from tests.test_spritesheet_importer import _spritesheet
from tools.import_spritesheet import main


def test_command_line_tool_imports_to_requested_pets_directory(tmp_path: Path, capsys: object) -> None:
    source = _spritesheet(tmp_path / "cat.png")

    exit_code = main([str(source), "--pets-root", str(tmp_path / "pets"), "--pet-id", "cli_cat"])

    assert exit_code == 0
    assert (tmp_path / "pets" / "cli_cat" / "pet.json").is_file()
