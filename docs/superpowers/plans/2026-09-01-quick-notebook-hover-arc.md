# PetNest 便签悬浮入口 C 形排列实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 将宠物旁的道具箱与便签本入口改为无可见轨道的外侧顶部 C 形排列，并在屏幕边缘、面板展开及高 DPI 环境下保持完整可用。

**架构：** 在 `interaction_item_toolbox.py` 中增加无 Qt 状态依赖的几何规划函数，统一决定左右侧、顶层窗口位置、入口画布偏移和按钮局部坐标。`InteractionItemToolbox` 仍是唯一顶层窗口，水平入口条改为固定 `87 × 79` 的透明画布，左右布局只镜像画布中的按钮及顶层布局方向，不改变现有 hover 生命周期和点击信号。

**技术栈：** Python 3.12、PySide6（Qt Widgets）、pytest、pytest-qt

---

## 文件结构

- 修改：`src/petnest/ui/interaction_item_toolbox.py`——定义 C 形入口几何模型、计算左右镜像及屏幕避让，并将两个入口放入透明绝对定位画布。
- 修改：`tests/test_interaction_item_toolbox.py`——覆盖纯几何函数、按钮尺寸与坐标、展开方向、屏幕约束和已有交互行为。
- 修改：`tests/test_pet_window.py`——确认改布局后宠物与工具窗之间的 700ms hover bridge 仍保持不变。

### 任务 1：锁定 C 形入口的纯几何规则

**文件：**
- 修改：`tests/test_interaction_item_toolbox.py`
- 修改：`src/petnest/ui/interaction_item_toolbox.py`

- [ ] **步骤 1：为默认右侧、左侧镜像和顶部避让编写失败测试**

把测试文件的 QtCore 导入补为 `from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QSize, Qt`，并从被测模块导入 `LauncherArcPlacement` 与 `plan_launcher_arc`，然后加入：

```python
def test_plan_launcher_arc_uses_right_outer_top_c_shape_by_default() -> None:
    placement = plan_launcher_arc(
        QRect(200, 100, 80, 100),
        QRect(0, 0, 800, 600),
        QSize(0, 0),
        expanded=False,
    )

    assert placement.side == "right"
    assert placement.window_position == QPoint(288, 78)
    assert placement.canvas_offset == QPoint(0, 0)
    assert placement.toolbox_position == QPoint(0, 0)
    assert placement.notebook_position == QPoint(43, 35)


def test_plan_launcher_arc_mirrors_the_whole_pair_near_right_edge() -> None:
    placement = plan_launcher_arc(
        QRect(720, 100, 60, 100),
        QRect(0, 0, 800, 600),
        QSize(0, 0),
        expanded=False,
    )

    assert placement.side == "left"
    assert placement.window_position == QPoint(625, 78)
    assert placement.toolbox_position == QPoint(43, 0)
    assert placement.notebook_position == QPoint(0, 35)
    assert placement.notebook_position - placement.toolbox_position == QPoint(-43, 35)


def test_plan_launcher_arc_shifts_both_buttons_down_at_top_edge() -> None:
    placement = plan_launcher_arc(
        QRect(200, 5, 80, 100),
        QRect(0, 0, 800, 600),
        QSize(0, 0),
        expanded=False,
    )

    assert placement.window_position.y() == 0
    assert placement.notebook_position - placement.toolbox_position == QPoint(43, 35)
```

- [ ] **步骤 2：运行三个测试并确认它们因新接口不存在而失败**

运行：

```powershell
.venv\Scripts\python.exe -m pytest tests/test_interaction_item_toolbox.py -k "plan_launcher_arc" -v
```

预期：测试收集阶段失败，提示无法导入 `LauncherArcPlacement` 或 `plan_launcher_arc`。

- [ ] **步骤 3：实现几何数据类、溢出评分与规划函数**

在模块常量区加入：

```python
from dataclasses import dataclass
from typing import Literal

_LAUNCHER_SIZE = QSize(44, 44)
_LAUNCHER_CANVAS_SIZE = QSize(87, 79)
_LAUNCHER_ARC_DELTA = QPoint(43, 35)
_PANEL_GAP = 6


@dataclass(frozen=True)
class LauncherArcPlacement:
    side: Literal["right", "left"]
    window_position: QPoint
    canvas_offset: QPoint
    toolbox_position: QPoint
    notebook_position: QPoint


def _overflow_score(rect: QRect, available: QRect) -> int:
    return (
        max(0, available.left() - rect.left())
        + max(0, rect.right() - available.right())
        + max(0, available.top() - rect.top())
        + max(0, rect.bottom() - available.bottom())
    )


def _clamp_rect_origin(rect: QRect, available: QRect) -> QPoint:
    max_x = max(available.left(), available.right() - rect.width() + 1)
    max_y = max(available.top(), available.bottom() - rect.height() + 1)
    return QPoint(
        min(max(rect.x(), available.left()), max_x),
        min(max(rect.y(), available.top()), max_y),
    )
```

