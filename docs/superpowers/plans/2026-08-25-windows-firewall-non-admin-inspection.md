# Windows 防火墙普通权限检测修复实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 让普通权限运行的 PetNest 准确识别已经放行到 Public 的 TCP/UDP 18487 规则，使“一键允许”后的警告立即消失并在重启后保持正确。

**架构：** 保留当前 PowerShell JSON 检查边界、网络摘要和防火墙配置文件查询，只把规则枚举从需要更高读取权限的 `Get-NetFirewallRule` cmdlet 改为 Windows 内置的 `HNetCfg.FwPolicy2` COM 接口。规则仍按名称、启用状态、方向、动作、Public 位、协议、端口和可执行文件路径严格匹配；COM 读取异常沿用现有后端错误状态。

**技术栈：** Python 3.12、PowerShell 5.1、Windows Firewall COM API、pytest。

---

## 文件结构

- 修改 `tests/test_windows_lan_firewall.py`：添加普通权限 COM 规则检查的结构回归测试，并锁定所有安全匹配条件。
- 修改 `src/petnest/core/windows_lan_firewall.py`：在现有检查脚本中使用 `HNetCfg.FwPolicy2` 枚举和验证规则。
- 新增 `docs/superpowers/plans/2026-08-25-windows-firewall-non-admin-inspection.md`：记录本实现步骤，与代码改动一起提交。

### 任务 1：锁定普通权限规则读取方式

**文件：**

- 修改：`tests/test_windows_lan_firewall.py:31-81`

- [ ] **步骤 1：编写失败的脚本结构回归测试**

在 `test_inspect_parses_json_and_hashes_sorted_network_identities` 取得 `command` 后，保留原有断言并添加：

```python
    script = command[-1]
    assert "HNetCfg.FwPolicy2" in script
    assert "$firewallRules" in script
    assert "Get-NetFirewallRule" not in script
    assert "Get-NetFirewallPortFilter" not in script
    assert "Get-NetFirewallApplicationFilter" not in script
```

新增独立测试，锁定规则的全部严格匹配条件：

```python
def test_inspection_script_strictly_matches_public_petnest_rules(tmp_path: Path) -> None:
    captured: list[list[str]] = []

    def runner(command: list[str], **_kwargs):
        captured.append(command)
        return subprocess.CompletedProcess(
            command,
            0,
            json.dumps(
                {
                    "publicNetworks": [],
                    "firewallEnabled": True,
                    "udpAllowed": False,
                    "tcpAllowed": False,
                    "policyManaged": False,
                }
            ),
            "",
        )

    executable = tmp_path / "PetNest.exe"
    WindowsLanFirewallBackend(
        executable=executable,
        platform="win32",
        frozen=True,
        command_runner=runner,
    ).inspect()

    script = captured[0][-1]
    for fragment in (
        ".Name -ne $displayName",
        ".Enabled",
        ".Direction -ne 1",
        ".Action -ne 1",
        ".Profiles -band 4",
        ".Protocol -ne $protocol",
        ".LocalPorts)",
        ".ApplicationName",
        "OrdinalIgnoreCase",
        "Test-PetNestRule 'PetNest LAN UDP 18487' 17",
        "Test-PetNestRule 'PetNest LAN TCP 18487' 6",
    ):
        assert fragment in script
```

- [ ] **步骤 2：运行测试并确认按预期失败**

运行：

```text
python -m pytest tests/test_windows_lan_firewall.py -q
```

预期：COM 相关断言失败，并显示当前脚本仍包含 `Get-NetFirewallRule`。

### 任务 2：改用 Windows Firewall COM 规则集合

**文件：**

- 修改：`src/petnest/core/windows_lan_firewall.py:136-164`
- 测试：`tests/test_windows_lan_firewall.py`

- [ ] **步骤 1：替换 PowerShell 规则枚举实现**

在读取 Public 防火墙配置文件后创建 COM 对象和规则快照：

```powershell
$firewallPolicy = New-Object -ComObject HNetCfg.FwPolicy2
$firewallRules = @($firewallPolicy.Rules)
```

