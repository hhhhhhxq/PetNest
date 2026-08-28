# 跨平台导航栏自适应实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 让设置中心与“宠物与动作”导航基于 Qt 实际字体、图标和样式度量自动调整，在跨平台、大字体、不同缩放及短屏环境中保持无重叠、无不可访问项目。

**架构：** 新建一个专注于导航几何的 `AdaptiveNavigationList`，由自定义 delegate 计算每行可靠尺寸，并在字体、样式、屏幕或 DPI 变化后合并重算。两个宿主窗口继续拥有各自的 QSS 和业务信号，只消费组件给出的完整内容高度与推荐宽度，并在空间不足时让列表滚动。

**技术栈：** Python 3.12、PySide6/Qt 6、pytest、pytest-qt

---

## 文件结构

- 创建 `src/petnest/ui/adaptive_navigation.py`：共享导航列表、项目尺寸代理和侧栏宽度约束函数。
- 创建 `tests/test_adaptive_navigation.py`：共享组件在普通字体、大字体、图标、空列表、运行时变化和空间不足时的单元测试。
- 修改 `src/petnest/ui/settings_center_dialog.py:10-53,399-438,512-548`：设置中心接入共享组件，保留短屏状态卡策略，并让侧栏宽度按内容受限增长。
- 修改 `tests/test_settings_dialog.py:11-24,417-472`：强化设置中心默认、短屏和大字体回归测试。
- 修改 `src/petnest/ui/pet_action_exchange_dialog.py:9-37,129-141,228-242`：宠物与动作导航接入共享组件，并在字体或窗口宽度变化时同步侧栏。
- 修改 `tests/test_pet_action_exchange_dialog.py:8-12,144-168`：验证默认视觉密度、大字体行高、侧栏增长和选中项稳定。

执行实现前，在独立 worktree 中打开本计划；不要把主工作区里现有的未跟踪素材或其他用户文件加入任何提交。

### 任务 1：实现共享自适应导航组件

**文件：**
- 创建：`src/petnest/ui/adaptive_navigation.py`
- 创建：`tests/test_adaptive_navigation.py`

- [ ] **步骤 1：编写共享组件失败测试**

创建 `tests/test_adaptive_navigation.py`：

