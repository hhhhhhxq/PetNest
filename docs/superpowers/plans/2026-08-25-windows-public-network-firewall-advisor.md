# Windows 公用网络防火墙提醒实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框逐项完成。

**目标:** 当 Windows 当前连接被标记为“公用网络”且 PetNest 的 TCP/UDP 18487 入站规则不完整时，给出不会自动消失的醒目提醒，并允许用户通过一次 UAC 授权完成修复。

**架构:** 新增一个不依赖 Qt 的 Windows 防火墙检测/修复后端，以及一个负责异步调度的 Qt 协调器。应用层把检测状态分别投递给桌宠旁提示气泡和互动窗口警告条；设置只保存当前公用网络的匿名指纹，用于避免同一网络反复弹气泡。安装器继续默认只放行专用网络，macOS 与其他平台使用空实现。

**技术栈:** Python 3.12、PySide6、Windows PowerShell/CIM、Windows ShellExecuteExW、pytest、Inno Setup。

**提交策略:** 按用户要求，不为本计划或规格文档创建独立提交，也不逐任务提交。所有文档、实现和测试通过后，将现有规格提交 `93501ef` 与本次改动整理为一个提交。

---

## 文件结构

- 新增 `src/petnest/core/windows_lan_firewall.py`：查询 Windows 当前网络类别与 PetNest 防火墙规则；以提升权限的当前安装程序修复规则。
- 新增 `src/petnest/core/lan_firewall_advisor.py`：在工作线程执行检测/修复，向 Qt 主线程发布不可变状态。
- 修改 `src/petnest/__main__.py`：增加仅供已打包程序使用的隐藏防火墙修复入口。
- 修改 `src/petnest/models/settings.py`：保存已关闭提示的公用网络匿名指纹。
- 修改 `src/petnest/core/settings_manager.py`：把设置版本升级到 28。
- 修改 `src/petnest/core/lan_service.py`：提供修复后立即重新发现并探测已保存好友的公开方法。
- 新增 `src/petnest/ui/lan_firewall_notice.py`：桌宠旁常驻、可点击、可关闭的非模态提示气泡。
- 修改 `src/petnest/ui/pet_window.py`：托管提示气泡并转发点击/关闭信号。
- 修改 `src/petnest/ui/lan_interaction_dialog.py`：增加固定在顶部的橙色警告条和“一键允许”按钮。
- 修改 `src/petnest/app.py`：连接设置、检测协调器、提示气泡、互动窗口及修复后的重新发现。
- 修改 `README.md`：说明安装时的专用/公用网络默认行为和运行时补救入口。
- 新增/修改对应测试文件，所有系统命令和 UAC 调用均使用假对象，不改动开发机防火墙。

## 任务 1：设置模型保存“该公用网络已关闭提示”

**文件：**

- 修改：`src/petnest/models/settings.py`
- 修改：`src/petnest/core/settings_manager.py`
- 测试：`tests/test_settings_manager.py`

- [ ] **步骤 1：先写设置往返和迁移失败测试**

在 `tests/test_settings_manager.py` 增加测试，覆盖：

```python
def test_settings_round_trip_preserves_dismissed_public_networks(tmp_path: Path) -> None:
    manager = SettingsManager(tmp_path / "settings.json")
    settings = replace(
        Settings(),
        lan_firewall_dismissed_public_networks=("network-a", "network-b"),
    )

    manager.save(settings)

    assert manager.load().lan_firewall_dismissed_public_networks == (
        "network-a",
        "network-b",
    )


def test_migration_27_adds_empty_firewall_dismissals(tmp_path: Path) -> None:
    payload = Settings().to_dict()
    payload["schema_version"] = 27
    payload.pop("lan_firewall_dismissed_public_networks", None)
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    loaded = SettingsManager(path).load()

    assert loaded.schema_version == 28
    assert loaded.lan_firewall_dismissed_public_networks == ()
```

再增加一个脏数据测试：非字符串、空字符串和重复项被丢弃，最多保留最后 20 个有效指纹。

- [ ] **步骤 2：运行测试确认失败**

运行：

```text
python -m pytest tests/test_settings_manager.py -q
```

