from dataclasses import replace
from datetime import datetime, timedelta

import pytest
from PySide6.QtCore import QDateTime, QRect, Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QStyle, QStyleOptionComboBox

from petnest.core.quick_notebook_store import QuickNotebookStore, ReminderItem
from petnest.ui.quick_notebook_window import QuickNotebookWindow


@pytest.fixture
def notebook(qtbot, tmp_path):
    store = QuickNotebookStore(tmp_path / "book.json")
    window = QuickNotebookWindow(store=store)
    qtbot.addWidget(window)
    return window, store


def fail_write():
    raise OSError("simulated disk full")


def test_save_failure_retains_edits_blocks_navigation_and_retries(notebook, monkeypatch):
    window, store = notebook
    window.show()
    original = window.current_page_id
    other = store.create_page("note")
    store.save()
    real_save = store.save
    monkeypatch.setattr(store, "save", fail_write)
    window.note_editor.setPlainText("不能丢的文字")
    assert not window.flush_current_page()
    assert window.save_hint.text() == "保存失败"
    assert window.retry_button.isVisible()
    assert window._dirty
    assert store.page(original).body == ""
    window.show_page(other.id)
    window.select_type("todo")
    window.new_page()
    window.close_notebook()
    assert window.current_page_id == original
    assert window._active_type == "note"
    assert window.isVisible()
    assert window.note_editor.toPlainText() == "不能丢的文字"
    monkeypatch.setattr(store, "save", real_save)
    window.retry_button.click()
    assert not window._dirty
    assert window.save_hint.text() == "已保存到本机"
    loaded = QuickNotebookStore(store.path)
    loaded.load()
    assert loaded.page(original).body == "不能丢的文字"


@pytest.mark.parametrize("operation", ["create", "delete", "clear", "restore"])
def test_failed_store_mutations_roll_back(notebook, monkeypatch, operation):
    _, store = notebook
    page = store.pages("note")[0]
    if operation == "restore":
        store.delete_page(page.id)
    store.save()
    original_ids = store.page_ids("note")
    original_trash = store.trash_count
    before = store.path.read_bytes()
    monkeypatch.setattr(store, "save", fail_write)
    action = {
        "create": lambda: store.create_page("note"),
        "delete": lambda: store.delete_page(page.id),
        "clear": lambda: store.clear_type("note"),
        "restore": lambda: store.restore_page(page.id),
    }[operation]
    with pytest.raises(OSError):
        store.persist(action)
    assert store.page_ids("note") == original_ids
    assert store.trash_count == original_trash
    assert store.path.read_bytes() == before


def test_failed_page_delete_can_be_retried_once(notebook, monkeypatch):
    window, store = notebook
    window.note_editor.setPlainText("保留到回收站")
    window.flush_current_page()
    page_id = window.current_page_id
    real_save = store.save
    monkeypatch.setattr(store, "save", fail_write)
    window.confirm_delete_page(page_id)
    assert store.page(page_id) is not None
    assert store.trash_count == 0
    monkeypatch.setattr(store, "save", real_save)
    window.retry_button.click()
    assert store.page(page_id) is None
    assert store.trash_count == 1


def test_categories_deduplicate_before_limit_and_never_silently_drop(notebook):
    window, store = notebook
    window.tag_editor.setText("工作,工作,生活,项目,学习,其他")
    assert window.flush_current_page()
    assert store.page(window.current_page_id).tags == ("工作", "生活", "项目", "学习", "其他")
    assert window.tag_editor.text() == "工作、生活、项目、学习、其他"
    window.tag_editor.setText("工作,生活,项目,学习,其他,第六个")
    assert not window.flush_current_page()
    assert "已有 6 个" in window.tag_hint.text()
    assert "第六个" in window.tag_editor.text()
    assert len(store.page(window.current_page_id).tags) == 5
    window.tag_editor.setText("工作,第六个")
    assert window.flush_current_page()
    assert store.page(window.current_page_id).tags == ("工作", "第六个")


def test_directory_filters_categories_without_changing_navigation(notebook):
    window, store = notebook
    first = store.pages("note")[0]
    store.update_note(first.id, custom_title=None, body="工作内容", tags=("工作", "项目"))
    second = store.create_page("note")
    store.update_note(second.id, custom_title=None, body="生活内容", tags=("生活",))
    third = store.create_page("note")
    window.open_directory()
    window.category_filter.setCurrentIndex(window.category_filter.findData("工作"))
    assert window.directory_list.count() == 1
    assert window.directory_list.item(0).data(Qt.ItemDataRole.UserRole) == first.id
    row = window.directory_list.itemWidget(window.directory_list.item(0))
    assert "工作" in row.category_label.toolTip()
    assert store.page_ids("note") == (third.id, second.id, first.id)
    window.category_filter.setCurrentIndex(window.category_filter.findData(""))
    assert window.directory_list.count() == 1
    assert window.directory_list.item(0).data(Qt.ItemDataRole.UserRole) == third.id
    window.open_trash()
    assert window.category_filter.isHidden()
    window.open_directory()
    assert not window.category_filter.isHidden()