```python
"""Cross-platform geometry tests for adaptive sidebar navigation."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QMargins
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QListWidgetItem, QStyle

from petnest.ui.adaptive_navigation import (
    AdaptiveNavigationList,
    bounded_navigation_sidebar_width,
)


def _navigation() -> AdaptiveNavigationList:
    return AdaptiveNavigationList(
        minimum_row_height=40,
        vertical_padding=9,
        horizontal_padding=11,
        item_margin=2,
        outer_padding=QMargins(0, 6, 0, 6),
    )


def _assert_rows_do_not_overlap(navigation: AdaptiveNavigationList) -> None:
    rects = [
        navigation.visualItemRect(navigation.item(row))
        for row in range(navigation.count())
    ]
    assert all(rect.isValid() and rect.height() > 0 for rect in rects)
    assert all(first.bottom() < second.top() for first, second in zip(rects, rects[1:]))


def test_navigation_metrics_cover_text_icons_and_outer_padding(qtbot) -> None:
    navigation = _navigation()
    qtbot.addWidget(navigation)
    navigation.addItem("导入宠物")
    icon = navigation.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon)
    navigation.addItem(QListWidgetItem(icon, "宠物商店"))
    navigation.show()
    navigation.reflow()

    _assert_rows_do_not_overlap(navigation)
    assert navigation.sizeHintForRow(0) >= 40
    assert navigation.sizeHintForRow(1) >= 40
    assert navigation.full_content_height() >= sum(
        navigation.sizeHintForRow(row) for row in range(navigation.count())
    ) + 12
    assert navigation.recommended_content_width() >= navigation.fontMetrics().horizontalAdvance(
        "宠物商店"
    )


def test_navigation_reflows_after_runtime_font_change_without_changing_selection(qtbot) -> None:
    navigation = _navigation()
    qtbot.addWidget(navigation)
    navigation.addItems(["导入宠物", "宠物商店", "导入动作"])
    navigation.setCurrentRow(1)
    navigation.show()
    navigation.reflow()
    original_height = navigation.sizeHintForRow(0)

    font = QFont(navigation.font())
    font.setPointSize(max(24, font.pointSize() + 10))
    navigation.setFont(font)

    qtbot.waitUntil(lambda: navigation.sizeHintForRow(0) > original_height)
    _assert_rows_do_not_overlap(navigation)
    assert navigation.currentRow() == 1


def test_navigation_scrolls_instead_of_compressing_large_rows(qtbot) -> None:
    navigation = _navigation()
    qtbot.addWidget(navigation)
    navigation.addItems(["导入宠物", "宠物商店", "导入动作", "编辑动作", "导出动作"])
    font = QFont(navigation.font())
    font.setPointSize(24)
    navigation.setFont(font)
    navigation.setFixedHeight(100)
    navigation.show()

    qtbot.waitUntil(lambda: navigation.verticalScrollBar().maximum() > 0)
    row_heights = [navigation.sizeHintForRow(row) for row in range(navigation.count())]
    assert len(set(row_heights)) == 1
    assert row_heights[0] >= navigation.fontMetrics().height() + 22


def test_empty_navigation_has_safe_metrics(qtbot) -> None:
    navigation = _navigation()
    qtbot.addWidget(navigation)
    navigation.reflow()

    assert navigation.full_content_height() >= 12
    assert navigation.recommended_content_width() >= 0


def test_sidebar_width_grows_to_content_but_reserves_two_thirds_for_main_content() -> None:
    assert bounded_navigation_sidebar_width(
        base_width=145,
        available_width=1220,
        navigation_width=200,
        surrounding_width=22,
    ) == 222
    assert bounded_navigation_sidebar_width(
        base_width=145,
        available_width=1220,
        navigation_width=600,
        surrounding_width=22,
    ) == 406
```

- [ ] **步骤 2：运行测试确认模块尚不存在**

运行：

```bat
.\.venv\Scripts\python.exe -m pytest tests\test_adaptive_navigation.py -q
```

预期：测试收集失败，包含 `ModuleNotFoundError: No module named 'petnest.ui.adaptive_navigation'`。

- [ ] **步骤 3：编写最少共享组件实现**

创建 `src/petnest/ui/adaptive_navigation.py`：

