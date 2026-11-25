"""Keycap labels drawn as outlines from a bundled OFL font, without OS fallback."""

from functools import lru_cache

from PySide6.QtGui import QFont, QPainterPath, QRawFont, QTransform

from petnest.core.cat_appearance import asset_root

LABELS = {
    "Esc": "ESC",
    "Tab": "TAB",
    "Caps": "CAPS",
    "Back": "DEL",
    "Delete": "DEL",
    "Enter": "ENT",
    "Space": "SPACE",
    "ShiftL": "SHIFT",
    "ShiftR": "SHIFT",
    "CtrlL": "CTRL",
    "CtrlR": "CTRL",
    "AltL": "ALT",
    "AltR": "ALT",
    "MetaL": "META",
    "MetaR": "META",
    "Left": "<",
    "Right": ">",
    "Up": "^",
    "Down": "v",
    "PageUp": "PGUP",
    "PageDown": "PGDN",
    "NumEnter": "ENT",
    "NumLock": "NUM",
    "Scroll": "SCR",
    "Print": "PRT",
    "Pause": "PAUSE",
    "Insert": "INS",
}


@lru_cache(maxsize=1)
def label_font():
    font = QRawFont(
        str(asset_root() / "assets/fonts/NotoSans-Bold.ttf"),
        12,
        QFont.HintingPreference.PreferNoHinting,
    )
    if not font.isValid():
        raise RuntimeError("键盘猫字体资源缺失，请重新安装 PetNest")
    return font


@lru_cache(maxsize=160)
def label_path(key):
    label = LABELS.get(key, key[3:] if key.startswith("Num") else key).upper()
    font = label_font()
    glyphs = font.glyphIndexesForString(label)
    advances = font.advancesForGlyphIndexes(glyphs)
    path, x = QPainterPath(), 0.0
    for glyph, advance in zip(glyphs, advances, strict=True):
        path.addPath(QTransform.fromTranslate(x, 0).map(font.pathForGlyph(glyph)))
        x += advance.x()
    return path


def draw_label(painter, key, rect, color):
    path = label_path(key)
    bounds = path.boundingRect()
    if bounds.isEmpty():
        return
    scale = min(1, rect.width() / bounds.width(), rect.height() / bounds.height())
    painter.save()
    painter.translate(rect.center())
    painter.scale(scale, scale)
    painter.translate(-bounds.center())
    painter.fillPath(path, color)
    painter.restore()
