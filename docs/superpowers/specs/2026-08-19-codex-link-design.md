# Codex 联动设计

## 目标

PetNest 新增独立的“Codex 联动”设置页。启用后，当前宠物根据本机 Codex 任务状态播放对应动作，并在需要用户注意时显示不遮挡工作倒计时的状态气泡。

本功能不读取或保存提示词、回复正文、代码内容、账号凭据。联动只接收任务标识、Hook 事件名、工具执行结果等生成状态所需的最小信息。

## 接入方式

### 状态来源

采用 Codex 官方 Hooks 作为唯一的实时状态入口，不启动第二个 `codex app-server` 轮询桌面任务。

原因：独立启动的 app-server 只能看到自己的运行时，无法可靠读取 Codex 桌面应用当前已加载任务。Hooks 则由正在运行的 Codex 会话在生命周期节点主动触发，能够覆盖提交、执行、等待批准和结束等状态。

PetNest 提供一个不启动 GUI 的轻量 `--codex-hook` 桥接子命令，并在用户明确点击“安装/修复 Hook”后，合并写入用户级 `~/.codex/hooks.json`。写入时：

- 保留所有非 PetNest Hook 和未知字段；
- PetNest 条目使用稳定标识，重复安装只更新自己的条目；
- 卸载只移除 PetNest 条目，绝不整体覆盖或删除 Hooks 配置；
- Windows 安装版使用 `commandWindows` 调用当前 PetNest 可执行文件；源码运行时调用当前 Python 解释器的 `-m petnest --codex-hook`；
- 桥接子命令在创建 Qt 窗口和单实例锁前读取 Codex 传入的标准输入 JSON，裁剪后发送到 `127.0.0.1` 并立即退出；
- Codex 对非托管 Hook 的审查/信任仍由 Codex 自身完成，PetNest 只提示用户进入 `/hooks` 确认，不伪造信任状态。

监听事件：

- `SessionStart`、`SessionEnd`
- `UserPromptSubmit`
- `PreToolUse`、`PostToolUse`
- `PermissionRequest`
- `Stop`

### 本地通信与鉴权

复用 PetNest 的本地外部事件服务，但新增 Codex 专用入口和验证：

- 仅监听 `127.0.0.1`，不接受局域网连接；
- 首次安装生成高强度随机共享令牌；
- 令牌写入 PetNest 用户数据目录下的独立联动元数据文件，不进入普通设置导出；
- Hook 桥接请求必须携带正确令牌，否则直接丢弃；
- 限制单条消息大小、字段长度、事件种类和频率；
- 后台监听线程只负责解析与验证，通过 Qt 信号把事件切回主线程后才更新宠物和界面；
- “Codex 联动”开启时，即使通用“外部事件服务”关闭，也只为 Codex 桥接启动本机监听；关闭联动后若通用服务也未开启，则停止监听。

## 状态模型

协调器按 `(session_id, turn_id)` 保存活跃任务，避免多个 Codex 窗口或任务互相覆盖。收到事件时执行以下转换：

| Codex Hook | PetNest 状态 | 行为 |
| --- | --- | --- |
| `UserPromptSubmit` | `running` | 开始或恢复任务 |
| `PreToolUse` | `running` | 工具执行中 |
| `PostToolUse` 成功 | `running` | 任务仍在继续 |
| `PostToolUse` 失败 | `failed`（短暂） | 显示一次工具失败提醒；后续执行事件可恢复为 running |
| `PermissionRequest` | `waiting` | 持续等待用户处理 |
| `Stop` | `review` | 本轮已停止，等待用户查看；若 `stop_hook_active` 表示仍在续跑则不结算 |
| `SessionEnd` | 移除 | 清理该会话的所有状态 |

多个任务同时存在时，聚合优先级为：

`waiting > failed > review > running > idle`

聚合气泡显示同类任务数量，例如“2 个 Codex 任务等待你处理”。任何新执行事件都能覆盖同一任务先前的临时失败状态，避免一次工具报错把整个任务永久标红。

### 已知限制

稳定版 Hooks 当前没有提供一个可供外部程序可靠区分“整轮成功”与“整轮失败”的最终结果字段。因此：

- `Stop` 只能确定该轮已停止并进入 `review`，不能承诺精确判断最终成功/失败；
- `PostToolUse` 失败只代表某次工具调用失败，不等于整个 Codex 任务失败；
- PetNest 不读取回复正文猜测结果，也不依赖 Codex 内部数据库或未公开协议；
- 设置页明确显示“最终完成状态为 Hooks 可提供的最佳状态”，避免误导。

## 动作语义

PetNest 事件保持现有通用命名，Codex 协调器只负责发布这些事件：

