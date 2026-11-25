"""Qt coat layers for the non-macOS renderer, using the shared tabby artwork."""

from functools import lru_cache

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainterPath, QRadialGradient

from petnest.core.cat_appearance import asset_root, resolved_colors


@lru_cache(maxsize=24)
def tabby_texture(color):
    alpha = QImage(str(asset_root() / "assets/cat_coats/tabby-mask.png"))
    alpha = alpha.scaled(256, 384).convertToFormat(QImage.Format.Format_Grayscale8)
    alpha.reinterpretAsFormat(QImage.Format.Format_Alpha8)
    image = QImage(alpha.size(), QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor(color))
    image.setAlphaChannel(alpha)
    return image


def paint_coat(painter, path, rect, options, part="body"):
    colors = resolved_colors(options)
    fur, point, other = (QColor(colors[k]) for k in ("fur", "point", "secondary"))
    coat, marks = options["coat"], options["white_markings"]
    white = QColor("#FAF6EE")
    painter.save()
    painter.setClipPath(path)
    painter.fillRect(rect, fur)
    painter.translate(rect.x(), rect.y())
    painter.scale(rect.width() / 100, rect.height() / 100)

    def spot(x, y, rx, ry, color):
        painter.save()
        painter.translate(x, y)
        painter.scale(rx, ry)
        gradient = QRadialGradient(QPointF(0, 0), 1)
        gradient.setColorAt(0, color)
        gradient.setColorAt(0.45, color)
        end = QColor(color); end.setAlpha(0)
        gradient.setColorAt(1, end)
        painter.fillRect(QRectF(-1, -1, 2, 2), gradient)
        painter.restore()

    if coat == "tabby":
        texture = tabby_texture(colors["point"])
        source = QRectF(0, 0, 256, 115) if part == "head" else QRectF(0, 115, 256, 269)
        target = QRectF(0, 0, 100, 53) if part == "head" else QRectF(0, 0, 100, 100)
        painter.setOpacity(0.75)
        painter.drawImage(target, texture, source)
        painter.setOpacity(1)
    elif coat == "shaded":
        if part == "head":
            spot(50, 0, 70, 55, point)
        else:
            spot(0, 35, 40, 95, point); spot(100, 35, 40, 95, point)
    elif coat == "siamese" and part == "head":
        spot(50, 40, 70, 75, point)
    elif coat in ("tortie", "calico"):
        if part == "head":
            spot(13, 20, 30, 60, point)
            if coat == "calico":
                spot(90, 45, 35, 60, other)
        else:
            spot(90, 30, 36, 42, point)
            spot(10, 85, 38, 55, other if coat == "calico" else point)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(white)
    if part == "body" and marks["chest"]:
        width = 24 + marks["amount"] * 16
        bottom = 32 + marks["chest"] * 60
        bib = QPainterPath(QPointF(30, 0))
        bib.cubicTo(50 - width, 28, 50 - width, bottom - 25, 50, bottom)
        bib.cubicTo(50 + width, bottom - 25, 50 + width, 28, 70, 0)
        bib.closeSubpath(); painter.drawPath(bib)
    elif part == "head" and marks["face"] != "none":
        width = (23 if marks["face"] == "inverted_v" else 12) + marks["amount"] * 12
        blaze = QPainterPath(QPointF(50, 12))
        blaze.cubicTo(42, 20, 49, 56, 50 - width, 75)
        blaze.quadTo(50, 110, 50 + width, 75)
        blaze.cubicTo(51, 56, 58, 20, 50, 12)
        painter.drawPath(blaze)
    painter.restore()
