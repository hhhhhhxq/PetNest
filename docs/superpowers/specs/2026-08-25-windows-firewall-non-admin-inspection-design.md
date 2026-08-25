# Windows 防火墙普通权限检测修复设计

## 背景

PetNest 安装版平时以普通用户权限运行。用户点击互动窗口中的“一键允许”后，应用通过一次 Windows UAC 启动临时提权入口，成功重建以下两条入站规则：

- `PetNest LAN UDP 18487`
- `PetNest LAN TCP 18487`

规则限定到当前安装的 `PetNest.exe`，启用 Private 和 Public 网络配置文件。提权入口退出后，主应用恢复普通权限并重新检查规则。

当前检查使用 `Get-NetFirewallRule`、`Get-NetFirewallPortFilter` 和 `Get-NetFirewallApplicationFilter`。在已复现的 Windows 设备上，普通用户调用 `Get-NetFirewallRule` 返回 Access Denied；脚本又使用 `SilentlyContinue` 忽略错误，最终把空结果误判为“两条规则均不存在”。因此系统规则已经生效，但互动窗口仍显示“规则仍未完整生效”。

## 目标

- 普通权限下准确识别 PetNest 已生效的 Public 防火墙规则。
- 用户通过 UAC 完成“一键允许”后，互动窗口警告立即消失。
- 重启 PetNest 后仍能识别现有规则，不依赖一次性的成功缓存。
- 检查失败时明确归类为“无法检查”，不冒充“规则未放行”。

## 非目标

- 不修改 Windows UAC 的系统文案、样式或触发方式。
- 不扩大规则端口、方向、程序范围或网络配置文件范围。
- 不改变 macOS 和 Linux 行为。
- 不解析本地化的 `netsh show rule` 文本。
- 不通过缓存“一键允许成功”来替代实时系统状态。

## 方案选择

### 采用：Windows Firewall COM 接口

PowerShell 通过内置 COM 对象 `HNetCfg.FwPolicy2` 读取有效规则集合。该接口在复现设备的普通权限下可用，并返回稳定的布尔值和数值字段：

- `Enabled`
- `Direction`
- `Action`
- `Profiles`
- `Protocol`
- `LocalPorts`
- `ApplicationName`

实机验证得到 Profiles `6`（Private `2` + Public `4`）、TCP Protocol `6`、UDP Protocol `17`，并能读取端口和程序路径。

### 不采用：解析 netsh 文本

`netsh advfirewall firewall show rule` 在普通权限下可读，但字段名和值会随 Windows 显示语言变化，不适合作为稳定的机器接口。

### 不采用：缓存修复成功

缓存无法反映规则在应用退出后被删除、禁用或被系统策略覆盖的情况，会产生过期的成功状态。

## 架构与数据流

保留 `WindowsLanFirewallBackend.inspect()` 的现有边界和 JSON 载荷。PowerShell 检查仍负责：

1. 找到当前默认 IPv4 路由对应的 Public 网络。
2. 读取 Public 防火墙是否启用以及是否禁止本地规则。
3. 创建 `HNetCfg.FwPolicy2` 并枚举有效规则。
4. 对 UDP 和 TCP 规则执行严格匹配。
5. 输出现有 JSON 字段，Python 侧继续构造 `LanFirewallStatus`。

应用层和 `LanFirewallAdvisorCoordinator` 不需要改变。提权写规则完成后，协调器已有的修复后重新检查会收到 `udpAllowed=True`、`tcpAllowed=True`，然后发出修复成功事件并清除警告。

## 规则匹配

一条规则只有同时满足以下条件才算有效：

- 名称等于预期的 UDP 或 TCP 规则名。
- `Enabled` 为真。
- `Direction` 为 Inbound（数值 `1`）。
- `Action` 为 Allow（数值 `1`）。
- `Profiles` 包含 Public 位（数值 `4`），或为全部配置文件。
- `Protocol` 分别等于 UDP `17` 或 TCP `6`。
- `LocalPorts` 精确表示端口 `18487`。
- `ApplicationName` 与当前运行的 `PetNest.exe` 绝对路径不区分大小写相等。

保持名称、程序和端口三重限定，避免把其他应用或更宽泛的规则误认为 PetNest 已安全放行。

## 错误处理

- 创建 COM 对象或枚举规则失败时，让 PowerShell 检查以非零状态结束。
- Python 后端沿用现有异常处理，返回带 `error` 的 `LanFirewallStatus`。
- 带 `error` 的状态不触发“未放行”判断；界面不会错误声称规则缺失。
- UAC 被取消、规则写入失败和组织策略阻止仍沿用现有提示。

## 测试

### 后端脚本测试

- 断言检查脚本使用 `HNetCfg.FwPolicy2`，不再依赖 `Get-NetFirewallRule` 读取 PetNest 规则。
- 断言脚本包含 Public、Inbound、Allow、协议、端口和程序路径匹配。
- 保留 JSON 解析、Public 网络摘要和策略管理测试。

### PowerShell 集成测试

在 Windows 测试主机上，以普通权限创建替代的 COM 规则对象输入或拆分可测试的规则判定函数，覆盖：

- UDP/TCP 两条规则完整时均通过。
- 缺少一条规则时只标记对应协议失败。
- 程序路径、端口、方向、动作或 Public 配置文件不匹配时失败。
- COM 规则读取异常时返回检查错误，而不是两条规则为假。

### 应用回归

保留现有“一键允许后必须经过重新检查才成功”的协调器与应用测试。后端状态变为两条规则均通过后，警告消失；应用重启后的首次检查得到相同结果。

## 安全与兼容性

- COM 接口仅用于读取；规则修改仍只发生在用户确认的 UAC 提权入口中。
- 不降低检查条件，也不接受端口或程序范围更宽的替代规则。
- `HNetCfg.FwPolicy2` 是目标 Windows 版本自带的防火墙接口，无新增依赖。
- 非 Windows 平台继续返回不适用状态。

## 验收标准

- 复现设备以普通权限检查当前两条 Private+Public 规则时，得到 UDP/TCP 均允许。
- 点击“一键允许”并同意 UAC 后，互动窗口警告在修复后检查完成时消失。
- 重启已安装 PetNest 后警告不再误报。
- 自动化测试与完整测试套件通过。
