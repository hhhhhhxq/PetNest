"""以互斥播放模式编辑当前宠物的动作时长。"""

from __future__ import annotations

from PySide6.QtCore import QSignalBlocker, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QCloseEvent, QIcon, QPainter, QPalette, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QHeaderView,
)

from petnest.models.pet_package import AnimationDefinition, PetPackage
from petnest.ui.theme import COLORS, dialog_stylesheet


_TRIGGER_TEXT = {
    "idle": "默认待机", "drag": "拖动宠物时", "click": "鼠标点击时", "drop": "结束拖动时",
    "error": "任务报错时", "waiting": "任务等待时", "working": "任务工作时",
    "hover": "鼠标移入时", "codex_running_left": "外部事件可触发",
    "bored": "系统长时间无输入时", "sleep": "系统无人操作更久时", "wake": "系统恢复输入时",
}
_PREVIEW_HIGHLIGHT_STYLE = f"background: {COLORS['accent_soft']}; border: 1px solid {COLORS['accent']}; border-radius: 8px;"


class CheckerboardLabel(QLabel):
    """透明帧预览的棋盘格画布，避免用纯色块冒充透明背景。"""

    def paintEvent(self, event: object) -> None:  # noqa: ARG002 - Qt event signature
        painter = QPainter(self)
        tile = 18
        light = QColor("#FBF5F0")
        dark = QColor("#F2E7DF")
        for y in range(0, self.height(), tile):
            for x in range(0, self.width(), tile):
                painter.fillRect(x, y, tile, tile, light if (x // tile + y // tile) % 2 == 0 else dark)
        pixmap = self.pixmap()
        if pixmap is not None and not pixmap.isNull():
            scaled = pixmap.scaled(
                self.contentsRect().size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            painter.drawPixmap(
                (self.width() - scaled.width()) // 2,
                (self.height() - scaled.height()) // 2,
                scaled,
            )
        elif self.text():
            painter.setPen(QColor(COLORS["muted_text"]))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.text())


class AnimationEditorDialog(QDialog):
    """编辑会写入宠物包的逐帧时长；每个动作在两种编辑方式间二选一。"""

    def __init__(self, package: PetPackage, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("animationEditorDialog")
        self.setWindowTitle(f"编辑动画时长 — {package.name}")
        self.resize(1280, 780)
        self.setMinimumSize(1080, 700)
        self.setStyleSheet(dialog_stylesheet())
        self._package = package
        self._timelines = {action: _source_durations(definition) for action, definition in package.animations.items()}
        self._modes = {
            action: "per_frame" if definition.frame_durations_ms is not None else "total"
            for action, definition in package.animations.items()
        }
        self._changed_actions: set[str] = set()
        self._current_action: str | None = None
        self._loading = False
        self._duration_spins: list[QSpinBox] = []
        self._preview_pixmaps: dict[str, tuple[QPixmap, ...]] = {}
        self.preview_frame_index = 0
        self._highlighted_frame_index: int | None = None
        self._preview_paused = False
        self.preview_timer = QTimer(self)
        self.preview_timer.timeout.connect(self._advance_preview)

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(0)
        window_shell = QFrame(self)
        window_shell.setObjectName("windowShell")
        shell_layout = QVBoxLayout(window_shell)
        shell_layout.setContentsMargins(18, 18, 18, 16)
        shell_layout.setSpacing(14)
        header = QFrame(window_shell)
        header.setObjectName("headerBar")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(18, 13, 18, 13)
        title_column = QVBoxLayout()
        title_column.setSpacing(1)
        title = QLabel("编辑动画时长", header)
        title.setObjectName("pageTitle")
        title_column.addWidget(title)
        subtitle = QLabel("调整动作节奏 · 保存后自动重载当前宠物", header)
        subtitle.setObjectName("mutedLabel")
        title_column.addWidget(subtitle)
        header_layout.addLayout(title_column)
        header_layout.addStretch(1)
        pet_label = QLabel(f"当前宠物 · {package.name}", header)
        pet_label.setObjectName("mutedLabel")
        header_layout.addWidget(pet_label)
        header_layout.addSpacing(18)
        header_layout.addWidget(QLabel("×", header))
        shell_layout.addWidget(header)

        self.action_card = QFrame(window_shell)
        self.action_card.setObjectName("settingsCard")
        self.action_card.setMinimumWidth(450)
        action_card_layout = QVBoxLayout(self.action_card)
        action_card_layout.setContentsMargins(14, 12, 14, 12)
        action_card_layout.addWidget(QLabel("动作列表", self.action_card))
        self.action_table = QTableWidget(0, 5, self.action_card)
        self.action_table.setObjectName("animationActionTable")
        self.action_table.setHorizontalHeaderLabels(("动作", "展示时机", "帧数", "当前方式", "实际总时长"))
        self.action_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.action_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.action_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.action_table.horizontalHeader().setVisible(False)
        self.action_table.verticalHeader().setVisible(False)
        self.action_table.setShowGrid(False)
        action_palette = self.action_table.palette()
        for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive):
            action_palette.setColor(group, QPalette.ColorRole.Highlight, QColor(COLORS["accent_soft"]))
            action_palette.setColor(group, QPalette.ColorRole.HighlightedText, QColor(COLORS["accent"]))
        self.action_table.setPalette(action_palette)
        for column in (2, 3, 4):
            self.action_table.setColumnHidden(column, True)
        action_header = self.action_table.horizontalHeader()
        action_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        action_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.action_table.setWordWrap(True)
        self.action_table.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.action_table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.action_table.itemSelectionChanged.connect(self._load_selected_action)
        action_card_layout.addWidget(self.action_table, 1)

        self.editor_card = QFrame(window_shell)
        self.editor_card.setObjectName("settingsCard")
        editor_card_layout = QVBoxLayout(self.editor_card)
        editor_card_layout.setContentsMargins(14, 12, 14, 12)
        self.editor_heading_label = QLabel("选择动作", self.editor_card)
        self.editor_heading_label.setStyleSheet("font-size: 17px; font-weight: 700;")
        editor_card_layout.addWidget(self.editor_heading_label)
        self.editor_description_label = QLabel("选择一个动作查看并调整播放节奏", self.editor_card)
        self.editor_description_label.setObjectName("mutedLabel")
        editor_card_layout.addWidget(self.editor_description_label)

        self.mode_status_label = QLabel("—", self.editor_card)
        self.mode_status_label.setObjectName("mutedLabel")
        editor_card_layout.addWidget(self.mode_status_label)
        self.total_radio = QRadioButton("按总时长", self.editor_card)
        self.per_frame_radio = QRadioButton("逐帧编辑", self.editor_card)
        self.mode_group = QButtonGroup(self)
        self.mode_group.addButton(self.total_radio)
        self.mode_group.addButton(self.per_frame_radio)
        self.total_radio.toggled.connect(self._mode_changed)
        self.per_frame_radio.toggled.connect(self._mode_changed)
        mode_switch = QFrame(self.editor_card)
        mode_switch.setObjectName("modeSwitch")
        mode_switch_layout = QHBoxLayout(mode_switch)
        mode_switch_layout.setContentsMargins(6, 5, 6, 5)
        mode_switch_layout.setSpacing(6)
        mode_switch_layout.addWidget(self.total_radio, 1)
        mode_switch_layout.addWidget(self.per_frame_radio, 1)
        editor_card_layout.addWidget(mode_switch)

        self.mode_explanation_card = QFrame(self.editor_card)
        self.mode_explanation_card.setObjectName("modeExplanationCard")
        explanation_layout = QVBoxLayout(self.mode_explanation_card)
        explanation_layout.setContentsMargins(14, 10, 14, 10)
        self.mode_explanation_title = QLabel("编辑方式", self.mode_explanation_card)
        self.mode_explanation_title.setStyleSheet("font-weight: 700;")
        explanation_layout.addWidget(self.mode_explanation_title)
        self.mode_explanation_label = QLabel("保持原有帧间比例，统一缩放节奏", self.mode_explanation_card)
        self.mode_explanation_label.setObjectName("mutedLabel")
        explanation_layout.addWidget(self.mode_explanation_label)
        editor_card_layout.addWidget(self.mode_explanation_card)

        controls = QFormLayout()
        self.base_duration_label = QLabel("—", self)
        self.total_duration_spin = QSpinBox(self.editor_card)
        self.total_duration_spin.setRange(1, 600_000)
        self.total_duration_spin.setSingleStep(50)
        self.total_duration_spin.setSuffix(" ms")
        self.total_duration_spin.valueChanged.connect(self._total_duration_changed)
        controls.addRow("基准时长", self.base_duration_label)
        controls.addRow("目标总时长", self.total_duration_spin)
        editor_card_layout.addLayout(controls)

        timeline_heading = QHBoxLayout()
        self.total_timeline_heading = QLabel("节奏分配预览", self.editor_card)
        self.total_timeline_heading.setStyleSheet("font-weight: 700;")
        timeline_heading.addWidget(self.total_timeline_heading)
        self.total_timeline_hint = QLabel("按原比例缩放", self.editor_card)
        self.total_timeline_hint.setObjectName("mutedLabel")
        timeline_heading.addWidget(self.total_timeline_hint)
        timeline_heading.addStretch(1)
        editor_card_layout.addLayout(timeline_heading)
        self.total_timeline = QFrame(self.editor_card)
        self.total_timeline.setObjectName("totalTimeline")
        self.total_timeline_layout = QHBoxLayout(self.total_timeline)
        self.total_timeline_layout.setContentsMargins(12, 12, 12, 12)
        self.total_timeline_layout.setSpacing(5)
        editor_card_layout.addWidget(self.total_timeline)

        self.frame_list = QListWidget(self.editor_card)
        self.frame_list.setMinimumWidth(320)
        self.frame_list.setObjectName("animationFrameList")
        self.frame_list.setSpacing(4)
        self.frame_list.itemClicked.connect(self._select_preview_frame)
        editor_card_layout.addWidget(self.frame_list, 1)

        self.preview_card = QFrame(window_shell)
        self.preview_card.setObjectName("previewCard")
        self.preview_card.setMinimumWidth(260)
        preview_card_layout = QVBoxLayout(self.preview_card)
        preview_card_layout.setContentsMargins(14, 14, 14, 14)
        preview_title = QLabel("实时动作预览", self.preview_card)
        preview_title.setStyleSheet("color: #B07962; font-size: 13px; font-weight: 700;")
        preview_card_layout.addWidget(preview_title)
        self.preview_label = CheckerboardLabel("暂无可预览的帧", self.preview_card)
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setMinimumSize(220, 300)
        self.preview_label.setObjectName("animationPreviewChecker")
        self.preview_label.setProperty("checkerboard", True)
        self.preview_label.setStyleSheet(
            f"border: 1px solid {COLORS['border']}; border-radius: 10px;"
        )
        preview_card_layout.addWidget(self.preview_label, 1)
        self.preview_frame_label = QLabel("第 1 帧", self.preview_card)
        self.preview_frame_label.setObjectName("mutedLabel")
        self.preview_frame_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview_card_layout.addWidget(self.preview_frame_label)
        self.preview_play_button = QPushButton("暂停预览", self.preview_card)
        self.preview_play_button.clicked.connect(self._toggle_preview)
        preview_card_layout.addWidget(self.preview_play_button)
        main_row = QHBoxLayout()
        main_row.setSpacing(14)
        main_row.addWidget(self.action_card, 4)
        main_row.addWidget(self.editor_card, 5)
        main_row.addWidget(self.preview_card, 3)
        shell_layout.addLayout(main_row, 1)
        self._sync_responsive_preview()
        self.duration_table = self.frame_list

        self.apply_hint_label = QLabel("时长会随宠物文件夹一起分享。", window_shell)
        self.apply_hint_label.setObjectName("mutedLabel")
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save, window_shell)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("保存并重载")
        buttons.button(QDialogButtonBox.StandardButton.Save).setObjectName("primaryButton")
        footer = QHBoxLayout()
        footer.addWidget(self.apply_hint_label)
        footer.addStretch(1)
        footer.addWidget(buttons)
        shell_layout.addLayout(footer)
        root.addWidget(window_shell)
        self._populate_action_table()
        if self.action_table.rowCount():
            self.action_table.selectRow(0)

    def resizeEvent(self, event: object) -> None:  # noqa: N802 - Qt override signature.
        super().resizeEvent(event)  # type: ignore[arg-type]
        self._sync_responsive_preview()

    def _sync_responsive_preview(self) -> None:
        """在窄窗口隐藏预览，优先保证动作列表和编辑控件完整可用。"""
        compact = self.width() < 1180
        self.preview_card.setVisible(not compact)

    def updated_frame_durations(self) -> dict[str, tuple[int, ...]]:
        """仅返回本次编辑实际修改过的动作，避免无谓重写其余配置。"""
        return {action: self._timelines[action] for action in self._changed_actions}

    def applied_summary(self) -> str:
        if self._current_action is None:
            return ""
        return f"已保存：{self._current_action}，{_mode_label(self._modes[self._current_action])}，{sum(self._timelines[self._current_action])} ms"

    def _populate_action_table(self) -> None:
        self.action_table.setRowCount(len(self._package.animations))
        for row, (action, definition) in enumerate(self._package.animations.items()):
            values = (
                action, f"{_TRIGGER_TEXT.get(action, '自定义动作')} · {len(definition.frames)} 帧 · {sum(self._timelines[action])} ms", str(len(definition.frames)),
                _mode_label(self._modes[action]), f"{sum(self._timelines[action])} ms",
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, action)
                self.action_table.setItem(row, column, item)

    def _load_selected_action(self) -> None:
        items = self.action_table.selectedItems()
        if not items:
            return
        action = str(self.action_table.item(items[0].row(), 0).data(Qt.ItemDataRole.UserRole))
        self._current_action = action
        definition = self._package.animations[action]
        self.editor_heading_label.setText(f"{action} · {_TRIGGER_TEXT.get(action, '自定义动作')}")
        self.editor_description_label.setText(
            f"共 {len(definition.frames)} 帧 · "
            f"{'只调整整体播放速度' if self._modes[action] == 'total' else '每帧单独设置播放时长'}"
        )
        self._loading = True
        try:
            with QSignalBlocker(self.total_radio), QSignalBlocker(self.per_frame_radio), QSignalBlocker(self.total_duration_spin):
                self.total_radio.setChecked(self._modes[action] == "total")
                self.per_frame_radio.setChecked(self._modes[action] == "per_frame")
                self.total_duration_spin.setValue(sum(self._timelines[action]))
            self.base_duration_label.setText(f"{sum(_source_durations(definition))} ms")
            self._populate_frame_list(action)
            self._update_mode_widgets()
        finally:
            self._loading = False
        self._restart_preview()

    def _mode_changed(self, checked: bool) -> None:
        if self._loading or not checked or self._current_action is None:
            return
        action = self._current_action
        mode = "total" if self.total_radio.isChecked() else "per_frame"
        self._modes[action] = mode
        self._changed_actions.add(action)
        self._update_mode_widgets()
        self._populate_action_table()

    def _update_mode_widgets(self) -> None:
        total_mode = self.total_radio.isChecked()
        self.total_duration_spin.setEnabled(total_mode)
        self.base_duration_label.setVisible(total_mode)
        self.total_timeline.setVisible(total_mode)
        self.frame_list.setVisible(not total_mode)
        self._update_total_timeline()
        self.mode_status_label.setText(
            "当前方式：按总时长播放（仅缩放原有节奏）" if total_mode else "当前方式：手动逐帧播放（忽略总时长缩放）"
        )
        self.mode_explanation_label.setText(
            "保持原有帧间比例，统一缩放节奏" if total_mode else "每一帧独立控制，不会自动缩放其他帧"
        )
        self.total_timeline_hint.setText(
            f"按原比例缩放至 {sum(self._timelines.get(self._current_action, ())) / 1000:.2f} 秒"
            if self._current_action is not None
            else "按原比例缩放"
        )

    def _update_total_timeline(self) -> None:
        while self.total_timeline_layout.count():
            child = self.total_timeline_layout.takeAt(0)
            if child.widget() is not None:
                child.widget().deleteLater()
        if self._current_action is None:
            return
        durations = self._timelines[self._current_action]
        maximum = max(durations, default=1)
        for index, duration in enumerate(durations):
            bar = QFrame(self.total_timeline)
            bar.setObjectName("timelineSegment")
            bar.setMinimumWidth(max(14, round(92 * duration / maximum)))
            bar.setToolTip(f"第 {index + 1} 帧 · {duration} ms")
            bar.setStyleSheet(
                f"background: {COLORS['accent'] if index == 0 else COLORS['accent_soft']};"
                f"border: 1px solid {COLORS['accent']}; border-radius: 5px;"
            )
            self.total_timeline_layout.addWidget(bar, max(1, duration))
        self.total_timeline_layout.addStretch(1)

    def _populate_frame_list(self, action: str) -> None:
        self.frame_list.clear()
        self._duration_spins.clear()
        self._highlighted_frame_index = None
        for index, (path, duration) in enumerate(zip(self._package.animations[action].frames, self._timelines[action], strict=True)):
            pixmap = self._pixmaps_for(action)[index]
            item = QListWidgetItem(QIcon(pixmap), "")
            item.setData(Qt.ItemDataRole.UserRole, index)
            item.setSizeHint(QSize(0, 84))
            row = QWidget(self.frame_list)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(6, 4, 6, 4)
            thumbnail = QLabel(row)
            thumbnail.setPixmap(pixmap.scaled(72, 72, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            thumbnail.setFixedSize(76, 76)
            thumbnail.setAlignment(Qt.AlignmentFlag.AlignCenter)
            row_layout.addWidget(thumbnail)
            row_layout.addWidget(QLabel(f"第 {index + 1} 帧", row))
            spin = QSpinBox(row)
            spin.setRange(1, 60_000)
            spin.setValue(duration)
            spin.valueChanged.connect(self._duration_changed)
            spin.setSuffix(" ms")
            row_layout.addWidget(spin)
            self._duration_spins.append(spin)
            self.frame_list.addItem(item)
            self.frame_list.setItemWidget(item, row)

    def _total_duration_changed(self, total_duration: int) -> None:
        if self._loading or self._current_action is None or not self.total_radio.isChecked():
            return
        action = self._current_action
        self._timelines[action] = _scaled_timeline(self._timelines[action], total_duration)
        self._changed_actions.add(action)
        self._populate_frame_list(action)
        self._populate_action_table()
        self._restart_preview()

    def _duration_changed(self, _value: int) -> None:
        if self._loading or self._current_action is None or not self.per_frame_radio.isChecked():
            return
        action = self._current_action
        self._timelines[action] = self._table_durations()
        self._changed_actions.add(action)
        self._populate_action_table()
        self._restart_preview()

    def _table_durations(self) -> tuple[int, ...]:
        return tuple(spin.value() for spin in self._duration_spins)

    def _pixmaps_for(self, action: str) -> tuple[QPixmap, ...]:
        cached = self._preview_pixmaps.get(action)
        if cached is None:
            cached = tuple(QPixmap(str(path)) for path in self._package.animations[action].frames)
            self._preview_pixmaps[action] = cached
        return cached

    def _restart_preview(self) -> None:
        if self._current_action is None:
            return
        self.preview_frame_index = 0
        self._preview_paused = False
        self.preview_play_button.setText("暂停预览")
        self._render_preview()
        self.preview_frame_label.setText(f"第 {self.preview_frame_index + 1} 帧 · {self._timelines[self._current_action][self.preview_frame_index]} ms")
        self.preview_timer.start(self._timelines[self._current_action][0])

    def _advance_preview(self) -> None:
        if self._current_action is None:
            return
        self.preview_frame_index = (self.preview_frame_index + 1) % len(self._timelines[self._current_action])
        self._render_preview()
        self.preview_frame_label.setText(
            f"第 {self.preview_frame_index + 1} 帧 · {self._timelines[self._current_action][self.preview_frame_index]} ms"
        )
        self.preview_timer.start(self._timelines[self._current_action][self.preview_frame_index])

    def _render_preview(self) -> None:
        if self._current_action is None:
            return
        pixmap = self._pixmaps_for(self._current_action)[self.preview_frame_index]
        if pixmap.isNull():
            self.preview_label.setText("无法读取此帧预览")
            self.preview_label.setPixmap(QPixmap())
        else:
            available = self.preview_label.contentsRect().size()
            self.preview_label.setText("")
            self.preview_label.setPixmap(
                pixmap.scaled(available, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            )
        self._set_preview_highlight()

    def _set_preview_highlight(self) -> None:
        """仅更新前后两行的视觉高亮，绝不改变列表选择或滚动位置。"""
        if self._highlighted_frame_index == self.preview_frame_index:
            return
        self._set_frame_row_style(self._highlighted_frame_index, "")
        self._set_frame_row_style(self.preview_frame_index, _PREVIEW_HIGHLIGHT_STYLE)
        self._highlighted_frame_index = self.preview_frame_index

    def _set_frame_row_style(self, row: int | None, style: str) -> None:
        if row is None or row < 0 or row >= self.frame_list.count():
            return
        item_widget = self.frame_list.itemWidget(self.frame_list.item(row))
        if item_widget is not None:
            item_widget.setStyleSheet(style)

    def _select_preview_frame(self, item: QListWidgetItem) -> None:
        self.preview_timer.stop()
        self._preview_paused = True
        self.preview_play_button.setText("播放预览")
        self.preview_frame_index = int(item.data(Qt.ItemDataRole.UserRole))
        self._render_preview()

    def _toggle_preview(self) -> None:
        if self._current_action is None:
            return
        if self._preview_paused:
            self._preview_paused = False
            self.preview_play_button.setText("暂停预览")
            self.preview_timer.start(self._timelines[self._current_action][self.preview_frame_index])
        else:
            self.preview_timer.stop()
            self._preview_paused = True
            self.preview_play_button.setText("播放预览")

    def closeEvent(self, event: QCloseEvent) -> None:
        self.preview_timer.stop()
        self._preview_pixmaps.clear()
        self._highlighted_frame_index = None
        super().closeEvent(event)


def _source_durations(definition: AnimationDefinition) -> tuple[int, ...]:
    return definition.frame_durations_ms or tuple(round(1000 / definition.fps) for _ in definition.frames)


def _scaled_timeline(source: tuple[int, ...], target_total: int) -> tuple[int, ...]:
    target_total = max(len(source), target_total)
    source_total = sum(source)
    durations = [max(1, round(duration * target_total / source_total)) for duration in source]
    difference = target_total - sum(durations)
    index = len(durations) - 1
    while difference:
        adjustment = 1 if difference > 0 else -1
        if durations[index] + adjustment > 0:
            durations[index] += adjustment
            difference -= adjustment
        index = (index - 1) % len(durations)
    return tuple(durations)


def _mode_label(mode: str) -> str:
    return "总时长" if mode == "total" else "逐帧"