```python
"""Font- and style-aware list navigation shared by PetNest dialogs."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QModelIndex, QMargins, QSize, QTimer, Qt, Signal
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QListWidget,
    QStyleOptionViewItem,
    QStyledItemDelegate,
    QWidget,
)


class _AdaptiveNavigationDelegate(QStyledItemDelegate):
    def __init__(
        self,
        *,
        minimum_row_height: int,
        vertical_padding: int,
        horizontal_padding: int,
        item_margin: int,
        icon_text_spacing: int,
        parent: QWidget,
    ) -> None:
        super().__init__(parent)
        self._minimum_row_height = max(1, int(minimum_row_height))
        self._vertical_padding = max(0, int(vertical_padding))
        self._horizontal_padding = max(0, int(horizontal_padding))
        self._item_margin = max(0, int(item_margin))
        self._icon_text_spacing = max(0, int(icon_text_spacing))

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:  # noqa: N802
        base = super().sizeHint(option, index)
        text = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        decoration = index.data(Qt.ItemDataRole.DecorationRole)
        icon_width = max(0, option.decorationSize.width()) if decoration is not None else 0
        icon_height = max(0, option.decorationSize.height()) if decoration is not None else 0
        content_height = max(option.fontMetrics.height(), icon_height)
        required_height = content_height + 2 * (
            self._vertical_padding + self._item_margin
        )
        required_width = option.fontMetrics.horizontalAdvance(text) + 2 * (
            self._horizontal_padding + self._item_margin
        )
        if decoration is not None:
            required_width += icon_width + self._icon_text_spacing
        return QSize(
            max(base.width(), required_width),
            max(base.height(), self._minimum_row_height, required_height),
        )


class AdaptiveNavigationList(QListWidget):
    """A QListWidget whose rows remain readable across fonts, styles and DPI."""

    metrics_changed = Signal(int, int)
    _METRIC_CHANGE_EVENTS = frozenset(
        {
            QEvent.Type.FontChange,
            QEvent.Type.ApplicationFontChange,
            QEvent.Type.StyleChange,
            QEvent.Type.LayoutDirectionChange,
            QEvent.Type.ScreenChangeInternal,
            QEvent.Type.DevicePixelRatioChange,
        }
    )

    def __init__(
        self,
        *,
        minimum_row_height: int,
        vertical_padding: int,
        horizontal_padding: int,
        item_margin: int,
        outer_padding: QMargins,
        icon_text_spacing: int = 6,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._outer_padding = QMargins(
            outer_padding.left(),
            outer_padding.top(),
            outer_padding.right(),
            outer_padding.bottom(),
        )
        self._last_metrics = (-1, -1)
        self._reflow_timer = QTimer(self)
        self._reflow_timer.setSingleShot(True)
        self._reflow_timer.setInterval(0)
        self._reflow_timer.timeout.connect(self.reflow)
        self.setItemDelegate(
            _AdaptiveNavigationDelegate(
                minimum_row_height=minimum_row_height,
                vertical_padding=vertical_padding,
                horizontal_padding=horizontal_padding,
                item_margin=item_margin,
                icon_text_spacing=icon_text_spacing,
                parent=self,
            )
        )
        self.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        model = self.model()
        model.rowsInserted.connect(self.schedule_reflow)
        model.rowsRemoved.connect(self.schedule_reflow)
        model.modelReset.connect(self.schedule_reflow)
        model.dataChanged.connect(self.schedule_reflow)
        self.schedule_reflow()

    def schedule_reflow(self, *_args: object) -> None:
        if not self._reflow_timer.isActive():
            self._reflow_timer.start()

    def reflow(self) -> None:
        self.ensurePolished()
        self.doItemsLayout()
        metrics = (self.full_content_height(), self.recommended_content_width())
        self.updateGeometry()
        self.viewport().update()
        if metrics != self._last_metrics:
            self._last_metrics = metrics
            self.metrics_changed.emit(*metrics)

    def full_content_height(self) -> int:
        row_height = sum(
            max(1, self.sizeHintForRow(row)) for row in range(self.count())
        )
        return (
            row_height
            + self.frameWidth() * 2
            + self._outer_padding.top()
            + self._outer_padding.bottom()
        )

    def recommended_content_width(self) -> int:
        column_width = max(0, self.sizeHintForColumn(0)) if self.count() else 0
        return (
            column_width
            + self.frameWidth() * 2
            + self._outer_padding.left()
            + self._outer_padding.right()
        )

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802
        super().changeEvent(event)
        if event.type() in self._METRIC_CHANGE_EVENTS and hasattr(self, "_reflow_timer"):
            self.schedule_reflow()

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802
        super().showEvent(event)
        self.schedule_reflow()


def bounded_navigation_sidebar_width(
    *,
    base_width: int,
    available_width: int,
    navigation_width: int,
    surrounding_width: int,
) -> int:
    """Grow a sidebar for navigation while reserving two thirds for content."""

    base = max(1, int(base_width))
    available = max(1, int(available_width))
    desired = max(base, int(navigation_width) + max(0, int(surrounding_width)))
    maximum = max(base, available // 3)
    return min(desired, maximum)


__all__ = ["AdaptiveNavigationList", "bounded_navigation_sidebar_width"]
```

- [ ] **步骤 4：运行共享组件测试验证通过**

