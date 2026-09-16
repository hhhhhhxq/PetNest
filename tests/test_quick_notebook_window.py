from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest

from PySide6.QtCore import QMargins, QPoint, QRect, QSize, Qt
from PySide6.QtGui import QColor, QInputMethodEvent, QPalette
from PySide6.QtWidgets import QHBoxLayout, QSizePolicy, QStyle, QStyleOptionButton, QToolButton, QWidget

from petnest.core.quick_notebook_store import ReminderItem, QuickNotebookStore, TodoItem
from petnest.ui.quick_notebook_window import (
    QuickNotebookWindow,
    TodoCheckBox,
    paper_depths,
    place_notebook,
)


def save_visual_states(window: QuickNotebookWindow, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    for page_type in ("note", "todo", "reminder"):
        window.select_type(page_type)
        window.show()
        window.repaint()
        window.grab().save(str(output / f"notebook-{page_type}.png"))
    window.open_directory()
    window.repaint()
    window.grab().save(str(output / "notebook-directory.png"))


def test_place_notebook_prefers_right_then_flips_left() -> None:
    available = QRect(0, 0, 800, 600)

    right = place_notebook(QRect(100, 200, 80, 80), QSize(478, 448), available)
    left = place_notebook(QRect(700, 200, 80, 80), QSize(478, 448), available)

    assert right.x() == 189
    assert left.x() == 213
    assert available.contains(QRect(right, QSize(478, 448)))
    assert available.contains(QRect(left, QSize(478, 448)))


@pytest.mark.parametrize(
    ("active_type", "expected"),
    [
        ("note", {"note": 0, "todo": 1, "reminder": 2}),
        ("todo", {"todo": 0, "note": 1, "reminder": 2}),
        ("reminder", {"reminder": 0, "note": 1, "todo": 2}),
    ],
)
def test_paper_depths_put_active_type_in_front(active_type, expected) -> None:
    assert paper_depths(active_type) == expected


def test_layered_papers_and_tabs_match_v7_geometry(qtbot, tmp_path) -> None:
    window = QuickNotebookWindow(store=QuickNotebookStore(tmp_path / "book.json"))
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)

    body = window.body_frame.geometry()
    assert window.paper_layers["note"].geometry().topLeft() == body.topLeft()
    assert window.paper_layers["todo"].geometry().topLeft() == body.topLeft() + QPoint(3, 3)
    assert window.paper_layers["reminder"].geometry().topLeft() == body.topLeft() + QPoint(6, 6)
    for tab in window.type_tabs:
        page_type = tab.property("pageType")
        layer = window.paper_layers[page_type]
        assert tab.geometry().right() == layer.geometry().left() + 7
        expected_width = 87 if page_type == "note" else 80
        assert tab.size() == QSize(expected_width, 45)


def test_active_tab_protrudes_beyond_dimmed_tabs(qtbot, tmp_path) -> None:
    window = QuickNotebookWindow(store=QuickNotebookStore(tmp_path / "book.json"))
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)

    note_tab, todo_tab, reminder_tab = window.type_tabs
    assert note_tab.width() == todo_tab.width() + 7
    assert note_tab.width() == reminder_tab.width() + 7
    assert note_tab.geometry().left() <= min(
        todo_tab.geometry().left(), reminder_tab.geometry().left()
    ) - 7
    assert [tab._depth for tab in window.type_tabs] == [0, 1, 2]


def test_active_tab_keeps_seven_pixel_advantage_on_very_narrow_screen(qtbot, tmp_path) -> None:
    window = QuickNotebookWindow(store=QuickNotebookStore(tmp_path / "book.json"))
    qtbot.addWidget(window)
    window.fit_to_available_geometry(QRect(0, 0, 320, 520))
    window.show()
    qtbot.waitExposed(window)

    active = window.type_tabs[0]
    inactive = window.type_tabs[1:]
    assert all(active.width() == tab.width() + 7 for tab in inactive)
    assert all(tab.geometry().left() >= 0 for tab in window.type_tabs)


def test_translucent_paper_layers_do_not_use_per_layer_graphics_effects(qtbot, tmp_path) -> None:
    window = QuickNotebookWindow(store=QuickNotebookStore(tmp_path / "book.json"))
    qtbot.addWidget(window)

    assert all(layer.graphicsEffect() is None for layer in window.paper_layers.values())


def test_page_stack_clears_the_previous_page_before_painting(qtbot, tmp_path) -> None:
    window = QuickNotebookWindow(store=QuickNotebookStore(tmp_path / "book.json"))
    qtbot.addWidget(window)

    assert window.page_stack.autoFillBackground()
    assert window.page_stack.palette().color(QPalette.ColorRole.Window) == QColor("#FFFDFA")


def test_switching_type_does_not_rebuild_inactive_list_editors(qtbot, tmp_path) -> None:
    store = QuickNotebookStore(tmp_path / "book.json")
    store.create_page("note")
    store.create_page("todo")
    store.create_page("reminder")
    window = QuickNotebookWindow(store=store)
    qtbot.addWidget(window)

    window.select_type("todo")
    window.todo_editor.set_items((TodoItem("todo-1", "保留待办控件"),))
    window.flush_current_page()
    todo_row = window.todo_editor._rows[0]

    window.select_type("reminder")

    assert window.todo_editor._rows == [todo_row]


def test_returning_to_unchanged_list_page_reuses_existing_rows(qtbot, tmp_path) -> None:
    store = QuickNotebookStore(tmp_path / "book.json")
    store.create_page("note")
    store.create_page("todo")
    window = QuickNotebookWindow(store=store)
    qtbot.addWidget(window)

    window.select_type("todo")
    window.todo_editor.add_item("无需重建的待办")
    window.flush_current_page()
    todo_row = window.todo_editor._rows[0]

    window.select_type("note")
    window.select_type("todo")

    assert window.todo_editor._rows == [todo_row]


def test_switching_between_equal_todo_pages_resets_page_local_undo(qtbot, tmp_path) -> None:
    store = QuickNotebookStore(tmp_path / "book.json")
    first = store.create_page("todo")
    second = store.create_page("todo")
    window = QuickNotebookWindow(store=store)
    qtbot.addWidget(window)

    window.show_page(first.id)
    window.todo_editor.add_item("只属于第一页")
    window.flush_current_page()
    window.todo_editor._rows[0].remove_button.click()
    assert not window.todo_editor.removal_history.isHidden()

    window.show_page(second.id)

    assert window.todo_editor.removal_history.isHidden()
    window.todo_editor.removal_history.undo_button.click()
    assert window.todo_editor.items() == ()


def test_window_matches_final_shell(qtbot, tmp_path) -> None:
    window = QuickNotebookWindow(store=QuickNotebookStore(tmp_path / "quick-notebook.json"))
    qtbot.addWidget(window)

    assert window.objectName() == "quickNotebookWindow"
    assert window.body_frame.width() <= 390
    assert [button.property("pageType") for button in window.type_tabs] == [
        "note",
        "todo",
        "reminder",
    ]
    assert window.type_tabs[0].width() == 87
    assert window.type_tabs[1].width() == 80
    assert window.type_tabs[2].width() == 80
    assert [tab.text() for tab in window.type_tabs] == ["速记", "待办", "提醒"]
    assert window.type_tabs[0].accessibleName() == "速记"
    assert window.type_tabs[0].toolTip().startswith("速记：")
    assert window.findChild(QWidget, "notebookAppHeader") is None
    assert window.findChild(QWidget, "notebookSearch") is None
    assert window.findChild(QWidget, "notebookPinButton") is None
    assert window.delete_button.accessibleName() == "删除当前便签"
    assert window.previous_button.accessibleName() == "上一页"
    assert window.next_button.accessibleName() == "下一页"
    assert [button.property("iconKind") for button in window.type_tabs] == [
        "note",
        "todo",
        "reminder",
    ]
    assert window.directory_button.property("iconName") == "menu"


def test_window_flags_allow_editing_without_regular_window_chrome(qtbot, tmp_path) -> None:
    window = QuickNotebookWindow(store=QuickNotebookStore(tmp_path / "quick-notebook.json"))
    qtbot.addWidget(window)
    flags = window.windowFlags()

    assert flags & Qt.WindowType.Tool
    assert flags & Qt.WindowType.FramelessWindowHint
    assert flags & Qt.WindowType.WindowStaysOnTopHint
    assert not flags & Qt.WindowType.WindowDoesNotAcceptFocus
    assert window.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)


