# 互动道具拖拽视觉优化实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 消除互动道具入口的黑色窗口底与常驻按钮底板，并让展开后的道具盘通过托盘布局、抓取光标、浮起反馈和首次提示明确表达“把道具拖给宠物”。

**架构：** 所有表现逻辑继续封装在 `InteractionItemToolbox` 和 `InteractionItemButton` 中。顶层工具窗口只修正透明合成和入口样式；道具按钮维护自己的悬停、按下与拖动视觉状态；工具箱维护标题、布局和单实例首次提示。`PetWindow`、通用事件协议、宠物包格式和资源不变。

**技术栈：** Python 3.12、PySide6、Qt Style Sheets、Qt 属性动画、pytest、pytest-qt。

---

## 任务 1：修复透明窗口并改为纯盒子入口

**文件：**
- 修改：`src/petnest/ui/interaction_item_toolbox.py`
- 测试：`tests/test_interaction_item_toolbox.py`

- [ ] **步骤 1：编写失败的透明入口测试**

在 `tests/test_interaction_item_toolbox.py` 增加测试，验证：

```python
def test_toolbox_uses_translucent_window_and_icon_only_launcher(qtbot) -> None:
    toolbox = InteractionItemToolbox()
    qtbot.addWidget(toolbox)

    assert toolbox.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    assert toolbox.launcher.objectName() == "interactionItemLauncher"
    assert toolbox.launcher.cursor().shape() == Qt.CursorShape.PointingHandCursor
    assert "QToolButton#interactionItemLauncher" in toolbox.styleSheet()
    assert "QToolButton {" not in toolbox.styleSheet()
```

测试只锁定透明合成、专用选择器和点击光标，不依赖像素级平台渲染结果。

- [ ] **步骤 2：运行测试确认失败**

运行：

```bash
set QT_QPA_PLATFORM=offscreen
../../.venv/Scripts/python.exe -m pytest tests/test_interaction_item_toolbox.py::test_toolbox_uses_translucent_window_and_icon_only_launcher -q
```

预期：FAIL，因为工具窗口尚未启用 `WA_TranslucentBackground`，入口也没有专用 object name。

- [ ] **步骤 3：实现透明入口与独立样式**

在 `InteractionItemToolbox.__init__` 中：

- 设置 `WA_TranslucentBackground`。
- 将入口 object name 设为 `interactionItemLauncher`，并使用 `PointingHandCursor`。
- 删除作用于所有 `QToolButton` 的通用规则。
- 为入口建立专用规则：常态透明背景、无边框；悬停、按下和 checked 状态只显示低不透明度圆形暖色光晕。
- 保留 44 px 命中区域、22 px 图标、无焦点和工具提示。
- 通过轻量 `QGraphicsDropShadowEffect` 给盒子图形增加中性投影，控制 blur 和 offset，避免出现厚重黑边。

- [ ] **步骤 4：运行入口测试与现有工具箱测试**

运行：

```bash
set QT_QPA_PLATFORM=offscreen
../../.venv/Scripts/python.exe -m pytest tests/test_interaction_item_toolbox.py -q
```

预期：全部通过。

- [ ] **步骤 5：Commit**

```bash
git add src/petnest/ui/interaction_item_toolbox.py tests/test_interaction_item_toolbox.py
git commit -m "fix: remove interaction launcher window chrome"
```

## 任务 2：把按钮列表改成可拿取的托盘道具

**文件：**
- 修改：`src/petnest/ui/interaction_item_toolbox.py`
- 修改：`tests/test_interaction_item_toolbox.py`

- [ ] **步骤 1：编写失败的拖拽暗示测试**

扩展按钮和工具箱测试，验证：

```python
def test_item_button_advertises_dragging(qtbot, tmp_path: Path) -> None:
    item = _resolved_item(tmp_path, "toy_ball")
    button = InteractionItemButton(item)
    qtbot.addWidget(button)

    assert button.objectName() == "interactionItemButton"
    assert button.cursor().shape() == Qt.CursorShape.OpenHandCursor
    assert button.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonTextUnderIcon
    assert button.text() == item.definition.label
    assert button.toolTip() == "拖动 Item toy_ball 到宠物身上"
```

