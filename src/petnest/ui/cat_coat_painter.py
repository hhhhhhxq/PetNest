"""Cached color-independent coat artwork shared by all renderers."""

from functools import lru_cache

from PySide6.QtGui import QColor, QImage

from petnest.core.cat_appearance import asset_root


@lru_cache(maxsize=24)
def tabby_texture(color):
    alpha = QImage(str(asset_root() / "assets/cat_coats/tabby-mask.png"))
    alpha = alpha.scaled(256, 384).convertToFormat(QImage.Format.Format_Grayscale8)
    alpha.reinterpretAsFormat(QImage.Format.Format_Alpha8)
    image = QImage(alpha.size(), QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor(color))
    image.setAlphaChannel(alpha)
    return image
