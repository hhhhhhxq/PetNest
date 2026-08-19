"""PetNest 五分类设置中心。"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import replace
from datetime import date
from pathlib import Path

from PySide6.QtCore import QPoint, QSignalBlocker, QTime, Qt, QRect, QSize, Signal
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
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
    QAbstractSpinBox,
    QScrollArea,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QTimeEdit,
    QProgressBar,
    QRadioButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from petnest.core.cursor_style_catalog import CursorStyle
from petnest.core.codex_link import CodexHookStatus
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


class ToggleSwitch(QCheckBox):
    """跨平台自绘的 iOS 风格开关。"""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("toggleSwitch")
        self.setMinimumHeight(32)

    def sizeHint(self) -> QSize:
        base = super().sizeHint()
        return QSize(max(base.width() + 52, 160), max(base.height(), 32))

    def hitButton(self, pos: QPoint) -> bool:  # noqa: N802 - Qt override signature
        """让自绘的文字与开关轨道都属于实际可点击区域。"""
        return self.rect().contains(pos)

    def paintEvent(self, _event: object) -> None:  # noqa: ARG002 - Qt event signature
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        enabled = self.isEnabled()
        text_color = QColor("#4B4641") if enabled else QColor("#B7AAA3")
        painter.setPen(text_color)
        painter.drawText(
            QRect(0, 0, max(0, self.width() - 58), self.height()),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            self.text(),
        )
        track = QRect(self.width() - 46, (self.height() - 22) // 2, 44, 22)
        track_color = QColor("#D98663" if self.isChecked() else "#D9CEC7")
        if not enabled:
            track_color.setAlpha(120)
        painter.setBrush(track_color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(track, 11, 11)
        knob_x = track.right() - 18 if self.isChecked() else track.left() + 3
        knob = QRect(knob_x, track.top() + 3, 16, 16)
        knob_color = QColor("#FFFDF9")
        if not enabled:
            knob_color.setAlpha(180)
        painter.setBrush(knob_color)
        painter.drawEllipse(knob)


class DayChip(QCheckBox):
    """工作日的胶囊式多选标签。"""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setMinimumSize(72, 32)

    def sizeHint(self) -> QSize:
        return QSize(82, 32)

    def paintEvent(self, _event: object) -> None:  # noqa: ARG002 - Qt event signature
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        enabled = self.isEnabled()
        checked = self.isChecked()
        background = QColor("#FFF0E8" if checked else "#FBF5F0")
        border = QColor("#E8C7B8" if checked else "#E3D4CB")
        text_color = QColor("#A85D3E" if checked else "#9B8D84")
        if not enabled:
            background.setAlpha(110)
            border.setAlpha(110)
            text_color.setAlpha(110)
        painter.setBrush(background)
        painter.setPen(border)
        painter.drawRoundedRect(self.rect().adjusted(0, 1, -1, -1), 9, 9)
        painter.setPen(text_color)
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.text() + (" ✓" if checked else ""))


class SegmentRadioButton(QRadioButton):
    """不使用系统单选圆点的分段选择项。"""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setMinimumHeight(34)

    def sizeHint(self) -> QSize:
        return QSize(160, 34)

    def paintEvent(self, _event: object) -> None:  # noqa: ARG002 - Qt event signature
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        checked = self.isChecked()
        background = QColor("#FFFDF9" if checked else "#F5E8DF")
        border = QColor("#EBD8CD" if checked else "#F5E8DF")
        text_color = QColor("#A85D3E" if checked else "#8E8179")
        painter.setBrush(background)
        painter.setPen(border)
        painter.drawRoundedRect(self.rect().adjusted(0, 1, -1, -1), 10, 10)
        painter.setPen(text_color)
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.text())


class _FocusWheelMixin:
    """只有控件已获得焦点时才允许滚轮改值，否则交给外层滚动页面。"""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[misc]
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)  # type: ignore[attr-defined]

    def wheelEvent(self, event: object) -> None:  # noqa: N802 - Qt override signature
        if not self.hasFocus():
            event.ignore()  # type: ignore[attr-defined]
            return
        super().wheelEvent(event)  # type: ignore[misc]


class FocusWheelSpinBox(_FocusWheelMixin, QSpinBox):
    """避免滚动设置页时误改整数值。"""


class FocusWheelDoubleSpinBox(_FocusWheelMixin, QDoubleSpinBox):
    """避免滚动设置页时误改小数值。"""


class FocusWheelComboBox(_FocusWheelMixin, QComboBox):
    """避免滚动设置页时误切换选项。"""


class FocusWheelSlider(_FocusWheelMixin, QSlider):
    """避免滚动设置页时误改滑块值。"""


class PercentSlider(_FocusWheelMixin, QSlider):
    """以百分比直接展示桌宠缩放比例。"""

    def __init__(self, value: float, parent: QWidget | None = None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setRange(25, 200)
        self.setSingleStep(1)
        self.setPageStep(5)
        self.setValue(round(value * 100))


class FocusWheelSnappingSlider(_FocusWheelMixin, SnappingSlider):
    """可吸附节点且不会被页面滚轮误触的滑块。"""


class ClickableLabel(QLabel):
    """把普通标签变成只响应鼠标左键的轻量点击入口。"""

    clicked = Signal()

    def mouseReleaseEvent(self, event: object) -> None:  # noqa: N802 - Qt override signature
        if event.button() == Qt.MouseButton.LeftButton:  # type: ignore[attr-defined]
            self.clicked.emit()
        super().mouseReleaseEvent(event)  # type: ignore[arg-type]


class MinuteStepTimeEdit(_FocusWheelMixin, QTimeEdit):
    """时间输入按整分钟步进，避免短时间范围只能切换小时。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setDisplayFormat("HH:mm")
        self.setCurrentSection(QTimeEdit.Section.MinuteSection)

    def stepBy(self, steps: int) -> None:
        current = self.time().hour() * 60 + self.time().minute()
        minimum = self.minimumTime().hour() * 60 + self.minimumTime().minute()
        maximum = self.maximumTime().hour() * 60 + self.maximumTime().minute()
        target = max(minimum, min(maximum, current + int(steps)))
        if target != current:
            self.setTime(QTime(target // 60, target % 60))

    def stepEnabled(self) -> QAbstractSpinBox.StepEnabledFlags:
        current = self.time().hour() * 60 + self.time().minute()
        minimum = self.minimumTime().hour() * 60 + self.minimumTime().minute()
        maximum = self.maximumTime().hour() * 60 + self.maximumTime().minute()
        flags = QAbstractSpinBox.StepEnabledFlag(0)
        if current > minimum:
            flags |= QAbstractSpinBox.StepEnabledFlag.StepDownEnabled
        if current < maximum:
            flags |= QAbstractSpinBox.StepEnabledFlag.StepUpEnabled
        return flags


class SettingsCenterDialog(QDialog):
    """一个窗口承载桌宠显示、行为、联动、倒计时和更新设置。"""

    _PREFERRED_SIZE = QSize(1180, 760)
    _ROOMY_MINIMUM_SIZE = QSize(1000, 680)
    _SCREEN_MARGIN = 16

    _SECTION_NAMES = (
        ("display", "显示与窗口"),
        ("mouse_behavior", "鼠标与行为"),
        ("idle", "系统空闲"),
        ("codex_link", "Codex 联动"),
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
        on_download_app_update: Callable[[object], object] | None = None,
        on_unlock_codex_usage: Callable[[], object] | None = None,
        codex_hook_status: CodexHookStatus | None = None,
        codex_action_availability: Mapping[str, str] | None = None,
        on_install_codex_hook: Callable[[], CodexHookStatus] | None = None,
        on_remove_codex_hook: Callable[[], CodexHookStatus] | None = None,
        cursor_styles: list[CursorStyle] | None = None,
        supported_roles: Iterable[str] | None = None,
        pet_preview_path: Path | None = None,
        initial_section: str = "display",
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._cursor_styles = cursor_styles or []
        self._supported_roles = frozenset(supported_roles) if supported_roles is not None else None
        self._on_check_app_update = on_check_app_update
        self._on_download_app_update = on_download_app_update
        self._on_unlock_codex_usage = on_unlock_codex_usage
        self._codex_hook_status = codex_hook_status or CodexHookStatus(
            "missing", "尚未安装 PetNest Codex Hook", False
        )
        self._codex_action_availability = dict(codex_action_availability or {})
        self._on_install_codex_hook = on_install_codex_hook
        self._on_remove_codex_hook = on_remove_codex_hook
        self._version_click_count = 0
        self._pet_preview_path = pet_preview_path
        self._pet_preview_pixmap = QPixmap()
        self._app_update_info: object | None = None
        self.setObjectName("settingsCenter")
        self.setWindowTitle("PetNest 设置中心")
        self.setMinimumSize(self._ROOMY_MINIMUM_SIZE)
        self.resize(self._PREFERRED_SIZE)
        self.setStyleSheet(dialog_stylesheet())

        # 互动设置仍由互动窗口负责；保留隐藏兼容属性，不在设置中心页面呈现。
        self.lan_interaction_input = QCheckBox(self)
        self.lan_interaction_input.setChecked(settings.lan_interaction_enabled)
        self.lan_interaction_input.setVisible(False)
        self.lan_group_chat_notifications_input = QCheckBox(self)
        self.lan_group_chat_notifications_input.setChecked(
            settings.lan_group_chat_notifications_enabled
        )
        self.lan_group_chat_notifications_input.setVisible(False)
        self.remote_interaction_input = QCheckBox(self)
        self.remote_interaction_input.setChecked(settings.remote_interaction_enabled)
        self.remote_interaction_input.setVisible(False)

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(0)

        window_shell = QFrame(self)
        window_shell.setObjectName("windowShell")
        shell_layout = QVBoxLayout(window_shell)
        shell_layout.setContentsMargins(18, 18, 18, 16)
        shell_layout.setSpacing(16)

        header_bar = QFrame(window_shell)
        header_bar.setObjectName("headerBar")
        header_layout = QHBoxLayout(header_bar)
        header_layout.setContentsMargins(18, 13, 18, 13)
        brand_mark = QLabel("●", header_bar)
        brand_mark.setStyleSheet("color: #D98663; font-size: 25px; font-weight: 700;")
        header_layout.addWidget(brand_mark)
        header_text = QVBoxLayout()
        header_text.setSpacing(1)
        brand_title = QLabel("PetNest 设置中心", header_bar)
        brand_title.setStyleSheet("font-size: 18px; font-weight: 700; color: #4B4641;")
        brand_subtitle = QLabel("让桌宠更贴合你的桌面与工作节奏", header_bar)
        brand_subtitle.setObjectName("mutedLabel")
        header_text.addWidget(brand_title)
        header_text.addWidget(brand_subtitle)
        header_layout.addLayout(header_text)
        header_layout.addStretch(1)
        close_hint = QLabel("×", header_bar)
        close_hint.setStyleSheet("font-size: 23px; color: #A7978E;")
        header_layout.addWidget(close_hint)
        shell_layout.addWidget(header_bar)

        body = QHBoxLayout()
        body.setSpacing(18)
        sidebar = QFrame(window_shell)
        sidebar.setObjectName("settingsSidebar")
        sidebar.setFixedWidth(246)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(16, 18, 16, 16)
        sidebar_layout.setSpacing(10)
        sidebar_title = QLabel("偏好设置", sidebar)
        sidebar_title.setObjectName("mutedLabel")
        sidebar_title.setStyleSheet("font-size: 12px; font-weight: 700; letter-spacing: 1px;")
        sidebar_layout.addWidget(sidebar_title)
        self.section_list = QListWidget(sidebar)
        self.section_list.setObjectName("settingsNavigation")
        self.section_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.section_list.setFrameShape(QFrame.Shape.NoFrame)
        for _key, label in self._SECTION_NAMES:
            self.section_list.addItem(QListWidgetItem(label))
        sidebar_layout.addWidget(self.section_list, 1)
        self.status_title = QLabel("当前状态", sidebar)
        self.status_title.setObjectName("mutedLabel")
        self.status_title.setStyleSheet("font-size: 12px; font-weight: 700; letter-spacing: 1px;")
        sidebar_layout.addWidget(self.status_title)
        self.status_card = QFrame(sidebar)
        self.status_card.setObjectName("statusCard")
        status_layout = QVBoxLayout(self.status_card)
        status_layout.setContentsMargins(14, 11, 14, 11)
        status_row = QHBoxLayout()
        status_dot = QLabel("●", self.status_card)
        status_dot.setStyleSheet("color: #6D9A7A; font-size: 15px;")
        status_row.addWidget(status_dot)
        status_label = QLabel("桌宠在线", self.status_card)
        status_label.setStyleSheet("color: #6B625D; font-size: 14px;")
        status_row.addWidget(status_label)
        status_row.addStretch(1)
        status_layout.addLayout(status_row)
        current_pet = QLabel(f"当前宠物 · {self._settings.current_pet_id or '未选择'}", self.status_card)
        current_pet.setObjectName("mutedLabel")
        current_pet.setWordWrap(True)
        status_layout.addWidget(current_pet)
        sidebar_layout.addWidget(self.status_card)
        body.addWidget(sidebar)

        content_pane = QFrame(window_shell)
        content_pane.setObjectName("contentPane")
        content_layout = QVBoxLayout(content_pane)
        content_layout.setContentsMargins(10, 8, 8, 0)
        content_layout.setSpacing(4)
        self.page_title = QLabel(content_pane)
        self.page_title.setObjectName("contentTitle")
        self.page_description = QLabel(content_pane)
        self.page_description.setObjectName("contentDescription")
        self.page_description.setWordWrap(True)
        content_layout.addWidget(self.page_title)
        content_layout.addWidget(self.page_description)

        self.page_stack = QStackedWidget(content_pane)
        self.page_stack.setObjectName("settingsPageStack")
        self.page_stack.addWidget(self._build_display_page())
        self.page_stack.addWidget(self._build_mouse_behavior_page())
        self.page_stack.addWidget(self._build_idle_page())
        self.page_stack.addWidget(self._build_codex_link_page())
        self.page_stack.addWidget(self._build_countdown_page())
        self.page_stack.addWidget(self._build_app_update_page())
        scroll = QScrollArea(content_pane)
        scroll.setObjectName("settingsScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(self.page_stack)
        self.settings_scroll = scroll
        content_layout.addWidget(scroll, 1)
        body.addWidget(content_pane, 1)
        shell_layout.addLayout(body, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            window_shell,
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("应用并关闭")
        buttons.button(QDialogButtonBox.StandardButton.Ok).setObjectName("primaryButton")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.button_box = buttons
        footer = QHBoxLayout()
        footer.setContentsMargins(10, 0, 8, 0)
        footer_hint = QLabel("修改会在应用并关闭后保存", window_shell)
        footer_hint.setObjectName("mutedLabel")
        footer.addWidget(footer_hint)
        footer.addStretch(1)
        footer.addWidget(buttons)
        shell_layout.addLayout(footer)
        root.addWidget(window_shell)

        self.section_list.currentRowChanged.connect(self._change_section)
        self.section_list.setCurrentRow(self._section_index(initial_section))
        screen = self.screen() or QApplication.primaryScreen()
        if screen is not None:
            self._fit_to_available_geometry(screen.availableGeometry())

    def _fit_to_available_geometry(self, available: QRect) -> None:
        """在小屏或高 DPI 环境中保住导航，空间充足时保持设计尺寸。"""
        usable_width = max(1, available.width() - self._SCREEN_MARGIN * 2)
        usable_height = max(1, available.height() - self._SCREEN_MARGIN * 2)
        constrained = (
            usable_width < self._ROOMY_MINIMUM_SIZE.width()
            or usable_height < self._ROOMY_MINIMUM_SIZE.height()
        )
        short_screen = usable_height < self._ROOMY_MINIMUM_SIZE.height()
        self.status_title.setVisible(not short_screen)
        self.status_card.setVisible(not short_screen)

        navigation_height = sum(
            max(1, self.section_list.sizeHintForRow(row))
            for row in range(self.section_list.count())
        )
        frame_height = self.section_list.frameWidth() * 2
        navigation_padding = 16  # 与 settingsNavigation 的上下 QSS padding 一致。
        self.section_list.setMinimumHeight(navigation_height + frame_height + navigation_padding)

        if constrained:
            self.setMinimumSize(
                min(self._ROOMY_MINIMUM_SIZE.width(), usable_width),
                min(self.minimumSizeHint().height(), usable_height),
            )
        else:
            self.setMinimumSize(self._ROOMY_MINIMUM_SIZE)
        self.resize(
            min(self._PREFERRED_SIZE.width(), usable_width),
            min(self._PREFERRED_SIZE.height(), usable_height),
        )

    def _section_index(self, section: str) -> int:
        aliases = {
            "显示与窗口": 0,
            "鼠标与行为": 1,
            "系统空闲": 2,
            "Codex 联动": 3,
            "工作倒计时": 4,
            "应用与更新": 5,
            "mouse": 1,
            "idle": 2,
            "codex": 3,
            "work_countdown": 4,
            "update": 5,
        }
        return aliases.get(section, next((i for i, (key, _label) in enumerate(self._SECTION_NAMES) if key == section), 0))

    def select_section(self, section: str) -> None:
        """供托盘不同入口激活同一窗口时切换分类。"""
        self.section_list.setCurrentRow(self._section_index(section))

    def _change_section(self, index: int) -> None:
        if index < 0:
            return
        self.page_stack.setCurrentIndex(index)
        self.settings_scroll.verticalScrollBar().setValue(0)
        self.settings_scroll.horizontalScrollBar().setValue(0)
        self.page_title.setText(self._SECTION_NAMES[index][1])
        descriptions = (
            "调整桌宠在桌面上的显示方式",
            "控制宠物如何响应鼠标和系统光标",
            "让宠物在长时间没有操作时自动改变状态",
            "让当前宠物跟随本机 Codex 的运行、等待和完成状态",
            "工作日只选择一次，再选择固定时段或弹性打卡的计算方式",
            "查看当前版本，并在需要时手动检查新的 PetNest 安装包",
        )
        self.page_description.setText(descriptions[index])

    @staticmethod
    def _page(title: str, description: str, parent: QWidget) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget(parent)
        page.setObjectName("settingsPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 18, 10, 8)
        layout.setSpacing(14)
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
        scale_row = QWidget(card)
        scale_layout = QVBoxLayout(scale_row)
        scale_layout.setContentsMargins(0, 0, 0, 0)
        scale_value_row = QHBoxLayout()
        self.scale_input = PercentSlider(self._settings.scale, scale_row)
        scale_value_row.addWidget(self.scale_input, 1)
        self.scale_value_label = QLabel(scale_row)
        self.scale_value_label.setObjectName("accentValue")
        self.scale_value_label.setMinimumWidth(52)
        self.scale_value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        scale_value_row.addWidget(self.scale_value_label)
        scale_layout.addLayout(scale_value_row)
        scale_range_row = QHBoxLayout()
        scale_min_label = QLabel("25%", scale_row)
        scale_min_label.setObjectName("mutedLabel")
        scale_max_label = QLabel("200%", scale_row)
        scale_max_label.setObjectName("mutedLabel")
        scale_range_row.addWidget(scale_min_label)
        scale_range_row.addStretch(1)
        scale_range_row.addWidget(scale_max_label)
        scale_layout.addLayout(scale_range_row)
        self.always_on_top_input = ToggleSwitch("始终置顶", card)
        self.always_on_top_input.setChecked(self._settings.always_on_top)
        self.mouse_interaction_input = ToggleSwitch("启用鼠标交互", card)
        self.mouse_interaction_input.setChecked(self._settings.mouse_interaction_enabled)
        form.addRow("桌宠大小", scale_row)
        form.addRow("窗口层级", self.always_on_top_input)
        card_layout.addLayout(form)
        preview = QFrame(page)
        preview.setObjectName("previewCard")
        preview_layout = QVBoxLayout(preview)
        preview_layout.setContentsMargins(18, 15, 18, 15)
        preview_title = QLabel("实时预览", preview)
        preview_title.setStyleSheet("color: #B07962; font-size: 12px; font-weight: 600;")
        preview_layout.addWidget(preview_title)
        self.pet_preview_label = QLabel(preview)
        self.pet_preview_label.setObjectName("petPreviewImage")
        self.pet_preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pet_preview_label.setMinimumSize(180, 150)
        self.pet_preview_label.setStyleSheet("color: #A7978E; font-size: 13px;")
        if self._pet_preview_path is not None:
            self._pet_preview_pixmap = QPixmap(str(self._pet_preview_path))
        preview_layout.addWidget(self.pet_preview_label, 1)
        preview_caption = QLabel("显示比例会立即影响当前桌宠大小", preview)
        preview_caption.setObjectName("mutedLabel")
        preview_caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview_layout.addWidget(preview_caption)
        row = QHBoxLayout()
        row.addWidget(card, 3)
        row.addWidget(preview, 2)
        layout.addLayout(row)
        secondary, secondary_layout = self._card("鼠标交互", "允许拖动、点击和右键操作桌宠。", page)
        secondary_layout.addWidget(self.mouse_interaction_input)
        layout.addWidget(secondary)
        layout.addStretch(1)
        self.scale_input.valueChanged.connect(self._update_pet_preview)
        self.scale_input.valueChanged.connect(self._update_scale_value_label)
        self._update_scale_value_label(self.scale_input.value())
        self._update_pet_preview()
        return page

    def _update_pet_preview(self) -> None:
        """在设置中心显示当前宠物的真实首帧，而不是占位符。"""
        if self._pet_preview_pixmap.isNull():
            self.pet_preview_label.clear()
            self.pet_preview_label.setText("暂无宠物预览")
            return
        size = max(64, min(190, round(150 * self.scale_input.value() / 100)))
        self.pet_preview_label.setText("")
        self.pet_preview_label.setPixmap(
            self._pet_preview_pixmap.scaled(
                size,
                size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def _update_scale_value_label(self, value: int) -> None:
        self.scale_value_label.setText(f"{value}%")

    def _build_mouse_behavior_page(self) -> QWidget:
        page, layout = self._page("鼠标与行为", "决定桌宠如何跟随鼠标，以及系统自定义鼠标的显示方式。", self)
        behavior_card, behavior_layout = self._card("跟随行为", "关闭跟随后，宠物大小不会再随光标变化。", page)
        behavior_form = QFormLayout()
        self.mouse_follow_input = ToggleSwitch("跟随鼠标", behavior_card)
        self.mouse_follow_input.setChecked(self._settings.mouse_follow_enabled)
        self.mouse_follow_scale_input = FocusWheelDoubleSpinBox(behavior_card)
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
        self.cursor_style_enabled_input = ToggleSwitch("使用自定义鼠标样式", cursor_card)
        self.cursor_style_enabled_input.setChecked(self._settings.cursor_style_enabled)
        self.cursor_style_input = FocusWheelComboBox(cursor_card)
        self.cursor_style_input.addItem("系统默认", None)
        for style in self._cursor_styles:
            self.cursor_style_input.addItem(style.display_name, style.identifier)
        selected_index = self.cursor_style_input.findData(self._settings.cursor_style_id)
        self.cursor_style_input.setCurrentIndex(max(0, selected_index))
        cursor_layout.addWidget(self.cursor_style_enabled_input)
        cursor_form = QFormLayout()
        cursor_form.addRow("鼠标主题", self.cursor_style_input)
        self.cursor_scale_slider = FocusWheelSnappingSlider(cursor_card)
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
        card, card_layout = self._card("自动空闲动作", "根据系统无操作时间切换宠物状态。", page)
        self.system_idle_input = ToggleSwitch("启用系统空闲动作", card)
        self.system_idle_input.setChecked(self._settings.system_idle_enabled)
        card_layout.addWidget(self.system_idle_input)
        form = QFormLayout()
        self.system_bored_input = FocusWheelSpinBox(card)
        self.system_bored_input.setRange(1, 86_400)
        self.system_bored_input.setSuffix(" 秒")
        self.system_bored_input.setValue(self._settings.system_bored_seconds)
        self.system_sleep_input = FocusWheelSpinBox(card)
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

    def _build_codex_link_page(self) -> QWidget:
        page, layout = self._page(
            "Codex 联动",
            "通过本机 Codex Hooks 同步任务状态；不会读取提示词、回复正文、代码或账号凭据。",
            self,
        )

        link_card, link_layout = self._card(
            "联动开关与 Hook",
            "Hook 只向 127.0.0.1 发送脱敏状态。首次安装后请在 Codex 的 /hooks 页面确认信任。",
            page,
        )
        self.codex_link_enabled_input = ToggleSwitch("跟随 Codex 状态播放动作", link_card)
        self.codex_link_enabled_input.setChecked(self._settings.codex_link_enabled)
        link_layout.addWidget(self.codex_link_enabled_input)
        self.codex_hook_status_label = QLabel(self._codex_hook_status.message, link_card)
        self.codex_hook_status_label.setWordWrap(True)
        self.codex_hook_status_label.setObjectName("mutedLabel")
        link_layout.addWidget(self.codex_hook_status_label)
        hook_buttons = QHBoxLayout()
        self.codex_hook_install_button = QPushButton("安装/修复 Hook", link_card)
        self.codex_hook_remove_button = QPushButton("移除 PetNest Hook", link_card)
        self.codex_hook_install_button.setEnabled(self._on_install_codex_hook is not None)
        self.codex_hook_remove_button.setEnabled(
            self._on_remove_codex_hook is not None and self._codex_hook_status.installed
        )
        self.codex_hook_install_button.clicked.connect(self._install_codex_hook)
        self.codex_hook_remove_button.clicked.connect(self._remove_codex_hook)
        hook_buttons.addWidget(self.codex_hook_install_button)
        hook_buttons.addWidget(self.codex_hook_remove_button)
        hook_buttons.addStretch(1)
        link_layout.addLayout(hook_buttons)
        layout.addWidget(link_card)

        action_card, action_layout = self._card(
            "状态动作",
            "动作缺失时安全回退到 idle；最终成功或失败无法由稳定版 Hooks 精确区分，Stop 统一进入 review。",
            page,
        )
        self.codex_action_status_labels: dict[str, QLabel] = {}
        action_names = (
            ("working", "运行中 running"),
            ("waiting", "等待处理 waiting"),
            ("error", "工具失败 failed"),
            ("review", "停止待查看 review"),
        )
        action_form = QFormLayout()
        for action, title in action_names:
            resolved = self._codex_action_availability.get(action, "idle（回退）")
            label = QLabel(resolved, action_card)
            label.setObjectName("mutedLabel")
            self.codex_action_status_labels[action] = label
            action_form.addRow(title, label)
        action_layout.addLayout(action_form)
        layout.addWidget(action_card)

        notice_card, notice_layout = self._card(
            "提醒方式",
            "运行中只播放动画；需要处理和任务停止时可单独显示气泡。",
            page,
        )
        self.codex_attention_bubbles_input = ToggleSwitch("等待或失败时显示气泡", notice_card)
        self.codex_attention_bubbles_input.setChecked(self._settings.codex_link_show_attention_bubbles)
        self.codex_review_bubbles_input = ToggleSwitch("任务停止时显示完成气泡", notice_card)
        self.codex_review_bubbles_input.setChecked(self._settings.codex_link_show_review_bubbles)
        notice_layout.addWidget(self.codex_attention_bubbles_input)
        notice_layout.addWidget(self.codex_review_bubbles_input)
        layout.addWidget(notice_card)
        layout.addStretch(1)

        self.codex_link_enabled_input.toggled.connect(self._update_codex_link_controls)
        self._update_codex_link_controls()
        return page

    def _update_codex_link_controls(self) -> None:
        enabled = self.codex_link_enabled_input.isChecked()
        self.codex_attention_bubbles_input.setEnabled(enabled)
        self.codex_review_bubbles_input.setEnabled(enabled)

    def _install_codex_hook(self) -> None:
        if self._on_install_codex_hook is None:
            return
        try:
            status = self._on_install_codex_hook()
        except Exception as error:  # noqa: BLE001 - 设置页必须就地报告文件错误。
            status = CodexHookStatus("error", f"安装 Hook 失败：{error}", False)
        self.set_codex_hook_status(status)

    def _remove_codex_hook(self) -> None:
        if self._on_remove_codex_hook is None:
            return
        try:
            status = self._on_remove_codex_hook()
        except Exception as error:  # noqa: BLE001 - 设置页必须就地报告文件错误。
            status = CodexHookStatus("error", f"移除 Hook 失败：{error}", True)
        self.set_codex_hook_status(status)

    def set_codex_hook_status(self, status: CodexHookStatus) -> None:
        self._codex_hook_status = status
        self.codex_hook_status_label.setText(status.message)
        self.codex_hook_remove_button.setEnabled(self._on_remove_codex_hook is not None and status.installed)

    def _build_countdown_page(self) -> QWidget:
        page, layout = self._page("工作倒计时", "工作日只选择一次，再选择固定时段或弹性打卡的计算方式。", self)
        schedule_card, schedule_layout = self._card("工作安排", "选择工作日和时间计算方式，其他设置按需展开。", page)
        self.work_countdown_input = ToggleSwitch("显示工作倒计时", schedule_card)
        self.work_countdown_input.setChecked(self._settings.work_countdown_enabled)
        schedule_layout.addWidget(self.work_countdown_input)

        workday_selector = QFrame(schedule_card)
        workday_selector.setObjectName("workdaySelector")
        workday_layout = QVBoxLayout(workday_selector)
        workday_layout.setContentsMargins(0, 4, 0, 4)
        workday_heading = QHBoxLayout()
        workday_heading.addWidget(QLabel("工作日", workday_selector))
        workday_heading.addWidget(QLabel("周一至周日均可选择", workday_selector))
        workday_heading.itemAt(1).widget().setObjectName("mutedLabel")
        workday_heading.addStretch(1)
        workday_layout.addLayout(workday_heading)
        workday_row = QHBoxLayout()
        self.workday_inputs: dict[str, QCheckBox] = {}
        for index, name in enumerate(self._WEEKDAYS):
            checkbox = DayChip(name, workday_selector)
            checkbox.setChecked(self._settings.daily_work_end_times.get(str(index)) is not None)
            self.workday_inputs[str(index)] = checkbox
            workday_row.addWidget(checkbox)
        workday_layout.addLayout(workday_row)
        shortcut_row = QHBoxLayout()
        all_days = QPushButton("工作日全选", workday_selector)
        weekdays = QPushButton("周末设为休息日", workday_selector)
        reset_days = QPushButton("恢复默认", workday_selector)
        all_days.clicked.connect(lambda: [item.setChecked(True) for item in self.workday_inputs.values()])
        weekdays.clicked.connect(lambda: [item.setChecked(index < 5) for index, item in enumerate(self.workday_inputs.values())])
        reset_days.clicked.connect(self._reset_workdays)
        shortcut_row.addWidget(all_days)
        shortcut_row.addWidget(weekdays)
        shortcut_row.addWidget(reset_days)
        shortcut_row.addStretch(1)
        workday_layout.addLayout(shortcut_row)
        schedule_layout.addWidget(workday_selector)

        mode_heading = QHBoxLayout()
        mode_heading.addWidget(QLabel("时间计算方式", schedule_card))
        mode_heading_hint = QLabel("弹性打卡会显示独立打卡入口，不改变原倒计时气泡。", schedule_card)
        mode_heading_hint.setObjectName("mutedLabel")
        mode_heading.addWidget(mode_heading_hint)
        mode_heading.addStretch(1)
        schedule_layout.addLayout(mode_heading)

        self.schedule_mode_input = FocusWheelComboBox(schedule_card)
        self.schedule_mode_input.addItem("固定时间", "fixed")
        self.schedule_mode_input.addItem("弹性打卡", "elastic")
        self.schedule_mode_input.setCurrentIndex(max(0, self.schedule_mode_input.findData(self._settings.work_schedule_mode)))
        self.schedule_mode_input.setVisible(False)
        schedule_layout.addWidget(self.schedule_mode_input)
        schedule_mode_switch = QFrame(schedule_card)
        schedule_mode_switch.setObjectName("scheduleModeSwitch")
        schedule_mode_layout = QHBoxLayout(schedule_mode_switch)
        schedule_mode_layout.setContentsMargins(6, 5, 6, 5)
        self.fixed_schedule_radio = SegmentRadioButton("固定时间", schedule_mode_switch)
        self.elastic_schedule_radio = SegmentRadioButton("弹性打卡", schedule_mode_switch)
        schedule_mode_layout.addWidget(self.fixed_schedule_radio, 1)
        schedule_mode_layout.addWidget(self.elastic_schedule_radio, 1)
        schedule_layout.addWidget(schedule_mode_switch)
        self.fixed_schedule_radio.setChecked(self.schedule_mode_input.currentData() == "fixed")
        self.elastic_schedule_radio.setChecked(self.schedule_mode_input.currentData() == "elastic")

        self.mode_stack = QStackedWidget(schedule_card)
        self.mode_stack.addWidget(self._build_fixed_schedule_page(schedule_card))
        self.mode_stack.addWidget(self._build_elastic_schedule_page(schedule_card))
        schedule_layout.addWidget(self.mode_stack)
        self.schedule_error_label = QLabel("", schedule_card)
        self.schedule_error_label.setStyleSheet("color: #C66C62;")
        self.schedule_error_label.setWordWrap(True)
        self.schedule_error_label.hide()
        schedule_layout.addWidget(self.schedule_error_label)
        layout.addWidget(schedule_card)

        appearance = QFrame(page)
        appearance.setObjectName("advancedSettings")
        appearance_layout = QVBoxLayout(appearance)
        appearance_layout.setContentsMargins(14, 6, 14, 6)
        self.advanced_appearance_toggle = QToolButton(appearance)
        self.advanced_appearance_toggle.setText("高级外观设置")
        self.advanced_appearance_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.advanced_appearance_toggle.setArrowType(Qt.ArrowType.DownArrow)
        self.advanced_appearance_toggle.setCheckable(True)
        appearance_layout.addWidget(self.advanced_appearance_toggle)
        self.advanced_appearance_panel = QFrame(appearance)
        appearance_panel_layout = QFormLayout(self.advanced_appearance_panel)
        self.advanced_appearance_panel.setVisible(False)
        appearance_layout.addWidget(self.advanced_appearance_panel)
        appearance_form = appearance_panel_layout
        self.countdown_gap_input = FocusWheelSpinBox(self.advanced_appearance_panel)
        self.countdown_gap_input.setRange(0, 80)
        self.countdown_gap_input.setSuffix(" 像素")
        self.countdown_gap_input.setValue(self._settings.countdown_gap)
        self.countdown_width_input = FocusWheelSpinBox(self.advanced_appearance_panel)
        self.countdown_width_input.setRange(110, 420)
        self.countdown_width_input.setSuffix(" 像素")
        self.countdown_width_input.setValue(self._settings.countdown_width)
        self.countdown_height_input = FocusWheelSpinBox(self.advanced_appearance_panel)
        self.countdown_height_input.setRange(26, 100)
        self.countdown_height_input.setSuffix(" 像素")
        self.countdown_height_input.setValue(self._settings.countdown_height)
        self.countdown_theme_input = FocusWheelComboBox(self.advanced_appearance_panel)
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

        self.schedule_mode_input.currentIndexChanged.connect(self._change_schedule_mode)
        self.fixed_schedule_radio.toggled.connect(lambda checked: checked and self._set_schedule_mode_index(0))
        self.elastic_schedule_radio.toggled.connect(lambda checked: checked and self._set_schedule_mode_index(1))
        self.advanced_appearance_toggle.toggled.connect(self._toggle_advanced_appearance)
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

    def _set_schedule_mode_index(self, index: int) -> None:
        if self.schedule_mode_input.currentIndex() != index:
            self.schedule_mode_input.setCurrentIndex(index)

    def _change_schedule_mode(self, index: int) -> None:
        self.mode_stack.setCurrentIndex(index)
        blocker = QSignalBlocker(self.fixed_schedule_radio)
        self.fixed_schedule_radio.setChecked(index == 0)
        del blocker
        blocker = QSignalBlocker(self.elastic_schedule_radio)
        self.elastic_schedule_radio.setChecked(index == 1)
        del blocker
        self._update_schedule_validation()

    def _toggle_advanced_appearance(self, expanded: bool) -> None:
        self.advanced_appearance_panel.setVisible(expanded)
        self.advanced_appearance_toggle.setArrowType(Qt.ArrowType.UpArrow if expanded else Qt.ArrowType.DownArrow)

    def _build_fixed_schedule_page(self, parent: QWidget) -> QWidget:
        page = QWidget(parent)
        form = QFormLayout(page)
        self.work_start_input = MinuteStepTimeEdit(page)
        self.work_start_input.setTime(self._qtime(self._settings.work_start_time, QTime(9, 0)))
        self.work_end_input = MinuteStepTimeEdit(page)
        self.work_end_input.setTime(self._qtime(self._settings.work_end_time, QTime(18, 0)))
        form.addRow("统一上班时间", self.work_start_input)
        form.addRow("统一下班时间", self.work_end_input)
        return page

    def _build_elastic_schedule_page(self, parent: QWidget) -> QWidget:
        page = QWidget(parent)
        layout = QVBoxLayout(page)
        form = QFormLayout()
        self.clock_in_start_input = MinuteStepTimeEdit(page)
        self.clock_in_start_input.setTime(self._qtime(self._settings.clock_in_start_time, QTime(9, 30)))
        self.clock_in_end_input = MinuteStepTimeEdit(page)
        self.clock_in_end_input.setTime(self._qtime(self._settings.clock_in_end_time, QTime(10, 0)))
        self.work_duration_input = FocusWheelDoubleSpinBox(page)
        self.work_duration_input.setRange(0.5, 24.0)
        self.work_duration_input.setDecimals(1)
        self.work_duration_input.setSingleStep(0.5)
        self.work_duration_input.setSuffix(" 小时")
        self.work_duration_input.setValue(self._settings.work_duration_minutes / 60.0)
        self.elastic_end_range_label = QLabel(page)
        self.elastic_end_range_label.setObjectName("mutedLabel")
        self.elastic_end_range_label.setWordWrap(True)
        form.addRow("允许打卡开始", self.clock_in_start_input)
        form.addRow("允许打卡结束", self.clock_in_end_input)
        form.addRow("打卡后工作时长", self.work_duration_input)
        form.addRow("", self.elastic_end_range_label)
        layout.addLayout(form)

        today_card = QFrame(page)
        today_card.setObjectName("todayClockInCard")
        today_layout = QVBoxLayout(today_card)
        today_layout.setContentsMargins(12, 10, 12, 10)
        today_title = QLabel("今日打卡", today_card)
        today_title.setStyleSheet("font-weight: 700;")
        today_layout.addWidget(today_title)
        self.today_clock_in_input = MinuteStepTimeEdit(today_card)
        self.today_clock_in_input.setToolTip("仅修改今天的打卡时间")
        self.today_clock_in_hint = QLabel(today_card)
        self.today_clock_in_hint.setObjectName("mutedLabel")
        self.today_clock_in_hint.setWordWrap(True)
        today_form = QFormLayout()
        today_form.addRow("打卡时间", self.today_clock_in_input)
        today_layout.addLayout(today_form)
        today_layout.addWidget(self.today_clock_in_hint)
        layout.addWidget(today_card)
        self._configure_today_clock_in()
        self.clock_in_start_input.timeChanged.connect(self._configure_today_clock_in)
        self.clock_in_end_input.timeChanged.connect(self._configure_today_clock_in)
        self.work_duration_input.valueChanged.connect(self._configure_today_clock_in)
        self.today_clock_in_input.timeChanged.connect(self._update_today_clock_in_hint)
        return page

    def _configure_today_clock_in(self) -> None:
        """按今天的已保存记录配置可编辑范围和预计下班提示。"""
        start = self.clock_in_start_input.time()
        end = self.clock_in_end_input.time()
        today = date.today().isoformat()
        recorded = self._qtime(self._settings.clock_in_time or "", QTime())
        has_record = self._settings.clock_in_date == today and bool(self._settings.clock_in_time) and recorded.isValid()
        valid_window = start.isValid() and end.isValid() and start < end
        self.today_clock_in_input.setEnabled(has_record and valid_window)
        if valid_window:
            latest = min(end, QTime.currentTime())
            if latest < start:
                latest = start
            self.today_clock_in_input.setMinimumTime(start)
            self.today_clock_in_input.setMaximumTime(latest)
        if not has_record:
            self.today_clock_in_hint.setText("今天尚未打卡；完成打卡后可在这里调整，仅影响今天。")
            return
        if valid_window:
            clamped = min(max(recorded, start), self.today_clock_in_input.maximumTime())
            self.today_clock_in_input.setTime(clamped)
            self._update_today_clock_in_hint()
        else:
            self.today_clock_in_hint.setText("请先设置有效的打卡时间范围。")

    def _update_today_clock_in_hint(self) -> None:
        if not self.today_clock_in_input.isEnabled():
            return
        end_text = self._format_end_time(
            self.today_clock_in_input.time(), round(self.work_duration_input.value() * 60)
        )
        self.today_clock_in_hint.setText(f"预计下班 {end_text} · 仅影响今天")

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
        self._update_elastic_end_range()
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

    def _update_elastic_end_range(self) -> None:
        if not hasattr(self, "elastic_end_range_label"):
            return
        start = self.clock_in_start_input.time()
        end = self.clock_in_end_input.time()
        if start >= end:
            self.elastic_end_range_label.setText("请先设置有效的打卡时间范围。")
            return
        duration_minutes = round(self.work_duration_input.value() * 60)
        earliest = self._format_end_time(start, duration_minutes)
        latest = self._format_end_time(end, duration_minutes)
        self.elastic_end_range_label.setText(
            f"预计下班时间：{earliest}–{latest}（按实际打卡时间计算）"
        )

    @staticmethod
    def _format_end_time(start: QTime, duration_minutes: int) -> str:
        total_minutes = start.hour() * 60 + start.minute() + duration_minutes
        return f"{(total_minutes // 60) % 24:02d}:{total_minutes % 60:02d}"

    def _build_app_update_page(self) -> QWidget:
        page, layout = self._page("应用与更新", "查看当前版本，并在需要时手动检查新的 PetNest 安装包。", self)
        card, card_layout = self._card("程序版本", "更新检查不会影响当前宠物和设置。", page)
        from petnest import __version__

        self.current_version_label = ClickableLabel(f"当前版本  {__version__}", card)
        self.current_version_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.current_version_label.clicked.connect(self._handle_version_click)
        card_layout.addWidget(self.current_version_label)
        self.codex_unlock_status_label = QLabel("Codex 用量入口已解锁", card)
        self.codex_unlock_status_label.setObjectName("mutedLabel")
        self.codex_unlock_status_label.hide()
        card_layout.addWidget(self.codex_unlock_status_label)
        self.app_update_status_label = QLabel("尚未检查更新。", card)
        self.app_update_status_label.setObjectName("mutedLabel")
        self.app_update_status_label.setWordWrap(True)
        card_layout.addWidget(self.app_update_status_label)
        self.app_update_notes_label = QLabel("", card)
        self.app_update_notes_label.setObjectName("mutedLabel")
        self.app_update_notes_label.setWordWrap(True)
        self.app_update_notes_label.hide()
        card_layout.addWidget(self.app_update_notes_label)
        self.app_update_progress = QProgressBar(card)
        self.app_update_progress.setRange(0, 100)
        self.app_update_progress.setValue(0)
        self.app_update_progress.setTextVisible(False)
        self.app_update_progress.hide()
        card_layout.addWidget(self.app_update_progress)
        if self._on_check_app_update is not None or self._on_download_app_update is not None:
            self.app_update_button = QPushButton("检查程序更新", card)
            self.app_update_button.setToolTip("从 PetNest GitHub Releases 检查新的安装包")
            self.app_update_button.clicked.connect(self._handle_app_update_button)
            card_layout.addWidget(self.app_update_button, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(card)
        layout.addStretch(1)
        return page

    def _handle_version_click(self) -> None:
        if self._settings.codex_usage_unlocked:
            return
        self._version_click_count += 1
        if self._version_click_count < 7:
            return
        self._settings = replace(self._settings, codex_usage_unlocked=True)
        self.codex_unlock_status_label.show()
        if self._on_unlock_codex_usage is not None:
            self._on_unlock_codex_usage()

    def _handle_app_update_button(self) -> None:
        if self._app_update_info is not None and self._on_download_app_update is not None:
            self._on_download_app_update(self._app_update_info)
        elif self._on_check_app_update is not None:
            self._on_check_app_update()

    def set_app_update_checking(self) -> None:
        if not hasattr(self, "app_update_button"):
            return
        self._app_update_info = None
        self.app_update_button.setText("检查中…")
        self.app_update_button.setEnabled(False)
        self.app_update_status_label.setText("正在检查 PetNest 更新…")
        self.app_update_notes_label.hide()
        self.app_update_progress.hide()

    def set_app_update_no_update(self) -> None:
        if not hasattr(self, "app_update_button"):
            return
        self._app_update_info = None
        self.app_update_button.setText("检查程序更新")
        self.app_update_button.setEnabled(True)
        self.app_update_status_label.setText("当前已经是最新版本。")
        self.app_update_notes_label.hide()
        self.app_update_progress.hide()

    def set_app_update_available(self, info: object) -> None:
        if not hasattr(self, "app_update_button"):
            return
        self._app_update_info = info
        version = str(getattr(info, "version", "新版本"))
        notes = str(getattr(info, "release_notes", "") or "").strip()
        self.app_update_button.setText("更新")
        self.app_update_button.setEnabled(True)
        self.app_update_status_label.setText(f"发现新版本 {version}。")
        self.app_update_notes_label.setText(notes)
        self.app_update_notes_label.setVisible(bool(notes))
        self.app_update_progress.hide()

    def set_app_update_downloading(self, progress: int = 0) -> None:
        if not hasattr(self, "app_update_button"):
            return
        progress = max(0, min(100, int(progress)))
        self.app_update_button.setText("下载中…")
        self.app_update_button.setEnabled(False)
        self.app_update_status_label.setText(f"正在下载更新（{progress}%）…")
        self.app_update_progress.setValue(progress)
        self.app_update_progress.show()

    def set_app_update_error(self, message: str) -> None:
        if not hasattr(self, "app_update_button"):
            return
        self._app_update_info = None
        self.app_update_button.setText("重新检查")
        self.app_update_button.setEnabled(True)
        self.app_update_status_label.setText(f"检查更新失败：{message}")
        self.app_update_notes_label.hide()
        self.app_update_progress.hide()

    def set_app_update_finished(self) -> None:
        if not hasattr(self, "app_update_button"):
            return
        self.app_update_button.setText("已准备安装")
        self.app_update_button.setEnabled(False)
        self.app_update_status_label.setText("更新包已准备完成，应用即将重启安装。")
        self.app_update_progress.setValue(100)
        self.app_update_progress.show()

    def updated_settings(self) -> Settings:
        """返回编辑副本；由应用层负责应用和持久化。"""
        if self.cursor_scale_slider.isEnabled():
            self.cursor_scale_slider.snap_to_node()
        daily_end_times = {
            key: self.work_end_input.time().toString("HH:mm") if checkbox.isChecked() else None
            for key, checkbox in self.workday_inputs.items()
        }
        legacy_end = next((value for value in daily_end_times.values() if value is not None), self._settings.work_end_time)
        clock_in_date = self._settings.clock_in_date
        clock_in_time = self._settings.clock_in_time
        if self.schedule_mode_input.currentData() == "elastic" and self.today_clock_in_input.isEnabled():
            clock_in_date = date.today().isoformat()
            clock_in_time = self.today_clock_in_input.time().toString("HH:mm")
        return replace(
            self._settings,
            scale=self.scale_input.value() / 100.0,
            always_on_top=self.always_on_top_input.isChecked(),
            mouse_interaction_enabled=self.mouse_interaction_input.isChecked(),
            mouse_follow_enabled=self.mouse_follow_input.isChecked(),
            mouse_follow_scale=self.mouse_follow_scale_input.value(),
            lan_interaction_enabled=self.lan_interaction_input.isChecked(),
            lan_group_chat_notifications_enabled=(
                self.lan_group_chat_notifications_input.isChecked()
            ),
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
            codex_link_enabled=self.codex_link_enabled_input.isChecked(),
            codex_link_show_attention_bubbles=self.codex_attention_bubbles_input.isChecked(),
            codex_link_show_review_bubbles=self.codex_review_bubbles_input.isChecked(),
            work_countdown_enabled=self.work_countdown_input.isChecked(),
            work_start_time=self.work_start_input.time().toString("HH:mm"),
            work_end_time=legacy_end,
            daily_work_end_times=daily_end_times,
            work_schedule_mode=str(self.schedule_mode_input.currentData()),
            clock_in_start_time=self.clock_in_start_input.time().toString("HH:mm"),
            clock_in_end_time=self.clock_in_end_input.time().toString("HH:mm"),
            work_duration_minutes=round(self.work_duration_input.value() * 60),
            clock_in_date=clock_in_date,
            clock_in_time=clock_in_time,
            countdown_gap=self.countdown_gap_input.value(),
            countdown_width=self.countdown_width_input.value(),
            countdown_height=self.countdown_height_input.value(),
            countdown_theme=str(self.countdown_theme_input.currentData()),
        )


__all__ = ["SettingsCenterDialog", "SnappingSlider"]
