"""透明 PNG 到 Windows CUR 转换的行为测试。"""

from __future__ import annotations

from pathlib import Path
import struct

from PIL import Image, ImageDraw

from tools.build_cursor_asset import build_cursor, prepare_cursor_image


def _read_cursor_entries(path: Path) -> list[tuple[int, int, int, int]]:
    data = path.read_bytes()
    reserved, kind, count = struct.unpack_from("<HHH", data, 0)
    assert (reserved, kind) == (0, 2)
    entries: list[tuple[int, int, int, int]] = []
    for index in range(count):
        width, height, _colors, _reserved, hotspot_x, hotspot_y, _size, _offset = struct.unpack_from(
            "<BBBBHHII", data, 6 + index * 16
        )
        entries.append((width or 256, height or 256, hotspot_x, hotspot_y))
    return entries


def _read_first_cursor_frame(path: Path) -> Image.Image:
    data = path.read_bytes()
    _width, _height, _colors, _reserved, _hotspot_x, _hotspot_y, size, offset = struct.unpack_from(
        "<BBBBHHII", data, 6
    )
    from io import BytesIO

    with Image.open(BytesIO(data[offset : offset + size])) as opened:
        return opened.convert("RGBA")


def test_prepare_cursor_image_removes_low_alpha_halo(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    image = Image.new("RGBA", (80, 60), (0, 0, 0, 0))
    pixels = image.load()
    pixels[0, 0] = (255, 0, 0, 1)
    ImageDraw.Draw(image).rectangle((20, 10, 59, 49), fill=(255, 0, 0, 255))
    image.save(source)

    cropped = prepare_cursor_image(source, alpha_threshold=8)

    assert cropped.size == (40, 40)
    assert cropped.getchannel("A").getbbox() == (0, 0, 40, 40)


def test_build_cursor_writes_multiple_sizes_and_scales_normalized_hotspot(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    Image.new("RGBA", (20, 40), (255, 128, 0, 255)).save(source)
    destination = tmp_path / "nested" / "cursor.cur"

    build_cursor(source, destination, hotspot=(0.0, 0.0))

    assert _read_cursor_entries(destination) == [
        (32, 32, 8, 0),
        (48, 48, 12, 0),
        (64, 64, 16, 0),
    ]


def test_build_cursor_can_mirror_a_diagonal_cursor(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    image = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    painter = ImageDraw.Draw(image)
    painter.rectangle((0, 0, 15, 31), fill=(255, 0, 0, 255))
    painter.rectangle((16, 0, 31, 31), fill=(0, 0, 255, 255))
    image.save(source)
    destination = tmp_path / "mirrored.cur"

    build_cursor(source, destination, hotspot=(0.5, 0.5), mirror_horizontal=True)

    frame = _read_first_cursor_frame(destination)
    assert frame.getpixel((4, 16))[:3] == (0, 0, 255)
    assert frame.getpixel((28, 16))[:3] == (255, 0, 0)
