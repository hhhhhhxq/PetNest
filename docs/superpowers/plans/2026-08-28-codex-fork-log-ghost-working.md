# Codex fork 日志假 working 修复计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:executing-plans 按步骤实施。步骤使用复选框（`- [ ]`）语法跟踪。

**目标：** 阻止 fork/历史合并 JSONL 改写文件会话身份或重放旧生命周期，从而消除没有真实任务时残留的 working。

**架构：** `_FileCursor` 保存不可变的文件会话身份；文件名可识别时以文件名为准，否则只接受第一条有效 `session_meta`。poll 首次发现任何候选文件时从安全快照 EOF 建立游标，并调用现有有界尾读恢复判断最新任务是否仍在运行。

**技术栈：** Python 3.12、现有 `CodexSessionLogWatcher`/`CodexLinkCoordinator`、pytest。

---

### 任务 1：固定 rollout 文件会话身份

**文件：**
- 修改：`src/petnest/core/codex_session_log.py`
- 测试：`tests/test_codex_session_log.py`

- [x] **步骤 1：编写失败测试**

构造一个文件：外层 `session_meta`、父会话 `session_meta`、`task_started`、再次出现外层 `session_meta`、相同 turn 的 `task_complete`。逐行解析并交给 `CodexLinkCoordinator`，断言最终没有 running 任务。

- [x] **步骤 2：运行红灯**

运行：`python -m pytest tests/test_codex_session_log.py::test_embedded_session_metadata_cannot_split_lifecycle_identity -q`

预期：FAIL，开始和结束被错误记到不同 session，最终 snapshot 为 running。

- [x] **步骤 3：最少实现**

`_FileCursor` 继续由文件名初始化 `session_id`。解析 `session_meta` 时仅在 `cursor.session_id is None` 时设置首个有效值；已确定身份后忽略后续不同 ID，但格式无效且尚未建立身份时仍进入 incompatible。

- [x] **步骤 4：运行绿灯**

运行同一目标测试，预期 PASS。

### 任务 2：运行时新文件从 EOF 建立基线

**文件：**
- 修改：`src/petnest/core/codex_session_log.py`
- 测试：`tests/test_codex_session_log.py`

- [x] **步骤 1：编写失败测试**

在 watcher 启动后创建今天的 fork 文件，写入已完成历史和一个最新完成事件；断言首次 poll 不重放历史且保持 idle。再创建最新记录为近期 `task_started` 的新文件，断言通过尾读恢复只产生一个 `UserPromptSubmit`。

- [x] **步骤 2：运行红灯**

运行：`python -m pytest tests/test_codex_session_log.py -k "runtime_new_date_file" -q`

预期：FAIL，当前实现从 offset 0 重放历史生命周期。

- [x] **步骤 3：最少实现**

在 poll 处理候选前统一基线所有不在 `_cursors` 的路径：使用 `_CandidateFile.stat.st_size` 作为 offset、记录文件身份和 last_seen，并把这些候选交给 `_recover_recent_running_turns()`。随后增量循环只读取基线之后追加的字节。

- [x] **步骤 4：运行绿灯与回归**

运行：`python -m pytest tests/test_codex_session_log.py tests/test_codex_link.py -q`

预期：全部 PASS。

### 任务 3：完整验证

**文件：**
- 修改：`docs/superpowers/specs/2026-08-24-codex-resumed-session-working-recovery-design.md`
- 包含：本计划及任务 1-2 的代码和测试

- [x] **步骤 1：运行 Codex 相关测试**

运行：`python -m pytest tests/test_codex_thread_index.py tests/test_codex_session_log.py tests/test_codex_link.py tests/test_work_activity.py tests/test_state_machine.py tests/test_app_and_platforms.py -q`

- [x] **步骤 2：运行完整测试、编译与差异检查**

运行：`python -m pytest -q`、`python -m compileall -q src`、`git diff --check`。

- [x] **步骤 3：真实日志只读复验**

使用已确认的 fork 文件结构做只读回放，断言固定文件身份后最终 snapshot 为 idle、remaining tasks 为 0；不得修改 Codex 文件。

- [x] **步骤 4：提交边界**

仅暂存本计划、设计补充、watcher 和对应测试；不包含用户的未跟踪素材，不单独提交 MD。