再用 `qtbot.mousePress` 和 `qtbot.mouseRelease` 验证按下时为 `ClosedHandCursor`、释放后恢复 `OpenHandCursor`。在工具箱测试中验证 `toolbox.hint_label.text() == "拖给宠物"`，以及十个输入仍只保留前八个并按四列布局。

- [ ] **步骤 2：运行新增测试确认失败**

运行：

```bash
set QT_QPA_PLATFORM=offscreen
../../.venv/Scripts/python.exe -m pytest tests/test_interaction_item_toolbox.py -k "advertises_dragging or first_eight" -q
```

预期：FAIL，因为道具仍是无文字的普通按钮外观，没有标题或抓取光标。

- [ ] **步骤 3：实现开放托盘布局**

在 `InteractionItemToolbox` 中：

- 给面板增加纵向布局和 object name 为 `interactionItemHint` 的标题 `QLabel("拖给宠物")`。
- 将原 `QGridLayout` 放入独立的透明内容容器，保持最多八项、四列和声明顺序。
- 面板保留暖白背景、细边框与紧凑圆角；标题使用小号中性色文字。
- 为 `interactionItemButton` 使用独立透明样式，移除矩形边框、按下凹陷和常驻底板。
- 道具按钮显示图标下方名称，固定稳定命中尺寸；完整名称仍保留在工具提示和无障碍文本中。

在 `InteractionItemButton` 中：

- 常态使用 `OpenHandCursor`，左键按下使用 `ClosedHandCursor`，释放、取消或拖拽结束后恢复。
- 悬停时轻微增大图标并启用柔和阴影；离开时恢复。
- 开始 `QDrag` 前保存图标并进入 dragging 动态属性状态，拖动期间降低原位视觉权重；`drag.exec()` 返回后在 `finally` 中完整恢复。
- 保留现有拖拽阈值、MIME 只携带通用 item ID、拖拽副本热点位于中心。

- [ ] **步骤 4：运行工具箱与宠物窗口回归测试**

运行：

```bash
set QT_QPA_PLATFORM=offscreen
../../.venv/Scripts/python.exe -m pytest tests/test_interaction_item_toolbox.py tests/test_pet_window.py -q
```

预期：全部通过，既有拖放事件和生命周期行为不变。

- [ ] **步骤 5：Commit**

```bash
git add src/petnest/ui/interaction_item_toolbox.py tests/test_interaction_item_toolbox.py
git commit -m "feat: make interaction items visually draggable"
```

## 任务 3：增加单实例首次拖拽提示

**文件：**
- 修改：`src/petnest/ui/interaction_item_toolbox.py`
- 修改：`tests/test_interaction_item_toolbox.py`

- [ ] **步骤 1：编写失败的首次提示测试**

增加测试，使用连接到 `intro_hint_started` 信号的列表验证：

```python
def test_first_open_plays_drag_hint_once(qtbot, tmp_path: Path) -> None:
    toolbox = InteractionItemToolbox()
    qtbot.addWidget(toolbox)
    toolbox.set_items((_resolved_item(tmp_path, "toy"),))
    starts: list[bool] = []
    toolbox.intro_hint_started.connect(lambda: starts.append(True))

    toolbox.open_panel()
    toolbox.collapse()
    toolbox.open_panel()

    assert starts == [True]
    assert toolbox.intro_has_played
```

同时验证空道具盘不会标记教学已播放，设置第一批有效道具后仍可播放一次。

- [ ] **步骤 2：运行首次提示测试确认失败**

运行：

```bash
set QT_QPA_PLATFORM=offscreen
../../.venv/Scripts/python.exe -m pytest tests/test_interaction_item_toolbox.py::test_first_open_plays_drag_hint_once -q
```

预期：FAIL，因为工具箱还没有首次提示状态与信号。