实现 `plan_launcher_arc`，使用以下固定关系：

```python
def plan_launcher_arc(
    pet_rect: QRect,
    available: QRect,
    panel_size: QSize,
    *,
    expanded: bool,
) -> LauncherArcPlacement:
    del panel_size, expanded
    group_y = pet_rect.top() - 22
    right_group_x = pet_rect.right() + 1 + _TOOLBOX_GAP
    left_group_x = pet_rect.left() - _TOOLBOX_GAP - _LAUNCHER_SIZE.width() - 43

    right_rect = QRect(QPoint(right_group_x, group_y), _LAUNCHER_CANVAS_SIZE)
    left_rect = QRect(QPoint(left_group_x, group_y), _LAUNCHER_CANVAS_SIZE)
    side: Literal["right", "left"] = (
        "right" if _overflow_score(right_rect, available) <= _overflow_score(left_rect, available) else "left"
    )
    candidate = right_rect if side == "right" else left_rect
    window_position = _clamp_rect_origin(candidate, available)
    toolbox_position = QPoint(0, 0) if side == "right" else QPoint(43, 0)
    notebook_position = QPoint(43, 35) if side == "right" else QPoint(0, 35)
    return LauncherArcPlacement(
        side,
        window_position,
        QPoint(0, 0),
        toolbox_position,
        notebook_position,
    )
```

将 `LauncherArcPlacement` 与 `plan_launcher_arc` 加入 `__all__`；保留 `clamp_toolbox_position` 到调用迁移完成，避免一步同时破坏现有测试。

- [ ] **步骤 4：运行几何测试确认通过**

运行：

```powershell
.venv\Scripts\python.exe -m pytest tests/test_interaction_item_toolbox.py -k "plan_launcher_arc" -v
```

预期：3 个测试全部 `PASSED`。

- [ ] **步骤 5：提交几何规则**

```powershell
git add src/petnest/ui/interaction_item_toolbox.py tests/test_interaction_item_toolbox.py
git commit --fixup=92cc1bd
```

### 任务 2：把水平入口条替换为透明 C 形画布

**文件：**
- 修改：`tests/test_interaction_item_toolbox.py`
- 修改：`src/petnest/ui/interaction_item_toolbox.py`

- [ ] **步骤 1：把旧水平间距断言改为画布几何和命中区域断言**

在测试文件加入 `from PySide6.QtWidgets import QBoxLayout`。

将 `test_matching_toolbox_and_notebook_launchers` 的 `launcher_strip` 断言替换为：

```python
assert toolbox.launcher_canvas.size() == QSize(87, 79)
assert toolbox.launcher.geometry() == QRect(0, 0, 44, 44)
assert toolbox.notebook_launcher.geometry() == QRect(43, 35, 44, 44)
delta = toolbox.notebook_launcher.geometry().center() - toolbox.launcher.geometry().center()
assert delta == QPoint(43, 35)
assert round((delta.x() ** 2 + delta.y() ** 2) ** 0.5, 1) == 55.4
assert toolbox.launcher.hitButton(QPoint(43, 43))
assert toolbox.notebook_launcher.hitButton(QPoint(43, 43))
```

另加左右镜像 UI 测试：

```python
def test_toolbox_applies_mirrored_arc_and_panel_direction(qtbot, tmp_path: Path) -> None:
    toolbox = InteractionItemToolbox()
    qtbot.addWidget(toolbox)
    toolbox.set_items((_resolved_item(tmp_path, "toy"),))
    toolbox.set_notebook_enabled(True)

    toolbox._apply_arc_side("left")

    assert toolbox.launcher.pos() == QPoint(43, 0)
    assert toolbox.notebook_launcher.pos() == QPoint(0, 35)
    assert toolbox.layout().direction() == QBoxLayout.Direction.RightToLeft
```

- [ ] **步骤 2：运行 UI 几何测试并确认旧结构导致失败**

运行：

```powershell
.venv\Scripts\python.exe -m pytest tests/test_interaction_item_toolbox.py -k "matching_toolbox or mirrored_arc" -v
```

预期：失败原因包含 `launcher_canvas` 或 `_apply_arc_side` 不存在，或者旧按钮坐标仍是水平排列。

- [ ] **步骤 3：创建固定透明画布并用绝对坐标摆放按钮**

在 `InteractionItemToolbox.__init__` 中：

