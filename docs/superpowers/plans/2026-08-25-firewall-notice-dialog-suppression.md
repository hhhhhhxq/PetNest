# 互动窗口抑制防火墙气泡实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 点击防火墙气泡进入互动窗口后，窗口存活期间不重复显示气泡；窗口关闭且问题仍存在时恢复提醒。

**架构：** 应用层以 `_lan_interaction_dialog` 是否存在作为气泡抑制状态。防火墙状态仍实时更新互动窗口警告条，但统一的 `_refresh_lan_firewall_notice()` 只在互动窗口不存在时显示桌宠旁气泡。

**技术栈：** Python 3.12、PySide6、pytest。

---

## 文件结构

- 修改 `src/petnest/app.py`：集中计算防火墙气泡可见性，并协调互动窗口的打开、复检和关闭。
- 修改 `tests/test_app_and_platforms.py`：覆盖真实的气泡正文点击、窗口内复检和窗口关闭恢复链路。
- 修改 `docs/superpowers/specs/2026-08-25-windows-public-network-firewall-advisor-design.md`：记录已确认的交互状态规则。

### 任务 1：锁定互动窗口期间的气泡状态

**文件：**

- 修改：`tests/test_app_and_platforms.py`

- [ ] **步骤 1：编写失败的应用级回归测试**

在现有防火墙应用测试附近添加：

```python
def test_firewall_notice_stays_hidden_while_interaction_dialog_is_open(
    qtbot: pytest.QtBot,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    advisor = _LanFirewallAdvisor()
    application = PetNest(
        pets_root=tmp_path / "pets",
        settings_manager=SettingsManager(tmp_path / "settings.json"),
        lan_firewall_advisor=advisor,
        enable_tray=False,
    )
    qtbot.addWidget(application.window)
    application.window.show()
    warning = LanFirewallStatus(
        applicable=True,
        public_network_active=True,
        public_network_key="network-a",
        firewall_enabled=True,
        udp_allowed=False,
        tcp_allowed=True,
        can_repair=True,
    )
    states_while_open: list[bool] = []

    def exec_dialog(_dialog: object) -> int:
        advisor.status_changed.emit(warning)
        states_while_open.append(application.window.lan_firewall_notice.isVisible())
        return 0

    monkeypatch.setattr("petnest.app.LanInteractionDialog.exec", exec_dialog)
    advisor.status_changed.emit(warning)
    application.window.lan_firewall_notice._activate()

    assert states_while_open == [False]
    assert application.window.lan_firewall_notice.isVisible()
    application.shutdown()
```

- [ ] **步骤 2：运行测试并确认按预期失败**

运行：

```text
python -m pytest tests/test_app_and_platforms.py -q -k firewall_notice_stays_hidden
```

预期：`states_while_open` 实际为 `[True]`，证明互动窗口内的重复状态发布重新显示了气泡。

### 任务 2：集中气泡可见性并协调互动窗口生命周期

**文件：**

- 修改：`src/petnest/app.py`

- [ ] **步骤 1：提取气泡刷新方法**

把 `_handle_lan_firewall_status()` 中现有的显示判断移动到：

```python
def _refresh_lan_firewall_notice(self) -> None:
    status = self._lan_firewall_status
    dismissed = self.settings.lan_firewall_dismissed_public_networks
    should_show = (
        self.settings.lan_interaction_enabled
        and status.requires_attention
        and status.public_network_key not in dismissed
        and self._lan_interaction_dialog is None
    )
    if should_show:
        self.window.show_lan_firewall_notice()
    else:
        self.window.clear_lan_firewall_notice()
```

`_handle_lan_firewall_status()` 在更新互动窗口警告条后调用该方法。

- [ ] **步骤 2：调整互动窗口的复检顺序和关闭恢复**

在 `show_lan_interaction_dialog()` 中先构造对话框并设置 `self._lan_interaction_dialog = dialog`，然后：

```python
self.window.clear_lan_firewall_notice()
self.lan_firewall_advisor.request_check()
dialog.exec()
self._lan_interaction_dialog = None
self._refresh_lan_firewall_notice()
```

必须删除方法入口处原有的 `request_check()`，确保同步或异步返回的复检结果都发生在 `_lan_interaction_dialog` 已设置之后。其余信号连接、断开和设置保存顺序保持不变。

- [ ] **步骤 3：运行定向测试确认通过**

运行：

```text
python -m pytest tests/test_app_and_platforms.py tests/test_pet_window.py -q
```

预期：全部通过；正文点击、右上角关闭记忆、修复成功清除提醒均不回归。

### 任务 3：完整验证、提交和安装烟雾测试

**文件：**

- 修改：`docs/superpowers/specs/2026-08-25-windows-public-network-firewall-advisor-design.md`
- 新增：`docs/superpowers/plans/2026-08-25-firewall-notice-dialog-suppression.md`

- [ ] **步骤 1：运行静态和完整验证**

```text
python -m compileall -q src
python -m pytest -q
git diff --check
```

预期：完整测试通过；仅保留 Windows 无符号链接权限导致的既有跳过项。

- [ ] **步骤 2：把文档、实现和测试合为一个提交**

```text
git add docs/superpowers/specs/2026-08-25-windows-public-network-firewall-advisor-design.md docs/superpowers/plans/2026-08-25-firewall-notice-dialog-suppression.md src/petnest/app.py tests/test_app_and_platforms.py
git commit -m fix:防止互动窗口重复显示防火墙气泡
```

- [ ] **步骤 3：合并回 `main` 并重新打包安装**

合并后重新运行完整测试和 `build_windows.bat`，安装到 `D:\installed\PetNest`。在 Public 防火墙开启且规则仅为 Private 的状态下，确认点击正文后互动窗口内只保留顶部警告，关闭互动窗口后气泡恢复。
