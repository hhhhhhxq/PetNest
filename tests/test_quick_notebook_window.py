from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtGui import QInputMethodEvent
from PySide6.QtWidgets import QWidget

from petnest.core.quick_notebook_store import ReminderItem, QuickNotebookStore, TodoItem
from petnest.ui.quick_notebook_window import QuickNotebookWindow, TodoCheckBox, place_notebook


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
    assert window.type_tabs[0].width() == 88
    assert window.type_tabs[1].width() == 88
    assert window.type_tabs[2].width() == 88
    assert [tab.text() for tab in window.type_tabs] == ["便签", "待办", "提醒"]
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


def test_tabs_share_the_paper_edge_without_entering_content(qtbot, tmp_path) -> None:
    window = QuickNotebookWindow(store=QuickNotebookStore(tmp_path / "quick-notebook.json"))
    qtbot.addWidget(window)
    window.resize(window.sizeHint())
    window.show()
    qtbot.waitExposed(window)

    paper_left = window.body_frame.geometry().left()
    assert [button.geometry().right() - paper_left for button in window.type_tabs] == [0, 0, 0]


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
    assert window.tag_editor.width() == window.note_editor.width()


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
    assert window.tag_editor.placeholderText() == "例如：工作，生活"
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


@pytest.mark.parametrize("page_type,button_text", [("note", "＋ 新建便签"), ("todo", "＋ 新建清单"), ("reminder", "＋ 新建提醒页")])
def test_navigation_explains_page_scope_and_fits_small_screen(qtbot, tmp_path, page_type, button_text) -> None:
    window = QuickNotebookWindow(store=QuickNotebookStore(tmp_path / "book.json"))
    qtbot.addWidget(window)
    window.select_type(page_type)
    window.fit_to_available_geometry(QRect(0, 0, 360, 520))
    window.show()
    qtbot.waitExposed(window)

    assert window.new_button.text() == button_text
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


def test_note_field_labels_remain_visible_after_typing(qtbot, tmp_path) -> None:
    window = QuickNotebookWindow(store=QuickNotebookStore(tmp_path / "book.json"))
    qtbot.addWidget(window)
    window.show()
    window.set_custom_title("项目记录")
    window.note_editor.setPlainText("今天的讨论要点")
    window.tag_editor.setText("工作，项目")
    qtbot.wait(20)

    for label, editor in ((window.title_label, window.title_editor), (window.body_label, window.note_editor), (window.tag_label, window.tag_editor)):
        assert label.isVisible()
        assert label.buddy() is editor
        assert label.mapTo(window, label.rect().bottomLeft()).y() < editor.mapTo(window, QPoint()).y()
    assert window.title_label.text() == "标题（选填）"
    assert window.tag_label.text() == "分类（选填）"
    assert window.tag_editor.accessibleName() == "分类（选填，最多 5 个）"
    assert window.tag_editor.toolTip() == "最多 5 个分类，例如：工作、生活"
    assert window.tag_hint.isVisible()
    assert window.tag_hint.text() == "多个分类用逗号分隔，最多 5 个"


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

    for widget in (window.title_label, window.title_editor, window.body_label, window.note_editor, window.tag_label, window.tag_editor, window.tag_hint):
        rect = QRect(widget.mapTo(window, QPoint()), widget.size())
        assert window.rect().contains(rect)
        assert rect.bottom() < window.footer.mapTo(window, QPoint()).y()
    assert window.tag_editor.width() == window.note_editor.width()
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


@pytest.mark.parametrize("field", ["title", "note", "tag", "todo", "reminder"])
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
        editor = {"title": window.title_editor, "note": window.note_editor, "tag": window.tag_editor}[field]
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
