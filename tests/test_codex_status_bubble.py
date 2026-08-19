"""Codex 状态气泡的持续、未读与屏幕边界行为。"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt

from petnest.core.codex_link import CodexLinkSnapshot
from petnest.ui.codex_status_bubble import CodexStatusBubble


def test_running_and_idle_do_not_show_a_bubble(qtbot) -> None:
    bubble = CodexStatusBubble(review_duration_ms=30)
    qtbot.addWidget(bubble)

    bubble.show_snapshot(CodexLinkSnapshot("running", 1, 0, "Codex 正在运行"), QRect(100, 100, 80, 80))
    assert not bubble.isVisible()

    bubble.show_snapshot(CodexLinkSnapshot("idle"), QRect(100, 100, 80, 80))
    assert not bubble.isVisible()


def test_waiting_and_failed_stay_visible_without_a_dismiss_timer(qtbot) -> None:
    bubble = CodexStatusBubble(review_duration_ms=30)
    qtbot.addWidget(bubble)

    bubble.show_snapshot(
        CodexLinkSnapshot("waiting", 2, 0, "2 个 Codex 任务等待你处理"),
        QRect(100, 100, 80, 80),
    )
    assert bubble.isVisible()
    assert "2 个" in bubble.text()
    assert not bubble.dismiss_timer.isActive()

    bubble.show_snapshot(
        CodexLinkSnapshot("failed", 1, 0, "Codex 执行遇到问题"),
        QRect(100, 100, 80, 80),
    )
    assert bubble.isVisible()
    assert "遇到问题" in bubble.text()
    assert not bubble.dismiss_timer.isActive()


def test_review_collapses_to_unread_badge_then_click_marks_it_read(qtbot) -> None:
    bubble = CodexStatusBubble(review_duration_ms=30)
    qtbot.addWidget(bubble)
    activated: list[bool] = []
    bubble.activated.connect(lambda: activated.append(True))

    bubble.show_snapshot(
        CodexLinkSnapshot("review", 1, 1, "Codex 任务已停止，等待查看"),
        QRect(100, 100, 80, 80),
    )
    assert bubble.dismiss_timer.isActive()
    qtbot.waitUntil(lambda: bubble.is_compact, timeout=500)
    assert bubble.isVisible()
    assert "待查看" in bubble.text()

    qtbot.mouseClick(bubble, Qt.MouseButton.LeftButton, pos=QPoint(4, 4))
    assert activated == [True]
    assert not bubble.isVisible()


def test_bubble_geometry_is_clamped_to_available_screen(qtbot) -> None:
    bubble = CodexStatusBubble(review_duration_ms=30)
    qtbot.addWidget(bubble)
    available = bubble.screen().availableGeometry()
    anchor = QRect(available.right() - 4, available.bottom() - 4, 4, 4)

    bubble.show_snapshot(
        CodexLinkSnapshot("waiting", 1, 0, "Codex 正在等待你处理"),
        anchor,
    )

    assert available.contains(bubble.frameGeometry())
