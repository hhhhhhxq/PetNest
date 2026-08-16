# 编辑动作页面按交互原型对齐实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 让统一“宠物与动作”中心的编辑动作页按已确认网页原型显示动作列表、时长编辑和常驻实时预览，并保留现有保存、草稿与回滚行为。

**架构：** 保持 `AnimationEditorPage`、`AnimationTimingEditor`、`AnimationPreviewWidget` 和 `PetActionExchangeDialog` 的既有职责，只调整组合布局并为预览补充公开的定位／重播接口。窗口外壳负责提供足够宽度，编辑器负责三栏最低尺寸和数据同步，预览组件继续唯一拥有计时器与帧渲染。

**技术栈：** Python 3.12、PySide6、pytest、pytest-qt

---

## 文件结构

- 修改：`src/petnest/ui/pet_action_exchange_dialog.py` — 统一中心初始与最小尺寸。
- 修改：`src/petnest/ui/animation_editor_page.py` — 原型式顶部宠物选择行和嵌入编辑器空间分配。
- 修改：`src/petnest/ui/animation_timing_editor.py` — 三栏布局、动作缩略图、预览元数据和控制连接。
- 修改：`src/petnest/ui/animation_preview_widget.py` — 公开帧定位与重播接口。
- 修改：`tests/test_pet_action_exchange_dialog.py` — 标准窗口下预览可见性和外壳尺寸回归。
- 修改：`tests/test_animation_editor_page.py` — 页内选择器和编辑区布局回归。
- 修改：`tests/test_animation_timing_editor.py` — 三栏尺寸、缩略图、元数据和预览同步回归。
- 修改：`tests/test_animation_preview_widget.py` — 播放、定位和重播接口回归。

### 任务 1：锁定标准窗口的三栏与预览可见性

**文件：**
- 修改：`tests/test_pet_action_exchange_dialog.py`
- 修改：`tests/test_animation_timing_editor.py`
- 修改：`src/petnest/ui/pet_action_exchange_dialog.py:61-62`
- 修改：`src/petnest/ui/animation_timing_editor.py:82-219,314-321`

- [ ] **步骤 1：编写失败的窗口与三栏测试**

在 `tests/test_pet_action_exchange_dialog.py` 增加：

```python
def test_editor_page_keeps_preview_visible_at_standard_dialog_size(qtbot, tmp_path):
    package = PackageLoader().load(_write_package(tmp_path / "pet"))
    dialog = PetActionExchangeDialog([package], tmp_path / "pets")
    qtbot.addWidget(dialog)
    dialog.select_page("编辑动作")
    dialog.show()
    qtbot.wait(10)

    editor = dialog.animation_editor_page.editor
    assert dialog.width() >= 1220
    assert editor is not None
    assert editor.preview_card.isVisible()
    assert editor.preview_card.width() >= 260
```

在 `tests/test_animation_timing_editor.py` 增加：

```python
def test_timing_editor_uses_prototype_three_column_minimums(qtbot, tmp_path):
    editor = AnimationTimingEditor(_package(tmp_path))
    qtbot.addWidget(editor)
    editor.resize(1000, 620)
    editor.show()
    qtbot.wait(10)

    assert editor.action_card.minimumWidth() == 205
    assert editor.editor_card.minimumWidth() == 360
    assert editor.preview_card.minimumWidth() == 260
    assert editor.preview_card.isVisible()
```

- [ ] **步骤 2：运行测试验证正确失败**

运行：

```powershell
python -m pytest -q tests/test_pet_action_exchange_dialog.py::test_editor_page_keeps_preview_visible_at_standard_dialog_size tests/test_animation_timing_editor.py::test_timing_editor_uses_prototype_three_column_minimums
```

预期：FAIL；当前对话框宽度为 1100、动作栏最小宽度为 450，且编辑器宽度不足 1180 时隐藏预览。

- [ ] **步骤 3：实现原型尺寸和常驻预览**

在 `PetActionExchangeDialog.__init__` 使用：

```python
self.resize(1220, 760)
self.setMinimumSize(1180, 680)
```

在 `AnimationTimingEditor.__init__` 设置三栏：

```python
self.action_card.setMinimumWidth(205)
self.action_card.setMaximumWidth(250)
self.editor_card.setMinimumWidth(360)
self.preview_card.setMinimumWidth(260)
self.preview_card.setMaximumWidth(320)
root.setStretch(0, 0)
root.setStretch(1, 1)
root.setStretch(2, 0)
self.preview_card.setVisible(True)
```

删除 `resizeEvent()` 和 `_sync_responsive_preview()`，以及构造函数中对 `_sync_responsive_preview()` 的调用。预览不再根据编辑器宽度静默隐藏。

