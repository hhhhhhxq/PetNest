# Codex 联动实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 通过 Codex 官方 Hooks 将本机任务状态安全地映射到 PetNest 当前宠物动作和独立状态气泡，并提供完整的安装、设置与故障提示。

**架构：** `CodexHookManager` 只负责安全合并 Hooks 配置、桥接命令和令牌元数据；PetNest 的 `--codex-hook` 子命令在 GUI/单实例初始化前转发脱敏事件；`ExternalEventServer` 验证本机 Hook 消息后把事件交给 Qt 主线程；`CodexLinkCoordinator` 聚合多个任务并产生通用 `agent.*` 事件和 UI 状态。设置中心控制联动开关与 Hook 生命周期，宠物窗口独立承载 Codex 气泡。

**技术栈：** Python 3.12、PySide6、newline-delimited JSON over loopback TCP、pytest、pytest-qt

---

## 文件结构

- 创建 `src/petnest/core/codex_link.py`：Hook 安装状态、原子配置合并、令牌元数据、桥接命令和多任务状态协调。
- 修改 `src/petnest/__main__.py`、`tests/test_main.py`：在 Qt 与单实例初始化前处理 `--codex-hook`。
- 创建 `src/petnest/ui/codex_status_bubble.py`：可点击、可持续、支持未读状态的独立顶层气泡。
- 创建 `tests/test_codex_link.py`：Hook 配置安全、桥接请求裁剪、鉴权数据和状态聚合测试。
- 创建 `tests/test_codex_status_bubble.py`：气泡文本、持续/限时、点击和屏幕边界测试。
- 修改 `src/petnest/models/settings.py`、`src/petnest/core/settings_manager.py`、`tests/test_settings_manager.py`：新增三项非敏感偏好并迁移 schema。
- 修改 `src/petnest/events/external_event_server.py`、`tests/test_external_events.py`：Codex 专用令牌验证和可注入事件出口。
- 修改 `src/petnest/core/state_machine.py`、`src/petnest/core/spritesheet_importer.py` 及对应测试：拖动结束恢复上下文，纠正 jumping/review 语义。
- 修改 `src/petnest/ui/settings_center_dialog.py`、`tests/test_settings_dialog.py`：新增第六个设置分类及运行状态操作。
- 修改 `src/petnest/ui/pet_window.py`、`tests/test_pet_window.py`：管理 Codex 气泡位置并与倒计时分离。
- 修改 `src/petnest/app.py`、`tests/test_app_and_platforms.py`：主线程事件桥接、服务生命周期、协调器和设置页回调装配。
- 修改 `docs/superpowers/specs/2026-08-19-codex-link-design.md`：若实现验证发现官方 Hooks 字段差异，只同步真实字段，不扩大功能。

### 任务 1：设置模型与迁移

- [x] **步骤 1：编写失败测试**

在 `tests/test_settings_manager.py` 增加：默认值为关闭/开启/开启；schema 23 的旧设置迁移后保留原值并得到 schema 24；损坏类型回退默认布尔值。

```python
def test_schema_23_migrates_codex_link_preferences(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text('{"schema_version": 23, "scale": 1.25}', encoding="utf-8")
    loaded = SettingsManager(path).load()
    assert loaded.schema_version == 24
    assert loaded.codex_link_enabled is False
    assert loaded.codex_link_show_attention_bubbles is True
    assert loaded.codex_link_show_review_bubbles is True
```

- [x] **步骤 2：验证红灯**

运行：`python -m pytest tests/test_settings_manager.py -q`

预期：测试因 `Settings` 没有 `codex_link_*` 字段而失败。

- [x] **步骤 3：最少实现**

把 `Settings.SCHEMA_VERSION` 升至 24，增加三个字段，并在 `from_dict` 用严格布尔归一化；在 `_migrate` 的 23 → 24 分支补默认值。

```python
codex_link_enabled: bool = False
codex_link_show_attention_bubbles: bool = True
codex_link_show_review_bubbles: bool = True
```

- [x] **步骤 4：验证绿灯**

运行：`python -m pytest tests/test_settings_manager.py -q`

预期：全部通过。