运行：

```bat
.\.venv\Scripts\python.exe -m pytest tests\test_adaptive_navigation.py -q
```

预期：`5 passed`。

- [ ] **步骤 5：提交共享组件**

```bat
git add src\petnest\ui\adaptive_navigation.py tests\test_adaptive_navigation.py
git commit -m "feat: add adaptive navigation geometry"
```

### 任务 2：设置中心接入共享导航

**文件：**
- 修改：`src/petnest/ui/settings_center_dialog.py:10-53,399-438,512-548`
- 修改：`tests/test_settings_dialog.py:11-24,417-472`

- [ ] **步骤 1：先强化设置中心失败测试**

在 `tests/test_settings_dialog.py` 导入 `AdaptiveNavigationList`，并将现有导航布局测试整理为以下断言；保留文件中其他测试不变：

```python
from petnest.ui.adaptive_navigation import AdaptiveNavigationList


def _assert_navigation_rows_do_not_overlap(navigation: AdaptiveNavigationList) -> None:
    rects = [
        navigation.visualItemRect(navigation.item(row))
        for row in range(navigation.count())
    ]
    assert all(rect.isValid() and rect.height() > 0 for rect in rects)
    assert all(first.bottom() < second.top() for first, second in zip(rects, rects[1:]))


def test_settings_center_keeps_preferred_layout_on_roomy_screen(qtbot) -> None:
    dialog = SettingsDialog(Settings())
    qtbot.addWidget(dialog)

    dialog._fit_to_available_geometry(QRect(0, 0, 1920, 1040))

    assert isinstance(dialog.section_list, AdaptiveNavigationList)
    assert dialog.minimumSize() == QSize(1000, 680)
    assert dialog.size() == QSize(1180, 760)
    assert dialog.sidebar.width() == 246
    assert not dialog.status_title.isHidden()
    assert not dialog.status_card.isHidden()


def test_settings_center_prioritizes_accessible_navigation_on_short_screen(qtbot) -> None:
    dialog = SettingsDialog(Settings(), initial_section="mouse_behavior")
    qtbot.addWidget(dialog)
    available = QRect(0, 0, 960, 600)

    dialog._fit_to_available_geometry(available)
    dialog.show()
    qtbot.wait(20)

    assert dialog.width() <= available.width() - 32
    assert dialog.height() <= available.height() - 32
    assert dialog.status_title.isHidden()
    assert dialog.status_card.isHidden()
    _assert_navigation_rows_do_not_overlap(dialog.section_list)
    last_item = dialog.section_list.item(dialog.section_list.count() - 1)
    dialog.section_list.scrollToItem(last_item)
    qtbot.wait(10)
    assert dialog.section_list.visualItemRect(last_item).bottom() < dialog.section_list.viewport().height()


def test_settings_center_navigation_reflows_for_larger_system_font(qtbot) -> None:
    dialog = SettingsDialog(Settings())
    qtbot.addWidget(dialog)
    original_height = dialog.section_list.sizeHintForRow(0)
    font = QFont(dialog.section_list.font())
    font.setPointSize(20)

    dialog.section_list.setFont(font)
    dialog._fit_to_available_geometry(QRect(0, 0, 960, 640))
    dialog.show()

    qtbot.waitUntil(lambda: dialog.section_list.sizeHintForRow(0) > original_height)
    _assert_navigation_rows_do_not_overlap(dialog.section_list)
    last_item = dialog.section_list.item(dialog.section_list.count() - 1)
    dialog.section_list.scrollToItem(last_item)
    qtbot.wait(10)
    assert dialog.section_list.visualItemRect(last_item).bottom() < dialog.section_list.viewport().height()
```

- [ ] **步骤 2：运行设置中心测试确认新断言失败**

运行：

```bat
.\.venv\Scripts\python.exe -m pytest tests\test_settings_dialog.py -q
```

预期：至少 `isinstance(dialog.section_list, AdaptiveNavigationList)` 失败，且 `dialog.sidebar` 尚不存在。

