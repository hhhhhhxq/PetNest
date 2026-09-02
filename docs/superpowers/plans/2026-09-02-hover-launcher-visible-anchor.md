# PetNest 悬浮入口可见区域锚点实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 让宠物悬浮入口贴近当前悬浮动作的 Alpha 可见范围，并在一次悬浮期间保持稳定、不随动画帧抖动。

**架构：** 在 `pet_window.py` 增加动作帧 Alpha 并集纯函数和动作级缓存。`PetWindow` 在入口显示时冻结宠物画布相对锚点，移动窗口时只做全局坐标映射；现有 `InteractionItemToolbox` C 形布局算法保持不变。

**技术栈：** Python 3.12、Pillow、PySide6、pytest、pytest-qt

---

## 文件结构

- 修改：`src/petnest/ui/pet_window.py`——计算动作 Alpha 并集、缓存并冻结入口锚点，管理移动、缩放、隐藏和重载生命周期。
- 修改：`src/petnest/ui/interaction_item_toolbox.py`——仅有一个入口时复用靠近宠物的内侧槽位。
- 修改：`tests/test_pet_window.py`——覆盖透明留白、多帧并集、冻结、整体移动、倒计时居中和回退行为。
- 修改：`tests/test_interaction_item_toolbox.py`——覆盖单入口在左右两侧的内侧槽位坐标。

### 任务 1：计算并缓存动作可见区域

**文件：**
- 修改：`tests/test_pet_window.py`
- 修改：`src/petnest/ui/pet_window.py`

- [ ] **步骤 1：编写 Alpha 并集与透明帧回退测试**

从 `petnest.ui.pet_window` 导入 `_visible_frame_union`，加入：

```python
def test_visible_frame_union_ignores_padding_and_covers_every_frame() -> None:
    first = Image.new("RGBA", (100, 80), (0, 0, 0, 0))
    first.paste((255, 0, 0, 255), (30, 10, 70, 60))
    second = Image.new("RGBA", (100, 80), (0, 0, 0, 0))
    second.paste((255, 0, 0, 255), (20, 20, 80, 70))

    assert _visible_frame_union((first, second), QSize(100, 80)) == QRect(20, 10, 60, 60)


def test_visible_frame_union_falls_back_to_canvas_for_transparent_frames() -> None:
    transparent = Image.new("RGBA", (100, 80), (0, 0, 0, 0))

    assert _visible_frame_union((transparent,), QSize(100, 80)) == QRect(0, 0, 100, 80)
```

- [ ] **步骤 2：运行测试确认新函数缺失导致红灯**

运行：

```cmd
.venv\Scripts\python.exe -m pytest tests\test_pet_window.py -k visible_frame_union -v
```

预期：收集失败，提示无法导入 `_visible_frame_union`。

- [ ] **步骤 3：实现 Alpha 并集纯函数**

在 `_prepare_translucent_frame` 前加入：

```python
def _visible_frame_union(frames: tuple[Image.Image, ...], fallback_size: QSize) -> QRect:
    bounds = [frame.getchannel("A").getbbox() for frame in frames]
    visible = [value for value in bounds if value is not None]
    if not visible:
        return QRect(0, 0, max(1, fallback_size.width()), max(1, fallback_size.height()))
    left = min(value[0] for value in visible)
    top = min(value[1] for value in visible)
    right = max(value[2] for value in visible)
    bottom = max(value[3] for value in visible)
    return QRect(left, top, max(1, right - left), max(1, bottom - top))
```

在 `PetWindow.__init__` 中增加：

```python
self._hover_action_bounds_cache: dict[str, QRect] = {}
self._frozen_hover_anchor_pet_rect: QRect | None = None
```

在 `load_package()` 清理 `_hover_action_bounds_cache`；`_clear_interaction_item_ui()` 清除 `_frozen_hover_anchor_pet_rect`。

- [ ] **步骤 4：运行纯函数测试和宠物窗口既有测试**

运行：

```cmd
.venv\Scripts\python.exe -m pytest tests\test_pet_window.py -v
```

预期：新增并集测试和既有 Alpha 缓存测试全部通过。

- [ ] **步骤 5：提交动作可见区域计算**

```cmd
git add src\petnest\ui\pet_window.py tests\test_pet_window.py
git commit -m feat:增加宠物动作可见区域锚点
```

### 任务 2：冻结入口锚点并接入悬浮生命周期

**文件：**
- 修改：`tests/test_pet_window.py`
- 修改：`src/petnest/ui/pet_window.py`

- [ ] **步骤 1：编写缩放、倒计时居中和冻结行为测试**

创建一个 `100 × 80` 画布宠物包，其 hover 两帧可见区域并集为 `(20, 10, 80, 70)`，默认缩放为 `1.0`。显示宽度为 `200px` 的倒计时后触发 hover，断言：

```python
assert window._frozen_hover_anchor_pet_rect == QRect(20, 10, 60, 60)
expected_global = QRect(
    window.mapToGlobal(QPoint(window._pet_left() + 20, 10)),
    QSize(60, 60),
)
assert window.interaction_toolbox._pet_rect == expected_global
```

记录锚点后推进动画一帧，断言冻结值不变：

