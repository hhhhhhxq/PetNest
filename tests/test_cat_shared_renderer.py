"""Approved artwork, input parity and motion regressions for both OS runners."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter

from petnest.core.cat_appearance import COATS
from petnest.core.cat_motion import CatMotion, Point, Spring, key_point
from petnest.core.keyboard_cat import CatState, cat_preferences
from petnest.ui.cat_scene import CatScene, Path as ScenePath
from petnest.ui.keyboard_cat_renderer import render_cat

FIXTURES = Path(__file__).parent / "fixtures/keyboard_cat"
APPROVED = json.loads((FIXTURES / "approved.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("filename", APPROVED)
def test_matches_approved_mac_artwork(qapp, filename):
    """Fixed native reference prevents 'unifying' by regressing both to the old cat."""
    old = QImage(str(FIXTURES / filename))
    new = render_cat(CatState(), APPROVED[filename], dt=0)
    union = intersection = error = 0
    for y in range(320):
        for x in range(360):
            a, b = old.pixelColor(x, y), new.pixelColor(x, y)
            if a.alpha() > 127 or b.alpha() > 127:
                union += 1
                intersection += int(a.alpha() > 127 and b.alpha() > 127)
                error += (
                    sum(abs(v - w) for v, w in zip(a.getRgb(), b.getRgb(), strict=True))
                    / 4
                )
    assert intersection / union > 0.997
    # Small CoreGraphics vs Qt edge/gradient rasterization differences are expected.
    assert error / union < 1.8


@pytest.mark.parametrize("coat", COATS)
def test_mouse_paw_has_no_hole_and_shoulder_inherits_body(qapp, coat):
    scene = CatScene(cat_preferences({"coat": coat, "colors": {"fur": "#B89265"}}))
    scene.image = QImage(100, 100, QImage.Format.Format_RGBA8888_Premultiplied)
    scene.image.fill(Qt.GlobalColor.transparent)
    scene.p = QPainter(scene.image)
    scene.p.fillRect(QRectF(40, 10, 20, 20), QColor("#785F4B"))
    assert scene.shoulder_color(Point(50, 15)).name() == "#785f4b"
    assert scene.shoulder_color(Point(-50, -50)) == scene.fur
    corners = [Point(40, 10), Point(60, 10), Point(60, 80), Point(40, 80)]
    try:
        for points in (corners, list(reversed(corners))):
            path = ScenePath(points[0])
            for point in points[1:]:
                path.line(point)
            path.close()
            scene.coat_limb(path, QRectF(38, 70, 24, 20), Point(50, 10), Point(50, 80))
            assert all(
                scene.image.pixelColor(x, y).alpha() == 255
                for y in range(73, 86)
                for x in range(46, 55)
            )
            assert scene.image.pixelColor(0, 0).alpha() == 0
    finally:
        scene.p.end()


def test_shared_springs_keep_upstream_equations():
    spring = Spring(10)
    spring.target = 20
    spring.step(0.02, 260, 22)
    assert spring.velocity == pytest.approx(52)
    assert spring.value == pytest.approx(11.04)


def test_multi_key_and_mouse_assign_the_third_key_to_a_foot():
    m = CatMotion()
    for key in ("A", "S", "D", "MouseLeft"):
        m.key_event(key, True)
    for _ in range(30):
        m.step(1 / 30, Point(500, 100), petting=False)
    assert m.leftPawOnMouse
    assert m.rightPawTyping
    assert m.hindFootActive.value > 0.9
    assert m.leftMouse
    assert m.mousePressLeft.value > 0.9
    assert m.rightPaw.x.target == key_point("D").x
    m.key_event("reset", False)
    assert not m.keys and not m.leftMouse and not m.floatingKeycaps


def test_petting_sleep_and_fast_mouse_motion_are_not_static_effects():
    m = CatMotion()
    for i in range(15):
        m.step(1 / 30, Point(180 + (i % 2) * 8, 124))
    assert m.isHappyClosedEyes and m.sparkles
    for _ in range(200):
        m.step(1 / 30, None, idle=90)
    assert m.sleepiness > 0.9
    assert any(p.sleeping for p in m.sparkles)
    for i in range(40):
        m.step(1 / 30, Point(-300 if i % 2 else 600, 90), petting=False)
    assert m.huntIntensity.value > 0.8 and m.sleepiness == 0
    m.key_event("A", True)
    assert m.floatingKeycaps and m.sleepiness == 0


@pytest.mark.parametrize(
    "platform,native,qt_key,expected",
    [
        ("darwin", 0, Qt.Key.Key_A, "A"),
        ("win32", 65, Qt.Key.Key_A, "A"),
        ("darwin", 60, Qt.Key.Key_Shift, "ShiftR"),
        ("win32", 161, Qt.Key.Key_Shift, "ShiftR"),
        ("win32", 0, Qt.Key.Key_A, "A"),
        ("win32", 0, Qt.Key.Key_Return, "Enter"),
        ("win32", 0, Qt.Key.Key_Control, "CtrlL"),
    ],
)
def test_local_input_uses_same_names_as_global_input(
    monkeypatch, platform, native, qt_key, expected
):
    from petnest.ui import keyboard_preview_input as local

    monkeypatch.setattr(local, "sys", SimpleNamespace(platform=platform))
    event = SimpleNamespace(nativeVirtualKey=lambda: native, key=lambda: qt_key)
    assert local.preview_key(event) == expected


def test_windows_and_mac_physical_codes_produce_identical_animation(qapp):
    from petnest.platforms.physical_keys import MAC_KEYS, WINDOWS_KEYS

    a, b = CatState(), CatState()
    mac_codes, win_codes = [0, 1, 56], [65, 83, 160]
    for down in (True, False):
        for ac, bc in zip(mac_codes, win_codes, strict=True):
            a.key_event(MAC_KEYS[ac], down)
            b.key_event(WINDOWS_KEYS[bc], down)
        for i in range(30):
            cursor = QPointF(400 - i * 3, 100)
            assert render_cat(a, {"sleep_enabled": False}, cursor=cursor) == render_cat(
                b, {"sleep_enabled": False}, cursor=cursor
            )


def test_bounded_event_queue_reconciles_after_long_pause(qapp):
    state = CatState()
    for _ in range(300):
        state.key_event("A", True)
        state.key_event("A", False)
    state.key_event("S", True)
    render_cat(state, {})
    assert state.motion.keys == ["S"]


def test_badge_font_does_not_depend_on_system_fonts(qapp):
    from petnest.ui.cat_labels import label_font, label_path

    font = label_font()
    assert font.familyName() == "Noto Sans"
    for name in ("A", "S", "CtrlL", "MetaR", "Num1", "Enter", "ShiftR", "F12"):
        assert not label_path(name).isEmpty()
