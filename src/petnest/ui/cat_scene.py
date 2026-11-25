"""Portable drawing of the approved KuroCat geometry and PetNest coat layers.

This is the single production scene for macOS and Windows. The MIT Swift source
in native/kurocat is retained as a reference, not as a platform-specific backend.
"""

from math import atan2, cos, sin, hypot, pi, acos, tan

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPainterPathStroker,
    QPen,
    QRadialGradient,
)

from petnest.core.cat_appearance import custom_coat, resolved_colors
from petnest.core.cat_motion import KEYCAPS, Point as P, clamp, key_point, quad_point
from petnest.ui.cat_coat_painter import tabby_texture


def color(r, g=None, b=None, a=1):
    return QColor(r) if g is None else QColor.fromRgbF(r, g, b, a)


def alpha(c, value):
    c = QColor(c)
    c.setAlphaF(clamp(value))
    return c


def blend(a, b, fraction):
    return QColor.fromRgbF(
        *(
            x + (y - x) * clamp(fraction)
            for x, y in zip(a.getRgbF(), b.getRgbF(), strict=True)
        )
    )


# Original calibrated Mac palette converted once to fixed sRGB for both systems.
BLACK = color(0.1110998, 0.1115786, 0.1255719)
MINT = color(0.8518631, 0.9337629, 0.9117690, 0.76)
WHISKER = color(0.9031549, 0.9200640, 0.9361239, 0.68)
CREAM, LATTE = color(0.9569027, 0.9227479, 0.8662919), color(
    0.8925753, 0.8318188, 0.7476310
)
MOCHA, POINT = color(0.5269890, 0.4150698, 0.3396026), color(
    0.2317127, 0.1712261, 0.1393352
)
OUTLINE, SIAMESE_WHISKER = color(0.3308350, 0.2492074, 0.2052527, 0.88), color(
    0.4373493, 0.3406742, 0.2834527, 0.68
)
WHITE = color(0.98, 0.965, 0.935)


def q(point):
    return QPointF(point.x, point.y)


class Path(QPainterPath):
    def __init__(self, start=None):
        super().__init__()
        self.setFillRule(Qt.FillRule.WindingFill)
        if start is not None:
            self.moveTo(q(start))

    def line(self, point):
        self.lineTo(q(point))
        return self

    def cubic(self, end, control1, control2):
        self.cubicTo(q(control1), q(control2), q(end))
        return self

    def quad(self, end, control):
        self.quadTo(q(control), q(end))
        return self

    def close(self):
        self.closeSubpath()
        return self


def ellipse(rect):
    path = Path()
    path.addEllipse(rect)
    return path


def rounded(rect, radius):
    path = Path()
    path.addRoundedRect(rect, radius, radius)
    return path


def polyline(points):
    path = Path(points[0])
    for point in points[1:]:
        path.line(point)
    return path


def rounded_quad(points, radius):
    """Circular tangent corners, matching CGPath.addArc(tangent1End:...)."""
    corners = []
    for i, point in enumerate(points):
        before, after = points[i - 1], points[(i + 1) % len(points)]
        lu, lv = hypot(before.x - point.x, before.y - point.y), hypot(
            after.x - point.x, after.y - point.y
        )
        ux, uy = (before.x - point.x) / lu, (before.y - point.y) / lu
        vx, vy = (after.x - point.x) / lv, (after.y - point.y) / lv
        angle = acos(clamp(ux * vx + uy * vy, -1, 1))
        distance = min(radius / max(0.001, tan(angle / 2)), lu / 2, lv / 2)
        r = distance * tan(angle / 2)
        handle = 4 / 3 * tan((pi - angle) / 4) * r
        a, b = P(point.x + ux * distance, point.y + uy * distance), P(
            point.x + vx * distance, point.y + vy * distance
        )
        corners.append(
            (
                a,
                b,
                P(a.x - ux * handle, a.y - uy * handle),
                P(b.x - vx * handle, b.y - vy * handle),
            )
        )
    path = Path(corners[0][0])
    for a, b, c1, c2 in corners:
        path.line(a).cubic(b, c1, c2)
    return path.close()


def project(x, y, z, yaw, pitch):
    x1, z1 = x * cos(yaw) + z * sin(yaw), -x * sin(yaw) + z * cos(yaw)
    return P(x1, y * cos(pitch) + z1 * sin(pitch))