### 任务 2：Hook 管理器与桥接脚本

- [x] **步骤 1：编写失败测试**

在 `tests/test_codex_link.py` 覆盖：空配置安装、保留未知字段和其他 Hook、重复安装幂等、只移除 PetNest handler、损坏 JSON 不写入、元数据令牌持久且至少 32 字节、桥接请求不包含提示词字段。`tests/test_main.py` 覆盖桥接子命令不会创建 QApplication 或获取单实例锁。

```python
manager = CodexHookManager(codex_home, data_dir, port=18486)
result = manager.install()
document = json.loads((codex_home / "hooks.json").read_text(encoding="utf-8"))
assert result.installed
assert document["hooks"]["Stop"][0]["hooks"][0]["commandWindows"]
assert manager.install().token == result.token
```

- [x] **步骤 2：验证红灯**

运行：`python -m pytest tests/test_codex_link.py -q`

预期：导入 `petnest.core.codex_link` 失败。

- [x] **步骤 3：最少实现**

实现以下公开接口：

```python
@dataclass(frozen=True, slots=True)
class CodexHookStatus:
    state: str
    message: str
    installed: bool
    token: str | None = None

class CodexHookManager:
    def inspect(self) -> CodexHookStatus: ...
    def install(self) -> CodexHookStatus: ...
    def remove(self) -> CodexHookStatus: ...
    def ensure_metadata(self) -> CodexLinkMetadata: ...
```

Hook handler 使用 `type=command`、`commandWindows`、`timeoutSec=5`、`async=True`；命令带稳定参数 `--codex-hook`。文件写入采用同目录临时文件、`fsync`、原子 `replace`；存在的 hooks.json 在首次修改前复制带时间戳备份。`forward_codex_hook()` 只提取 `hook_event_name`、`session_id`、`turn_id`、`tool_name`、工具响应中明确的成功标志和 `stop_hook_active`，然后向元数据中的回环端口发送一行 JSON，连接失败在 250ms 内静默退出。安装版命令调用当前 exe，源码命令调用 `sys.executable -m petnest`。

- [x] **步骤 4：验证绿灯**

运行：`python -m pytest tests/test_codex_link.py -q`

预期：Hook 管理测试全部通过。

### 任务 3：本机服务鉴权与 Qt 线程出口

- [x] **步骤 1：编写失败测试**

扩展 `tests/test_external_events.py`：普通事件继续兼容；`codex.hook` 缺令牌、错令牌、未知 payload 字段时被拒绝；正确令牌被发布且 token 不进入 `PetEvent.payload`；`event_sink` 在服务线程调用而不是直接依赖应用总线。

```python
server = ExternalEventServer(EventBus(), port=0, codex_token="secret", event_sink=received.append)
_send(server.port, b'{"event":"codex.hook","token":"wrong","payload":{}}\n')
assert received == []
```

- [x] **步骤 2：验证红灯**

运行：`python -m pytest tests/test_external_events.py -q`

预期：构造器不接受 `codex_token` / `event_sink`。

- [x] **步骤 3：最少实现**

为服务器新增可选的 `codex_token` 和 `event_sink`。只有 `event == "codex.hook"` 时允许顶层 `token`；使用 `hmac.compare_digest` 验证；验证后移除 token。若提供 `event_sink` 则调用它，否则保持原 `EventBus.publish` 行为。

应用侧增加一个私有 `QObject` 中继：后台 `event_sink` 只发 `Signal(object)`，信号槽在创建它的 Qt 主线程调用 `event_bus.publish`。

- [x] **步骤 4：验证绿灯**

运行：`python -m pytest tests/test_external_events.py tests/test_app_and_platforms.py -q`

预期：外部事件回归与线程出口测试通过。

### 任务 4：Codex 多任务状态协调器

- [x] **步骤 1：编写失败测试**

在 `tests/test_codex_link.py` 覆盖状态转换、同 turn 覆盖、SessionEnd 清理、`stop_hook_active` 不结算、工具失败可被后续运行恢复、多任务优先级和气泡数量。

