"""将透明 PNG 转换为含多尺寸 PNG 条目的 Windows CUR 文件。"""

from __future__ import annotations

import argparse
from io import BytesIO
from pathlib import Path
import struct

from PIL import Image


CURSOR_SIZES = (32, 48, 64)


def prepare_cursor_image(source: Path, *, alpha_threshold: int = 8, padding: int = 0) -> Image.Image:
    """清理极低透明度光晕并裁出实际可见区域。"""
    if not 0 <= alpha_threshold < 256:
        raise ValueError("alpha_threshold 必须在 0 到 255 之间")
    if padding < 0:
        raise ValueError("padding 不能为负数")
    with Image.open(source) as opened:
        image = opened.convert("RGBA")
    alpha = image.getchannel("A")
    filtered_alpha = alpha.point(lambda value: value if value > alpha_threshold else 0)
    image.putalpha(filtered_alpha)
    alpha_bounds = filtered_alpha.getbbox()
    if alpha_bounds is None:
        raise ValueError("光标 PNG 没有可见像素")

    left, top, right, bottom = alpha_bounds
    left = max(0, left - padding)
    top = max(0, top - padding)
    right = min(image.width, right + padding)
    bottom = min(image.height, bottom + padding)
    return image.crop((left, top, right, bottom))


def _render_cursor_frame(image: Image.Image, size: int) -> tuple[Image.Image, float, tuple[int, int]]:
    """将裁剪后的图片等比放入方形 CUR 画布。"""
    scale = min(size / image.width, size / image.height)
    width = max(1, round(image.width * scale))
    height = max(1, round(image.height * scale))
    resized = image.resize((width, height), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (size, size))
    offset = ((size - width) // 2, (size - height) // 2)
    canvas.alpha_composite(resized, offset)
    return canvas, scale, offset


def build_cursor(
    source: Path,
    destination: Path,
    *,
    hotspot: tuple[float, float] | None = None,
    hotspot_x: int | None = None,
    hotspot_y: int | None = None,
    alpha_threshold: int = 8,
    padding: int = 0,
    mirror_horizontal: bool = False,
) -> None:
    """裁去透明边并写入 32/48/64 像素的 CUR 光标资源。

    ``hotspot`` 使用裁剪后图像的归一化坐标，可让不同尺寸的 CUR 条目保持
    相同热点；不传入时保留旧版固定像素热点参数的行为。
    """
    if hotspot is not None:
        if len(hotspot) != 2 or any(not 0 <= value <= 1 for value in hotspot):
            raise ValueError("hotspot 必须是 0 到 1 之间的归一化坐标")
        fixed_hotspot = None
    else:
        if hotspot_x is None:
            hotspot_x = 0
        if hotspot_y is None:
            hotspot_y = 0
        fixed_hotspot = (hotspot_x, hotspot_y)

    cropped = prepare_cursor_image(source, alpha_threshold=alpha_threshold, padding=padding)
    if mirror_horizontal:
        cropped = cropped.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        if hotspot is not None:
            hotspot = (1 - hotspot[0], hotspot[1])
    entries: list[tuple[int, int, bytes]] = []
    hotspots: list[tuple[int, int]] = []
    for size in CURSOR_SIZES:
        canvas, scale, offset = _render_cursor_frame(cropped, size)
        if hotspot is not None:
            current_hotspot = (
                round(offset[0] + hotspot[0] * max(0, round(cropped.width * scale) - 1)),
                round(offset[1] + hotspot[1] * max(0, round(cropped.height * scale) - 1)),
            )
        else:
            current_hotspot = fixed_hotspot
        assert current_hotspot is not None
        current_hotspot = (
            min(size - 1, max(0, current_hotspot[0])),
            min(size - 1, max(0, current_hotspot[1])),
        )
        hotspots.append(current_hotspot)
        stream = BytesIO()
        canvas.save(stream, format="PNG")
        entries.append((size, size, stream.getvalue()))
    offset = 6 + 16 * len(entries)
    directory = [struct.pack("<HHH", 0, 2, len(entries))]
    payload: list[bytes] = []
    for index, (width, height, encoded) in enumerate(entries):
        current_hotspot = hotspots[index]
        directory.append(
            struct.pack(
                "<BBBBHHII",
                0 if width == 256 else width,
                0 if height == 256 else height,
                0,
                0,
                current_hotspot[0],
                current_hotspot[1],
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
    parser.add_argument("--alpha-threshold", type=int, default=8)
    parser.add_argument("--padding", type=int, default=0)
    parser.add_argument("--mirror-horizontal", action="store_true")
    arguments = parser.parse_args()
    build_cursor(
        arguments.source,
        arguments.destination,
        hotspot_x=arguments.hotspot_x,
        hotspot_y=arguments.hotspot_y,
        alpha_threshold=arguments.alpha_threshold,
        padding=arguments.padding,
        mirror_horizontal=arguments.mirror_horizontal,
    )


if __name__ == "__main__":
    main()
