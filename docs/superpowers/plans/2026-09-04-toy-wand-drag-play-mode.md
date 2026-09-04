# 逗猫棒按住拖拽陪玩模式实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 在保持现有道具拖放行为的同时，让声明了 `hold_play` 的任意道具在按住并拖入宠物画布期间驱动方向动作，并在画布内松手后按需播放该道具的普通投放绑定。

**架构：** 宠物包模型新增可选按住陪玩配置和 pet 动作独立画布；纯逻辑 `HoldPlayController` 负责方向、防抖、冷却和释放决策；Qt 层复用原生 `QDrag` 生命周期，由 PetWindow 管理临时画布、光标覆盖层和动画切换。平安 V2 的资源与 `pet.json` 在工作区内接入并验证，但保持未跟踪，不进入代码提交。

**技术栈：** Python 3.12、PySide6、Pillow、pytest、pytest-qt、JSON 宠物包格式、WebP RGBA 动画帧。

---

## 文件结构与职责

- 修改 `src/petnest/models/pet_package.py`：定义 `HoldPlayDefinition`、`HoldPlayTargetDefinition`，并扩展 `InteractionItemDefinition`。
- 修改 `src/petnest/core/package_validator.py`：校验 pet 动作独立画布和 `hold_play` 的路径、数值、动作引用及画布一致性。
- 修改 `src/petnest/core/package_loader.py`：加载动作独立画布与按住陪玩配置。
- 修改 `src/petnest/core/interaction_items.py`：解析同时具备普通投放动作和可选按住陪玩能力的道具。
- 创建 `src/petnest/core/interaction_play.py`：纯逻辑状态控制器，不依赖 Qt。
- 创建 `src/petnest/ui/drag_cursor_overlay.py`：输入透明的逗猫棒拖拽视觉覆盖层。
- 修改 `src/petnest/ui/interaction_item_toolbox.py`：暴露道具拖拽开始、结束及原生结果。
- 修改 `src/petnest/ui/pet_window.py`：接入按住陪玩会话、动态画布、目标更新、待完成投放及统一清理。
- 修改 `tests/test_package_validator.py`、`tests/test_package_loader.py`、`tests/test_interaction_items.py`：覆盖配置兼容性。
- 创建 `tests/test_interaction_play.py`：覆盖纯逻辑状态机。
- 修改 `tests/test_interaction_item_toolbox.py`：覆盖拖拽生命周期信号。
- 创建 `tests/test_drag_cursor_overlay.py`：覆盖光标覆盖层几何与输入透明属性。
- 修改 `tests/test_pet_window.py`：覆盖动态画布和端到端拖放语义。
- 修改未跟踪的 `pets/pinganv2/pet.json` 并新增未跟踪动作目录：仅用于本地运行验证，不加入 Git。

---

### 任务 1：宠物包支持独立动作画布和按住陪玩配置

**文件：**
- 修改：`src/petnest/models/pet_package.py:27-71`
- 修改：`src/petnest/core/package_validator.py:146-252`
- 修改：`src/petnest/core/package_validator.py:294-405`
- 修改：`src/petnest/core/package_loader.py:52-93`
- 修改：`src/petnest/core/package_loader.py:134-168`
- 修改：`src/petnest/core/interaction_items.py:15-66`
- 测试：`tests/test_package_validator.py`
- 测试：`tests/test_package_loader.py`
- 测试：`tests/test_interaction_items.py`

- [ ] **步骤 1：编写 pet 动作独立画布的失败测试**

在 `tests/test_package_validator.py` 增加：

```python
def test_pet_animation_accepts_its_own_canvas(tmp_path: Path) -> None:
    root = _write_package(
        tmp_path / "pet-canvas",
        animations={
            "idle": _animation("animations/idle"),
            "toy_ready": _animation(
                "animations/toy_ready",
                canvas={"width": 512, "height": 384},
            ),
        },
    )
    _write_webp(root / "animations" / "toy_ready" / "001.webp", 512, 384)

    result = PackageValidator().validate(root)

    assert result.is_valid, result.errors
```

再增加尺寸不匹配测试，期望错误同时包含动作名、实际尺寸和 `512×384`。