预期：因为 `Settings` 还没有新字段且版本仍为 27，新增测试失败。

- [ ] **步骤 3：实现字段和迁移**

在 `Settings` 中加入：

```python
SCHEMA_VERSION: ClassVar[int] = 28
lan_firewall_dismissed_public_networks: tuple[str, ...] = ()
```

在 `from_dict()` 中将输入归一化为去重后的非空字符串元组，并只保留最后 20 项。在 `SettingsManager._migrate()` 中加入明确的 27 → 28 迁移：

```python
if version == 27:
    migrated.setdefault("lan_firewall_dismissed_public_networks", [])
    migrated["schema_version"] = Settings.SCHEMA_VERSION
```

- [ ] **步骤 4：重新运行设置测试**

运行相同命令，预期全部通过。

## 任务 2：实现可独立测试的 Windows 检测与修复后端

**文件：**

- 新增：`src/petnest/core/windows_lan_firewall.py`
- 新增：`tests/test_windows_lan_firewall.py`

- [ ] **步骤 1：先写状态判定测试**

定义不可变状态，并先测试其边界：

```python
@dataclass(frozen=True, slots=True)
class LanFirewallStatus:
    applicable: bool = False
    public_network_active: bool = False
    public_network_key: str | None = None
    firewall_enabled: bool = False
    udp_allowed: bool = False
    tcp_allowed: bool = False
    can_repair: bool = False
    error: str | None = None

    @property
    def requires_attention(self) -> bool:
        return (
            self.applicable
            and self.public_network_active
            and self.firewall_enabled
            and not (self.udp_allowed and self.tcp_allowed)
            and self.error is None
        )
```

测试矩阵至少包含：非 Windows、不在公用网络、防火墙关闭、两条规则完整、仅 UDP 完整、仅 TCP 完整、查询失败。只有“公用网络 + 防火墙开启 + 任一规则缺失 + 无查询错误”返回 `True`。

- [ ] **步骤 2：写检测命令解析测试并确认失败**

使用注入的 `subprocess.run` 假对象返回 JSON，不匹配本地化文字。JSON 固定为：

```json
{
  "publicNetworks": ["NetworkProfile:7"],
  "firewallEnabled": true,
  "udpAllowed": true,
  "tcpAllowed": false
}
```

测试：

- 网络身份排序后再做 SHA-256，返回值不含原始网络名称。
- `program` 必须等于规范化后的当前 `sys.executable`。
- 规则必须同时匹配启用状态、入站、允许、Public profile、协议、18487 本地端口和程序路径。
- PowerShell 超时、非零退出、空输出、非法 JSON都返回含 `error` 的状态，不抛到 UI 线程。
- 非 Windows 直接返回 `applicable=False`，不启动子进程。

运行：

```text
python -m pytest tests/test_windows_lan_firewall.py -q
```

预期：模块尚不存在，测试收集失败。

- [ ] **步骤 3：实现检测后端**

实现：

```python
class WindowsLanFirewallBackend:
    def __init__(
        self,
        *,
        executable: Path | None = None,
        platform: str | None = None,
        frozen: bool | None = None,
        command_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ) -> None: ...

    def inspect(self) -> LanFirewallStatus: ...
    def repair(self) -> FirewallRepairResult: ...
```

PowerShell 脚本使用 `Get-NetConnectionProfile`、`Get-NetFirewallProfile` 和 `Get-NetFirewallRule`/关联过滤器，在脚本内部算出布尔值后通过 `ConvertTo-Json -Compress` 输出。Python 仅解析固定字段，命令使用参数列表、`shell=False`、隐藏窗口、8 秒超时。

公用网络指纹只由排序后的连接配置身份构造并散列，不写入 SSID、接口名称或 IP。未打包运行时 `can_repair=False`，仍可用于诊断，但不允许提升权限修复。

- [ ] **步骤 4：先写规则修复测试**

测试 `configure_public_firewall_rules()` 只接受明确的可执行文件路径，并依次：

1. 删除 PetNest UDP/TCP 旧规则；删除不存在允许成功。
2. 添加程序范围的 UDP 18487 入站允许规则。
3. 添加程序范围的 TCP 18487 入站允许规则。
4. 两条新规则的 profile 都是 `private,public`。

