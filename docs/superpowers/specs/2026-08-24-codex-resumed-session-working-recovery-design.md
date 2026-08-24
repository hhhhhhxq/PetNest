# Codex 旧任务恢复与 working 状态自愈设计

## 背景

PetNest 当前优先接收 Codex Hook，并在 Hook 不可用时增量读取 `CODEX_HOME/sessions` 下的 JSONL。日志回退只扫描今天和昨天的日期目录，因此恢复更早创建的 Codex 任务时，即使今天产生了新的 `task_started`，PetNest 也不会读取原日期目录中的日志。

此外，Codex 已处于 running 时，点击、拖动或悬浮等临时宠物动作结束后会恢复为 idle；后续新增并发任务仍聚合为 running，现有去重逻辑不会再次发布 working，导致逻辑状态与画面状态不一致。

## 目标

- Hook 不可用时，能够发现今天继续执行的旧 Codex 任务。
- 不递归高频扫描全部历史日志，不读取或保存提示词、回复、代码和工具参数。
- working 作为持续上下文存在；临时宠物动作结束后自动恢复 working。
- 新任务开始时可重新确认 working，使偶发画面漂移自愈。
- Codex 索引缺失、被锁定、损坏或 schema 变化时安全降级，不能影响 PetNest 主功能。

## 方案

### 1. 分层事件来源

优先级保持如下：

1. Codex Hook：精确发送开始、等待、失败和停止事件。
2. Codex 任务索引：只读查询最近活跃任务的 `rollout_path`，将对应 JSONL 加入增量监听。
3. 日期目录回退：保留今天和昨天的现有扫描逻辑。

索引增强只负责发现日志路径，生命周期事件仍由现有 JSONL 解析器产生，避免建立第二套状态解释规则。

### 2. Codex 任务索引读取

- 在已验证的 Codex Home 根目录中枚举 `state_*.sqlite`，不固定依赖某个版本号。
- 以 SQLite 只读 URI 打开候选数据库，设置短超时，不创建、不迁移、不写入任何表。
- SQLite 采用标准 `mode=ro` 与 `query_only` 一致性协议；PetNest 不写业务数据、schema、主库事务或 WAL。WAL 模式下仅在既有 `-wal`/`-shm` 完整且路径安全时读取，并允许 SQLite 协调其管理型共享内存；极小竞态下 SQLite 可能重建自身 sidecar，这不包含提示词、回复或代码，也不视为修改 Codex 业务数据。
- 使用前检查 `threads` 表及 `id`、`rollout_path`、`updated_at_ms` 或兼容更新时间字段。
- 仅查询最近更新的有限数量任务，并按更新时间降序返回日志路径。
- 查询失败、数据库繁忙或 schema 不兼容时返回空结果，由现有日期目录回退继续工作。

### 3. 路径与资源边界

每个索引路径必须同时满足：

- 规范化后位于当前 `CODEX_HOME/sessions` 内；
- 扩展名为 `.jsonl`，是普通文件且路径链不包含软链接；
- 文件数量、单轮读取字节数和单行长度继续受现有限制；
- 重复路径去重，索引候选与日期目录候选共同遵守总文件上限。

索引发现按低频间隔刷新；JSONL 内容仍按文件游标增量读取，不重复扫描完整文件。每次读取都在安全 `stat` 后打开文件，并通过 `fstat` 核对同一文件身份；被替换或路径链变化的候选直接放弃。游标缓存按 TTL/LRU 淘汰并设置硬上限，当前候选和有效恢复租约优先保留。Windows 的 `\\?\\` 路径前缀（包括大小写不同的 UNC 标记）和 macOS/POSIX 路径在进入安全校验前统一规范化。

### 4. working 持续上下文

- 状态机收到 `agent.working` 时记录 working 上下文。
- click、drag、drop、hover 等临时动作可以暂时覆盖画面；动作结束后优先恢复 working，而不是固定恢复 idle。
- 收到 `agent.idle`、`agent.waiting`、`agent.success` 或 `agent.error` 时清除 working 上下文，再按相应状态处理。
- 每个新的 `UserPromptSubmit` 即使没有改变 running 聚合状态，也允许重新发布一次 `agent.working`；工作活动仲裁层允许该重复事件用于画面自愈。
- 未提供 working 动作的宠物继续使用现有动作回退，不新增强制动作。

## 错误处理与兼容

- SQLite 文件不存在、只读打开失败、锁冲突、表或字段缺失：记录诊断状态并回退，不弹错误气泡。
- 索引返回外部路径、软链接、目录或超限文件：忽略该候选，不访问目标。
- JSONL 缺少 `session_id`/`turn_id` 或生命周期格式不兼容：沿用现有保守停用规则，不根据正文猜测状态。
- 恢复租约只在读取到完整、兼容且带有效 turn 的活动记录后续期；无效或不兼容增长不会延长 working，租约到期后发布保守中止事件。
- 多个 Codex Home/profile 只读取当前发现或用户指定的 Codex Home，不跨 profile 混合任务。
- macOS 使用同样的 Codex Home 与 SQLite/JSONL 逻辑；路径比较采用平台规则，不写死 Windows 路径。

## 测试

- 旧日期目录中的任务今天更新时能够产生 working，并在完成后产生停止事件。
- 索引 schema 缺失、数据库锁定、路径越界、软链接、非 JSONL、候选超限均安全降级。
- Windows `\\?\\` 路径和 POSIX 路径规范化后仍受 sessions 根目录约束。
- working → click/drag/drop/hover → 临时动画结束 → 恢复 working。
- 第二个并发任务开始时重新确认 working；`agent.idle` 后不再恢复 working。
- Hook、索引和日期目录发现同一事件时不重复计数。
- 运行 Codex 联动、状态机、工作活动和应用集成测试，再运行完整测试套件。

## 非目标

- 不解析提示词、回复、代码或工具参数。
- 不修改 Codex 配置、Hook 审核状态或 SQLite 数据。
- 不高频递归扫描全部历史 sessions 目录。
- 不改变 waiting、failed、review 和未读任务的既有产品语义。
