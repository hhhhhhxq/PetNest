# Codex 自动发现、真实状态与默认联动设计

## 背景与目标

PetNest 现有基础联动会读取 Codex 本机会话 JSONL，但“允许联动”“检测到 Codex”“找到日志”“日志兼容”和“已经收到状态”没有被完整区分。直接把开关默认改为开启，会把“正在尝试连接”误报成“联动正常”，也无法可靠处理自定义 `CODEX_HOME`、多 profile、旧目录、macOS 路径或尚未生成本地任务的情况。

本次目标：

- 新用户默认允许基础联动；
- 已有有效开关值保持不变；
- 综合多种证据发现 Codex，而不是依赖单一路径；
- 验证日志位置、可读性和结构后再报告“已准备好”；
- 自动发现失败时允许用户指定 Codex 数据目录；
- Windows 与 macOS 使用相同的发现、验证和状态模型；
- 精确连接插件仍需用户主动启用；
- 不读取、展示或保存提示词、回复、代码和工具参数。

## 非目标

- 不把会话 JSONL 当作官方永久稳定接口；
- 不自动安装、审核或启用 Codex 插件；
- 不通过窗口标题作为主要安装证据；
- 不要求用户选择某个会话 JSONL 文件；
- 不重放 PetNest 启动前的历史任务状态；
- 不在本次工作中承诺未经实机验证的 macOS 发布结果。

## 核心概念

### 允许联动

设置开关表示用户是否允许 PetNest 自动发现和监听 Codex。它不代表连接已经成功。

### 安装证据

表示本机可能安装或正在运行 Codex，例如 app-server 响应、Codex Desktop 可执行文件、CLI 或本地数据。安装证据与日志可用性分开判断。

### Codex Home 候选

可能包含 `sessions`、`.codex-global-state.json` 等数据的根目录。候选目录经过验证和排序后才能成为当前日志源。

### 日志源

基础任务状态来自：

```text
<Codex Home>/sessions/YYYY/MM/DD/*.jsonl
```

待查看状态可选地来自：

```text
<Codex Home>/.codex-global-state.json
```

后者缺失只影响“打开任务后自动清除待查看”，不阻止 working/review。

## 架构边界

新增独立的发现层，不把安装检测、候选选择和兼容性判断继续塞入 `CodexSessionLogWatcher`。

### `CodexInstallationDetector`

职责：收集 Codex 安装和运行证据，不读取会话内容。

证据按可信度从高到低包括：

1. Codex app-server 成功响应并返回 `codexHome`；
2. Codex Desktop 的真实可执行文件或 macOS 应用包存在；
3. PATH 中存在可运行的 Codex CLI；
4. `CODEX_HOME` 已配置；
5. 默认或历史 Codex 数据目录存在。

返回证据集合，而不是过早压缩成一个布尔值。仅发现数据目录时状态为“仅发现 Codex 数据”，不能直接断言仍安装 Codex。

### `CodexHomeDiscovery`

职责：生成、规范化、去重和排序 Codex Home 候选。

候选来源：

1. 用户在 PetNest 中明确指定的目录；
2. `CODEX_HOME`；
3. app-server 返回的 `codexHome`；
4. 用户默认 `~/.codex`；
5. 可从已验证 Codex 运行环境推导的其他数据目录。

自动模式不会因为第一个目录存在就停止，而会验证全部候选。手动目录是显式覆盖：无效时显示原因，不静默切换到其他 profile；同时可以提示自动发现存在其他可用目录。用户选择“恢复自动查找”后才重新采用自动候选。

### `CodexLogSourceProbe`

职责：只读验证候选目录，并产生结构化结果。

检查内容：

- 路径存在性和可读性；
- 用户选择的是 Codex Home 还是 `sessions`，选择后统一规范化为 Codex Home；
- `sessions` 是否存在；
- 今天和前一天目录是否存在近期 JSONL；
- 文件是否为普通文件且不通过符号链接或 junction 越界；
- 会话元数据是否含有有界 `session_id`；
-状态记录是否仍使用可识别的外层结构和必要 `turn_id`；
- `.codex-global-state.json` 是否可选可用。