- [ ] **步骤 3：接入组件并替换重复高度计算**

在 `src/petnest/ui/settings_center_dialog.py`：

1. 为 QtCore 导入加入 `QMargins`。
2. 导入共享组件：

```python
from petnest.ui.adaptive_navigation import (
    AdaptiveNavigationList,
    bounded_navigation_sidebar_width,
)
```

3. 将局部侧栏与列表构造替换为：

```python
self.sidebar = QFrame(window_shell)
self.sidebar.setObjectName("settingsSidebar")
self.sidebar.setFixedWidth(246)
self.sidebar_layout = QVBoxLayout(self.sidebar)
self.sidebar_layout.setContentsMargins(16, 18, 16, 16)
self.sidebar_layout.setSpacing(10)
sidebar_title = QLabel("偏好设置", self.sidebar)
sidebar_title.setObjectName("mutedLabel")
sidebar_title.setStyleSheet("font-size: 12px; font-weight: 700; letter-spacing: 1px;")
self.sidebar_layout.addWidget(sidebar_title)
self.section_list = AdaptiveNavigationList(
    minimum_row_height=46,
    vertical_padding=11,
    horizontal_padding=14,
    item_margin=3,
    outer_padding=QMargins(4, 8, 4, 8),
    parent=self.sidebar,
)
self.section_list.setObjectName("settingsNavigation")
self.section_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
self.section_list.setFrameShape(QFrame.Shape.NoFrame)
for _key, label in self._SECTION_NAMES:
    self.section_list.addItem(QListWidgetItem(label))
self.sidebar_layout.addWidget(self.section_list, 1)
```

把紧随其后的状态标题、状态卡和 `body.addWidget(...)` 的父对象及布局变量改为 `self.sidebar`、`self.sidebar_layout`，内容保持原样。

4. 在首次 `_fit_to_available_geometry()` 之前连接指标变化：

```python
self.section_list.metrics_changed.connect(self._refresh_navigation_geometry)
```

5. 新增宿主几何方法：

```python
def _refresh_navigation_geometry(self, *_metrics: int) -> None:
    screen = self.screen() or QApplication.primaryScreen()
    if screen is not None:
        self._fit_to_available_geometry(screen.availableGeometry())

def _sync_navigation_sidebar_width(self, usable_width: int) -> None:
    margins = self.sidebar_layout.contentsMargins()
    surrounding_width = margins.left() + margins.right()
    self.sidebar.setFixedWidth(
        bounded_navigation_sidebar_width(
            base_width=246,
            available_width=usable_width,
            navigation_width=self.section_list.recommended_content_width(),
            surrounding_width=surrounding_width,
        )
    )
```

6. 在 `_fit_to_available_geometry()` 中删掉手工 `sizeHintForRow()` 求和、`frame_height` 和常量 `navigation_padding`，换成：

```python
self.section_list.reflow()
maximum_navigation_height = max(1, usable_height * 3 // 5)
self.section_list.setMinimumHeight(
    min(self.section_list.full_content_height(), maximum_navigation_height)
)
```

保留现有窗口 `setMinimumSize()` 与 `resize()` 逻辑，并在 `resize()` 之后调用：

```python
self._sync_navigation_sidebar_width(usable_width)
```

- [ ] **步骤 4：运行设置中心与共享组件测试**

运行：

```bat
.\.venv\Scripts\python.exe -m pytest tests\test_adaptive_navigation.py tests\test_settings_dialog.py -q
```

预期：全部通过；当前基线下应至少包含共享组件的 `5 passed` 与设置中心文件的全部既有测试。

- [ ] **步骤 5：提交设置中心接入**

```bat
git add src\petnest\ui\settings_center_dialog.py tests\test_settings_dialog.py
git commit -m "fix: adapt settings navigation to font metrics"
```

### 任务 3：宠物与动作窗口接入共享导航