def test_v7_header_and_note_body_use_one_continuous_paper(qtbot, tmp_path) -> None:
    window = QuickNotebookWindow(store=QuickNotebookStore(tmp_path / "book.json"))
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)

    assert window.title_editor.parent() is window.content_frame
    assert window.title_editor.geometry().top() == window.delete_button.geometry().top()
    assert window.title_editor.geometry().top() == window.close_button.geometry().top()
    assert window.title_label.isHidden()
    assert window.body_label.isHidden()
    assert window.tag_label.isHidden()
    assert window.page_hint.isHidden()
    assert window.note_editor.placeholderText() == ""
    assert window.note_empty_hint.text().startswith("开始写点什么吧")
    assert isinstance(window.footer.layout(), QHBoxLayout)
    assert window.new_button.size() == QSize(35, 35)
    assert window.new_button.text() == "+"


def test_note_body_does_not_stack_an_extra_ten_pixel_margin(qtbot, tmp_path) -> None:
    window = QuickNotebookWindow(store=QuickNotebookStore(tmp_path / "book.json"))
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)

    assert window.note_page.layout().contentsMargins() == QMargins(0, 0, 0, 0)
    title_left = window.title_editor.mapTo(window.content_frame, QPoint()).x()
    body_left = window.note_editor.mapTo(window.content_frame, QPoint()).x()
    assert abs(body_left - title_left) <= 6


def test_footer_outlines_both_bottom_corners(qtbot, tmp_path) -> None:
    window = QuickNotebookWindow(store=QuickNotebookStore(tmp_path / "book.json"))
    qtbot.addWidget(window)
    footer_css = window.styleSheet().split("QFrame#quickNotebookFooter {", 1)[1].split("}", 1)[0]

    assert window.body_frame.layout().contentsMargins() == QMargins(1, 1, 1, 1)
    assert "border-left: 1px solid #DECFC4" not in footer_css
    assert "border-right: 1px solid #DECFC4" not in footer_css
    assert "border-bottom: 1px solid #DECFC4" not in footer_css


def test_category_controls_float_inside_note_body(qtbot, tmp_path) -> None:
    window = QuickNotebookWindow(store=QuickNotebookStore(tmp_path / "book.json"))
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)

    assert window.category_floating.parent() is window.body_frame
    assert window.category_toggle is window.category_floating
    assert window.note_page.layout().indexOf(window.category_floating) == -1
    assert window.body_frame.rect().contains(window.category_floating.geometry())
    assert window.category_floating.width() < window.note_editor.viewport().width() - 16
    assert window.note_editor.document().rootFrame().frameFormat().bottomMargin() >= 44


def test_floating_category_control_is_one_adaptive_click_target(qtbot, tmp_path) -> None:
    window = QuickNotebookWindow(store=QuickNotebookStore(tmp_path / "book.json"))
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)

    assert isinstance(window.category_floating, QToolButton)
    assert window.category_toggle is window.category_floating
    assert window.category_empty_label.text() == "选择分类"
    assert window.category_empty_label.isVisible()
    assert window.category_icon_label.pixmap() is not None
    assert not window.category_icon_label.pixmap().isNull()
    assert window.category_floating.width() < window.note_editor.viewport().width() - 16
    assert window.category_floating.toolTip() == "点击选择分类"
    assert window.category_floating.geometry().right() == window.body_frame.rect().right()
    floating_top_left = window.note_editor.viewport().mapFromGlobal(
        window.category_floating.mapToGlobal(QPoint())
    )
    bottom_gap = window.note_editor.viewport().height() - (
        floating_top_left.y() + window.category_floating.height()
    )
    assert bottom_gap <= 3

    qtbot.mouseClick(
        window.category_floating,
        Qt.MouseButton.LeftButton,
        pos=window.category_floating.rect().center(),
    )
    assert window.category_panel.isVisible()

    window._set_categories(("工作", "待发送", "灵感"))
    qtbot.wait(20)
    assert window.category_empty_label.isHidden()
    assert window.category_floating.toolTip() == "点击管理分类"
    assert window.category_floating.width() < window.note_editor.viewport().width() - 16
    assert window.category_floating.width() <= 225
    assert window.category_floating.geometry().right() == window.body_frame.rect().right()


def test_floating_category_summary_does_not_clip_tag_text(qtbot, tmp_path) -> None:
    window = QuickNotebookWindow(store=QuickNotebookStore(tmp_path / "book.json"))
    qtbot.addWidget(window)
    window._set_categories(("项目", "灵感"))
    window.show()
    qtbot.waitExposed(window)
    window._layout_note_overlays()

    labels = [
        window.category_summary_layout.itemAt(index).widget()
        for index in range(window.category_summary_layout.count())
        if window.category_summary_layout.itemAt(index).widget().objectName()
        == "quickNotebookCategorySummaryTag"
    ]
    assert [label.text() for label in labels] == ["项目", "灵感"]
    assert all(label.width() >= label.sizeHint().width() for label in labels)


def test_last_note_line_scrolls_above_floating_categories(qtbot, tmp_path) -> None:
    window = QuickNotebookWindow(store=QuickNotebookStore(tmp_path / "book.json"))
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    window.note_editor.setPlainText("\n".join(f"第 {index} 行" for index in range(40)))
    cursor = window.note_editor.textCursor()
    cursor.movePosition(cursor.MoveOperation.End)
    window.note_editor.setTextCursor(cursor)
    window.note_editor.verticalScrollBar().setValue(
        window.note_editor.verticalScrollBar().maximum()
    )

    assert window.note_editor.cursorRect().bottom() < window.category_floating.geometry().top()


def test_note_safe_margin_does_not_create_a_fake_undo_command(qtbot, tmp_path) -> None:
    window = QuickNotebookWindow(store=QuickNotebookStore(tmp_path / "book.json"))
    qtbot.addWidget(window)
    window.show()
    window.note_editor.setPlainText("原始正文")

    assert not window.note_editor.document().isUndoAvailable()
    cursor = window.note_editor.textCursor()
    cursor.movePosition(cursor.MoveOperation.End)
    cursor.insertText("新增")
    assert window.note_editor.document().isUndoAvailable()
    window.note_editor.undo()

    assert window.note_editor.toPlainText() == "原始正文"
    assert window.note_editor.document().rootFrame().frameFormat().bottomMargin() >= 44


def test_category_panel_scrolls_when_vertical_space_is_tight(qtbot, tmp_path) -> None:
    store = QuickNotebookStore(tmp_path / "book.json")
    for index in range(8):
        page = store.create_page("note")
        store.update_page(replace(page, tags=(f"候选{index}",)))
    target = store.create_page("note")
    store.update_page(replace(target, tags=("项目", "工作", "生活", "资料", "重要")))
    window = QuickNotebookWindow(store=store)
    qtbot.addWidget(window)
    window.show_page(target.id)
    window.fit_to_available_geometry(QRect(0, 0, 320, 260))
    window.show()
    window.category_toggle.click()
    qtbot.wait(20)

    assert window.note_editor.viewport().rect().contains(window.category_panel.geometry())
    assert window.category_scroll.verticalScrollBar().maximum() > 0
    assert window._edge_scroll_source is window.category_scroll
    assert window.note_edge_scrollbar.isVisible()
    assert window.note_edge_scrollbar.geometry().right() == window.body_frame.rect().right()
    assert (
        window.category_new_editor.height()
        >= window.category_new_editor.minimumSizeHint().height()
    )
    assert window.category_panel_close_button.isVisible()


def test_floating_summary_shows_two_elided_tags_and_overflow_count(qtbot, tmp_path) -> None:
    window = QuickNotebookWindow(store=QuickNotebookStore(tmp_path / "book.json"))
    qtbot.addWidget(window)
    names = ("非常非常长的项目分类", "灵感", "待发送", "工作", "资料")
    window._set_categories(names)
    window.show()
    qtbot.waitExposed(window)

    widgets = [
        window.category_summary_layout.itemAt(index).widget()
        for index in range(window.category_summary_layout.count())
    ]
    tag_widgets = [
        widget
        for widget in widgets
        if widget.objectName() == "quickNotebookCategorySummaryTag"
    ]
    overflow = next(
        widget
        for widget in widgets
        if widget.objectName() == "quickNotebookCategorySummaryMore"
    )
    assert tag_widgets[0].toolTip() == names[0]
    assert tag_widgets[0].maximumWidth() <= 72
    assert tag_widgets[1].text() == "灵感"
    assert overflow.text() == "+3"