- [ ] **步骤 4：运行测试验证通过**

运行：

```powershell
python -m pytest -q tests/test_pet_action_exchange_dialog.py tests/test_animation_timing_editor.py
```

预期：PASS。

- [ ] **步骤 5：提交三栏布局**

```powershell
git add src/petnest/ui/pet_action_exchange_dialog.py src/petnest/ui/animation_timing_editor.py tests/test_pet_action_exchange_dialog.py tests/test_animation_timing_editor.py
git commit -m "fix: keep animation preview visible in exchange center"
```

### 任务 2：为实时预览提供公开定位和重播能力

**文件：**
- 修改：`tests/test_animation_preview_widget.py`
- 修改：`src/petnest/ui/animation_preview_widget.py:117-165`
- 修改：`src/petnest/ui/animation_timing_editor.py:518-568`

- [ ] **步骤 1：编写失败的预览控制测试**

在 `tests/test_animation_preview_widget.py` 增加：

```python
def test_preview_can_seek_and_replay_with_public_api(qtbot, tmp_path):
    first = tmp_path / "1.png"
    second = tmp_path / "2.png"
    write_png(first, (255, 0, 0, 255))
    write_png(second, (0, 255, 0, 255))
    widget = AnimationPreviewWidget()
    qtbot.addWidget(widget)
    widget.set_frames((first, second), frame_durations_ms=(100, 100))

    widget.set_current_frame(1, pause=True)
    assert widget.preview_frame_index == 1
    assert not widget.preview_timer.isActive()

    widget.replay()
    assert widget.preview_frame_index == 0
    assert widget.preview_timer.isActive()
```

- [ ] **步骤 2：运行测试验证正确失败**

运行：

```powershell
python -m pytest -q tests/test_animation_preview_widget.py::test_preview_can_seek_and_replay_with_public_api
```

预期：FAIL，`AnimationPreviewWidget` 尚无 `set_current_frame()` 和 `replay()`。

- [ ] **步骤 3：实现公开预览接口**

在 `AnimationPreviewWidget` 增加：

```python
def set_current_frame(self, index: int, *, pause: bool = False) -> None:
    if not self._pixmaps or self._invalid_frame:
        return
    if pause:
        self.set_playing(False)
    self.preview_frame_index = max(0, min(int(index), len(self._pixmaps) - 1))
    self._render()
    self.frame_changed.emit(self.preview_frame_index)

def replay(self) -> None:
    if not self._pixmaps or self._invalid_frame:
        return
    self.set_current_frame(0)
    self.set_playing(True)
```

把 `AnimationTimingEditor._set_preview_frame()` 改为调用 `self.preview.set_current_frame(index, pause=True)`，兼容方法 `_render_preview()` 和 `_advance_preview()` 保留，但不再直接读取 `_pixmaps` 或调用 `_render()`。

- [ ] **步骤 4：运行预览与编辑器测试**

运行：

```powershell
python -m pytest -q tests/test_animation_preview_widget.py tests/test_animation_timing_editor.py tests/test_animation_editor_dialog.py
```

预期：PASS。

- [ ] **步骤 5：提交公开预览接口**

```powershell
git add src/petnest/ui/animation_preview_widget.py src/petnest/ui/animation_timing_editor.py tests/test_animation_preview_widget.py
git commit -m "feat: add seek and replay controls to animation preview"
```

### 任务 3：按原型补齐动作缩略图、预览元数据和页面层次

**文件：**
- 修改：`tests/test_animation_timing_editor.py`
- 修改：`tests/test_animation_editor_page.py`
- 修改：`src/petnest/ui/animation_timing_editor.py:88-216,323-376`
- 修改：`src/petnest/ui/animation_editor_page.py:52-84`

- [ ] **步骤 1：编写失败的内容同步测试**

在 `tests/test_animation_timing_editor.py` 增加：

```python
def test_action_selection_syncs_thumbnail_and_preview_metadata(qtbot, tmp_path):
    editor = AnimationTimingEditor(_package(tmp_path))
    qtbot.addWidget(editor)
    editor.action_table.selectRow(0)

    action_item = editor.action_table.item(0, 0)
    assert action_item is not None
    assert not action_item.icon().isNull()
    assert editor.preview_action_value.text() == "idle"
    assert editor.preview_frame_count_value.text() == "2"
    assert editor.preview_loop_value.text() in {"是", "否"}
    assert editor.preview_replay_button.text() == "重播"
```

在 `tests/test_animation_editor_page.py` 增加：