- [ ] **步骤 2：运行测试并确认因现有限制失败**

运行：

```bash
.venv/Scripts/python.exe -m pytest tests/test_package_validator.py -k "own_canvas" -v
```

预期：FAIL，错误包含“只有全屏动画可以声明独立 canvas”。

- [ ] **步骤 3：允许 pet 动作声明独立画布**

修改 `PackageValidator._animation_canvas()`：

```python
if "canvas" not in definition:
    return package_canvas
canvas = self._validate_canvas(definition["canvas"], f"动画 {name}", result)
return canvas or package_canvas
```

删除“只有全屏动画可以声明独立 canvas”的限制；保留 fullscreen 入口方向规则。修改 loader 的 `_animation_canvas()`，只要配置声明了 `canvas` 就返回 `Canvas`，否则返回 `None`。

- [ ] **步骤 4：运行独立画布测试确认通过**

运行：

```bash
.venv/Scripts/python.exe -m pytest tests/test_package_validator.py tests/test_package_loader.py -k "canvas" -v
```

预期：新增测试和既有 fullscreen canvas 测试全部 PASS。

- [ ] **步骤 5：编写有效 `hold_play` 加载失败测试**

在 `tests/test_package_loader.py` 构造带以下配置的包：

```python
"interaction_items": [{
    "id": "toy_wand",
    "label": "逗猫棒",
    "icon": "items/toy_wand.png",
    "hold_play": {
        "cursor": "items/toy_wand.png",
        "cursor_hotspot": [100, 105],
        "ready_action": "toy_ready",
        "attack_origin": [256, 310],
        "settle_ms": 140,
        "cooldown_ms": 350,
        "rearm_distance": 24,
        "targets": {
            "center": {
                "action": "toy_pounce_center",
                "contact_frame": 12,
                "contact_point": [256, 180],
                "max_correction": [12, 10],
            },
        },
    },
}]
```

断言 loader 返回的 `InteractionItemDefinition.hold_play` 不为空，且所有坐标转换为二元整数元组。普通投放动作字段允许为 `None`。

- [ ] **步骤 6：运行加载测试确认失败**

运行：

```bash
.venv/Scripts/python.exe -m pytest tests/test_package_loader.py -k "hold_play" -v
```

预期：FAIL，`InteractionItemDefinition` 尚无 `hold_play`。

- [ ] **步骤 7：添加配置模型**

在 `pet_package.py` 添加：

```python
HoldPlayDirection = Literal["center", "left", "right", "up_left", "up_right"]

@dataclass(frozen=True, slots=True)
class HoldPlayTargetDefinition:
    action: str
    contact_frame: int
    contact_point: tuple[int, int]
    max_correction: tuple[int, int]

@dataclass(frozen=True, slots=True)
class HoldPlayDefinition:
    cursor: Path
    cursor_hotspot: tuple[int, int]
    ready_action: str
    attack_origin: tuple[int, int]
    settle_ms: int
    cooldown_ms: int
    rearm_distance: int
    targets: dict[HoldPlayDirection, HoldPlayTargetDefinition]
```

给 `InteractionItemDefinition` 增加：

```python
hold_play: HoldPlayDefinition | None = None
```

- [ ] **步骤 8：实现 `hold_play` 校验和加载**

校验规则：

- `cursor` 必须是包内、存在、RGBA PNG，尺寸不超过 `512×512`。
- 热点必须是两个非负整数且落在 cursor 图片范围内。
- `ready_action` 和五方向 target 动作必须存在、scope 为 pet。
- target key 只能来自五个受支持方向，至少包含 `center`；其他方向可缺省。
- ready 与所有 target 动作必须声明同一个独立画布。
- `attack_origin`、`contact_point` 必须落在动作画布内。
- `contact_frame` 从 1 开始且不大于对应动作帧数。
- `settle_ms` 为 `50..1000`，`cooldown_ms` 为 `0..5000`，`rearm_distance` 为 `1..512`。
- `max_correction` 每轴为 `0..64`。

