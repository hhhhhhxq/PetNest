# 跨平台自动启动设计

## 目标

为 PetNest 提供一个默认关闭的“自动启动”开关：

- Windows：当前用户登录后启动 PetNest；由系统启动任务运行的 PetNest 异常退出时，每隔一分钟重试，最多三次。
- macOS 13 及以上：当前用户登录后启动 PetNest，不提供异常退出重试。
- 其他平台及不支持的旧版 macOS：不显示该开关。

该功能不引入常驻系统服务，不申请管理员权限。用户从托盘正常退出后，本次登录会话中不会再次拉起应用；下一次登录仍会按照开关设置启动。

## 用户界面

设置中心的“应用与更新”页面新增启动管理卡片。支持的平台显示一个开关和两行辅助说明：

- 开关名称：`自动启动`
- 辅助说明：

  ```text
  登录电脑后自动启动 PetNest
  Windows 上异常退出后将自动重试，最多 3 次。
  ```

开关默认关闭。用户点击“应用并关闭”后才修改系统登录项；取消设置窗口不会产生系统变更。现有 `Settings.run_at_startup` 字段继续作为该开关的持久化值。

## 方案选择

使用统一平台接口表达“当前用户登录后启动”，由各平台采用系统原生机制：

- Windows 使用任务计划程序负责登录触发，由隐藏的 `PetNestStartupHost.exe` 负责有限失败重试。
- macOS 使用 Apple Service Management 的 `SMAppService.mainAppService`，注册主应用登录项。

实机验证证明，Windows 会保存任务 XML 中的 `RestartOnFailure`，也会把被强制终止的 PetNest 记录为结果码 `1`，但不会可靠地重新启动已经成功创建、随后异常退出的普通进程。最小化 `cmd.exe` 探针同样复现，因此不能把该字段作为崩溃恢复保证。

备选方案包括：继续依赖任务计划程序（实机失败）；让 PetNest 自身重启（进程崩溃后已无代码可执行）；以及使用隐藏启动宿主。选择最后一种，因为它能直接等待子进程并区分退出码，且只在系统登录项启动 PetNest 时存在。不采用定时轮询或系统服务，避免用户正常退出后被再次拉起，也不获得额外权限。

## 平台能力接口

`PlatformEventAdapter.register_startup(enabled)` 是应用层修改入口，返回 `StartupRegistrationResult`，区分成功、需要 macOS 用户批准和失败。平台适配器通过 `startup_supported` 报告能力：

- Windows 打包版为支持。
- macOS 13+ 打包版且 Service Management 桥接可用时为支持。
- 源码开发模式、旧版 macOS 和其他平台为不支持。

设置中心不直接判断操作系统名称，只根据平台适配器报告的能力决定是否显示卡片。

## Windows 实现

系统任务使用包含当前用户 SID 的稳定名称，例如 `\PetNest\AutoStart-S-1-5-21-…`。这样同一台电脑上的不同 Windows 用户不会覆盖或删除彼此的任务。开启时创建或覆盖当前用户任务，关闭时只删除当前用户任务。配置如下：

- 触发器：当前用户登录 Windows。
- 身份：当前交互用户，`InteractiveToken`。
- 权限：`LeastPrivilege`，不请求管理员权限。
- 操作：使用绝对路径执行冻结版 `PetNestStartupHost.exe`。
- 工作目录：两个可执行文件所在的 PetNest 安装目录。
- 多实例策略：`IgnoreNew`。
- 错过触发后补启：开启。
- 电池供电：允许启动并继续运行。
- 空闲和网络条件：不作为启动条件。
- 执行时限：无限制。
- 任务本身不配置 `RestartOnFailure`，避免不同 Windows 版本与启动宿主叠加重试。

应用使用无 shell 的参数列表调用系统 `schtasks.exe` 导入受控生成的任务 XML。XML 临时文件使用 UTF-16 编码，并在成功或失败后删除。删除前通过 Task Scheduler COM API 查询精确任务，并以稳定的 HRESULT 区分“任务不存在”和真实错误，避免依赖本地化命令输出。源码模式不创建任务，但可删除当前用户的旧任务。

`PetNestStartupHost.exe` 只使用 Python 标准库并以无窗口单文件形式打包。宿主从自身目录定位 `PetNest.exe`，使用参数列表启动 `PetNest.exe --startup` 并同步等待：

