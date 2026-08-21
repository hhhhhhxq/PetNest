# 按页面同步远程资源实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:executing-plans 在当前会话逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 移除托盘中的重复入口，并在资源相关设置页打开时自动异步检查、分类显示进度、下载并刷新远程资源。

**架构：** 设置中心用 section 信号通知应用层；应用层持有单个资源任务与可重放的页面状态，复用现有后台线程和结果队列。缓存层增加“当前资源开始传输”回调，常规更新上报 manifest 类型/名称，冷缓存归档上报整包阶段；资源目录切换后刷新仍打开的鼠标主题列表。

**技术栈：** Python 3.11、PySide6、pytest、pytest-qt、现有 `RemoteResourceCache` / `RemoteResourceUpdateCoordinator`

---

## 文件结构

- 修改 `src/petnest/core/remote_resource_update.py`：把资源阶段回调从协调器透传到缓存层。
- 修改 `src/petnest/core/remote_resource_cache.py`：在整包或单资源开始获取时上报准确上下文。
- 修改 `src/petnest/ui/settings_center_dialog.py`：报告资源相关 section、展示非阻塞状态、刷新鼠标主题选项。
- 修改 `src/petnest/ui/tray_icon.py`：删除鼠标样式和手动资源更新动作及其 loading 状态。
- 修改 `src/petnest/app.py`：删除启动/周期/托盘资源检查，添加按页面自动同步、状态重放和分类进度。
- 修改 `tests/test_remote_resource_cache.py`：覆盖单资源与初始资源包阶段回调。
- 修改 `tests/test_remote_resource_update.py`：覆盖协调器回调透传。
- 修改 `tests/test_settings_dialog.py`：覆盖 section 事件、文案、自动隐藏和主题列表刷新。
- 修改 `tests/test_tray_icon.py`：覆盖托盘不再暴露两个重复入口。
- 修改 `tests/test_app_and_platforms.py`：覆盖上下文触发、自动下载、无启动检查和页面状态集成。
- 修改 `docs/superpowers/specs/2026-08-20-contextual-resource-sync-design.md`：保留用户确认后的分类文案与提交边界。

### 任务 1：缓存层上报准确资源阶段

**文件：**
- 修改：`tests/test_remote_resource_cache.py`
- 修改：`tests/test_remote_resource_update.py`
- 修改：`src/petnest/core/remote_resource_cache.py`
- 修改：`src/petnest/core/remote_resource_update.py`

- [x] **步骤 1：为常规资源和冷缓存归档编写失败测试**

在缓存测试中记录 `on_resource_started`：常规逐资源路径断言收到对应 `RemoteResource`，冷缓存归档断言先收到 `None`。在协调器测试中使用捕获关键字参数的 fake cache，断言回调被原样透传。

```python
started: list[RemoteResource | None] = []
result = cache.sync_partial(on_resource_started=started.append)
assert [(item.type, item.metadata.get("name")) for item in started if item is not None] == [
    ("cursor_theme", "奶油爪爪")
]

archive_started: list[RemoteResource | None] = []
cold_cache.sync_partial(on_resource_started=archive_started.append)
assert archive_started[0] is None
```

- [x] **步骤 2：运行定向测试并确认因新参数不存在而失败**

运行：`.venv\Scripts\python.exe -m pytest tests\test_remote_resource_cache.py tests\test_remote_resource_update.py -q`

预期：FAIL，错误指出 `sync_partial()` 或 `apply()` 不接受 `on_resource_started`。

- [x] **步骤 3：实现最小回调协议**

在 cache/coordinator 的 `sync`、`sync_partial`、`apply` 和协议签名中加入：

```python
on_resource_started: Callable[[RemoteResource | None], object] | None = None
```

冷缓存调用 `_download_archive` 前安全通知 `None`；逐资源 `pending` 非空且即将调用 `_download_manifest_files` 前安全通知当前 `RemoteResource`。通知异常只记录日志，不中断同步。

- [x] **步骤 4：运行定向测试并确认通过**

