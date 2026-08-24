# Codex 旧任务恢复与 working 状态自愈实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 在 Hook 不可用时安全发现今天继续执行的旧 Codex 任务，并确保 working 被临时动作打断后能够恢复和自愈。

**架构：** 新增一个只负责读取 Codex `state_*.sqlite` 任务路径元数据的只读索引组件；现有 JSONL watcher 低频刷新索引候选并继续使用统一的生命周期解析器。状态机保存 working 持续上下文，Codex 聚合层和工作活动仲裁层允许新任务开始时重新确认 working。

**技术栈：** Python 3.12、标准库 `sqlite3`/`pathlib`、pytest、现有 PetEvent/状态机架构。

---

## 文件结构

- 创建 `src/petnest/core/codex_thread_index.py`：只读发现兼容的 Codex 状态数据库并返回受限、已校验的最近任务日志路径。
- 创建 `tests/test_codex_thread_index.py`：覆盖 schema 降级、只读、安全路径、版本选择和数量限制。
- 修改 `src/petnest/core/codex_session_log.py`：低频合并索引候选与日期候选，新发现的旧日志从 EOF 建立游标并执行有界运行中恢复。
- 修改 `tests/test_codex_session_log.py`：覆盖运行期恢复旧任务、完成事件、去重和失败降级。
- 修改 `src/petnest/core/state_machine.py`：保存并清除 working 持续上下文。
- 修改 `tests/test_state_machine.py`：覆盖 click/drag/hover 后恢复 working 及 idle 清理。
- 修改 `src/petnest/core/codex_link.py`：新任务开始时强制重新发布 working，但不重复通知快照观察者。
- 修改 `tests/test_codex_link.py`：覆盖并发 running 重申与重复任务计数。
- 修改 `src/petnest/core/work_activity.py`：允许重复 running 事件穿过有效状态去重层。
- 修改 `tests/test_work_activity.py`：覆盖 working 自愈重发及其他状态仍保持去重。

### 任务 1：只读 Codex 任务索引

**文件：**
- 创建：`src/petnest/core/codex_thread_index.py`
- 创建：`tests/test_codex_thread_index.py`

- [ ] **步骤 1：编写失败测试**

```python
def test_recent_rollout_paths_reads_old_session_from_latest_compatible_database(tmp_path):
    home = tmp_path / ".codex"
    old_log = home / "sessions/2026/08/18/rollout-old.jsonl"
    old_log.parent.mkdir(parents=True)
    old_log.write_text("", encoding="utf-8")
    create_state_db(home / "state_5.sqlite", old_log, updated_at_ms=200)
    assert CodexThreadIndex(home).recent_rollout_paths() == (old_log.resolve(),)

def test_recent_rollout_paths_rejects_external_symlink_and_incompatible_schema(tmp_path):
    home = tmp_path / ".codex"
    outside = tmp_path / "outside.jsonl"
    outside.write_text("", encoding="utf-8")
    create_state_db(home / "state_5.sqlite", outside, updated_at_ms=200)
    assert CodexThreadIndex(home).recent_rollout_paths() == ()
```

- [ ] **步骤 2：运行测试验证失败**

运行：`python -m pytest tests/test_codex_thread_index.py -q`
预期：FAIL，`petnest.core.codex_thread_index` 尚不存在。

- [ ] **步骤 3：实现最少只读索引**

```python
class CodexThreadIndex:
    def recent_rollout_paths(self, *, limit: int = 64) -> tuple[Path, ...]:
        for database in self._candidate_databases():
            paths = self._read_compatible_database(database, limit=limit)
            if paths is not None:
                return tuple(path for path in paths if self._safe_rollout(path))
        return ()
```

实现必须使用只读 URI、`query_only`、短超时、`PRAGMA table_info(threads)` schema 检查、参数化 LIMIT、`state_*.sqlite` 版本/mtime 排序，以及 `sessions` 根目录/普通 JSONL/软链接链校验。WAL 模式只有在既有 `-wal`/`-shm` 完整且安全时才打开；允许 SQLite 使用其管理型共享内存，但不得写业务表、schema、主库事务或 WAL。

- [ ] **步骤 4：运行索引测试验证通过**

运行：`python -m pytest tests/test_codex_thread_index.py -q`
预期：全部 PASS。

### 任务 2：JSONL watcher 合并旧任务候选

**文件：**
- 修改：`src/petnest/core/codex_session_log.py`
- 修改：`tests/test_codex_session_log.py`

- [ ] **步骤 1：编写失败测试**

```python
def test_runtime_index_discovers_resumed_task_in_old_date_directory(tmp_path):
    watcher.start()
    old_log.write_bytes(_meta(session_id) + _event("task_started", turn_id))
    index.set_paths(old_log)
    now[0] += 2.1
    assert watcher.poll()[0].payload["hook_event_name"] == "UserPromptSubmit"

def test_indexed_old_task_completion_is_read_incrementally(tmp_path):
    watcher.start()
    old_log.write_bytes(_meta(session_id) + _event("task_started", turn_id))
    index.set_paths(old_log)
    now[0] += 2.1
    watcher.poll()
    with old_log.open("ab") as stream:
        stream.write(_event("task_complete", turn_id))
    assert [event.payload["hook_event_name"] for event in watcher.poll()] == ["Stop"]
```

- [ ] **步骤 2：运行目标测试验证失败**

运行：`python -m pytest tests/test_codex_session_log.py -q`
预期：新增测试 FAIL，旧日期日志不在候选中。

