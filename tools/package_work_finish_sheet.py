"""把平安的 8×3 原始图集切成标准下班动画包。"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import tempfile

from PIL import Image, ImageChops, ImageFilter, UnidentifiedImageError


SHEET_SIZE = (2172, 724)
FRAME_SIZE = (312, 242)
GRID_SIZE = (7, 3)
WALK_CELLS = tuple((column, 0) for column in range(7))
LIE_DOWN_CELLS = tuple((column, row) for row in (1, 2) for column in range(7))


class WorkFinishSheetError(ValueError):
    """原始图集无法安全转换。"""


def package_sheet(source: Path, output: Path, *, name: str = "平安下班") -> Path:
    """切出 8 帧走路和 13 帧躺下，并生成可导入目录。"""
    source = Path(source).expanduser().resolve()
    output = Path(output).expanduser().resolve()
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise WorkFinishSheetError("输出目录已经存在且非空")
    try:
        with Image.open(source) as opened:
            opened.load()
            if opened.size != SHEET_SIZE:
                raise WorkFinishSheetError("原始图集必须是 2172×724 像素")
            sheet = opened.convert("RGBA")
    except WorkFinishSheetError:
        raise
    except (OSError, UnidentifiedImageError) as error:
        raise WorkFinishSheetError(f"原始图集无法读取：{error}") from error

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{output.name}-", dir=output.parent) as temporary:
        bundle = Path(temporary) / "bundle"
        walk_frames = _export_phase(sheet, WALK_CELLS, bundle / "walk")
        lie_down_frames = _export_phase(sheet, LIE_DOWN_CELLS, bundle / "lie-down")
        manifest = {
            "name": name,
            "canvas": {"width": FRAME_SIZE[0], "height": FRAME_SIZE[1]},
            "walk": {"path": "walk", "fps": 10},
            "lie_down": {"path": "lie-down", "fps": 7},
        }
        (bundle / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        _write_preview((*walk_frames, *lie_down_frames), bundle / "preview.png")
        if output.exists():
            output.rmdir()
        os.replace(bundle, output)
    return output


def _export_phase(sheet: Image.Image, cells: tuple[tuple[int, int], ...], destination: Path) -> tuple[Image.Image, ...]:
    destination.mkdir(parents=True)
    frames: list[Image.Image] = []
    width, height = FRAME_SIZE
    for index, (column, row) in enumerate(cells, start=1):
        source_width, source_height = sheet.size
        columns, rows = GRID_SIZE
        box = (
            round(column * source_width / columns),
            round(row * source_height / rows),
            round((column + 1) * source_width / columns),
            round((row + 1) * source_height / rows),
        )
        cropped = sheet.crop(box)
        frame = Image.new("RGBA", FRAME_SIZE, (0, 0, 0, 0))
        frame.alpha_composite(cropped, ((width - cropped.width) // 2, (height - cropped.height) // 2))
        frame = _keep_largest_alpha_component(frame)
        frame.save(destination / f"{index:03d}.png")
        frames.append(frame)
    return tuple(frames)


def _keep_largest_alpha_component(frame: Image.Image) -> Image.Image:
    """保留主体连通区域及其抗锯齿边缘，去掉散落在透明区的噪点。"""
    alpha = frame.getchannel("A")
    opaque = alpha.point(lambda value: 255 if value >= 16 else 0).tobytes()
    width, height = frame.size
    visited = bytearray(len(opaque))
    largest: list[int] = []
    for start, value in enumerate(opaque):
        if value == 0 or visited[start]:
            continue
        visited[start] = 1
        component: list[int] = []
        pending = [start]
        while pending:
            index = pending.pop()
            component.append(index)
            x = index % width
            neighbours = (index - width, index + width)
            if x:
                neighbours += (index - 1,)
            if x + 1 < width:
                neighbours += (index + 1,)
            for neighbour in neighbours:
                if 0 <= neighbour < len(opaque) and opaque[neighbour] and not visited[neighbour]:
                    visited[neighbour] = 1
                    pending.append(neighbour)
        if len(component) > len(largest):
            largest = component
    if not largest:
        return frame.copy()
    mask_data = bytearray(len(opaque))
    for index in largest:
        mask_data[index] = 255
    mask = Image.frombytes("L", frame.size, bytes(mask_data)).filter(ImageFilter.MaxFilter(5))
    cleaned = frame.copy()
    cleaned.putalpha(ImageChops.multiply(alpha, mask))
    return cleaned


def _write_preview(frames: tuple[Image.Image, ...], destination: Path) -> None:
    columns = 4
    rows = (len(frames) + columns - 1) // columns
    preview = Image.new("RGBA", (columns * FRAME_SIZE[0], rows * FRAME_SIZE[1]), (0, 0, 0, 0))
    for index, frame in enumerate(frames):
        preview.alpha_composite(frame, ((index % columns) * FRAME_SIZE[0], (index // columns) * FRAME_SIZE[1]))
    preview.save(destination)


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="把 2172×724 平安图集切成 PetNest 下班动画包")
    parser.add_argument("source", type=Path, help="原始透明 PNG 图集")
    parser.add_argument("output", type=Path, help="标准动画包输出目录")
    parser.add_argument("--name", default="平安下班", help="导入时显示的动画名称")
    args = parser.parse_args(arguments)
    try:
        result = package_sheet(args.source, args.output, name=args.name)
    except WorkFinishSheetError as error:
        print(f"切分失败：{error}")
        return 1
    print(f"动画包已生成：{result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["WorkFinishSheetError", "package_sheet"]
