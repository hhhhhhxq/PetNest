# Codex 子代理未读过滤实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 让 PetNest 只把 Codex 顶层任务计为待查看，忽略直接及嵌套子代理任务。

**架构：** 在现有只读 `CodexThreadIndex` 中增加批量父子关系分类，把任务分为顶层、子代理和未知三类。`CodexSessionLogWatcher` 仅为确认的顶层任务发出 `ThreadUnread`，子代理静默丢弃，未知任务保留并在后续轮询重试。

**技术栈：** Python 3.12、sqlite3 只读连接、pytest

---

## 文件结构

- 修改 `src/petnest/core/codex_thread_index.py`：提供有界、只读的任务 ID 分类接口。
- 修改 `src/petnest/core/codex_session_log.py`：在生成未读事件前调用分类接口。
- 修改 `tests/test_codex_thread_index.py`：验证顶层、直接子代理、嵌套子代理及不可用数据库的分类。
- 修改 `tests/test_codex_session_log.py`：验证子代理不产生提示、顶层任务仍产生和清除提示、未知任务可重试。
- 新增本计划与对应设计文档：记录行为和验证边界，与代码合并为一个提交。

### 任务 1：任务关系批量分类

**文件：**
- 修改：`tests/test_codex_thread_index.py`
- 修改：`src/petnest/core/codex_thread_index.py`

- [x] **步骤 1：编写失败的分类测试**

扩展测试数据库夹具，使其可创建 `thread_spawn_edges`，并添加以下核心断言：

```python
classification = CodexThreadIndex(tmp_path).classify_thread_ids(
    {root_id, child_id, nested_child_id, unknown_id}
)

assert classification.top_level_ids == frozenset({root_id})
assert classification.child_ids == frozenset({child_id, nested_child_id})
assert classification.unknown_ids == frozenset({unknown_id})
```

另加数据库缺少 `thread_spawn_edges` 时全部返回未知且 `last_status == "incompatible"` 的测试。

- [x] **步骤 2：运行测试验证失败**

运行：

```powershell
F:\Desktop Projects\PetNest\.venv\Scripts\python.exe -m pytest tests/test_codex_thread_index.py -q
```

预期：FAIL，原因是 `CodexThreadIndex` 尚无 `classify_thread_ids`。

- [x] **步骤 3：实现最小分类接口**

加入明确的不可变返回类型：

```python
@dataclass(frozen=True)
class ThreadIdClassification:
    top_level_ids: frozenset[str]
    child_ids: frozenset[str]
    unknown_ids: frozenset[str]
```

公开方法对输入去重并限制为 4096 个有效字符串；逐个检查候选数据库，调用只读查询。数据库查询先验证 `threads.id` 与 `thread_spawn_edges.child_thread_id`，再用不超过 500 个参数的分块 `IN` 查询得到已索引 ID 和子代理 ID：

```python
present_ids = _select_ids(connection, "threads", "id", candidate_ids)
child_ids = _select_ids(connection, "thread_spawn_edges", "child_thread_id", candidate_ids)
return ThreadIdClassification(
    top_level_ids=frozenset(present_ids - child_ids),
    child_ids=frozenset(child_ids),
    unknown_ids=frozenset(candidate_ids - present_ids),
)
```

任何只读预检、SQLite、路径或 schema 失败都返回全部未知，并设置既有 `last_status`。

- [x] **步骤 4：运行索引测试验证通过**

运行同上。预期：全部 PASS，输出无警告。

### 任务 2：未读事件过滤与重试

**文件：**
- 修改：`tests/test_codex_session_log.py`
- 修改：`src/petnest/core/codex_session_log.py`

- [x] **步骤 1：编写失败的监听测试**

扩展 `_FakeThreadIndex`，允许按调用返回分类结果；添加三组行为测试：

```python
assert watcher.poll() == ()  # 25 个子代理稳定后仍无 ThreadUnread
```

```python
assert [event.payload for event in watcher.poll()] == [
    {"hook_event_name": "ThreadUnread", "session_id": root_id}
]
```

```python
assert watcher.poll() == ()  # 第一次分类未知
index.top_level_ids = {root_id}
assert watcher.poll()[0].payload["session_id"] == root_id  # 后续轮询重试成功
```

保留现有 `ThreadRead` 断言，确认只有已经发出未读事件的顶层任务才产生清除事件。

- [x] **步骤 2：运行监听测试验证失败**

运行：

```powershell
F:\Desktop Projects\PetNest\.venv\Scripts\python.exe -m pytest tests/test_codex_session_log.py -q
```

预期：FAIL，现有实现会为每个稳定子代理 ID 发出 `ThreadUnread`。

- [x] **步骤 3：实现最小过滤逻辑**

达到稳定时间后一次性分类所有候选 ID：

```python
classification = self._classify_unread_ids(stable_ids)
for session_id in classification.child_ids:
    self._pending_unread_since.pop(session_id, None)
for session_id in classification.top_level_ids:
    self._pending_unread_since.pop(session_id, None)
    self._confirmed_unread_ids.add(session_id)
    events.append(self._thread_unread_event(session_id))
# unknown_ids 保留在 _pending_unread_since，供下次 poll 重试
```

索引不存在、抛出异常或返回不可用状态时，把全部候选 ID 视为未知，不生成气泡。现有基线、稳定时间、排序和已确认任务的 `ThreadRead` 行为保持不变。

- [x] **步骤 4：运行监听测试验证通过**

运行同上。预期：全部 PASS，输出无警告。

### 任务 3：回归验证与单提交

**文件：**
- 修改：`docs/superpowers/specs/2026-08-31-codex-subagent-unread-filter-design.md`
- 修改：`docs/superpowers/plans/2026-08-31-codex-subagent-unread-filter.md`

- [x] **步骤 1：运行相关回归测试**

```powershell
F:\Desktop Projects\PetNest\.venv\Scripts\python.exe -m pytest tests/test_codex_thread_index.py tests/test_codex_session_log.py tests/test_codex_link.py -q
```

预期：全部 PASS，输出无错误或警告。

- [x] **步骤 2：运行完整测试套件**

```powershell
F:\Desktop Projects\PetNest\.venv\Scripts\python.exe -m pytest -q
```

预期：全部 PASS；若存在与本次修改无关的既有失败，单独记录并用改动前基线复核，不修改无关文件。

- [x] **步骤 3：检查差异与工作树边界**

```powershell
git diff --check
git diff -- src/petnest/core/codex_thread_index.py src/petnest/core/codex_session_log.py tests/test_codex_thread_index.py tests/test_codex_session_log.py docs/superpowers/specs/2026-08-31-codex-subagent-unread-filter-design.md docs/superpowers/plans/2026-08-31-codex-subagent-unread-filter.md
```

预期：无空白错误，差异只包含本计划列出的六个文件。

- [x] **步骤 4：合并为一个提交**

只暂存上述六个文件，保留工作树内所有用户文件和无关提交：

```powershell
git add src/petnest/core/codex_thread_index.py src/petnest/core/codex_session_log.py tests/test_codex_thread_index.py tests/test_codex_session_log.py docs/superpowers/specs/2026-08-31-codex-subagent-unread-filter-design.md docs/superpowers/plans/2026-08-31-codex-subagent-unread-filter.md
git commit -m "fix: 过滤 Codex 子代理待查看事件"
```
