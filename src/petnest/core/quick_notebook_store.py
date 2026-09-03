"""便签本页面模型与本地原子 JSON 存储。"""

from __future__ import annotations

import json
import os
import shutil
import uuid
from collections.abc import Callable, Iterable, Sequence
from copy import deepcopy
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal


PageType = Literal["note", "todo", "reminder"]
PAGE_TYPES: tuple[PageType, ...] = ("note", "todo", "reminder")
SCHEMA_VERSION = 1
TRASH_RETENTION = timedelta(days=7)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def _identifier() -> str:
    return uuid.uuid4().hex


@dataclass(slots=True)
class TodoItem:
    id: str
    text: str
    completed: bool = False
    created_at: str = ""
    completed_at: str | None = None


@dataclass(slots=True)
class ReminderItem:
    id: str
    text: str
    due_at: str | None = None
    repeat: str = "once"
    weekdays: tuple[int, ...] = ()
    enabled: bool = True
    completed: bool = False
    snoozed_until: str | None = None
    last_triggered_at: str | None = None


@dataclass(slots=True)
class NotebookPage:
    id: str
    type: PageType
    custom_title: str | None
    created_at: str
    updated_at: str
    body: str = ""
    tags: tuple[str, ...] = ()
    todo_items: list[TodoItem] = field(default_factory=list)
    reminders: list[ReminderItem] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        if (self.custom_title or "").strip():
            return False
        if self.type == "note":
            return not self.body.strip() and not any(tag.strip() for tag in self.tags)
        if self.type == "todo":
            return not any(item.text.strip() for item in self.todo_items)
        return not any(item.text.strip() for item in self.reminders)

    @property
    def display_title(self) -> str:
        custom = (self.custom_title or "").strip()
        if custom:
            return custom
        if self.type == "note":
            candidates = self.body.splitlines()
        elif self.type == "todo":
            candidates = [item.text for item in self.todo_items]
        else:
            candidates = [item.text for item in self.reminders]
        first = next((line.strip() for line in candidates if line.strip()), "")
        return first or {
            "note": "无标题便签",
            "todo": "新待办清单",
            "reminder": "新提醒列表",
        }[self.type]

    @classmethod
    def note(cls, custom_title: str | None, body: str, *, now: datetime) -> NotebookPage:
        stamp = _iso(now)
        return cls(_identifier(), "note", custom_title, stamp, stamp, body=body)

    @classmethod
    def todo(
        cls,
        custom_title: str | None,
        items: Iterable[str],
        *,
        now: datetime,
    ) -> NotebookPage:
        stamp = _iso(now)
        todo_items = [TodoItem(_identifier(), text, created_at=stamp) for text in items]
        return cls(_identifier(), "todo", custom_title, stamp, stamp, todo_items=todo_items)

    @classmethod
    def reminder_list(
        cls,
        custom_title: str | None,
        items: Iterable[str],
        *,
        now: datetime,
    ) -> NotebookPage:
        stamp = _iso(now)
        reminders = [ReminderItem(_identifier(), text) for text in items]
        return cls(_identifier(), "reminder", custom_title, stamp, stamp, reminders=reminders)


@dataclass(slots=True)
class TrashEntry:
    page: NotebookPage
    deleted_at: str


