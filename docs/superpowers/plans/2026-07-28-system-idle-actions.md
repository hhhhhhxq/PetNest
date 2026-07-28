# 系统空闲动作实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 根据系统空闲时间触发 bored、sleep 与 wake 标准动作。

**架构：** 纯 Python 监控器将秒数转换为仅在状态边界发生的事件；应用层用 Qt 计时器轮询平台适配器；设置提供阈值与开关；状态机使用安全默认绑定。

**技术栈：** Python 3.12、PySide6、Win32 `GetLastInputInfo`、pytest。

---

### 任务 1：空闲状态机与事件

**文件：** `src/petnest/core/system_idle_monitor.py`、`src/petnest/models/event.py`、`tests/test_system_idle_monitor.py`

- [ ] 编写失败测试，覆盖活动→无聊→睡眠→唤醒和不重复发布。
- [ ] 实现不依赖 Qt 的阈值状态机。
- [ ] 运行监控器测试。

### 任务 2：设置与运行时轮询

**文件：** `src/petnest/models/settings.py`、`src/petnest/core/settings_manager.py`、`src/petnest/ui/settings_dialog.py`、`src/petnest/app.py`、`tests/test_settings_manager.py`、`tests/test_app_and_platforms.py`

- [ ] 编写失败测试，覆盖阈值设置和应用层发布事件。
- [ ] 增加开关、两个阈值、每秒 Qt 轮询与启停逻辑。
- [ ] 运行相关测试。

### 任务 3：标准绑定与导入

**文件：** `src/petnest/ui/pet_window.py`、`src/petnest/core/spritesheet_importer.py`、`tests/test_state_machine.py`、`tests/test_spritesheet_importer.py`

- [ ] 编写失败测试，证明缺少 bored/sleep/wake 动作时回退 idle。
- [ ] 合并标准默认绑定与回退，并写入新导入包。
- [ ] 运行全量测试和编译检查。
