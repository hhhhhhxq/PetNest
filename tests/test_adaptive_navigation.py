"""Cross-platform geometry tests for adaptive sidebar navigation."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QMargins
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QListWidgetItem, QStyle

from petnest.ui.adaptive_navigation import (
    AdaptiveNavigationList,
    bounded_navigation_sidebar_width,
)


def _navigation() -> AdaptiveNavigationList:
    return AdaptiveNavigationList(
        minimum_row_height=40,
        vertical_padding=9,
        horizontal_padding=11,
        item_margin=2,
        outer_padding=QMargins(0, 6, 0, 6),
    )


def _assert_rows_do_not_overlap(navigation: AdaptiveNavigationList) -> None:
    rects = [
        navigation.visualItemRect(navigation.item(row))
        for row in range(navigation.count())
    ]
    assert all(rect.isValid() and rect.height() > 0 for rect in rects)
    assert all(first.bottom() < second.top() for first, second in zip(rects, rects[1:]))


def test_navigation_metrics_cover_text_icons_and_outer_padding(qtbot) -> None:
    navigation = _navigation()
    qtbot.addWidget(navigation)
    navigation.addItem("导入宠物")
    icon = navigation.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon)
    navigation.addItem(QListWidgetItem(icon, "宠物商店"))
    navigation.show()
    navigation.reflow()

    _assert_rows_do_not_overlap(navigation)
    assert navigation.sizeHintForRow(0) >= 40
    assert navigation.sizeHintForRow(1) >= 40
    assert navigation.full_content_height() >= sum(
        navigation.sizeHintForRow(row) for row in range(navigation.count())
    ) + 12
    assert navigation.recommended_content_width() >= navigation.fontMetrics().horizontalAdvance(
        "宠物商店"
    )


def test_navigation_reflows_after_runtime_font_change_without_changing_selection(qtbot) -> None:
    navigation = _navigation()
    qtbot.addWidget(navigation)
    navigation.addItems(["导入宠物", "宠物商店", "导入动作"])
    navigation.setCurrentRow(1)
    navigation.show()
    navigation.reflow()
    original_height = navigation.sizeHintForRow(0)

    font = QFont(navigation.font())
    font.setPointSize(max(24, font.pointSize() + 10))
    navigation.setFont(font)

    qtbot.waitUntil(lambda: navigation.sizeHintForRow(0) > original_height)
    _assert_rows_do_not_overlap(navigation)
    assert navigation.currentRow() == 1


def test_navigation_scrolls_instead_of_compressing_large_rows(qtbot) -> None:
    navigation = _navigation()
    qtbot.addWidget(navigation)
    navigation.addItems(["导入宠物", "宠物商店", "导入动作", "编辑动作", "导出动作"])
    font = QFont(navigation.font())
    font.setPointSize(24)
    navigation.setFont(font)
    navigation.setFixedHeight(100)
    navigation.show()

    qtbot.waitUntil(lambda: navigation.verticalScrollBar().maximum() > 0)
    row_heights = [navigation.sizeHintForRow(row) for row in range(navigation.count())]
    assert len(set(row_heights)) == 1
    assert row_heights[0] >= navigation.fontMetrics().height() + 22


def test_empty_navigation_has_safe_metrics(qtbot) -> None:
    navigation = _navigation()
    qtbot.addWidget(navigation)
    navigation.reflow()

    assert navigation.full_content_height() >= 12
    assert navigation.recommended_content_width() >= 0


def test_sidebar_width_grows_to_content_but_reserves_two_thirds_for_main_content() -> None:
    assert bounded_navigation_sidebar_width(
        base_width=145,
        available_width=1220,
        navigation_width=200,
        surrounding_width=22,
    ) == 222
    assert bounded_navigation_sidebar_width(
        base_width=145,
        available_width=1220,
        navigation_width=600,
        surrounding_width=22,
    ) == 406
