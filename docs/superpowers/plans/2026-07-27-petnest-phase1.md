# PetNest 第一阶段实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 创建可启动、可测试的跨平台配置驱动桌面宠物第一阶段版本。

**架构：** 以独立 core 模块承载配置、状态与动画，UI 仅负责显示和输入；所有动作和事件绑定从宠物包读取；本地 TCP 事件服务通过 EventBus 连接状态机。

**技术栈：** Python 3.12+、PySide6、Pillow、pytest、pytest-qt、PyInstaller。

---

## 文件结构

- `src/petnest/models/`：类型化配置与事件数据模型。
- `src/petnest/core/`：验证、加载、fallback、状态、动画与设置。
- `src/petnest/ui/`：透明桌宠、托盘和设置界面。
- `src/petnest/events/`：鼠标及本地 TCP 事件源。
- `src/petnest/platforms/`：平台能力适配。
- `tools/`：包验证、样例生成、事件发送和帧处理工具。
- `tests/`：核心与 UI 的回归测试。

### 任务 1：初始化与宠物包模型

- [ ] 先写宠物包路径、idle 缺失、FPS、帧尺寸及 fallback 循环的失败测试。
- [ ] 运行 `python -m pytest tests/test_package_validator.py -q`，确认功能缺失而失败。
- [ ] 创建 `pyproject.toml`、依赖文件、数据模型、validator 与 loader；仅让测试要求的行为通过。
- [ ] 重新运行对应测试并提交。

### 任务 2：状态、事件与设置核心

- [ ] 先写 idle/hover、不可中断 drag、单次动画完成、优先级、去重和原子设置恢复的失败测试。
- [ ] 运行 `python -m pytest tests/test_state_machine.py tests/test_settings_manager.py -q`，确认失败。
- [ ] 实现 `EventBus`、`PetStateMachine`、`FallbackResolver` 和 `SettingsManager`。
- [ ] 重新运行核心测试并提交。

### 任务 3：动画与本地事件服务

- [ ] 先写自然排序、动画结束通知、JSON 校验、超大消息、限流和只绑定回环的失败测试。
- [ ] 实现预加载动画播放器和具有可控生命周期的本地 TCP 服务。
- [ ] 运行 `python -m pytest tests/test_animation_player.py tests/test_external_events.py -q` 并提交。

### 任务 4：PySide6 桌宠 UI 与托盘

- [ ] 先用 pytest-qt 写窗口创建、点击、拖动、动画计时器和宠物重载的失败测试。
- [ ] 实现透明无边框置顶窗口、alpha 命中缓存、拖动阈值、托盘菜单及简易设置对话框。
- [ ] 运行 `python -m pytest tests/test_pet_window.py -q` 并提交。

### 任务 5：应用装配、平台接口与工具

- [ ] 先为应用关闭和平台 unsupported 行为写失败测试。
- [ ] 实现应用装配、平台适配接口、样例宠物生成器、事件发送/包验证/预览/帧标准化工具和运行脚本。
- [ ] 生成样例宠物，运行 `python tools/validate_pet.py pets/sample_pet`，再运行完整测试并提交。

### 任务 6：文档、静态检查与运行验证

- [ ] 编写中文 README、LICENSE 和打包脚本，明确平台限制与隐私边界。
- [ ] 运行 `python -m compileall src tools`、`python -m pytest -q` 和 `python -m petnest --check`。
- [ ] 实际启动应用并验证可创建透明窗口，随后正常退出。