```python
layout = QHBoxLayout(self)
layout.setContentsMargins(0, 0, 0, 0)
layout.setSpacing(_PANEL_GAP)

self.launcher_canvas = QWidget(self)
self.launcher_canvas.setObjectName("interactionLauncherCanvas")
self.launcher_canvas.setFixedSize(_LAUNCHER_CANVAS_SIZE)

self.launcher = QToolButton(self.launcher_canvas)
self.launcher.move(0, 0)

self.notebook_launcher = QToolButton(self.launcher_canvas)
self.notebook_launcher.move(43, 35)

layout.addWidget(self.launcher_canvas, 0, Qt.AlignmentFlag.AlignTop)
```

两个 `QToolButton` 从 `launcher_strip` 改挂到 `launcher_canvas` 后，其现有图标、阴影、tooltip、accessible name、点击信号、`44 × 44` 尺寸与 `25 × 25` 图标设置逐行保持不变。

补充方向切换方法：

```python
def _apply_arc_side(self, side: Literal["right", "left"]) -> None:
    self._arc_side = side
    if side == "right":
        self.launcher.move(0, 0)
        self.notebook_launcher.move(43, 35)
        self.layout().setDirection(QBoxLayout.Direction.LeftToRight)
    else:
        self.launcher.move(43, 0)
        self.notebook_launcher.move(0, 35)
        self.layout().setDirection(QBoxLayout.Direction.RightToLeft)
```

导入 `QBoxLayout`，删除不再使用的 `QHBoxLayout(self.launcher_strip)` 和 `launcher_strip`。初始化 `_arc_side = "right"`。不添加画布背景、边框、轨道或动画。

- [ ] **步骤 4：运行整个工具箱测试文件**

运行：

```powershell
.venv\Scripts\python.exe -m pytest tests/test_interaction_item_toolbox.py -v
```

预期：工具箱测试全部 `PASSED`；现有图标、拖放、打开/收起和便签点击测试仍通过。

- [ ] **步骤 5：提交入口画布变更**

```powershell
git add src/petnest/ui/interaction_item_toolbox.py tests/test_interaction_item_toolbox.py
git commit --fixup=92cc1bd
```

### 任务 3：接入展开方向、跨屏重排与 DPI 回归

**文件：**
- 修改：`tests/test_interaction_item_toolbox.py`
- 修改：`tests/test_pet_window.py`
- 修改：`src/petnest/ui/interaction_item_toolbox.py`

- [ ] **步骤 1：为面板外向展开与完整屏幕约束编写失败测试**

加入：

```python
def test_expanded_arc_panel_stays_outside_pet_on_both_sides() -> None:
    available = QRect(0, 0, 800, 600)
    panel_size = QSize(300, 190)
    right_pet = QRect(150, 150, 80, 100)
    left_pet = QRect(700, 150, 60, 100)

    right = plan_launcher_arc(right_pet, available, panel_size, expanded=True)
    left = plan_launcher_arc(left_pet, available, panel_size, expanded=True)
    right_panel = QRect(
        right.window_position + right.canvas_offset + QPoint(87 + 6, 0),
        panel_size,
    )
    left_panel = QRect(left.window_position, panel_size)

    assert right.side == "right"
    assert left.side == "left"
    assert not right_panel.intersects(right_pet)
    assert not left_panel.intersects(left_pet)
    assert available.contains(QRect(right.window_position, QSize(393, 190)))
    assert available.contains(QRect(left.window_position, QSize(393, 190)))
```

保留并重新运行 `test_pet_hover_bridge_keeps_toolbox_visible_until_both_regions_are_left` 中的以下关键断言：

```python
assert window._interaction_hide_timer.interval() == 700
window.interaction_toolbox.hover_changed.emit(True)
assert not window._interaction_hide_timer.isActive()
window.interaction_toolbox.hover_changed.emit(False)
assert window._interaction_hide_timer.isActive()
```

- [ ] **步骤 2：运行新增测试确认定位尚未接入**

运行：

```powershell
.venv\Scripts\python.exe -m pytest tests/test_interaction_item_toolbox.py -k "expanded_arc_panel" -v
```

预期：测试失败，表明当前 `reposition` 仍调用旧的 `clamp_toolbox_position`，或展开后的方向与规划结果不一致。

- [ ] **步骤 3：让 `_fit_contents` 与 `reposition` 使用同一份几何规划**

先把 `plan_launcher_arc` 的函数体扩展为同时计算展开面板：