```python
coordinator.consume(PetEvent("codex.hook", payload={
    "hook_event_name": "PermissionRequest", "session_id": "s1", "turn_id": "t1"
}))
assert coordinator.snapshot.state == "waiting"
assert coordinator.snapshot.count == 1
assert published[-1].event_name == "agent.waiting"
```

- [x] **步骤 2：验证红灯**

运行：`python -m pytest tests/test_codex_link.py -q`

预期：`CodexLinkCoordinator` 未定义。

- [x] **步骤 3：最少实现**

定义不可变 `CodexLinkSnapshot(state, count, unread_review_count, message)`；协调器只接收 `source="codex-hook"` 的 `codex.hook`，校验 ID 长度和事件白名单，按 `(session_id, turn_id or "session")` 聚合；变更时调用注入的 `publish(PetEvent)` 和 `snapshot_changed(snapshot)`。

优先级固定为 `waiting > failed > review > running > idle`，映射到 `agent.waiting / agent.error / agent.success / agent.working`。`Stop` 产生 review，`SessionEnd` 删除会话，后续 running 清除同 turn 的临时 failed/review。

- [x] **步骤 4：验证绿灯**

运行：`python -m pytest tests/test_codex_link.py -q`

预期：协调器测试全部通过。

### 任务 5：精灵图语义与拖动结束恢复

- [x] **步骤 1：编写失败测试**

修改 `tests/test_spritesheet_importer.py`，断言第 5 行生成 `hover`、第 9 行生成 `review`、`agent.success -> review`、没有 `drop` 和 `mouse.drag_end` 绑定。修改 `tests/test_state_machine.py`，构造只有 `drag` 无 drag_end 绑定的包，断言松手恢复 hover/idle。

```python
transition = machine.handle(PetEvent("mouse.drag_end", timestamp=2.0))
assert transition.changed
assert transition.current_action == "idle"
```

- [x] **步骤 2：验证红灯**

运行：`python -m pytest tests/test_spritesheet_importer.py tests/test_state_machine.py -q`

预期：旧映射仍生成 drop，未绑定 drag_end 返回 unbound。

- [x] **步骤 3：最少实现**

将 row 4（jumping）映射为 `hover`，row 8（review）映射为 `review`；移除 drop 映射与 drag_end 绑定；将 success fallback 改为 review fallback。状态机在 `mouse.drag_end` 未绑定时直接请求 `_context_action()`，仍保留 forced 中断语义。

- [x] **步骤 4：验证绿灯**

运行：`python -m pytest tests/test_spritesheet_importer.py tests/test_state_machine.py tests/test_pet_window.py -q`

预期：新语义和现有窗口交互均通过。

### 任务 6：独立 Codex 状态气泡

- [x] **步骤 1：编写失败测试**

在 `tests/test_codex_status_bubble.py` 验证 running 隐藏、waiting/failed 持续、review 启动 10 秒计时且保留未读点、点击发信号并清除未读、文本按任务数聚合、位置限制在当前屏幕可用区域。

```python
bubble.show_snapshot(CodexLinkSnapshot("waiting", 2, 0, "2 个 Codex 任务等待你处理"), anchor)
assert bubble.isVisible()
assert "2 个" in bubble.text()
assert not bubble.dismiss_timer.isActive()
```

- [x] **步骤 2：验证红灯**

运行：`python -m pytest tests/test_codex_status_bubble.py -q`

预期：气泡模块不存在。

- [x] **步骤 3：最少实现**

实现 `CodexStatusBubble(QWidget)`，内部使用标签、未读点和关闭按钮，信号为 `activated`、`dismissed`。`show_snapshot(snapshot, anchor_rect, avoid_rect=None)` 选择上/左/右位置并夹紧至屏幕可用区域；running/idle 隐藏；review 的正文 10 秒后隐藏但未读点保留为紧凑徽标；waiting/failed 不启动计时。

PetWindow 创建该窗口，公开 `show_codex_status(snapshot)`、`clear_codex_status()` 和 `codex_status_activated`；移动、缩放和倒计时布局变化时重排气泡。

- [x] **步骤 4：验证绿灯**

运行：`python -m pytest tests/test_codex_status_bubble.py tests/test_pet_window.py -q`

预期：气泡和窗口布局测试通过。

