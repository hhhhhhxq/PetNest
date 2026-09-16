# 便签正文密度、底部描边与删除提示修正实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 收紧普通便签正文留白、补齐前景页底部描边、让空白页无确认直接删除，并修复提醒“开启”按钮裁字。

**架构：** 仅调整 `QuickNotebookWindow` 的 note 页布局和页脚样式，并在现有删除入口前复用 `flush_current_page()` 与 `NotebookPage.is_empty`。提醒按钮只调整固定尺寸，不改提醒状态逻辑。

**技术栈：** Python 3.12、PySide6、pytest-qt。

---

### 任务 1：正文密度与底部描边

**文件：**
- 修改：`tests/test_quick_notebook_window.py`
- 修改：`src/petnest/ui/quick_notebook_window.py`

- [ ] 编写失败测试：断言 note 页布局四周边距为 0；正文左边界与标题左边界差值不超过 6 px；页脚样式包含左右和底部纸张描边。
- [ ] 运行目标测试确认失败。
- [ ] 将 `note_layout.setContentsMargins(10, 10, 10, 10)` 改为 0；内容承载层四周内收 1 px，露出真实纸张边框，页脚只保留顶部分隔线和底部圆角。
- [ ] 运行目标测试确认通过。

### 任务 2：空白页直接删除

**文件：**
- 修改：`tests/test_quick_notebook_window.py`
- 修改：`src/petnest/ui/quick_notebook_window.py`

- [ ] 编写失败测试：点击空白页删除按钮后确认弹窗保持隐藏、页面直接消失、回收站数量不变；非空页仍显示“进入回收站”确认。
- [ ] 运行目标测试确认失败。
- [ ] 在 `_prompt_delete_current()` 中先刷新当前页；空白时直接调用 `confirm_delete_page()`，非空时才配置并显示确认浮层。
- [ ] 运行目标测试确认通过。

### 任务 3：提醒开启按钮尺寸

**文件：**
- 修改：`tests/test_quick_notebook_window.py`
- 修改：`src/petnest/ui/quick_notebook_window.py`

- [ ] 编写失败测试：断言 `confirm_time_button` 尺寸至少为 52×28，并在 100%、125%、150% DPI 下包含完整“开启”文字。
- [ ] 运行目标测试确认失败。
- [ ] 将按钮固定尺寸从 40×26 调整为 52×28，保留现有样式、信号和位置。
- [ ] 运行目标测试确认通过。

### 任务 4：回归、视觉复核与合并提交

**文件：**
- 测试：`tests/test_quick_notebook_window.py`
- 测试：`tests/test_quick_notebook_usability.py`

- [ ] 运行便签窗口、存储、提醒测试。
- [ ] 分别用 `QT_SCALE_FACTOR=1.25` 和 `1.5` 运行窗口测试。
- [ ] 启动真实 PetNest，截图检查正文对齐、底部轮廓、空白删除和提醒按钮。
- [ ] 将设计、计划、实现和测试并入现有便签功能提交，不增加碎片提交。

### 任务 5：强化当前书签并悬浮归类控件

**文件：**
- 修改：`tests/test_quick_notebook_window.py`
- 修改：`src/petnest/ui/quick_notebook_window.py`

- [ ] 编写失败测试：当前书签左边界比两个非当前书签至少多伸出 7 px；非当前深度颜色明显降低；归类容器的父级是正文视口且不再占用 `note_layout`；正文底部保留至少 42 px 安全区。
- [ ] 运行目标测试确认失败。
- [ ] 调整 `NotebookTypeTab` 深度绘制和 `_layout_floating_children()` 的书签宽度/位置，使当前页左伸 7 px并强化明暗差。
- [ ] 将归类标题行改为 `note_editor.viewport()` 的悬浮子控件，更新 `_layout_note_overlays()` 使其固定在正文左下角，分类面板锚定其上方。
- [ ] 将正文底部内边距保持在 42 px 以上，确保滚动文字不被覆盖。
- [ ] 运行窗口测试与真实截图复核当前书签、悬浮归类和底部真实纸张边框。

### 任务 6：完成真实浮层、标签省略与前景轮廓

**文件：**
- 修改：`tests/test_quick_notebook_window.py`
- 修改：`src/petnest/ui/quick_notebook_window.py`

- [ ] 编写失败测试：文档根框架底部留白至少 44 px，末行滚动后位于浮层上方；悬浮摘要最多两个标签加 `+N`；长标签按钮最大宽度并有完整 tooltip；前景轮廓与纸张同尺寸且不接收鼠标。
- [ ] 运行目标测试确认失败。
- [ ] 将归类条和面板重新挂到正文 viewport，使用文档 root frame bottom margin 提供真实滚动余量。
- [ ] 悬浮摘要压缩为两个 72 px 以内标签和 `+N`；分类面板改为两列、按钮最大 120 px并省略长文字，输入框最小宽度为 0。
- [ ] 新增透明 `NotebookOutline` 顶层控件，用 `QPainter` 绘制完整 1 px 圆角轮廓并保持鼠标穿透。
- [ ] 运行极窄、低高度、长标签、末行滚动和三档 DPI 测试，并进行真实截图复核。
