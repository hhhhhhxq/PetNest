"""Native browse, detail, adopt, and update page for the PetNest store."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from queue import Empty, Queue
from threading import Event, Thread

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from petnest.core.pet_store_cache import PetStoreDownloadCancelled
from petnest.core.pet_store_catalog import PetStoreCatalog, PetStoreItem
from petnest.core.pet_store_service import (
    PetStoreInstallResult,
    PetStoreLocalConflict,
    PetStoreService,
)
from petnest.core.pet_store_state import PetStoreStatus
from petnest.models.pet_package import PetPackage
from petnest.ui.exchange_page import ExchangePage
from petnest.ui.pet_store_widgets import PetStoreCard, PetStoreIdlePreview


@dataclass(frozen=True, slots=True)
class _TaskResult:
    kind: str
    value: object | None = None
    error: Exception | None = None


class PetStorePage(ExchangePage):
    pet_install_ready = Signal(str, object)

    def __init__(
        self,
        service: PetStoreService,
        parent: QWidget | None = None,
        *,
        run_tasks_inline: bool = False,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self._run_tasks_inline = run_tasks_inline
        self._catalog: PetStoreCatalog | None = None
        self._cards: dict[str, PetStoreCard] = {}
        self._statuses: dict[str, PetStoreStatus] = {}
        self._selected_tag = "全部"
        self._detail_item: PetStoreItem | None = None
        self._pending_install: PetStoreInstallResult | None = None
        self._operation_phase: str | None = None
        self._results: Queue[_TaskResult] = Queue()
        self._worker: Thread | None = None
        self._task_queue: list[tuple[str, Callable[[], object]]] = []
        self._cancel = Event()
        self._cover_queue: list[str] = []
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(100)
        self._poll_timer.timeout.connect(self._poll_results)
        self._build_ui()
        self.set_footer(status="等待加载宠物商店", primary_text="刷新")

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 6, 6, 6)
        self.stack = QStackedWidget(self)
        root.addWidget(self.stack)
        self.home_page = QWidget(self.stack)
        self.detail_page = QWidget(self.stack)
        self.stack.addWidget(self.home_page)
        self.stack.addWidget(self.detail_page)
        self._build_home()
        self._build_detail()

    def _build_home(self) -> None:
        layout = QVBoxLayout(self.home_page)
        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("发现新伙伴", self.home_page)
        title.setObjectName("contentTitle")
        title_box.addWidget(title)
        description = QLabel("挑一只会陪你工作的桌面宠物", self.home_page)
        description.setObjectName("mutedLabel")
        title_box.addWidget(description)
        header.addLayout(title_box)
        header.addStretch(1)
        self.offline_badge = QLabel("离线内容", self.home_page)
        self.offline_badge.setObjectName("selectionBadge")
        self.offline_badge.hide()
        header.addWidget(self.offline_badge)
        self.search_input = QLineEdit(self.home_page)
        self.search_input.setPlaceholderText("搜索宠物、作者或标签")
        self.search_input.setFixedWidth(300)
        self.search_input.textChanged.connect(self._apply_filters)
        header.addWidget(self.search_input)
        layout.addLayout(header)

        self.hero = QFrame(self.home_page)
        self.hero.setObjectName("petStoreHero")
        hero_layout = QHBoxLayout(self.hero)
        hero_copy = QVBoxLayout()
        featured_label = QLabel("精选推荐", self.hero)
        featured_label.setObjectName("accentValue")
        hero_copy.addWidget(featured_label)
        self.hero_name = QLabel("", self.hero)
        self.hero_name.setObjectName("pageTitle")
        hero_copy.addWidget(self.hero_name)
        self.hero_summary = QLabel("", self.hero)
        self.hero_summary.setWordWrap(True)
        hero_copy.addWidget(self.hero_summary)
        hero_layout.addLayout(hero_copy, 1)
        self.hero_button = QPushButton("查看详情", self.hero)
        self.hero_button.setObjectName("petStoreHeroButton")
        self.hero_button.clicked.connect(self._open_featured)
        hero_layout.addWidget(self.hero_button)
        self.hero.hide()
        layout.addWidget(self.hero)

        self.tags_widget = QWidget(self.home_page)
        self.tags_layout = QHBoxLayout(self.tags_widget)
        self.tags_layout.setContentsMargins(0, 4, 0, 4)
        self.tags_layout.addStretch(1)
        layout.addWidget(self.tags_widget)

        self.scroll = QScrollArea(self.home_page)
        self.scroll.setWidgetResizable(True)
        self.scroll_content = QWidget(self.scroll)
        self.scroll_content.setObjectName("petStoreScrollContent")
        self.cards_layout = QGridLayout(self.scroll_content)
        self.cards_layout.setContentsMargins(0, 0, 6, 0)
        self.cards_layout.setSpacing(12)
        self.cards_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        for column in range(3):
            self.cards_layout.setColumnStretch(column, 1)
        self.scroll.setWidget(self.scroll_content)
        self.scroll.verticalScrollBar().valueChanged.connect(self._request_visible_covers)
        layout.addWidget(self.scroll, 1)

    def _build_detail(self) -> None:
        layout = QVBoxLayout(self.detail_page)
        self.back_button = QPushButton("← 返回宠物商店", self.detail_page)
        self.back_button.clicked.connect(self._show_home)
        layout.addWidget(self.back_button, 0, Qt.AlignmentFlag.AlignLeft)
        body = QHBoxLayout()
        self.preview = PetStoreIdlePreview(self.detail_page)
        body.addWidget(self.preview, 5)
        copy = QVBoxLayout()
        self.detail_badge = QLabel("", self.detail_page)
        self.detail_badge.setObjectName("petStoreBadge")
        copy.addWidget(self.detail_badge, 0, Qt.AlignmentFlag.AlignLeft)
        self.detail_name = QLabel("", self.detail_page)
        self.detail_name.setObjectName("contentTitle")
        copy.addWidget(self.detail_name)
        self.detail_author = QLabel("", self.detail_page)
        self.detail_author.setObjectName("mutedLabel")
        copy.addWidget(self.detail_author)
        self.detail_summary = QLabel("", self.detail_page)
        self.detail_summary.setWordWrap(True)
        copy.addWidget(self.detail_summary)
        self.detail_tags = QLabel("", self.detail_page)
        self.detail_tags.setWordWrap(True)
        copy.addWidget(self.detail_tags)
        self.detail_facts = QLabel("", self.detail_page)
        self.detail_facts.setObjectName("mutedLabel")
        self.detail_facts.setWordWrap(True)
        copy.addWidget(self.detail_facts)
        self.detail_capabilities = QLabel("", self.detail_page)
        self.detail_capabilities.setWordWrap(True)
        copy.addWidget(self.detail_capabilities)
        copy.addStretch(1)
        body.addLayout(copy, 6)
        layout.addLayout(body, 1)

    def activate(self) -> None:
        if self._catalog is None:
            self._load_catalog()
        else:
            self.refresh_statuses()

    def _load_catalog(self) -> None:
        self.set_footer(status="正在加载宠物商店…", primary_text="刷新", primary_enabled=False)
        self._start_task("catalog", self.service.load_catalog)

    def refresh_catalog(self) -> None:
        self._load_catalog()

    def show_detail(self, pet_id: str) -> None:
        if self._catalog is None:
            return
        item = self._catalog.pet(pet_id)
        if item is None:
            return
        self.preview.stop()
        self.preview.frame_label.setText("预览加载中…")
        self._detail_item = item
        self.stack.setCurrentWidget(self.detail_page)
        self.detail_name.setText(item.name)
        self.detail_author.setText(f"由 {item.author} 提供")
        self.detail_summary.setText(item.summary)
        self.detail_tags.setText(" · ".join(item.tags))
        self.detail_facts.setText(
            f"{item.action_count} 个动作  ·  {_format_bytes(self.service.package_for(item).size)}  ·  "
            f"更新于 {item.updated_at.astimezone().strftime('%Y-%m-%d')}"
        )
        self.detail_capabilities.setText(_capability_text(item.capabilities))
        self._sync_detail_status()
        self._start_task(
            "preview",
            lambda: (item.identifier, self.service.load_media(item.idle_preview.file)),
        )

    def _show_home(self) -> None:
        self.preview.stop()
        self._detail_item = None
        self.stack.setCurrentWidget(self.home_page)
        self.set_footer(status=self._home_status(), primary_text="刷新")

    def _open_featured(self) -> None:
        if self._catalog is not None and self._catalog.featured_pet_id is not None:
            self.show_detail(self._catalog.featured_pet_id)

    def refresh_packages(
        self, _packages: Sequence[PetPackage], _current_pet_id: str
    ) -> None:
        self.refresh_statuses()

    def refresh_statuses(self) -> None:
        if self._catalog is None:
            return
        self._statuses = {item.identifier: self.service.status_for(item) for item in self._catalog.pets}
        for pet_id, card in self._cards.items():
            card.set_store_status(self._statuses[pet_id])
        self._apply_filters()
        self._sync_detail_status()

    def select_tag(self, tag: str) -> None:
        self._selected_tag = tag
        for index in range(self.tags_layout.count()):
            widget = self.tags_layout.itemAt(index).widget()
            if isinstance(widget, QPushButton):
                widget.setChecked(widget.text() == tag)
        self._apply_filters()

    def visible_pet_ids(self) -> list[str]:
        if self._catalog is None:
            return []
        return [item.identifier for item in self._catalog.pets if not self._cards[item.identifier].isHidden()]

    def trigger_primary(self) -> None:
        if self.stack.currentWidget() is self.home_page:
            self._load_catalog()
            return
        item = self._detail_item
        if item is None or self._operation_phase is not None:
            return
        status = self._statuses.get(item.identifier, self.service.status_for(item))
        if status in {PetStoreStatus.ADOPTED}:
            return
        self._begin_install(allow_local_replace=False)

    def trigger_secondary(self) -> None:
        if self._operation_phase == "installing":
            self._cancel.set()
            self.set_footer(status="正在取消下载…", primary_text="取消中", primary_enabled=False)

    def _begin_install(self, *, allow_local_replace: bool) -> None:
        item = self._detail_item
        if item is None:
            return
        self._cancel = Event()
        self._operation_phase = "installing"
        self.set_footer(
            status=f"准备下载 {item.name}…",
            primary_text="处理中",
            primary_enabled=False,
            secondary_text="取消",
        )

        def install() -> PetStoreInstallResult:
            return self.service.install(
                item,
                allow_local_replace=allow_local_replace,
                progress=lambda current, total: self._results.put(
                    _TaskResult("progress", (current, total))
                ),
                cancel=self._cancel,
            )

        self._start_task("install", install)

    def complete_install(self, message: str) -> None:
        if self._pending_install is None:
            return
        self.service.confirm_install(self._pending_install)
        self._pending_install = None
        self._operation_phase = None
        self.refresh_statuses()
        self._sync_detail_status(status_override=message)

    def complete_install_failure(self, message: str) -> None:
        self._pending_install = None
        self._operation_phase = None
        self.refresh_statuses()
        self._sync_detail_status(status_override=message)

    def request_leave(self) -> bool:
        return True

    def request_close(self) -> bool:
        if self._operation_phase == "installing":
            answer = QMessageBox.question(
                self,
                "下载尚未完成",
                "要取消当前下载吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer == QMessageBox.StandardButton.Yes:
                self._cancel.set()
            return False
        if self._operation_phase == "awaiting_runtime":
            QMessageBox.information(self, "正在安装", "安装完成或回滚后才能关闭窗口。")
            return False
        return True

    def deactivate(self) -> None:
        self.preview.stop()

    def _start_task(self, kind: str, operation: Callable[[], object]) -> None:
        if self._run_tasks_inline:
            try:
                value = operation()
            except Exception as error:  # noqa: BLE001 - routed to the GUI error state.
                self._handle_result(_TaskResult(kind, error=error))
            else:
                self._handle_result(_TaskResult(kind, value=value))
            return
        if self._worker is not None and self._worker.is_alive():
            self._task_queue.append((kind, operation))
            return

        def run() -> None:
            try:
                value = operation()
            except Exception as error:  # noqa: BLE001 - worker errors are displayed in the GUI.
                self._results.put(_TaskResult(kind, error=error))
            else:
                self._results.put(_TaskResult(kind, value=value))

        self._worker = Thread(target=run, name=f"petnest-store-{kind}", daemon=True)
        self._worker.start()
        self._poll_timer.start()

    def _poll_results(self) -> None:
        handled = False
        while True:
            try:
                result = self._results.get_nowait()
            except Empty:
                break
            handled = True
            self._handle_result(result)
        if handled and (self._worker is None or not self._worker.is_alive()):
            self._poll_timer.stop()
            self._worker = None
            if self._task_queue:
                kind, operation = self._task_queue.pop(0)
                self._start_task(kind, operation)
            else:
                self._start_next_cover()

    def _handle_result(self, result: _TaskResult) -> None:
        if result.kind == "progress" and isinstance(result.value, tuple):
            current, total = result.value
            percent = round(current / total * 100) if total else 0
            self.set_footer(
                status=f"正在下载 {_format_bytes(current)} / {_format_bytes(total)}（{percent}%）",
                primary_text="处理中",
                primary_enabled=False,
                secondary_text="取消",
            )
            return
        if result.error is not None:
            self._handle_task_error(result.kind, result.error)
            return
        if result.kind == "catalog":
            loaded = result.value
            self._catalog = loaded.catalog  # type: ignore[union-attr]
            self.offline_badge.setVisible(bool(loaded.offline))  # type: ignore[union-attr]
            self._render_catalog()
            return
        if result.kind == "cover" and isinstance(result.value, tuple):
            pet_id, path = result.value
            card = self._cards.get(pet_id)
            if card is not None:
                card.set_cover(path)
            return
        if result.kind == "preview" and isinstance(result.value, tuple):
            pet_id, path = result.value
            if self._detail_item is not None and pet_id == self._detail_item.identifier:
                preview = self._detail_item.idle_preview
                self.preview.load_strip(
                    path,
                    frame_width=preview.frame_width,
                    frame_height=preview.frame_height,
                    durations_ms=preview.frame_durations_ms,
                )
            return
        if result.kind == "install" and isinstance(result.value, PetStoreInstallResult):
            self._pending_install = result.value
            self._operation_phase = "awaiting_runtime"
            self.set_footer(status="宠物包已校验，正在应用…", primary_text="安装中", primary_enabled=False)
            self.pet_install_ready.emit(result.value.item.identifier, result.value)

    def _handle_task_error(self, kind: str, error: Exception) -> None:
        if kind == "install" and isinstance(error, PetStoreLocalConflict):
            self._operation_phase = None
            answer = QMessageBox.question(
                self,
                "本地已有同名宠物",
                "本地已有同 ID 宠物。继续会先备份，再用商店内容替换。是否继续？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer == QMessageBox.StandardButton.Yes:
                self._begin_install(allow_local_replace=True)
            else:
                self._sync_detail_status(status_override="已取消更新本地同名宠物")
            return
        if isinstance(error, PetStoreDownloadCancelled):
            message = "下载已取消"
        else:
            message = f"商店操作失败：{error}"
        if kind == "catalog" and self._catalog is None:
            self.set_footer(status=message, primary_text="重试")
            return
        if kind == "preview":
            self.preview.stop()
            self.preview.frame_label.setText("动画预览暂时无法加载")
            return
        if kind == "cover":
            return
        self._pending_install = None
        self._operation_phase = None
        self._sync_detail_status(status_override=message)

    def _render_catalog(self) -> None:
        assert self._catalog is not None
        detail_id = (
            self._detail_item.identifier
            if self._detail_item is not None
            and self.stack.currentWidget() is self.detail_page
            else None
        )
        self._clear_cards()
        featured = self._catalog.featured_pet
        if featured is not None:
            self.hero_name.setText(featured.name)
            self.hero_summary.setText(featured.summary)
            self.hero.show()
        else:
            self.hero.hide()
        for index, item in enumerate(self._catalog.pets):
            card = PetStoreCard(
                item,
                self.scroll_content,
                package_size=self.service.package_for(item).size,
            )
            card.selected.connect(self.show_detail)
            card.cover_requested.connect(self._queue_cover)
            self.cards_layout.addWidget(card, index // 3, index % 3)
            self._cards[item.identifier] = card
        self._render_tags()
        self.refresh_statuses()
        if detail_id is not None and self._catalog.pet(detail_id) is not None:
            self.show_detail(detail_id)
        else:
            self.set_footer(status=self._home_status(), primary_text="刷新")
        QTimer.singleShot(0, self._request_visible_covers)

    def _render_tags(self) -> None:
        while self.tags_layout.count():
            child = self.tags_layout.takeAt(0)
            widget = child.widget()
            if widget is not None:
                widget.deleteLater()
        tags = ["全部"]
        assert self._catalog is not None
        tags.extend(sorted({tag for item in self._catalog.pets for tag in item.tags}))
        tags.append("已领养")
        for tag in tags:
            button = QPushButton(tag, self.tags_widget)
            button.setObjectName("petStoreChip")
            button.setCheckable(True)
            button.setChecked(tag == self._selected_tag)
            button.clicked.connect(lambda _checked=False, selected=tag: self.select_tag(selected))
            self.tags_layout.addWidget(button)
        self.tags_layout.addStretch(1)

    def _clear_cards(self) -> None:
        while self.cards_layout.count():
            child = self.cards_layout.takeAt(0)
            widget = child.widget()
            if widget is not None:
                widget.deleteLater()
        self._cards.clear()
        self._cover_queue.clear()

    def _apply_filters(self) -> None:
        if self._catalog is None:
            return
        query = self.search_input.text().strip().casefold()
        visible_cards: list[PetStoreCard] = []
        for item in self._catalog.pets:
            matches_text = not query or query in " ".join(
                (item.name, item.author, *item.tags)
            ).casefold()
            if self._selected_tag == "全部":
                matches_tag = True
            elif self._selected_tag == "已领养":
                matches_tag = self._statuses.get(item.identifier) in {
                    PetStoreStatus.LOCAL_EXISTING,
                    PetStoreStatus.ADOPTED,
                    PetStoreStatus.UPDATE_AVAILABLE,
                }
            else:
                matches_tag = self._selected_tag in item.tags
            card = self._cards[item.identifier]
            self.cards_layout.removeWidget(card)
            visible = matches_text and matches_tag
            card.setVisible(visible)
            if visible:
                visible_cards.append(card)
        for index, card in enumerate(visible_cards):
            self.cards_layout.addWidget(card, index // 3, index % 3)
        QTimer.singleShot(0, self._request_visible_covers)

    def _request_visible_covers(self) -> None:
        viewport = self.scroll.viewport()
        for card in self._cards.values():
            card.request_cover_if_visible(viewport)

    def _queue_cover(self, pet_id: str) -> None:
        if pet_id not in self._cover_queue:
            self._cover_queue.append(pet_id)
        self._start_next_cover()

    def _start_next_cover(self) -> None:
        if not self._cover_queue or (self._worker is not None and self._worker.is_alive()):
            return
        pet_id = self._cover_queue.pop(0)
        if self._catalog is None:
            return
        item = self._catalog.pet(pet_id)
        if item is not None:
            self._start_task(
                "cover", lambda: (pet_id, self.service.load_media(item.cover))
            )

    def _sync_detail_status(self, *, status_override: str | None = None) -> None:
        item = self._detail_item
        if item is None:
            return
        status = self._statuses.get(item.identifier, self.service.status_for(item))
        labels = {
            PetStoreStatus.NOT_ADOPTED: "",
            PetStoreStatus.LOCAL_EXISTING: "本地已有",
            PetStoreStatus.ADOPTED: "已领养",
            PetStoreStatus.UPDATE_AVAILABLE: "可更新",
        }
        self.detail_badge.setText(labels[status])
        self.detail_badge.setVisible(bool(labels[status]))
        if status is PetStoreStatus.ADOPTED:
            message, primary, enabled = "当前安装内容与商店一致", "已领养", False
        elif status is PetStoreStatus.UPDATE_AVAILABLE:
            message, primary, enabled = "商店内容有更新", "更新", True
        elif status is PetStoreStatus.LOCAL_EXISTING:
            message, primary, enabled = "本地已有同 ID 宠物，更新前会要求确认", "更新", True
        else:
            message, primary, enabled = (
                f"下载大小 {_format_bytes(self.service.package_for(item).size)}",
                "领养",
                True,
            )
        self.set_footer(
            status=status_override or message,
            primary_text=primary,
            primary_enabled=enabled,
        )

    def _home_status(self) -> str:
        if self._catalog is None:
            return "尚未加载宠物商店"
        prefix = "离线内容 · " if self.offline_badge.isVisible() else ""
        return f"{prefix}共 {len(self._catalog.pets)} 只伙伴"


def _format_bytes(size: int) -> str:
    value = float(size)
    for suffix in ("B", "KB", "MB", "GB"):
        if value < 1024 or suffix == "GB":
            return f"{value:.0f} {suffix}" if suffix == "B" else f"{value:.1f} {suffix}"
        value /= 1024
    return f"{size} B"


def _capability_text(capabilities: tuple[str, ...]) -> str:
    names = {
        "click": "响应点击",
        "hover": "响应悬停",
        "drag": "支持拖动",
        "agent_status": "响应任务状态",
        "sleep": "会休息",
        "work_finish": "支持下班提醒",
    }
    values = [names[value] for value in capabilities if value in names]
    return " · ".join(values) if values else "包含基础桌宠动画"


__all__ = ["PetStorePage"]
