"""命令行校验 PetNest 宠物包。"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from petnest.core.package_validator import PackageValidator


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="校验 PetNest 宠物包")
    parser.add_argument("package", type=Path, help="宠物包目录")
    args = parser.parse_args(arguments)
    result = PackageValidator().validate(args.package)
    for warning in result.warnings:
        print(f"警告：{warning}")
    if result.errors:
        for error in result.errors:
            print(f"错误：{error}", file=sys.stderr)
        return 1
    print(f"通过：{result.root}（{len(result.frames)} 个可用动作）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