**文件：**
- 修改：`src/petnest/ui/pet_action_exchange_dialog.py:9-37,129-141,228-242`
- 修改：`tests/test_pet_action_exchange_dialog.py:8-12,144-168`

- [ ] **步骤 1：编写宠物与动作大字体失败测试**

在 `tests/test_pet_action_exchange_dialog.py` 加入 `QFont` 与 `AdaptiveNavigationList` 导入，并新增：

```python
from PySide6.QtGui import QFont

from petnest.ui.adaptive_navigation import AdaptiveNavigationList


def test_exchange_navigation_reflows_and_grows_sidebar_for_large_font(
    qtbot: object, tmp_path: Path
) -> None:
    package = PackageLoader().load(_write_package(tmp_path / "pet"))
    dialog = PetActionExchangeDialog([package], tmp_path / "pets")
    qtbot.addWidget(dialog)
    dialog.navigation.setCurrentRow(1)
    original_row_height = dialog.navigation.sizeHintForRow(0)
    font = QFont(dialog.navigation.font())
    font.setPointSize(24)

    dialog.navigation.setFont(font)
    dialog.show()

    qtbot.waitUntil(lambda: dialog.navigation.sizeHintForRow(0) > original_row_height)
    assert isinstance(dialog.navigation, AdaptiveNavigationList)
    assert dialog.navigation.currentRow() == 1
    assert dialog.sidebar.width() > 145
    rects = [
        dialog.navigation.visualItemRect(dialog.navigation.item(row))
        for row in range(dialog.navigation.count())
    ]
    assert all(rect.isValid() and rect.height() > 0 for rect in rects)
    assert all(first.bottom() < second.top() for first, second in zip(rects, rects[1:]))
    assert dialog.navigation.sizeHintForColumn(0) >= max(
        dialog.navigation.fontMetrics().horizontalAdvance(dialog.navigation.item(row).text())
        for row in range(dialog.navigation.count())
    )
```

在现有 `test_exchange_shell_uses_v4_geometry_and_lucide_navigation` 中保留 `dialog.sidebar.width() == 145`，以锁定默认字体下不发生视觉回归。

- [ ] **步骤 2：运行新测试确认失败**

运行：

```bat
.\.venv\Scripts\python.exe -m pytest tests\test_pet_action_exchange_dialog.py::test_exchange_navigation_reflows_and_grows_sidebar_for_large_font -q
```

预期：`isinstance(dialog.navigation, AdaptiveNavigationList)` 或侧栏增宽断言失败。

- [ ] **步骤 3：接入共享组件与受限侧栏宽度**

在 `src/petnest/ui/pet_action_exchange_dialog.py`：

1. QtCore 导入加入 `QMargins`，QtGui 导入加入 `QResizeEvent`。
2. 导入共享组件：

```python
from petnest.ui.adaptive_navigation import (
    AdaptiveNavigationList,
    bounded_navigation_sidebar_width,
)
```

3. 将导航构造替换为：

```python
self.sidebar = QFrame(body_widget)
self.sidebar.setObjectName("actionExchangeSidebar")
self.sidebar.setFixedWidth(145)
self.sidebar_layout = QVBoxLayout(self.sidebar)
self.sidebar_layout.setContentsMargins(11, 11, 11, 11)
self.navigation = AdaptiveNavigationList(
    minimum_row_height=40,
    vertical_padding=9,
    horizontal_padding=11,
    item_margin=2,
    outer_padding=QMargins(0, 6, 0, 6),
    parent=self.sidebar,
)
self.navigation.setObjectName("settingsNavigation")
for label, icon_name in zip(self._PAGE_LABELS, self._PAGE_ICONS, strict=True):
    self.navigation.addItem(
        QListWidgetItem(lucide_icon(icon_name, color="#88776e", size=16), label)
    )
self.sidebar_layout.addWidget(self.navigation)
body.addWidget(self.sidebar)
```

4. 项目添加后连接和执行首次重算：

