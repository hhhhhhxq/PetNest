# PetNest 轻量便签本层叠纸页实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 严格按照 `notebook-layered-tabs-v7.html` 还原三层纸页、被纸边压住的书签、顶部标题、空白引导与浮动保存状态，同时保持待办和提醒 item 的现有样式与行为。

**架构：** 在现有 `QuickNotebookWindow` 外层增加三个仅负责纸面绘制的 `NotebookPaperLayer`，内容控件继续只有一份并覆盖在当前前景纸页上，避免复制编辑状态。页型切换通过纯函数计算深度，再统一更新纸页几何、书签亮度和 sibling 堆叠顺序；保存状态改为 `QuickNotebookSaveToast` 浮层，复用现有 `_try_persist` 和重试语义。

**技术栈：** Python 3.12、PySide6 Qt Widgets、pytest、pytest-qt

---

## 文件结构

- 修改：`src/petnest/ui/quick_notebook_window.py`——新增纸页层、书签深度、顶部标题布局、普通速记空白提示、归类浮层和保存状态浮层。
- 修改：`tests/test_quick_notebook_window.py`——锁定 v7 几何、颜色、堆叠顺序、空白态、保存状态及待办/提醒 item 不变约束。
- 参考：`.superpowers/brainstorm/notes-20260904/content/notebook-layered-tabs-v7.html`——视觉唯一基准，不在实现任务中修改。
- 参考：`docs/superpowers/specs/2026-09-16-quick-notebook-layered-pages-design.md`——行为边界和逐项视觉验收表。

### 任务 1：建立三层纸页与书签深度模型

**文件：**
- 修改：`tests/test_quick_notebook_window.py`
- 修改：`src/petnest/ui/quick_notebook_window.py`

- [ ] **步骤 1：为深度顺序、纸张偏移和书签贴边编写失败测试**

在测试文件加入：

```python
@pytest.mark.parametrize(
    ("active_type", "expected"),
    [
        ("note", {"note": 0, "todo": 1, "reminder": 2}),
        ("todo", {"todo": 0, "note": 1, "reminder": 2}),
        ("reminder", {"reminder": 0, "note": 1, "todo": 2}),
    ],
)
def test_paper_depths_put_active_type_in_front(active_type, expected) -> None:
    assert paper_depths(active_type) == expected


def test_layered_papers_and_tabs_match_v7_geometry(qtbot, tmp_path) -> None:
    window = QuickNotebookWindow(store=QuickNotebookStore(tmp_path / "book.json"))
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)

    body = window.body_frame.geometry()
    assert window.paper_layers["note"].geometry().topLeft() == body.topLeft()
    assert window.paper_layers["todo"].geometry().topLeft() == body.topLeft() + QPoint(3, 3)
    assert window.paper_layers["reminder"].geometry().topLeft() == body.topLeft() + QPoint(6, 6)
    for tab in window.type_tabs:
        page_type = tab.property("pageType")
        layer = window.paper_layers[page_type]
        assert tab.geometry().right() == layer.geometry().left() + 7
        assert tab.size() == QSize(80, 45)
```

- [ ] **步骤 2：运行测试确认新模型和纸页层缺失**

运行：

```cmd
.venv\Scripts\python.exe -m pytest tests\test_quick_notebook_window.py -k paper_depth -v
.venv\Scripts\python.exe -m pytest tests\test_quick_notebook_window.py -k layered_papers -v
```

预期：第一组因无法导入 `paper_depths` 失败，第二组因 `paper_layers` 不存在失败。

- [ ] **步骤 3：实现深度纯函数和纸页绘制层**

在模块常量区加入：

```python
PAPER_STACK_OFFSETS = (QPoint(0, 0), QPoint(3, 3), QPoint(6, 6))
PAPER_COLORS = ("#FFFDFA", "#FFFBF7", "#FFF8F1")
TAB_WIDTH = 80
TAB_HEIGHT = 45
TAB_TOP = 34
TAB_GAP = 12
TAB_PAPER_OVERLAP = 8


def paper_depths(active_type: PageType) -> dict[PageType, int]:
    order = [active_type, *(value for value in PAGE_TYPES if value != active_type)]
    return {page_type: depth for depth, page_type in enumerate(order)}
```

从 store 模块导入 `PAGE_TYPES`，新增：