class CatScene:
    def __init__(self, options):
        self.options = options
        self.custom = custom_coat(options)
        self.siamese = options["coat"] == "siamese"
        self.pattern = options["coat"]
        self.colors = {k: color(v) for k, v in resolved_colors(options).items()}
        self.fur, self.point, self.other = (
            self.colors[k] for k in ("fur", "point", "secondary")
        )
        self.marks = options["white_markings"]
        r, g, b, _ = self.fur.getRgbF()
        self.line = (
            color(0.30, 0.27, 0.24, 0.70)
            if r * 0.3 + g * 0.6 + b * 0.1 > 0.45
            else color(0.82, 0.88, 0.85, 0.76)
        )
        self.eye = (
            self.colors["eyes"]
            if self.custom or "eyes" in options["colors"]
            else (
                color(0.4308411, 0.8214476, 0.9849748)
                if self.siamese
                else color(0.8247580, 0.9451730, 0.3138255)
            )
        )
        self.glow = (
            color(0.4406621, 0.8377618, 0.9929082, 0.85)
            if self.siamese
            else color(0.8073625, 0.9448115, 0.3024600, 0.85)
        )
        self.paw = (
            WHITE if self.marks["paws"] else self.point if self.siamese else self.fur
        )

    def fill(self, path, brush):
        self.p.fillPath(path, brush)

    def stroke(self, path, c, width=1):
        self.p.strokePath(
            path,
            QPen(
                c,
                width,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
                Qt.PenJoinStyle.RoundJoin,
            ),
        )

    def rotate(self, radians):
        self.p.rotate(radians * 180 / pi)

    def clip(self, path):
        self.p.setClipPath(path, Qt.ClipOperation.IntersectClip)

    def linear(self, path, start, end, stops):
        gradient = QLinearGradient(q(start), q(end))
        for pos, c in stops:
            gradient.setColorAt(pos, c)
        self.fill(path, gradient)

    def radial(self, x, y, rx, ry, stops, inner=0):
        self.p.save()
        self.p.translate(x, y)
        self.p.scale(rx, ry)
        gradient = QRadialGradient(QPointF(), 1)
        for pos, c in stops:
            gradient.setColorAt(inner + (1 - inner) * pos, c)
        self.p.fillRect(QRectF(-1, -1, 2, 2), gradient)
        self.p.restore()

    def spot(self, x, y, rx, ry, c, opacity=1):
        self.radial(
            x,
            y,
            rx,
            ry,
            [(0, alpha(c, opacity)), (0.5, alpha(c, opacity * 0.92)), (1, alpha(c, 0))],
        )

    def draw(self, motion):
        self.image = QImage(360, 320, QImage.Format.Format_RGBA8888_Premultiplied)
        self.image.fill(Qt.GlobalColor.transparent)
        self.p = QPainter(self.image)
        self.p.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.m = motion
        try:
            breath = sin(motion.time * 2.1) * 1.6
            sx, sy = 184 + motion.bodyShiftX.value, 226
            head = P(
                sx + motion.bodyTilt.value * 36 + motion.headYaw.value * 7.5,
                126
                + motion.headOffsetY.value
                + motion.headPitch.value * 4.8
                + breath * 1.1,
            )
            self.mouse()
            self.keyboard()
            self.tail(sx, sy)
            self.ears(head)
            self.body(sx, sy, head, breath)
            if motion.hindFootActive.value > 0.03:
                hip, target = P(sx + 26, sy + 2), motion.hindFoot.point
                self.limb(
                    hip,
                    P((hip.x + target.x) * 0.5 + 10, (hip.y + target.y) * 0.5 - 8),
                    target,
                    15,
                    12,
                    True,
                    0.85 * motion.hindFootActive.value,
                )
            self.face(head)
            self.arms(sx, sy, breath)
            self.badges()
            self.sparkles()
        finally:
            self.p.end()
        return self.image

    def mouse(self):
        m, p = self.m, self.p
        offset = m.mouseOffset.point
        p.save()
        p.translate(
            78 + offset.x,
            258 + offset.y + max(m.mousePressLeft.value, m.mousePressRight.value) * 1.6,
        )
        self.rotate(0.22)
        self.fill(ellipse(QRectF(-13.5, -9.5, 27, 31)), color(0, 0, 0, 0.24))
        palettes = {
            "cream": (
                color(0.9642647, 0.9596165, 0.9400094),
                color(0.1864975, 0.1873504, 0.2119722),
                color(0.9727128, 0.7388677, 0.2049820),
            ),
            "dark": (
                color(0.2602647, 0.2732611, 0.3068725),
                color(0.1037400, 0.1047577, 0.1326911),
                color(0.8160786, 0.9450366, 0.3138756),
            ),
            "retro": (
                color(0.9120638, 0.8943841, 0.8539354),
                color(0.2607966, 0.2484661, 0.2364834),
                color(0.9108421, 0.5029935, 0.3038720),
            ),
        }
        body, border, wheel = palettes[self.options["keyboard"]]
        if any(k in self.options["colors"] for k in ("case", "keys", "accent")):
            body, border, wheel = (self.colors[k] for k in ("keys", "case", "accent"))
        shape = ellipse(QRectF(-13.5, -16.5, 27, 33))
        self.fill(shape, body)
        for x, spring in ((0, m.mousePressLeft), (-14, m.mousePressRight)):
            if spring.value > 0.05:
                p.save()
                self.clip(shape)
                p.fillRect(
                    QRectF(x, 0, 14, 17),
                    color(0.8247580, 0.9451730, 0.3138255, clamp(0.38 * spring.value)),
                )
                p.restore()
        self.stroke(Path(P(0, 16)).line(P(0, 1.5)), alpha(border, 0.32), 1.05)
        self.fill(rounded(QRectF(-1.9, 2.5, 3.8, 8.5), 1.9), wheel)
        self.stroke(shape, border, 1.7)
        p.restore()

    def keyboard(self):
        tl, tr, bl, br = (
            quad_point(-0.025, -0.08),
            quad_point(1.025, -0.08),
            quad_point(-0.032, 1.08),
            quad_point(1.032, 1.08),
        )
        self.fill(
            rounded_quad(
                [
                    P(tl.x, tl.y + 8.5),
                    P(tr.x, tr.y + 8.5),
                    P(br.x, br.y + 9.5),
                    P(bl.x, bl.y + 9.5),
                ],
                6,
            ),
            color(0, 0, 0, 0.22),
        )
        palettes = {
            "cream": (
                color(0.1326481, 0.1335945, 0.1601791),
                color(0.1864975, 0.1873504, 0.2119722),
                color(0.9746352, 0.9708795, 0.9537037),
                color(0.8208149, 0.8115539, 0.7866380, 0.75),
                color(0.9806855, 0.7473747, 0.2048253),
            ),
            "dark": (
                color(0.0729458, 0.0740693, 0.1037829),
                color(0.1322812, 0.1472116, 0.1735059),
                color(0.2720273, 0.2848670, 0.3181184),
                color(0.1465486, 0.1474669, 0.1734863, 0.95),
                color(0.8076331, 0.9371312, 0.3139723),
            ),
            "retro": (
                color(0.3182494, 0.3062623, 0.2837996),
                color(0.4560723, 0.4347591, 0.4041998),
                color(0.9201880, 0.9023144, 0.8539070),
                color(0.7356076, 0.7078559, 0.6640268, 0.85),
                color(0.9108421, 0.5029935, 0.3038720),
            ),
        }
        base, deck, keycolor, border, accent = palettes[self.options["keyboard"]]
        if any(k in self.options["colors"] for k in ("case", "keys", "accent")):
            deck, keycolor, accent = (
                self.colors[k] for k in ("case", "keys", "accent")
            )
            base, border = blend(deck, color("#000000"), 0.25), alpha(deck, 0.65)
        self.fill(
            rounded_quad([P(v.x, v.y + 6.5) for v in (tl, tr, br, bl)], 5.5), base
        )
        self.fill(rounded_quad([tl, tr, br, bl], 5), deck)
        for key, row, x, width in KEYCAPS:
            glow = self.m.keyGlow.get(key, 0)
            u0, u1 = 1 - x - width + 0.0028, 1 - x - 0.0028
            v0, v1 = 1 - (row + 1) / 5 + 0.014, 1 - row / 5 - 0.014
            vertices = [
                quad_point(u, v) for u, v in ((u0, v0), (u1, v0), (u1, v1), (u0, v1))
            ]
            shape = rounded_quad([P(v.x, v.y + glow * 1.9) for v in vertices], 1.6)
            fill = accent if key in ("Esc", "Enter") else keycolor
            if glow > 0.02:
                fill = blend(fill, self.glow, glow * 0.55)
            self.fill(shape, fill)
            self.stroke(shape, border, 0.65)
        for key, glow in self.m.keyGlow.items():
            if glow > 0.05:
                center, radius = key_point(key), 17 + glow * 6
                self.radial(
                    center.x,
                    center.y,
                    radius,
                    radius,
                    [(0, alpha(self.glow, 0.36 * glow)), (1, alpha(self.glow, 0))],
                )

    def tail(self, sx, sy):
        phase, hunt = self.m.tailPhase, clamp(self.m.huntIntensity.value)
        wag1, wag2, drop = (
            sin(phase) * (8 + hunt * 5.5),
            cos(phase * 1.3) * (6 + hunt * 4.5),
            hunt * 14,
        )
        root, tip = P(sx + 34, sy - 6), P(
            sx + 91 + wag2 * 0.5, sy - 30 + wag1 * 0.85 + drop
        )
        path = Path(root).cubic(
            tip,
            P(sx + 64, sy + 2 + wag1 * 0.35 + drop * 0.4),
            P(sx + 66 + wag2 * 0.4, sy - 26 + wag1 * 0.7 + drop),
        )
        if not self.custom:
            self.stroke(path, POINT if self.siamese else BLACK, 11)
            return
        stroker = QPainterPathStroker()
        stroker.setWidth(11)
        stroker.setCapStyle(Qt.PenCapStyle.RoundCap)
        shape = stroker.createStroke(path)
        self.fill(shape, self.point if self.siamese else self.fur)
        self.p.save()
        self.clip(shape)
        if self.pattern in ("shaded", "tortie", "calico"):
            self.spot(
                tip.x - 10,
                tip.y + 3,
                24,
                22,
                self.other if self.pattern == "calico" else self.point,
            )
        elif self.pattern == "tabby":
            dx, dy = tip.x - root.x, tip.y - root.y
            self.p.translate(root.x, root.y)
            self.rotate(atan2(dy, dx))
            for t in (0.30, 0.57, 0.84):
                self.p.fillRect(
                    QRectF(hypot(dx, dy) * t, -25, 6, 50), alpha(self.point, 0.75)
                )
        self.p.restore()

    def ears(self, center):
        m, p = self.m, self.p
        p.save()
        p.translate(center.x, center.y)
        self.rotate(m.headTilt.value)
        yaw, pitch = m.headYaw.value * 0.5, m.headPitch.value * 0.36
        for sign in (-1, 1):
            angle = (
                sign * (0.06 + m.earFold.value * 0.34)
                - sign * m.earTwitch.value * 0.045
            )
            inner, outer = project(sign * 9, -16, 0, yaw, pitch), project(
                sign * 35, -5, -2, yaw, pitch
            )
            tip = project(
                sign * 24.5 + sin(angle) * 32, -20 - cos(angle) * 32, -3, yaw, pitch
            )
            a, b = P(tip.x - sign * 3.8, tip.y + 2.8), P(
                tip.x + sign * 3.8, tip.y + 3.2
            )
            path = Path(inner).quad(
                a, P((inner.x + a.x) * 0.5 - sign * 1.5, (inner.y + a.y) * 0.5 - 2)
            )
            path.quad(b, P(tip.x, tip.y - 2.2)).quad(
                outer, P((outer.x + b.x) * 0.5 + sign * 2.5, (outer.y + b.y) * 0.5 - 2)
            ).close()
            c = POINT if self.siamese else BLACK
            if self.custom:
                c = self.point if self.siamese else self.fur
                if self.pattern == "tortie":
                    c = self.point if sign < 0 else self.fur
                if self.pattern == "calico":
                    c = self.point if sign < 0 else self.other
                if self.pattern == "shaded":
                    c = blend(self.fur, self.point, 0.55)
            self.fill(path, c)
        p.restore()

    def body(self, sx, sy, head, breath):
        m, p = self.m, self.p
        ht, bt, squash = m.headTilt.value, m.bodyTilt.value, m.bodySquash.value
        wide = 1 + (1 - squash) * 0.55

        def H(x, y):
            return P(
                head.x + x * cos(ht) - y * sin(ht), head.y + x * sin(ht) + y * cos(ht)
            )

        def B(x, y):
            return P(
                sx + x * wide * cos(bt) - y * squash * sin(bt),
                sy + x * wide * sin(bt) + y * squash * cos(bt),
            )

        cheek, crown_drop = m.headYaw.value * 3, m.headPitch.value * 2
        lx, rx = -42.5 + cheek * 0.4, 42.5 + cheek * 0.4
        crown = H(cheek * 0.2, -30 + crown_drop)
        path = Path(crown).cubic(
            H(rx, 5), H(26 + cheek * 0.3, -30 + crown_drop), H(rx + 1.5, -14)
        )
        path.cubic(B(49, -14), H(rx - 2.5, 24), B(51.5, -48 + breath * 0.5))
        path.cubic(B(24, 12), B(47, 5), B(36, 12)).line(B(-24, 12))
        path.cubic(B(-49, -14), B(-36, 12), B(-47, 5))
        path.cubic(H(lx, 5), B(-51.5, -48 + breath * 0.5), H(lx + 2.5, 24))
        path.cubic(
            crown, H(lx - 1.5, -14), H(-26 + cheek * 0.3, -30 + crown_drop)
        ).close()
        if self.custom:
            self.coat_body(path, sx, sy, head)
        elif self.siamese:
            self.linear(
                path, P(sx, head.y - 34), P(sx, sy + 18), [(0.15, CREAM), (1, LATTE)]
            )
            p.save()
            self.clip(path)
            p.translate(head.x, head.y)
            self.rotate(ht)
            yaw, pitch = m.headYaw.value * 0.5, m.headPitch.value * 0.36
            center = project(0, 2.5, 27, yaw, pitch)
            p.translate(center.x, center.y)
            p.scale(
                max(0.76, cos(yaw * 0.7)) * 1.18, max(0.82, cos(pitch * 0.7)) * 0.88
            )
            self.radial(
                0,
                0,
                31,
                31,
                [
                    (0, POINT),
                    (0.44, alpha(POINT, 0.96)),
                    (0.74, alpha(MOCHA, 0.70)),
                    (1, alpha(MOCHA, 0)),
                ],
                inner=2 / 31,
            )
            p.restore()
        else:
            self.fill(path, BLACK)
        if self.custom or self.siamese:
            self.stroke(path, alpha(self.line, 0.45) if self.custom else OUTLINE, 1.5)
        p.save()
        p.translate(sx, sy)
        self.rotate(bt)
        p.scale(wide, squash)
        paw = self.paw if self.custom else POINT if self.siamese else BLACK
        for x in (-26.5, 26.5):
            if x > 0 and m.hindFootActive.value >= 0.35:
                continue
            self.fill(ellipse(QRectF(x - 8.5, 3, 17, 11)), paw)
            arc = Path()
            arc.arcMoveTo(QRectF(x - 7.5, 1, 15, 15), -0.25 * 180 / pi)
            arc.arcTo(
                QRectF(x - 7.5, 1, 15, 15), -0.25 * 180 / pi, -(pi - 0.5) * 180 / pi
            )
            self.stroke(
                arc, alpha(CREAM, 0.55) if self.siamese else alpha(MINT, 0.58), 1.3
            )
        p.restore()

    def texture(self, rect, head):
        texture = tabby_texture(self.colors["point"].name())
        source = QRectF(0, 0, 256, 115) if head else QRectF(0, 115, 256, 269)
        self.p.save()
        self.p.setOpacity(0.75)
        self.p.drawImage(rect, texture, source)
        self.p.restore()

    def coat_body(self, path, sx, sy, head):
        p, m = self.p, self.m
        self.fill(path, self.fur)
        p.save()
        self.clip(path)
        p.save()
        p.translate(sx, sy)
        self.rotate(m.bodyTilt.value)
        p.scale(1 + (1 - m.bodySquash.value) * 0.55, m.bodySquash.value)
        if self.pattern == "tabby":
            self.texture(QRectF(-53, -100, 106, 114), False)
        if self.pattern == "shaded":
            self.spot(-53, -66, 47, 105, self.point, 0.72)
            self.spot(53, -66, 47, 105, self.point, 0.72)
        if self.pattern == "tortie":
            for x, y, rx, ry, opacity in (
                (43, -58, 32, 34, 1),
                (37, -39, 28, 26, 0.85),
                (-43, -10, 32, 42, 1),
                (-25, 7, 15, 21, 0.72),
            ):
                self.spot(x, y, rx, ry, self.point, opacity)
        if self.pattern == "calico":
            self.spot(-40, -34, 35, 48, self.point)
            self.spot(35, -6, 32, 37, self.other)
        p.restore()
        p.save()
        p.translate(head.x, head.y)
        self.rotate(m.headTilt.value)
        p.translate(m.headYaw.value * 12, m.headPitch.value * 8)
        p.scale(max(0.75, cos(m.headYaw.value * 0.5)), 1)
        if self.pattern == "tabby":
            self.texture(QRectF(-42, -34, 84, 43), True)
        if self.pattern == "shaded":
            self.spot(0, -42, 56, 42, self.point, 0.8)
        if self.pattern == "siamese":
            self.spot(0, -12, 72, 67, self.point)
        if self.pattern == "tortie":
            self.spot(-35, -29, 27, 42, self.point)
            self.spot(-31, -8, 24, 19, self.point, 0.70)
        if self.pattern == "calico":
            self.spot(-32, -29, 35, 39, self.point)
            self.spot(33, -8, 28, 37, self.other)
        amount = self.marks["amount"]
        if self.marks["face"] != "none":
            width = (
                21 + amount * 13
                if self.marks["face"] == "inverted_v"
                else 8 + amount * 9
            )
            tip = P(0, -24 - amount * 5)
            blaze = Path(tip).cubic(P(-width, 24), P(-6, -22), P(-5, 10))
            blaze.quad(P(width, 24), P(0, 49)).cubic(tip, P(5, 10), P(6, -22)).close()
            self.fill(blaze, WHITE)
        p.restore()
        p.save()
        p.translate(sx, sy)
        self.rotate(m.bodyTilt.value)
        p.scale(1 + (1 - m.bodySquash.value) * 0.55, m.bodySquash.value)
        if self.marks["chest"]:
            w, bottom = 17 + amount * 15, -55 + self.marks["chest"] * 65
            bib = Path(P(-18, -91)).cubic(
                P(0, bottom), P(-w - 12, -56), P(-w, bottom - 24)
            )
            bib.cubic(P(18, -91), P(w, bottom - 24), P(w + 12, -56)).close()
            self.fill(bib, WHITE)
        p.restore()
        p.restore()

    def face(self, head):
        p, m = self.p, self.m
        p.save()
        p.translate(head.x, head.y)
        self.rotate(m.headTilt.value)
        yaw, pitch = m.headYaw.value * 0.5, m.headPitch.value * 0.36
        for sign in (-1, 1):
            self.eye_shape(sign, yaw, pitch)
        wiggle = sin(m.time * 4.5) * max(m.petHeadIntensity, m.petBodyIntensity) * 1.2
        path = Path()
        for sign in (-1, 1):
            for y, xend, yend in (
                (10.5, 36.5, 8.8 + wiggle),
                (14.2, 37.8, 14.2 + wiggle * 0.5),
                (18, 35.5, 19.6 - wiggle * 0.4),
            ):
                a, b = project(sign * 24, y, 23, yaw, pitch), project(
                    sign * xend, yend, 14, yaw, pitch
                )
                path.moveTo(q(a))
                path.quad(b, P((a.x + b.x) * 0.5, (a.y + b.y) * 0.5 - 0.8))
        self.stroke(
            path,
            self.line if self.custom else SIAMESE_WHISKER if self.siamese else WHISKER,
            1,
        )
        p.restore()

    def eye_shape(self, sign, yaw, pitch):
        p, m = self.p, self.m
        center = project(sign * 17.2, -2, 27.5, yaw, pitch)
        p.save()
        p.translate(center.x, center.y)
        p.scale(
            clamp(cos(yaw + sign * 0.34) / cos(0.34), 0.64, 1.06),
            clamp(cos(pitch * 0.85), 0.78, 1.03),
        )
        if m.isHappyClosedEyes:
            self.stroke(
                Path(P(-11.5, 1)).quad(P(11.5, 1), P(sign * 1.5, 3.4)), self.eye, 2.6
            )
        elif m.isBlissfulSquint:
            self.fill(
                Path(P(-11.5, -0.5))
                .quad(P(11.5, -0.5), P(0, 0.6))
                .quad(P(-11.5, -0.5), P(0, 4.8))
                .close(),
                self.eye,
            )
        else:
            hunt = clamp(m.huntIntensity.value)
            self.rotate(sign * 0.06 * (1 - hunt * 0.6))
            rx, ry = 12 + hunt * 1.1, 10.8 + hunt * 1.8
            eye = QRectF(-rx, -ry, rx * 2, ry * 2)
            closure = m.effectiveEyeClosure
            aperture = (
                QRectF(
                    -rx,
                    -ry + 2 * ry * closure,
                    rx * 2,
                    max(0.01, ry * 2 * (1 - closure)),
                )
                if self.custom
                else eye
            )
            self.clip(ellipse(aperture))
            p.fillRect(eye, self.eye)
            gaze = m.eyeGaze.point
            px, py = gaze.x * (4.2 - hunt * 1.2), gaze.y * (3.6 - hunt)
            nw, nh = 5 * m.pupilScale.value, 13.5 * min(1.12, m.pupilScale.value)
            pw, ph = nw + (18.8 - nw) * hunt, nh + (18.8 - nh) * hunt
            self.fill(ellipse(QRectF(px - pw * 0.5, py - ph * 0.5, pw, ph)), BLACK)
            if hunt > 0.25:
                r = 2.1 + hunt * 0.9
                self.fill(
                    ellipse(
                        QRectF(
                            px - pw * 0.22 - r * 0.5,
                            py - ph * 0.22 - r * 0.5,
                            r * 2,
                            r * 2,
                        )
                    ),
                    color(1, 1, 1, min(1, (hunt - 0.25) / 0.55) * 0.92),
                )
            if closure > 0.02 and not self.custom:
                p.fillRect(
                    QRectF(-rx - 2, -ry - 2, rx * 2 + 4, ry * 2.2 * closure),
                    POINT if self.siamese else BLACK,
                )
        p.restore()

    def arms(self, sx, sy, breath):
        m = self.m
        for left, spring, rest, typing in (
            (True, m.leftPaw, P(164, 235), m.leftPawTyping),
            (False, m.rightPaw, P(204, 235), m.rightPawTyping),
        ):
            end, sign = spring.point, -1 if left else 1
            mouse = left and m.leftPawOnMouse
            if hypot(end.x - rest.x, end.y - rest.y) < 6 and not typing and not mouse:
                self.idle_leg(
                    P(sx + sign * 18, sy - 30), P(sx + sign * 16, sy + 12), sign
                )
            else:
                start = P(sx + sign * 24, sy - 56 + breath)
                control = P(
                    (start.x + end.x) * 0.5 + sign * (8 if mouse else 4),
                    (start.y + end.y) * 0.5 - 6,
                )
                self.limb(start, control, end, 19, 13.5, not left, 0.78)

    def idle_leg(self, top, bottom, sign):
        path = rounded(
            QRectF(bottom.x - 7.5, top.y, 15, bottom.y - top.y + 1),
            6 if self.custom else 6.5,
        )
        if self.custom:
            if self.marks["paws"] or self.siamese:
                self.coat_limb(
                    path, QRectF(bottom.x - 7, bottom.y - 6, 14, 8), top, bottom
                )
        elif self.siamese:
            self.linear(
                path,
                top,
                P(bottom.x, bottom.y + 2),
                [(0.05, alpha(CREAM, 0)), (0.52, alpha(MOCHA, 0.75)), (0.85, POINT)],
            )
        line = (
            self.line if self.custom else alpha(OUTLINE, 0.62) if self.siamese else MINT
        )
        outer = Path(P(top.x + sign * 8.5, top.y)).quad(
            P(bottom.x + sign * 7.5, bottom.y - 1),
            P(top.x + sign * 9.5, (top.y + bottom.y) * 0.5),
        )
        inner = Path(P(top.x - sign * 7, top.y + 4)).quad(
            P(bottom.x - sign * 6, bottom.y - 1),
            P(top.x - sign * 6.5, (top.y + bottom.y) * 0.5),
        )
        self.stroke(outer, line, 1.45)
        self.stroke(inner, line, 1.45)

    def shoulder_color(self, point):
        device = self.p.transform().map(q(point))
        samples = []
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                x, y = round(device.x()) + dx, round(device.y()) + dy
                if 0 <= x < self.image.width() and 0 <= y < self.image.height():
                    c = self.image.pixelColor(x, y)
                    if c.alpha() > 240:
                        samples.append(c.getRgbF()[:3])
        return (
            QColor.fromRgbF(
                *(sum(values) / len(samples) for values in zip(*samples, strict=True))
            )
            if samples
            else self.fur
        )

    def coat_limb(self, path, paw, start, end):
        shoulder = self.shoulder_color(start)
        arm = blend(shoulder, self.fur, 0.20)
        tip = self.paw if self.marks["paws"] or self.siamese else arm
        fade = min(0.30, 18 / max(1, hypot(end.x - start.x, end.y - start.y)))
        edge = 0.92 - self.marks["paws"] * 0.52 if self.marks["paws"] else 0.62
        stops = [
            (0, alpha(shoulder, 0)),
            (fade * 0.45, alpha(shoulder, 0.35)),
            (fade, shoulder),
            (max(fade + 0.01, edge - 0.18), arm),
            (min(1, edge + 0.14), tip),
            (1, tip),
        ]
        # Paint separately: opposite path windings must never subtract the paw overlap.
        self.linear(path, start, end, stops)
        self.linear(ellipse(paw), start, end, stops)

    def limb(self, start, control, end, start_width, end_width, outline_left, opacity):
        left, right = [], []
        for i in range(15):
            t, mt = i / 14, 1 - i / 14
            x, y = (
                mt * mt * start.x + 2 * mt * t * control.x + t * t * end.x,
                mt * mt * start.y + 2 * mt * t * control.y + t * t * end.y,
            )
            tx, ty = 2 * mt * (control.x - start.x) + 2 * t * (
                end.x - control.x
            ), 2 * mt * (control.y - start.y) + 2 * t * (end.y - control.y)
            length = max(0.001, hypot(tx, ty))
            nx, ny = -ty / length, tx / length
            width = (start_width + (end_width - start_width) * t) * 0.5
            left.append(P(x + nx * width, y + ny * width))
            right.append(P(x - nx * width, y - ny * width))
        path = polyline(left + list(reversed(right))).close()
        radius = end_width * 0.58
        paw = QRectF(end.x - radius, end.y - radius * 0.85, radius * 2, radius * 1.7)
        if self.custom:
            self.coat_limb(path, paw, start, end)
            for edge in (left, right):
                for i in range(1, len(edge) - 1):
                    fade = clamp((i / 14 - 0.16) / 0.22)
                    self.stroke(
                        Path(edge[i - 1]).line(edge[i]),
                        alpha(self.line, opacity * 0.68 * fade),
                        1.05,
                    )
        elif self.siamese:
            self.linear(
                path,
                start,
                end,
                [(0, alpha(CREAM, 0)), (0.16, CREAM), (0.48, MOCHA), (0.78, POINT)],
            )
            self.fill(ellipse(paw), POINT)
            edge = right if outline_left else left
            self.stroke(polyline(edge[3:-1]), alpha(OUTLINE, 0.72), 1.25)
        else:
            self.fill(path, BLACK)
            self.fill(ellipse(paw), BLACK)
        if not self.custom:
            edge = left if outline_left else right
            c = (
                alpha(OUTLINE, opacity * 0.78)
                if self.siamese
                else alpha(MINT, opacity * 0.9)
            )
            self.stroke(polyline(edge[2 : int((len(edge) - 1) * 0.68) + 1]), c, 1.35)

    def badges(self):
        from petnest.ui.cat_labels import draw_label

        p = self.p
        for badge in self.m.floatingKeycaps:
            progress, age = badge.age / badge.lifetime, badge.age
            scale = (
                0.72 + 0.38 * sin(age / 0.09 * pi * 0.65)
                if age < 0.09
                else 1.1 - 0.1 * (age - 0.09) / 0.09 if age < 0.18 else 1
            )
            opacity = 1 if progress < 0.62 else max(0, 1 - (progress - 0.62) / 0.38)
            label = badge.label
            width = 23 if len(label) <= 1 else 30 if len(label) == 2 else 38
            p.save()
            p.setOpacity(opacity)
            p.translate(badge.position.x, badge.position.y)
            self.rotate(badge.rotation)
            p.scale(scale, scale)
            self.fill(
                rounded(QRectF(-width / 2, -8.5, width, 22), 5.5),
                color(0.1993200, 0.2001556, 0.2243867, 0.95),
            )
            face = rounded(QRectF(-width / 2, -11, width, 22), 5.2)
            self.fill(face, color(0.9801961, 0.9772977, 0.9617315))
            self.stroke(face, color(0.2119305, 0.2127502, 0.2366200), 1.45)
            draw_label(
                p,
                label,
                QRectF(-width / 2 + 3, -8, width - 6, 15),
                color(0.1601364, 0.1610302, 0.1865397),
            )
            p.restore()

    def sparkles(self):
        from petnest.ui.cat_labels import draw_label

        p = self.p
        for sparkle in self.m.sparkles:
            progress = sparkle.age / sparkle.lifetime
            p.save()
            p.setOpacity(sin(min(1, progress) * pi) * 0.85)
            p.translate(sparkle.position.x, sparkle.position.y)
            if sparkle.sleeping:
                draw_label(
                    p, "Z", QRectF(0, 0, 8 + progress * 2, 11 + progress * 3), self.eye
                )
            else:
                r = 3.5 + progress * 1.5
                star = (
                    Path(P(0, -r))
                    .quad(P(r, 0), P(0.8, -0.8))
                    .quad(P(0, r), P(0.8, 0.8))
                )
                star.quad(P(-r, 0), P(-0.8, 0.8)).quad(P(0, -r), P(-0.8, -0.8)).close()
                self.fill(star, self.eye)
            p.restore()