- [ ] **步骤 3：实现一次性提示与轻量动画**

在 `InteractionItemToolbox` 中：

- 增加 `intro_hint_started = Signal()`、`_intro_has_played` 和只读 `intro_has_played`。
- 第一次打开非空面板时设置状态并发出信号；同一实例后续展开不再触发。
- 使用 `QSequentialAnimationGroup` 和两个 `QPropertyAnimation` 对第一个道具的 `iconSize` 做一次约 700 ms 的放大再复位。
- 暂时给标题设置 `intro=true` 动态属性并刷新样式，动画结束后恢复；静态标题始终存在。
- 保存动画对象引用，避免被垃圾回收；面板关闭、工具箱隐藏或对象销毁时停止并恢复图标尺寸。

- [ ] **步骤 4：运行定向回归测试**

运行：

```bash
set QT_QPA_PLATFORM=offscreen
../../.venv/Scripts/python.exe -m pytest tests/test_interaction_item_toolbox.py tests/test_pet_window.py tests/test_app_and_platforms.py -q
```

预期：全部通过。

- [ ] **步骤 5：Commit**

```bash
git add src/petnest/ui/interaction_item_toolbox.py tests/test_interaction_item_toolbox.py
git commit -m "feat: teach interaction item dragging on first open"
```

## 任务 4：完整验证与视觉验收

**文件：**
- 必要时修改：`src/petnest/ui/interaction_item_toolbox.py`
- 必要时修改：`tests/test_interaction_item_toolbox.py`

- [ ] **步骤 1：运行格式检查与完整测试**

```bash
git diff --check main...HEAD
set QT_QPA_PLATFORM=offscreen
../../.venv/Scripts/python.exe -m pytest -q
```

预期：`git diff --check` 无输出；完整套件全部通过，平台不支持的符号链接测试可保持既有 skip。

- [ ] **步骤 2：渲染并检查关键状态**

使用最小 Qt 预览脚本在离屏环境分别渲染以下状态到临时 PNG，不把预览图提交到仓库：

1. 仅入口常态。
2. 入口悬停或 checked 状态。
3. 展开托盘，包含四个示例道具。
4. 第一个道具悬停或抓取状态。

逐张确认顶层四角透明、无黑色方框、入口无常驻白底、标题清晰、道具不像普通按钮、文本没有裁切且阴影不被窗口边缘截断。

- [ ] **步骤 3：运行应用自检**

```bash
../../.venv/Scripts/python.exe -m petnest --check
```

预期：退出码为 0，并发现至少一个可用宠物包。

- [ ] **步骤 4：最终整理提交（仅在视觉验收产生修正时）**

```bash
git add src/petnest/ui/interaction_item_toolbox.py tests/test_interaction_item_toolbox.py
git commit -m "fix: refine interaction item drag affordance"
git status --short
```

若没有额外修改，则不创建空提交。

## 任务 5：恢复完整盒子结构并稍微放大入口图形

**文件：**
- 修改：`src/petnest/ui/lucide_icons.py`
- 修改：`src/petnest/ui/interaction_item_toolbox.py`
- 修改：`tests/test_interaction_item_toolbox.py`

- [ ] **步骤 1：编写失败的分层图标测试**

扩展入口测试，验证图标尺寸为 `25 × 25`，盒体内部存在填充像素，并且盒盖折线位置存在比填充更深的描边像素。测试不依赖整张截图，只采样稳定的内部区域和结构线区域。

- [ ] **步骤 2：运行测试确认失败**

```bash
set QT_QPA_PLATFORM=offscreen
.venv/Scripts/python.exe -m pytest tests/test_interaction_item_toolbox.py::test_toolbox_uses_translucent_window_and_icon_only_launcher -q
```

预期：FAIL，因为当前图标仍为 22 px，且 SVG 根级填充会让后绘制 path 覆盖前面的结构线。

- [ ] **步骤 3：实现填充层与描边层分离**