```python
class NotebookPaperLayer(QFrame):
    def __init__(self, page_type: PageType, parent: QWidget) -> None:
        super().__init__(parent)
        self.page_type = page_type
        self.setObjectName("quickNotebookPaperLayer")
        self.setProperty("depth", 2)
        self._shadow = QGraphicsDropShadowEffect(self)
        self.setGraphicsEffect(self._shadow)

    def set_depth(self, depth: int) -> None:
        self.setProperty("depth", depth)
        self._shadow.setBlurRadius((24, 14, 8)[depth])
        self._shadow.setOffset(0, (7, 4, 2)[depth])
        self._shadow.setColor(QColor(68, 47, 36, (48, 30, 20)[depth]))
        self.style().unpolish(self)
        self.style().polish(self)
```

在 `QuickNotebookWindow.__init__` 创建三个 sibling 纸页层，并把现有 `body_frame` 攑为透明内容承载层：

```python
self.paper_layers = {
    page_type: NotebookPaperLayer(page_type, self)
    for page_type in PAGE_TYPES
}
self.body_frame.setObjectName("quickNotebookContentHost")
```

- [ ] **步骤 4：增强 `NotebookTypeTab` 的深度绘制**

将页签标签改为“速记 / 待办 / 提醒”，固定 `80 × 45px`，增加 `set_depth()`：

```python
def set_depth(self, depth: int) -> None:
    self._depth = depth
    self._active = depth == 0
    self.setChecked(self._active)
    self.update()
```

`paintEvent()` 使用：

```python
color = QColor(self._color)
if self._depth == 1:
    color = color.darker(122)
elif self._depth == 2:
    color = color.darker(147)
painter.fillPath(path, color)
```

删除当前页签右侧白色竖条；纸面覆盖页签伸入区域后已经能表达选中状态。

- [ ] **步骤 5：在 `_layout_floating_children()` 应用几何和堆叠顺序**

按以下算法布局：

```python
depths = paper_depths(self._active_type)
body_rect = QRect(body_x, 0, self._body_width, body_height)
for page_type, layer in self.paper_layers.items():
    depth = depths[page_type]
    offset = PAPER_STACK_OFFSETS[depth]
    layer.setGeometry(body_rect.translated(offset))
    layer.set_depth(depth)

for index, tab in enumerate(self.type_tabs):
    page_type = tab.property("pageType")
    depth = depths[page_type]
    layer = self.paper_layers[page_type]
    tab.set_depth(depth)
    tab.move(
        layer.geometry().left() - tab.width() + TAB_PAPER_OVERLAP,
        layer.geometry().top() + TAB_TOP + index * (TAB_HEIGHT + TAB_GAP),
    )

for depth in (2, 1, 0):
    page_type = next(value for value, value_depth in depths.items() if value_depth == depth)
    tab = next(value for value in self.type_tabs if value.property("pageType") == page_type)
    tab.raise_()
    self.paper_layers[page_type].raise_()
self.body_frame.setGeometry(body_rect)
self.body_frame.raise_()
```

窗口 `sizeHint()` 的宽高分别为现有值增加 `6px`，保证底层纸页右边和底边不被裁切；窄屏计算同步预留 `6px`。

- [ ] **步骤 6：运行纸页和既有页签测试**

运行：

```cmd
.venv\Scripts\python.exe -m pytest tests\test_quick_notebook_window.py -k tab -v
.venv\Scripts\python.exe -m pytest tests\test_quick_notebook_window.py -k paper -v
```

预期：纸页深度、贴边、颜色和点击切换测试通过；旧的 `88 × 43` 和“便签”断言更新为 `80 × 45` 和“速记”。

- [ ] **步骤 7：提交纸页层**

```cmd
git add src\petnest\ui\quick_notebook_window.py tests\test_quick_notebook_window.py
git commit -m feat:实现便签本层叠纸页与书签
```

### 任务 2：还原顶部标题、正文和归类布局

**文件：**
- 修改：`tests/test_quick_notebook_window.py`
- 修改：`src/petnest/ui/quick_notebook_window.py`

- [ ] **步骤 1：锁定标题单行、正文无重复标签和底部单行导航**

加入：

```python
def test_v7_header_and_note_body_use_one_continuous_paper(qtbot, tmp_path) -> None:
    window = QuickNotebookWindow(store=QuickNotebookStore(tmp_path / "book.json"))
    qtbot.addWidget(window)
    window.show()

    assert window.title_editor.parent() is window.content_frame
    assert window.title_editor.geometry().top() == window.delete_button.geometry().top()
    assert window.title_editor.geometry().top() == window.close_button.geometry().top()
    assert window.title_label.isHidden()
    assert window.body_label.isHidden()
    assert window.tag_label.isHidden()
    assert window.page_hint.isHidden()
    assert window.note_editor.placeholderText().startswith("开始写点什么吧")
    assert window.footer.layout().count() == 1
    assert window.new_button.size() == QSize(35, 35)
    assert window.new_button.text() == "+"
```

