# 次日上班边界清理实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 让昨日下班状态在次日班次开始时清除，而不是保留到后一天零点。

**架构：** 在倒计时控制器中集中计算状态所属日期的次日清理边界。刷新时先清理已经越过边界的历史状态，再复用现有固定或弹性排班刷新流程。

**技术栈：** Python 3.12、PySide6、pytest、pytest-qt

---

### 任务 1：锁定跨日边界行为

**文件：**
- 修改：`tests/test_work_countdown.py`

- [x] **步骤 1：编写固定排班边界失败测试**

新增测试，用昨日 `overtime` 状态分别在次日上班前一秒和上班整点刷新；前者保留，后者清除并显示当天倒计时。

- [x] **步骤 2：运行固定排班测试验证失败**

运行：`python -m pytest tests/test_work_countdown.py -k next_day_work_start -q`

预期：整点仍显示昨日加班时间，断言失败。

- [x] **步骤 3：编写弹性排班与休息日边界失败测试**

新增测试，验证弹性模式在允许打卡开始时间清除，以及休息日不会把清理时间顺延到下一个工作日。

- [x] **步骤 4：运行新增测试验证失败**

运行：`python -m pytest tests/test_work_countdown.py -k next_day -q`

预期：新增边界测试因昨日状态未清除而失败。

### 任务 2：实现最小清理逻辑

**文件：**
- 修改：`src/petnest/ui/work_countdown.py`
- 测试：`tests/test_work_countdown.py`

- [x] **步骤 1：增加次日清理边界计算**

根据排班模式选择 `work_start_time` 或 `clock_in_start_time`，计算旧班次预计结束之后第一次到达的班次开始时间。

- [x] **步骤 2：在刷新入口应用边界**

当历史状态日期早于今天且当前时间达到边界时清除状态；边界前继续走现有跨夜逻辑。弹性打卡记录独立使用同一边界判断并通过回调持久化清除，即使没有历史下班状态，也不能在边界后自动新建昨日提醒。

- [x] **步骤 3：运行新增测试验证通过**

运行：`python -m pytest tests/test_work_countdown.py -k next_day -q`

预期：新增测试全部通过。

- [x] **步骤 4：运行倒计时与下班状态测试**

运行：`python -m pytest tests/test_work_countdown.py tests/test_work_finish_state.py -q`

预期：全部通过且无错误。

- [x] **步骤 5：检查差异与工作区状态**

运行：`git diff --check` 和 `git diff -- src/petnest/ui/work_countdown.py tests/test_work_countdown.py`

预期：没有空白错误，差异仅包含本次边界修复和回归测试。

### 任务 3：让错过的整点提醒按原计划过期

**文件：**
- 修改：`src/petnest/core/work_finish_state.py`
- 修改：`src/petnest/models/settings.py`
- 测试：`tests/test_work_finish_state.py`

- [x] **步骤 1：编写整点提醒迟到边界测试**

验证迟到 10 分钟沿用原整点作为提示起点，迟到恰好 30 分钟直接结束且不展示。

- [x] **步骤 2：运行测试验证失败**

运行：`python -m pytest tests/test_work_finish_state.py -q`

预期：旧逻辑错误地从恢复时刻重新计时，并补出已过期提醒。

- [x] **步骤 3：使用原计划整点推进状态**

创建整点提醒时将 `prompt_started_at` 设为 `next_prompt_at`；若当前时间已经达到 `next_prompt_at + PROMPT_TIMEOUT`，直接进入 `finished`。

- [x] **步骤 4：运行相关测试**

运行：`python -m pytest tests/test_work_finish_state.py tests/test_work_countdown.py -q`

预期：全部通过，且首次晚启动测试继续通过。

- [x] **步骤 5：兼容旧版已持久化的错误提醒**

为新整点提醒持久化 `prompt_timing: scheduled` 标记；加载到旧版无标记的 `hourly prompting` 状态时直接结束。验证错过多个整点以及带时区状态序列化恢复的截止时间。
