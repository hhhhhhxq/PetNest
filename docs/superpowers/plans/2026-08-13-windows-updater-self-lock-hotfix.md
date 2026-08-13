# Windows 更新器自占用热修实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 发布可由 0.1.2/0.1.4 自动升级、且后续不会自占用安装目录的 PetNest 0.1.5。

**架构：** 用新文件名完成旧更新器到新更新宿主的一次兼容迁移；新版本每次安装前将宿主复制到临时目录运行。更新器通过 `finally` 保证安装结束后恢复启动应用。

**技术栈：** Python 标准库、PyInstaller、Inno Setup、pytest。

---

### 任务 1：建立失败回归测试

**文件：**
- 修改：`tests/test_app_update.py`
- 修改：`tests/test_installer_script.py`

- [x] 添加临时更新宿主复制测试。
- [x] 添加安装失败后重启应用测试。
- [x] 添加安装器不覆盖旧更新器的静态测试。
- [x] 运行专项测试并确认三项因缺少行为而失败。

### 任务 2：实现兼容更新链路

**文件：**
- 修改：`src/petnest/core/windows_updater.py`
- 修改：`src/petnest/app.py`
- 修改：`build_windows.bat`
- 修改：`installer/PetNest.iss`

- [x] 实现 `stage_windows_updater`，复制并清理临时宿主。
- [x] 主程序从临时副本启动更新宿主。
- [x] 安装器改用 `PetNestUpdateHost.exe`。
- [x] 安装结束后无论结果都尝试重启 PetNest。
- [x] 运行专项测试确认通过。

### 任务 3：发布与真实升级验证

**文件：**
- 修改：`pyproject.toml`
- 修改：`src/petnest/__init__.py`
- 修改：`docs/app-update.md`

- [x] 将版本升级到 0.1.5 并运行全量测试。
- [x] 构建 Windows 正式安装包并核对 SHA-256。
- [x] 用现有 0.1.2 的旧更新器执行真实升级，确认 0.1.5 自动启动。
- [x] 完成提交清单、最终安装包、更新清单与线上发布资料准备。