无效 `hold_play` 添加 warning 并返回 `None`。普通投放绑定仍按 `interaction.item.<id>` 独立解析；只要普通绑定或 `hold_play` 至少一项有效，道具就保留。两项都无效时才隐藏。

- [ ] **步骤 9：增加无效配置回退测试**

参数化覆盖：越界热点、未知动作、画布不一致、缺少 center、接触帧越界、包外 cursor。断言包仍可加载；有普通绑定时道具仍存在且 `hold_play is None`，无普通绑定时道具隐藏，warnings 有明确原因。

在 `tests/test_interaction_items.py` 增加四组解析测试：仅普通绑定、仅 `hold_play`、两者都有、两者都无效。将 `ResolvedInteractionItem.event_name` 和 `action_name` 改为可选字段，只有普通绑定存在时才赋值。

- [ ] **步骤 10：运行包模型相关测试**

运行：

```bash
.venv/Scripts/python.exe -m pytest tests/test_package_validator.py tests/test_package_loader.py tests/test_interaction_items.py -v
```

预期：全部 PASS。

- [ ] **步骤 11：提交任务 1**

```bash
git add src/petnest/models/pet_package.py src/petnest/core/package_validator.py src/petnest/core/package_loader.py src/petnest/core/interaction_items.py tests/test_package_validator.py tests/test_package_loader.py tests/test_interaction_items.py
git commit -m "feat: 支持按住陪玩配置与独立动作画布"
```

---

### 任务 2：实现纯逻辑按住陪玩控制器

**文件：**
- 创建：`src/petnest/core/interaction_play.py`
- 创建：`tests/test_interaction_play.py`

- [ ] **步骤 1：编写方向判定失败测试**

```python
@pytest.mark.parametrize(
    ("point", "expected"),
    [
        ((256, 180), "center"),
        ((120, 280), "left"),
        ((390, 280), "right"),
        ((180, 120), "up_left"),
        ((340, 120), "up_right"),
    ],
)
def test_resolve_direction_uses_attack_origin(point, expected, definition) -> None:
    controller = HoldPlayController(definition)
    assert controller.resolve_direction(point) == expected
```

另用只声明 `center` 的 definition 断言五个方向全部解析到 center 动作；用声明 `center` 与 `right` 的 definition 断言 `up_right` 回退到 right，而 `up_left` 回退到 center。

- [ ] **步骤 2：运行测试确认模块不存在**

运行：

```bash
.venv/Scripts/python.exe -m pytest tests/test_interaction_play.py -v
```

预期：collection ERROR，`petnest.core.interaction_play` 不存在。

- [ ] **步骤 3：创建状态和结果类型**

```python
class HoldPlayPhase(StrEnum):
    INACTIVE = "inactive"
    READY = "ready"
    ATTACKING = "attacking"
    COOLDOWN = "cooldown"
    PENDING_DROP = "pending_drop"
    SUSPENDED = "suspended"

@dataclass(frozen=True, slots=True)
class HoldPlayUpdate:
    phase: HoldPlayPhase
    action: str | None = None
    deadline_ms: int | None = None
    finish_drop: bool = False
```

`HoldPlayController` 构造参数仅为 `HoldPlayDefinition`，所有时间通过方法参数 `now_ms` 注入，测试不依赖真实时钟。

- [ ] **步骤 4：实现并验证方向判定**

实现规格中的 `dy < -60`、`|dx| <= 60` 和左右规则。运行：

```bash
.venv/Scripts/python.exe -m pytest tests/test_interaction_play.py -k "direction" -v
```

预期：方向测试 PASS。

- [ ] **步骤 5：编写稳定判定与攻击锁定失败测试**

测试流程：

```python
controller.enter(now_ms=0)
assert controller.move((390, 280), now_ms=10).action is None
assert controller.tick(now_ms=149).action is None
attack = controller.tick(now_ms=150)
assert attack.action == "toy_pounce_right"
controller.move((180, 120), now_ms=160)
assert controller.phase is HoldPlayPhase.ATTACKING
assert controller.current_direction == "right"
```

另测目标在 18 px 抖动半径内不重置计时，超出后重新计时。

- [ ] **步骤 6：实现稳定目标、攻击锁定和 deadline**

