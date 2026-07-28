# 动画编辑器帧预览实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 在动画时长编辑器中显示逐帧缩略图，并提供按当前时间线实时循环的动作预览。

**架构：** 在 `AnimationEditorDialog` 内维护一个仅用于编辑预览的 `QTimer`、当前预览帧索引和 Pillow 缩略图缓存。帧行改为缩略图、帧号和时长输入；右侧预览标签显示缩放后的当前帧。修改时间线、切换动作或切换模式时重启预览，不改变 `pet.json` 写入接口。

**技术栈：** Python 3.12、PySide6、Pillow、pytest-qt。

---

## 文件结构

- 修改：`src/petnest/ui/animation_editor_dialog.py` — 管理缩略图、实时预览计时器和预览界面。
- 修改：`tests/test_animation_editor_dialog.py` — 覆盖帧缩略图、预览推进、修改时长后的重启和清理。

### 任务 1：逐帧缩略图列表

**文件：**
- 修改：`src/petnest/ui/animation_editor_dialog.py`
- 测试：`tests/test_animation_editor_dialog.py`

- [x] **步骤 1：编写失败的测试**

```python
def test_per_frame_editor_shows_one_thumbnail_for_each_frame(qtbot, tmp_path):
    dialog = AnimationEditorDialog(_package(tmp_path))
    qtbot.addWidget(dialog)
    dialog.per_frame_radio.click()

    assert dialog.frame_list.count() == len(dialog._package.animations["idle"].frames)
    assert dialog.frame_list.item(0).icon().isNull() is False
```

- [x] **步骤 2：运行测试验证失败**

运行：`C:\Python312\python.exe -m pytest tests/test_animation_editor_dialog.py::test_per_frame_editor_shows_one_thumbnail_for_each_frame -q`

预期：FAIL，提示 `AnimationEditorDialog` 没有 `frame_list`。

- [x] **步骤 3：编写最少实现代码**

```python
self.frame_list = QListWidget(self)
self.frame_list.setViewMode(QListView.ViewMode.IconMode)

def _populate_frame_list(self, action: str) -> None:
    self.frame_list.clear()
    for index, path in enumerate(self._package.animations[action].frames):
        image = QImage(str(path))
        item = QListWidgetItem(QIcon(QPixmap.fromImage(image)), f"{index + 1} · {self._timelines[action][index]} ms")
        self.frame_list.addItem(item)
```

- [x] **步骤 4：运行测试验证通过**

运行：`C:\Python312\python.exe -m pytest tests/test_animation_editor_dialog.py::test_per_frame_editor_shows_one_thumbnail_for_each_frame -q`

预期：PASS。

### 任务 2：实时循环预览

**文件：**
- 修改：`src/petnest/ui/animation_editor_dialog.py`
- 测试：`tests/test_animation_editor_dialog.py`

- [x] **步骤 1：编写失败的测试**

```python
def test_preview_uses_the_selected_action_timeline_and_restarts_after_duration_change(qtbot, tmp_path):
    dialog = AnimationEditorDialog(_package(tmp_path))
    qtbot.addWidget(dialog)
    dialog.total_duration_spin.setValue(100)

    assert dialog.preview_timer.interval() == 50
    assert dialog.preview_frame_index == 0
    dialog._advance_preview()
    assert dialog.preview_frame_index == 1
```

- [x] **步骤 2：运行测试验证失败**

运行：`C:\Python312\python.exe -m pytest tests/test_animation_editor_dialog.py::test_preview_uses_the_selected_action_timeline_and_restarts_after_duration_change -q`

预期：FAIL，提示缺少 `preview_timer`。

- [x] **步骤 3：编写最少实现代码**

```python
self.preview_timer = QTimer(self)
self.preview_timer.timeout.connect(self._advance_preview)

def _restart_preview(self) -> None:
    self.preview_frame_index = 0
    self._render_preview()
    self.preview_timer.start(self._timelines[self._current_action][0])

def _advance_preview(self) -> None:
    self.preview_frame_index = (self.preview_frame_index + 1) % len(self._timelines[self._current_action])
    self._render_preview()
    self.preview_timer.start(self._timelines[self._current_action][self.preview_frame_index])
```

- [x] **步骤 4：运行测试验证通过**

运行：`C:\Python312\python.exe -m pytest tests/test_animation_editor_dialog.py::test_preview_uses_the_selected_action_timeline_and_restarts_after_duration_change -q`

预期：PASS。

### 任务 3：交互收尾与回归验证

**文件：**
- 修改：`src/petnest/ui/animation_editor_dialog.py`
- 测试：`tests/test_animation_editor_dialog.py`

- [x] **步骤 1：编写失败的测试**

```python
def test_clicking_a_thumbnail_pauses_preview_on_that_frame_and_closing_stops_timer(qtbot, tmp_path):
    dialog = AnimationEditorDialog(_package(tmp_path))
    qtbot.addWidget(dialog)
    dialog.frame_list.itemClicked.emit(dialog.frame_list.item(1))

    assert dialog.preview_frame_index == 1
    assert not dialog.preview_timer.isActive()
    dialog.close()
    assert not dialog.preview_timer.isActive()
```

- [x] **步骤 2：运行测试验证失败**

运行：`C:\Python312\python.exe -m pytest tests/test_animation_editor_dialog.py::test_clicking_a_thumbnail_pauses_preview_on_that_frame_and_closing_stops_timer -q`

预期：FAIL，缩略图点击不会暂停预览。

- [x] **步骤 3：编写最少实现代码**

```python
def _select_preview_frame(self, item: QListWidgetItem) -> None:
    self.preview_timer.stop()
    self.preview_frame_index = int(item.data(Qt.ItemDataRole.UserRole))
    self._render_preview()

def closeEvent(self, event: QCloseEvent) -> None:
    self.preview_timer.stop()
    super().closeEvent(event)
```

- [x] **步骤 4：运行测试验证通过**

运行：`C:\Python312\python.exe -m pytest tests/test_animation_editor_dialog.py -q`

预期：PASS。

- [x] **步骤 5：运行完整回归测试并提交**

运行：`C:\Python312\python.exe -m pytest -q`

预期：全部通过；Windows 不支持符号链接时仅保留既有的单项跳过。

```powershell
git add src/petnest/ui/animation_editor_dialog.py tests/test_animation_editor_dialog.py
git commit -m "feat: add live animation frame preview"
```
