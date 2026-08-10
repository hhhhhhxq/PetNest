"""鼠标跟随模式的纯逻辑测试。"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize

from petnest.core.mouse_follow import MouseFollowController


def test_motion_stays_active_briefly_after_cursor_stops() -> None:
    controller = MouseFollowController(stationary_ms=150)

    assert controller.sample(QPoint(10, 10), now_ms=0) is False
    assert controller.sample(QPoint(20, 10), now_ms=20) is True
    assert controller.sample(QPoint(20, 10), now_ms=169) is True
    assert controller.sample(QPoint(20, 10), now_ms=170) is False


def test_target_flips_near_right_bottom_edge_and_stays_inside_screen() -> None:
    controller = MouseFollowController(offset=18)
    screen = QRect(1920, 0, 1920, 1040)
    target = controller.target_position(QPoint(3820, 1000), QSize(154, 190), screen)

    assert target.x() < 3820
    assert target.y() < 1000
    assert screen.contains(QRect(target, QSize(154, 190)))


def test_direction_uses_primary_axis_and_keeps_horizontal_facing_on_vertical_motion() -> None:
    controller = MouseFollowController()

    controller.sample(QPoint(10, 10), now_ms=0)
    controller.sample(QPoint(2, 10), now_ms=20)
    assert (controller.direction, controller.facing_left) == ("left", True)

    controller.sample(QPoint(2, 30), now_ms=40)
    assert (controller.direction, controller.facing_left) == ("down", True)


def test_target_position_keeps_gap_after_cursor_visible_bounds() -> None:
    controller = MouseFollowController(offset=8)

    target = controller.target_position(
        QPoint(100, 200), QSize(80, 80), QRect(0, 0, 800, 600), visible_bounds=(2, 1, 32, 31)
    )

    assert target == QPoint(140, 239)


def test_default_follow_gap_is_two_pixels_after_visible_cursor_bounds() -> None:
    controller = MouseFollowController()

    target = controller.target_position(
        QPoint(100, 200), QSize(80, 80), QRect(0, 0, 800, 600), visible_bounds=(0, 0, 31, 31)
    )

    assert target == QPoint(133, 233)