def test_category_panel_elides_long_tags_without_squeezing_add_controls(qtbot, tmp_path) -> None:
    store = QuickNotebookStore(tmp_path / "book.json")
    source = store.create_page("note")
    long_name = "这是一个非常非常长的候选分类名称"
    store.update_page(replace(source, tags=(long_name,)))
    target = store.create_page("note")
    window = QuickNotebookWindow(store=store)
    qtbot.addWidget(window)
    window.show_page(target.id)
    window.show()
    window.category_toggle.click()
    qtbot.wait(20)

    button = window.category_choice_buttons[long_name]
    assert button.maximumWidth() <= 120
    assert button.toolTip() == long_name
    assert window.category_choices_layout.hasHeightForWidth()
    assert window.category_new_editor.minimumWidth() == 0
    assert window.category_input_area.parent() is window.category_panel
    assert window.category_new_editor.parent() is window.category_input_area
    assert window.category_input_area.geometry().bottom() <= window.category_panel.rect().bottom()


def test_category_panel_reflows_immediately_after_adding_tags(qtbot, tmp_path) -> None:
    window = QuickNotebookWindow(store=QuickNotebookStore(tmp_path / "book.json"))
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    window.category_toggle.click()
    qtbot.wait(20)

    for name in ("工作", "灵感", "这是较长的分类", "资料"):
        window.category_new_editor.setText(name)
        qtbot.keyClick(window.category_new_editor, Qt.Key.Key_Return)
        qtbot.wait(20)

        buttons = list(window.category_selected_buttons.values())
        assert all(button.height() >= button.sizeHint().height() for button in buttons)
        assert all(
            first.geometry().bottom() < second.geometry().top()
            or second.geometry().bottom() < first.geometry().top()
            or first.geometry().right() < second.geometry().left()
            or second.geometry().right() < first.geometry().left()
            for index, first in enumerate(buttons)
            for second in buttons[index + 1 :]
        )
        assert window.category_new_editor.height() >= window.category_new_editor.minimumSizeHint().height()
        assert window.category_input_area.geometry().bottom() <= window.category_panel.rect().bottom()


def test_category_panel_uses_available_width_without_unneeded_scrollbar(qtbot, tmp_path) -> None:
    store = QuickNotebookStore(tmp_path / "book.json")
    recent = store.create_page("note")
    store.update_page(replace(recent, tags=("工作", "待发送", "md")))
    current = store.create_page("note")
    store.update_page(replace(current, tags=("哈哈", "嘿嘿嘿嘿", "嘿嘿")))
    window = QuickNotebookWindow(store=store)
    qtbot.addWidget(window)
    window.show_page(current.id)
    window.show()
    qtbot.waitExposed(window)
    window.category_toggle.click()
    qtbot.wait(20)

    selected = list(window.category_selected_buttons.values())
    recent_buttons = list(window.category_choice_buttons.values())
    assert window.category_scroll.verticalScrollBar().maximum() == 0, (
        window.category_scroll.viewport().height(),
        window.category_panel_content.height(),
        window.category_panel.height(),
    )
    assert len({button.y() for button in selected}) == 1
    assert len({button.y() for button in recent_buttons}) == 1


def test_category_tags_flow_independently_between_rows(qtbot, tmp_path) -> None:
    store = QuickNotebookStore(tmp_path / "book.json")
    current = store.create_page("note")
    store.update_page(
        replace(
            current,
            tags=("第一条非常长的分类", "第二条非常长的分类", "甲", "乙", "丙"),
        )
    )
    window = QuickNotebookWindow(store=store)
    qtbot.addWidget(window)
    window.show_page(current.id)
    window.show()
    qtbot.waitExposed(window)
    window.category_toggle.click()
    qtbot.wait(20)

    rows: dict[int, list[QWidget]] = {}
    for button in window.category_selected_buttons.values():
        rows.setdefault(button.y(), []).append(button)
    assert len(rows) >= 2
    second_row = sorted(rows[sorted(rows)[1]], key=lambda button: button.x())
    assert len(second_row) >= 2
    assert second_row[1].x() == (
        second_row[0].geometry().right()
        + 1
        + window.category_selected_layout.horizontalSpacing()
    )


def test_foreground_outline_covers_complete_active_paper(qtbot, tmp_path) -> None:
    window = QuickNotebookWindow(store=QuickNotebookStore(tmp_path / "book.json"))
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)

    assert window.paper_outline.geometry() == window.body_frame.geometry()
    assert window.paper_outline.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    assert window.paper_outline.property("drawsCompleteRoundedBorder") is True


def test_v7_shell_uses_vector_close_and_navigation_icons(qtbot, tmp_path) -> None:
    window = QuickNotebookWindow(store=QuickNotebookStore(tmp_path / "book.json"))
    qtbot.addWidget(window)

    assert window.close_button.property("iconName") == "x"
    assert window.previous_button.property("iconName") == "chevron-left"
    assert window.next_button.property("iconName") == "chevron-right"
    assert not window.close_button.icon().isNull()
    assert not window.previous_button.icon().isNull()
    assert not window.next_button.icon().isNull()


def test_empty_note_hint_is_visual_only_and_hides_after_input(qtbot, tmp_path) -> None:
    store = QuickNotebookStore(tmp_path / "book.json")
    window = QuickNotebookWindow(store=store)
    qtbot.addWidget(window)
    window.show()

    assert window.title_editor.placeholderText() == "无标题速记"
    assert window.note_editor.placeholderText() == ""
    assert window.note_empty_hint.isVisible()
    assert "第一行会自动成为标题" in window.note_empty_hint.text()
    window.note_editor.setPlainText("新的灵感")
    assert window.note_empty_hint.isHidden()
    assert window.note_editor.toPlainText() == "新的灵感"


def test_success_toast_is_transient_and_error_toast_persists(qtbot, tmp_path) -> None:
    window = QuickNotebookWindow(store=QuickNotebookStore(tmp_path / "book.json"))
    qtbot.addWidget(window)
    window.show()

    assert window.save_toast.testAttribute(Qt.WidgetAttribute.WA_StyledBackground)
    assert "background-color: #F1E8E0" in window.save_toast.styleSheet()
    window._set_save_status("已保存到本机")
    assert window.save_toast.isVisible()
    assert window.save_toast.graphicsEffect() is not None
    assert window.save_toast.parent() is window.body_frame
    assert window.save_toast.geometry().right() == window.category_floating.geometry().right()
    assert (
        window.category_floating.geometry().top()
        - window.save_toast.geometry().bottom()
        - 1
    ) == 6
    assert window.save_status_timer.interval() == 2000
    window.save_status_timer.timeout.emit()
    assert window.save_toast.isHidden()

    window.category_toggle.click()
    qtbot.wait(20)
    window._set_save_status("已保存到本机")
    panel_top_left = window.body_frame.mapFromGlobal(
        window.category_panel.mapToGlobal(QPoint())
    )
    panel_right = panel_top_left.x() + window.category_panel.width() - 1
    assert window.save_toast.geometry().right() == panel_right
    assert panel_top_left.y() - window.save_toast.geometry().bottom() - 1 == 6
    window.category_toggle.click()

    window._set_save_status("保存失败", error=True)
    assert window.save_toast.isVisible()
    assert window.retry_button.isVisible()
    assert not window.save_status_timer.isActive()
    assert window.save_toast.property("error") is True


def test_empty_category_summary_does_not_paint_a_blank_chip(qtbot, tmp_path) -> None:
    window = QuickNotebookWindow(store=QuickNotebookStore(tmp_path / "book.json"))
    qtbot.addWidget(window)
    window.show()

    assert window.current_categories() == ()
    assert window.category_summary.isHidden()


def test_category_panel_suggests_recent_live_tags_and_toggles_selection(qtbot, tmp_path) -> None:
    store = QuickNotebookStore(tmp_path / "book.json")
    recent = store.create_page("note")
    store.update_page(replace(recent, tags=("工作", "灵感")))
    store._pages[recent.id] = replace(store.page(recent.id), updated_at="2026-09-16T10:00:00+00:00")
    older = store.create_page("note")
    store.update_page(replace(older, tags=("资料", "工作")))
    store._pages[older.id] = replace(store.page(older.id), updated_at="2026-09-15T10:00:00+00:00")
    target = store.create_page("note")
    store.update_page(replace(target, tags=("项目",)))
    store._pages[target.id] = replace(store.page(target.id), updated_at="2026-09-14T10:00:00+00:00")
    trashed = store.create_page("note")
    store.update_page(replace(trashed, tags=("回收站标签",)))
    store.delete_page(trashed.id)
    window = QuickNotebookWindow(store=store)
    qtbot.addWidget(window)
    window.show_page(target.id)

    window.category_toggle.click()

    assert window.current_categories() == ("项目",)
    assert window.category_candidate_names() == ("工作", "灵感", "资料")
    assert "回收站标签" not in window.category_candidate_names()
    assert (
        window.category_selected_buttons["项目"].sizePolicy().horizontalPolicy()
        == QSizePolicy.Policy.Maximum
    )
    assert window.category_choices_layout.hasHeightForWidth()
    window.category_choice_buttons["工作"].click()
    assert window.current_categories() == ("项目", "工作")
    window.category_selected_buttons["项目"].click()
    assert window.current_categories() == ("工作",)
    assert window.flush_current_page()
    reloaded = QuickNotebookStore(store.path)
    reloaded.load()
    assert reloaded.page(target.id).tags == ("工作",)


