# Codex 状态气泡自适应尺寸实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 让所有 Codex 提示按单行自然宽度展示，仅在文本超过 260 px 时换行，并为 compact 状态提供对称的 16 px 水平留白。

**架构：** 在 `CodexStatusBubble` 内集中封装消息测量与标签尺寸设置，使所有状态调用同一算法。状态分支只控制布局边距和关闭按钮可见性，不再直接决定文本是否换行。

**技术栈：** Python 3.12、PySide6/Qt Widgets、pytest、pytest-qt

---

## 文件结构

- 修改：`src/petnest/ui/codex_status_bubble.py` — 集中计算文本自然宽度、260 px 上限、换行状态及 compact 边距。
- 修改：`tests/test_codex_status_bubble.py` — 覆盖短文本、长文本和状态切换后的尺寸行为。

### 任务 1：统一消息宽度与换行规则

**文件：**
- 修改：`tests/test_codex_status_bubble.py:88-120`
- 修改：`src/petnest/ui/codex_status_bubble.py:29-154`

- [ ] **步骤 1：把现有 compact 测试扩展为 B 方案的边距断言**

```python
margins = bubble.layout().contentsMargins()
assert (margins.left(), margins.right()) == (16, 16)
assert not bubble.message_label.wordWrap()
assert bubble.message_label.width() < 260
```

- [ ] **步骤 2：将完整短消息测试改为期望保持单行**

```python
def test_short_full_message_stays_on_one_line_after_compact_badge(qtbot) -> None:
    bubble = CodexStatusBubble(review_duration_ms=30)
    qtbot.addWidget(bubble)
    anchor = QRect(100, 100, 80, 80)
    bubble.show_snapshot(CodexLinkSnapshot("idle", 0, 1, "Codex 任务已完成，等待查看"), anchor)
    bubble.show_snapshot(CodexLinkSnapshot("waiting", 1, 0, "Codex 正在等待你处理"), anchor)

    margins = bubble.layout().contentsMargins()
    assert not bubble.message_label.wordWrap()
    assert bubble.message_label.width() < 260
    assert (margins.left(), margins.right()) == (11, 7)
```

- [ ] **步骤 3：增加超过 260 px 才换行的测试**

```python
def test_long_full_message_wraps_at_maximum_text_width(qtbot) -> None:
    bubble = CodexStatusBubble(review_duration_ms=30)
    qtbot.addWidget(bubble)
    message = "Codex 任务已完成，等待查看。" * 20
    bubble.show_snapshot(CodexLinkSnapshot("waiting", 1, 0, message), QRect(100, 100, 80, 80))

    assert bubble.message_label.wordWrap()
    assert bubble.message_label.width() == 260
    assert bubble.message_label.height() > bubble.message_label.fontMetrics().height()
```

- [ ] **步骤 4：运行三个尺寸测试并确认因现有状态专用逻辑而失败**

运行：

```bash
python -m pytest \
  tests/test_codex_status_bubble.py::test_compact_badge_hugs_single_line_content \
  tests/test_codex_status_bubble.py::test_short_full_message_stays_on_one_line_after_compact_badge \
  tests/test_codex_status_bubble.py::test_long_full_message_wraps_at_maximum_text_width -q
```

预期：FAIL；compact 边距仍为 11/7，短完整消息仍启用换行，长消息没有稳定占用 260 px。

- [ ] **步骤 5：实现统一的消息尺寸方法**

```python
MAX_MESSAGE_WIDTH = 260
FULL_MARGINS = (11, 7, 7, 7)
COMPACT_MARGINS = (16, 7, 16, 7)

def _set_message(self, message: str) -> None:
    self.message_label.ensurePolished()
    natural_width = max(1, self.message_label.fontMetrics().horizontalAdvance(message))
    width = min(natural_width, MAX_MESSAGE_WIDTH)
    self.message_label.setText(message)
    self.message_label.setFixedWidth(width)
    self.message_label.setWordWrap(natural_width > MAX_MESSAGE_WIDTH)
```

在完整提示分支调用 `_set_message(snapshot.message)` 并设置 `FULL_MARGINS`；在 `_show_unread_badge()` 调用同一方法并设置 `COMPACT_MARGINS`。删除按状态直接调用 `setWordWrap(True/False)` 的逻辑。

- [ ] **步骤 6：运行三个尺寸测试并确认通过**

运行步骤 4 的命令。

预期：`3 passed`。

- [ ] **步骤 7：运行 Codex 气泡与宠物窗口集成测试**

运行：

```bash
python -m pytest tests/test_codex_status_bubble.py tests/test_pet_window.py -q
```

预期：全部通过。

- [ ] **步骤 8：检查目标文件差异**

运行：

```bash
git diff --check -- src/petnest/ui/codex_status_bubble.py tests/test_codex_status_bubble.py
git diff -- src/petnest/ui/codex_status_bubble.py tests/test_codex_status_bubble.py
```

预期：没有空白错误，差异只包含统一尺寸算法、compact 边距及对应测试。

- [ ] **步骤 9：提交实现**

```bash
git add src/petnest/ui/codex_status_bubble.py tests/test_codex_status_bubble.py
git commit -m "fix: 统一 Codex 提示气泡尺寸"
```

- [ ] **步骤 10：重启并确认新进程加载当前源码**

先结束现有 PetNest 开发进程，再运行 `run.bat`。通过进程创建时间晚于 `src/petnest/ui/codex_status_bubble.py` 的修改时间确认重启有效。
