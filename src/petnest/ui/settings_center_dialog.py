"""PetNest 五分类设置中心。"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import replace

from PySide6.QtCore import QSignalBlocker, QTime, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from petnest.core.cursor_style_catalog import CursorStyle
from petnest.models.settings import Settings
from petnest.ui.theme import dialog_stylesheet


class SnappingSlider(QSlider):
    """鼠标大小滑块：拖动自由，释放后吸附到产品定义节点。"""

    NODES = (80, 100, 125, 150)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setRange(self.NODES[0], self.NODES[-1])
        self.setSingleStep(1)
        self.setPageStep(5)
        self.setTickInterval(5)
        self.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.sliderReleased.connect(self.snap_to_node)

    def snap_to_node(self) -> None:
        value = self.value()
        self.setValue(min(self.NODES, key=lambda node: abs(node - value)))


class SettingsCenterDialog(QDialog):
    """一个窗口承载显示、鼠标、空闲、倒计时和更新五类设置。"""

    _SECTION_NAMES = (
        ("display", "显示与窗口"),
        ("mouse_behavior", "鼠标与行为"),
        ("idle", "系统空闲"),
        ("countdown", "工作倒计时"),
        ("app_update", "应用与更新"),
    )
    _WEEKDAYS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")

    def __init__(
        self,
        settings: Settings,
        parent: QWidget | None = None,
        *,
        on_check_app_update: Callable[[], object] | None = None,
        cursor_styles: list[CursorStyle] | None = None,
        supported_roles: Iterable[str] | None = None,
        initial_section: str = "display",
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._cursor_styles = cursor_styles or []
        self._supported_roles = frozenset(supported_roles) if supported_roles is not None else None
        self._on_check_app_update = on_check_app_update
        self.setObjectName("settingsCenter")
        self.setWindowTitle("PetNest 设置中心")
        self.setMinimumSize(900, 650)
        self.resize(1040, 730)
        self.setStyleSheet(dialog_stylesheet())

        # 互动设置仍由互动窗口负责；保留隐藏兼容属性，不在设置中心页面呈现。
        self.lan_interaction_input = QCheckBox(self)
        self.lan_interaction_input.setChecked(settings.lan_interaction_enabled)
        self.lan_interaction_input.setVisible(False)
        self.remote_interaction_input = QCheckBox(self)
        self.remote_interaction_input.setChecked(settings.remote_interaction_enabled)
        self.remote_interaction_input.setVisible(False)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 14)
        root.setSpacing(14)
        header = QHBoxLayout()
        brand = QLabel("PetNest", self)
        brand.setStyleSheet("font-size: 15px; font-weight: 700; color: #D98663;")
        self.page_title = QLabel(self)
        self.page_title.setObjectName("pageTitle")
        header.addWidget(brand)
        header.addSpacing(18)
        header.addWidget(self.page_title)
        header.addStretch(1)
        root.addLayout(header)

        body = QHBoxLayout()
        body.setSpacing(18)
        self.section_list = QListWidget(self)
        self.section_list.setObjectName("settingsNavigation")
        self.section_list.setFixedWidth(170)
        self.section_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        for _key, label in self._SECTION_NAMES:
            self.section_list.addItem(QListWidgetItem(label))
        body.addWidget(self.section_list)

        self.page_stack = QStackedWidget(self)
        self.page_stack.addWidget(self._build_display_page())
        self.page_stack.addWidget(self._build_mouse_behavior_page())
        self.page_stack.addWidget(self._build_idle_page())
        self.page_stack.addWidget(self._build_countdown_page())
        self.page_stack.addWidget(self._build_app_update_page())
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.page_stack)
        body.addWidget(scroll, 1)
        root.addLayout(body, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("应用并关闭")
        buttons.button(QDialogButtonBox.StandardButton.Ok).setObjectName("primaryButton")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.button_box = buttons
        root.addWidget(buttons)

        self.section_list.currentRowChanged.connect(self._change_section)
        self.section_list.setCurrentRow(self._section_index(initial_section))

    def _section_index(self, section: str) -> int:
        aliases = {
            "显示与窗口": 0,
            "鼠标与行为": 1,
            "系统空闲": 2,
            "工作倒计时": 3,
            "应用与更新": 4,
            "mouse": 1,
            "idle": 2,
            "work_countdown": 3,
            "update": 4,
        }
        return aliases.get(section, next((i for i, (key, _label) in enumerate(self._SECTION_NAMES) if key == section), 0))

    def select_section(self, section: str) -> None:
        """供托盘不同入口激活同一窗口时切换分类。"""
        self.section_list.setCurrentRow(self._section_index(section))

    def _change_section(self, index: int) -> None:
        if index < 0:
            return
        self.page_stack.setCurrentIndex(index)
        self.page_title.setText(self._SECTION_NAMES[index][1])

    @staticmethod
    def _page(title: str, description: str, parent: QWidget) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget(parent)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 10, 4)
        layout.setSpacing(14)
        description_label = QLabel(description, page)
        description_label.setObjectName("pageDescription")
        description_label.setWordWrap(True)
        layout.addWidget(description_label)
        return page, layout

    @staticmethod
    def _card(title: str, description: str, parent: QWidget) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame(parent)
        card.setObjectName("settingsCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)
        heading = QLabel(title, card)
        heading.setStyleSheet("font-size: 15px; font-weight: 700;")
        layout.addWidget(heading)
        if description:
            text = QLabel(description, card)
            text.setObjectName("mutedLabel")
            text.setWordWrap(True)
            layout.addWidget(text)
        return card, layout

    def _build_display_page(self) -> QWidget:
        page, layout = self._page("显示与窗口", "调整桌宠的视觉比例和窗口行为。", self)
        card, card_layout = self._card("窗口行为", "常用显示选项会立即影响桌宠窗口。", page)
        form = QFormLayout()
        self.scale_input = QDoubleSpinBox(card)
        self.scale_input.setRange(0.25, 2.0)
        self.scale_input.setSingleStep(0.05)
        self.scale_input.setSuffix(" 倍")
        self.scale_input.setValue(self._settings.scale)
        self.always_on_top_input = QCheckBox("始终置顶", card)
        self.always_on_top_input.setChecked(self._settings.always_on_top)
        self.mouse_interaction_input = QCheckBox("启用鼠标交互", card)
        self.mouse_interaction_input.setChecked(self._settings.mouse_interaction_enabled)
        form.addRow("桌宠大小", self.scale_input)
        form.addRow("窗口层级", self.always_on_top_input)
        form.addRow("鼠标行为", self.mouse_interaction_input)
        card_layout.addLayout(form)
        layout.addWidget(card)
        layout.addStretch(1)
        return page

    def _build_mouse_behavior_page(self) -> QWidget:
        page, layout = self._page("鼠标与行为", "决定桌宠如何跟随鼠标，以及系统自定义鼠标的显示方式。", self)
        behavior_card, behavior_layout = self._card("跟随行为", "关闭跟随后，宠物大小不会再随光标变化。", page)
        behavior_form = QFormLayout()
        self.mouse_follow_input = QCheckBox("跟随鼠标", behavior_card)
        self.mouse_follow_input.setChecked(self._settings.mouse_follow_enabled)
        self.mouse_follow_scale_input = QDoubleSpinBox(behavior_card)
        self.mouse_follow_scale_input.setRange(0.25, 1.0)
        self.mouse_follow_scale_input.setSingleStep(0.05)
        self.mouse_follow_scale_input.setDecimals(2)
        self.mouse_follow_scale_input.setSuffix(" 倍")
        self.mouse_follow_scale_input.setValue(self._settings.mouse_follow_scale)
        behavior_form.addRow(self.mouse_follow_input)
        behavior_form.addRow("跟随时宠物大小", self.mouse_follow_scale_input)
        behavior_layout.addLayout(behavior_form)
        layout.addWidget(behavior_card)

        cursor_card, cursor_layout = self._card("自定义鼠标样式", "关闭后恢复系统默认光标，当前大小设置会保留。", page)
        self.cursor_style_enabled_input = QCheckBox("使用自定义鼠标样式", cursor_card)
        self.cursor_style_enabled_input.setChecked(self._settings.cursor_style_enabled)
        self.cursor_style_input = QComboBox(cursor_card)
        self.cursor_style_input.addItem("系统默认", None)
        for style in self._cursor_styles:
            self.cursor_style_input.addItem(style.display_name, style.identifier)
        selected_index = self.cursor_style_input.findData(self._settings.cursor_style_id)
        self.cursor_style_input.setCurrentIndex(max(0, selected_index))
        cursor_layout.addWidget(self.cursor_style_enabled_input)
        cursor_form = QFormLayout()
        cursor_form.addRow("鼠标主题", self.cursor_style_input)
        self.cursor_scale_slider = SnappingSlider(cursor_card)
        self.cursor_scale_slider.setValue(self._settings.cursor_scale)
        scale_row = QWidget(cursor_card)
        scale_layout = QHBoxLayout(scale_row)
        scale_layout.setContentsMargins(0, 0, 0, 0)
        scale_layout.addWidget(self.cursor_scale_slider, 1)
        self.cursor_scale_value_label = QLabel(scale_row)
        self.cursor_scale_value_label.setMinimumWidth(44)
        self.cursor_scale_value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        scale_layout.addWidget(self.cursor_scale_value_label)
        cursor_form.addRow("鼠标大小", scale_row)
        cursor_layout.addLayout(cursor_form)
        preview_row = QHBoxLayout()
        self.cursor_preview = QLabel(cursor_card)
        self.cursor_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cursor_preview.setMinimumSize(120, 96)
        preview_row.addWidget(self.cursor_preview, 1)
        self._role_group = QGroupBox("本主题已包含的光标", cursor_card)
        self._role_layout = QFormLayout(self._role_group)
        preview_row.addWidget(self._role_group, 1)
        cursor_layout.addLayout(preview_row)
        self.restore_cursor_button = QPushButton("恢复系统默认样式", cursor_card)
        self.restore_cursor_button.clicked.connect(self._restore_cursor_style)
        cursor_layout.addWidget(self.restore_cursor_button, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(cursor_card)
        layout.addStretch(1)

        self.mouse_follow_input.toggled.connect(self.mouse_follow_scale_input.setEnabled)
        self.cursor_style_enabled_input.toggled.connect(self._update_cursor_controls)
        self.cursor_style_input.currentIndexChanged.connect(self._update_cursor_controls)
        self.cursor_scale_slider.valueChanged.connect(self._update_cursor_scale_label)
        self._update_cursor_scale_label(self.cursor_scale_slider.value())
        self._update_cursor_controls()
        return page

    def _restore_cursor_style(self) -> None:
        self.cursor_style_enabled_input.setChecked(False)
        self.cursor_style_input.setCurrentIndex(0)

    def _update_cursor_scale_label(self, value: int) -> None:
        self.cursor_scale_value_label.setText(f"{value}%")

    def _update_cursor_controls(self) -> None:
        enabled = self.cursor_style_enabled_input.isChecked()
        if enabled and self.cursor_style_input.currentData() is None and self.cursor_style_input.count() > 1:
            self.cursor_style_input.setCurrentIndex(1)
        self.cursor_style_input.setEnabled(enabled)
        self.cursor_scale_slider.setEnabled(enabled)
        self.cursor_preview.setEnabled(enabled)
        self._role_group.setEnabled(enabled)
        self.restore_cursor_button.setEnabled(True)
        style = next((item for item in self._cursor_styles if item.identifier == self.cursor_style_input.currentData()), None)
        pixmap = QPixmap(str(style.preview_path)) if style else QPixmap()
        self.cursor_preview.setPixmap(
            pixmap.scaled(108, 88, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            if not pixmap.isNull()
            else QPixmap()
        )
        self.cursor_preview.setText("使用系统默认样式" if style is None else "")
        while self._role_layout.rowCount():
            self._role_layout.removeRow(0)
        for role, label in (
            ("arrow", "普通箭头"),
            ("busy", "忙碌中"),
            ("text", "文本选择"),
            ("move", "拖拽/移动"),
            ("resize_horizontal", "水平调整"),
            ("resize_vertical", "垂直调整"),
            ("resize_diag_1", "左上↘右下调整"),
            ("resize_diag_2", "右上↙左下调整"),
        ):
            supported = self._supported_roles is None or role in self._supported_roles
            self._role_layout.addRow(
                label,
                QLabel("主题样式" if style and role in style.roles and supported else "使用系统默认", self._role_group),
            )

    def _build_idle_page(self) -> QWidget:
        page, layout = self._page("系统空闲", "在一段时间没有操作时，让桌宠进入无聊或睡觉动作。", self)
        card, card_layout = self._card("空闲动作", "两个时间点保持清晰的先后关系。", page)
        self.system_idle_input = QCheckBox("启用系统空闲动作", card)
        self.system_idle_input.setChecked(self._settings.system_idle_enabled)
        card_layout.addWidget(self.system_idle_input)
        form = QFormLayout()
        self.system_bored_input = QSpinBox(card)
        self.system_bored_input.setRange(1, 86_400)
        self.system_bored_input.setSuffix(" 秒")
        self.system_bored_input.setValue(self._settings.system_bored_seconds)
        self.system_sleep_input = QSpinBox(card)
        self.system_sleep_input.setRange(2, 86_400)
        self.system_sleep_input.setSuffix(" 秒")
        self.system_sleep_input.setValue(self._settings.system_sleep_seconds)
        form.addRow("无操作后无聊", self.system_bored_input)
        form.addRow("无操作后睡觉", self.system_sleep_input)
        card_layout.addLayout(form)
        layout.addWidget(card)
        layout.addStretch(1)
        self.system_idle_input.toggled.connect(self.system_bored_input.setEnabled)
        self.system_idle_input.toggled.connect(self.system_sleep_input.setEnabled)
        self.system_bored_input.valueChanged.connect(self._keep_idle_thresholds_valid)
        self.system_sleep_input.valueChanged.connect(self._keep_idle_thresholds_valid)
        self._update_idle_controls()
        return page

    def _update_idle_controls(self) -> None:
        enabled = self.system_idle_input.isChecked()
        self.system_bored_input.setEnabled(enabled)
        self.system_sleep_input.setEnabled(enabled)

    def _keep_idle_thresholds_valid(self) -> None:
        if self.system_sleep_input.value() <= self.system_bored_input.value():
            blocker = QSignalBlocker(self.system_sleep_input)
            self.system_sleep_input.setValue(min(86_400, self.system_bored_input.value() + 1))
            del blocker

    def _build_countdown_page(self) -> QWidget:
        page, layout = self._page("工作倒计时", "工作日只选择一次，再选择固定时段或弹性打卡的计算方式。", self)
        schedule_card, schedule_layout = self._card("工作安排", "周六、周日也可以直接勾选为工作日。", page)
        workday_row = QHBoxLayout()
        self.workday_inputs: dict[str, QCheckBox] = {}
        for index, name in enumerate(self._WEEKDAYS):
            checkbox = QCheckBox(name, schedule_card)
            checkbox.setChecked(self._settings.daily_work_end_times.get(str(index)) is not None)
            self.workday_inputs[str(index)] = checkbox
            workday_row.addWidget(checkbox)
        schedule_layout.addLayout(workday_row)
        shortcut_row = QHBoxLayout()
        all_days = QPushButton("工作日全选", schedule_card)
        weekdays = QPushButton("周末设为休息日", schedule_card)
        reset_days = QPushButton("恢复默认", schedule_card)
        all_days.clicked.connect(lambda: [item.setChecked(True) for item in self.workday_inputs.values()])
        weekdays.clicked.connect(lambda: [item.setChecked(index < 5) for index, item in enumerate(self.workday_inputs.values())])
        reset_days.clicked.connect(self._reset_workdays)
        shortcut_row.addWidget(all_days)
        shortcut_row.addWidget(weekdays)
        shortcut_row.addWidget(reset_days)
        shortcut_row.addStretch(1)
        schedule_layout.addLayout(shortcut_row)
        self.work_countdown_input = QCheckBox("显示工作倒计时", schedule_card)
        self.work_countdown_input.setChecked(self._settings.work_countdown_enabled)
        schedule_layout.addWidget(self.work_countdown_input)
        layout.addWidget(schedule_card)

        mode_card, mode_layout = self._card("计算方式", "弹性打卡会在允许时间后显示独立打卡卡片，不改变原倒计时气泡。", page)
        self.schedule_mode_input = QComboBox(mode_card)
        self.schedule_mode_input.addItem("固定时段", "fixed")
        self.schedule_mode_input.addItem("弹性打卡", "elastic")
        self.schedule_mode_input.setCurrentIndex(max(0, self.schedule_mode_input.findData(self._settings.work_schedule_mode)))
        mode_layout.addWidget(self.schedule_mode_input)
        self.mode_stack = QStackedWidget(mode_card)
        self.mode_stack.addWidget(self._build_fixed_schedule_page(mode_card))
        self.mode_stack.addWidget(self._build_elastic_schedule_page(mode_card))
        mode_layout.addWidget(self.mode_stack)
        self.schedule_error_label = QLabel("", mode_card)
        self.schedule_error_label.setStyleSheet("color: #C66C62;")
        self.schedule_error_label.setWordWrap(True)
        self.schedule_error_label.hide()
        mode_layout.addWidget(self.schedule_error_label)
        layout.addWidget(mode_card)

        appearance = QGroupBox("高级设置 · 倒计时外观", page)
        appearance_form = QFormLayout(appearance)
        self.countdown_gap_input = QSpinBox(appearance)
        self.countdown_gap_input.setRange(0, 80)
        self.countdown_gap_input.setSuffix(" 像素")
        self.countdown_gap_input.setValue(self._settings.countdown_gap)
        self.countdown_width_input = QSpinBox(appearance)
        self.countdown_width_input.setRange(110, 420)
        self.countdown_width_input.setSuffix(" 像素")
        self.countdown_width_input.setValue(self._settings.countdown_width)
        self.countdown_height_input = QSpinBox(appearance)
        self.countdown_height_input.setRange(26, 100)
        self.countdown_height_input.setSuffix(" 像素")
        self.countdown_height_input.setValue(self._settings.countdown_height)
        self.countdown_theme_input = QComboBox(appearance)
        self.countdown_theme_input.addItem("A · 奶油爪爪", "cream")
        self.countdown_theme_input.addItem("B · 黑猫夜灯", "night")
        self.countdown_theme_input.addItem("C · 毛线便签", "yarn")
        theme_index = self.countdown_theme_input.findData(self._settings.countdown_theme)
        self.countdown_theme_input.setCurrentIndex(max(0, theme_index))
        appearance_form.addRow("与宠物间距", self.countdown_gap_input)
        appearance_form.addRow("最小宽度", self.countdown_width_input)
        appearance_form.addRow("卡片高度", self.countdown_height_input)
        appearance_form.addRow("倒计时背景", self.countdown_theme_input)
        layout.addWidget(appearance)
        layout.addStretch(1)

        self.schedule_mode_input.currentIndexChanged.connect(self.mode_stack.setCurrentIndex)
        self.schedule_mode_input.currentIndexChanged.connect(self._update_schedule_validation)
        self.work_countdown_input.toggled.connect(self._update_countdown_controls)
        self.work_start_input.timeChanged.connect(self._update_schedule_validation)
        self.work_end_input.timeChanged.connect(self._update_schedule_validation)
        self.clock_in_start_input.timeChanged.connect(self._update_schedule_validation)
        self.clock_in_end_input.timeChanged.connect(self._update_schedule_validation)
        self.work_duration_input.valueChanged.connect(self._update_schedule_validation)
        self._update_countdown_controls()
        self.mode_stack.setCurrentIndex(self.schedule_mode_input.currentIndex())
        self._update_schedule_validation()
        return page

    def _build_fixed_schedule_page(self, parent: QWidget) -> QWidget:
        page = QWidget(parent)
        form = QFormLayout(page)
        self.work_start_input = QTimeEdit(self._qtime(self._settings.work_start_time, QTime(9, 0)), page)
        self.work_start_input.setDisplayFormat("HH:mm")
        self.work_end_input = QTimeEdit(self._qtime(self._settings.work_end_time, QTime(18, 0)), page)
        self.work_end_input.setDisplayFormat("HH:mm")
        form.addRow("统一上班时间", self.work_start_input)
        form.addRow("统一下班时间", self.work_end_input)
        return page

    def _build_elastic_schedule_page(self, parent: QWidget) -> QWidget:
        page = QWidget(parent)
        form = QFormLayout(page)
        self.clock_in_start_input = QTimeEdit(self._qtime(self._settings.clock_in_start_time, QTime(9, 30)), page)
        self.clock_in_start_input.setDisplayFormat("HH:mm")
        self.clock_in_end_input = QTimeEdit(self._qtime(self._settings.clock_in_end_time, QTime(10, 0)), page)
        self.clock_in_end_input.setDisplayFormat("HH:mm")
        self.work_duration_input = QSpinBox(page)
        self.work_duration_input.setRange(1, 24 * 60)
        self.work_duration_input.setSuffix(" 分钟")
        self.work_duration_input.setValue(self._settings.work_duration_minutes)
        form.addRow("允许打卡开始", self.clock_in_start_input)
        form.addRow("允许打卡结束", self.clock_in_end_input)
        form.addRow("打卡后工作时长", self.work_duration_input)
        return page

    @staticmethod
    def _qtime(value: str, fallback: QTime) -> QTime:
        parsed = QTime.fromString(value, "HH:mm")
        return parsed if parsed.isValid() else fallback

    def _reset_workdays(self) -> None:
        for index, checkbox in self.workday_inputs.items():
            checkbox.setChecked(index in {"0", "1", "2", "3", "4"})

    def _update_countdown_controls(self) -> None:
        enabled = self.work_countdown_input.isChecked()
        for widget in (
            self.schedule_mode_input,
            self.mode_stack,
            self.countdown_gap_input,
            self.countdown_width_input,
            self.countdown_height_input,
            self.countdown_theme_input,
        ):
            widget.setEnabled(enabled)
        for checkbox in self.workday_inputs.values():
            checkbox.setEnabled(enabled)
        self._update_schedule_validation()

    def _update_schedule_validation(self) -> None:
        """只在当前输入确实无效时给出局部提示，并禁用确认。"""
        if not hasattr(self, "schedule_error_label"):
            return
        mode = str(self.schedule_mode_input.currentData())
        if mode == "elastic":
            valid = (
                self.clock_in_start_input.time().msecsSinceStartOfDay()
                < self.clock_in_end_input.time().msecsSinceStartOfDay()
                and self.work_duration_input.value() > 0
            )
            message = "允许打卡开始时间必须早于结束时间。" if not valid else ""
        else:
            valid = self.work_start_input.time().msecsSinceStartOfDay() < self.work_end_input.time().msecsSinceStartOfDay()
            message = "上班时间必须早于下班时间。" if not valid else ""
        enabled = self.work_countdown_input.isChecked()
        self.schedule_error_label.setText(message)
        self.schedule_error_label.setVisible(enabled and bool(message))
        if hasattr(self, "button_box"):
            self.button_box.button(QDialogButtonBox.StandardButton.Ok).setEnabled(not enabled or valid)

    def _build_app_update_page(self) -> QWidget:
        page, layout = self._page("应用与更新", "查看当前版本，并在需要时手动检查新的 PetNest 安装包。", self)
        card, card_layout = self._card("程序版本", "更新检查不会影响当前宠物和设置。", page)
        from petnest import __version__

        self.current_version_label = QLabel(f"当前版本  {__version__}", card)
        card_layout.addWidget(self.current_version_label)
        if self._on_check_app_update is not None:
            self.app_update_button = QPushButton("检查程序更新…", card)
            self.app_update_button.setToolTip("从 PetNest GitHub Releases 检查新的安装包")
            self.app_update_button.clicked.connect(self._on_check_app_update)
            card_layout.addWidget(self.app_update_button, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(card)
        layout.addStretch(1)
        return page

    def updated_settings(self) -> Settings:
        """返回编辑副本；由应用层负责应用和持久化。"""
        if self.cursor_scale_slider.isEnabled():
            self.cursor_scale_slider.snap_to_node()
        daily_end_times = {
            key: self.work_end_input.time().toString("HH:mm") if checkbox.isChecked() else None
            for key, checkbox in self.workday_inputs.items()
        }
        legacy_end = next((value for value in daily_end_times.values() if value is not None), self._settings.work_end_time)
        return replace(
            self._settings,
            scale=self.scale_input.value(),
            always_on_top=self.always_on_top_input.isChecked(),
            mouse_interaction_enabled=self.mouse_interaction_input.isChecked(),
            mouse_follow_enabled=self.mouse_follow_input.isChecked(),
            mouse_follow_scale=self.mouse_follow_scale_input.value(),
            lan_interaction_enabled=self.lan_interaction_input.isChecked(),
            remote_interaction_enabled=self.remote_interaction_input.isChecked(),
            cursor_style_enabled=self.cursor_style_enabled_input.isChecked(),
            cursor_style_id=(
                str(self.cursor_style_input.currentData())
                if self.cursor_style_enabled_input.isChecked() and isinstance(self.cursor_style_input.currentData(), str)
                else None
            ),
            cursor_scale=self.cursor_scale_slider.value(),
            system_idle_enabled=self.system_idle_input.isChecked(),
            system_bored_seconds=self.system_bored_input.value(),
            system_sleep_seconds=max(self.system_sleep_input.value(), self.system_bored_input.value() + 1),
            work_countdown_enabled=self.work_countdown_input.isChecked(),
            work_start_time=self.work_start_input.time().toString("HH:mm"),
            work_end_time=legacy_end,
            daily_work_end_times=daily_end_times,
            work_schedule_mode=str(self.schedule_mode_input.currentData()),
            clock_in_start_time=self.clock_in_start_input.time().toString("HH:mm"),
            clock_in_end_time=self.clock_in_end_input.time().toString("HH:mm"),
            work_duration_minutes=self.work_duration_input.value(),
            countdown_gap=self.countdown_gap_input.value(),
            countdown_width=self.countdown_width_input.value(),
            countdown_height=self.countdown_height_input.value(),
            countdown_theme=str(self.countdown_theme_input.currentData()),
        )


__all__ = ["SettingsCenterDialog", "SnappingSlider"]