探测只提取事件类型、会话 ID、任务 ID 和必要结构信息；读取内容仅存在于内存，不写入 PetNest 配置、日志或诊断结果。

### `CodexLinkAvailability`

发现层的统一输出，至少包含：

- `state`：状态枚举；
- `message`：普通用户文案；
- `codex_detected`：是否有强安装证据；
- `evidence`：高级详情使用的脱敏证据；
- `selected_home`：当前选择的 Codex Home；
- `sessions_path`：当前会话目录；
- `manual_override`：是否使用用户指定目录；
- `can_watch`：是否可以启动日志监听；
- `technical_reason`：高级详情中的准确原因。

## 跨平台发现

### Windows

检查：

- `%LOCALAPPDATA%\OpenAI\Codex\bin\*\codex.exe`；
- PATH 中的 `codex.exe`、`codex.cmd` 或 `codex.bat`；
- `CODEX_HOME`；
- app-server `codexHome`；
- `~/.codex`。

真实 Desktop `codex.exe` 优先于 PATH 中可能过期的 Node `.CMD` 包装器。

### macOS

检查：

- `/Applications/Codex.app`；
- `~/Applications/Codex.app`；
- PATH 中的 `codex`；
- `CODEX_HOME`；
- app-server `codexHome`；
- `~/.codex`。

基础监听器使用 `pathlib` 和普通只读文件操作，不依赖 Windows API。自动化测试模拟 macOS 路径、权限和日志结构；正式声明 macOS 可用前，必须在安装当前 Codex Desktop 的 Mac 上验证真实 `codexHome`、任务开始、任务完成和已读清除。

## 状态模型与用户文案

可用性状态不覆盖真实任务状态；收到任务事件时，working/waiting/failed/review 优先显示。

| 状态 | 普通页面文案 | 是否监听 |
|---|---|---|
| `disabled` | 联动已关闭 | 否 |
| `detecting` | 正在查找 Codex | 否 |
| `not_detected` | 未检测到 Codex，安装或启动后会自动连接 | 否 |
| `data_only` | 发现 Codex 数据，但未确认当前安装 | 继续低频发现 |
| `waiting_for_sessions` | 已检测到 Codex，等待创建本地任务 | 等待目录/新文件 |
| `unreadable` | 已检测到 Codex，但无法读取本地日志 | 否 |
| `incompatible` | 当前 Codex 版本暂不支持基础联动 | 否，可使用精确连接 |
| `ready` | 联动已准备好，等待新的任务 | 是 |
| `active` | 联动正常 | 是 |
| `running` | Codex 正在工作 | 是 |
| `waiting` | 需要你处理 | 是 |
| `failed` | 执行遇到问题 | 是 |
| `review` | 任务已完成 | 是 |

不得用“联动正常”表示仅仅启动了轮询或某个目录存在。

## 检测与重试时机

1. PetNest 启动并读取设置；
2. 如果用户允许联动，立即执行一次发现；
3. 打开 Codex 联动设置页时强制刷新；
4. 未检测到 Codex、只有数据、等待 sessions 或路径暂时不可用时，每 30 秒低频重试；
5. 找到可监听源后停止安装路径扫描，保留现有 250ms 增量日志轮询；
6. 手动目录失效时保持用户选择并显示原因，不擅自切换 profile；
7. 用户关闭联动后停止发现计时器、日志轮询和联动状态；
8. 用户重新开启后立即重新发现。

重试只做路径和有界文件检查，不反复启动插件安装或读取完整历史。

## 手动选择 Codex 数据目录

### 入口

- 自动发现失败、日志不可读或不兼容时，在主联动卡显示“选择 Codex 数据目录”；
- 自动发现成功时主页面不显示该按钮；
- 高级详情始终提供“重新选择…”和“恢复自动查找”。

### 选择与验证

