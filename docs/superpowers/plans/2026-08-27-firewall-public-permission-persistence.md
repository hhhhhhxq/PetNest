# 公用网络防火墙授权持久化实现计划

> **面向 AI 代理的工作者：** 按 TDD 顺序执行；步骤使用复选框（`- [ ]`）跟踪。

**目标：** 保留用户对公用网络局域网互动的明确授权，避免升级或重装后重复警告。

**架构：** 安装器与提升后的应用辅助入口共享一个 HKLM 32 位视图 DWORD 偏好。安装器以偏好或精确旧规则迁移结果初始化选择，并在旧规则成功清理、新规则成功创建后写回；卸载删除。

**技术栈：** Inno Setup Pascal Script、Python `winreg`、pytest。

---

### 任务 1：锁定安装器行为

**文件：**
- 修改：`tests/test_installer_firewall.py`
- 修改：`installer/PetNest.iss`

- [x] 添加失败断言，要求安装器查询机器级 Public 偏好、无值时迁移精确旧规则、用结果初始化 `FirewallPage`、删除失败即停止、配置成功后写回，并在卸载时删除。
- [x] 运行 `.venv\Scripts\python.exe -m pytest tests\test_installer_firewall.py -q`，确认断言因功能缺失失败。
- [x] 在 Inno Setup 脚本中实现 HKLM 32 位视图 DWORD 读取、写入和卸载清理。
- [x] 重新运行测试并确认通过。

### 任务 2：锁定应用内授权行为

**文件：**
- 修改：`tests/test_windows_lan_firewall.py`
- 修改：`src/petnest/core/windows_lan_firewall.py`

- [x] 添加失败测试：提升权限辅助入口成功创建两条规则时写入机器级 Public 偏好；删除或新增失败、UAC 取消时不写入。
- [x] 运行 `.venv\Scripts\python.exe -m pytest tests\test_windows_lan_firewall.py -q`，确认失败原因正确。
- [x] 实现机器级 32 位注册表偏好写入，并在修复成功路径调用。
- [x] 重新运行测试并确认通过。

### 任务 3：验证安装包与实机状态

**文件：**
- 验证：`installer/PetNest.iss`
- 验证：`src/petnest/core/windows_lan_firewall.py`

- [x] 运行防火墙、安装器和入口相关测试。
- [x] 运行 `build_windows.bat` 生成 0.1.7 安装包。
- [ ] 覆盖安装并通过一次明确授权把当前规则设为 Private,Public。
- [ ] 再次静默重装，确认规则仍为 Private,Public，应用检查不再需要提醒。
- [ ] 检查差异并将规格、计划、实现和测试整理为一个 `fix: ...` 中文提交。
