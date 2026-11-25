"""Shared KuroCat motion model; no OS clock, native library or global input state.

Ported from KuroCat v1.2.1 (MIT), see native/kurocat/NOTICE. Coordinates are
360 x 320, top-down on every platform. Each pet owns its clock and random stream.
"""

from dataclasses import dataclass, field
from math import hypot, sin, pi
from random import Random


def clamp(value, low=0.0, high=1.0):
    return max(low, min(high, value))


@dataclass
class Point:
    x: float = 0.0
    y: float = 0.0


@dataclass
class Spring:
    value: float = 0.0
    velocity: float = 0.0
    target: float = field(init=False)

    def __post_init__(self):
        self.target = self.value

    def step(self, dt, stiffness=260, damping=22):
        self.velocity += (
            (self.target - self.value) * stiffness - self.velocity * damping
        ) * dt
        self.value += self.velocity * dt


class SpringPoint:
    def __init__(self, x=0, y=0):
        self.x, self.y = Spring(x), Spring(y)

    @property
    def point(self):
        return Point(self.x.value, self.y.value)

    def aim(self, point):
        self.x.target, self.y.target = point.x, point.y

    def step(self, dt, stiffness=340, damping=25):
        self.x.step(dt, stiffness, damping)
        self.y.step(dt, stiffness, damping)


# The original 65% keyboard faces the cat, with Space nearest its paws.
ROWS = (
    [("Esc", 1)]
    + [(str(i), 1) for i in (1, 2, 3, 4, 5, 6, 7, 8, 9, 0)]
    + [("-", 1), ("=", 1), ("Back", 2)],
    [("Tab", 1.5)] + [(k, 1) for k in "QWERTYUIOP[]"] + [("\\", 1.5)],
    [("Caps", 1.75)] + [(k, 1) for k in "ASDFGHJKL;'"] + [("Enter", 2.25)],
    [("ShiftL", 2.25)] + [(k, 1) for k in "ZXCVBNM,./"] + [("ShiftR", 1.75), ("Up", 1)],
    [
        ("CtrlL", 1.25),
        ("AltL", 1.25),
        ("MetaL", 1.25),
        ("Space", 6.25),
        ("MetaR", 1),
        ("AltR", 1),
        ("Left", 1),
        ("Down", 1),
        ("Right", 1),
    ],
)
KEYCAPS = []
for row_number, row in enumerate(ROWS):
    x_units = 0
    for key_name, units in row:
        KEYCAPS.append((key_name, row_number, x_units / 15, units / 15))
        x_units += units


def quad_point(u, v):
    return Point(109 + 172 * u + (-6 + 11 * u) * v, 238 + 9 * u + (44 + u) * v)


KEY_POINTS = {
    k: quad_point(1 - x - w / 2, 1 - (row + 0.5) / 5) for k, row, x, w in KEYCAPS
}
ALIASES = {
    "`": "Esc",
    "Delete": "Back",
    "CtrlR": "Fn",
    **{f"F{i}": k for i, k in enumerate("1234567890-=", 1)},
    **{f"Num{i}": str(i) for i in range(10)},
    "NumEnter": "Enter",
    "Num+": "=",
    "Num-": "-",
    "Num/": "/",
    "Num.": ".",
    "Num=": "=",
    "Num*": "8",
    "NumLock": "Esc",
    "Home": "Left",
    "End": "Right",
    "PageUp": "Up",
    "PageDown": "Down",
    "Insert": "Back",
    "Print": "Esc",
    "Scroll": "Esc",
    "Pause": "Esc",
}
RIGHT_PAW_KEYS = set("123456QWERTASDFGZXCVB") | {
    "Esc",
    "Tab",
    "Caps",
    "ShiftL",
    "CtrlL",
    "AltL",
    "MetaL",
    "Space",
}


def visual_key(key):
    return ALIASES.get(key, key)


def key_point(key):
    return KEY_POINTS.get(visual_key(key), quad_point(0.5, 0.5))


