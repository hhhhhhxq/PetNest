# 普通便签引导、保存提示与归类面板实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 按确认的 A 方案 v2 修复普通便签重复提示、保存浮层、空分类色块，并实现可选择、移除和创建分类的浮动标签盘。

**架构：** 保持 `NotebookPage.tags` 和 JSON schema 不变，用隐藏的 `tag_editor` 继续承载序列化分类文本；新增可见的新分类输入框和动态标签按钮。候选分类从现存普通便签动态汇总，面板只覆盖正文底部，不参与主布局高度。

**技术栈：** Python 3.12、PySide6、pytest-qt、现有 `QuickNotebookStore`。

---

## 文件结构

- 修改：`src/petnest/ui/quick_notebook_window.py`——普通便签空白提示、保存浮层和分类面板 UI/交互。
- 修改：`tests/test_quick_notebook_window.py`——控件结构、分类交互和视觉契约测试。
- 修改：`tests/test_quick_notebook_usability.py`——保存、切页与数据持久化回归测试。

### 任务 1：修正重复提示、保存浮层和空分类摘要

**文件：**
- 修改：`tests/test_quick_notebook_window.py`
- 修改：`src/petnest/ui/quick_notebook_window.py`

- [ ] **步骤 1：编写失败测试**

新增测试，要求正文编辑器自身占位文字为空、中央引导仍存在；空分类摘要隐藏；保存浮层启用 styled background 并保留设计色。

```python
def test_note_uses_one_empty_hint_and_hides_empty_category_summary(qtbot, tmp_path):
    window = QuickNotebookWindow(store=QuickNotebookStore(tmp_path / "book.json"))
    qtbot.addWidget(window)
    window.show()
    assert window.note_editor.placeholderText() == ""
    assert window.note_empty_hint.isVisible()
    assert window.category_summary.isHidden()

def test_save_toast_uses_the_v7_floating_surface(qtbot, tmp_path):
    window = QuickNotebookWindow(store=QuickNotebookStore(tmp_path / "book.json"))
    qtbot.addWidget(window)
    assert window.save_toast.testAttribute(Qt.WidgetAttribute.WA_StyledBackground)
    assert "background: #F1E8E0" in window.styleSheet()
```

- [ ] **步骤 2：运行测试并确认因现有重复占位与空摘要而失败**

运行：`.venv\Scripts\python.exe -m pytest tests\test_quick_notebook_window.py -k "one_empty_hint or v7_floating_surface" -q`

- [ ] **步骤 3：实现最小修复**

将 `note_editor` 占位文字设为空；保留 `note_empty_hint`。为保存浮层设置 `WA_StyledBackground`。把分类摘要改为独立容器，并在没有分类时隐藏整个容器。

- [ ] **步骤 4：运行目标测试确认通过**

运行同上，预期 2 项通过。

### 任务 2：实现分类候选、选择与移除

**文件：**
- 修改：`tests/test_quick_notebook_window.py`
- 修改：`src/petnest/ui/quick_notebook_window.py`

- [ ] **步骤 1：编写失败测试**

覆盖候选来源、最多 8 个、排除当前已选项，以及点击候选/已选标签后的序列化结果。

```python
def test_category_panel_suggests_recent_live_tags_and_toggles_selection(qtbot, tmp_path):
    store = QuickNotebookStore(tmp_path / "book.json")
    # 创建带“项目”“工作”的普通便签和一个回收站便签。
    window = QuickNotebookWindow(store=store)
    qtbot.addWidget(window)
    window.show_page(target.id)
    window.category_toggle.click()
    assert window.category_candidate_names() == ("项目", "工作")
    window.category_choice_buttons["项目"].click()
    assert window.current_categories() == ("项目",)
    window.category_selected_buttons["项目"].click()
    assert window.current_categories() == ()
```

- [ ] **步骤 2：运行测试确认失败**

运行：`.venv\Scripts\python.exe -m pytest tests\test_quick_notebook_window.py -k category_panel_suggests -q`

- [ ] **步骤 3：实现分类面板结构与辅助方法**

在 `QuickNotebookWindow` 中加入：

```python
def current_categories(self) -> tuple[str, ...]: ...
def category_candidate_names(self) -> tuple[str, ...]: ...
def _set_categories(self, names: Sequence[str]) -> None: ...
def _toggle_category(self, name: str) -> None: ...
def _refresh_category_controls(self) -> None: ...
```