运行：`.venv\Scripts\python.exe -m pytest tests\test_remote_resource_cache.py tests\test_remote_resource_update.py -q`

预期：全部 PASS。

### 任务 2：设置中心显示并保留资源状态

**文件：**
- 修改：`tests/test_settings_dialog.py`
- 修改：`src/petnest/ui/settings_center_dialog.py`

- [x] **步骤 1：编写 section 与状态文案失败测试**

测试 `resource_section_opened` 仅对 `mouse_behavior` / `countdown` 发出稳定 key；测试以下 API：

```python
dialog.set_resource_checking()
assert dialog.resource_status_label.text() == "正在获取最新资源信息…"

dialog.set_resource_downloading(43, resource_type="interaction_effect", display_name="星光")
assert dialog.resource_status_label.text() == "正在获取互动动效「星光」… 43%"

dialog.set_resource_downloading(43, archive=True)
assert dialog.resource_status_label.text() == "正在获取初始资源包… 43%"

dialog.set_resource_error()
assert dialog.resource_status_label.text() == "新资源获取失败，将稍后自动重试"
```

另测 `set_cursor_styles()` 重建下拉项后仍保留调用前 `currentData()`，若该项已不存在才回退系统默认。

- [x] **步骤 2：运行测试并确认缺少信号/控件/API 的预期失败**

运行：`.venv\Scripts\python.exe -m pytest tests\test_settings_dialog.py -q`

预期：FAIL，错误指向缺少 `resource_section_opened`、`resource_status_label` 或状态方法。

- [x] **步骤 3：实现共享状态区域与资源文案格式化**

新增 `resource_section_opened = Signal(str)`、标题下方隐藏的 `resource_status_label` 和单次完成隐藏计时器。`_change_section()` 在资源 section 发信号并按当前 section 控制状态可见性；下载文案只接受固定类型映射：

```python
labels = {
    "cursor_theme": "鼠标主题",
    "interaction_effect": "互动动效",
    "countdown_background": "倒计时背景",
}
```

`set_resource_ready()` 显示“新资源已就绪”并在 3000 ms 后隐藏；检查、下载或错误方法先停止该计时器，避免旧回调隐藏新状态。

- [x] **步骤 4：实现主题列表热刷新**

`set_cursor_styles(styles)` 保存当前 data，阻塞 combo 信号、替换 `_cursor_styles` 和选项、恢复 data，再调用 `_update_cursor_controls()`；不得覆盖窗口内尚未保存的选择。

- [x] **步骤 5：运行设置中心测试并确认通过**

运行：`.venv\Scripts\python.exe -m pytest tests\test_settings_dialog.py -q`

预期：全部 PASS。

### 任务 3：移除托盘重复入口并改为按页面自动同步

**文件：**
- 修改：`tests/test_tray_icon.py`
- 修改：`tests/test_app_and_platforms.py`
- 修改：`src/petnest/ui/tray_icon.py`
- 修改：`src/petnest/app.py`

- [x] **步骤 1：编写托盘精简与启动行为失败测试**

断言托盘 action 文案不包含“鼠标样式”和“资源更新”，且对象不再暴露 `cursor_styles_action` / `resource_update_action`。应用 `start()` 测试用 spy 断言不会调用 `_schedule_resource_check`，并断言不再创建 `resource_update_timer`。

```python
texts = [action.text() for action in tray.menu.actions()]
assert all("鼠标样式" not in text and "资源更新" not in text for text in texts)
assert not hasattr(tray, "cursor_styles_action")
assert not hasattr(tray, "resource_update_action")
```

- [x] **步骤 2：编写页面触发与自动下载失败测试**

分别覆盖：进入 display 不同步；进入 mouse/countdown 调用受节流检查；已有 `update_available` 直接 apply；检查结果发现更新自动 apply；无更新清空状态；重复进入时活动 worker 不重复创建。

```python
application._handle_resource_section_opened("mouse_behavior")
assert checks == [False]

application._handle_resource_check_result(RemoteResourceCheckResult(True, False, True))
assert applies == [True]
```

