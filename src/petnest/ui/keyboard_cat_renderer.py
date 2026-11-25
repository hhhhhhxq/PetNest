"""Original native KuroCat on macOS; simplified Qt renderer on other platforms.

See pets/keyboard_cat/LICENSE and NOTICE. Draws locally, without executing skins.
"""

from __future__ import annotations

import sys
from math import sin
from time import monotonic

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QLinearGradient, QBrush, QPainter, QPainterPath, QPen

from petnest.core.keyboard_cat import CatState, cat_preferences
from petnest.core.cat_appearance import custom_coat, resolved_colors
from petnest.ui.cat_coat_painter import paint_coat

# Physical positions, independent of typed characters and IME composition.
KEY_ROWS = (
    ("Esc", "F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10", "F11", "F12"),
    ("`", "1", "2", "3", "4", "5", "6", "7", "8", "9", "0", "-", "=", "Back"),
    ("Tab", "Q", "W", "E", "R", "T", "Y", "U", "I", "O", "P", "[", "]", "\\"),
    ("Caps", "A", "S", "D", "F", "G", "H", "J", "K", "L", ";", "'", "Enter"),
    ("ShiftL", "Z", "X", "C", "V", "B", "N", "M", ",", ".", "/", "ShiftR", "Up"),
    (
        "CtrlL",
        "MetaL",
        "AltL",
        "Space",
        "AltR",
        "MetaR",
        "CtrlR",
        "Left",
        "Down",
        "Right",
    ),
)


def key_positions() -> dict[str, QRectF]:
    result = {}
    for row, keys in enumerate(KEY_ROWS):
        units = len(keys) + (4 if "Space" in keys else 0)
        width = 226 / units
        x = 57.0
        for key in keys:
            w = width * (5 if key == "Space" else 1)
            result[key] = QRectF(x, 226 + row * 11, w - 2, 9)
            x += w
    return result


KEY_POSITIONS = key_positions()


