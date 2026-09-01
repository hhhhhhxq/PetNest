from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QPoint, QRect, QSize, Qt
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
    assert window.type_tabs[1].width() == 43
    assert window.type_tabs[2].width() == 43
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

    assert window.title_editor.text() == "自动标题"
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
    assert window.tag_editor.width() <= 180


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
    assert window.tag_editor.placeholderText() == "分类标签，如：项目、联系人（最多 5 个）"
    assert window.note_editor.property("seamlessPaper") is True
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
    assert row.due.calendarPopup() is False
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
    assert window.reminder_editor._rows[0].height() <= 86
    assert window.reminder_editor.rows_scroll.viewport().objectName() == "quickNotebookReminderViewport"


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