测试任一步失败时返回非零结果且保留可读错误；参数中含空格的安装路径保持为单个 argv 项，不使用字符串拼接或 `shell=True`。

- [ ] **步骤 5：实现规则修复和 UAC 启动**

实现固定入口：

```python
FIREWALL_HELPER_ARGUMENT = "--configure-lan-firewall-public"


def configure_public_firewall_rules(executable: Path, *, command_runner=...) -> int:
    ...


def run_elevated_firewall_helper(executable: Path) -> FirewallRepairResult:
    ...
```

`run_elevated_firewall_helper()` 使用 `ShellExecuteExW` 的 `runas` verb 启动当前已打包的 PetNest.exe，只传固定隐藏参数，等待子进程并读取退出码。用户取消 UAC（错误码 1223）返回 `cancelled=True`；其他启动失败、子进程失败分别提供中文消息。始终关闭进程句柄。

- [ ] **步骤 6：运行后端测试**

运行：

```text
python -m pytest tests/test_windows_lan_firewall.py -q
```

预期：全部通过，测试期间没有真实 PowerShell、netsh 或 UAC 调用。

## 任务 3：增加已打包程序的隐藏修复入口

**文件：**

- 修改：`src/petnest/__main__.py`
- 修改：`tests/test_main.py`

- [ ] **步骤 1：先写命令行入口测试**

覆盖：

- 解析器接受但帮助文本不展示 `--configure-lan-firewall-public`。
- 该参数在创建 `QApplication`、单实例锁和主窗口之前被处理。
- 非 Windows 返回非零。
- 非 frozen 环境返回非零，避免开发源码意外修改系统防火墙。
- Windows frozen 环境把 `Path(sys.executable)` 传给 `configure_public_firewall_rules()` 并原样返回退出码。

- [ ] **步骤 2：运行测试确认失败**

运行：

```text
python -m pytest tests/test_main.py -q
```

预期：解析器拒绝新参数或未调用修复函数。

- [ ] **步骤 3：实现隐藏入口**

使用 `argparse.SUPPRESS` 隐藏参数；在 GUI 初始化之前处理：

```python
if args.configure_lan_firewall_public:
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return 2
    return configure_public_firewall_rules(Path(sys.executable))
```

- [ ] **步骤 4：运行主入口测试**

运行相同命令，预期全部通过。

## 任务 4：异步协调检测、网络变化和修复

**文件：**

- 新增：`src/petnest/core/lan_firewall_advisor.py`
- 新增：`tests/test_lan_firewall_advisor.py`

- [ ] **步骤 1：先写协调器行为测试**

使用可控假后端和 Qt 事件循环，覆盖：

- `start(enabled=True)` 在 5 秒启动延迟后请求一次检测。
- `enabled=False` 不检测并发布不适用状态。
- 连续多个网络变化通知被 1 秒防抖合并成一次检测。
- 检测运行期间再次请求只记录一次待处理检查，不并发启动多个 PowerShell。
- `request_repair()` 在工作线程调用后端，UAC 取消发布失败消息但协调器继续可用。
- 修复成功后必须重新检测，只有复检确认两条规则完整才发布无警告状态。
- `stop()` 停止计时器，并忽略迟到的工作线程结果。

- [ ] **步骤 2：运行测试确认失败**

运行：

```text
python -m pytest tests/test_lan_firewall_advisor.py -q
```

预期：模块尚不存在，测试收集失败。

- [ ] **步骤 3：实现 Qt 协调器**

接口固定为：

```python
class LanFirewallAdvisorCoordinator(QObject):
    status_changed = Signal(object)
    repair_finished = Signal(bool, str)

    def start(self, *, enabled: bool) -> None: ...
    def set_enabled(self, enabled: bool) -> None: ...
    def request_check(self) -> None: ...
    def request_repair(self) -> None: ...
    def stop(self) -> None: ...

    @property
    def status(self) -> LanFirewallStatus: ...
```

检测与 UAC 等待都放到 Python 工作线程；线程只写 `Queue`，由 100ms `QTimer` 在 Qt 主线程排空并发信号。协调器最多保留一个检测工作线程和一个 pending 标记。