- [ ] **步骤 2：运行测试确认当前表单式布局失败**

运行：

```cmd
.venv\Scripts\python.exe -m pytest tests\test_quick_notebook_window.py -k v7_header -v
```

预期：字段标签仍显示、标题编辑器位于第二行、footer 仍有两行，因此测试失败。

- [ ] **步骤 3：把标题编辑器移入顶部操作行**

标题行直接包含：

```python
header.addWidget(self.title_editor, 1)
header.addWidget(self.delete_button)
header.addWidget(self.close_button)
content_layout.addLayout(header)
```

不再把 `title_label`、独立 `title_editor` 和 `page_hint` 加入内容布局；保留对象但隐藏，以减少测试和外部引用迁移风险。标题编辑器高度改为 `31px`，QSS 改为透明无边框，仅 focus 时使用 `#FFF3EC` 圆角背景。

- [ ] **步骤 4：让普通速记正文成为主要区域**

普通页布局顺序固定为：`note_editor(1)`、紧凑归类行。隐藏 `body_label` 与 `tag_label`；正文 QSS 使用透明背景、无边框、`13px` 字号和 `8px 4px 40px` 等效内边距，不绘制标题分割线或装饰短线。

归类行增加 `category_chips_label`：

```python
self.category_toggle.setText("归类")
self.category_toggle.setAccessibleName("归类当前速记")
self.category_chips_label = QLabel(self.note_page)
self.category_chips_label.setObjectName("quickNotebookCategoryChips")
category_heading.addWidget(self.category_toggle)
category_heading.addWidget(self.category_chips_label)
category_heading.addStretch(1)
```

`_update_category_summary()` 把现有 tags 用 `"  ".join(tags)` 显示在 chips label 中。现有输入框、最多五项校验和分类筛选数据逻辑保持不变；`category_panel` 改为浮动 QFrame，在归类行上方展开，不参与 note layout 高度计算。

- [ ] **步骤 5：合并 footer 为 v7 单行结构**

footer 只保留一个 `QHBoxLayout`：目录、stretch、上一页、页码、下一页、圆形新建。删除原 footer 第二行；`save_hint` 与 `retry_button` 在任务 3 中迁移到浮层，暂时设为隐藏。

新建按钮：

```python
self.new_button.setText("+")
self.new_button.setFixedSize(35, 35)
self.new_button.setToolTip("新建便签")
self.new_button.setAccessibleName("新建便签")
```

目录按钮统一显示“目录”，页型范围继续通过目录页标题表达。

- [ ] **步骤 6：运行普通页、分类、目录、翻页和窄屏测试**

运行：

```cmd
.venv\Scripts\python.exe -m pytest tests\test_quick_notebook_window.py -k note -v
.venv\Scripts\python.exe -m pytest tests\test_quick_notebook_window.py -k category -v
.venv\Scripts\python.exe -m pytest tests\test_quick_notebook_window.py -k navigation -v
```

预期：标题自动命名、分类校验、目录筛选、翻页和 360px 窄屏测试全部通过。

- [ ] **步骤 7：提交纸面内容布局**

```cmd
git add src\petnest\ui\quick_notebook_window.py tests\test_quick_notebook_window.py
git commit -m feat:还原便签本顶部标题与紧凑正文
```

### 任务 3：实现空白引导和浮动保存状态

**文件：**
- 修改：`tests/test_quick_notebook_window.py`
- 修改：`src/petnest/ui/quick_notebook_window.py`

- [ ] **步骤 1：为空白提示和保存浮层编写失败测试**

加入：