- 只允许选择文件夹，不选择单个 JSONL；
- 选择包含 `sessions` 的 Codex Home 时直接使用；
- 选择 `sessions` 时自动规范化到父目录；
- 没有历史日志但目录具有 Codex Home 证据时允许保存，状态为“等待创建本地任务”；
- 明显不是 Codex 数据目录时不保存，并就地说明需要选择包含 `sessions` 的目录；
- 选择后从现有文件 EOF 建立基线，不播放历史任务；
- 保存规范化后的只读路径，不复制任何 Codex 文件。

### 设置字段

设置 schema 升级并新增：

```text
codex_home_override: str | None
```

`None` 表示自动发现。路径不存在或不可读时保留该值，便于移动磁盘恢复后自动重连；用户可主动恢复自动查找。

## 默认开启与迁移

- `Settings()` 的 `codex_link_enabled` 默认改为 `True`；
- 新建配置默认允许基础联动；
- 现有配置中有效的 `true` 或 `false` 原样保留；
- 旧 schema 中没有该字段时按新默认补为 `true`；
- 非布尔损坏值按新默认 `true` 归一化；
- 配置文件整体损坏时按现有流程备份，并使用包括默认联动开启在内的新默认设置；
- 用户关闭后持久化 `false`，升级和重启不得重新开启；
- 默认开启不安装精确连接插件，也不产生“未检测到 Codex”气泡。

## 与精确连接插件的关系

- 基础日志源 `ready/active` 时无需插件；
- `unreadable/incompatible` 时可在页面推荐“启用精确连接”；
- 插件仍必须由用户主动点击安装，并在 Codex 中确认；
- 收到真实插件事件后，事件源升级为精确连接；
- 插件失败、未审核或 CET 不兼容时，发现层和基础日志监听继续独立工作；
- 手动 Codex Home 同时传给日志监听、旧 PetNest Hook 清理和 Codex CLI 环境，避免跨 profile 写错位置。

## 错误与安全边界

- 安装检测失败不影响普通桌宠功能；
- 所有探测错误转为结构化状态，不在普通页面展示堆栈或内部路径细节；
- 高级详情显示候选来源、选中路径、验证结果和最近事件，不显示会话正文；
- 不跟随会话目录内的符号链接或 junction；
- 单文件、单行和单轮读取继续保留大小上限；
- 候选目录去重后设置上限，避免异常环境变量造成无限扫描；
- 用户手动路径只用于只读发现和监听；插件写入继续遵循既有独立边界检查。

## 测试与验收

### 发现测试

- 无 Codex、仅旧数据、Desktop 可执行文件、CLI、app-server 和 `CODEX_HOME`；
- 默认 `.codex` 是旧目录但 app-server 返回可用 profile；
- 多个候选中选择真正兼容的源；
- Windows `.CMD` 不遮蔽 Desktop `codex.exe`；
- macOS `/Applications`、`~/Applications` 和 `~/.codex` 模拟；
- 候选目录、sessions 或文件为符号链接/junction；
- 目录不可读、日志过大、JSON 损坏和结构不兼容。

### 设置与迁移测试

- 新用户默认允许联动；
- 已保存 `false` 保持关闭；
- 缺失字段迁移为开启；
- 手动目录保存、重新选择和恢复自动；
- 关闭联动停止发现和监听。

### 运行测试

- 启动时不重放历史；
- 新建会话触发 working；
- 完成触发 review；
- 打开任务清除待查看；
- 找不到 Codex 时不显示错误气泡；
- 不兼容时不猜测状态；
- 设置页实时展示可用性和任务状态；
- 插件失败不停止基础发现。

### 发布验收

- Windows 当前安装环境实机验证；
- 完整自动化测试与插件 validator；
- macOS 自动化路径测试；
- macOS 正式发布前完成真实 Codex Desktop 实机验证，并记录实际 Codex Home 和会话格式证据。

## 实施顺序

1. 先建立发现结果模型和失败测试；
2. 实现安装证据、候选目录和日志探测；
3. 将日志监听器改为消费已验证源；
4. 加入低频重试和真实状态；
5. 加入手动目录选择与持久化；
6. 更新设置页与高级详情；
7. 最后修改默认值和 schema 迁移；
8. 完成 Windows 实机、跨平台自动化、全量回归和发布说明。