Windows 上若 `QNetworkInformation.instance()` 可用，连接 `reachabilityChanged` 和 transport medium 变化信号并防抖检查；不可用时只做启动检查和设置变化检查，不因此报错。其他平台使用同一后端返回不适用状态。

- [ ] **步骤 4：运行协调器测试**

运行相同命令，预期全部通过。

## 任务 5：实现桌宠旁常驻提示气泡

**文件：**

- 新增：`src/petnest/ui/lan_firewall_notice.py`
- 修改：`src/petnest/ui/pet_window.py`
- 修改：`tests/test_pet_window.py`

- [ ] **步骤 1：先写 UI 测试**

测试：

- 气泡是无焦点、置顶、非模态窗口，不抢走当前输入焦点。
- `show_notice()` 后不会启动自动关闭计时器。
- 点击正文发出 `activated` 并隐藏。
- 点击右上角关闭按钮只发出 `dismissed` 并隐藏，不发出 `activated`。
- 重复显示不会创建多个窗口。
- 宠物移动时重新定位；靠近屏幕右/下边缘时完整夹在可用屏幕区域内。
- `PetWindow.closeEvent()` 清理气泡。

- [ ] **步骤 2：运行测试确认失败**

运行：

```text
python -m pytest tests/test_pet_window.py -q
```

预期：新气泡属性和信号不存在。

- [ ] **步骤 3：实现气泡组件**

参考已有 `CodexStatusBubble` 的窗口标志和定位方式，但不复用其自动消失定时器。固定文案：

```text
局域网设备可能连不上
当前是公用网络，点击检查防火墙设置
```

气泡使用橙色边框和浅橙背景，正文整块可点击，右上角 `×` 有独立命中区域。公开接口：

```python
class LanFirewallNoticeBubble(QWidget):
    activated = Signal()
    dismissed = Signal()

    def show_notice(self, anchor_rect: QRect, *, avoid_rect: QRect | None = None) -> None: ...
    def reposition(self, anchor_rect: QRect, *, avoid_rect: QRect | None = None) -> None: ...
    def clear(self) -> None: ...
```

- [ ] **步骤 4：接入 PetWindow**

在 `PetWindow` 增加 `lan_firewall_notice_activated`、`lan_firewall_notice_dismissed` 信号以及 `show_lan_firewall_notice()`、`clear_lan_firewall_notice()` 方法。`moveEvent()` 负责重定位，`closeEvent()` 负责清理。

- [ ] **步骤 5：运行窗口测试**

运行相同命令，预期全部通过。

## 任务 6：互动窗口增加固定警告条和修复按钮

**文件：**

- 修改：`src/petnest/ui/lan_interaction_dialog.py`
- 修改：`tests/test_lan_interactions.py`

- [ ] **步骤 1：先写互动窗口测试**

为 `LanInteractionDialog` 增加可注入的防火墙状态和回调，覆盖：

- 无警告时警告条隐藏，原布局与键盘导航不变。
- 有警告时顶部显示“公用网络防火墙尚未放行，部分设备可能无法连接”和“一键允许”。
- 点击按钮后立即禁用并显示“处理中…”，防止重复启动 UAC。
- 修复成功并复检通过后警告条隐藏。
- UAC 取消、修复失败或复检仍缺规则时恢复按钮，警告条不消失，并显示可重试消息。
- `can_repair=False` 时显示诊断文案但不显示可用按钮。

- [ ] **步骤 2：运行测试确认失败**

运行：

```text
python -m pytest tests/test_lan_interactions.py -q
```

预期：构造参数和警告条接口不存在。

- [ ] **步骤 3：实现警告条**

将对话框根布局改成外层 `QVBoxLayout`：警告条在上，原来的左右两栏 `QHBoxLayout` 在下。构造参数增加：

```python
firewall_status: LanFirewallStatus | None = None,
on_allow_public_firewall: Callable[[], None] | None = None,
```

公开更新接口：

```python
def set_firewall_status(
    self,
    status: LanFirewallStatus,
    *,
    repair_message: str = "",
    repairing: bool = False,
) -> None: ...
```