用下列函数替换现有 `Get-NetFirewallRule`、端口筛选器和应用筛选器逻辑：

```powershell
function Test-PetNestRule([string]$displayName, [int]$protocol) {
    foreach ($rule in $firewallRules) {
        if ($rule.Name -ne $displayName) { continue }
        if (-not [bool]$rule.Enabled -or [int]$rule.Direction -ne 1 -or [int]$rule.Action -ne 1) {
            continue
        }
        if (([int]$rule.Profiles -band 4) -eq 0) { continue }
        if ([int]$rule.Protocol -ne $protocol) { continue }
        if ("$($rule.LocalPorts)" -ne '18487') { continue }
        if (-not [string]::Equals(
            $rule.ApplicationName,
            $program,
            [System.StringComparison]::OrdinalIgnoreCase
        )) { continue }
        return $true
    }
    return $false
}
```

更新 JSON 载荷调用：

```powershell
udpAllowed = [bool](Test-PetNestRule 'PetNest LAN UDP 18487' 17)
tcpAllowed = [bool](Test-PetNestRule 'PetNest LAN TCP 18487' 6)
```

保留 `$ErrorActionPreference = 'Stop'`。COM 创建或枚举失败会让命令返回非零状态，Python 侧现有异常处理将生成带 `error` 的状态，不会误报规则缺失。

- [ ] **步骤 2：运行定向测试确认通过**

运行：

```text
python -m pytest tests/test_windows_lan_firewall.py tests/test_lan_firewall_advisor.py tests/test_lan_interactions.py -q
```

预期：全部通过；现有 UAC、修复后重新检查和界面状态测试无回归。

- [ ] **步骤 3：运行实机普通权限检查**

通过一个不提交的临时 Python 探针，用安装路径实例化后端：

```python
from pathlib import Path
from petnest.core.windows_lan_firewall import WindowsLanFirewallBackend

print(
    WindowsLanFirewallBackend(
        executable=Path(r"D:\installed\PetNest\PetNest.exe"),
        platform="win32",
        frozen=True,
    ).inspect()
)
```

预期：当前实机状态包含 `udp_allowed=True`、`tcp_allowed=True`、`error=None`。

- [ ] **步骤 4：提交测试、实现和计划**

```text
git add src/petnest/core/windows_lan_firewall.py tests/test_windows_lan_firewall.py docs/superpowers/plans/2026-08-25-windows-firewall-non-admin-inspection.md
git commit -m fix:修复普通权限防火墙规则误报
```

### 任务 3：完整验证、合并和安装确认

**文件：**

- 验证：`src/petnest/core/windows_lan_firewall.py`
- 验证：`tests/test_windows_lan_firewall.py`

- [ ] **步骤 1：运行完整验证**

```text
python -m compileall -q src
python -m pytest -q
git diff --check
git status --short
```

预期：完整测试通过；只保留当前 Windows 主机不支持无管理员符号链接的既有跳过项；工作树无未提交变更。

- [ ] **步骤 2：把功能分支整合到最新 main**

先检查 `main` 是否在本任务期间前进。如果前进，将功能分支变基到最新 `main` 并重新运行定向测试；然后从主工作区执行快进合并。不得覆盖主工作区已有的其他任务修改。

- [ ] **步骤 3：在合并后的 main 重新验证并打包**

停止已确认路径为 `D:\installed\PetNest\PetNest.exe` 的运行实例，运行完整测试和：

```text
build_windows.bat
```

预期生成：

```text
dist\installer\PetNest-Setup-0.1.7.exe
```

- [ ] **步骤 4：覆盖安装并验证**

静默安装到 `D:\installed\PetNest`，确认安装日志成功，并确认：

- `dist\PetNest\PetNest.exe` 与已安装 EXE 哈希相同。
- 普通权限后端检查得到 UDP/TCP 均允许。
- 启动后 TCP/UDP 18487 正常监听。
- 打开互动窗口时不再显示防火墙警告。

- [ ] **步骤 5：清理隔离工作树**

确认功能工作树干净且提交已在 `main` 历史中后，删除 `firewall-inspection-com-fallback` 工作树和临时分支；保留其他任务的工作树与主工作区修改。