```python
def test_empty_note_hint_is_visual_only_and_hides_after_input(qtbot, tmp_path) -> None:
    store = QuickNotebookStore(tmp_path / "book.json")
    window = QuickNotebookWindow(store=store)
    qtbot.addWidget(window)
    window.show()

    assert window.title_editor.placeholderText() == "无标题速记"
    assert window.note_empty_hint.isVisible()
    assert "第一行会自动成为标题" in window.note_empty_hint.text()
    window.note_editor.setPlainText("新的灵感")
    assert window.note_empty_hint.isHidden()
    assert window.note_editor.toPlainText() == "新的灵感"


def test_success_toast_is_transient_and_error_toast_persists(qtbot, tmp_path) -> None:
    window = QuickNotebookWindow(store=QuickNotebookStore(tmp_path / "book.json"))
    qtbot.addWidget(window)
    window.show()

    window._set_save_status("已保存到本机")
    assert window.save_toast.isVisible()
    assert window.save_status_timer.interval() == 2000
    window.save_status_timer.timeout.emit()
    assert window.save_toast.isHidden()

    window._set_save_status("保存失败", error=True)
    assert window.save_toast.isVisible()
    assert window.retry_button.isVisible()
    assert not window.save_status_timer.isActive()
    assert window.save_toast.property("error") is True
```

- [ ] **步骤 2：运行测试确认空白 overlay 和 toast 尚不存在**

运行：

```cmd
.venv\Scripts\python.exe -m pytest tests\test_quick_notebook_window.py -k empty_note_hint -v
.venv\Scripts\python.exe -m pytest tests\test_quick_notebook_window.py -k success_toast -v
```

预期：分别因 `note_empty_hint`、`save_toast` 和 `save_status_timer` 缺失失败。

- [ ] **步骤 3：实现居中的空白提示**

创建 `note_empty_hint` 为 `note_editor.viewport()` 的子 QLabel：

```python
self.note_empty_hint = QLabel(
    "开始写点什么吧\n第一行会自动成为标题\n也可以点击上方标题自定义",
    self.note_editor.viewport(),
)
self.note_empty_hint.setObjectName("quickNotebookEmptyHint")
self.note_empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
self.note_empty_hint.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
```

增加 `_sync_note_empty_hint()`，仅在活动页是 note 且正文为空时显示；`show_page()`、`_show_empty_type()`、`_on_page_content_changed()` 和 resize 后调用。提示只绘制在 overlay，不写入 `NotebookPage.body`。

- [ ] **步骤 4：实现浮动保存状态**

新增 `QuickNotebookSaveToast(QFrame)`，内部放置现有 `save_hint` 和 `retry_button`，父级为 `page_stack`。增加：

```python
self.save_status_timer = QTimer(self)
self.save_status_timer.setSingleShot(True)
self.save_status_timer.setInterval(2000)
self.save_status_timer.timeout.connect(self.save_toast.hide)
```

重写 `_set_save_status()`：

```python
def _set_save_status(self, text: str, *, error: bool = False) -> None:
    self.save_hint.setText(text)
    self.save_hint.setToolTip(text)
    self.save_toast.setProperty("error", error)
    self.save_toast.style().unpolish(self.save_toast)
    self.save_toast.style().polish(self.save_toast)
    self.save_status_timer.stop()
    if error:
        self.save_toast.show()
        self.retry_button.show()
    elif text == "已保存到本机":
        self.retry_button.hide()
        self.save_toast.show()
        self.save_status_timer.start()
    else:
        self.save_toast.hide()
```

在 `_layout_floating_children()` 中把 toast 放在 `page_stack` 右下角 `10px` 内边距处并 `raise_()`。

- [ ] **步骤 5：区分实际内容保存与选择状态保存**

为 `_try_persist` 增加 `announce_success: bool = False`；只有 `flush_current_page()` 与 `persist_reminder_change()` 传 `announce_success=True`。创建页、删除页、清空、恢复和仅保存选择状态成功时不显示 toast。失败分支仍统一显示常驻错误。

- [ ] **步骤 6：运行保存失败、关闭保护、IME 和提醒并发测试**

运行：

```cmd
.venv\Scripts\python.exe -m pytest tests\test_quick_notebook_window.py -k save -v
.venv\Scripts\python.exe -m pytest tests\test_quick_notebook_window.py -k ime -v
.venv\Scripts\python.exe -m pytest tests\test_app_and_platforms.py -k notebook -v
```

预期：成功 toast、失败重试、关闭时保存保护、输入法预编辑、提醒状态合并测试全部通过。

- [ ] **步骤 7：提交状态反馈**

```cmd
git add src\petnest\ui\quick_notebook_window.py tests\test_quick_notebook_window.py
git commit -m feat:增加便签空白引导与浮动保存状态
```

### 任务 4：冻结待办提醒样式并完成视觉验收

