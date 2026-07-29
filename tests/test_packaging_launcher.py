"""验证冻结包使用的顶层启动器能保留 petnest 包上下文。"""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def test_packaging_launcher_runs_the_check_command() -> None:
    result = subprocess.run(
        [sys.executable, "src/petnest_launcher.py", "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "PetNest 检查通过" in result.stdout