按钮只调用回调，不直接执行系统命令。确保警告条高度不会覆盖原内容，窗口最小尺寸仍能容纳按钮。

- [ ] **步骤 4：运行互动窗口测试**

运行相同命令，预期全部通过。

## 任务 7：应用层完整接线并在修复后刷新局域网

**文件：**

- 修改：`src/petnest/core/lan_service.py`
- 修改：`src/petnest/app.py`
- 修改：`tests/test_lan_service.py`
- 修改：`tests/test_app_and_platforms.py`

- [ ] **步骤 1：先写 LAN 刷新公开接口测试**

增加：

```python
def test_refresh_connections_discovers_and_probes_saved_peers(...) -> None:
    service.refresh_connections()
    assert discover_calls == 1
    assert saved_peer_probe_calls == 1


def test_refresh_connections_is_noop_when_stopped(...) -> None:
    service.refresh_connections()
    assert discover_calls == 0
```

运行：

```text
python -m pytest tests/test_lan_service.py -q
```

预期：`refresh_connections()` 不存在。

- [ ] **步骤 2：实现刷新接口并通过测试**

在 `LanInteractionService` 增加公开方法，运行中依次广播发现和探测已保存好友；复用现有私有实现，不复制连接逻辑。

- [ ] **步骤 3：先写应用接线测试**

向 `PetNest.__init__()` 注入可选 `lan_firewall_advisor` 假对象，覆盖：

- `start()` 按 `lan_interaction_enabled` 启动协调器。
- 设置关闭局域网互动后清除气泡、隐藏互动窗口警告并停止主动检查。
- 需要关注且网络指纹未被关闭时显示气泡。
- 同一网络指纹已关闭时不再显示气泡，但打开互动窗口仍显示警告条。
- 点击气泡正文打开互动窗口；点击 `×` 只保存当前网络指纹，不打开窗口。
- 切换到不同公用网络指纹时再次显示。
- 修复按钮调用协调器一次；修复中重复点击无效。
- 修复成功但复检未通过时不清除警告。
- 复检确认两条规则完整时清除气泡/警告，并调用一次 `lan_service.refresh_connections()`。
- app shutdown 调用协调器 `stop()`，迟到结果不更新已销毁 UI。
- `sys.platform == "darwin"` 和 Linux 状态不适用，不创建提示、不显示 Windows 文案。

- [ ] **步骤 4：运行应用测试确认失败**

运行：

```text
python -m pytest tests/test_app_and_platforms.py -q
```

预期：构造注入点和事件处理不存在。

- [ ] **步骤 5：实现应用接线**

在 `PetNest` 中：

1. 构造协调器并缓存最近的 `LanFirewallStatus`。
2. 连接窗口气泡的正文点击和关闭信号。
3. `start()` 在窗口显示后启动协调器；协调器内部负责 5 秒延迟。
4. `apply_settings()` 在 LAN 开关变化时调用 `set_enabled()`。
5. 状态需要关注且未关闭时显示气泡；否则清除气泡。
6. 关闭气泡时只把当前非空网络指纹追加到设置，去重并限制 20 项，然后保存。
7. `show_lan_interaction_dialog()` 无论气泡是否被关闭，都传入最新状态；在对话框存活期间把状态/修复结果同步给警告条，关闭后断开连接。
8. 修复成功后等待后端复检；仅当 `requires_attention` 从真变假且规则完整时刷新局域网连接。
9. `shutdown()` 停止协调器。

不要把 IP、SSID、接口名或原始网络身份写入设置和日志。错误日志只记录操作阶段与异常类别。

- [ ] **步骤 6：运行应用和 LAN 测试**

运行：

```text
python -m pytest tests/test_lan_service.py tests/test_app_and_platforms.py -q
```

预期：全部通过。

## 任务 8：安装器回归、文档和完整验证

**文件：**

- 修改：`README.md`
- 视测试需要修改：`tests/test_installer_firewall.py`
- 已有规格：`docs/superpowers/specs/2026-08-25-windows-public-network-firewall-advisor-design.md`
- 本计划：`docs/superpowers/plans/2026-08-25-windows-public-network-firewall-advisor.md`

- [ ] **步骤 1：锁定安装器现有默认行为**