### 任务 7：设置中心 Codex 联动页

- [x] **步骤 1：编写失败测试**

修改 `tests/test_settings_dialog.py`：导航为六页且 Codex 位于空闲和倒计时之间；三个开关正确读写；状态标签和动作可用性文案可刷新；安装、移除按钮调用回调并更新状态；关闭总开关时提醒开关禁用但值保留。

```python
dialog = SettingsCenterDialog(Settings(), codex_hook_status=CodexHookStatus("missing", "尚未安装", False))
assert dialog.section_list.item(3).text() == "Codex 联动"
dialog.codex_link_enabled_input.setChecked(True)
assert dialog.updated_settings().codex_link_enabled
```

- [x] **步骤 2：验证红灯**

运行：`python -m pytest tests/test_settings_dialog.py -q`

预期：构造器和 Codex 控件缺失。

- [x] **步骤 3：最少实现**

新增构造参数 `codex_hook_status`、`codex_action_availability`、`on_install_codex_hook`、`on_remove_codex_hook`。页面包含联动开关/状态/最近事件、四项动作解析结果和两项气泡偏好。按钮回调返回 `CodexHookStatus`，页面就地更新并把错误显示为可换行文案。

- [x] **步骤 4：验证绿灯**

运行：`python -m pytest tests/test_settings_dialog.py -q`

预期：设置中心测试全部通过。

### 任务 8：应用装配与生命周期

- [x] **步骤 1：编写失败测试**

在 `tests/test_app_and_platforms.py` 覆盖：仅 Codex 联动开启也启动服务；关闭两种入口才停止；应用启动只 inspect 不改写 hooks；设置页安装/移除回调；Hook 事件在主线程更新状态；关闭联动清状态；shutdown 先清气泡/协调器再停 server。

```python
application.apply_settings(replace(application.settings, codex_link_enabled=True))
assert application.external_server is not None
assert application.external_server.is_running
```

- [x] **步骤 2：验证红灯**

运行：`python -m pytest tests/test_app_and_platforms.py -q`

预期：Codex 联动尚未装配。

- [x] **步骤 3：最少实现**

PetNest 初始化 `CodexHookManager`、Qt 事件中继和 `CodexLinkCoordinator`；服务需要条件为 `external_event_server_enabled or codex_link_enabled`。`apply_settings` 检测开关变化，启动/重启/停止服务并清理 UI；设置页传入实时状态和动作可用性。协调器快照根据偏好调用 `window.show_codex_status`，并把激活信号连接到 Windows 上查找并前置 Codex 顶层窗口的安全帮助函数；未找到时只隐藏气泡，不启动程序或打开任意文件。

- [x] **步骤 4：验证绿灯与回归**

运行：

```powershell
python -m pytest tests/test_codex_link.py tests/test_external_events.py tests/test_state_machine.py tests/test_spritesheet_importer.py tests/test_codex_status_bubble.py tests/test_settings_manager.py tests/test_settings_dialog.py tests/test_pet_window.py tests/test_app_and_platforms.py -q
```

预期：所列测试全部通过且无线程未退出警告。

### 任务 9：端到端验证与提交

- [ ] **步骤 1：桥接烟雾测试**

使用临时 Codex home 安装 Hook，启动随机端口服务，把一份最小 `PermissionRequest` JSON 通过生成的桥接脚本标准输入发送，断言服务收到脱敏 `codex.hook` 且协调器输出 waiting；再发送 Stop，断言 review。

- [ ] **步骤 2：完整测试**

运行：`python -m pytest -q`

预期：全部通过；既有平台条件跳过可保留。

- [ ] **步骤 3：静态检查与差异审查**

运行：

```powershell
python -m compileall -q src tests
git diff --check
git status --short
```

预期：compileall 和 diff check 退出码为 0；状态只包含本功能文件以及用户原有的 `build_windows.bat`、`tests/test_installer_script.py` 和其他未跟踪文件。

- [ ] **步骤 4：功能提交**

只暂存本计划列出的实现、测试、规格和计划文件，明确排除用户已有改动。提交信息：

```text
feat: link pet animations with Codex hooks
```