```python
self.navigation.metrics_changed.connect(self._sync_navigation_sidebar_width)
self.navigation.reflow()
self._sync_navigation_sidebar_width()
```

5. 在类中新增：

```python
def _sync_navigation_sidebar_width(self, *_metrics: int) -> None:
    if not hasattr(self, "navigation"):
        return
    margins = self.sidebar_layout.contentsMargins()
    surrounding_width = margins.left() + margins.right()
    self.sidebar.setFixedWidth(
        bounded_navigation_sidebar_width(
            base_width=145,
            available_width=max(1, self.width()),
            navigation_width=self.navigation.recommended_content_width(),
            surrounding_width=surrounding_width,
        )
    )

def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
    super().resizeEvent(event)
    self._sync_navigation_sidebar_width()
```

不改 `_on_navigation_changed()`、`_sync_navigation_icons()` 或离开确认逻辑。

- [ ] **步骤 4：运行宠物与动作及共享组件测试**

运行：

```bat
.\.venv\Scripts\python.exe -m pytest tests\test_adaptive_navigation.py tests\test_pet_action_exchange_dialog.py -q
```

预期：全部通过；默认字体测试继续得到 `dialog.sidebar.width() == 145`，大字体测试得到更宽侧栏和互不相交的行。

- [ ] **步骤 5：提交宠物与动作接入**

```bat
git add src\petnest\ui\pet_action_exchange_dialog.py tests\test_pet_action_exchange_dialog.py
git commit -m "fix: adapt pet action navigation across fonts"
```

### 任务 4：完成跨平台不变量与全量回归验证

**文件：**
- 验证：`src/petnest/ui/adaptive_navigation.py`
- 验证：`src/petnest/ui/settings_center_dialog.py`
- 验证：`src/petnest/ui/pet_action_exchange_dialog.py`
- 验证：`tests/test_adaptive_navigation.py`
- 验证：`tests/test_settings_dialog.py`
- 验证：`tests/test_pet_action_exchange_dialog.py`

- [ ] **步骤 1：运行导航相关测试集合**

运行：

```bat
.\.venv\Scripts\python.exe -m pytest tests\test_adaptive_navigation.py tests\test_settings_dialog.py tests\test_pet_action_exchange_dialog.py tests\test_ui_theme.py tests\test_action_import_visual_style.py -q
```

预期：全部通过，无 Qt 警告导致的失败，无导航选择行为回归。

- [ ] **步骤 2：检查补丁格式与意外文件**

运行：

```bat
git diff --check
git status --short
```

预期：`git diff --check` 无输出；状态中不包含本计划范围之外被暂存或修改的文件。主工作区已有的未跟踪素材不属于本任务。

- [ ] **步骤 3：运行完整测试套件**

运行：

```bat
.\.venv\Scripts\python.exe -m pytest -q
```

预期：完整测试套件通过；平台条件性测试只允许已有的预期 skip，不出现新增失败。

- [ ] **步骤 4：执行可用平台上的人工视觉抽查**

在当前可用桌面平台分别用默认系统字体和较大系统字体打开设置中心及“宠物与动作”，逐项检查：

```text
1. 相邻文字与选中背景不重叠。
2. 图标与文字垂直居中。
3. 默认字体下侧栏宽度保持原设计。
4. 大字体放不下时侧栏增长；达到三分之一窗口宽度后可水平滚动。
5. 矮窗口中导航行不被压缩，最后一项可滚动访问。
6. 更换选中项、切换页面和取消离开确认仍按原逻辑工作。
```

预期：六项全部满足。自动化测试负责跨平台几何不变量，人工抽查只验证当前实际可用的平台渲染。

- [ ] **步骤 5：确认提交边界**

运行：

```bat
git log -3 --oneline
git status --short
```

预期：最近三次实现提交分别对应共享组件、设置中心接入、宠物与动作接入；没有把用户已有素材或其他无关文件纳入提交。
