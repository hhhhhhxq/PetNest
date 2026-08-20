# Codex 联动简化设置与插件实现计划

> **执行要求：** TDD；只提交本功能文件；插件用 plugin-creator validator 验证。

**目标：** 简化普通设置页，并用一个可识别的 PetNest Codex 插件承载精确状态 Hook。

### 任务 1：插件模板

- 用 plugin-creator scaffold 创建 `assets/codex-plugins/petnest-status-link`，包含 manifest、hooks、scripts 目录。
- 修改 manifest 为“PetNest 状态联动”，Hook 仅保留 UserPromptSubmit、PermissionRequest、PostToolUse、Stop。
- 增加模板验证测试，运行 plugin validator。

### 任务 2：插件安装管理器

- 新建 `src/petnest/core/codex_plugin.py` 和 `tests/test_codex_plugin.py`。
- 测试个人 marketplace 新建、保留其他插件、幂等修复、路径边界、Codex CLI add/remove、失败不破坏文件。
- 实现状态视图、材料复制/命令重写、原子 marketplace 合并和 CLI 调用。
- 插件启用成功后移除旧 PetNest 用户 Hook。

### 任务 3：应用装配

- 替换设置页 Hook 回调为插件状态驱动回调；基础日志联动不变。
- 增加插件状态、重新检查、启用/修复、停用回调和诊断信息。
- 测试插件失败时仍使用日志回退。

### 任务 4：普通设置页简化

- 失败测试覆盖：主页面无专业术语；普通状态；tooltip 技术详情；动作缺失警告；两项提醒；一个测试按钮。
- 高级详情覆盖来源、路径、动作映射、日志回退和诊断。
- 精确连接区域同一时间只显示一个主要操作；停用为二次确认文字操作。

### 任务 5：验证与集成

- 插件 validator、Codex plugin manager、设置页和联动回归。
- 完整 pytest、compileall、diff check。
- 提交并 cherry-pick 到实际 main，重启 PetNest。
