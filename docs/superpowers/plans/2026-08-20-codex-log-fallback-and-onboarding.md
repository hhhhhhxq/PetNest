# Codex 日志回退与联动引导实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:executing-plans 逐任务实现；全程 TDD，步骤使用复选框跟踪。

**目标：** 让 Codex 联动开关保存后立即通过 JSONL 回退可用，并把 Hook 降为可选精确增强，设置页清楚展示当前来源、能力和下一步。

**架构：** 新增纯核心增量 JSONL watcher，将 task lifecycle 转为现有 `codex.hook` 语义事件；现有协调器按 session/turn 去重 Hook 与日志来源。应用用 250ms Qt timer poll，设置页只消费不可变运行状态视图。

**技术栈：** Python 3.12、PySide6、JSONL、pytest、pytest-qt

---

### 任务 1：日志回退设置与迁移

**文件：**
- 修改：`src/petnest/models/settings.py`
- 修改：`src/petnest/core/settings_manager.py`
- 测试：`tests/test_settings_manager.py`

- [x] 写失败测试：schema 24 迁移后 `codex_link_log_fallback_enabled=True`，严格拒绝非布尔值，并可 round-trip。
- [x] 运行 `python -m pytest tests/test_settings_manager.py -q`，确认字段缺失导致失败。
- [x] schema 升到 25，增加字段、布尔归一化和 24→25 迁移。
- [x] 重跑设置测试确认通过。

### 任务 2：增量 JSONL watcher

**文件：**
- 创建：`src/petnest/core/codex_session_log.py`
- 创建：`tests/test_codex_session_log.py`

- [x] 写失败测试：启动不重放已有内容；新文件 task_started；追加 task_complete；turn_aborted；半行；损坏行；截断；今天/前一天；多会话。
- [x] 运行 `python -m pytest tests/test_codex_session_log.py -q`，确认模块缺失。
- [x] 实现 `CodexSessionLogWatcher(root, clock, today)`、`start()`、`poll()`、`stop()` 和不可变 `CodexLogSourceStatus`。
- [x] watcher 只输出 allowlist 状态字段组成的 `PetEvent(source="codex-log")`，限制每次文件数、读取字节和单行长度。
- [x] 重跑 watcher 测试确认通过。

### 任务 3：Hook 与日志去重协调

**文件：**
- 修改：`src/petnest/core/codex_link.py`
- 测试：`tests/test_codex_link.py`

- [x] 写失败测试：codex-log task_started/Stop 可驱动；日志 turn 先到、无 turn Hook 后到只保留一个任务；Hook waiting 覆盖日志 running；重复 Stop 不重播。
- [x] 运行聚焦测试确认失败原因是 source 被拒绝或 key 不一致。
- [x] 增加 active turn 映射和 source 去重；Hook 优先但不要求等待 Hook。
- [x] 重跑 `tests/test_codex_link.py tests/test_external_events.py`。

### 任务 4：应用生命周期与来源状态

**文件：**
- 修改：`src/petnest/app.py`
- 测试：`tests/test_app_and_platforms.py`

- [x] 写失败测试：联动+回退开启时 watcher start/timer active；关闭时 stop/clear；日志事件进入主线程协调器；Hook 到达后来源升级；仅 Hook 模式不扫描目录；shutdown 停 timer。
- [x] 运行聚焦测试确认缺少 watcher 装配。
- [x] 注入 watcher factory，新增 250ms timer、`CodexLinkRuntimeStatus` 和设置页实时刷新。
- [x] 重跑应用、外部事件与窗口相关测试。

### 任务 5：设置页开箱即用引导

**文件：**
- 修改：`src/petnest/ui/settings_center_dialog.py`
- 测试：`tests/test_settings_dialog.py`

- [x] 写失败测试：主说明明确保存后可用；状态来源标签；日志回退开关；Hook 卡为可折叠增强；正确桌面路径；无 `/hooks` 文案；诊断/动画测试回调。
- [x] 运行设置页测试确认控件缺失。
- [x] 实现主状态卡、动作/提醒卡、折叠 Hook 卡和诊断卡；保留旧属性名兼容既有测试与调用。
- [x] 重跑设置页测试和小屏导航测试。

### 任务 6：端到端与提交

- [x] 用临时 sessions 目录验证 task_started 在 500ms 内触发 working、task_complete 触发 review。
- [x] 运行 Codex 联动、设置、应用、窗口聚焦测试。
- [x] 运行完整 `python -m pytest -q`。
- [x] 运行 `python -m compileall -q src tests`、`git diff --check`，审查隐私字段与工作区边界。
- [x] 只暂存本功能文件、规格和计划，提交后应用到 `F:\Desktop Projects\PetNest` main；不暂存其他任务改动。