```python
panel_width = max(0, panel_size.width()) if expanded else 0
panel_height = max(0, panel_size.height()) if expanded else 0
extra_width = panel_width + (_PANEL_GAP if panel_width else 0)
window_size = QSize(
    _LAUNCHER_CANVAS_SIZE.width() + extra_width,
    max(_LAUNCHER_CANVAS_SIZE.height(), panel_height),
)
group_y = pet_rect.top() - 22
right_group_x = pet_rect.right() + 1 + _TOOLBOX_GAP
left_group_x = pet_rect.left() - _TOOLBOX_GAP - _LAUNCHER_SIZE.width() - 43
right_rect = QRect(QPoint(right_group_x, group_y), window_size)
left_rect = QRect(QPoint(left_group_x - extra_width, group_y), window_size)
side: Literal["right", "left"] = (
    "right" if _overflow_score(right_rect, available) <= _overflow_score(left_rect, available) else "left"
)
candidate = right_rect if side == "right" else left_rect
window_position = _clamp_rect_origin(candidate, available)
canvas_offset = QPoint(0 if side == "right" else extra_width, 0)
toolbox_position = QPoint(0, 0) if side == "right" else QPoint(43, 0)
notebook_position = QPoint(43, 35) if side == "right" else QPoint(0, 35)
return LauncherArcPlacement(
    side,
    window_position,
    canvas_offset,
    toolbox_position,
    notebook_position,
)
```

再增加面板尺寸辅助函数，并替换 `reposition`：

```python
def _planned_panel_size(self) -> QSize:
    if not self._is_expanded or not self.panel.isVisible():
        return QSize(0, 0)
    return self.panel.sizeHint().expandedTo(self.panel.minimumSizeHint())


def reposition(self, pet_rect: QRect) -> None:
    self._pet_rect = QRect(pet_rect)
    if not self.isVisible():
        return
    screen = QGuiApplication.screenAt(self._pet_rect.center()) or QGuiApplication.primaryScreen()
    if screen is None:
        return
    placement = plan_launcher_arc(
        self._pet_rect,
        screen.availableGeometry(),
        self._planned_panel_size(),
        expanded=self._is_expanded,
    )
    self._apply_arc_side(placement.side)
    self._fit_contents()
    self.move(placement.window_position)
```

在 `_apply_arc_side` 中调用布局激活后，保证左侧时 panel 在画布左边，右侧时 panel 在画布右边；删除不再被调用的 `clamp_toolbox_position` 及旧测试。`show_for`、`open_panel`、`collapse` 和宠物移动仍统一调用 `reposition`，因此切换屏幕或展开状态都会重算。

- [ ] **步骤 4：运行工具箱、宠物 hover bridge 和便签集成测试**

运行：

```powershell
.venv\Scripts\python.exe -m pytest tests/test_interaction_item_toolbox.py tests/test_pet_window.py tests/test_quick_notebook_window.py -v
```

预期：全部 `PASSED`，且 hover timer 仍为 `700ms`。

- [ ] **步骤 5：在 100%、125%、150% 缩放下启动真实程序并逐项复核**

每次关闭前一实例，再分别设置环境变量启动真实程序：

```cmd
set QT_SCALE_FACTOR=1.0&& set PYTHONPATH=F:\Desktop Projects\PetNest\src&& .venv\Scripts\python.exe -m petnest
set QT_SCALE_FACTOR=1.25&& set PYTHONPATH=F:\Desktop Projects\PetNest\src&& .venv\Scripts\python.exe -m petnest
set QT_SCALE_FACTOR=1.5&& set PYTHONPATH=F:\Desktop Projects\PetNest\src&& .venv\Scripts\python.exe -m petnest
```

每个缩放比例都悬浮宠物、打开道具面板、移动宠物到屏幕右缘再重新悬浮，必须同时满足：无弧线或轨道；两个入口均完整显示；道具箱靠近宠物头顶、便签本位于外侧下方；两图标无视觉重叠；靠右场景整体镜像；展开面板不覆盖宠物；窗口未超出可用屏幕。

- [ ] **步骤 6：运行完整验证**

运行：

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m compileall -q src tests
git diff --check
```

预期：pytest 无失败；compileall 退出码为 0；`git diff --check` 无输出。

- [ ] **步骤 7：提交集成测试并合并 fixup**

```powershell
git add src/petnest/ui/interaction_item_toolbox.py tests/test_interaction_item_toolbox.py tests/test_pet_window.py
git commit --fixup=92cc1bd
git rebase -i --autosquash origin/main
```

预期：新增实现被合并进既有 `feat:实现宠物旁便签本界面` 提交，便签功能仍保持四个主题清晰的提交。

## 计划自检

- 规格覆盖：任务 1 覆盖固定坐标、中心距离、整体镜像与顶部避让；任务 2 覆盖透明画布、图标尺寸、完整命中区与无轨道视觉；任务 3 覆盖面板外向展开、跨屏重排、700ms hover bridge、100%/125%/150% DPI 和完整回归。
- 占位符扫描：所有测试名、函数签名、坐标、命令和预期结果均已给出，没有未定义步骤。
- 类型一致性：全文统一使用 `LauncherArcPlacement`、`plan_launcher_arc`、`launcher_canvas`、`_apply_arc_side`、`_planned_panel_size` 与 `Literal["right", "left"]`。
