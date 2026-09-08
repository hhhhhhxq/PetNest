# Codex 完成状态与待查看计数分离实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 让 PetNest 待查看数量严格等于 Codex 真实顶层未读数量，同时保留顶层完成动画并抑制子代理完成动画。

**架构：** `CodexSessionLogWatcher` 公开既有只读任务分类能力，`CodexLinkCoordinator` 在处理 `Stop` 时用该能力识别子代理。完成动画使用临时 review 状态，未读标志仅由 `ThreadUnread/ThreadRead` 维护；应用层允许无未读的临时 review 气泡短暂显示。

**技术栈：** Python 3.12、PySide6、SQLite 只读索引、pytest、pytest-qt

---

## 文件结构

- 修改 `src/petnest/core/codex_session_log.py`：公开批量任务分类接口并供未读过滤复用。
- 修改 `src/petnest/core/codex_link.py`：分离 Stop 完成动画与真实未读，过滤子代理 Stop。
- 修改 `src/petnest/app.py`：注入任务分类函数并显示临时完成气泡。
- 修改 `tests/test_codex_link.py`：覆盖完成/未读分离、子代理 Stop 清理和 8→1 场景。
- 修改 `tests/test_codex_session_log.py`：覆盖公开分类接口。
- 修改 `tests/test_app_and_platforms.py`：覆盖临时完成气泡到真实未读徽标的生命周期。
- 新增本计划及对应设计规格，与代码合并为一个提交。

### 任务 1：完成与未读状态分离

**文件：**
- 修改：`tests/test_codex_link.py`
- 修改：`src/petnest/core/codex_link.py`

- [x] **步骤 1：编写失败测试**

将前台完成测试改为以下不变量，并增加 8→1 聚合测试：

```python
coordinator.consume(_log("Stop", session="foreground"))
assert coordinator.snapshot.state == "review"
assert coordinator.snapshot.unread_review_count == 0
assert coordinator.snapshot.message == "Codex 任务已完成"

coordinator.finish_review_animation()
assert coordinator.snapshot.state == "idle"
assert coordinator.snapshot.unread_review_count == 0
```

```python
for session in ("child-1", "child-2", "child-3"):
    coordinator.consume(_log("Stop", session=session))
for session in ("top-1", "top-2", "top-3", "top-4", "unread-top"):
    coordinator.consume(_log("Stop", session=session))
coordinator.consume(_log("ThreadUnread", session="unread-top"))
coordinator.finish_review_animation()
assert coordinator.snapshot.unread_review_count == 1
```

另加回归断言，分类为子代理的 `PermissionRequest` 仍进入 waiting、失败事件仍进入 failed；对应 `Stop` 到达后清除已终止的注意状态但不发布 success。分类器抛出异常时允许临时 review，未读数保持 0。

- [x] **步骤 2：运行红灯测试**

```powershell
F:\Desktop Projects\PetNest\.venv\Scripts\python.exe -m pytest tests/test_codex_link.py -q
```

预期：FAIL，现有 `Stop` 立即产生未读并在动画后残留。

- [x] **步骤 3：编写最小实现**

为协调器增加可选分类函数：

```python
SessionClassifier = Callable[[set[str]], ThreadIdClassification]

def __init__(..., classify_sessions: SessionClassifier | None = None):
    self._classify_sessions = classify_sessions
```

处理 `Stop` 时，已确认子代理清理该会话而不创建 review；其他任务的临时 review 不再直接标为未读：

```python
if self._is_child_session(session_id):
    self._discard_session(session_id)
    return True
task = _CodexTask("review", session_id in self._unread_sessions, True)
```

聚合临时 review 时使用完成文案：

```python
message = _completion_message(count) if state == "review" else _snapshot_message(message_state, message_count)
```

- [x] **步骤 4：运行绿灯测试**

运行任务 1 的 pytest 命令。预期：全部 PASS。

### 任务 2：接入任务分类与临时完成气泡

**文件：**
- 修改：`tests/test_codex_session_log.py`
- 修改：`tests/test_app_and_platforms.py`
- 修改：`src/petnest/core/codex_session_log.py`
- 修改：`src/petnest/app.py`

- [x] **步骤 1：编写失败测试**

验证监听器公开分类结果，并更新应用生命周期断言：

```python
classification = watcher.classify_thread_ids({"top", "child"})
assert classification.top_level_ids == frozenset({"top"})
assert classification.child_ids == frozenset({"child"})
```