调整 `lucide_icon()`：传入 `fill` 时先用 `stroke="none"` 绘制一份填充节点，再用 `fill="none"` 绘制完整原始描边节点。未传 `fill` 的既有图标输出保持不变。互动入口使用暖橙填充、深橙描边和 25 px 尺寸，按钮命中区域仍为 44 px。

- [ ] **步骤 4：运行入口与图标相关测试**

```bash
set QT_QPA_PLATFORM=offscreen
.venv/Scripts/python.exe -m pytest tests/test_interaction_item_toolbox.py -q
```

预期：全部通过。

## 任务 6：用生成图片把平面面板改成自然木置物架

**文件：**
- 创建：`assets/interaction_items/wood_shelf.png`
- 修改：`src/petnest/ui/interaction_item_toolbox.py`
- 修改：`tests/test_interaction_item_toolbox.py`

- [ ] **步骤 1：编写失败的托盘层次与道具抬起测试**

新增测试验证：

- 面板使用专用 `InteractionItemPanel`，加载 `1200 × 400` RGBA 木质置物架资源；资源上方透明且层板区域不透明。
- 道具按钮常态 `lifted` 为 false；进入时变为 true、图标增大；离开时恢复。
- dragging 状态隐藏图标但保留按钮绘制区域，使接触阴影和空槽仍可见。
- 现有四列、最多八项、标题、工具提示和拖放 MIME 测试保持不变。

- [ ] **步骤 2：运行新增测试确认失败**

```bash
set QT_QPA_PLATFORM=offscreen
.venv/Scripts/python.exe -m pytest tests/test_interaction_item_toolbox.py -q
```

预期：FAIL，因为当前面板仍由单个 QSS 圆角矩形绘制，道具也没有接触阴影和独立抬起属性。

- [ ] **步骤 3：实现浅纸箱与立体道具**

- 使用内置生图生成一个空的自然白橡木置物架透明 PNG：无文字、无道具、低后沿、薄倒角层板、左右端盖紧凑、中段平直可延展。保留透明上方空间并缩放为 `1200 × 400` RGBA 项目资源。
- 创建 `InteractionItemPanel(QFrame)` 加载资源，并在 `paintEvent()` 中使用 150 px 源端盖进行横向三段绘制；只拉伸中段，保持左右折角和纵向比例。
- 去掉 `interactionItemPanel` 的 QSS 实心背景和边框，避免覆盖图片资产。
- 增加面板底部布局空间，使前挡板位于图标与文字下方，不遮挡标签或鼠标命中。
- 在 `InteractionItemButton.paintEvent()` 中先绘制椭圆接触阴影，再调用原按钮绘制。
- 进入/离开时切换 `lifted` 动态属性，并通过稳定 padding、图标尺寸与阴影宽度差形成上抬效果；不对碗、猫条等素材做透视扭曲。
- dragging 状态继续隐藏图标，但接触阴影和淡槽位保留。

- [ ] **步骤 4：运行定向测试并渲染四道具预览**

```bash
set QT_QPA_PLATFORM=offscreen
.venv/Scripts/python.exe -m pytest tests/test_interaction_item_toolbox.py tests/test_pet_window.py -q
```

使用本地四个道具渲染入口常态、展开托盘和首个道具悬停状态，确认盒盖线完整、入口尺寸合适、托盘纵深清楚、图标像竖立在箱底且所有文字完整。

- [ ] **步骤 5：完整验证并合并到上一提交**

```bash
git diff --check
set QT_QPA_PLATFORM=offscreen
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m petnest --check
git add assets/interaction_items/wood_shelf.png docs/superpowers/specs/2026-08-31-interaction-item-drag-affordance-design.md docs/superpowers/plans/2026-08-31-interaction-item-drag-affordance.md src/petnest/ui/lucide_icons.py src/petnest/ui/interaction_item_toolbox.py tests/test_interaction_item_toolbox.py
git commit --amend --no-edit
```

不创建新分支或新提交；最终仍只保留一个 `feat:improve-interaction-item-drag-affordance` 提交。