def left_paw(key):
    return visual_key(key) not in RIGHT_PAW_KEYS


@dataclass
class Particle:
    position: Point
    velocity: Point
    label: str = ""
    rotation: float = 0.0
    age: float = 0.0
    lifetime: float = 1.25
    sleeping: bool = False


class CatMotion:
    """The same springs, key targeting and 2.5D head model on both systems."""

    def __init__(self, seed=0):
        self.random = Random(seed)
        self.leftPaw, self.rightPaw = SpringPoint(164, 235), SpringPoint(204, 235)
        self.hindFoot = SpringPoint(214, 234)
        self.eyeGaze, self.mouseOffset = SpringPoint(), SpringPoint()
        for name in (
            "hindFootActive",
            "bodyShiftX",
            "bodyTilt",
            "headTilt",
            "headYaw",
            "headPitch",
            "headOffsetY",
            "earFold",
            "earTwitch",
            "huntIntensity",
            "mousePressLeft",
            "mousePressRight",
        ):
            setattr(self, name, Spring())
        self.bodySquash, self.pupilScale = Spring(1), Spring(1)
        self.leftPawOnMouse = self.leftPawTyping = self.rightPawTyping = False
        self.keyGlow, self.keys = {}, []
        self.floatingKeycaps, self.sparkles = [], []
        self.time = self.tailPhase = self.sleepiness = 0.0
        self.petHeadIntensity = self.petBodyIntensity = self.lastPetTime = 0.0
        self.lastMove = self.lastClick = self.lastKey = 0.0
        self.lastBadgeTime = 0.0
        self.badgeCascadeIndex = 0
        self.petSparkleCooldown = self.sleepZCooldown = 0.0
        self.nextBlinkTime, self.blinkProgress, self.blinkTimer = 3.2, 0.0, 0.0
        self.isBlinking = False
        self.recentLeftKey = self.recentRightKey = None
        self.lastTypedPoint = self.previousCursor = None
        self.leftMouse = self.rightMouse = False

    @property
    def effectiveEyeClosure(self):
        return min(
            1,
            max(
                self.blinkProgress,
                self.petHeadIntensity,
                self.petBodyIntensity * 0.62,
                self.sleepiness * 0.92,
            ),
        )

    @property
    def isHappyClosedEyes(self):
        return self.petHeadIntensity > 0.45

    @property
    def isBlissfulSquint(self):
        return self.petBodyIntensity > 0.35 and not self.isHappyClosedEyes

    def key_event(self, key, down):
        if key == "reset":
            self.__init__()
            return
        if key in ("MouseLeft", "MouseRight"):
            if key == "MouseLeft":
                self.leftMouse = down
                self.mousePressLeft.target = float(down)
            else:
                self.rightMouse = down
                self.mousePressRight.target = float(down)
            self.lastClick, self.sleepiness = self.time, 0
            if down:
                self.leftPaw.y.velocity += 130 if key == "MouseLeft" else 110
                self.pupilScale.target = 1.12
                self.earTwitch.velocity -= 2.2
            return
        if not down:
            if key in self.keys:
                self.keys.remove(key)
            return
        if key not in self.keys:
            self.keys.append(key)
        vk, pt = visual_key(key), key_point(key)
        self.keyGlow[vk] = 1.0
        self.lastTypedPoint, self.lastKey = pt, self.time
        if left_paw(key):
            self.recentLeftKey = (key, self.time)
            self.leftPaw.y.velocity -= 180
        else:
            self.recentRightKey = (key, self.time)
            self.rightPaw.y.velocity -= 180
        self.bodySquash.velocity -= 1.3
        self.earTwitch.velocity += -3.8 if left_paw(key) else 3.8
        self.headTilt.velocity += -1.4 if left_paw(key) else 1.4
        self.pupilScale.target, self.sleepiness = 1.16, 0
        self.badgeCascadeIndex = (
            (self.badgeCascadeIndex + 1) % 6
            if self.time - self.lastBadgeTime < 0.38
            else 0
        )
        self.lastBadgeTime = self.time
        dx = [-10, 14, -22, 26, 2, 36][self.badgeCascadeIndex] + self.random.uniform(
            -3, 3
        )
        self.floatingKeycaps.append(
            Particle(
                Point(
                    clamp(pt.x + dx * 0.45, 55, 315),
                    pt.y - 26 - (self.badgeCascadeIndex % 2) * 8,
                ),
                Point(dx * 0.65, -36 - self.random.uniform(0, 14)),
                key,
                self.random.uniform(-0.07, 0.07),
            )
        )
        self.floatingKeycaps = self.floatingKeycaps[-16:]

    def pet(self, point, distance, head):
        self.lastPetTime, self.sleepiness = self.time, 0
        energy = min(distance / 26, 0.35)
        if head:
            self.petHeadIntensity = min(1, self.petHeadIntensity + energy + 0.08)
            self.petBodyIntensity = max(
                self.petBodyIntensity, self.petHeadIntensity * 0.6
            )
        else:
            self.petBodyIntensity = min(1, self.petBodyIntensity + energy + 0.07)
        self.headTilt.target = clamp((point.x - 184) / 60 * 0.16, -0.18, 0.18)
        self.headOffsetY.velocity += 18

    def step(self, dt, cursor, *, look=True, petting=True, idle=0):
        dt = clamp(dt, 0.001, 0.04)
        # The original bridge samples cursor motion before advancing the springs.
        point = cursor or Point(184, 124)
        old = self.previousCursor or point
        dx, dy = point.x - old.x, point.y - old.y
        self.previousCursor = point
        distance = hypot(dx, dy)
        if distance > 0.1:
            self.lastMove = self.time
            cx = 184 + self.bodyShiftX.value
            head = Point(
                cx + self.bodyTilt.value * 42,
                124 + self.headOffsetY.value + sin(self.time * 2.1) * 1.6,
            )
            on_head = ((point.x - head.x) / 48) ** 2 + (
                (point.y - head.y) / 42
            ) ** 2 <= 1
            on_body = ((point.x - cx) / 58) ** 2 + ((point.y - 196) / 56) ** 2 <= 1
            on_keyboard = 58 <= point.x <= 294 and 232 <= point.y <= 296
            if petting and (on_head or on_body or on_keyboard):
                self.pet(point, distance, on_head)
        self.time += dt
        now = self.time
        vx, vy = (dx / dt, dy / dt) if look and cursor is not None else (0, 0)
        last_move = self.lastMove if look and cursor is not None else -100
        if not petting:
            self.petHeadIntensity = self.petBodyIntensity = 0
        elif now - self.lastPetTime > 0.28:
            self.petHeadIntensity = max(0, self.petHeadIntensity - dt * 1.4)
            self.petBodyIntensity = max(0, self.petBodyIntensity - dt * 1.2)
        elif max(self.petHeadIntensity, self.petBodyIntensity) > 0.55:
            self.petSparkleCooldown -= dt
            if self.petSparkleCooldown <= 0:
                self.petSparkleCooldown = 0.42
                self.sparkles.append(
                    Particle(
                        Point(
                            184 + self.random.uniform(-44, 44),
                            88 + self.random.uniform(-14, 18),
                        ),
                        Point(self.random.uniform(-10, 10), -24),
                        lifetime=0.9,
                    )
                )
        if not self.keys and idle > 45:
            self.sleepiness += (min(1, (idle - 45) / 35) - self.sleepiness) * dt * 1.5
            if self.sleepiness > 0.8:
                self.sleepZCooldown -= dt
                if self.sleepZCooldown <= 0:
                    self.sleepZCooldown = 2.6
                    self.sparkles.append(
                        Particle(
                            Point(226, 100), Point(12, -18), lifetime=0.9, sleeping=True
                        )
                    )
        else:
            self.sleepiness = max(0, self.sleepiness - dt * 5)
        speed = hypot(vx, vy)
        if speed > 460 and max(self.petHeadIntensity, self.petBodyIntensity) < 0.25:
            self.huntIntensity.target = min(
                1,
                self.huntIntensity.target
                + (0.45 + min(1, (speed - 460) / 1100) * 1.15) * dt,
            )
            self.sleepiness = 0
        else:
            self.huntIntensity.target = max(0, self.huntIntensity.target - dt * 0.65)
        self.huntIntensity.step(dt, 85, 16)
        hunt = clamp(self.huntIntensity.value)
        mouse_recent = now - last_move < 2.2 or self.leftMouse or self.rightMouse
        mouse_active = now - last_move < 0.75 or self.leftMouse or self.rightMouse
        left = [k for k in self.keys if left_paw(k)]
        right = [k for k in self.keys if not left_paw(k)]
        lk, rk = (left[-1] if left else None), (right[-1] if right else None)
        if lk is None and len(right) >= 2 and not mouse_active:
            ordered = sorted(right, key=lambda k: key_point(k).x)
            lk, rk = ordered[0], ordered[-1]
        elif rk is None and len(left) >= 2:
            ordered = sorted(left, key=lambda k: key_point(k).x)
            lk, rk = ordered[0], ordered[-1]
        fk = None
        if len(self.keys) >= 3:
            fk = next((k for k in self.keys if k not in (lk, rk)), None)
        elif mouse_active and lk is None and len(right) >= 2:
            fk = next((k for k in right if k != rk), None)
        for side, recent in (
            ("left", self.recentLeftKey),
            ("right", self.recentRightKey),
        ):
            if recent and now - recent[1] < 0.14:
                if side == "left" and lk is None:
                    lk = recent[0]
                if side == "right" and rk is None:
                    rk = recent[0]
        self.mouseOffset.aim(
            Point(clamp(vx * 0.0045, -5.5, 5.5), clamp(vy * 0.0045, -4.5, 4.5))
        )
        self.mouseOffset.step(dt, 120, 16)
        self.mousePressLeft.step(dt, 400, 24)
        self.mousePressRight.step(dt, 400, 24)
        self.leftPawTyping, self.rightPawTyping = lk is not None, rk is not None
        self.leftPawOnMouse = lk is None and mouse_recent and self.sleepiness < 0.3
        mouse = self.mouseOffset.point
        self.leftPaw.aim(
            key_point(lk)
            if lk
            else (
                Point(80 + mouse.x, 255 + mouse.y)
                if self.leftPawOnMouse
                else Point(164, 235)
            )
        )
        self.rightPaw.aim(key_point(rk) if rk else Point(204, 235))
        self.hindFoot.aim(key_point(fk) if fk else Point(214, 234))
        self.hindFootActive.target = float(fk is not None)
        self.leftPaw.step(dt, 360, 24)
        self.rightPaw.step(dt, 360, 24)
        self.hindFoot.step(dt, 320, 22)
        self.hindFootActive.step(dt)
        shift = tilt = 0
        if self.leftPawOnMouse:
            shift = -3 if self.rightPawTyping else -10
            tilt = (
                (self.rightPaw.point.x - 196) * 0.0008
                if self.rightPawTyping
                else -0.075
            )
        elif self.leftPawTyping or self.rightPawTyping:
            average = (
                (self.leftPaw.point.x if self.leftPawTyping else 184)
                + (self.rightPaw.point.x if self.rightPawTyping else 184)
            ) * 0.5
            shift, tilt = (average - 184) * 0.14, (average - 184) * 0.0011
        self.bodyShiftX.target, self.bodyTilt.target = clamp(shift, -16, 16), clamp(
            tilt, -0.12, 0.12
        )
        self.bodySquash.target = 1 - hunt * 0.11
        self.headOffsetY.target = (
            3.5
            if self.leftPawTyping or self.rightPawTyping
            else self.sleepiness * 5 + hunt * 10.5
        )
        self.earFold.target = (
            max(self.petHeadIntensity * 0.7, self.petBodyIntensity * 0.45)
            + self.sleepiness * 0.25
            - hunt * 0.18
        )
        self.earTwitch.target = 0
        for name, stiffness, damping in (
            ("bodyShiftX", 140, 18),
            ("bodyTilt", 140, 18),
            ("bodySquash", 280, 18),
            ("headOffsetY", 180, 19),
            ("earFold", 120, 16),
            ("earTwitch", 320, 16),
        ):
            getattr(self, name).step(dt, stiffness, damping)
        origin = Point(184 + self.bodyShiftX.value, 124 + self.headOffsetY.value)
        aim = point if look and cursor is not None else Point(184, 124)
        nx, ny = (aim.x - origin.x) / 290, (aim.y - origin.y) / 260
        magnitude = hypot(nx, ny)
        if magnitude > 1:
            nx, ny = nx / magnitude, ny / magnitude
        typing = bool(self.keys) or now - self.lastKey < 0.65
        moving = now - last_move < 1.2
        if typing and self.lastTypedPoint is not None:
            kx = clamp((self.lastTypedPoint.x - origin.x) / 95, -0.85, 0.85)
            if moving:
                nx, ny = nx * 0.72 + kx * 0.28, ny * 0.72 + 0.25
            else:
                nx, ny = kx, clamp((self.lastTypedPoint.y - origin.y) / 125, -0.3, 0.92)
        self.headYaw.target = 0 if self.sleepiness > 0.45 else clamp(nx, -1, 1)
        self.headPitch.target = (
            0.45 * self.sleepiness if self.sleepiness > 0.45 else clamp(ny, -1, 1)
        )
        self.headYaw.step(dt, 88 + hunt * 75, 14.5 + hunt * 4.5)
        self.headPitch.step(dt, 88 + hunt * 75, 14.5 + hunt * 4.5)
        if now - self.lastPetTime > 0.28:
            self.headTilt.target = (
                self.bodyTilt.target * 0.45
                + self.headYaw.value * (0.11 + hunt * 0.05)
                - self.headYaw.value * self.headPitch.value * 0.04
            )
        self.headTilt.step(dt, 130, 16)
        self.eyeGaze.aim(Point(nx * 0.88, ny * 0.85))
        self.eyeGaze.step(dt, 210 + hunt * 80, 21)
        if self.hindFootActive.value > 0.3:
            self.pupilScale.target = 1.24
        elif now - self.lastKey > 0.45 and now - self.lastClick > 0.45:
            self.pupilScale.target = 1
        self.pupilScale.step(dt, 150, 18)
        if self.isBlinking:
            self.blinkTimer += dt
            if self.blinkTimer >= 0.14:
                self.isBlinking, self.blinkProgress = False, 0
                self.nextBlinkTime = now + self.random.uniform(2.6, 5.6)
            else:
                self.blinkProgress = sin(self.blinkTimer / 0.14 * pi)
        elif (
            now >= self.nextBlinkTime
            and self.sleepiness < 0.5
            and self.petHeadIntensity < 0.3
            and hunt < 0.35
        ):
            self.isBlinking, self.blinkTimer = True, 0
        self.tailPhase += dt * (
            1.85
            + max(self.petHeadIntensity, self.petBodyIntensity) * 1.4
            + hunt * 2.8
            - self.sleepiness * 1.1
        )
        active = {visual_key(k) for k in self.keys}
        self.keyGlow = {
            k: (1 if k in active else v - dt * 4.5)
            for k, v in self.keyGlow.items()
            if k in active or v - dt * 4.5 > 0.01
        }
        self.keyGlow.update({k: 1 for k in active})
        for particles in (self.floatingKeycaps, self.sparkles):
            for particle in particles:
                particle.age += dt
                particle.position.x += particle.velocity.x * dt
                particle.position.y += particle.velocity.y * dt
                if particles is self.floatingKeycaps:
                    particle.velocity.x *= 1 - dt * 2.4
                    particle.velocity.y *= 1 - dt * 1.6
            particles[:] = [p for p in particles if p.age < p.lifetime]
