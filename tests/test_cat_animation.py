"""Shared production animation regressions, exercised on macOS and Windows."""

from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest

from petnest.core.keyboard_cat import CatState
from petnest.ui.keyboard_cat_renderer import render_cat


def badge_pixels(image):
    # Original A key badge rises just above the right side of the reversed keyboard.
    return sum(
        image.pixelColor(x, y).alpha() > 200
        and min(image.pixelColor(x, y).getRgb()[:3]) > 200
        for x in range(232, 276)
        for y in range(208, 239)
    )


def test_short_tap_between_frames_keeps_badge_then_expires(qapp):
    state = CatState()
    assert badge_pixels(render_cat(state, {})) == 0
    state.key_event("A", True)
    state.key_event("A", False)
    assert not state.keys
    assert badge_pixels(render_cat(state, {})) > 40
    for _ in range(45):
        final = render_cat(state, {})
    assert badge_pixels(final) == 0


def test_reset_removes_floating_keys_and_other_context_is_independent(qapp):
    state = CatState()
    state.key_event("A", True)
    assert badge_pixels(render_cat(state, {})) > 40
    assert badge_pixels(render_cat(CatState(), {"coat": "siamese"})) == 0
    state.reset()
    assert badge_pixels(render_cat(state, {})) == 0


def test_cursor_turns_head_and_movement_drives_mouse_without_key_permission(qapp):
    left, right, neutral = CatState(), CatState(), CatState()
    for _ in range(30):
        a = render_cat(left, {}, cursor=QPointF(-500, 120))
        b = render_cat(right, {}, cursor=QPointF(800, 120))
        c = render_cat(neutral, {"look": False}, cursor=QPointF(800, 120))
    assert a.copy(135, 95, 100, 70) != b.copy(135, 95, 100, 70)
    assert b.copy(135, 95, 100, 70) != c.copy(135, 95, 100, 70)
    moving = render_cat(right, {}, cursor=QPointF(-500, 120))
    assert moving.copy(55, 230, 50, 65) != b.copy(55, 230, 50, 65)


def test_preview_accepts_local_keys_without_global_permission(qtbot):
    from pathlib import Path

    from petnest.core.package_loader import PackageLoader
    from petnest.ui.my_pets_page import MyPetsPage

    package = PackageLoader().load(
        Path(__file__).resolve().parents[1] / "pets/keyboard_cat"
    )
    page = MyPetsPage([package], package.identifier, input_status=lambda: "需要授权")
    qtbot.addWidget(page)
    page.show()
    page.preview_timer.stop()
    QTest.keyClick(page.pet_list, Qt.Key.Key_A)
    assert not page._preview_state.keys
    assert badge_pixels(render_cat(page._preview_state, {})) > 40
    page.hide()
    assert badge_pixels(render_cat(page._preview_state, {})) == 0