- 返回码 `0`：视为用户正常退出或已有实例已响应，宿主立即正常结束。
- 非零返回码或无法创建进程：记录诊断日志，等待一分钟后重试。
- 最多执行三次重启；第三次重启的进程再次失败后，宿主停止，不开启新一轮。
- 关闭开关或卸载时原子推进 `%LOCALAPPDATA%\PetNest\startup-host.generation`；已经运行的宿主检测到代际变化后立即停止监督，但不会结束用户当前正在使用的 PetNest。

宿主日志写入当前用户的 `%LOCALAPPDATA%\PetNest\logs\startup-host.log`；若日志目录或文件不可写，日志降级为丢弃，但仍启动并监督 PetNest。宿主和 PetNest 使用同一普通用户令牌；它不提供网络接口、不接收外部命令，也不提升权限。

Windows 安装器以管理员身份卸载时，隐藏参数 `--remove-startup` 会枚举 `\PetNest` 任务文件夹，并只删除名称匹配 `AutoStart-S-<SID>` 的全部用户任务及旧版 `AutoStart` 任务。这避免 UAC 使用其他管理员凭据时误以管理员 SID 代替原用户 SID。安装器另以固定名称删除一次旧版任务作为兼容回退；任务或任务文件夹不存在时视为成功。

## macOS 实现

macOS 13 及以上通过 `SMAppService.mainAppService` 注册或注销 PetNest 主应用登录项。应用使用条件依赖 `pyobjc-framework-ServiceManagement` 调用公开 API，不直接写入 `~/Library/LaunchAgents`，也不使用已弃用的 `SMLoginItemSetEnabled`。

系统可能要求用户在“系统设置 → 通用 → 登录项”中批准 PetNest。注册调用成功但状态为 `requiresApproval` 时，应用保存开关并提示用户；调用失败时，开关恢复为修改前的值。

该能力只支持打包后的 `.app`。`SMAppService.mainAppService` 负责后续登录时启动主应用，不为 PetNest 主进程提供“最多三次”的崩溃恢复。

## 应用生命周期

`PetNest.apply_settings()` 只在 `run_at_startup` 变化时调用平台适配器：

- 系统操作成功：保存用户请求的新值。
- 系统操作失败：其余设置照常应用，但 `run_at_startup` 回退为旧值，并显示一次错误提示。

`--startup` 参数只标记系统登录项启动，仍进入既有桌宠流程；现有单实例协调器继续阻止重复窗口。持久化设置开启时，每次正常启动都会在 Qt 事件循环开始后通过后台线程静默重新登记对应平台的登录项，避免系统调用延迟首屏显示或阻塞界面。登记状态带有版本令牌：若用户在后台修复期间修改开关，线程会再次应用最新值，保证最终系统状态与已保存设置一致。修复失败只记录日志，不阻止桌宠启动。

用户从托盘正常退出时，PetNest 返回 `0`，Windows 启动宿主随即结束。异常退出时启动宿主触发有限重试；macOS 本版本不处理崩溃恢复。

## 安全边界

- Windows 创建、覆盖、查询或删除任务均检查进程返回码和超时；任务名只接受系统返回的 SID 格式。
- macOS 注册和注销检查 Service Management 返回值与错误对象。
- 两个平台都以当前普通用户身份运行，不能获得高于 PetNest 当前进程的权限。
- Windows 启动宿主的一分钟冷却和三次上限避免快速、无限的崩溃循环；任务计划程序不再叠加重试。
- 用户可通过 Windows 任务计划程序或 macOS 登录项设置取得最终系统控制权。

## 依赖、打包与验证

`pyproject.toml` 和 `requirements.txt` 增加仅在 Darwin 安装的 `pyobjc-framework-ServiceManagement` 条件依赖，macOS PyInstaller 构建显式包含 `ServiceManagement`，继续使用应用标识 `com.petnest.app`。Windows 任务模块和启动宿主只依赖标准库，macOS 平台模块延迟导入 PyObjC。

自动化测试覆盖启动宿主的正常退出、失败冷却、三次上限、创建进程失败、运行中取消和日志初始化降级，另覆盖任务 XML、任务导入与删除、临时文件清理、macOS 状态映射、设置 UI、失败回退、启动修复、CLI 参数和发布配置。macOS 系统 API 的真实注册、系统设置可见性、注销和重新登录启动必须在 macOS 13+ 打包 `.app` 上实机验证；Windows 任务创建、正常退出和异常恢复必须在安装包产物上实机验证。