```python
from PySide6.QtWidgets import QSizePolicy


def test_editor_page_places_pet_selector_in_compact_header(qtbot, tmp_path):
    page = _page(tmp_path)
    qtbot.addWidget(page)
    assert page.pet_combo.maximumWidth() == 260
    assert page.editor_stack.sizePolicy().verticalPolicy() == QSizePolicy.Policy.Expanding
```

- [ ] **步骤 2：运行测试验证正确失败**

运行：

```powershell
python -m pytest -q tests/test_animation_timing_editor.py::test_action_selection_syncs_thumbnail_and_preview_metadata tests/test_animation_editor_page.py::test_editor_page_places_pet_selector_in_compact_header
```

预期：FAIL，动作行无首帧图标，预览元数据、重播按钮和紧凑宠物选择器尚不存在。

- [ ] **步骤 3：实现动作行和预览卡片**

在 `_populate_action_table()` 为动作名项使用首帧：

```python
if column == 0:
    item.setData(Qt.ItemDataRole.UserRole, action)
    pixmaps = self._pixmaps_for(action)
    if pixmaps and not pixmaps[0].isNull():
        item.setIcon(QIcon(pixmaps[0]))
```

将动作表图标尺寸设为 `QSize(38, 38)`，行高至少 58 px；第一列展示动作名，第二列展示“触发说明 · 帧数 · 秒数”。

在预览卡片中给播放按钮旁增加 `preview_replay_button`，并连接 `self.preview.replay`。在按钮下增加 `preview_action_value`、`preview_frame_count_value`、`preview_loop_value` 三个值标签；`_load_selected_action()` 每次选择时写入当前动作、帧数与循环状态。

在 `AnimationEditorPage` 把宠物标签和选择器放入同一紧凑顶行，将 `pet_combo` 最大宽度设为 260；继续保留现有 `pageTitle` 与 `mutedLabel`，由统一外壳隐藏重复标题。

- [ ] **步骤 4：运行页面、编辑器和兼容测试**

运行：

```powershell
python -m pytest -q tests/test_animation_timing_editor.py tests/test_animation_editor_page.py tests/test_animation_editor_dialog.py tests/test_pet_action_exchange_dialog.py
```

预期：PASS。

- [ ] **步骤 5：提交原型内容对齐**

```powershell
git add src/petnest/ui/animation_timing_editor.py src/petnest/ui/animation_editor_page.py tests/test_animation_timing_editor.py tests/test_animation_editor_page.py
git commit -m "feat: align animation editor content with approved prototype"
```

### 任务 4：完整回归与运行时视觉验收

**文件：**
- 验证：`src/petnest/ui/animation_preview_widget.py`
- 验证：`src/petnest/ui/animation_timing_editor.py`
- 验证：`src/petnest/ui/animation_editor_page.py`
- 验证：`src/petnest/ui/pet_action_exchange_dialog.py`
- 验证：`docs/superpowers/prototypes/action-duration-editor-v1.html`

- [ ] **步骤 1：运行编辑与交换中心定向回归**

```powershell
python -m pytest -q tests/test_animation_preview_widget.py tests/test_animation_timing_editor.py tests/test_animation_editor_dialog.py tests/test_animation_editor_page.py tests/test_pet_action_exchange_dialog.py tests/test_pet_action_exchange_app.py
```

预期：全部 PASS，只有仓库既有的 Windows 符号链接权限用例可被 skip。

- [ ] **步骤 2：运行完整测试集**

```powershell
python -m pytest -q
```

预期：全部 PASS，输出无新增错误或警告。

- [ ] **步骤 3：执行静态检查**

```powershell
python -m compileall -q src
git diff --check
git status --short
```

预期：编译成功、`git diff --check` 无输出，状态中只包含本计划涉及的源码和测试。

- [ ] **步骤 4：启动应用进行并排视觉验收**

从当前 worktree 启动 PetNest，打开“宠物与动作…”并切换到“编辑动作”。将 Qt 页面与 `docs/superpowers/prototypes/action-duration-editor-v1.html` 并排检查：三栏均可见，右侧棋盘格中播放真实宠物帧，动作切换同步缩略图和元数据，总时长／逐帧修改立即改变预览节奏，底部操作仍由统一外壳承载。

- [ ] **步骤 5：提交视觉验收中的必要微调**

如并排验收只发现间距、固定宽度或文案偏差，先为可测试的偏差补失败断言，再修改对应 Qt 属性，然后运行任务 4 的定向回归并提交：

```powershell
git add src/petnest/ui tests
git commit -m "style: finish animation editor prototype alignment"
```

若无需微调，不创建空提交。