def test_category_creation_normalizes_reuses_and_enforces_limits(qtbot, tmp_path) -> None:
    window = QuickNotebookWindow(store=QuickNotebookStore(tmp_path / "book.json"))
    qtbot.addWidget(window)
    window.show()
    window.category_toggle.click()

    for name in (" 项目 ", "项目", "工作", "生活", "资料", "重要", "第六个"):
        window.category_new_editor.setText(name)
        qtbot.keyClick(window.category_new_editor, Qt.Key.Key_Return)

    assert window.current_categories() == ("项目", "工作", "生活", "资料", "重要")
    assert window.category_limit_hint.isVisible()
    window.category_new_editor.setText("   ")
    qtbot.keyClick(window.category_new_editor, Qt.Key.Key_Return)
    assert window.current_categories() == ("项目", "工作", "生活", "资料", "重要")


def test_category_name_is_limited_and_escape_closes_panel(qtbot, tmp_path) -> None:
    window = QuickNotebookWindow(store=QuickNotebookStore(tmp_path / "book.json"))
    qtbot.addWidget(window)
    window.show()
    window.category_toggle.click()
    window.category_new_editor.setText("1234567890额外")
    qtbot.keyClick(window.category_new_editor, Qt.Key.Key_Return)
    assert window.current_categories() == ("1234567890",)

    window.category_new_editor.setFocus()
    qtbot.keyClick(window.category_new_editor, Qt.Key.Key_Escape)

    assert window.category_panel.isHidden()
    assert window.focusWidget() is window.category_toggle


def test_category_draft_is_cleared_when_switching_pages(qtbot, tmp_path) -> None:
    store = QuickNotebookStore(tmp_path / "book.json")
    first = store.create_page("note")
    second = store.create_page("note")
    window = QuickNotebookWindow(store=store)
    qtbot.addWidget(window)
    window.show_page(first.id)
    window.category_toggle.click()
    window.category_new_editor.setText("第一页草稿")

    window.show_page(second.id)
    window.category_toggle.click()

    assert window.category_new_editor.text() == ""


def test_category_input_rejects_multiple_names_in_one_entry(qtbot, tmp_path) -> None:
    window = QuickNotebookWindow(store=QuickNotebookStore(tmp_path / "book.json"))
    qtbot.addWidget(window)
    window.show()
    window.category_toggle.click()
    window._set_categories(("项目", "工作", "生活", "资料"))
    window.category_new_editor.setText("甲,乙")

    qtbot.keyClick(window.category_new_editor, Qt.Key.Key_Return)

    assert window.current_categories() == ("项目", "工作", "生活", "资料")
    assert window.category_limit_hint.text() == "一次只能添加一个分类"
    assert window.category_limit_hint.isVisible()


def test_removing_last_use_of_category_hides_it_from_candidates_immediately(qtbot, tmp_path) -> None:
    store = QuickNotebookStore(tmp_path / "book.json")
    page = store.create_page("note")
    store.update_page(replace(page, tags=("临时标签",)))
    window = QuickNotebookWindow(store=store)
    qtbot.addWidget(window)
    window.show_page(page.id)
    window.category_toggle.click()

    window.category_selected_buttons["临时标签"].click()

    assert window.current_categories() == ()
    assert "临时标签" not in window.category_candidate_names()


def test_switching_away_from_note_collapses_category_panel_before_escape(qtbot, tmp_path) -> None:
    window = QuickNotebookWindow(store=QuickNotebookStore(tmp_path / "book.json"))
    qtbot.addWidget(window)
    window.show()
    window.category_toggle.click()
    window.select_type("todo")

    assert not window.category_toggle.isChecked()
    assert window.category_panel.isHidden()
    qtbot.keyClick(window, Qt.Key.Key_Escape)
    assert not window.isVisible()


def test_directory_and_confirmation_take_escape_priority_over_category_panel(qtbot, tmp_path) -> None:
    window = QuickNotebookWindow(store=QuickNotebookStore(tmp_path / "book.json"))
    qtbot.addWidget(window)
    window.show()
    window.category_toggle.click()
    window.open_directory()
    qtbot.keyClick(window, Qt.Key.Key_Escape)
    assert window.directory_overlay.isHidden()
    assert window.isVisible()

    window.note_editor.setPlainText("需要确认删除")
    window.flush_current_page()
    window.category_toggle.click()
    window.delete_button.click()
    qtbot.keyClick(window, Qt.Key.Key_Escape)
    assert window.confirm_overlay.isHidden()
    assert window.isVisible()


def test_tabs_share_the_paper_edge_without_entering_content(qtbot, tmp_path) -> None:
    window = QuickNotebookWindow(store=QuickNotebookStore(tmp_path / "quick-notebook.json"))
    qtbot.addWidget(window)
    window.resize(window.sizeHint())
    window.show()
    qtbot.waitExposed(window)

    assert [
        button.geometry().right()
        - window.paper_layers[button.property("pageType")].geometry().left()
        for button in window.type_tabs
    ] == [7, 7, 7]


def test_fit_keeps_footer_buttons_and_tabs_visible(qtbot, tmp_path) -> None:
    window = QuickNotebookWindow(store=QuickNotebookStore(tmp_path / "quick-notebook.json"))
    qtbot.addWidget(window)

    fitted = window.fit_to_available_geometry(QRect(0, 0, 360, 520))
    window.show()
    qtbot.waitExposed(window)

    assert fitted.width() <= 360
    assert fitted.height() <= 520
    assert window.footer.geometry().bottom() <= window.rect().bottom()
    assert window.new_button.mapTo(window, window.new_button.rect().bottomRight()).x() < window.width()


def test_type_switch_scopes_directory_and_count(qtbot, tmp_path) -> None:
    store = QuickNotebookStore(tmp_path / "quick-notebook.json")
    store.create_page("note")
    store.create_page("note")
    store.create_page("todo")
    window = QuickNotebookWindow(store=store)
    qtbot.addWidget(window)

    window.select_type("note")
    assert window.page_count_label.text() == "1 / 2"
    assert len(window.directory_titles()) == 2
    window.select_type("todo")
    assert window.page_count_label.text() == "1 / 1"
    assert len(window.directory_titles()) == 1


def test_optional_title_tracks_first_line_until_customized(qtbot, tmp_path) -> None:
    store = QuickNotebookStore(tmp_path / "quick-notebook.json")
    page = store.create_page("note")
    window = QuickNotebookWindow(store=store)
    qtbot.addWidget(window)
    window.show_page(page.id)

    window.note_editor.setPlainText("自动标题\n正文")
    qtbot.wait(550)

    assert window.title_editor.text() == ""
    assert window.title_editor.placeholderText() == "自动命名：自动标题"
    assert store.page(page.id).custom_title is None
    assert store.page(page.id).body == "自动标题\n正文"
    window.set_custom_title("自定义标题")
    window.note_editor.setPlainText("新首行")
    qtbot.wait(550)
    assert window.title_editor.text() == "自定义标题"
    assert store.page(page.id).custom_title == "自定义标题"


def test_switching_pages_flushes_pending_note_edits(qtbot, tmp_path) -> None:
    store = QuickNotebookStore(tmp_path / "quick-notebook.json")
    first = store.create_page("note")
    second = store.create_page("note")
    window = QuickNotebookWindow(store=store)
    qtbot.addWidget(window)
    window.show_page(first.id)
    window.note_editor.setPlainText("切页前保存")

    window.show_page(second.id)

    assert store.page(first.id).body == "切页前保存"


def test_todo_and_reminder_editors_round_trip_items(qtbot, tmp_path) -> None:
    store = QuickNotebookStore(tmp_path / "quick-notebook.json")
    todo_page = store.create_page("todo")
    reminder_page = store.create_page("reminder")
    window = QuickNotebookWindow(store=store)
    qtbot.addWidget(window)

    window.show_page(todo_page.id)
    window.todo_editor.set_items((TodoItem("t1", "确认布局"),))
    window.todo_editor.add_item("补充测试")
    window.flush_current_page()
    assert [item.text for item in store.page(todo_page.id).todo_items] == ["确认布局", "补充测试"]

    window.show_page(reminder_page.id)
    window.reminder_editor.set_items((ReminderItem("r1", "交周报"),))
    window.reminder_editor.add_item("续费提醒")
    window.flush_current_page()
    assert [item.text for item in store.page(reminder_page.id).reminders] == ["交周报", "续费提醒"]


