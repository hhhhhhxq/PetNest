"""将 PNG 序列帧规范为同一透明画布，不覆盖源素材。"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from PIL import Image, UnidentifiedImageError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
from petnest.core.package_validator import natural_sort_key


def normalize_frames(source: Path, destination: Path, width: int, height: int, *, align: str = "center", dry_run: bool = False) -> int:
    """等比缩放并输出连续编号，返回成功转换的帧数量。"""
    frames = sorted((path for path in source.iterdir() if path.suffix.casefold() == ".png"), key=natural_sort_key)
    if not frames:
        raise ValueError("源目录中没有 PNG 帧")
    if not dry_run:
        destination.mkdir(parents=True, exist_ok=True)
    converted = 0
    for index, path in enumerate(frames, start=1):
        try:
            with Image.open(path) as raw:
                image = raw.convert("RGBA")
                image.thumbnail((width, height), Image.Resampling.LANCZOS)
                canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
                x = (width - image.width) // 2
                y = height - image.height if align == "bottom" else (height - image.height) // 2
                canvas.alpha_composite(image, (x, y))
                if not dry_run:
                    canvas.save(destination / f"{index:03d}.png")
                converted += 1
        except (OSError, UnidentifiedImageError) as error:
            print(f"跳过异常图片 {path.name}：{error}", file=sys.stderr)
    return converted


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="统一 PetNest PNG 序列帧画布")
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--width", required=True, type=int)
    parser.add_argument("--height", required=True, type=int)
    parser.add_argument("--align", choices=("center", "bottom"), default="center")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(arguments)
    try:
        count = normalize_frames(args.source, args.destination, args.width, args.height, align=args.align, dry_run=args.dry_run)
    except (OSError, ValueError) as error:
        print(f"规范化失败：{error}", file=sys.stderr)
        return 1
    print(f"已{'检查' if args.dry_run else '写入'} {count} 帧")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