def test_editing_keeps_page_number_but_directory_shows_recent_first(notebook):
    window, store = notebook
    first = window.current_page_id
    store.create_page("note")
    store.create_page("note")
    window.show_page(first)
    assert window.page_count_label.text() == "3 / 3"
    window.note_editor.setPlainText("编辑第三页")
    window.flush_current_page()
    assert window.page_count_label.text() == "3 / 3"
    window.open_directory()
    assert window.directory_list.item(0).data(Qt.ItemDataRole.UserRole) == first


def test_body_gets_more_space_with_categories_collapsed(notebook, qtbot):
    window, _ = notebook
    window.show()
    qtbot.wait(20)
    assert window.category_panel.isHidden()
    collapsed_height = window.note_editor.height()
    assert collapsed_height >= 150
    window.category_toggle.click()
    qtbot.wait(20)
    assert window.note_editor.height() < collapsed_height
    window.fit_to_available_geometry(QRect(0, 0, 360, 520))
    qtbot.wait(20)
    assert window.note_editor.height() >= 72


@pytest.mark.parametrize("page_type", ["note", "todo", "reminder"])
def test_new_page_reuses_blank_without_discarding_written_pages(notebook, page_type):
    window, store = notebook
    window.select_type(page_type)
    blank_id = window.current_page_id
    for _ in range(4):
        assert window.new_page().id == blank_id
    assert len(store.pages(page_type)) == 1
    window.set_custom_title("有内容的页")
    new_page = window.new_page()
    assert new_page.id != blank_id
    assert store.page(blank_id).custom_title == "有内容的页"
    assert len(store.pages(page_type)) == 2


def test_reminder_needs_valid_content_time_and_explicit_enable(notebook):
    window, store = notebook
    window.select_type("reminder")
    window.reminder_editor.add_item("")
    row = window.reminder_editor._rows[0]
    assert not row.enabled.isChecked()
    row.confirm_time_button.click()
    assert not row.enabled.isChecked()
    assert "内容" in row.validation_label.text()
    row.text.setText("确认提醒")
    row.due.setDateTime(QDateTime.currentDateTime().addSecs(-60))
    row.confirm_time_button.click()
    assert not row.enabled.isChecked()
    assert "未来" in row.validation_label.text()
    row.due.setDateTime(QDateTime.currentDateTime().addSecs(3600))
    assert not row.enabled.isChecked()
    row.confirm_time_button.click()
    assert row.enabled.isChecked()
    window.flush_current_page()
    assert store.page(window.current_page_id).reminders[0].enabled
    row.due.setDateTime(QDateTime.currentDateTime().addSecs(7200))
    assert not row.enabled.isChecked()


@pytest.mark.parametrize("notify", [False, True])
def test_external_reminder_completion_survives_pending_text_edit(notebook, notify):
    window, store = notebook
    window.select_type("reminder")
    window.reminder_editor.add_item("提醒")
    row = window.reminder_editor._rows[0]
    row.confirm_time_button.click()
    window.flush_current_page()
    page_id = window.current_page_id
    row.text.setText("正在修改的内容")
    current = store.page(page_id).reminders[0]
    done = replace(current, completed=True, enabled=False)
    if notify:
        assert window.persist_reminder_change(page_id, done)
        assert row.completed
        assert "已完成" in row.sub_label.text()
    else:
        page = store.page(page_id)
        store.update_page(replace(page, reminders=[done]))
    assert row.text.text() == "正在修改的内容"
    assert window.flush_current_page()
    saved = store.page(page_id).reminders[0]
    assert saved.completed
    assert not saved.enabled
    assert saved.text == "正在修改的内容"


def test_external_repeat_reschedule_and_snooze_survive_edit(notebook):
    window, store = notebook
    window.select_type("reminder")
    window.reminder_editor.add_item("每天提醒")
    window.flush_current_page()
    row = window.reminder_editor._rows[0]
    row.text.setText("更新文字")
    current = store.page(window.current_page_id).reminders[0]
    future = (datetime.now().astimezone() + timedelta(days=2)).replace(microsecond=0).isoformat()
    updated = replace(current, due_at=future, snoozed_until=future, last_triggered_at=current.due_at)
    window.persist_reminder_change(window.current_page_id, updated)
    window.flush_current_page()
    saved = store.page(window.current_page_id).reminders[0]
    assert datetime.fromisoformat(saved.due_at) == datetime.fromisoformat(future)
    assert saved.snoozed_until == future
    assert saved.last_triggered_at == current.due_at


