# Codex 联动简化设置与 PetNest 插件设计

## 目标

普通用户打开“Codex 联动”页面时，只需要理解三件事：如何开启、当前是否正常、是否需要自己操作。JSONL、Hook、session、turn 和动作内部名称默认不展示；高级用户可通过提示图标和折叠详情查看真实来源、路径、能力与原因。

精确状态识别从匿名用户 Hook 改为一个可识别的 Codex 插件“PetNest 状态联动”。插件内部仍按 Codex 生命周期注册事件，但 Codex UI 显示统一 plugin 来源，用户通过插件级操作启用或停用。

## 普通页面

### 联动卡

- 总开关：“Codex 联动”；
- 说明：“让宠物自动跟随 Codex 的工作状态变化。开启并保存后即可使用。”；
- 普通状态：联动已关闭、等待新的任务、Codex 正在工作、需要你处理、任务已完成、联动暂不可用；
- 状态后提供 `ⓘ`，tooltip 才显示当前来源与技术原因；
- 只在必要时显示操作按钮：“测试一下”“重新检查”“选择 Codex 数据目录”“启用精确状态识别”。

### 当前宠物能力

如果 working/review 实际解析到 idle，联动卡内显示黄色提示：

> 当前宠物缺少“任务进行中”或“任务完成”动画，对应状态会保持待机，看起来可能像没有生效。

提供“为当前宠物添加动作”入口。动作完整时不显示提示。tooltip 中可查看 working/review 等内部名称和实际回退结果。

### 提醒卡

只显示普通语言：

- “Codex 需要我操作时提醒”；
- “Codex 完成任务时提醒”。

## 高级详情

默认折叠“高级设置与技术详情”，展开后显示：

- 当前来源：本机会话状态 / PetNest 插件；
- Codex Home、sessions 路径、最近事件；
- 日志回退开关；
- working/waiting/error/review 与当前宠物实际动作；
- 诊断结果和“检查连接”。

## 精确状态识别插件

插件名 `petnest-status-link`，展示名“PetNest 状态联动”。插件源包含：

- `.codex-plugin/plugin.json`；
- `hooks/hooks.json`；
- 四个必要事件：UserPromptSubmit、PermissionRequest、PostToolUse、Stop；
- 所有命令仍调用 PetNest 的脱敏 `--codex-hook` 桥接。

不再安装 SessionStart、SessionEnd、PreToolUse。插件 Hook 运行失败时不影响本地日志基础联动。

### 状态驱动的单一操作

- 未安装：“启用精确状态识别”；
- 插件材料不完整：“修复精确状态识别”；
- 已安装、等待 Codex 确认：“我已完成，重新检查”；
- 已收到插件事件：“精确状态识别已启用”；
- 运行器不可用：“当前设备使用基础联动，无需处理”。

“停用精确状态识别…”放在高级详情底部，点击后二次确认；不与启用/修复按钮并排。停用不关闭基础联动。

### Codex 操作引导

需要用户确认时显示步骤：

1. PetNest 配置连接；
2. Codex → 设置 → 插件，找到“PetNest 状态联动”并启用；
3. 如 Codex 仍显示 Hook 审核：设置 → 编码 → 钩子 → `Plugin - PetNest`，确认信任；
4. 返回 PetNest，点击“我已完成，重新检查”。

## 插件安装

PetNest 在用户个人 marketplace 下原子维护自身条目和插件材料：

- marketplace：`~/.agents/plugins/marketplace.json`；
- 插件材料：`~/plugins/petnest-status-link`（个人 marketplace 的 `./plugins/...` 按 Codex 个人插件规则从用户目录解析）；
- 保留其他 marketplace 字段和插件条目；
- 调用当前 Codex CLI：`codex plugin add petnest-status-link@personal --json`；
- 停用调用 `codex plugin remove petnest-status-link`，不删除其他插件；
- 旧版 PetNest 用户 Hook 在插件启用成功后仅移除 PetNest 自己的条目。

所有写入先验证路径、备份现有文件并原子替换。CLI 失败时基础联动继续工作，错误在高级详情显示。

## 验收

- 默认页面不出现 JSONL、Hook、working/review/idle 等术语；
- 普通用户可只用总开关和状态完成使用；
- 缺少基础动作时在首卡明确提示；
- 页面打开时自动判断是否需要启用、修复或重新检查精确连接；
- 主流程永远只显示一个精确连接操作；
- 停用操作隐藏在高级详情并二次确认；
- Codex UI 中插件来源可识别为 PetNest；
- 插件安装/停用不破坏其他 marketplace、插件或 Hook；
- JSONL 基础联动在插件缺失、未信任、CET 失败时继续工作；
- 相关插件验证、设置页、联动和完整测试通过。
