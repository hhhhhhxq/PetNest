"""将透明 PNG 转换为含多尺寸 PNG 条目的 Windows CUR 文件。"""

from __future__ import annotations

import argparse
from io import BytesIO
from pathlib import Path
import struct

from PIL import Image


def build_cursor(source: Path, destination: Path, *, hotspot_x: int, hotspot_y: int) -> None:
    """裁去透明边并写入 32/48/64 像素的 CUR 光标资源。"""
    with Image.open(source) as opened:
        image = opened.convert("RGBA")
    alpha_bounds = image.getchannel("A").getbbox()
    if alpha_bounds is None:
        raise ValueError("光标 PNG 没有可见像素")
    cropped = image.crop(alpha_bounds)
    entries: list[tuple[int, int, bytes]] = []
    for size in (32, 48, 64):
        frame = cropped.copy()
        frame.thumbnail((size, size), Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", (size, size))
        canvas.alpha_composite(frame, ((size - frame.width) // 2, (size - frame.height) // 2))
        stream = BytesIO()
        canvas.save(stream, format="PNG")
        entries.append((size, size, stream.getvalue()))
    offset = 6 + 16 * len(entries)
    directory = [struct.pack("<HHH", 0, 2, len(entries))]
    payload: list[bytes] = []
    for width, height, encoded in entries:
        directory.append(
            struct.pack(
                "<BBBBHHII",
                0 if width == 256 else width,
                0 if height == 256 else height,
                0,
                0,
                hotspot_x,
                hotspot_y,
                len(encoded),
                offset,
            )
        )
        payload.append(encoded)
        offset += len(encoded)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(b"".join(directory + payload))


def main() -> None:
    parser = argparse.ArgumentParser(description="从透明 PNG 构建 Windows CUR 光标")
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--hotspot-x", type=int, default=0)
    parser.add_argument("--hotspot-y", type=int, default=0)
    arguments = parser.parse_args()
    build_cursor(arguments.source, arguments.destination, hotspot_x=arguments.hotspot_x, hotspot_y=arguments.hotspot_y)


if __name__ == "__main__":
    main()
