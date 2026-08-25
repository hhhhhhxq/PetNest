# 跨平台自动启动实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 `superpowers:executing-plans` 在当前隔离工作树中逐项执行；每个生产行为都先运行对应失败测试。

**目标：** 用一个“自动启动”开关在 Windows 和 macOS 上登记当前用户登录启动，并在 Windows 上提供一分钟间隔、最多三次的异常恢复。

**架构：** 平台层以 `StartupRegistrationResult` 统一表达成功、等待 macOS 用户批准和失败。Windows 使用任务计划程序触发隐藏的 `PetNestStartupHost.exe`，由宿主等待 PetNest 并执行有界重试；macOS 13+ 使用 `SMAppService.mainAppService`。设置中心只根据平台能力决定是否显示开关，应用层负责失败回退和启动时静默修复。

**技术栈：** Python 3.12、PySide6、Windows Task Scheduler XML、`schtasks.exe`、Apple Service Management、PyObjC、PyInstaller、Inno Setup、pytest、pytest-qt。

---

## 启动宿主增量文件结构

- 创建 `src/petnest_startup_host.py`：仅依赖标准库，监督 PetNest 子进程并写本地诊断日志。
- 创建 `tests/test_startup_host.py`：覆盖正常退出、异常重试、三次上限、创建进程失败和默认同目录路径。
- 修改 `src/petnest/platforms/windows_startup.py`：任务动作改为启动宿主，任务 XML 不再声明系统级失败重试。
- 修改 `tests/test_windows_startup.py`：锁定宿主动作、无叠加重试和宿主缺失诊断。
- 修改 `build_windows.bat`：生成无窗口单文件 `PetNestStartupHost.exe`。
- 修改 `installer/PetNest.iss`：把启动宿主安装到 `{app}`。
- 修改 `tests/test_installer_script.py`：检查启动宿主构建和安装声明。

## 启动宿主增量任务

### 任务 1：启动宿主监督循环

- [x] **步骤 1：编写失败测试**

  在 `tests/test_startup_host.py` 中通过注入 runner 和 sleeper 断言：返回 `0` 时只启动一次；连续非零时共启动四次、等待三次且每次 60 秒；第二次成功时停止；`OSError` 也计入失败尝试。

- [x] **步骤 2：验证红灯**

  ```powershell
  python -m pytest tests/test_startup_host.py -q
  ```

  预期：收集阶段因 `petnest_startup_host` 尚不存在而失败。

- [x] **步骤 3：最少实现**

  创建 `run_supervisor(app_path=None, runner=subprocess.run, sleeper=time.sleep, retry_delay_seconds=60, max_restarts=3, logger=None)`；默认从 `sys.executable` 的同目录定位 `PetNest.exe`，每次以 `[PetNest.exe, "--startup"]` 和安装目录作为工作目录启动。

- [x] **步骤 4：验证绿灯**

  ```powershell
  python -m pytest tests/test_startup_host.py -q
  ```

  预期：全部通过。

### 任务 2：任务动作切换到启动宿主

- [x] **步骤 1：编写失败测试**

  更新 `tests/test_windows_startup.py`，断言任务动作命令是同目录 `PetNestStartupHost.exe`、没有 `--startup` 参数、没有 `RestartOnFailure`；宿主文件缺失时不调用 `schtasks` 并返回可读错误。

- [x] **步骤 2：验证红灯**

  ```powershell
  python -m pytest tests/test_windows_startup.py -q
  ```

  预期：现有 XML 仍指向 `PetNest.exe --startup`，相关断言失败。

- [x] **步骤 3：最少实现并验证**

  `WindowsStartupTask` 默认把 `PetNest.exe` 的同级 `PetNestStartupHost.exe` 作为动作；开启前检查两个文件存在；保留 SID 隔离、UTF-16 临时 XML、COM 查询和卸载清理逻辑。

  ```powershell
  python -m pytest tests/test_windows_startup.py tests/test_windows_platform.py -q
  ```

  预期：全部通过。

### 任务 3：构建、安装与整体验证

- [x] **步骤 1：编写失败发布测试**

  更新 `tests/test_installer_script.py`，断言 `build_windows.bat` 生成 `PetNestStartupHost`，且 `installer/PetNest.iss` 将 `dist\PetNestStartupHost.exe` 安装到 `{app}`。