```python
frozen = QRect(window._frozen_hover_anchor_pet_rect)
window.animation_timer.timeout.emit()
assert window._frozen_hover_anchor_pet_rect == frozen
```

移动宠物窗口 `(20, 10)`，断言工具入口锚点同步移动同一向量：

```python
before = QRect(window.interaction_toolbox._pet_rect)
window.move(window.pos() + QPoint(20, 10))
QApplication.processEvents()
assert window.interaction_toolbox._pet_rect.topLeft() == before.topLeft() + QPoint(20, 10)
```

- [ ] **步骤 2：运行冻结测试确认当前完整窗口锚点导致红灯**

运行：

```cmd
.venv\Scripts\python.exe -m pytest tests\test_pet_window.py -k hover_tool_anchor -v
```

预期：失败，当前 `_pet_rect` 等于完整窗口矩形，且冻结字段不存在或与 Alpha 并集不符。

- [ ] **步骤 3：实现缩放后的宠物相对锚点**

导入 `ceil` 与 `floor`，增加：

```python
def _action_visible_pet_rect(self) -> QRect:
    bounds = self._hover_action_bounds_cache.get(self._playing_action)
    if bounds is None:
        bounds = _visible_frame_union(
            self.player.current_frames,
            QSize(self.package.canvas.width, self.package.canvas.height),
        )
        self._hover_action_bounds_cache[self._playing_action] = QRect(bounds)
    left = floor(bounds.left() * self.scale)
    top = floor(bounds.top() * self.scale)
    right = ceil((bounds.right() + 1) * self.scale)
    bottom = ceil((bounds.bottom() + 1) * self.scale)
    return QRect(left, top, max(1, right - left), max(1, bottom - top))


def _freeze_hover_tool_anchor(self) -> None:
    self._frozen_hover_anchor_pet_rect = self._action_visible_pet_rect()


def _hover_tool_anchor_global_rect(self) -> QRect:
    anchor = self._frozen_hover_anchor_pet_rect
    if anchor is None:
        anchor = QRect(0, 0, self._pet_width(), self._pet_height())
    local_top_left = QPoint(self._pet_left() + anchor.left(), anchor.top())
    return QRect(self.mapToGlobal(local_top_left), anchor.size())
```

- [ ] **步骤 4：接入显示、移动、缩放和清理路径**

`open_interaction_toolbox()` 在 `show_for()` 前调用 `_freeze_hover_tool_anchor()`，并传入 `_hover_tool_anchor_global_rect()`。

`enterEvent()` 先判断透明命中并处理 `mouse.enter`，再冻结锚点并显示入口：

```python
opaque = self.is_opaque_at(int(event.position().x()), int(event.position().y()))
if opaque:
    self._handle_event("mouse.enter")
if self._hover_tools_can_show():
    self._freeze_hover_tool_anchor()
    self.interaction_toolbox.show_for(self._hover_tool_anchor_global_rect())
```

`moveEvent()` 在入口可见时改用 `_hover_tool_anchor_global_rect()`；`_clear_interaction_item_ui()` 隐藏入口后把冻结锚点设为 `None`。

`set_scale()` 若入口可见，在 `_set_current_frame()` 前清除冻结锚点，缩放完成后重新冻结并调用 `reposition()`。

- [ ] **步骤 5：运行宠物窗口、工具箱和便签入口回归**

在工具箱测试中增加单入口槽位断言：

```python
toolbox.set_items(())
toolbox.set_notebook_enabled(True)
toolbox._apply_arc_side("right")
assert toolbox.notebook_launcher.pos() == QPoint(0, 0)
toolbox._apply_arc_side("left")
assert toolbox.notebook_launcher.pos() == QPoint(43, 0)
```

`_apply_arc_side()` 仅在 `bool(self._item_buttons) and self._notebook_enabled` 时把笔记本放到 C 形外侧槽位；否则放入与道具箱相同的内侧槽位。

运行：

```cmd
.venv\Scripts\python.exe -m pytest tests\test_pet_window.py tests\test_interaction_item_toolbox.py tests\test_app_and_platforms.py -q
```

预期：可见区域、冻结、整体移动、700ms hover bridge、左右镜像和便签入口测试全部通过。

- [ ] **步骤 6：运行完整验证并提交**

运行：

```cmd
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m compileall -q src tests
git diff --check
```

预期：pytest 无失败，compileall 返回 0，`git diff --check` 无输出。

提交：

```cmd
git add src\petnest\ui\pet_window.py src\petnest\ui\interaction_item_toolbox.py tests\test_pet_window.py tests\test_interaction_item_toolbox.py
git commit -m feat:让悬浮入口贴近宠物可见区域
```

## 计划自检

- 规格覆盖：任务 1 覆盖 Alpha 并集、透明回退和缓存；任务 2 覆盖缩放、倒计时居中、冻结、整体移动、清理和既有交互回归。
- 占位符扫描：函数签名、字段名、测试断言、命令和预期结果均已明确。
- 类型一致性：全文统一使用 `_visible_frame_union`、`_hover_action_bounds_cache`、`_frozen_hover_anchor_pet_rect`、`_action_visible_pet_rect`、`_freeze_hover_tool_anchor` 与 `_hover_tool_anchor_global_rect`。