def test_empty_todo_shows_input_hint_without_saving_it(qtbot, tmp_path) -> None:
    store = QuickNotebookStore(tmp_path / "quick-notebook.json")
    page = store.create_page("todo")
    window = QuickNotebookWindow(store=store)
    qtbot.addWidget(window)
    window.show_page(page.id)
    window.todo_editor.set_items(())
    window.todo_editor.add_item("")

    row = window.todo_editor._rows[0]
    assert row.text.placeholderText() == "点击输入待办事项"
    assert row.text.text() == ""
    window.flush_current_page()
    assert store.page(page.id).todo_items[0].text == ""


def test_delete_clear_and_restore_update_visible_pages(qtbot, tmp_path) -> None:
    store = QuickNotebookStore(tmp_path / "quick-notebook.json")
    note = store.create_page("note")
    store.update_note(note.id, custom_title=None, body="需要保留的内容")
    store.create_page("todo")
    window = QuickNotebookWindow(store=store)
    qtbot.addWidget(window)

    window.confirm_delete_page(note.id)
    assert store.trash_count == 1
    window.select_type("todo")
    window.confirm_clear_all()
    assert store.trash_count == 2
    assert store.page_ids("note") == ()
    assert store.page_ids("todo") == ()
    window.restore_from_trash(note.id)
    assert store.page(note.id) is not None


def test_new_and_flip_stay_inside_active_type(qtbot, tmp_path) -> None:
    store = QuickNotebookStore(tmp_path / "quick-notebook.json")
    first = store.create_page("note")
    store.create_page("todo")
    window = QuickNotebookWindow(store=store)
    qtbot.addWidget(window)
    window.select_type("note")

    created = window.new_page()
    assert created.type == "note"
    assert window.current_page_id == created.id
    window.next_page()
    assert window.current_page_id == first.id


def test_note_tags_round_trip_through_editor(qtbot, tmp_path) -> None:
    store = QuickNotebookStore(tmp_path / "quick-notebook.json")
    page = store.create_page("note")
    window = QuickNotebookWindow(store=store)
    qtbot.addWidget(window)
    window.show_page(page.id)

    window.tag_editor.setText("待发送，小林")
    window.show()
    qtbot.waitExposed(window)
    window.flush_current_page()

    assert store.page(page.id).tags == ("待发送", "小林")
    assert window.category_panel.isVisible()
    assert window.category_panel.width() >= 220
    assert window.category_panel.width() == window.note_editor.viewport().width() - 16


def test_todo_progress_bar_matches_completed_ratio(qtbot, tmp_path) -> None:
    store = QuickNotebookStore(tmp_path / "quick-notebook.json")
    page = store.create_page("todo")
    window = QuickNotebookWindow(store=store)
    qtbot.addWidget(window)
    window.show_page(page.id)

    window.todo_editor.set_items(
        (
            TodoItem("t1", "完成", completed=True),
            TodoItem("t2", "未完成"),
        )
    )

    assert window.todo_editor.progress_bar.value() == 50


def test_delete_and_clear_require_in_window_confirmation(qtbot, tmp_path) -> None:
    store = QuickNotebookStore(tmp_path / "quick-notebook.json")
    note = store.create_page("note")
    store.update_note(note.id, custom_title=None, body="需要确认删除")
    store.create_page("todo")
    window = QuickNotebookWindow(store=store)
    qtbot.addWidget(window)
    window.show_page(note.id)
    window.show()

    window.delete_button.click()
    assert store.page(note.id) is not None
    assert window.confirm_overlay.isVisible()
    window.confirm_action_button.click()
    assert store.page(note.id) is None

    window.open_directory()
    window.clear_all_button.click()
    assert store.page_ids("todo")
    assert window.confirm_overlay.isVisible()
    window.confirm_action_button.click()
    assert store.page_ids("todo")


def test_escape_closes_notebook_without_deleting_content(qtbot, tmp_path) -> None:
    store = QuickNotebookStore(tmp_path / "quick-notebook.json")
    page = store.create_page("note")
    window = QuickNotebookWindow(store=store)
    qtbot.addWidget(window)
    window.show_page(page.id)
    window.show()

    qtbot.keyClick(window, Qt.Key.Key_Escape)

    assert not window.isVisible()
    assert store.page(page.id) is not None


def test_new_reminder_defaults_to_a_future_time(qtbot, tmp_path) -> None:
    window = QuickNotebookWindow(store=QuickNotebookStore(tmp_path / "quick-notebook.json"))
    qtbot.addWidget(window)

    window.reminder_editor.add_item("稍后处理")
    reminder = window.reminder_editor.items()[-1]

    assert reminder.due_at is not None
    assert datetime.fromisoformat(reminder.due_at) > datetime.now().astimezone()


def test_weekly_reminder_exposes_editable_weekdays(qtbot, tmp_path) -> None:
    window = QuickNotebookWindow(store=QuickNotebookStore(tmp_path / "quick-notebook.json"))
    qtbot.addWidget(window)
    window.reminder_editor.set_items(
        (ReminderItem("r1", "周报", repeat="weekly", weekdays=(0, 4)),)
    )
    row = window.reminder_editor._rows[0]

    row.weekday_checks[2].setChecked(True)

    assert window.reminder_editor.items()[0].weekdays == (0, 2, 4)


def test_delete_uses_the_final_line_icon(qtbot, tmp_path) -> None:
    window = QuickNotebookWindow(store=QuickNotebookStore(tmp_path / "quick-notebook.json"))
    qtbot.addWidget(window)

    assert window.delete_button.property("iconName") == "trash-2"


def test_opening_or_flipping_does_not_change_page_modified_order(qtbot, tmp_path) -> None:
    store = QuickNotebookStore(tmp_path / "quick-notebook.json")
    first = store.create_page("note")
    second = store.create_page("note")
    original_timestamp = store.page(first.id).updated_at
    original_order = store.page_ids("note")
    window = QuickNotebookWindow(store=store)
    qtbot.addWidget(window)

    window.show_page(first.id)
    window.show_page(second.id)

    assert store.page(first.id).updated_at == original_timestamp
    assert store.page_ids("note") == original_order


