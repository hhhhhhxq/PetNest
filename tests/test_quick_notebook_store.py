from __future__ import annotations

import json
from datetime import UTC, datetime

from petnest.core.quick_notebook_store import NotebookPage, QuickNotebookStore


NOW = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)


def test_display_title_prefers_custom_title_then_content() -> None:
    assert NotebookPage.note("给小林", "正文第一行\n第二行", now=NOW).display_title == "给小林"
    assert NotebookPage.note(None, "正文第一行\n第二行", now=NOW).display_title == "正文第一行"
    assert NotebookPage.todo(None, ["", "确认侧页签"], now=NOW).display_title == "确认侧页签"
    assert NotebookPage.reminder_list(None, ["", "周五交周报"], now=NOW).display_title == "周五交周报"


def test_empty_types_have_stable_fallback_titles() -> None:
    assert NotebookPage.note(None, "", now=NOW).display_title == "无标题便签"
    assert NotebookPage.todo(None, [], now=NOW).display_title == "新待办清单"
    assert NotebookPage.reminder_list(None, [], now=NOW).display_title == "新提醒列表"


def test_store_round_trips_and_scopes_navigation_by_type(tmp_path) -> None:
    path = tmp_path / "quick-notebook.json"
    store = QuickNotebookStore(path, now=lambda: NOW)
    first = store.create_page("note")
    second = store.create_page("note")
    todo = store.create_page("todo")
    store.last_type = "todo"
    store.last_page_id_by_type["note"] = second.id
    store.save()

    assert path.exists()
    assert not path.with_suffix(".json.tmp").exists()

    loaded = QuickNotebookStore(path, now=lambda: NOW)
    loaded.load()

    assert loaded.page_ids("note") == (second.id, first.id)
    assert loaded.page_ids("todo") == (todo.id,)
    assert loaded.next_page("note", first.id) is None
    assert loaded.previous_page("note", first.id).id == second.id
    assert loaded.last_type == "todo"
    assert loaded.last_page_id_by_type["note"] == second.id


def test_delete_clear_restore_and_expiry_are_recoverable(tmp_path) -> None:
    current = [NOW]
    store = QuickNotebookStore(tmp_path / "quick-notebook.json", now=lambda: current[0])
    note = store.create_page("note")
    store.create_page("todo")

    store.delete_page(note.id)
    assert store.trash_count == 1
    assert store.restore_page(note.id).id == note.id

    store.clear_all()
    assert store.trash_count == 2
    assert store.page_ids("note") == ()
    assert store.page_ids("todo") == ()

    current[0] = datetime(2026, 9, 9, tzinfo=UTC)
    assert store.purge_expired_trash() == 2
    assert store.trash_count == 0


def test_update_page_moves_it_to_front_without_crossing_types(tmp_path) -> None:
    current = [NOW]
    store = QuickNotebookStore(tmp_path / "quick-notebook.json", now=lambda: current[0])
    first = store.create_page("note")
    second = store.create_page("note")
    todo = store.create_page("todo")
    current[0] = datetime(2026, 9, 1, 11, 0, tzinfo=UTC)

    store.update_note(first.id, custom_title=None, body="新的第一行", tags=("项目",))

    assert store.page_ids("note") == (first.id, second.id)
    assert store.page_ids("todo") == (todo.id,)
    assert store.page(first.id).display_title == "新的第一行"
    assert store.page(first.id).tags == ("项目",)


def test_corrupt_file_is_backed_up_and_does_not_overwrite_source(tmp_path) -> None:
    path = tmp_path / "quick-notebook.json"
    path.write_text("{broken", encoding="utf-8")
    store = QuickNotebookStore(path, now=lambda: NOW)

    store.load()

    assert store.page_ids("note") == ()
    backups = list(tmp_path.glob("quick-notebook.json.corrupt-*.bak"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == "{broken"


def test_invalid_trash_timestamp_is_rejected_during_load(tmp_path) -> None:
    path = tmp_path / "quick-notebook.json"
    original = QuickNotebookStore(path, now=lambda: NOW)
    page = original.create_page("note")
    original.delete_page(page.id)
    original.save()
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["trash"][0]["deleted_at"] = "not-a-date"
    path.write_text(json.dumps(payload), encoding="utf-8")
    loaded = QuickNotebookStore(path, now=lambda: NOW)

    loaded.load()

    assert loaded.trash_count == 0
    assert loaded.purge_expired_trash() == 0
    backups = list(tmp_path.glob("quick-notebook.json.corrupt-*.bak"))
    assert len(backups) == 1


def test_page_empty_state_ignores_blank_default_rows() -> None:
    assert NotebookPage.note(None, "   \n", now=NOW).is_empty
    assert NotebookPage.todo(None, ["  "], now=NOW).is_empty
    assert NotebookPage.reminder_list(None, ["  "], now=NOW).is_empty
    assert not NotebookPage.note("自定义标题", "", now=NOW).is_empty
    assert not NotebookPage.note(None, "正文", now=NOW).is_empty


def test_clear_type_only_moves_matching_pages_to_trash(tmp_path) -> None:
    store = QuickNotebookStore(tmp_path / "quick-notebook.json", now=lambda: NOW)
    note = store.create_page("note")
    todo = store.create_page("todo")

    store.clear_type("note")

    assert store.page(note.id) is None
    assert store.page(todo.id) is not None
    assert store.trash_count == 1