- [ ] **步骤 3：实现低频索引刷新和有界恢复**

```python
def _refresh_indexed_paths(self, *, force: bool = False) -> None:
    if not force and now - self._last_index_refresh < self._index_refresh_seconds:
        return
    for path in self._thread_index.recent_rollout_paths(limit=self._max_files):
        if path not in self._cursors:
            self._baseline_path(path)
            self._recover_path(path)
```

日期候选和索引候选按 mtime 排序、去重并共同受 `_max_files` 限制；索引异常只返回空候选。新发现日志从 EOF 开始，使用现有启动恢复预算检查最近未结束的 task，不重放历史。增量读取和恢复尾读统一执行 `stat`/打开/`fstat` 文件身份核对；租约只由完整、兼容且带有效 turn 的活动记录续期；游标按 TTL/LRU 与硬上限回收，并保留当前候选及有效租约所需状态。

- [ ] **步骤 4：运行 watcher 测试验证通过**

运行：`python -m pytest tests/test_codex_thread_index.py tests/test_codex_session_log.py -q`
预期：全部 PASS。

### 任务 3：working 持续上下文

**文件：**
- 修改：`src/petnest/core/state_machine.py`
- 修改：`tests/test_state_machine.py`

- [ ] **步骤 1：编写失败测试**

```python
def test_working_context_is_restored_after_click_and_drop():
    machine.handle(PetEvent("agent.working", timestamp=1.0))
    machine.handle(PetEvent("mouse.click", timestamp=2.0))
    assert machine.complete_current_animation().current_action == "working"
    machine.handle(PetEvent("mouse.drag_start", timestamp=3.0))
    machine.handle(PetEvent("mouse.drag_end", timestamp=4.0))
    assert machine.complete_current_animation().current_action == "working"

def test_agent_idle_clears_working_context():
    machine.handle(PetEvent("agent.working", timestamp=1.0))
    machine.handle(PetEvent("agent.idle", timestamp=2.0))
    machine.handle(PetEvent("mouse.click", timestamp=3.0))
    assert machine.complete_current_animation().current_action == "idle"
```

- [ ] **步骤 2：运行状态机测试验证失败**

运行：`python -m pytest tests/test_state_machine.py -q`
预期：FAIL，临时动画结束恢复 idle/hover。

- [ ] **步骤 3：实现 working 上下文**

收到 `agent.working` 时记录解析后的动作；收到 idle/waiting/success/error 时先清除。`_context_action()` 优先返回 working 上下文，再返回 hover/idle。

- [ ] **步骤 4：运行状态机测试验证通过**

运行：`python -m pytest tests/test_state_machine.py -q`
预期：全部 PASS。

### 任务 4：重复 running 自愈事件

**文件：**
- 修改：`src/petnest/core/codex_link.py`
- 修改：`src/petnest/core/work_activity.py`
- 修改：`tests/test_codex_link.py`
- 修改：`tests/test_work_activity.py`

- [ ] **步骤 1：编写失败测试**

```python
def test_second_running_task_reasserts_working_without_duplicate_snapshot_callback():
    coordinator.consume(_hook("UserPromptSubmit", session="one", turn="t1"))
    coordinator.consume(_hook("UserPromptSubmit", session="two", turn="t2"))
    assert [event.event_name for event in published] == ["agent.working", "agent.working"]
    assert coordinator.snapshot.count == 2

def test_repeated_codex_working_reasserts_effective_working():
    coordinator.handle_codex_event(_event("agent.working"))
    coordinator.handle_codex_event(_event("agent.working"))
    assert [event.event_name for event in published] == ["agent.working", "agent.working"]
```

- [ ] **步骤 2：运行聚合与仲裁测试验证失败**

运行：`python -m pytest tests/test_codex_link.py tests/test_work_activity.py -q`
预期：FAIL，第二个 running 被两层去重。

- [ ] **步骤 3：实现受控重发**

为 `_emit_snapshot()` 增加仅由 `UserPromptSubmit` 使用的 `force_pet_event`；快照未变化时只重发宠物事件，不触发快照回调。WorkActivity 仅对重复 `agent.working` 重发，waiting/failed/review/idle 继续按有效状态去重。

- [ ] **步骤 4：运行目标测试验证通过**

运行：`python -m pytest tests/test_codex_link.py tests/test_work_activity.py -q`
预期：全部 PASS。

### 任务 5：集成验证与单提交整理

**文件：**
- 修改：`tests/test_app_and_platforms.py`（仅在现有集成夹具需要补充时）
- 包含：本计划、设计规格及任务 1-4 的全部实现与测试文件

- [ ] **步骤 1：运行 Codex 联动相关测试**

运行：`python -m pytest tests/test_codex_thread_index.py tests/test_codex_session_log.py tests/test_codex_link.py tests/test_work_activity.py tests/test_state_machine.py tests/test_app_and_platforms.py -q`
预期：全部 PASS。

- [ ] **步骤 2：运行完整测试套件**

运行：`python -m pytest -q`
预期：无失败；平台受限测试按既有条件 skip。

- [ ] **步骤 3：检查差异与边界**

运行：`git diff --check`，并确认只包含本计划列出的文件；检查没有读取正文、没有写 Codex 数据库、没有扩大路径根目录。

- [ ] **步骤 4：整理为一个提交**

将现有规格提交与实现合并，最终提交信息：

```text
fix: 修复 Codex 旧任务 working 状态恢复
```

最终历史只保留一个包含规格、计划、代码和测试的提交，不单独保留 Markdown 提交。