def test_final_visual_metrics_match_reference(qtbot, tmp_path) -> None:
    window = QuickNotebookWindow(store=QuickNotebookStore(tmp_path / "quick-notebook.json"))
    qtbot.addWidget(window)
    window.resize(window.sizeHint())
    window.show()
    qtbot.waitExposed(window)

    assert window.rect().bottom() - window.body_frame.geometry().bottom() >= 8
    assert [button.property("iconName") for button in window.type_tabs] == [
        "pencil",
        "check",
        "clock-3",
    ]
    assert all(button.property("textColor") == "#FFFFFF" for button in window.type_tabs)
    assert window.directory_button.property("iconName") == "menu"
    assert window.category_new_editor.placeholderText() == "输入新分类名称"
    assert window.body_label.text() == "正文"
    mask = window.body_frame.mask()
    assert not mask.contains(QPoint(0, window.body_frame.height() - 1))
    assert mask.contains(QPoint(window.body_frame.width() // 2, window.body_frame.height() - 2))


def test_todo_layout_matches_reference_cards(qtbot, tmp_path) -> None:
    window = QuickNotebookWindow(store=QuickNotebookStore(tmp_path / "quick-notebook.json"))
    qtbot.addWidget(window)
    window.todo_editor.set_items(
        (
            TodoItem("t1", "完成", completed=True),
            TodoItem("t2", "未完成"),
        )
    )

    margins = window.todo_editor.layout().contentsMargins()
    assert (margins.left(), margins.top(), margins.right()) == (12, 12, 12)
    assert window.todo_editor.progress_percent_label.text() == "50%"
    assert all(row.objectName() == "quickNotebookTodoRow" for row in window.todo_editor._rows)
    assert all(row.check.objectName() == "quickNotebookTodoCheck" for row in window.todo_editor._rows)
    assert all(row.check.size() == QSize(32, 32) for row in window.todo_editor._rows)


def test_reminder_layout_matches_reference_cards(qtbot, tmp_path) -> None:
    window = QuickNotebookWindow(store=QuickNotebookStore(tmp_path / "quick-notebook.json"))
    qtbot.addWidget(window)
    window.reminder_editor.set_items(
        (ReminderItem("r1", "把方案发给小林", due_at="2026-09-03T10:00:00+08:00"),)
    )
    row = window.reminder_editor._rows[0]
    margins = window.reminder_editor.layout().contentsMargins()

    assert (margins.left(), margins.top(), margins.right()) == (12, 12, 12)
    assert row.objectName() == "quickNotebookReminderRow"
    assert row.date_box.objectName() == "quickNotebookDateBox"
    assert row.enabled.objectName() == "quickNotebookReminderSwitch"
    assert row.due.calendarPopup() is True
    assert row.due.displayFormat() == "yyyy-MM-dd HH:mm"


def test_confirmation_buttons_match_reference_spacing(qtbot, tmp_path) -> None:
    window = QuickNotebookWindow(store=QuickNotebookStore(tmp_path / "quick-notebook.json"))
    qtbot.addWidget(window)

    assert window.confirm_cancel_button.minimumWidth() >= 54
    assert window.confirm_action_button.minimumWidth() >= 54
    assert "padding: 5px 9px" in window.styleSheet()
    assert (
        "QFrame#quickNotebookConfirmOverlay QPushButton#quickNotebookDangerButton"
        in window.styleSheet()
    )


def test_deleting_completely_empty_page_skips_trash(qtbot, tmp_path) -> None:
    store = QuickNotebookStore(tmp_path / "quick-notebook.json")
    page = store.create_page("note")
    window = QuickNotebookWindow(store=store)
    qtbot.addWidget(window)

    window.confirm_delete_page(page.id)

    assert store.trash_count == 0
    assert store.page(page.id) is None


def test_delete_button_skips_confirmation_for_completely_empty_page(qtbot, tmp_path) -> None:
    store = QuickNotebookStore(tmp_path / "quick-notebook.json")
    page = store.create_page("note")
    window = QuickNotebookWindow(store=store)
    qtbot.addWidget(window)
    window.show_page(page.id)
    window.show()

    window.delete_button.click()

    assert window.confirm_overlay.isHidden()
    assert store.page(page.id) is None
    assert store.trash_count == 0


def test_delete_button_keeps_confirmation_for_nonempty_page(qtbot, tmp_path) -> None:
    store = QuickNotebookStore(tmp_path / "quick-notebook.json")
    page = store.create_page("note")
    store.update_note(page.id, custom_title=None, body="保留内容")
    window = QuickNotebookWindow(store=store)
    qtbot.addWidget(window)
    window.show_page(page.id)
    window.show()

    window.delete_button.click()

    assert window.confirm_overlay.isVisible()
    assert "进入回收站" in window.confirm_message.text()
    assert store.page(page.id) is not None


def test_deleting_dirty_current_page_flushes_content_into_trash(qtbot, tmp_path) -> None:
    store = QuickNotebookStore(tmp_path / "quick-notebook.json")
    page = store.create_page("note")
    window = QuickNotebookWindow(store=store)
    qtbot.addWidget(window)
    window.show_page(page.id)
    window.note_editor.setPlainText("刚输入、尚未自动保存")

    window.confirm_delete_page(page.id)

    assert store.page(page.id) is None
    assert store.trash_count == 1
    assert store.trash_entries()[0].page.body == "刚输入、尚未自动保存"


def test_directory_uses_elided_spaced_cards_without_horizontal_scroll(qtbot, tmp_path) -> None:
    store = QuickNotebookStore(tmp_path / "quick-notebook.json")
    page = store.create_page("note")
    store.update_note(page.id, custom_title="很长很长的目录标题" * 8, body="正文")
    window = QuickNotebookWindow(store=store)
    qtbot.addWidget(window)

    window.open_directory()

    assert window.directory_list.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    assert window.directory_list.textElideMode() == Qt.TextElideMode.ElideRight
    assert "QListWidget#quickNotebookDirectoryList::item" in window.styleSheet()
    assert window.trash_button.objectName() == "quickNotebookTrashButton"


def test_many_todo_items_scroll_instead_of_compressing_rows(qtbot, tmp_path) -> None:
    store = QuickNotebookStore(tmp_path / "quick-notebook.json")
    page = store.create_page("todo")
    window = QuickNotebookWindow(store=store)
    qtbot.addWidget(window)
    window.show_page(page.id)
    window.todo_editor.set_items(
        tuple(TodoItem(f"t{index}", f"待办 {index}") for index in range(12))
    )
    window.show()
    qtbot.waitExposed(window)

    assert window.todo_editor.rows_scroll.verticalScrollBar().maximum() > 0
    assert window.todo_editor.rows_scroll.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff


def test_directory_rows_right_align_page_count_and_restore_action(qtbot, tmp_path) -> None:
    store = QuickNotebookStore(tmp_path / "quick-notebook.json")
    first = store.create_page("note")
    store.update_note(first.id, custom_title="第一张", body="正文")
    second = store.create_page("note")
    store.update_note(second.id, custom_title="第二张", body="正文")
    deleted = store.create_page("note")
    store.update_note(deleted.id, custom_title="已删除", body="正文")
    store.delete_page(deleted.id)
    window = QuickNotebookWindow(store=store)
    qtbot.addWidget(window)
    window.show()

    window.open_directory()
    qtbot.wait(10)
    page_row = window.directory_list.itemWidget(window.directory_list.item(0))
    assert page_row.right_label.text() == "1 / 2"
    assert page_row.right_label.geometry().right() >= page_row.width() - 12
    assert window.trash_button.text() == "回收站 · 1"

    window.open_trash()
    qtbot.wait(10)
    trash_row = window.directory_list.itemWidget(window.directory_list.item(0))
    assert window.directory_title.text() == "回收站 · 1"
    assert trash_row.restore_button.objectName() == "quickNotebookRestoreButton"
    assert trash_row.restore_button.geometry().right() >= trash_row.width() - 12
    assert window.directory_list.item(0).sizeHint().height() >= 50
    assert trash_row.restore_button.geometry().bottom() <= trash_row.height() - 6
    assert "QPushButton#quickNotebookRestoreButton" in window.styleSheet()


def test_single_rows_keep_card_height_and_scrollbars_use_notebook_skin(qtbot, tmp_path) -> None:
    store = QuickNotebookStore(tmp_path / "quick-notebook.json")
    todo = store.create_page("todo")
    reminder = store.create_page("reminder")
    window = QuickNotebookWindow(store=store)
    qtbot.addWidget(window)
    window.show()

    window.show_page(todo.id)
    window.todo_editor.set_items((TodoItem("t1", "唯一待办"),))
    qtbot.wait(10)
    assert window.todo_editor._rows[0].height() <= 52
    assert "QScrollBar:vertical" in window.styleSheet()
    assert window.todo_editor.rows_scroll.viewport().objectName() == "quickNotebookTodoViewport"

    window.show_page(reminder.id)
    window.reminder_editor.set_items(
        (ReminderItem("r1", "唯一提醒", due_at="2026-09-03T10:00:00+08:00"),)
    )
    qtbot.wait(10)
    assert window.reminder_editor._rows[0].height() <= 108
    assert window.reminder_editor.rows_scroll.viewport().objectName() == "quickNotebookReminderViewport"


def test_layered_shell_preserves_todo_and_reminder_item_visual_contract(
    qtbot, tmp_path
) -> None:
    window = QuickNotebookWindow(store=QuickNotebookStore(tmp_path / "book.json"))
    qtbot.addWidget(window)
    window.todo_editor.set_items((TodoItem("t1", "待办事项"),))
    window.reminder_editor.set_items(
        (
            ReminderItem(
                "r1",
                "提醒事项",
                due_at="2026-09-16T18:00:00+08:00",
            ),
        )
    )
    todo_row = window.todo_editor._rows[0]
    reminder_row = window.reminder_editor._rows[0]

    assert todo_row.height() == 48
    assert todo_row.layout().contentsMargins() == QMargins(8, 6, 8, 6)
    assert todo_row.check.size() == QSize(32, 32)
    assert reminder_row.layout().contentsMargins() == QMargins(10, 9, 10, 9)
    assert reminder_row.date_box.size() == QSize(52, 58)
    assert reminder_row.enabled.size() == QSize(31, 18)
    assert reminder_row.confirm_time_button.size().width() >= 52
    assert reminder_row.confirm_time_button.size().height() >= 28
    option = QStyleOptionButton()
    reminder_row.confirm_time_button.initStyleOption(option)
    content_rect = reminder_row.confirm_time_button.style().subElementRect(
        QStyle.SubElement.SE_PushButtonContents,
        option,
        reminder_row.confirm_time_button,
    )
    assert (
        reminder_row.confirm_time_button.fontMetrics().horizontalAdvance("开启")
        <= content_rect.width()
    )
    assert "QFrame#quickNotebookTodoRow" in window.styleSheet()
    assert "QFrame#quickNotebookReminderRow" in window.styleSheet()


@pytest.mark.parametrize("page_type", ["note", "todo", "reminder"])
def test_navigation_explains_page_scope_and_fits_small_screen(qtbot, tmp_path, page_type) -> None:
    window = QuickNotebookWindow(store=QuickNotebookStore(tmp_path / "book.json"))
    qtbot.addWidget(window)
    window.select_type(page_type)
    window.fit_to_available_geometry(QRect(0, 0, 360, 520))
    window.show()
    qtbot.waitExposed(window)

    assert window.new_button.text() == "+"
    assert window.directory_button.text() == "目录"
    for widget in (window.new_button, window.directory_button, window.previous_button, window.next_button, window.close_button, *window.type_tabs):
        assert window.rect().contains(QRect(widget.mapTo(window, QPoint()), widget.size()))
    assert not window.page_hint.text().startswith("普通")


def test_todo_enter_focuses_next_row_and_reuses_blank(qtbot, tmp_path) -> None:
    window = QuickNotebookWindow(store=QuickNotebookStore(tmp_path / "book.json"))
    qtbot.addWidget(window)
    window.select_type("todo")
    window.show()
    editor = window.todo_editor
    editor.add_button.click()
    first = editor._rows[0]
    assert window.focusWidget() is first.text
    first.text.setText("完成第一件事")
    qtbot.keyClick(first.text, Qt.Key.Key_Return)
    assert len(editor._rows) == 2
    assert window.focusWidget() is editor._rows[1].text
    editor.add_button.click()
    assert len(editor._rows) == 2
    first.check.setChecked(True)
    assert editor.progress_bar.value() == 100
    assert editor.progress_label.text() == "已完成 1 / 1 项"


@pytest.mark.parametrize("page_type", ["todo", "reminder"])
def test_item_delete_undo_preserves_order_and_saved_values(qtbot, tmp_path, page_type) -> None:
    store = QuickNotebookStore(tmp_path / "book.json")
    window = QuickNotebookWindow(store=store)
    qtbot.addWidget(window)
    window.select_type(page_type)
    editor = window.todo_editor if page_type == "todo" else window.reminder_editor
    for text in ("第一条", "第二条", "第三条"):
        editor.add_item(text)
    original = editor.items()
    editor._rows[1].remove_button.click()
    assert [item.text for item in editor.items()] == ["第一条", "第三条"]
    editor._rows[0].remove_button.click()
    editor.removal_history.undo_button.click()
    editor.removal_history.undo_button.click()
    assert editor.items() == original
    window.flush_current_page()
    reloaded = QuickNotebookStore(store.path)
    reloaded.load()
    page = reloaded.page(window.current_page_id)
    assert tuple(page.todo_items if page_type == "todo" else page.reminders) == original
    editor._rows[0].remove_button.click()
    window.new_page()
    assert editor.removal_history.isHidden()


def test_reminder_creation_exposes_time_and_weekly_defaults(qtbot, tmp_path) -> None:
    window = QuickNotebookWindow(store=QuickNotebookStore(tmp_path / "book.json"))
    qtbot.addWidget(window)
    window.select_type("reminder")
    window.show()
    editor = window.reminder_editor
    editor.add_button.click()
    row = editor._rows[0]
    assert row.edit_panel.isVisible()
    assert window.focusWidget() is row.text
    editor.add_button.click()
    assert len(editor._rows) == 1
    row.repeat.setCurrentIndex(row.repeat.findData("weekly"))
    assert row.value().weekdays == (row.due.dateTime().toPython().weekday(),)
    row.enabled.setChecked(False)
    assert "未开启" in row.sub_label.text()
    row.edit_time_button.click()
    assert row.edit_panel.isHidden()
    assert row.edit_time_button.text() == "设置时间 ▾"


@pytest.mark.parametrize("page_type", ["note", "todo", "reminder"])
def test_edit_after_deleting_last_page_is_saved(qtbot, tmp_path, page_type) -> None:
    store = QuickNotebookStore(tmp_path / "book.json")
    window = QuickNotebookWindow(store=store)
    qtbot.addWidget(window)
    window.select_type(page_type)
    window.confirm_delete_page(window.current_page_id)
    assert window.current_page_id is None
    if page_type == "note":
        window.note_editor.setPlainText("继续记录")
    else:
        editor = window.todo_editor if page_type == "todo" else window.reminder_editor
        editor.add_item("继续记录")
    window.flush_current_page()
    assert store.page(window.current_page_id).display_title == "继续记录"


def test_close_button_saves_and_trash_has_a_way_back(qtbot, tmp_path) -> None:
    store = QuickNotebookStore(tmp_path / "book.json")
    window = QuickNotebookWindow(store=store)
    qtbot.addWidget(window)
    window.show()
    window.open_directory()
    window.trash_button.click()
    assert window.trash_button.text() == "‹ 返回列表"
    window.trash_button.click()
    assert "目录" in window.directory_title.text()
    window.directory_close_button.click()
    window.note_editor.setPlainText("关闭时保存")
    with qtbot.waitSignal(window.closed_by_user):
        window.close_button.click()
    assert not window.isVisible()
    assert store.page(window.current_page_id).body == "关闭时保存"


def test_weekly_reminder_controls_fit_narrow_viewport(qtbot, tmp_path) -> None:
    window = QuickNotebookWindow(store=QuickNotebookStore(tmp_path / "book.json"))
    qtbot.addWidget(window)
    window.select_type("reminder")
    window.fit_to_available_geometry(QRect(0, 0, 360, 520))
    window.show()
    window.reminder_editor.add_item("每周提醒")
    row = window.reminder_editor._rows[0]
    row.repeat.setCurrentIndex(row.repeat.findData("weekly"))
    qtbot.wait(20)

    viewport = window.reminder_editor.rows_scroll.viewport()
    assert row.width() <= viewport.width()
    for widget in (row.due, row.repeat, *row.weekday_checks):
        assert widget.mapTo(row, widget.rect().bottomRight()).x() < row.width()


@pytest.mark.parametrize("page_type", ["todo", "reminder"])
def test_new_item_input_is_scrolled_into_view(qtbot, tmp_path, page_type) -> None:
    window = QuickNotebookWindow(store=QuickNotebookStore(tmp_path / "book.json"))
    qtbot.addWidget(window)
    window.select_type(page_type)
    window.show()
    editor = window.todo_editor if page_type == "todo" else window.reminder_editor
    for index in range(12):
        editor.add_item(f"事项 {index}")
    qtbot.wait(20)
    editor.add_button.click()
    qtbot.wait(20)
    text = editor._rows[-1].text
    viewport = editor.rows_scroll.viewport()
    assert viewport.rect().contains(text.mapTo(viewport, text.rect().center()))


def test_note_fields_keep_accessible_names_without_permanent_labels(qtbot, tmp_path) -> None:
    window = QuickNotebookWindow(store=QuickNotebookStore(tmp_path / "book.json"))
    qtbot.addWidget(window)
    window.show()
    window.set_custom_title("项目记录")
    window.note_editor.setPlainText("今天的讨论要点")
    window._set_categories(("工作", "项目"))
    qtbot.wait(20)

    assert window.title_label.isHidden()
    assert window.body_label.isHidden()
    assert window.tag_label.isHidden()
    assert window.title_label.buddy() is window.title_editor
    assert window.body_label.buddy() is window.note_editor
    assert window.tag_label.buddy() is window.category_new_editor
    assert window.title_editor.accessibleName() == "标题（选填）"
    assert window.note_editor.accessibleName() == "便签正文"
    assert window.category_new_editor.accessibleName() == "新分类名称"
    assert window.tag_editor.isHidden()
    assert [
        window.category_summary_layout.itemAt(index).widget().text()
        for index in range(window.category_summary_layout.count())
        if window.category_summary_layout.itemAt(index).widget().objectName()
        == "quickNotebookCategorySummaryTag"
    ] == ["工作", "项目"]


@pytest.mark.parametrize("page_type", ["note", "todo", "reminder"])
def test_clearing_custom_title_restores_automatic_name_without_inserting_text(qtbot, tmp_path, page_type) -> None:
    store = QuickNotebookStore(tmp_path / "book.json")
    window = QuickNotebookWindow(store=store)
    qtbot.addWidget(window)
    window.select_type(page_type)
    if page_type == "note":
        window.note_editor.setPlainText("来自内容的名称")
    else:
        editor = window.todo_editor if page_type == "todo" else window.reminder_editor
        editor.add_item("来自内容的名称")
    window.set_custom_title("旧标题")
    window.flush_current_page()
    window.set_custom_title(None)
    window.flush_current_page()
    window.show_page(window.current_page_id)

    assert window.title_editor.text() == ""
    assert window.title_editor.placeholderText() == "自动命名：来自内容的名称"
    assert store.page(window.current_page_id).custom_title is None
    assert store.page(window.current_page_id).display_title == "来自内容的名称"


def test_note_fields_fit_narrow_window(qtbot, tmp_path) -> None:
    window = QuickNotebookWindow(store=QuickNotebookStore(tmp_path / "book.json"))
    qtbot.addWidget(window)
    window.fit_to_available_geometry(QRect(0, 0, 360, 520))
    window.show()
    window.category_toggle.click()
    qtbot.wait(20)

    for widget in (window.title_label, window.title_editor, window.body_label, window.note_editor, window.tag_label, window.category_panel, window.category_new_editor):
        rect = QRect(widget.mapTo(window, QPoint()), widget.size())
        assert window.rect().contains(rect)
        assert rect.bottom() < window.footer.mapTo(window, QPoint()).y()
    assert window.category_panel.width() == window.note_editor.viewport().width() - 16
    assert window.note_editor.height() >= 72


def test_scroll_background_does_not_override_item_card_borders(qtbot, tmp_path) -> None:
    window = QuickNotebookWindow(store=QuickNotebookStore(tmp_path / "quick-notebook.json"))
    qtbot.addWidget(window)

    assert window.todo_editor.rows_widget.styleSheet() == ""
    assert window.todo_editor.rows_scroll.viewport().styleSheet() == ""
    assert window.reminder_editor.rows_widget.styleSheet() == ""
    assert window.reminder_editor.rows_scroll.viewport().styleSheet() == ""
    assert "QFrame#quickNotebookTodoRow" in window.styleSheet()
    assert "QFrame#quickNotebookReminderRow" in window.styleSheet()


def test_notebook_scrollbar_uses_refined_paper_edge_style(qtbot, tmp_path) -> None:
    window = QuickNotebookWindow(store=QuickNotebookStore(tmp_path / "book.json"))
    qtbot.addWidget(window)
    window.note_editor.setPlainText("\n".join(f"第 {index} 行" for index in range(80)))
    window.show()
    qtbot.waitExposed(window)

    native_scrollbar = window.note_editor.verticalScrollBar()
    scrollbar = window.note_edge_scrollbar
    assert (
        window.note_editor.verticalScrollBarPolicy()
        == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    )
    assert scrollbar.isVisible()
    assert scrollbar.parent() is window.body_frame
    assert scrollbar.property("paintsRoundedHandle") is True
    assert scrollbar.property("handleCornerRadius") == 2.5
    assert scrollbar.geometry().right() == window.body_frame.rect().right()
    assert scrollbar.geometry().bottom() < window.category_floating.geometry().top()
    assert scrollbar.width() <= 7
    scrollbar.setValue(scrollbar.maximum())
    assert native_scrollbar.value() == native_scrollbar.maximum()
    stylesheet = window.styleSheet()
    assert "qlineargradient" in stylesheet
    assert "background: rgba(201, 126, 88, 150)" in stylesheet
    assert "border-radius: 3px" in stylesheet
    assert "QScrollBar::handle:vertical:pressed" in stylesheet


@pytest.mark.parametrize("page_type", ["todo", "reminder"])
def test_shared_edge_scrollbar_follows_list_pages(qtbot, tmp_path, page_type) -> None:
    window = QuickNotebookWindow(store=QuickNotebookStore(tmp_path / "book.json"))
    qtbot.addWidget(window)
    window.select_type(page_type)
    editor = window.todo_editor if page_type == "todo" else window.reminder_editor
    for index in range(20):
        editor.add_item(f"事项 {index}")
    window.show()
    qtbot.waitExposed(window)
    qtbot.wait(20)

    assert window._edge_scroll_source is editor.rows_scroll
    assert window.note_edge_scrollbar.isVisible()
    assert window.note_edge_scrollbar.geometry().right() == window.body_frame.rect().right()
    assert window.note_edge_scrollbar.property("paintsRoundedHandle") is True


def test_shared_edge_scrollbar_follows_directory_and_trash(qtbot, tmp_path) -> None:
    store = QuickNotebookStore(tmp_path / "book.json")
    for index in range(30):
        page = store.create_page("note")
        store.update_note(page.id, custom_title=f"便签 {index}", body=f"正文 {index}")
        if index >= 15:
            store.delete_page(page.id)
    window = QuickNotebookWindow(store=store)
    qtbot.addWidget(window)
    window.fit_to_available_geometry(QRect(0, 0, 360, 360))
    window.show()
    window.open_directory()
    qtbot.wait(20)

    assert window._edge_scroll_source is window.directory_list
    assert window.note_edge_scrollbar.isVisible()
    assert window.note_edge_scrollbar.geometry().right() == window.body_frame.rect().right()
    assert window.category_floating.isHidden()

    window.open_trash()
    qtbot.wait(20)
    assert window._edge_scroll_source is window.directory_list
    assert window.note_edge_scrollbar.isVisible()
    assert window.category_floating.isHidden()

    window._close_directory()
    qtbot.wait(20)
    assert window.category_floating.isVisible()


def test_todo_checkbox_uses_the_whole_32px_hit_area(qtbot) -> None:
    checkbox = TodoCheckBox()
    qtbot.addWidget(checkbox)
    checkbox.show()
    edge = QPoint(29, 29)

    qtbot.mouseClick(checkbox, Qt.MouseButton.LeftButton, pos=edge)
    assert checkbox.isChecked()
    qtbot.mouseClick(checkbox, Qt.MouseButton.LeftButton, pos=edge)
    assert not checkbox.isChecked()


def test_clear_confirmation_only_targets_active_type(qtbot, tmp_path) -> None:
    store = QuickNotebookStore(tmp_path / "quick-notebook.json")
    note = store.create_page("note")
    todo = store.create_page("todo")
    window = QuickNotebookWindow(store=store)
    qtbot.addWidget(window)
    window.select_type("note")

    window.confirm_clear_all()

    assert store.page(note.id) is None
    assert store.page(todo.id) is not None
    assert store.trash_count == 1


@pytest.mark.parametrize("field", ["title", "category", "todo", "reminder"])
def test_ime_preedit_hides_placeholder_until_commit_or_cancel(qtbot, tmp_path, field) -> None:
    from PySide6.QtWidgets import QApplication, QPlainTextEdit

    window = QuickNotebookWindow(store=QuickNotebookStore(tmp_path / "book.json"))
    qtbot.addWidget(window)
    if field in {"todo", "reminder"}:
        window.select_type(field)
        list_editor = window.todo_editor if field == "todo" else window.reminder_editor
        list_editor.add_item("")
        editor = list_editor._rows[0].text
    else:
        editor = {"title": window.title_editor, "category": window.category_new_editor}[field]
    window.show()
    editor.setFocus()
    original_hint = editor.placeholderText()
    assert original_hint

    QApplication.sendEvent(editor, QInputMethodEvent("ni'h", []))
    assert editor.placeholderText() == ""
    value = editor.toPlainText() if isinstance(editor, QPlainTextEdit) else editor.text()
    assert value == ""  # 组词内容尚未提交，不能写进便签。
    window.flush_current_page()
    page = window.store.page(window.current_page_id)
    assert page.custom_title is None
    assert page.body == ""
    assert all(item.text == "" for item in (*page.todo_items, *page.reminders))

    QApplication.sendEvent(editor, QInputMethodEvent("", []))
    assert editor.placeholderText() == original_hint
    QApplication.sendEvent(editor, QInputMethodEvent("ni'hao", []))
    assert editor.placeholderText() == ""
    committed = QInputMethodEvent()
    committed.setCommitString("你好")
    QApplication.sendEvent(editor, committed)
    value = editor.toPlainText() if isinstance(editor, QPlainTextEdit) else editor.text()
    assert value == "你好"
    assert editor.placeholderText() == original_hint
    editor.clear()
    assert editor.placeholderText() == original_hint


def test_title_hint_update_during_ime_stays_hidden_and_restores_latest_hint(qtbot, tmp_path) -> None:
    from PySide6.QtWidgets import QApplication

    window = QuickNotebookWindow(store=QuickNotebookStore(tmp_path / "book.json"))
    qtbot.addWidget(window)
    window.show()
    editor = window.title_editor
    editor.setFocus()
    QApplication.sendEvent(editor, QInputMethodEvent("ni", []))
    window.note_editor.setPlainText("新的自动标题")
    assert editor.placeholderText() == ""
    QApplication.sendEvent(editor, QInputMethodEvent("", []))
    assert editor.placeholderText() == "自动命名：新的自动标题"