**文件：**
- 修改：`tests/test_quick_notebook_window.py`
- 不修改：`TodoCheckBox`、`_TodoRow`、`TodoListEditor`、`ReminderSwitch`、`_ReminderRow`、`ReminderListEditor` 的内部绘制与 QSS 规则

- [ ] **步骤 1：加入 item 样式指纹回归测试**

把测试文件的 QtCore 导入补为 `from PySide6.QtCore import QMargins, QPoint, QRect, QSize, Qt`，然后加入：

```python
def test_layered_shell_preserves_todo_and_reminder_item_visual_contract(qtbot, tmp_path) -> None:
    window = QuickNotebookWindow(store=QuickNotebookStore(tmp_path / "book.json"))
    qtbot.addWidget(window)
    window.todo_editor.set_items((TodoItem("t1", "待办事项"),))
    window.reminder_editor.set_items(
        (ReminderItem("r1", "提醒事项", due_at="2026-09-16T18:00:00+08:00"),)
    )
    todo_row = window.todo_editor._rows[0]
    reminder_row = window.reminder_editor._rows[0]

    assert todo_row.height() == 48
    assert todo_row.layout().contentsMargins() == QMargins(8, 6, 8, 6)
    assert todo_row.check.size() == QSize(32, 32)
    assert reminder_row.layout().contentsMargins() == QMargins(10, 9, 10, 9)
    assert reminder_row.date_box.size() == QSize(52, 58)
    assert reminder_row.enabled.size() == QSize(31, 18)
    assert "QFrame#quickNotebookTodoRow" in window.styleSheet()
    assert "QFrame#quickNotebookReminderRow" in window.styleSheet()
```

- [ ] **步骤 2：运行完整便签相关测试**

```cmd
.venv\Scripts\python.exe -m pytest tests\test_quick_notebook_window.py tests\test_quick_notebook_store.py tests\test_quick_notebook_reminder.py tests\test_quick_notebook_reminders.py tests\test_interaction_item_toolbox.py tests\test_app_and_platforms.py -k notebook -q
```

预期：所有便签相关测试通过，item 指纹无变化。

- [ ] **步骤 3：进行 100%、125%、150% 真实 Qt 视觉复核**

每次关闭前一实例后分别运行：

```cmd
set QT_SCALE_FACTOR=1.0&& set PYTHONPATH=F:\Desktop Projects\PetNest\src&& .venv\Scripts\python.exe -m petnest
set QT_SCALE_FACTOR=1.25&& set PYTHONPATH=F:\Desktop Projects\PetNest\src&& .venv\Scripts\python.exe -m petnest
set QT_SCALE_FACTOR=1.5&& set PYTHONPATH=F:\Desktop Projects\PetNest\src&& .venv\Scripts\python.exe -m petnest
```

每档缩放都与 v7 原型逐项复核规格第 11 节八项内容，并分别检查速记有内容、速记空白、待办单 item、待办多 item 滚动、提醒单 item、提醒展开时间、保存成功、保存失败八种状态。

- [ ] **步骤 4：运行完整验证**

```cmd
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m compileall -q src tests
git diff --check
```

预期：pytest 无失败；compileall 退出码为 0；`git diff --check` 无输出。

- [ ] **步骤 5：代码审查与提交整理**

对照规格和 v7 原型审查完整 diff，Critical 与 Important 问题修复后，先保留备份分支，再把任务 1–4 的四个临时提交软合并为一个功能提交：

```cmd
git branch codex/quick-notebook-layered-pre-squash
git reset --soft HEAD~4
git commit -m feat:严格还原便签本层叠纸页交互
```

最终提交标题：

```text
feat:严格还原便签本层叠纸页交互
```

## 计划自检

- 规格覆盖：任务 1 覆盖三层纸、贴边遮挡、深度颜色和页型切换；任务 2 覆盖顶部标题、正文、归类和 footer；任务 3 覆盖空白引导及保存成功/失败；任务 4 覆盖 item 冻结、DPI、视觉逐项复核和全量验证。
- 占位符扫描：所有新增类型、字段、函数、几何值、颜色、测试命令和预期结果均已定义。
- 类型一致性：全文统一使用 `NotebookPaperLayer`、`paper_depths`、`paper_layers`、`QuickNotebookSaveToast`、`save_toast`、`save_status_timer`、`note_empty_hint` 和 `announce_success`。
- 范围一致性：不修改待办和提醒 item 内部类与 QSS；所有变更集中在 `QuickNotebookWindow` 外壳及新增辅助组件。