- [x] **步骤 2：验证红灯、实现并验证绿灯**

  ```powershell
  python -m pytest tests/test_installer_script.py -q
  ```

  先确认新断言失败，再添加一条 PyInstaller 构建命令和一条安装器 `[Files]` 声明，重跑至通过。

- [x] **步骤 3：完整自动化验证**

  ```powershell
  python -m compileall -q src tests
  python -m pytest -q
  git diff --check
  ```

- [x] **步骤 4：安装包实机验证**

  构建并覆盖安装后确认任务动作指向启动宿主；由任务启动 PetNest，正常托盘退出后不拉起；每次强制结束后约一分钟出现新 PID，三次重试耗尽后不再出现。核对 `startup-host.log` 的启动、退出码、重试次数和最终停止记录。

- [x] **步骤 5：保持单一提交**

  将设计、计划、实现、测试和发布配置全部暂存，使用 `git commit --amend --no-edit` 修订原功能提交。

## 实施项

- [x] 定义 `StartupRegistrationResult` 和 `startup_supported` 平台能力。
- [x] 实现 Windows 登录任务 XML，包含 `InteractiveToken`、`LeastPrivilege` 和 `IgnoreNew`。
- [x] 使用绝对系统工具、无 shell 参数列表和 UTF-16 临时 XML 创建或删除按用户 SID 隔离的任务。
- [x] 通过 Task Scheduler COM HRESULT 区分任务不存在与查询权限错误，不依赖本地化输出。
- [x] 实现 macOS 13+ `SMAppService` 延迟桥接，映射四种服务状态和 NSError 返回值。
- [x] 让 Windows 和 macOS 平台适配器委托各自的启动组件。
- [x] 在“应用与更新”页增加单一“自动启动”开关和确认文案，不支持时隐藏。
- [x] 应用设置时只在开关变化后调用平台接口；失败只回退该字段。
- [x] macOS 状态为 `requiresApproval` 时保存开启值，并指向“系统设置 → 通用 → 登录项”。
- [x] 持久化值开启时，在 Qt 事件循环开始后通过后台线程静默修复系统登记，并以版本令牌对齐并发用户修改。
- [x] 命令行入口接受隐藏的 `--startup` 参数。
- [x] 增加 Darwin 条件 PyObjC 依赖、PyInstaller 隐式导入，以及可在提升权限下清理全部 SID/旧版任务的 Windows 卸载流程。
- [x] 完成组件、平台委托、UI、应用生命周期、CLI 与发布配置的自动化测试。
- [x] 先为 `PetNestStartupHost` 编写正常退出、异常退出、三次上限和创建失败测试并确认红灯。
- [x] 实现标准库启动宿主：启动同目录 PetNest、等待退出、异常时一分钟后最多重启三次并写诊断日志。
- [x] 将 Windows 任务动作切换为 `PetNestStartupHost.exe`，删除任务级 `RestartOnFailure`，避免叠加重试。
- [x] 将启动宿主加入 PyInstaller 和 Inno Setup，并覆盖发布配置测试。
- [x] 运行相关测试和完整测试套件，确认工作树无格式问题。
- [x] 关闭或卸载时通过控制代际取消已运行宿主，并让日志初始化失败降级而不阻止 PetNest 启动。
- [x] 重新构建、覆盖安装并实机验证正常退出与三次异常恢复。
- [x] 在 Windows 安装包上实机验证任务创建、正常退出不重启以及异常退出三次恢复。
- [ ] 在 macOS 13+ 打包 `.app` 上实机验证登记、批准、注销和重新登录启动。

## 验证命令

```powershell
python -m pytest tests/test_windows_startup.py tests/test_macos_startup.py tests/test_windows_platform.py tests/test_macos_platform.py tests/test_settings_dialog.py tests/test_app_and_platforms.py tests/test_main.py tests/test_macos_build_script.py tests/test_installer_script.py tests/test_installer_firewall.py
python -m pytest
git diff --check
```

用户要求文档不单独提交；本计划、设计、实现和测试将作为一个功能提交交付。