class QuickNotebookStore:
    """维护便签页顺序，并通过 replace 原子写入单一 JSON 快照。"""

    def __init__(self, path: Path, *, now: Callable[[], datetime] = _utc_now) -> None:
        self.path = path
        self._now = now
        self.last_type: PageType = "note"
        self.last_page_id_by_type: dict[str, str] = {}
        self._pages: dict[str, NotebookPage] = {}
        self._order: list[str] = []
        self._trash: dict[str, TrashEntry] = {}

    @property
    def trash_count(self) -> int:
        return len(self._trash)

    def trash_entries(self) -> tuple[TrashEntry, ...]:
        return tuple(self._trash.values())

    def load(self) -> None:
        self._reset()
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict) or raw.get("schema_version") != SCHEMA_VERSION:
                raise ValueError("便签本数据版本无效")
            self._load_mapping(raw)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            self._reset()
            self._backup_corrupt_file()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        payload = {
            "schema_version": SCHEMA_VERSION,
            "last_type": self.last_type,
            "last_page_id_by_type": self.last_page_id_by_type,
            "pages": [asdict(self._pages[page_id]) for page_id in self._order],
            "trash": [
                {"page": asdict(entry.page), "deleted_at": entry.deleted_at}
                for entry in self._trash.values()
            ],
        }
        contents = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        try:
            temporary.write_text(contents + "\n", encoding="utf-8")
            with temporary.open("r+", encoding="utf-8") as stream:
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(self.path)
        finally:
            if temporary.exists():
                temporary.unlink()

    def persist(self, change: Callable[[], object]) -> object:
        """写盘成功才保留内存变更；失败可安全重试增删、恢复等操作。"""
        snapshot = deepcopy((self._pages, self._order, self._trash, self.last_type, self.last_page_id_by_type))
        try:
            result = change()
            self.save()
            return result
        except Exception:
            self._pages, self._order, self._trash, self.last_type, self.last_page_id_by_type = snapshot
            raise

    def create_page(self, page_type: PageType) -> NotebookPage:
        if page_type not in PAGE_TYPES:
            raise ValueError(f"不支持的便签页型：{page_type}")
        current = self._now()
        if page_type == "note":
            page = NotebookPage.note(None, "", now=current)
        elif page_type == "todo":
            page = NotebookPage.todo(None, (), now=current)
        else:
            page = NotebookPage.reminder_list(None, (), now=current)
        self._pages[page.id] = page
        self._order.insert(0, page.id)
        self.last_type = page_type
        self.last_page_id_by_type[page_type] = page.id
        return page

    def page(self, page_id: str) -> NotebookPage | None:
        return self._pages.get(page_id)

    def pages(self, page_type: PageType) -> tuple[NotebookPage, ...]:
        return tuple(
            self._pages[page_id]
            for page_id in self._order
            if self._pages[page_id].type == page_type
        )

    def page_ids(self, page_type: PageType) -> tuple[str, ...]:
        return tuple(page.id for page in self.pages(page_type))

    def previous_page(self, page_type: PageType, page_id: str) -> NotebookPage | None:
        ids = self.page_ids(page_type)
        try:
            index = ids.index(page_id)
        except ValueError:
            return None
        return self._pages[ids[index - 1]] if index > 0 else None

    def next_page(self, page_type: PageType, page_id: str) -> NotebookPage | None:
        ids = self.page_ids(page_type)
        try:
            index = ids.index(page_id)
        except ValueError:
            return None
        return self._pages[ids[index + 1]] if index + 1 < len(ids) else None

    def update_page(self, page: NotebookPage) -> NotebookPage:
        if page.id not in self._pages:
            raise KeyError(page.id)
        updated = replace(page, updated_at=_iso(self._now()))
        self._pages[page.id] = updated
        self.last_type = updated.type
        self.last_page_id_by_type[updated.type] = updated.id
        return updated

    def update_note(
        self,
        page_id: str,
        *,
        custom_title: str | None,
        body: str,
        tags: Sequence[str] = (),
    ) -> NotebookPage:
        page = self._required_page(page_id, "note")
        normalized_tags = tuple(dict.fromkeys(tag.strip() for tag in tags if tag.strip()))[:5]
        return self.update_page(
            replace(page, custom_title=custom_title, body=body, tags=normalized_tags)
        )

    def delete_page(self, page_id: str) -> NotebookPage:
        page = self._remove_live_page(page_id)
        self._trash[page_id] = TrashEntry(page, _iso(self._now()))
        return page

    def discard_page(self, page_id: str) -> NotebookPage:
        """永久移除完全空白的页面，不制造无意义的回收站条目。"""
        page = self._pages[page_id]
        if not page.is_empty:
            raise ValueError("只有完全空白的便签页可以直接丢弃")
        return self._remove_live_page(page_id)

    def _remove_live_page(self, page_id: str) -> NotebookPage:
        page = self._pages.pop(page_id)
        self._order.remove(page_id)
        if self.last_page_id_by_type.get(page.type) == page_id:
            remaining = self.page_ids(page.type)
            if remaining:
                self.last_page_id_by_type[page.type] = remaining[0]
            else:
                self.last_page_id_by_type.pop(page.type, None)
        return page

    def clear_all(self) -> None:
        for page_id in tuple(self._order):
            self.delete_page(page_id)

    def clear_type(self, page_type: PageType) -> None:
        for page_id in self.page_ids(page_type):
            self.delete_page(page_id)

    def restore_page(self, page_id: str) -> NotebookPage:
        entry = self._trash.pop(page_id)
        self._pages[page_id] = entry.page
        self._order.insert(0, page_id)
        self.last_type = entry.page.type
        self.last_page_id_by_type[entry.page.type] = page_id
        return entry.page

    def purge_expired_trash(self) -> int:
        current = self._now()
        if current.tzinfo is None:
            current = current.replace(tzinfo=UTC)
        expired = [
            page_id
            for page_id, entry in self._trash.items()
            if current.astimezone(UTC) - datetime.fromisoformat(entry.deleted_at).astimezone(UTC)
            >= TRASH_RETENTION
        ]
        for page_id in expired:
            del self._trash[page_id]
        return len(expired)

    def _required_page(self, page_id: str, page_type: PageType) -> NotebookPage:
        page = self._pages[page_id]
        if page.type != page_type:
            raise ValueError(f"便签页 {page_id} 不是 {page_type}")
        return page

    def _reset(self) -> None:
        self.last_type = "note"
        self.last_page_id_by_type = {}
        self._pages = {}
        self._order = []
        self._trash = {}

    def _load_mapping(self, raw: dict[str, object]) -> None:
        last_type = raw.get("last_type", "note")
        if last_type in PAGE_TYPES:
            self.last_type = last_type  # type: ignore[assignment]
        last_ids = raw.get("last_page_id_by_type", {})
        if isinstance(last_ids, dict):
            self.last_page_id_by_type = {
                str(key): value
                for key, value in last_ids.items()
                if key in PAGE_TYPES and isinstance(value, str)
            }
        pages = raw.get("pages", [])
        if not isinstance(pages, list):
            raise ValueError("便签页列表无效")
        for value in pages:
            page = _page_from_dict(value)
            self._pages[page.id] = page
            self._order.append(page.id)
        trash = raw.get("trash", [])
        if not isinstance(trash, list):
            raise ValueError("回收站列表无效")
        for value in trash:
            if not isinstance(value, dict) or not isinstance(value.get("deleted_at"), str):
                raise ValueError("回收站条目无效")
            deleted_at = value["deleted_at"]
            try:
                deleted_at_value = datetime.fromisoformat(deleted_at)
            except ValueError as error:
                raise ValueError("回收站删除时间无效") from error
            if deleted_at_value.tzinfo is None or deleted_at_value.utcoffset() is None:
                raise ValueError("回收站删除时间必须包含时区")
            page = _page_from_dict(value.get("page"))
            self._trash[page.id] = TrashEntry(page, deleted_at)

    def _backup_corrupt_file(self) -> None:
        if not self.path.exists():
            return
        stamp = self._now().astimezone(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        backup = self.path.with_name(f"{self.path.name}.corrupt-{stamp}.bak")
        try:
            shutil.move(self.path, backup)
        except OSError:
            pass


def _page_from_dict(value: object) -> NotebookPage:
    if not isinstance(value, dict):
        raise ValueError("便签页无效")
    page_type = value.get("type")
    if page_type not in PAGE_TYPES:
        raise ValueError("便签页型无效")
    page_id = value.get("id")
    created_at = value.get("created_at")
    updated_at = value.get("updated_at")
    if not all(isinstance(item, str) for item in (page_id, created_at, updated_at)):
        raise ValueError("便签页标识或时间无效")
    todo_items = value.get("todo_items", [])
    reminders = value.get("reminders", [])
    if not isinstance(todo_items, list) or not isinstance(reminders, list):
        raise ValueError("便签内容无效")
    return NotebookPage(
        id=page_id,  # type: ignore[arg-type]
        type=page_type,  # type: ignore[arg-type]
        custom_title=value.get("custom_title") if isinstance(value.get("custom_title"), str) else None,
        created_at=created_at,  # type: ignore[arg-type]
        updated_at=updated_at,  # type: ignore[arg-type]
        body=value.get("body") if isinstance(value.get("body"), str) else "",
        tags=tuple(item for item in value.get("tags", []) if isinstance(item, str))
        if isinstance(value.get("tags", []), list)
        else (),
        todo_items=[_todo_from_dict(item) for item in todo_items],
        reminders=[_reminder_from_dict(item) for item in reminders],
    )


def _todo_from_dict(value: object) -> TodoItem:
    if not isinstance(value, dict) or not isinstance(value.get("id"), str):
        raise ValueError("待办项无效")
    return TodoItem(
        id=value["id"],
        text=value.get("text") if isinstance(value.get("text"), str) else "",
        completed=bool(value.get("completed", False)),
        created_at=value.get("created_at") if isinstance(value.get("created_at"), str) else "",
        completed_at=value.get("completed_at") if isinstance(value.get("completed_at"), str) else None,
    )


def _reminder_from_dict(value: object) -> ReminderItem:
    if not isinstance(value, dict) or not isinstance(value.get("id"), str):
        raise ValueError("提醒项无效")
    weekdays = value.get("weekdays", [])
    return ReminderItem(
        id=value["id"],
        text=value.get("text") if isinstance(value.get("text"), str) else "",
        due_at=value.get("due_at") if isinstance(value.get("due_at"), str) else None,
        repeat=value.get("repeat") if value.get("repeat") in {"once", "daily", "weekly"} else "once",
        weekdays=tuple(day for day in weekdays if isinstance(day, int) and 0 <= day <= 6)
        if isinstance(weekdays, list)
        else (),
        enabled=bool(value.get("enabled", True)),
        completed=bool(value.get("completed", False)),
        snoozed_until=value.get("snoozed_until") if isinstance(value.get("snoozed_until"), str) else None,
        last_triggered_at=value.get("last_triggered_at")
        if isinstance(value.get("last_triggered_at"), str)
        else None,
    )


__all__ = [
    "NotebookPage",
    "PAGE_TYPES",
    "PageType",
    "QuickNotebookStore",
    "ReminderItem",
    "TodoItem",
    "TrashEntry",
]