提供四个固定接口：`enter(*, now_ms: int) -> HoldPlayUpdate`、
`move(point: tuple[int, int], *, now_ms: int) -> HoldPlayUpdate`、
`tick(*, now_ms: int) -> HoldPlayUpdate`、
`attack_completed(*, now_ms: int) -> HoldPlayUpdate`。

`move()` 只记录候选点；达到 deadline 的 `tick()` 才输出攻击动作。

- [ ] **步骤 7：编写冷却和重触发失败测试**

完成一次攻击后，350 ms 内不得攻击；冷却后鼠标仍在原目标 24 px 内也不得攻击；移动超过 24 px 并稳定 140 ms 后允许下一次攻击。

- [ ] **步骤 8：实现冷却与 rearm**

`attack_completed()` 记录最后攻击目标和冷却结束时间。`move()` 在距离不足时保持 ready，不设置新的稳定 deadline。

- [ ] **步骤 9：编写画布内外释放失败测试**

覆盖：

- ready 状态且存在普通投放绑定时，`release_inside(has_drop_action=True)` 立即返回 `finish_drop=True`。
- ready 状态且不存在普通投放绑定时，`release_inside(has_drop_action=False)` 回到 inactive 且 `finish_drop=False`。
- attacking 状态 `release_inside()` 进入 pending_drop，`attack_completed()` 才返回 `finish_drop=True`。
- `leave()` 进入 suspended。
- suspended 状态 `release_outside()` 回到 inactive 且不完成投放。
- 任意状态 `cancel()` 回到 inactive 并清空目标。

- [ ] **步骤 10：实现释放和统一清理**

提供四个固定接口：`leave() -> HoldPlayUpdate`、
`release_inside(*, has_drop_action: bool) -> HoldPlayUpdate`、
`release_outside() -> HoldPlayUpdate`、`cancel() -> HoldPlayUpdate`。

- [ ] **步骤 11：编写接触帧校正失败测试**

`correction_for_frame()` 在接触帧前后两帧使用三角权重，接触帧达到完整校正，其余帧返回 `(0, 0)`；每轴受 `max_correction` 限制。

- [ ] **步骤 12：实现校正并运行全部控制器测试**

运行：

```bash
.venv/Scripts/python.exe -m pytest tests/test_interaction_play.py -v
```

预期：全部 PASS。

- [ ] **步骤 13：提交任务 2**

```bash
git add src/petnest/core/interaction_play.py tests/test_interaction_play.py
git commit -m "feat: 实现按住陪玩目标控制器"
```

---

### 任务 3：暴露拖拽生命周期并实现逗猫棒覆盖层

**文件：**
- 创建：`src/petnest/ui/drag_cursor_overlay.py`
- 修改：`src/petnest/ui/interaction_item_toolbox.py:251-342`
- 修改：`src/petnest/ui/interaction_item_toolbox.py:415-575`
- 创建：`tests/test_drag_cursor_overlay.py`
- 修改：`tests/test_interaction_item_toolbox.py`

- [ ] **步骤 1：编写覆盖层失败测试**

```python
def test_drag_cursor_overlay_tracks_hotspot_without_accepting_input(qtbot, tmp_path) -> None:
    icon = _write_rgba_icon(tmp_path / "wand.png", size=(128, 128))
    overlay = DragCursorOverlay()
    qtbot.addWidget(overlay)

    overlay.show_at(QPoint(500, 300), icon, hotspot=(100, 105))

    assert overlay.isVisible()
    assert overlay.windowFlags() & Qt.WindowType.WindowTransparentForInput
    assert overlay.mapToGlobal(QPoint(100, 105)) == QPoint(500, 300)
```

- [ ] **步骤 2：运行测试确认模块不存在**

运行：

```bash
.venv/Scripts/python.exe -m pytest tests/test_drag_cursor_overlay.py -v
```

预期：collection ERROR。

- [ ] **步骤 3：实现 `DragCursorOverlay`**

创建无焦点、透明、输入穿透的 Tool 窗口；使用 QLabel/PaintEvent 绘制按设备像素比缩放的 RGBA 图标。接口固定为：

