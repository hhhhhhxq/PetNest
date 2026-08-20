# Codex 日志回退与联动引导设计

## 目标

“Codex 联动”总开关在保存后必须立即产生可用联动，不再要求用户先安装 Hook、寻找信任入口或重启 Codex。PetNest 优先使用官方 Hook；Hook 未安装、未信任、运行失败或长时间没有事件时，自动读取本机 Codex 会话 JSONL 的新增状态行作为回退。

首版日志回退稳定支持 `working → review/idle`。`waiting` 与 `failed` 只有在当前 Codex 版本提供明确事件时才启用，不依据文本内容猜测。

## 数据来源与优先级

1. **官方 Hook**：事件到达时优先使用，可提供 working、waiting、failed、review。
2. **本机会话日志回退**：Hook 没有为当前 turn 到达时接管，稳定提供 working、review、idle。
3. **不可用**：会话目录不存在或 JSONL 基础结构不兼容时停止联动并提示，不伪造状态。

同一 `(session_id, turn_id)` 的两种来源由现有协调器去重。日志先产生 working、Hook 稍后到达时可升级为 Hook 来源但不重启动画。Hook 没有 turn_id 时，使用日志记录的当前 active turn；没有日志 turn 时按 session 聚合。

## JSONL 增量监听

新增纯核心 `CodexSessionLogWatcher`：

- 默认目录为 `~/.codex/sessions/YYYY/MM/DD`，同时检查今天与前一天以覆盖跨午夜任务；
- 开启时把已有文件偏移设为 EOF，不重放历史任务；
- 新文件从头读取，现有文件只读取上次偏移后的字节；
- 不完整的最后一行保留到下次 poll，单行过大或格式错误时安全跳过；
- 每 250ms poll，一次读取有上限，避免阻塞 Qt 主线程；
- 文件截断或替换时重新建立偏移，不重复发出已经确认的事件；
- 只保留文件路径、偏移、session/turn ID 和状态，不保存 prompt、assistant message、tool input 或代码内容。

事件映射：

| JSONL 事件 | 联动事件 | 状态 |
| --- | --- | --- |
| `event_msg.task_started` | `UserPromptSubmit` | working |
| `event_msg.task_complete` | `Stop` | review |
| `event_msg.turn_aborted` | `TurnAborted` | 清理当前 turn 并恢复上下文；中断不等同失败 |

若未来版本更名但仍能识别基础事件，使用版本适配表；未知版本保守使用上述核心事件。连 `session_meta`、`event_msg` 或 turn ID 都无法识别时进入“不兼容”，不猜测。

## 自动来源选择

联动开启且允许日志回退时，日志 watcher 立即启动。每个 turn：

- JSONL task_started 可立即触发 working，不等待 Hook 超时；
- 同 turn 后续 Hook 事件到达后标记为“官方 Hook”，并允许 waiting/failed 覆盖；
- 只有 JSONL 事件时标记为“本地日志回退”；
- task_complete 进入 review；turn_aborted 只结束对应 turn，不显示失败气泡；
- 同时监听 `.codex-global-state.json` 的本机未读会话 ID；review 会话从未读集合移除时，仅清除该会话的 review 气泡；
- review 动画只播放当前宠物该动作的一个时间线周期，随后恢复 idle，未读徽标与动画生命周期分离；
- 应用关闭、联动关闭或日志源不可用时清空 watcher 状态并恢复上下文。

因为 JSONL 与 Hook 都可能到达，协调器必须用 session/turn 去重，禁止产生两个并行任务或重复播放 review。

## 设置与迁移

设置 schema 增加：

- `codex_link_log_fallback_enabled: bool = True`

旧用户迁移后默认允许回退。用户可在高级设置选择“仅使用官方 Hook”，此时 Hook 不可用就明确显示未连接。

## 设置页流程

### 1. 联动总开关与当前状态

页面首卡只呈现主任务：

- “跟随 Codex 状态播放动作”总开关；
- 说明：“开启并保存后即可使用。PetNest 优先使用官方 Hook，不可用时自动使用本机会话日志。”；
- 当前状态徽标：
  - `完整联动 · 官方 Hook`
  - `已联动 · 本地日志回退`
  - `部分联动 · waiting/failed 不可用`
  - `等待新的 Codex 任务`
  - `当前 Codex 版本不兼容`
  - `联动已关闭`
- 当前来源与能力说明，不用“已安装”冒充“已连接”。

### 2. 提醒与动作

保留气泡开关和 working/waiting/error/review 实际回退结果。按当前来源标注：日志模式保证 working/review，waiting/failed 为 best-effort。

### 3. 可折叠“官方 Hook 精确增强”

Hook 不再是主流程前置条件。折叠卡显示：

- 已安装数量、已信任数量、运行器健康状态；
- “安装/修复 Hook”“移除 PetNest Hook”；
- 唯一正确的桌面路径：“Codex 设置 → 钩子 → 用户配置”；
- 不再提示在聊天框输入 `/hooks`；
- CET、命令启动失败或连续没有 Hook 事件时显示：“官方 Hook 不可用，已自动使用本地日志，无需额外处理。”

### 4. 测试与诊断

- “测试宠物动画”：本地播放 working → review → idle，并明确标注不代表 Codex 已连接；
- “检查联动状态”：刷新会话目录、Hook 安装/信任、监听端口、最近 Hook/日志事件和当前来源；
- 诊断结果在页面内显示，不弹出多个消息框。

## 隐私与安全

- 页面明确说明 JSONL 文件由 Codex 本身创建，PetNest 只读取新增事件元数据；
- JSON 解码不可避免会在内存中短暂解析整行，但 PetNest 不提取、不使用、不复制 prompt/message/tool_input 的值，也不写入自己的日志；
- 只监听当前用户的 `~/.codex/sessions`；
- 单次读取、单行长度、文件数和解析频率都有上限；
- 符号链接、目录逃逸和非普通文件不读取；
- “仅官方 Hook”选项可完全禁止 JSONL 回退。

## 验收标准

- 开启联动并保存后，无 Hook 也能在 500ms 内由新 task_started 驱动 working；
- task_complete 驱动 review，turn_aborted 清理当前状态并恢复 idle；
- 在 Codex 中打开未读会话后，对应 review 气泡自动消失；
- review 动画播放一个周期后恢复 idle，不因未读徽标持续循环；
- 启用时不重放历史会话；
- 半行、损坏行、文件截断、跨午夜、多会话并发不会崩溃或重复动画；
- Hook 与 JSONL 同时到达时每个 turn 只有一个聚合状态；
- 设置页不再把主开关描述成 Hook 已完成，也不再要求 `/hooks`；
- Hook 不可用时页面自动显示日志回退，无需用户排障；
- 关闭日志回退后不读取 sessions 目录；
- 不保存或输出提示词、回复、工具输入与代码正文；
- 现有 Hook、动作、气泡、外部事件和完整测试套件通过。