- [x] **步骤 3：运行定向测试确认旧托盘和旧手动流程导致失败**

运行：`.venv\Scripts\python.exe -m pytest tests\test_tray_icon.py tests\test_app_and_platforms.py -q`

预期：FAIL，旧动作仍存在、启动仍检查、页面 handler 尚不存在。

- [x] **步骤 4：删除托盘资源状态及启动/周期检查**

从 `PetTrayIcon` 删除两个 callback 参数、动作、触发方法、蓝点/loading 图标和计时器；从 `PetNest` 构造/start/shutdown 删除对应接线、`resource_update_timer`、启动检查与 `_resource_timer_tick`。保留 `resource_result_timer` 处理后台结果。

- [x] **步骤 5：实现应用层上下文同步与可重放状态**

新增只接受资源 section 的 `_handle_resource_section_opened(section)`。应用持有 `checking/downloading/ready/error/idle` 状态；活动 worker 存在时只把当前状态重放给新打开页面。没有 worker时，持久状态有更新则 apply，否则 `_schedule_resource_check(force=False)`。

检查结果无论是否被 24 小时节流跳过，只要 `update_available` 就自动 apply；无更新清空状态；失败设置统一错误文案。下载 worker用 `on_resource_started` 保存类型/名称/归档上下文，并让 progress 队列携带不可变快照。

- [x] **步骤 6：连接设置中心并刷新当前主题目录**

创建 dialog 后连接 `resource_section_opened`，赋值 `_settings_center_dialog` 后显式处理初始 section；复用 dialog 时由 `select_section()` 对相同 section 也发出事件。`_refresh_resource_directories()` 在 dialog 存在时调用：

```python
dialog.set_cursor_styles(self.cursor_catalog.discover())
```

- [x] **步骤 7：运行定向测试并确认通过**

运行：`.venv\Scripts\python.exe -m pytest tests\test_tray_icon.py tests\test_settings_dialog.py tests\test_app_and_platforms.py -q`

预期：全部 PASS（平台权限测试可能保持既有 skip）。

### 任务 4：回归验证与提交整理

**文件：**
- 修改：`docs/superpowers/plans/2026-08-21-contextual-resource-sync.md`（勾选实际完成步骤）

- [x] **步骤 1：运行资源与 UI 相关回归测试**

运行：`.venv\Scripts\python.exe -m pytest tests\test_tray_icon.py tests\test_settings_dialog.py tests\test_remote_resource_cache.py tests\test_remote_resource_update.py tests\test_app_and_platforms.py -q`

预期：全部 PASS，只有既有 Windows symlink 权限用例允许 skip。

- [x] **步骤 2：运行完整测试套件并隔离 Windows LAN socket 用例**

运行：`.venv\Scripts\python.exe -m pytest -q --ignore=tests\test_lan_service.py --ignore=tests\test_lan_chat.py`，并分别运行 `tests\test_lan_service.py` 与 `tests\test_lan_chat.py`。

预期：三组均 PASS；避免 Windows 全量进程中的 UDP 端口占用瞬态污染 LAN 断言，并记录精确通过/跳过数量。

- [x] **步骤 3：检查差异和提交范围**

运行：`git diff --check`、`git status --short`、`git diff --stat`。逐项核对规格，确保未暂存用户的素材、缓存、宠物包或无关文档。

- [x] **步骤 4：整理为一个功能提交**

只创建一个包含规格修订、计划、测试和实现的功能提交，并且只暂存本计划“文件结构”列出的文件。先前的规格创建提交已经与其他并行功能提交交错，本次不重写这些不相关提交的哈希。最终提交标题：

```text
feat: 按页面自动同步远程资源
```

- [x] **步骤 5：在整理后的 HEAD 重新运行验证**

运行任务 4 步骤 1 的回归命令和 `git status --short`，确认历史整理没有改变功能，且用户原有未跟踪文件仍未被暂存或删除。