```python
application._poll_codex_logs()  # Stop
assert application.codex_link.snapshot.unread_review_count == 0
assert application.window.codex_status_text == "Codex 任务已完成"

application._poll_codex_logs()  # ThreadUnread
assert application.codex_link.snapshot.unread_review_count == 1
```

- [x] **步骤 2：运行红灯测试**

```powershell
F:\Desktop Projects\PetNest\.venv\Scripts\python.exe -m pytest tests/test_codex_session_log.py tests/test_app_and_platforms.py -q
```

预期：FAIL，监听器没有公开接口，应用不显示未确认的临时 review 气泡。

- [x] **步骤 3：编写最小实现**

把监听器现有 `_classify_unread_ids` 改为公共 `classify_thread_ids`，内部未读轮询复用该方法。应用构造协调器时安全获取并注入该方法：

```python
classify_sessions = getattr(self.codex_log_watcher, "classify_thread_ids", None)
self.codex_link = CodexLinkCoordinator(
    self.work_activity.handle_codex_event,
    self._handle_codex_snapshot,
    classify_sessions=classify_sessions if callable(classify_sessions) else None,
)
```

应用显示条件加入临时 review：

```python
if (
    (snapshot.state == "review" or snapshot.unread_review_count > 0)
    and self.settings.codex_link_show_review_bubbles
):
    self.window.show_codex_status(snapshot)
```

- [x] **步骤 4：运行绿灯测试**

运行任务 2 的 pytest 命令。预期：全部 PASS。

- [x] **步骤 5：补齐启动恢复红—绿循环**

新增测试，在启动前同时写入一个顶层未读和一个子代理未读；`start()` 后第一次 `poll()` 只返回顶层 `ThreadUnread`。实现时把初始未读加入已满足稳定时间的待分类集合，由第一次轮询先剔除已读项再分类，不能直接重放原始列表。

- [x] **步骤 6：活动任务未读延迟到 Stop**

新增红—绿测试：running 会话收到 `ThreadUnread` 时仍为 working 且待查看为 0；对应 `Stop` 后才进入 review 并计为 1。聚合计数按同时满足 review 与真实 unread 的唯一会话计算。

### 任务 3：回归、真实数据核对与提交

**文件：**
- 修改：`docs/superpowers/specs/2026-09-08-codex-completion-unread-separation-design.md`
- 修改：`docs/superpowers/plans/2026-09-08-codex-completion-unread-separation.md`

- [x] **步骤 1：运行 Codex 联动回归测试**

```powershell
F:\Desktop Projects\PetNest\.venv\Scripts\python.exe -m pytest tests/test_codex_thread_index.py tests/test_codex_session_log.py tests/test_codex_link.py tests/test_codex_status_bubble.py tests/test_app_and_platforms.py -q
```

预期：全部 PASS；仅保留 Windows 无符号链接权限的既有跳过。

- [x] **步骤 2：运行完整测试套件**

```powershell
F:\Desktop Projects\PetNest\.venv\Scripts\python.exe -m pytest -q
```

预期：0 失败；平台不支持的符号链接测试可跳过。

当前主分支完整收集另有三个与本次差异无关的问题：Windows 平台测试导入缺失常量、两个 macOS 启动测试未跳过 Windows，以及一条便签窄窗口时序波动。逐项确认后，使用以下命令验证当前平台可执行的其余完整套件：

```powershell
F:\Desktop Projects\PetNest\.venv\Scripts\python.exe -m pytest --ignore=tests/test_windows_platform.py --ignore=tests/test_macos_source_startup.py --deselect=tests/test_quick_notebook_window.py::test_weekly_reminder_controls_fit_narrow_viewport -q
```

实际结果：1692 passed、7 skipped、1 deselected；便签波动用例单独运行通过。

- [x] **步骤 3：核对真实 Codex 状态**

只读当前 `.codex-global-state.json` 与 `state_*.sqlite`，确认真实顶层未读数量可由 `CodexThreadIndex.classify_thread_ids` 得出，子代理未读不进入目标数量。

- [x] **步骤 4：检查并提交精确文件**

```powershell
git diff --check
git add src/petnest/core/codex_session_log.py src/petnest/core/codex_link.py src/petnest/app.py tests/test_codex_session_log.py tests/test_codex_link.py tests/test_app_and_platforms.py docs/superpowers/specs/2026-09-08-codex-completion-unread-separation-design.md docs/superpowers/plans/2026-09-08-codex-completion-unread-separation.md
git commit -m "fix: 分离 Codex 完成动画与待查看计数"
```

只暂存上述八个文件，不触碰其他未跟踪用户资源。