| 联动状态 | PetNest 事件 | 首选动作 | 缺失时 |
| --- | --- | --- | --- |
| running | `agent.working` | `working` | 回退 `idle` |
| waiting | `agent.waiting` | `waiting` | 回退 `idle` |
| failed | `agent.error` | `error` | 回退 `idle` |
| review | `agent.success` | `review` | 回退 `idle` |
| idle | 恢复上下文 | 当前系统空闲/普通动作 | 回退 `idle` |

Codex 8×9 精灵图后续导入规则同步纠正：

- `jumping` 行导入为 `hover`，绑定 `mouse.enter`；
- `review` 行导入为 `review`，绑定 `agent.success`；
- 不再把 `jumping` 生成为 `drop`；
- 不再为 `mouse.drag_end` 硬凑动作；
- 若宠物没有拖动结束绑定，松手时由状态机恢复当前上下文动作，确保离开循环 `drag`；
- `waving` 暂保留为点击动作 `click`，不改变既有点击交互。

该规则只影响之后导入的精灵图。已安装宠物不做不可逆批量改写；如需迁移，后续提供明确的单宠物修复入口。

## 设置页

在设置中心左侧导航新增“Codex 联动”，放在“系统空闲”和“工作倒计时”之间，避免与隐藏的“Codex 用量”入口混合。

页面分为三张卡片：

1. **联动开关与状态**
   - “跟随 Codex 状态播放动作”总开关；
   - 当前状态：未安装 / 需要 Codex 信任 / 等待首次事件 / 已连接 / Hook 异常；
   - “安装/修复 Hook”和“移除 PetNest Hook”按钮；
   - 显示最近一次有效事件时间，不显示事件内容。

2. **状态动作说明**
   - 展示 running、waiting、failed、review 对应动作；
   - 显示当前宠物是否具备对应动作及实际回退结果；
   - 此阶段不允许用户自由选择任意动作，先保证语义一致和设置简单。

3. **提醒方式**
   - “需要处理时显示气泡”；
   - “任务停止时显示完成气泡”；
   - 关闭气泡不影响宠物动作联动。

普通偏好存入设置：

- `codex_link_enabled`，默认关闭；
- `codex_link_show_attention_bubbles`，默认开启；
- `codex_link_show_review_bubbles`，默认开启。

Hook 安装状态、共享令牌和最近事件属于运行元数据，不进入普通设置模型或设置导出。

## 状态气泡

Codex 使用独立状态气泡，不复用局域网聊天气泡，也不覆盖全屏下班提醒或工作倒计时：

- `running`：只播放动作，不显示气泡；
- `waiting`：持续显示“Codex 正在等待你处理”，直到状态变化或用户关闭；
- `failed`：高优先级持续提示某次执行遇到问题；
- `review`：显示约 10 秒完成提示，并保留一个未读标记，直到用户点击/关闭或任务重新开始；
- 多任务显示聚合数量；
- 气泡可点击，点击时尝试把 Codex 窗口带到前台；
- 由于没有稳定公开的单任务深链，首版不承诺点击后精确跳到对应任务。

气泡位置根据宠物所在屏幕可用区域自动选择，优先位于宠物上方；若与倒计时卡片重叠则换边或隐藏低优先级 review 气泡。waiting/failed 不会被 review 覆盖。

## 生命周期与故障处理

- PetNest 启动且联动开启：启动本地监听，检查 Hook 文件和桥接脚本，仅报告状态，不自动改写 Codex 配置；
- 用户点击安装/修复：先备份目标 Hooks 文件，再做结构化合并和原子替换；解析失败时不写入并显示错误；
- 联动关闭：停止处理新状态、清空联动气泡并恢复宠物上下文，但保留 Hook，便于再次开启；
- 用户点击移除：只删除 PetNest 标记的 Hook，保留令牌元数据和其他 Hook；
- 端口占用：不终止占用进程；设置页报告冲突并允许重试；
- Hook 请求异常、鉴权失败或过大：记录脱敏日志，不更新 UI；
- PetNest 关闭：先停止接收事件，再停止监听线程，避免 Qt 对象销毁后被后台线程访问。

## 验收标准

- 设置中心出现独立“Codex 联动”页，默认关闭；
- 安装/修复 Hook 不覆盖用户已有 Hook，重复执行幂等；
- 未携带正确令牌的本机事件不能改变宠物状态；
- UI 更新全部发生在 Qt 主线程；
- running、waiting、review 和工具失败能按设计驱动当前宠物；
- 多任务按优先级和数量聚合，结束会话后能清理；
- waiting/failed 气泡持续，review 气泡限时且保留未读，running 无气泡；
- 气泡不遮挡工作倒计时，关闭气泡设置不影响动作；
- 新导入精灵图使用 `jumping → hover`、`review → review`，且没有 `drop` 时拖动松手仍恢复正确动作；
- 已安装宠物不会被批量修改；
- Hook 配置损坏、端口占用、PetNest 未运行、Codex 未信任 Hook 等情况均有可理解提示且不会破坏用户文件；
- 相关单元测试、Qt 测试、外部事件回归和完整测试套件通过。