候选按普通便签 `updated_at` 倒序汇总、去重，排除回收站、已选项并截取 8 个。已选与候选区域使用可键盘点击的 `QPushButton`，分类摘要仅展示当前已选项。

- [ ] **步骤 4：运行目标测试确认通过**

运行同上，预期通过。

### 任务 3：实现新分类输入、上限和键盘关闭

**文件：**
- 修改：`tests/test_quick_notebook_window.py`
- 修改：`src/petnest/ui/quick_notebook_window.py`

- [ ] **步骤 1：编写失败测试**

```python
def test_category_creation_normalizes_reuses_and_enforces_limits(qtbot, tmp_path):
    window = QuickNotebookWindow(store=QuickNotebookStore(tmp_path / "book.json"))
    qtbot.addWidget(window)
    window.category_toggle.click()
    for name in (" 项目 ", "项目", "工作", "生活", "资料", "重要", "第六个"):
        window.category_new_editor.setText(name)
        qtbot.keyClick(window.category_new_editor, Qt.Key.Key_Return)
    assert window.current_categories() == ("项目", "工作", "生活", "资料", "重要")
    assert window.category_limit_hint.isVisible()
```

另测空值不创建、名称截断为 10 个字符、Escape 关闭面板并恢复焦点。

- [ ] **步骤 2：运行测试确认失败**

运行：`.venv\Scripts\python.exe -m pytest tests\test_quick_notebook_window.py -k "category_creation or category_escape" -q`

- [ ] **步骤 3：实现输入和限制**

新增 `category_new_editor`、`category_add_button`、`category_limit_hint`；Enter 与添加按钮调用同一方法。输入去除首尾空格，空值忽略，重复值只选中一次，最多 5 个。窗口 `keyPressEvent` 优先关闭分类面板。

- [ ] **步骤 4：运行目标测试确认通过**

运行同上，预期通过。

### 任务 4：持久化、布局与回归验证

**文件：**
- 修改：`tests/test_quick_notebook_usability.py`
- 修改：`src/petnest/ui/quick_notebook_window.py`

- [ ] **步骤 1：编写失败测试**

验证通过面板选择的分类在自动保存、切页与重新加载后保持；面板浮在正文底部且不越过页脚。

```python
def test_category_panel_selection_round_trips_without_compressing_note(qtbot, tmp_path):
    store = QuickNotebookStore(tmp_path / "book.json")
    window = QuickNotebookWindow(store=store)
    qtbot.addWidget(window)
    original_height = window.note_editor.height()
    window.category_toggle.click()
    window._set_categories(("项目", "工作"))
    window.flush_current_page()
    assert window.note_editor.height() == original_height
    reloaded = QuickNotebookStore(store.path)
    reloaded.load()
    assert reloaded.page(window.current_page_id).tags == ("项目", "工作")
```

- [ ] **步骤 2：运行测试确认失败**

运行：`.venv\Scripts\python.exe -m pytest tests\test_quick_notebook_usability.py -k category_panel_selection -q`

- [ ] **步骤 3：完善浮层定位与保存联动**

更新 `_layout_note_overlays()`，面板宽度贴合正文、底边位于分类行上方；选择变化写回隐藏 `tag_editor` 并复用现有 500 ms 保存计时器。

- [ ] **步骤 4：运行便签测试与 DPI 测试**

```text
.venv\Scripts\python.exe -m pytest tests\test_quick_notebook_window.py tests\test_quick_notebook_usability.py tests\test_quick_notebook_store.py tests\test_quick_notebook_reminders.py -q
set QT_SCALE_FACTOR=1.25&& .venv\Scripts\python.exe -m pytest tests\test_quick_notebook_window.py -q
set QT_SCALE_FACTOR=1.5&& .venv\Scripts\python.exe -m pytest tests\test_quick_notebook_window.py -q
```

- [ ] **步骤 5：真实窗口视觉复核**

运行 PetNest，逐项截图检查：单一空白提示、暖灰保存浮层、无分类时无绿色空块、A 方案标签盘、5 个上限、翻页后分类不串页。

- [ ] **步骤 6：合并提交**

将实现和测试并入当前便签功能提交，避免为同一功能增加碎片提交；保留设计与计划文档的可追溯性。