def test_failed_reminder_completion_is_retried_before_editor_save(notebook, monkeypatch):
    window, store = notebook
    window.select_type("reminder")
    window.reminder_editor.add_item("原始提醒")
    row = window.reminder_editor._rows[0]
    row.confirm_time_button.click()
    window.flush_current_page()
    page_id = window.current_page_id
    current = store.page(page_id).reminders[0]
    real_save = store.save
    monkeypatch.setattr(store, "save", fail_write)
    assert not window.persist_reminder_change(page_id, replace(current, enabled=False, completed=True))
    row.text.setText("失败期间仍在编辑")
    assert not window.flush_current_page()
    assert window._pending_reminder_changes
    monkeypatch.setattr(store, "save", real_save)
    assert window.flush_current_page()
    saved = store.page(page_id).reminders[0]
    assert saved.completed and not saved.enabled
    assert saved.text == "失败期间仍在编辑"
    assert not window._pending_reminder_changes


def test_reminder_background_update_does_not_change_selected_type(notebook):
    window, store = notebook
    selected_note = window.current_page_id
    page = store.create_page("reminder")
    item = ReminderItem("r1", "提醒", due_at=(datetime.now().astimezone() + timedelta(hours=1)).isoformat())
    store.update_page(replace(page, reminders=[item]))
    window.show_page(selected_note)
    window.persist_reminder_change(page.id, replace(item, completed=True, enabled=False))
    assert store.last_type == "note"
    assert store.last_page_id_by_type["note"] == selected_note


def test_reminder_enable_button_and_save_retry_fit_narrow_window(notebook, qtbot, monkeypatch):
    window, store = notebook
    window.select_type("reminder")
    window.fit_to_available_geometry(QRect(0, 0, 360, 520))
    window.show()
    window.reminder_editor.add_item("待确认提醒")
    qtbot.wait(20)
    row = window.reminder_editor._rows[0]
    viewport = window.reminder_editor.rows_scroll.viewport()
    assert viewport.rect().contains(row.confirm_time_button.mapTo(viewport, row.confirm_time_button.rect().center()))
    monkeypatch.setattr(store, "save", fail_write)
    assert not window.flush_current_page()
    qtbot.wait(20)
    for widget in (window.retry_button, window.new_button):
        assert window.rect().contains(widget.mapTo(window, widget.rect().bottomRight()))


@pytest.mark.parametrize("field", ["category", "repeat"])
def test_combo_popup_stays_light_and_keyboard_selectable_in_dark_theme(notebook, qtbot, field):
    window, _ = notebook
    original_palette = QApplication.palette()
    dark = QPalette(original_palette)
    dark.setColor(QPalette.ColorRole.Base, QColor("#303030"))
    dark.setColor(QPalette.ColorRole.Window, QColor("#303030"))
    dark.setColor(QPalette.ColorRole.Text, QColor("#EEEEEE"))
    try:
        QApplication.setPalette(dark)
        window.show()
        if field == "category":
            window.open_directory()
            combo = window.category_filter
        else:
            window.select_type("reminder")
            window.reminder_editor.add_item("测试提醒")
            combo = window.reminder_editor._rows[0].repeat
        combo.showPopup()
        qtbot.wait(20)
        view = combo.view()
        assert view.isVisible()
        option = QStyleOptionComboBox()
        combo.initStyleOption(option)
        assert not combo.style().styleHint(QStyle.StyleHint.SH_ComboBox_Popup, option, combo)
        for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive, QPalette.ColorGroup.Disabled):
            assert view.palette().color(group, QPalette.ColorRole.Base).name() == "#fffdfa"
            assert view.palette().color(group, QPalette.ColorRole.Text).name() == "#4b4641"
            assert view.palette().color(group, QPalette.ColorRole.Highlight).name() == "#f2d8c8"
            assert view.palette().color(group, QPalette.ColorRole.HighlightedText).name() == "#4b3226"
        qtbot.keyClick(view, Qt.Key.Key_Down)
        qtbot.keyClick(view, Qt.Key.Key_Return)
        assert combo.currentIndex() == 1
        assert not view.isVisible()
        assert window.isVisible()
    finally:
        QApplication.setPalette(original_palette)
