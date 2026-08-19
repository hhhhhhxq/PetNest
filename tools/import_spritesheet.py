"""将 Codex 标准 `1536 × 1872` 透明 PNG/WebP 图集导入为 PetNest 宠物包。"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from petnest.core.spritesheet_importer import SpriteSheetImportError, SpriteSheetImporter


def main(arguments: list[str] | None = None) -> int:
    """解析本地导入参数；失败时不创建不完整的目标宠物包。"""
    parser = argparse.ArgumentParser(description="导入 Codex 8×9 透明 PNG/静态 WebP 精灵图到 PetNest")
    parser.add_argument("source", type=Path, help="1536×1872 RGBA PNG 或静态 WebP 精灵图")
    parser.add_argument("--pets-root", type=Path, default=PROJECT_ROOT / "pets", help="宠物包输出目录")
    parser.add_argument("--pet-id", required=True, help="小写宠物 ID，例如 codex_cat")
    parser.add_argument("--name", help="显示名称；默认使用 pet-id")
    args = parser.parse_args(arguments)
    try:
        result = SpriteSheetImporter().import_file(args.source, args.pets_root, args.pet_id, name=args.name)
    except (OSError, SpriteSheetImportError) as error:
        print(f"导入失败：{error}", file=sys.stderr)
        return 1
    print(f"导入完成：{result.package_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
