"""Codex weekly quota and per-computer token dashboard."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from queue import Empty, Queue
from threading import Thread
from typing import Callable

from PySide6.QtCore import QSize, QTimer, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from petnest.core.codex_usage import (
    CodexAccountSnapshot,
    CodexDeviceUsageStore,
    CodexModelUsage,
    CodexRateLimit,
    CodexRateWindow,
    CodexTokenUsage,
    CodexUsageClient,
    CodexUsageHistoryStore,
    CodexUsageReport,
    codex_device_usage_path,
)
from petnest.ui.theme import dialog_stylesheet


ClientFactory = Callable[[], CodexUsageClient]
ReportCallback = Callable[[CodexUsageReport], object]


class CodexUsageDialog(QDialog):
    """Display the signed-in Codex account without reading its auth file."""

    def __init__(
        self,
        history_path: Path,
        parent: QWidget | None = None,
        *,
        client_factory: ClientFactory = CodexUsageClient,
        auto_refresh: bool = True,
        device_id: str = "",
        device_label: str = "",
        on_connect_device: Callable[[], object] | None = None,
        on_report: ReportCallback | None = None,
    ) -> None:
        super().__init__(
            parent,
            Qt.WindowType.Window
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowSystemMenuHint
            | Qt.WindowType.WindowMinMaxButtonsHint
            | Qt.WindowType.WindowCloseButtonHint,
        )
        self.setWindowModality(Qt.WindowModality.NonModal)
        self._history = CodexUsageHistoryStore(history_path)
        self._device_history = CodexDeviceUsageStore(codex_device_usage_path(history_path))
        self._client_factory = client_factory
        self._device_id = str(device_id)
        self._device_label = str(device_label).strip() or "当前电脑"
        self._on_connect_device = on_connect_device
        self._on_report = on_report
        self._results: Queue[tuple[str, object]] = Queue()
        self._worker: Thread | None = None
        self._live_report: CodexUsageReport | None = None
        self._cycle_snapshots: dict[str, CodexAccountSnapshot] = {}
        self._remote_cycles: dict[str, tuple[CodexDeviceUsageSnapshot, ...]] = {}
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(100)
        self._poll_timer.timeout.connect(self._poll_result)

        self.setObjectName("codexUsageDialog")
        self.setWindowTitle("Codex 用量")
        self.setMinimumSize(820, 650)
        self.resize(920, 730)
        self.setStyleSheet(dialog_stylesheet())

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.content_scroll = QScrollArea(self)
        self.content_scroll.setObjectName("codexUsageScroll")
        self.content_scroll.setWidgetResizable(True)
        self.content_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.content_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget(self.content_scroll)
        content.setObjectName("codexUsageContent")
        root = QVBoxLayout(content)
        root.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        root.setContentsMargins(24, 22, 24, 22)
        root.setSpacing(14)
        self.content_scroll.setWidget(content)
        outer.addWidget(self.content_scroll)

        header = QHBoxLayout()
        titles = QVBoxLayout()
        title = QLabel("Codex 额度与本机 Token", self)
        title.setObjectName("contentTitle")
        subtitle = QLabel(
            "读取当前 ChatGPT/Codex 账号的滚动用量，并从本机 Codex 会话统计 Token。",
            self,
        )
        subtitle.setObjectName("contentDescription")
        subtitle.setWordWrap(True)
        titles.addWidget(title)
        titles.addWidget(subtitle)
        header.addLayout(titles, 1)
        self.connect_device_button = QPushButton("连接电脑…", self)
        self.connect_device_button.clicked.connect(self._connect_device)
        self.connect_device_button.setVisible(on_connect_device is not None)
        header.addWidget(self.connect_device_button, 0, Qt.AlignmentFlag.AlignTop)
        self.refresh_button = QPushButton("刷新", self)
        self.refresh_button.setObjectName("primaryButton")
        self.refresh_button.clicked.connect(self.refresh_usage)
        header.addWidget(self.refresh_button, 0, Qt.AlignmentFlag.AlignTop)
        root.addLayout(header)

        account_card = QFrame(self)
        account_card.setObjectName("surfaceCard")
        account_layout = QHBoxLayout(account_card)
        account_layout.setContentsMargins(18, 14, 18, 14)
        account_label = QLabel("账号", account_card)
        account_label.setStyleSheet("font-weight: 700; color: #4B4641;")
        account_layout.addWidget(account_label)
        self.account_selector = QComboBox(account_card)
        self.account_selector.setMinimumWidth(330)
        self.account_selector.currentIndexChanged.connect(self._show_selected_account)
        account_layout.addWidget(self.account_selector)
        cycle_label = QLabel("周期", account_card)
        cycle_label.setStyleSheet("font-weight: 700; color: #4B4641;")
        account_layout.addWidget(cycle_label)
        self.cycle_selector = QComboBox(account_card)
        self.cycle_selector.setMinimumWidth(235)
        self.cycle_selector.currentIndexChanged.connect(self._show_selected_cycle)
        account_layout.addWidget(self.cycle_selector)
        account_layout.addStretch(1)
        self.current_account_label = QLabel("正在识别…", account_card)
        self.current_account_label.setObjectName("mutedLabel")
        account_layout.addWidget(self.current_account_label)
        root.addWidget(account_card)

        self.status_label = QLabel("尚未读取 Codex 用量。", self)
        self.status_label.setObjectName("mutedLabel")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)
        self.loading_bar = QProgressBar(self)
        self.loading_bar.setRange(0, 0)
        self.loading_bar.setTextVisible(False)
        self.loading_bar.hide()
        root.addWidget(self.loading_bar)

        quota_card, quota_layout = self._card(
            "剩余用量",
            "与 Codex 界面中的 1 周百分比和重置时间采用同一数据源。",
        )
        self.quota_rows = QVBoxLayout()
        self.quota_rows.setSpacing(10)
        quota_layout.addLayout(self.quota_rows)
        root.addWidget(quota_card)

        metrics = QGridLayout()
        metrics.setHorizontalSpacing(14)
        metrics.setVerticalSpacing(14)
        account_tokens_card, account_tokens_layout = self._card(
            "当前账号 Token",
            "账号汇总由 Codex app-server 返回，会随登录账号切换。",
        )
        self.account_lifetime_label = self._metric("累计  —", account_tokens_card)
        self.account_recent_label = QLabel("最近记录  —", account_tokens_card)
        self.account_recent_label.setObjectName("mutedLabel")
        self.account_streak_label = QLabel("连续使用  —", account_tokens_card)
        self.account_streak_label.setObjectName("mutedLabel")
        account_tokens_layout.addWidget(self.account_lifetime_label)
        account_tokens_layout.addWidget(self.account_recent_label)
        account_tokens_layout.addWidget(self.account_streak_label)
        metrics.addWidget(account_tokens_card, 0, 0)

        local_card, local_layout = self._card(
            "当前电脑 · 本周期",
            "按本机 token_count 的额度重置时间关联账号周期；日志不含账号 ID，极近重置时间可能存在歧义。",
        )
        self.local_total_label = self._metric("Token  —", local_card)
        self.local_breakdown_label = QLabel("输入 / 输出 / 缓存  —", local_card)
        self.local_breakdown_label.setObjectName("mutedLabel")
        self.local_breakdown_label.setWordWrap(True)
        self.local_requests_label = QLabel("模型请求  —", local_card)
        self.local_requests_label.setObjectName("mutedLabel")
        self.local_models_label = QLabel("常用模型  —", local_card)
        self.local_models_label.setObjectName("mutedLabel")
        self.local_models_label.setWordWrap(True)
        self.local_speed_label = QLabel("速度占比  —", local_card)
        self.local_speed_label.setObjectName("mutedLabel")
        self.local_speed_label.setToolTip(
            "按本额度周期内实际产生 Token 的模型回合统计：极快对应 priority，"
            "标准对应 default。"
        )
        self.local_scan_label = QLabel("日志匹配  —", local_card)
        self.local_scan_label.setObjectName("mutedLabel")
        self.local_scan_label.setWordWrap(True)
        self.local_quota_change_label = QLabel("账号额度变化  —", local_card)
        self.local_quota_change_label.setObjectName("mutedLabel")
        self.local_quota_change_label.setWordWrap(True)
        self.local_quota_change_label.setToolTip(
            "Codex 只提供账号级额度百分比。这里展示本机请求期间观察到的账号已用额度变化；"
            "若同一账号也在其他电脑使用，无法精确拆分到单台电脑。"
        )
        self.synced_devices_label = QLabel("局域网同步  尚未连接其他电脑", local_card)
        self.synced_devices_label.setObjectName("mutedLabel")
        self.synced_devices_label.setWordWrap(True)
        self.all_devices_total_label = QLabel("多电脑合计  —", local_card)
        self.all_devices_total_label.setStyleSheet("font-weight: 700; color: #4B4641;")
        self.all_devices_total_label.setWordWrap(True)
        self.quota_attribution_label = QLabel("额度归属  —", local_card)
        self.quota_attribution_label.setObjectName("mutedLabel")
        self.quota_attribution_label.setWordWrap(True)
        self.device_ranking_title = QLabel("同账号设备用量排名（预估）", local_card)
        self.device_ranking_title.setStyleSheet("font-weight: 700; color: #4B4641;")
        self.device_ranking_hint = QLabel(
            "设备额度占用按已同步设备 Token 比例折算；未同步设备和无匹配日志的占用无法判断，"
            "不会当作官方单机归因。",
            local_card,
        )
        self.device_ranking_hint.setObjectName("mutedLabel")
        self.device_ranking_hint.setWordWrap(True)
        self.device_ranking_list = QListWidget(local_card)
        self.device_ranking_list.setObjectName("deviceRankingList")
        self.device_ranking_list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.device_ranking_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.device_ranking_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.device_ranking_list.setMinimumHeight(52)
        self.device_ranking_list.setMaximumHeight(338)
        self.device_ranking_list.setStyleSheet(
            "QListWidget#deviceRankingList {"
            "background: #FBF7F2; color: #4B4641; border: 1px solid #E8DED5;"
            "border-radius: 8px; padding: 4px; outline: none;"
            "}"
            "QListWidget#deviceRankingList::item {"
            "background: transparent; color: #4B4641; padding: 5px 6px; border: none;"
            "}"
        )
        local_layout.addWidget(self.local_total_label)
        local_layout.addWidget(self.local_breakdown_label)
        local_layout.addWidget(self.local_requests_label)
        local_layout.addWidget(self.local_models_label)
        local_layout.addWidget(self.local_speed_label)
        local_layout.addWidget(self.local_scan_label)
        local_layout.addWidget(self.local_quota_change_label)
        local_layout.addWidget(self.synced_devices_label)
        local_layout.addWidget(self.all_devices_total_label)
        local_layout.addWidget(self.quota_attribution_label)
        local_layout.addWidget(self.device_ranking_title)
        local_layout.addWidget(self.device_ranking_hint)
        local_layout.addWidget(self.device_ranking_list)
        metrics.addWidget(local_card, 0, 1)
        metrics.setColumnStretch(0, 1)
        metrics.setColumnStretch(1, 1)
        root.addLayout(metrics)

        note = QLabel(
            "说明：设备额度占用按已同步 Token 比例动态估算；由于输入、缓存、输出和模型权重不同，"
            "它不是 Codex 官方的单机精确归因。局域网只交换各账号的脱敏汇总，不传输会话内容和凭据。",
            self,
        )
        note.setObjectName("mutedLabel")
        note.setWordWrap(True)
        root.addWidget(note)
        root.addStretch(1)

        footer = QHBoxLayout()
        footer.addStretch(1)
        close_button = QPushButton("关闭", self)
        close_button.clicked.connect(self.close)
        footer.addWidget(close_button)
        root.addLayout(footer)

        self._reload_account_selector()
        self._show_selected_cycle()
        if auto_refresh:
            QTimer.singleShot(0, self.refresh_usage)

    @staticmethod
    def _card(title: str, description: str) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("surfaceCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(8)
        title_label = QLabel(title, card)
        title_label.setStyleSheet("font-size: 16px; font-weight: 700; color: #4B4641;")
        description_label = QLabel(description, card)
        description_label.setObjectName("mutedLabel")
        description_label.setWordWrap(True)
        layout.addWidget(title_label)
        layout.addWidget(description_label)
        return card, layout

    @staticmethod
    def _metric(text: str, parent: QWidget) -> QLabel:
        label = QLabel(text, parent)
        label.setStyleSheet("font-size: 20px; font-weight: 700; color: #A85D3E;")
        label.setWordWrap(True)
        return label

    def refresh_usage(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            return
        self.refresh_button.setEnabled(False)
        self.loading_bar.show()
        self.status_label.setStyleSheet("")
        self.status_label.setText("正在读取当前 Codex 账号、周额度和本机会话…")
        self._worker = Thread(target=self._fetch_worker, name="petnest-codex-usage", daemon=True)
        self._worker.start()
        self._poll_timer.start()

    def _fetch_worker(self) -> None:
        try:
            report = self._client_factory().fetch_report()
        except Exception as error:  # noqa: BLE001 - pass safe failure to the Qt thread.
            self._results.put(("error", error))
        else:
            self._results.put(("report", report))

    def _poll_result(self) -> None:
        try:
            kind, payload = self._results.get_nowait()
        except Empty:
            return
        self._poll_timer.stop()
        self._worker = None
        self.refresh_button.setEnabled(True)
        self.loading_bar.hide()
        if kind == "error":
            message = str(payload) or payload.__class__.__name__
            self.status_label.setText(f"读取失败：{message}")
            self.status_label.setStyleSheet("color: #B34D3F;")
            return
        if not isinstance(payload, CodexUsageReport):
            self.status_label.setText("读取失败：Codex 用量结果格式无效。")
            self.status_label.setStyleSheet("color: #B34D3F;")
            return
        self._live_report = payload
        try:
            self._history.save_report(payload)
        except (OSError, ValueError) as error:
            history_warning = f"；账号历史未保存：{error}"
        else:
            history_warning = ""
        self._reload_account_selector(current_key=payload.account.key)
        self._show_report(payload)
        if self._on_report is not None:
            try:
                self._on_report(payload)
            except Exception:  # noqa: BLE001 - usage remains visible if LAN sync fails.
                pass
        fetched = payload.fetched_at.astimezone()
        self.status_label.setText(
            f"已更新 · {fetched:%Y-%m-%d %H:%M:%S} · {payload.account.label}{history_warning}"
        )
        self.status_label.setStyleSheet("")

    def _reload_account_selector(
        self,
        *,
        current_key: str | None = None,
        selected_key: str | None = None,
    ) -> None:
        snapshots = self._history.load()
        local_keys = {item.account_key for item in snapshots}
        remote_latest: dict[str, CodexDeviceUsageSnapshot] = {}
        for snapshot in self._device_history.load():
            previous = remote_latest.get(snapshot.account_key)
            if previous is None or snapshot.updated_at > previous.updated_at:
                remote_latest[snapshot.account_key] = snapshot
        self.account_selector.blockSignals(True)
        self.account_selector.clear()
        for snapshot in snapshots:
            current = snapshot.account_key == current_key
            suffix = "（当前）" if current else ""
            self.account_selector.addItem(
                f"{snapshot.account_label} · {_plan_label(snapshot.plan_type)}{suffix}",
                snapshot.account_key,
            )
        for account_key, snapshot in sorted(
            remote_latest.items(),
            key=lambda item: item[1].updated_at,
            reverse=True,
        ):
            if account_key in local_keys:
                continue
            label = snapshot.account_label or f"局域网账号 {account_key[:6]}…"
            plan = f" · {_plan_label(snapshot.plan_type)}" if snapshot.plan_type else ""
            self.account_selector.addItem(f"{label}{plan}（局域网）", account_key)
        if self.account_selector.count() == 0:
            self.account_selector.addItem("尚无账号记录", None)
        preferred_key = selected_key or current_key
        if preferred_key is not None:
            index = self.account_selector.findData(preferred_key)
            if index >= 0:
                self.account_selector.setCurrentIndex(index)
        self.account_selector.blockSignals(False)
        self.account_selector.setEnabled(self.account_selector.currentData() is not None)
        selected_key = self.account_selector.currentData()
        self._reload_cycle_selector(
            selected_key if isinstance(selected_key, str) else None,
            prefer_live=current_key is not None,
        )

    def _show_selected_account(self) -> None:
        key = self.account_selector.currentData()
        if not isinstance(key, str):
            return
        self._reload_cycle_selector(
            key,
            prefer_live=self._live_report is not None and key == self._live_report.account.key,
        )
        self._show_selected_cycle()

    def _reload_cycle_selector(self, account_key: str | None, *, prefer_live: bool) -> None:
        self.cycle_selector.blockSignals(True)
        self.cycle_selector.clear()
        self._cycle_snapshots = {}
        self._remote_cycles = {}
        live_reset: str | None = None
        known_reset_epochs: set[int] = set()
        if (
            account_key is not None
            and self._live_report is not None
            and self._live_report.account.key == account_key
        ):
            window = self._live_report.primary_limit.primary
            live_reset = window.resets_at.isoformat() if window is not None and window.resets_at else None
            if window is not None and window.resets_at is not None:
                known_reset_epochs.add(int(window.resets_at.timestamp()))
            self.cycle_selector.addItem(
                _live_cycle_label(window),
                "__live__",
            )
        if account_key is not None:
            for index, snapshot in enumerate(self._history.load_cycles(account_key)):
                if live_reset is not None and snapshot.resets_at == live_reset:
                    continue
                reset = _parse_snapshot_time(snapshot.resets_at)
                if reset is not None:
                    known_reset_epochs.add(int(reset.timestamp()))
                identifier = f"snapshot:{index}:{snapshot.resets_at or snapshot.updated_at}"
                self._cycle_snapshots[identifier] = snapshot
                self.cycle_selector.addItem(_snapshot_cycle_label(snapshot), identifier)
            remote_by_reset: dict[int, list[CodexDeviceUsageSnapshot]] = {}
            for snapshot in self._device_history.load(
                account_key=account_key,
                exclude_device_id=self._device_id or None,
            ):
                remote_by_reset.setdefault(snapshot.window_resets_at, []).append(snapshot)
            for reset_epoch, devices in sorted(remote_by_reset.items(), reverse=True):
                if any(abs(reset_epoch - known) <= 10 for known in known_reset_epochs):
                    continue
                identifier = f"remote:{reset_epoch}"
                ordered = tuple(sorted(devices, key=lambda item: item.updated_at, reverse=True))
                self._remote_cycles[identifier] = ordered
                reset = datetime.fromtimestamp(reset_epoch, UTC)
                self.cycle_selector.addItem(
                    f"局域网 · {_cycle_range(reset, ordered[0].window_duration_minutes)} · 最后同步",
                    identifier,
                )
        if self.cycle_selector.count() == 0:
            self.cycle_selector.addItem("尚无周期记录", None)
        elif prefer_live:
            live_index = self.cycle_selector.findData("__live__")
            if live_index >= 0:
                self.cycle_selector.setCurrentIndex(live_index)
        self.cycle_selector.setEnabled(self.cycle_selector.currentData() is not None)
        self.cycle_selector.blockSignals(False)

    def _show_selected_cycle(self) -> None:
        identifier = self.cycle_selector.currentData()
        if identifier == "__live__" and self._live_report is not None:
            self._show_report(self._live_report)
            return
        if isinstance(identifier, str):
            snapshot = self._cycle_snapshots.get(identifier)
            if snapshot is not None:
                self._show_snapshot(snapshot)
                return
            devices = self._remote_cycles.get(identifier)
            if devices:
                self._show_remote_cycle(devices)

    def _show_report(self, report: CodexUsageReport) -> None:
        self.current_account_label.setText(
            f"当前登录 · {report.account.label} · {_plan_label(report.account.plan_type)}"
        )
        self._clear_quota_rows()
        for limit in report.rate_limits:
            self._add_limit_rows(limit)
        summary = report.account_tokens
        self.account_lifetime_label.setText(
            "累计  " + (_number(summary.lifetime_tokens) if summary.lifetime_tokens is not None else "—")
        )
        recent_tokens = sum(item.tokens for item in report.daily_usage[-7:])
        self.account_recent_label.setText(
            f"最近 {min(7, len(report.daily_usage))} 个有记录日  {_number(recent_tokens)}"
            if report.daily_usage
            else "最近记录  —"
        )
        self.account_streak_label.setText(
            f"连续使用  {summary.current_streak_days} 天"
            if summary.current_streak_days is not None
            else "连续使用  —"
        )
        local = report.local_usage
        tokens = local.tokens
        self.local_total_label.setText(
            f"Token  {_number(tokens.total_tokens)}"
            if _has_device_usage(local.scan_status, tokens.total_tokens, tokens.requests)
            else "Token  —（未发现当前账号/周期匹配记录）"
        )
        self.local_breakdown_label.setText(
            "输入 / 输出 / 缓存  "
            f"{_number(tokens.input_tokens)} / {_number(tokens.output_tokens)} / "
            f"{_number(tokens.cached_input_tokens)}"
        )
        self.local_requests_label.setText(f"模型请求  {_number(tokens.requests)}")
        self.local_models_label.setText(_model_usage_label(local.model_usage))
        self.local_speed_label.setText(
            "速度占比  " + _speed_usage_label(local.fast_uses, local.standard_uses)
        )
        self.local_scan_label.setText(
            "日志匹配  "
            + _scan_status_label(local.scan_status, local.files_scanned, local.files_skipped)
        )
        change = local.observed_quota_change
        if change is None:
            self.local_quota_change_label.setText("本机记录期间的账号整体额度变化  —")
        else:
            self.local_quota_change_label.setText(
                f"本机记录期间，账号整体已用额度 +{_percent(change)} 个百分点"
                "（非单机归因）"
            )
        window = report.primary_limit.primary
        reset_epoch = int(window.resets_at.timestamp()) if window is not None and window.resets_at else None
        self._show_synced_devices(
            account_key=report.account.key,
            reset_epoch=reset_epoch,
            local_tokens=tokens,
            local_models=local.model_usage,
            local_fast_uses=local.fast_uses,
            local_standard_uses=local.standard_uses,
            local_scan_status=local.scan_status,
            local_files_scanned=local.files_scanned,
            local_files_skipped=local.files_skipped,
            account_used_percent=(window.used_percent if window is not None else None),
        )

    def _show_snapshot(self, snapshot: CodexAccountSnapshot) -> None:
        self.current_account_label.setText(
            f"历史快照 · {snapshot.account_label} · {_plan_label(snapshot.plan_type)}"
        )
        self._clear_quota_rows()
        reset = _parse_snapshot_time(snapshot.resets_at)
        window = CodexRateWindow(
            used_percent=snapshot.used_percent,
            window_duration_minutes=snapshot.window_duration_minutes,
            resets_at=reset,
        )
        self._add_window_row("Codex", window, historical=True)
        self.account_lifetime_label.setText(
            "累计  "
            + (_number(snapshot.account_lifetime_tokens) if snapshot.account_lifetime_tokens is not None else "—")
        )
        self.account_recent_label.setText(f"最后更新  {_format_snapshot_date(snapshot.updated_at)}")
        self.account_streak_label.setText("切换回该账号后可刷新最新数据")
        self.local_total_label.setText(
            f"Token  {_number(snapshot.local_tokens)}"
            if _has_device_usage(
                snapshot.local_scan_status,
                snapshot.local_tokens,
                snapshot.local_requests,
            )
            else "Token  —（无可确认的匹配记录）"
        )
        self.local_breakdown_label.setText(
            "输入 / 输出 / 缓存  "
            f"{_number(snapshot.local_input_tokens)} / {_number(snapshot.local_output_tokens)} / "
            f"{_number(snapshot.local_cached_input_tokens)}"
        )
        self.local_requests_label.setText(f"模型请求  {_number(snapshot.local_requests)}")
        self.local_models_label.setText(_model_usage_label(snapshot.local_model_usage))
        self.local_speed_label.setText(
            "速度占比  "
            + _speed_usage_label(snapshot.local_fast_uses, snapshot.local_standard_uses)
        )
        self.local_scan_label.setText(
            "日志匹配  "
            + _scan_status_label(
                snapshot.local_scan_status,
                snapshot.local_files_scanned,
                snapshot.local_files_skipped,
                tokens=snapshot.local_tokens,
                requests=snapshot.local_requests,
            )
        )
        if snapshot.observed_quota_change is None:
            self.local_quota_change_label.setText("本机记录期间的账号整体额度变化  —")
        else:
            self.local_quota_change_label.setText(
                "本机记录期间，账号整体已用额度 "
                f"+{_percent(snapshot.observed_quota_change)} 个百分点（非单机归因）"
            )
        self._show_synced_devices(
            account_key=snapshot.account_key,
            reset_epoch=int(reset.timestamp()) if reset is not None else None,
            local_tokens=CodexTokenUsage(
                input_tokens=snapshot.local_input_tokens,
                cached_input_tokens=snapshot.local_cached_input_tokens,
                output_tokens=snapshot.local_output_tokens,
                total_tokens=snapshot.local_tokens,
                requests=snapshot.local_requests,
            ),
            local_models=snapshot.local_model_usage,
            local_fast_uses=snapshot.local_fast_uses,
            local_standard_uses=snapshot.local_standard_uses,
            local_scan_status=snapshot.local_scan_status,
            local_files_scanned=snapshot.local_files_scanned,
            local_files_skipped=snapshot.local_files_skipped,
            account_used_percent=snapshot.used_percent,
        )

    def _show_remote_cycle(
        self,
        devices: tuple[CodexDeviceUsageSnapshot, ...],
    ) -> None:
        latest = max(devices, key=lambda item: item.updated_at)
        label = latest.account_label or f"局域网账号 {latest.account_key[:6]}…"
        plan = f" · {_plan_label(latest.plan_type)}" if latest.plan_type else ""
        self.current_account_label.setText(f"局域网同步 · {label}{plan} · 本机未登录")
        self._clear_quota_rows()
        reset = datetime.fromtimestamp(latest.window_resets_at, UTC)
        used_percent = latest.account_used_percent
        if used_percent is not None:
            self._add_window_row(
                "Codex",
                CodexRateWindow(
                    used_percent=used_percent,
                    window_duration_minutes=latest.window_duration_minutes,
                    resets_at=reset,
                ),
                historical=True,
            )
        self.account_lifetime_label.setText("累计  —")
        self.account_recent_label.setText(f"最后同步  {_format_snapshot_date(latest.updated_at)}")
        self.account_streak_label.setText("该账号无需在本机登录即可查看局域网汇总")
        self.local_total_label.setText("Token  —（本机无该账号记录）")
        self.local_breakdown_label.setText("输入 / 输出 / 缓存  —")
        self.local_requests_label.setText("模型请求  —")
        self.local_models_label.setText("常用模型  —")
        self.local_speed_label.setText("速度占比  —")
        self.local_scan_label.setText("日志匹配  本机未登录该账号")
        self.local_quota_change_label.setText("账号额度来自最近一次局域网同步")
        known_devices = tuple(
            item
            for item in devices
            if _has_device_usage(item.scan_status, item.total_tokens, item.requests)
        )
        total_tokens = sum(item.total_tokens for item in known_devices)
        total_requests = sum(item.requests for item in known_devices)
        self.synced_devices_label.setText(f"局域网同步  已同步 {len(devices)} 台设备")
        self.synced_devices_label.setToolTip("、".join(item.device_label for item in devices))
        self.all_devices_total_label.setText(
            f"已知设备合计  {_number(total_tokens)} Token · {_number(total_requests)} 次模型请求"
            if known_devices
            else "已知设备合计  —（无可确认 Token）"
        )
        self._show_device_ranking(
            local_tokens=CodexTokenUsage(),
            local_models=(),
            local_fast_uses=0,
            local_standard_uses=0,
            local_scan_status="unknown",
            local_files_scanned=0,
            local_files_skipped=0,
            devices=devices,
            account_used_percent=used_percent,
            include_local=False,
        )

    def reload_synced_usage(self, account_key: str | None = None) -> None:
        selected = self.account_selector.currentData()
        current_key = self._live_report.account.key if self._live_report is not None else None
        self._reload_account_selector(
            current_key=current_key,
            selected_key=selected if isinstance(selected, str) else account_key,
        )
        if self._live_report is None:
            self._show_selected_cycle()
            return
        if (
            self.account_selector.currentData() == self._live_report.account.key
            and self.cycle_selector.currentData() == "__live__"
        ):
            self._show_report(self._live_report)
        else:
            self._show_selected_cycle()

    def _show_synced_devices(
        self,
        *,
        account_key: str,
        reset_epoch: int | None,
        local_tokens: CodexTokenUsage,
        local_models: tuple[CodexModelUsage, ...],
        local_fast_uses: int,
        local_standard_uses: int,
        local_scan_status: str,
        local_files_scanned: int,
        local_files_skipped: int,
        account_used_percent: float | None,
    ) -> None:
        if reset_epoch is None:
            self.synced_devices_label.setText("局域网同步  当前额度周期未知")
            self.all_devices_total_label.setText("多电脑合计  —")
            self.quota_attribution_label.setText("额度归属  当前额度周期未知")
            self._set_device_ranking_lines(("当前额度周期未知，无法生成排名",))
            return
        devices = self._device_history.load(
            account_key=account_key,
            window_resets_at=reset_epoch,
            exclude_device_id=self._device_id or None,
        )
        if not devices:
            self.synced_devices_label.setText("局域网同步  尚未同步其他电脑")
            self.all_devices_total_label.setText(
                f"已知设备合计  {_number(local_tokens.total_tokens)} Token（仅本机）"
                if _has_device_usage(
                    local_scan_status,
                    local_tokens.total_tokens,
                    local_tokens.requests,
                )
                else "已知设备合计  —（本机无可确认 Token）"
            )
            self.synced_devices_label.setToolTip("点击“连接电脑”并输入对方局域网 IPv4")
            self._show_device_ranking(
                local_tokens=local_tokens,
                local_models=local_models,
                local_fast_uses=local_fast_uses,
                local_standard_uses=local_standard_uses,
                local_scan_status=local_scan_status,
                local_files_scanned=local_files_scanned,
                local_files_skipped=local_files_skipped,
                devices=(),
                account_used_percent=account_used_percent,
            )
            return
        combined = CodexTokenUsage()
        known_count = 0
        if _has_device_usage(local_scan_status, local_tokens.total_tokens, local_tokens.requests):
            combined += local_tokens
            known_count += 1
        for device in devices:
            if _has_device_usage(device.scan_status, device.total_tokens, device.requests):
                combined += device.tokens
                known_count += 1
        labels = "、".join(device.device_label for device in devices)
        self.synced_devices_label.setText(f"局域网同步  已同步 {len(devices)} 台其他电脑")
        self.synced_devices_label.setToolTip(labels)
        self.all_devices_total_label.setText(
            (
                f"已知设备合计  {_number(combined.total_tokens)} Token · "
                f"{_number(combined.requests)} 次模型请求"
            )
            if known_count
            else "已知设备合计  —（无可确认 Token）"
        )
        self._show_device_ranking(
            local_tokens=local_tokens,
            local_models=local_models,
            local_fast_uses=local_fast_uses,
            local_standard_uses=local_standard_uses,
            local_scan_status=local_scan_status,
            local_files_scanned=local_files_scanned,
            local_files_skipped=local_files_skipped,
            devices=devices,
            account_used_percent=account_used_percent,
        )

    def _show_device_ranking(
        self,
        *,
        local_tokens: CodexTokenUsage,
        local_models: tuple[CodexModelUsage, ...],
        local_fast_uses: int,
        local_standard_uses: int,
        local_scan_status: str,
        local_files_scanned: int,
        local_files_skipped: int,
        devices: tuple[CodexDeviceUsageSnapshot, ...],
        account_used_percent: float | None,
        include_local: bool = True,
    ) -> None:
        entries = []
        if include_local:
            entries.append(
                (
                    self._device_label + "（本机）",
                    local_tokens.total_tokens,
                    local_tokens.requests,
                    local_models,
                    local_fast_uses,
                    local_standard_uses,
                    local_scan_status,
                    local_files_scanned,
                    local_files_skipped,
                )
            )
        entries.extend(
            (
                device.device_label,
                device.total_tokens,
                device.requests,
                device.model_usage,
                device.fast_uses,
                device.standard_uses,
                device.scan_status,
                device.files_scanned,
                device.files_skipped,
            )
            for device in devices
        )
        entries.sort(
            key=lambda item: (
                not _has_device_usage(item[6], item[1], item[2]),
                -item[1],
                item[0].casefold(),
            )
        )
        lines: list[str] = []
        known_total = sum(
            item[1] for item in entries if _has_device_usage(item[6], item[1], item[2])
        )
        incomplete = any(not _has_device_usage(item[6], item[1], item[2]) for item in entries)
        self.quota_attribution_label.setText(
            _quota_attribution_label(account_used_percent, known_total, incomplete)
        )
        for rank, (
            label,
            tokens,
            requests,
            models,
            fast_uses,
            standard_uses,
            scan_status,
            files_scanned,
            files_skipped,
        ) in enumerate(
            entries[:8],
            1,
        ):
            medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, f"{rank}.")
            estimate = _estimated_quota_share(
                tokens,
                known_total,
                account_used_percent,
            )
            model = models[0] if models else None
            model_suffix = (
                f"常用 {model.model}（{_number(model.uses)} 次）"
                if model is not None
                else "常用模型 —"
            )
            has_usage = _has_device_usage(scan_status, tokens, requests)
            quota_suffix = (
                f"按已知设备折算约 {estimate} 额度" if estimate != "—" and has_usage else "预估额度 —"
            )
            token_summary = (
                f"{_number(tokens)} Token"
                if has_usage
                else f"Token —（{_scan_status_short(scan_status)}）"
            )
            line = (
                f"{medal} {label}  {token_summary} · {quota_suffix}\n"
                f"    {_number(requests)} 次模型请求 · {model_suffix}\n"
                f"    速度 {_speed_usage_label(fast_uses, standard_uses)}"
            )
            if not has_usage:
                line += "\n    日志 " + _scan_status_label(
                    scan_status,
                    files_scanned,
                    files_skipped,
                    tokens=tokens,
                    requests=requests,
                )
            lines.append(line)
        if len(entries) > 8:
            lines.append(f"…还有 {len(entries) - 8} 台设备")
        self._set_device_ranking_lines(tuple(lines))

    def _set_device_ranking_lines(self, lines: tuple[str, ...]) -> None:
        self.device_ranking_list.clear()
        for line in lines:
            item = QListWidgetItem(line, self.device_ranking_list)
            item.setSizeHint(QSize(0, 80 if line.count("\n") >= 3 else 64 if "\n" in line else 30))
        visible_rows = max(1, min(len(lines), 4))
        self.device_ranking_list.setFixedHeight(min(338, 10 + visible_rows * 82))

    def _connect_device(self) -> None:
        if self._on_connect_device is not None:
            self._on_connect_device()

    def _add_limit_rows(self, limit: CodexRateLimit) -> None:
        prefix = limit.limit_name or ("Codex" if limit.limit_id == "codex" else limit.limit_id)
        if limit.primary is not None:
            self._add_window_row(prefix, limit.primary)
        if limit.secondary is not None:
            self._add_window_row(f"{prefix} · 次级窗口", limit.secondary)

    def _add_window_row(
        self,
        name: str,
        window: CodexRateWindow,
        *,
        historical: bool = False,
    ) -> None:
        row = QFrame(self)
        row.setObjectName("statusCard")
        layout = QGridLayout(row)
        layout.setContentsMargins(14, 10, 14, 10)
        title = QLabel(f"{name} · {_window_label(window.window_duration_minutes)}", row)
        title.setStyleSheet("font-weight: 700; color: #4B4641;")
        layout.addWidget(title, 0, 0)
        layout.setColumnStretch(0, 1)
        remaining_label = QLabel(f"剩余 {_percent(window.remaining_percent)}%", row)
        remaining_label.setObjectName("quotaRemainingLabel")
        remaining_label.setStyleSheet("font-weight: 700; color: #A85D3E;")
        remaining_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(remaining_label, 0, 1)
        reset_text = "重置时间未知"
        if window.resets_at is not None:
            reset = window.resets_at.astimezone()
            reset_text = f"{reset:%m月%d日 %H:%M} 重置"
        if historical:
            reset_text = f"历史快照 · {reset_text}"
        reset_label = QLabel(reset_text, row)
        reset_label.setObjectName("mutedLabel")
        reset_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(reset_label, 0, 2)
        progress = QProgressBar(row)
        progress.setRange(0, 100)
        progress.setValue(round(window.remaining_percent))
        progress.setFormat(f"剩余 {_percent(window.remaining_percent)}%")
        # macOS native progress bars intentionally do not paint their format text.
        # Keep the format for accessibility/tests and show the value in a label above.
        progress.setTextVisible(False)
        layout.addWidget(progress, 1, 0, 1, 3)
        self.quota_rows.addWidget(row)

    def _clear_quota_rows(self) -> None:
        while self.quota_rows.count():
            item = self.quota_rows.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def closeEvent(self, event: object) -> None:  # noqa: N802 - Qt override signature
        self._poll_timer.stop()
        super().closeEvent(event)  # type: ignore[arg-type]


def _window_label(minutes: int | None) -> str:
    if minutes is None:
        return "滚动窗口"
    if minutes % (7 * 24 * 60) == 0:
        return f"{minutes // (7 * 24 * 60)} 周"
    if minutes % (24 * 60) == 0:
        return f"{minutes // (24 * 60)} 天"
    if minutes % 60 == 0:
        return f"{minutes // 60} 小时"
    return f"{minutes} 分钟"


def _live_cycle_label(window: CodexRateWindow | None) -> str:
    if window is None:
        return "当前周期"
    return f"当前 · {_cycle_range(window.resets_at, window.window_duration_minutes)}"


def _snapshot_cycle_label(snapshot: CodexAccountSnapshot) -> str:
    reset = _parse_snapshot_time(snapshot.resets_at)
    state = "已归档" if snapshot.finalized else "最后快照"
    return f"往期 · {_cycle_range(reset, snapshot.window_duration_minutes)} · {state}"


def _cycle_range(reset: datetime | None, minutes: int | None) -> str:
    if reset is None:
        return "重置时间未知"
    local_reset = reset.astimezone()
    if minutes is None:
        return f"{local_reset:%m/%d} 重置"
    start = (reset - timedelta(minutes=minutes)).astimezone()
    return f"{start:%m/%d}–{local_reset:%m/%d}"


def _plan_label(plan: str) -> str:
    labels = {
        "free": "Free",
        "go": "Go",
        "plus": "Plus",
        "pro": "Pro",
        "team": "Team",
        "business": "Business",
        "enterprise": "Enterprise",
        "edu": "Edu",
    }
    return labels.get(plan, plan.replace("_", " ").title() if plan else "Unknown")


def _number(value: int | None) -> str:
    return "—" if value is None else f"{value:,}"


def _percent(value: float) -> str:
    rounded = round(value, 1)
    return f"{rounded:g}"


def _estimated_quota_share(
    device_tokens: int,
    known_tokens: int,
    account_used_percent: float | None,
) -> str:
    if account_used_percent is None or known_tokens <= 0:
        return "—"
    share = max(0.0, account_used_percent) * max(0, device_tokens) / known_tokens
    return f"{_percent(share)}%"


def _has_device_usage(scan_status: str, tokens: int, requests: int) -> bool:
    return scan_status == "matched" or tokens > 0 or requests > 0


def _scan_status_short(scan_status: str) -> str:
    return {
        "no_matching_events": "当前账号/周期无匹配记录",
        "unreadable_files": "会话日志不可读取",
        "no_session_files": "未发现本机会话日志",
        "unknown": "旧版快照无扫描状态",
    }.get(scan_status, "无可确认的匹配记录")


def _scan_status_label(
    scan_status: str,
    files_scanned: int,
    files_skipped: int,
    *,
    tokens: int = 0,
    requests: int = 0,
) -> str:
    if _has_device_usage(scan_status, tokens, requests) or scan_status == "matched":
        detail = f"已扫描 {_number(files_scanned)} 个会话文件"
        if files_skipped:
            detail += f"，{_number(files_skipped)} 个无法读取"
        return f"已匹配 · {detail}"
    if scan_status == "no_matching_events":
        return f"已扫描 {_number(files_scanned)} 个会话文件，但当前账号/周期无匹配事件"
    if scan_status == "unreadable_files":
        return f"{_number(files_skipped)} 个会话文件无法读取"
    if scan_status == "no_session_files":
        return "未发现本机 Codex 会话日志"
    return "旧版设备未提供扫描诊断；重新同步后更新"


def _quota_attribution_label(
    account_used_percent: float | None,
    known_tokens: int,
    incomplete: bool,
) -> str:
    if account_used_percent is None:
        return "额度归属  账号已用额度未知"
    used = f"{_percent(account_used_percent)}%"
    if known_tokens <= 0:
        return f"额度归属  账号已用 {used}；已同步设备没有可确认的 Token，无法分配"
    if incomplete:
        return f"额度归属  账号已用 {used}；部分设备记录缺失，未归属额度无法判断"
    return f"额度归属  账号已用 {used}；仅按已同步设备折算，未同步设备占用无法判断"


def _speed_usage_label(fast_uses: int, standard_uses: int) -> str:
    fast = max(0, fast_uses)
    standard = max(0, standard_uses)
    total = fast + standard
    if total <= 0:
        return "—"
    fast_percent = fast * 100 / total
    standard_percent = 100 - fast_percent
    return f"极快 {_percent(fast_percent)}% · 标准 {_percent(standard_percent)}%"


def _model_usage_label(models: tuple[CodexModelUsage, ...]) -> str:
    if not models:
        return "常用模型  —"
    summary = " · ".join(
        f"{item.model}（{_number(item.uses)} 次）"
        for item in models[:3]
    )
    return f"常用模型  {summary}"


def _parse_snapshot_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _format_snapshot_date(value: str) -> str:
    try:
        return datetime.fromisoformat(value).astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return value


__all__ = ["CodexUsageDialog"]
