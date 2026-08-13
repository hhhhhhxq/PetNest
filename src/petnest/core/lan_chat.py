"""Safe preparation of local images for bounded LAN chat transfer."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from petnest.models.lan_interaction import MAX_CHAT_IMAGE_BYTES


class LanChatImageError(ValueError):
    pass


def validate_chat_image_data(data: bytes, *, max_dimension: int = 1_600) -> None:
    """Reject malformed or unexpectedly large images before Qt renders them."""
    if not isinstance(data, bytes) or not data:
        raise LanChatImageError("聊天图片内容为空")
    try:
        with Image.open(BytesIO(data)) as image:
            width, height = image.size
            if image.format != "JPEG":
                raise LanChatImageError("聊天图片必须是 JPEG")
            if width <= 0 or height <= 0 or width > max_dimension or height > max_dimension:
                raise LanChatImageError("聊天图片尺寸超过安全上限")
            image.verify()
    except LanChatImageError:
        raise
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as error:
        raise LanChatImageError(f"聊天图片无法解码：{error}") from error


def prepare_chat_image(
    path: Path,
    *,
    max_source_bytes: int = 20 * 1024 * 1024,
    max_dimension: int = 1_600,
) -> tuple[bytes, str]:
    """Decode, orient, resize and encode a static JPEG without altering source."""
    source = path.expanduser()
    try:
        size = source.stat().st_size
    except OSError as error:
        raise LanChatImageError(f"无法读取图片：{error}") from error
    if not source.is_file() or size <= 0:
        raise LanChatImageError("请选择有效的图片文件")
    if size > max_source_bytes:
        raise LanChatImageError("原图超过 20 MB 安全上限")
    try:
        with Image.open(source) as opened:
            opened.load()
            oriented = ImageOps.exif_transpose(opened)
            image = oriented.convert("RGBA")
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as error:
        raise LanChatImageError(f"图片无法解码：{error}") from error
    try:
        image.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)
        background = Image.new("RGB", image.size, "white")
        background.paste(image, mask=image.getchannel("A"))
        quality = 88
        while True:
            output = BytesIO()
            background.save(output, format="JPEG", quality=quality, optimize=True)
            data = output.getvalue()
            if len(data) <= MAX_CHAT_IMAGE_BYTES:
                safe_stem = "".join(
                    char for char in source.stem if char.isalnum() or char in {"-", "_", " "}
                ).strip()[:80]
                return data, f"{safe_stem or 'image'}.jpg"
            if quality > 58:
                quality -= 10
                continue
            width, height = background.size
            if width <= 320 or height <= 320:
                raise LanChatImageError("图片压缩后仍超过 1.5 MB")
            resized = background.resize(
                (max(320, round(width * 0.8)), max(320, round(height * 0.8))),
                Image.Resampling.LANCZOS,
            )
            background.close()
            background = resized
            quality = 78
    finally:
        image.close()
        if "background" in locals():
            background.close()


__all__ = ["LanChatImageError", "prepare_chat_image", "validate_chat_image_data"]