def render_cat(
    state: CatState,
    preferences: object,
    *,
    cursor: QPointF | None = None,
    action: str = "idle",
    dt: float = 1 / 30,
) -> QImage:
    options = cat_preferences(preferences)
    if sys.platform == "darwin":
        from petnest.ui.native_keyboard_cat import NativeCat

        if state.native_renderer is None:
            state.native_renderer = NativeCat()
        return state.native_renderer.render(state, options, cursor, action, dt)
    state.events.clear()
    now = monotonic()
    state.elapsed += max(0, min(dt, 0.1))
    if cursor is not None and options["look"]:
        tx = max(-1.0, min(1.0, (cursor.x() - 180) / 240))
        ty = max(-1.0, min(1.0, (cursor.y() - 125) / 200))
    else:
        tx = ty = 0.0
    ease = min(1.0, dt * 9)
    state.yaw += (tx - state.yaw) * ease
    state.pitch += (ty - state.pitch) * ease
    petted = options["petting"] and now < state.pet_until
    asleep = (
        not state.keys
        and options["sleep_enabled"]
        and (action == "sleep" or now - state.last_activity > options["sleep_seconds"])
    )
    closed = petted or asleep or state.elapsed % 4.7 > 4.55
    cream = options["coat"] == "siamese"
    custom = custom_coat(options)
    colors = resolved_colors(options)
    body = QColor(colors["fur"] if custom else ("#f6efe4" if cream else "#202126"))
    point = QColor(colors["point"] if custom else ("#35261f" if cream else "#292b31"))
    outline = QColor("#9d8572" if cream else "#697a78")
    iris = QColor(colors["eyes"] if custom or "eyes" in options["colors"] else ("#72c7ef" if cream else "#b7dc65"))
    base, keycolor, ink = {
        "cream": ("#d5c7aa", "#fff3d4", "#78654b"),
        "dark": ("#282d35", "#414a55", "#d9e7eb"),
        "retro": ("#9d998c", "#d5d3c7", "#5c6159"),
    }[options["keyboard"]]
    if any(k in options["colors"] for k in ("case", "keys", "accent")):
        base, keycolor = colors["case"], colors["keys"]
    paw = QColor("#FAF6EE") if options["white_markings"]["paws"] else (point if cream else body)
    image = QImage(360, 320, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    def ellipse(x, y, w, h, fill, border=None):
        p.setBrush(fill)
        p.setPen(QPen(border, 1.3) if border else Qt.PenStyle.NoPen)
        p.drawEllipse(QRectF(x, y, w, h))

    def curve(points, color, width):
        path = QPainterPath(QPointF(*points[0]))
        path.cubicTo(*[QPointF(*q) for q in points[1:]])
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QBrush(color), width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawPath(path)

    breath = sin(state.elapsed * (1.2 if asleep else 2.1)) * 1.5
    # Tail and body behind face. Geometry stays within the common 360 x 320 canvas.
    curve(
        [(218, 211), (296, 232), (292, 151), (270 + sin(state.elapsed * 2) * 8, 174)],
        point,
        15,
    )
    ellipse(126, 150 + breath, 112, 94, body, outline)
    if custom:
        rect = QRectF(126, 150 + breath, 112, 94)
        path = QPainterPath(); path.addEllipse(rect)
        paint_coat(p, path, rect, options)
    ellipse(139, 211, 30, 25, paw)
    ellipse(199, 211, 30, 25, paw)
    cx = 182 + state.yaw * 10
    cy = 119 + state.pitch * 6 + breath + (8 if asleep else 0)
    for direction in (-1, 1):
        path = QPainterPath(QPointF(cx + direction * 42, cy - 14))
        path.lineTo(cx + direction * 47, cy - 65)
        path.quadTo(cx + direction * 24, cy - 56, cx + direction * 15, cy - 31)
        path.closeSubpath()
        p.setPen(QPen(outline, 1))
        p.setBrush(point)
        p.drawPath(path)
        path = QPainterPath(QPointF(cx + direction * 39, cy - 27))
        path.lineTo(cx + direction * 42, cy - 51)
        path.lineTo(cx + direction * 26, cy - 33)
        p.setBrush(QColor("#9b756e"))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawPath(path)
    ellipse(cx - 53, cy - 40, 106, 82, body, outline)
    if custom:
        rect = QRectF(cx - 53, cy - 40, 106, 82)
        path = QPainterPath(); path.addEllipse(rect)
        paint_coat(p, path, rect, options, "head")
    elif cream:
        ellipse(cx - 40 + state.yaw * 5, cy - 28, 80, 61, QColor("#6a5041"))
    for direction in (-1, 1):
        ex = cx + direction * 22 + state.yaw * 7
        ey = cy - 5 + state.pitch * 3
        if closed:
            curve(
                [(ex - 10, ey), (ex - 4, ey + 6), (ex + 4, ey + 6), (ex + 10, ey)],
                iris,
                2.4,
            )
        else:
            ellipse(ex - 10, ey - 10, 20, 21, iris)
            ellipse(ex - 3 + state.yaw * 3, ey - 9, 6, 19, QColor("#17181a"))
            ellipse(ex + 2, ey - 7, 3, 4, QColor("#ffffff"))
        for offset in (-5, 3):
            curve(
                [
                    (cx + direction * 25, cy + 16 + offset),
                    (cx + direction * 39, cy + 16 + offset),
                    (cx + direction * 51, cy + 13 + offset),
                    (cx + direction * 63, cy + 11 + offset),
                ],
                outline,
                1.2,
            )
    ellipse(cx - 4 + state.yaw * 5, cy + 14, 8, 5, QColor("#d69b92"))
    curve(
        [(cx - 7, cy + 24), (cx - 3, cy + 29), (cx + 3, cy + 29), (cx + 7, cy + 24)],
        outline,
        1.4,
    )
    # Independent keyboard palette; every supported physical key has a stable hit target.
    p.setPen(QPen(QColor(ink), 1))
    p.setBrush(QColor(base))
    p.drawRoundedRect(QRectF(50, 220, 239, 76), 8, 8)
    p.setFont(QFont("Arial", 5))
    for key, rect in KEY_POSITIONS.items():
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(iris if key in state.keys else QColor(colors["accent"] if key in {"Esc", "Enter"} else keycolor))
        p.drawRoundedRect(rect, 2, 2)
        p.setPen(QColor(ink))
        label = {
            "Space": "",
            "ShiftL": "⇧",
            "ShiftR": "⇧",
            "CtrlL": "^",
            "CtrlR": "^",
            "MetaL": "⌘",
            "MetaR": "⌘",
            "AltL": "⌥",
            "AltR": "⌥",
            "Back": "←",
            "Enter": "↵",
        }.get(key, key)
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)
    ellipse(299, 235, 27, 42, QColor(keycolor), QColor(ink))
    mouse_down = bool(state.keys & {"MouseLeft", "MouseRight"})
    ellipse(309, 241, 6, 10, iris if mouse_down else QColor(colors["accent"]))
    positions = dict(KEY_POSITIONS)
    extra = sorted(state.keys - positions.keys() - {"MouseLeft", "MouseRight"})
    for i, key in enumerate(extra[:12]):
        rect = QRectF(45 + (i % 6) * 45, 300 + (i // 6) * 10, 43, 9)
        positions[key] = rect
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(iris)
        p.drawRoundedRect(rect, 2, 2)
        p.setPen(QColor(ink))
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, key)
    keys = sorted(
        state.keys & positions.keys(), key=lambda k: (positions[k].center().x(), k)
    )
    targets = [positions[k].center() for k in keys]
    if not targets and action in {"working", "thinking"}:
        targets = [QPointF(140 + sin(state.elapsed * 12) * 20, 250)]
    for i, start in enumerate((QPointF(151, 192), QPointF(213, 192))):
        target = (
            targets[min(i, len(targets) - 1)]
            if targets
            else QPointF(146 + i * 70, 220 + sin(state.elapsed * 2 + i) * 2)
        )
        if i == 1 and mouse_down:
            target = QPointF(312, 252)
        arm_fill = body
        arm_tip = paw
        if custom:
            shoulder = image.pixelColor(round(start.x()), round(start.y()))
            if shoulder.alpha() < 240:
                shoulder = body
            arm = QColor.fromRgbF(*(0.8 * a + 0.2 * b for a, b in zip(
                shoulder.getRgbF()[:3], body.getRgbF()[:3], strict=True)))
            arm_tip = paw if cream or options["white_markings"]["paws"] else arm
            gradient = QLinearGradient(start, target)
            transparent = QColor(shoulder)
            transparent.setAlpha(0)
            gradient.setColorAt(0, transparent)
            gradient.setColorAt(0.30, shoulder)
            edge = 0.92 - options["white_markings"]["paws"] * 0.52 if options["white_markings"]["paws"] else 0.62
            gradient.setColorAt(max(0.31, edge - 0.18), arm)
            gradient.setColorAt(min(1.0, edge + 0.14), arm_tip)
            gradient.setColorAt(1, arm_tip)
            arm_fill = gradient
            # A slightly wider, fading under-stroke gives both sides an outline.
            border = QLinearGradient(start, target)
            clear = QColor(outline); clear.setAlpha(0)
            border.setColorAt(0, clear)
            border.setColorAt(0.16, clear)
            border.setColorAt(0.38, outline)
            border.setColorAt(1, outline)
            curve([(start.x(), start.y()), (start.x(), start.y() + 20),
                   (target.x(), target.y() - 12), (target.x(), target.y())], border, 18)
        curve(
            [
                (start.x(), start.y()),
                (start.x(), start.y() + 20),
                (target.x(), target.y() - 12),
                (target.x(), target.y()),
            ],
            arm_fill,
            16,
        )
        ellipse(target.x() - 10, target.y() - 7, 20, 14, arm_tip, outline)
    # Extra simultaneous keys visibly use a foot and the tail.
    if len(targets) >= 3:
        t = targets[2]
        ellipse(t.x() - 10, t.y() - 8, 20, 16, paw, outline)
    if len(targets) >= 4:
        t = targets[3]
        curve(
            [(237, 210), (290, 210), (t.x() + 20, t.y() - 20), (t.x(), t.y())], point, 9
        )
    p.setFont(QFont("Arial", 14))
    p.setPen(iris)
    if asleep:
        p.drawText(QPointF(247, 85), "z Z")
    elif petted:
        p.drawText(QPointF(248, 95), "♥")
    elif action in {"success", "error", "waiting"}:
        p.drawText(
            QPointF(248, 95), {"success": "✓", "error": "!", "waiting": "…"}[action]
        )
    p.end()
    return image