接口固定为 `show_at(global_hotspot: QPoint, icon: Path, *, hotspot: tuple[int, int]) -> None`、
`move_hotspot(global_hotspot: QPoint) -> None` 和 `clear() -> None`。

`clear()` 必须隐藏窗口并释放 pixmap 引用。

- [ ] **步骤 4：运行覆盖层测试确认通过**

```bash
.venv/Scripts/python.exe -m pytest tests/test_drag_cursor_overlay.py -v
```

- [ ] **步骤 5：编写按钮拖拽生命周期失败测试**

给 `InteractionItemButton` 增加并测试：

```python
drag_started = Signal(str)
drag_finished = Signal(str, object)
```

测试用可注入的 `_execute_drag(drag)` 方法返回 `Qt.MoveAction`，断言开始信号先于结束信号，结束信号携带 item id 和动作；抛异常时也必须在 `finally` 发出结束信号。

- [ ] **步骤 6：实现生命周期信号并转发到 Toolbox**

`InteractionItemToolbox` 暴露同名信号，并在 `set_items()` 创建按钮时连接。保持普通按钮的 drag pixmap、tooltip 和 MoveAction 不变。

- [ ] **步骤 7：运行道具箱与覆盖层测试**

```bash
.venv/Scripts/python.exe -m pytest tests/test_interaction_item_toolbox.py tests/test_drag_cursor_overlay.py -v
```

预期：全部 PASS。

- [ ] **步骤 8：提交任务 3**

```bash
git add src/petnest/ui/drag_cursor_overlay.py src/petnest/ui/interaction_item_toolbox.py tests/test_drag_cursor_overlay.py tests/test_interaction_item_toolbox.py
git commit -m "feat: 暴露道具拖拽生命周期与光标层"
```

---

### 任务 4：PetWindow 接入动态画布与按住陪玩会话

**文件：**
- 修改：`src/petnest/ui/pet_window.py:95-180`
- 修改：`src/petnest/ui/pet_window.py:317-389`
- 修改：`src/petnest/ui/pet_window.py:607-693`
- 修改：`src/petnest/ui/pet_window.py:822-886`
- 修改：`src/petnest/ui/pet_window.py:973-1065`
- 修改：`tests/test_pet_window.py:101-160`
- 修改：`tests/test_pet_window.py:1048-1300`

- [ ] **步骤 1：编写动作画布切换失败测试**

构造默认 `10×8`、`toy_ready` 独立 `20×16` 的测试包。记录切换前 `window.mapToGlobal(window.rect().bottomLeft())` 和底部中心，播放 `toy_ready` 后断言：

- 窗口逻辑宠物尺寸变为 `20×16` 乘 scale。
- 底部中心全局坐标不变。
- 切回 idle 后恢复原尺寸和锚点。

- [ ] **步骤 2：运行测试确认失败**

```bash
.venv/Scripts/python.exe -m pytest tests/test_pet_window.py -k "action_canvas" -v
```

预期：FAIL，PetWindow 仍使用 package canvas。

- [ ] **步骤 3：实现当前动作画布和底部中心锚定**

新增：

```python
def _current_pet_canvas(self) -> Canvas:
    definition = self.package.animations[self._playing_action]
    return definition.canvas or self.package.canvas
```

新增 `_resize_for_action_canvas(previous_bottom_center: QPoint) -> None`：按新画布和 scale 设置固定尺寸，再把窗口移动到“新窗口底部中心等于 previous_bottom_center”的坐标并执行 clamp。

修改 `_pet_width()`、`_pet_height()`、`_set_current_frame()`、命中坐标和 paintEvent 使用当前动作画布。动作变化前记录全局底部中心，尺寸变化后恢复位置并 clamp。

- [ ] **步骤 4：运行画布测试和既有 PetWindow 测试**

```bash
.venv/Scripts/python.exe -m pytest tests/test_pet_window.py -k "canvas or scale or countdown" -v
```

- [ ] **步骤 5：编写拖入陪玩失败测试**

扩展 `_interaction_package()`，加入有效 `hold_play`。发送 toy_wand 的 `QDragEnterEvent` 和 `QDragMoveEvent`，断言：

