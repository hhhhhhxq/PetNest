# 陪玩扑抓接触点分区实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 将陪玩动作方向从“相对脚底攻击原点的固定 60 px 阈值”改为“由五个动作接触点中线自动生成的五方向分区”，使画布中间触发 `center`，只有真实上方区域触发 `up_left` 或 `up_right`。

**架构：** 只修改不依赖 Qt 的 `HoldPlayController.resolve_direction()`。控制器先通过现有 `_target_for()` 获得带回退的五个有效 target，再根据它们的 `contact_point` 计算一条上方横向分界、上方左右分界以及普通区域左右分界；稳定判定、动作锁定、冷却、重触发和素材配置均保持不变。

**技术栈：** Python 3.12、dataclasses、pytest。

---

## 文件结构

- 修改：`src/petnest/core/interaction_play.py`——集中计算接触点中线并返回五方向结果。
- 修改：`tests/test_interaction_play.py`——覆盖旧规则误判的画布中部、上下和左右边界。

不修改 `PetWindow`、宠物包模型、平安 V2 资源和动作切换策略。可视化触发区域编辑器属于后续独立功能，不包含在本计划中。

### 任务 1：用接触点中线替换固定攻击原点阈值

**文件：**
- 修改：`tests/test_interaction_play.py:38-54`
- 修改：`src/petnest/core/interaction_play.py:56-65`

- [ ] **步骤 1：编写会在旧算法下失败的中部回归测试**

把方向用例改成直接表达接触点中线边界。现有 fixture 的接触点会生成：上方分界 `y=60`、上方左右分界 `x=100`、普通区域左右分界 `x=65` 与 `x=135`。

```python
@pytest.mark.parametrize(
    ("point", "expected"),
    [
        ((99, 59), "up_left"),
        ((100, 59), "up_right"),
        ((100, 60), "center"),
        ((100, 70), "center"),
        ((64, 100), "left"),
        ((65, 100), "center"),
        ((135, 100), "center"),
        ((136, 100), "right"),
    ],
)
def test_resolve_direction_uses_contact_point_midlines(
    definition, point, expected
) -> None:
    assert HoldPlayController(definition).resolve_direction(point) == expected
```

- [ ] **步骤 2：运行测试并确认旧算法错误地把中部判为向上**

运行：

```bash
python -m pytest -q tests/test_interaction_play.py::test_resolve_direction_uses_contact_point_midlines
```

预期：FAIL；至少 `(100, 70)` 的实际结果为 `up_right`，期望为 `center`。

- [ ] **步骤 3：实现中线计算和五方向判断**

在 `HoldPlayController` 中加入私有中点函数，并替换 `resolve_direction()`：

```python
def resolve_direction(self, point: tuple[int, int]) -> HoldPlayDirection:
    center = self._target_for("center").contact_point
    left = self._target_for("left").contact_point
    right = self._target_for("right").contact_point
    up_left = self._target_for("up_left").contact_point
    up_right = self._target_for("up_right").contact_point

    upper_contact_y = self._midpoint(up_left[1], up_right[1])
    upper_boundary_y = self._midpoint(upper_contact_y, center[1])
    if point[1] < upper_boundary_y:
        upper_split_x = self._midpoint(up_left[0], up_right[0])
        return "up_left" if point[0] < upper_split_x else "up_right"

    left_boundary_x = self._midpoint(left[0], center[0])
    right_boundary_x = self._midpoint(center[0], right[0])
    if point[0] < left_boundary_x:
        return "left"
    if point[0] <= right_boundary_x:
        return "center"
    return "right"

@staticmethod
def _midpoint(first: int, second: int) -> int:
    return round((first + second) / 2)
```

继续使用 `_target_for()`，使缺少方向的宠物包仍按 `up → 同侧 → center` 回退；多个方向复用同一 target 时分界可以重合，但最终动作保持一致。

- [ ] **步骤 4：运行控制器测试确认新边界通过**

运行：

```bash
python -m pytest -q tests/test_interaction_play.py
```

预期：全部 PASS；稳定判定、冷却、释放和接触帧校正测试不变。

- [ ] **步骤 5：运行完整陪玩相关回归测试**

运行：

```bash
python -m pytest -q tests/test_package_loader.py tests/test_package_validator.py tests/test_interaction_items.py tests/test_interaction_play.py tests/test_interaction_item_toolbox.py tests/test_drag_cursor_overlay.py tests/test_pet_window.py
```

预期：全部 PASS，且无失败或错误。

- [ ] **步骤 6：检查差异并提交代码**

运行：

```bash
git diff --check
git diff -- src/petnest/core/interaction_play.py tests/test_interaction_play.py
git status --short
```

确认只暂存控制器及其测试，不暂存 `pets/pinganv2` 或其他用户文件，然后提交：

```bash
git add src/petnest/core/interaction_play.py tests/test_interaction_play.py
git commit -m "fix: 按动作接触点划分陪玩扑抓方向"
```

- [ ] **步骤 7：重新运行最新版并人工确认代表点**

启动 PetNest 后，用逗猫棒验证以下平安 V2 逻辑坐标：

```text
(264, 200) -> center
(264, 100) -> up_right
(180, 100) -> up_left
(100, 200) -> left
(430, 200) -> right
```

动作播放期间仍等待当前动作完成，本计划不修改该行为。
