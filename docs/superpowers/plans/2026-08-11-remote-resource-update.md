# 远程资源更新实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法跟踪进度。

**目标：** 将 Worker 资源更新接入 PetNest，使光标、倒计时背景和后续互动动效使用可回退的版本化远程缓存。

**架构：** 客户端以安装包资源为最终兜底；`RemoteResourceCache` 将完整 manifest 下载到版本目录并原子切换 `current.json`；`RemoteResourceUpdateCoordinator` 负责 24 小时节流、手动强制检查、状态持久化和蓝点状态。网络工作在后台线程，Qt 主线程只接收结果并刷新目录。

**技术栈：** Python 3.12、PySide6、urllib、JSON、SHA-256、pytest/pytest-qt。

---

### 任务 1：将缓存改为版本化原子切换

**文件：**
- 修改：`src/petnest/core/remote_resource_cache.py`
- 测试：`tests/test_remote_resource_cache.py`

- [ ] 编写失败测试：同步新 manifest 后创建 `versions/<catalog>-<digest>/resources/...` 和 `current.json`；下载失败时旧 current 指针和旧文件保持不变；`path_for()` 从 current 版本解析。
- [ ] 运行 `python -m pytest tests/test_remote_resource_cache.py -q`，确认新断言因缺少版本目录/指针而失败。
- [ ] 实现 `current_pointer_path`、`current_root`、`load_current_manifest()`；让 `sync()` 先写 staging，再把 staging 重命名为不可变版本目录，最后原子写入 current 指针；保留旧版本，不直接覆盖旧版本文件。
- [ ] 运行同一测试文件，确认全部通过，并运行现有 14 个远程资源测试。
- [ ] 提交：`git add src/petnest/core/remote_resource_cache.py tests/test_remote_resource_cache.py && git commit -m "feat: make resource cache versioned and atomic"`

### 任务 2：实现检查节流、状态和蓝点协调器

**文件：**
- 创建：`src/petnest/core/remote_resource_update.py`
- 创建：`tests/test_remote_resource_update.py`

- [ ] 编写失败测试：首次检查允许请求；24 小时内的定时检查跳过；强制检查绕过节流；manifest 文件哈希变化设置 `update_available`；状态文件重载后蓝点仍存在；应用成功后清除蓝点。
- [ ] 运行 `python -m pytest tests/test_remote_resource_update.py -q`，确认因协调器不存在而失败。
- [ ] 实现 `RemoteResourceUpdateState` 和 `RemoteResourceUpdateCoordinator`：状态原子写入 `state.json`，`check(force=False)` 只请求 manifest，`apply()` 调用缓存完整同步，失败保留 pending 状态。
- [ ] 运行测试，确认节流、强制检查、状态恢复和失败回退全部通过。
- [ ] 提交：`git add src/petnest/core/remote_resource_update.py tests/test_remote_resource_update.py && git commit -m "feat: add resource update coordinator"`

### 任务 3：让应用优先使用 current 资源并保持内置回退

**文件：**
- 修改：`src/petnest/app.py`
- 修改：`src/petnest/ui/pet_window.py`
- 测试：`tests/test_app_and_platforms.py`、`tests/test_pet_window.py`

- [ ] 编写失败测试：有效 current 版本存在时，光标目录和倒计时皮肤从 current 资源根目录读取；current 缺失或损坏时仍使用安装包目录。
- [ ] 运行相关测试，确认现有构造函数没有 current 资源注入能力。
- [ ] 增加资源根目录解析函数，创建 `RemoteResourceCache` 和协调器；在应用启动后排入后台检查，不在构造窗口时同步网络；`CursorStyleCatalog` 使用 current 的 `resources/cursors`，否则回退内置目录；`PetWindow` 接收可选 countdown 根目录。
- [ ] 运行 `python -m pytest tests/test_app_and_platforms.py tests/test_pet_window.py -q`，确认现有光标恢复、倒计时和内置回退测试通过。
- [ ] 提交：`git add src/petnest/app.py src/petnest/ui/pet_window.py tests/test_app_and_platforms.py tests/test_pet_window.py && git commit -m "feat: use verified remote resource generations"`

### 任务 4：添加后台检查、手动检查和蓝点菜单动作

**文件：**
- 修改：`src/petnest/app.py`
- 修改：`src/petnest/ui/tray_icon.py`
- 测试：`tests/test_app_and_platforms.py`

- [ ] 编写失败测试：启动调度不阻塞；30 分钟计时器只在 24 小时到期后检查；手动动作立即触发；检测到更新时动作文字带 `●`，应用成功后去掉蓝点。
- [ ] 运行测试确认新托盘动作和调度接口缺失。
- [ ] 使用 `threading.Thread` 执行 manifest 检查/下载，使用 Qt 信号回到主线程；增加 24 小时 QTimer、手动 `resource_update_action` 和 `set_resource_update_available()`；成功后刷新资源目录但不强制替换当前系统光标。
- [ ] 运行 `python -m pytest tests/test_app_and_platforms.py -q`，确认 UI 和退出流程无回归。
- [ ] 提交：`git add src/petnest/app.py src/petnest/ui/tray_icon.py tests/test_app_and_platforms.py && git commit -m "feat: schedule resource checks and show update badge"`

### 任务 5：全量验证与线上抽样校验

**文件：**
- 无新增源码文件；验证 `src/petnest/core/remote_resource_*`、`worker/src/index.js` 和私有资源仓库。

- [ ] 运行 `python -m pytest -q`，预期现有测试全部通过，允许已有平台限定 skip。
- [ ] 使用线上 `https://red-lake-ce5a.bbbbbiubiubiu.workers.dev/v1/manifest.json` 校验一个 cursor、一个 effect、一个 countdown 文件的大小和 SHA-256。
- [ ] 运行 `git diff --check` 和 `git status --short --branch`，确认只留下计划内提交且主工作区仍未修改。
- [ ] 提交验证记录：`git commit --allow-empty -m "test: verify remote resource update flow"`