- 画布扩展。
- `playing_action == "toy_ready"`。
- cursor overlay 可见且热点跟随全局位置。
- 透明画布点也接受 MoveAction。
- 普通道具在同一点仍拒绝。

- [ ] **步骤 6：实现会话创建、拖入和移动**

PetWindow 新增成员：

```python
self._hold_play_controller: HoldPlayController | None = None
self._hold_play_item_id: str | None = None
self._hold_play_restore_action: str | None = None
self._hold_play_timer = QTimer(self)
self._drag_cursor_overlay = DragCursorOverlay()
```

在 `dragEnterEvent()` 检测 `item.definition.hold_play`。进入后保存原动作，播放 ready，显示覆盖层并接受整个动作画布。`dragMoveEvent()` 将事件点转换为逻辑动作坐标，调用 controller.move() 并按 deadline 启动单次 QTimer。

- [ ] **步骤 7：编写稳定触发和方向锁定失败测试**

使用注入时钟或直接调用内部 deadline handler：右侧稳定后播放 `toy_pounce_right`；攻击中移动到左上仍保持右扑；动画完成后回到 ready。

- [ ] **步骤 8：实现 deadline、攻击完成和接触帧偏移**

在 `_on_animation_tick()` 检测当前 held-play 攻击完成并调用 controller.attack_completed()。paintEvent 根据当前 frame index 调用 `correction_for_frame()`，仅在接触窗口给宠物 pixmap 增加缩放后的 QPoint 偏移。

- [ ] **步骤 9：编写拖出、画布外松手和异常结束测试**

断言 `dragLeaveEvent()` 恢复原画布和动作、隐藏 overlay；toolbox 的 `drag_finished(item_id, IgnoreAction)` 调用统一 cancel；切换包、follow mode、mouse interaction disabled、hide 和 close 都清理全部状态。

- [ ] **步骤 10：实现统一清理方法**

```python
def _cancel_hold_play(self, *, restore: bool) -> None:
    self._hold_play_timer.stop()
    self._drag_cursor_overlay.clear()
    self._hold_play_controller = None
    self._hold_play_item_id = None
    self._restore_default_canvas_and_action() if restore else None
```

所有退出路径只调用该方法，不复制清理逻辑。

- [ ] **步骤 11：编写画布内松手失败测试**

覆盖两个场景：

1. ready 时 drop：立即恢复默认画布并触发 `interaction.item.toy_wand`，播放 `playing_toy`。
2. attacking 时 drop 且存在普通绑定：QDropEvent 已接受，但保持扩展画布直到扑抓完成；完成后再恢复并播放配置动作。
3. ready 或 attacking 时 drop 且不存在普通绑定：结束或自然完成当前扑抓后恢复，不播放额外动作。

- [ ] **步骤 12：实现 pending drop**

`dropEvent()` 对 held-play 道具调用 `release_inside(has_drop_action=item.action_name is not None)`。若 `finish_drop` 立即为真，结束会话后复用可选普通绑定；否则按 controller 状态决定保存待投放 item 或只结束陪玩。普通道具继续执行原逻辑。

- [ ] **步骤 13：运行 PetWindow、道具箱和控制器测试**

```bash
.venv/Scripts/python.exe -m pytest tests/test_interaction_play.py tests/test_drag_cursor_overlay.py tests/test_interaction_item_toolbox.py tests/test_pet_window.py -v
```

预期：全部 PASS。

- [ ] **步骤 14：提交任务 4**

```bash
git add src/petnest/ui/pet_window.py tests/test_pet_window.py
git commit -m "feat: 接入逗猫棒按住拖拽陪玩模式"
```

---

### 任务 5：接入平安 V2 资源并验证真实交互

**文件：**
- 修改但不跟踪：`pets/pinganv2/pet.json`
- 新增但不跟踪：`pets/pinganv2/animations/toy_ready/`
- 新增但不跟踪：`pets/pinganv2/animations/toy_pounce_center/`
- 新增但不跟踪：`pets/pinganv2/animations/toy_pounce_left/`
- 新增但不跟踪：`pets/pinganv2/animations/toy_pounce_right/`
- 新增但不跟踪：`pets/pinganv2/animations/toy_pounce_up_left/`
- 新增但不跟踪：`pets/pinganv2/animations/toy_pounce_up_right/`