确保 `tests/test_installer_firewall.py` 明确断言：

- “允许在公用网络中使用局域网互动”默认不勾选。
- 未勾选时安装规则 profile 为 private。
- 勾选时安装规则 profile 为 private,public。
- TCP 与 UDP 18487 都使用程序路径约束。

运行：

```text
python -m pytest tests/test_installer_firewall.py -q
```

预期：全部通过；不修改安装器默认勾选状态。

- [ ] **步骤 2：更新 README**

用简短文字说明：Windows 安装默认只放行专用网络；用户在公用网络开启局域网互动且规则不完整时，PetNest 会显示常驻提醒；“一键允许”会触发一次系统管理员确认并只为当前 PetNest.exe 放行 TCP/UDP 18487；macOS 不显示这条 Windows 专属提醒。

- [ ] **步骤 3：运行定向测试组**

```text
python -m pytest tests/test_settings_manager.py tests/test_windows_lan_firewall.py tests/test_main.py tests/test_lan_firewall_advisor.py tests/test_pet_window.py tests/test_lan_interactions.py tests/test_lan_service.py tests/test_app_and_platforms.py tests/test_installer_firewall.py -q
```

预期：全部通过。

- [ ] **步骤 4：运行静态检查和完整测试**

先根据 `pyproject.toml` 中已有工具运行项目既有静态检查；不得临时引入新的检查器。然后运行：

```text
python -m pytest -q
```

预期：完整测试通过。若存在与本次改动无关的既有失败，记录精确测试名与失败证据；本次新增和受影响测试必须全部通过。

- [ ] **步骤 5：做 Windows 安装包烟雾验证**

在不改变真实规则的测试环境先完成自动化验证；若本机已有可用构建链，再构建安装包并手动验证：

1. 专用网络且规则完整：不显示提示。
2. 公用网络且规则缺失：启动约 5 秒后显示气泡，持续存在。
3. 点击 `×`：当前网络本次及以后不再弹气泡，互动窗口警告仍在。
4. 点击正文：气泡关闭并打开互动窗口。
5. 点击“一键允许”：出现一次 UAC；取消后可重试。
6. 同意后：TCP/UDP 规则均为当前安装路径、profile 为 private,public；复检通过后警告消失并立即重新发现好友。

如果无法安全隔离真实防火墙环境，不执行会改动真实规则的人工步骤，只报告自动化结果与待人工验证项。

- [ ] **步骤 6：检查改动范围并整理成一个提交**

先运行：

```text
git status --short
git diff --check
git diff --name-only 93501ef^
```

只暂存本计划列出的文件；保留工作区中用户原有的其他已修改/未跟踪文件。确认 `93501ef` 之后没有混入用户的新提交，再使用非破坏性的 soft reset 将规格提交展开：

```text
git reset --soft 93501ef^
```

重新核对暂存区，只提交本功能文件：

```text
git commit -m "feat: 添加公用网络防火墙提醒"
```

最后运行：

```text
git status --short
git log -3 --oneline
```

预期：规格、计划、实现和测试只形成一个新提交；用户原有的无关工作区改动保持原样。

## 自检清单

- [ ] 需求覆盖：常驻气泡、正文点击、独立关闭按钮、互动窗口固定警告、一键 UAC 修复均有任务和测试。
- [ ] 平台边界：仅 Windows 生效，macOS/Linux 明确不显示。
- [ ] 网络边界：同一公用网络关闭后不再弹；不同公用网络重新提示；不保存原始网络身份。
- [ ] 防火墙边界：防火墙关闭不提示；TCP/UDP 任一缺失都提示；路径、端口、方向、动作、启用状态和 profile 必须全部匹配。
- [ ] 权限边界：开发模式不能修复；UAC 取消不被视为成功；无 shell 字符串拼接。
- [ ] 并发边界：检测不阻塞 UI，不并发重复检测；退出后不处理迟到结果。
- [ ] 成功判定：提升进程退出码为零仍需复检，两条规则都正确才清除警告。
- [ ] 发现恢复：修复确认后立即广播发现并探测已保存好友。
- [ ] 提交边界：不单独提交 Markdown，最终只有一个功能提交，其他用户文件不纳入。