- [ ] **步骤 1：复制已验证资源**

从：

```text
D:\downloaded\rembg\output\pinganv2-play-actions\final
```

复制六个动作目录到 `pets/pinganv2/animations/`。复制后检查：

```bash
.venv/Scripts/python.exe -c "from PIL import Image; from pathlib import Path; assert all(Image.open(p).size == (512, 384) for p in Path('pets/pinganv2/animations/toy_ready').glob('*.webp'))"
```

预期：退出码 0。

- [ ] **步骤 2：更新未跟踪的平安配置**

为六个动作声明 `canvas: {"width": 512, "height": 384}`、8 FPS、逐帧时长、优先级和首尾行为；给 `toy_wand` 增加规格中的 `hold_play`。保留既有：

```json
"interaction.item.toy_wand": "playing_toy"
```

- [ ] **步骤 3：运行真实宠物包校验**

```bash
.venv/Scripts/python.exe -c "from pathlib import Path; from petnest.core.package_validator import PackageValidator; r=PackageValidator().validate(Path('pets/pinganv2')); print(r.errors, r.warnings); raise SystemExit(0 if r.is_valid else 1)"
```

预期：退出码 0，errors 为空。

- [ ] **步骤 4：确认资源没有进入 Git 暂存区**

```bash
git diff --cached --name-only
git status --short pets/pinganv2
```

预期：缓存区无 `pets/pinganv2`；资源只显示为未跟踪内容。

- [ ] **步骤 5：运行最新版并手动验证**

验证清单：

- 拖动其他道具行为不变。
- 按住逗猫棒进入画布后显示 wand 覆盖层和 `toy_ready`。
- 在中央、左右、左上、右上分别停留，方向正确。
- 同一点不重复扑，移动后重新触发。
- 扑抓中移动不抽搐。
- 画布内松手最终播放 `playing_toy`。
- 用仅 `hold_play`、没有 `interaction.item.<id>` 绑定的测试宠物验证：道具仍显示，画布内松手只结束陪玩。
- 画布外松手直接恢复。
- 猫的脚底不跳、大小不缩、爪子和尾巴不裁切。

本任务不创建 Git commit。

---

### 任务 6：全量回归、代码审查与收尾提交

**文件：**
- 检查：本计划涉及的所有已跟踪源码和测试
- 不提交：`pets/pinganv2/**`

- [ ] **步骤 1：运行格式和差异检查**

```bash
git diff --check
git status --short
```

预期：无空白错误；已跟踪修改均属于本功能；宠物资源仍未跟踪。

- [ ] **步骤 2：运行全部相关测试**

```bash
.venv/Scripts/python.exe -m pytest tests/test_package_validator.py tests/test_package_loader.py tests/test_interaction_items.py tests/test_interaction_play.py tests/test_drag_cursor_overlay.py tests/test_interaction_item_toolbox.py tests/test_pet_window.py -v
```

预期：全部 PASS。

- [ ] **步骤 3：运行完整测试套件**

```bash
.venv/Scripts/python.exe -m pytest
```

预期：全部适用测试 PASS。若 Windows 主机上的 macOS 权限或符号链接测试失败，单独复现并明确记录为平台限制；不得把相关失败描述为通过。

- [ ] **步骤 4：请求代码审查**

使用 `requesting-code-review` 检查：包兼容性、拖放清理、动态画布锚点、计时状态、资源未提交和测试覆盖。

- [ ] **步骤 5：修复审查问题并重跑相关测试**

每项问题单独修改并运行最小相关测试；最后重新运行步骤 2。

- [ ] **步骤 6：确认提交边界**

```bash
git diff --cached --name-only
git log --oneline --decorate -8
```

预期：代码提交中不包含 `pets/`、D 盘输出、截图、GIF 或临时脚本。

- [ ] **步骤 7：报告结果，不自动推送**

报告已生成的代码提交、测试结果、真实运行结果和仍未跟踪的资源。只有用户明确要求时才更新远端。
