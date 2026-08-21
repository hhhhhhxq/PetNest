# 键盘活动 Working 动画实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 在 Windows 上全局敲键盘时播放 working，最后一次按键后 1.5 秒释放，并用统一仲裁避免键盘与 Codex working 相互错误取消。

**架构：** 新增纯 Python `WorkActivityCoordinator` 统一 Codex 与键盘来源；新增平台键盘监听协议和 Windows 低级 Hook 实现，原生线程只发无参数活动通知，经 Qt Signal 进入主线程。设置页增加默认关闭的键盘活动开关，macOS/其他平台显式降级。

**技术栈：** Python 3.12、PySide6、ctypes/Win32 Hook、threading、pytest、pytest-qt。

---

## 文件结构

- 创建 `src/petnest/core/work_activity.py`：Codex/键盘 working 的纯状态仲裁。
- 创建 `tests/test_work_activity.py`：真值表、review、来源释放和重复事件测试。
- 创建 `src/petnest/platforms/keyboard.py`：监听协议、unsupported 实现和平台工厂。
- 创建 `src/petnest/platforms/windows_keyboard.py`：Windows 全局低级键盘 Hook 与线程生命周期。
- 创建 `tests/test_keyboard_activity.py`：平台工厂、unsupported 和 Windows Hook 替身测试。
- 修改 `src/petnest/models/settings.py`、`src/petnest/core/settings_manager.py`、`tests/test_settings_manager.py`：schema 27 和默认关闭设置。
- 修改 `src/petnest/ui/settings_center_dialog.py`、`tests/test_settings_dialog.py`：键盘活动卡片、平台状态和动作缺失提示。
- 修改 `src/petnest/app.py`、`tests/test_app_and_platforms.py`：Qt relay、1.5 秒 timer、监听生命周期、Codex 仲裁和 wake 抑制。
- 修改 `tests/test_codex_link.py`、`tests/test_state_machine.py`：现有 Codex/状态机回归边界。

### 任务 1：实现 Codex 与键盘 Working 的纯状态仲裁

**文件：**
- 创建：`src/petnest/core/work_activity.py`
- 创建：`tests/test_work_activity.py`

- [ ] **步骤 1：编写冲突真值表的失败测试**

```python
from petnest.core.work_activity import WorkActivityCoordinator
from petnest.models.event import PetEvent


def _event(name: str, *, priority: int = 90) -> PetEvent:
    return PetEvent(name, source="codex-link", priority=priority)


def test_keyboard_stop_does_not_cancel_running_codex() -> None:
    published: list[PetEvent] = []
    coordinator = WorkActivityCoordinator(published.append)
    coordinator.handle_codex_event(_event("agent.working"))
    coordinator.keyboard_activity_started()
    published.clear()

    coordinator.keyboard_activity_stopped()

    assert published == []
    assert coordinator.effective_event == "agent.working"


def test_codex_idle_does_not_cancel_active_keyboard() -> None:
    published: list[PetEvent] = []
    coordinator = WorkActivityCoordinator(published.append)
    coordinator.keyboard_activity_started()
    published.clear()

    coordinator.handle_codex_event(_event("agent.idle"))

    assert [event.event_name for event in published] == []
    assert coordinator.effective_event == "agent.working"


def test_waiting_and_failed_override_keyboard_working() -> None:
    published: list[PetEvent] = []
    coordinator = WorkActivityCoordinator(published.append)
    coordinator.keyboard_activity_started()

    coordinator.handle_codex_event(_event("agent.waiting"))
    coordinator.keyboard_activity_started()
    coordinator.handle_codex_event(_event("agent.error"))

    assert [event.event_name for event in published] == [
        "agent.working",
        "agent.waiting",
        "agent.error",
    ]


def test_review_finishes_to_keyboard_working_without_marking_review_read() -> None:
    published: list[PetEvent] = []
    coordinator = WorkActivityCoordinator(published.append)
    coordinator.keyboard_activity_started()
    coordinator.handle_codex_event(_event("agent.success", priority=100))
    published.clear()

    coordinator.finish_codex_review_animation()

    assert [event.event_name for event in published] == ["agent.working"]
    assert coordinator.codex_state == "review"


def test_repeated_keyboard_activity_reasserts_without_changing_effective_state() -> None:
    published: list[PetEvent] = []
    coordinator = WorkActivityCoordinator(published.append)

    coordinator.keyboard_activity_started()
    coordinator.keyboard_activity_started()
    coordinator.keyboard_activity_started()

    assert [event.event_name for event in published] == [
        "agent.working",
        "agent.working",
        "agent.working",
    ]
```

- [ ] **步骤 2：运行测试并确认模块缺失**

运行：`python -m pytest tests/test_work_activity.py -q`

预期：收集失败，提示 `ModuleNotFoundError: petnest.core.work_activity`。

- [ ] **步骤 3：实现最小仲裁器**

```python
# src/petnest/core/work_activity.py
from __future__ import annotations

from collections.abc import Callable

from petnest.models.event import PetEvent


_CODEX_STATES = {
    "agent.idle": "idle",
    "agent.working": "running",
    "agent.waiting": "waiting",
    "agent.error": "failed",
    "agent.success": "review",
}


class WorkActivityCoordinator:
    def __init__(self, publish: Callable[[PetEvent], object]) -> None:
        self._publish = publish
        self.codex_state = "idle"
        self.keyboard_active = False
        self.review_animation_finished = True
        self.effective_event = "agent.idle"

    def handle_codex_event(self, event: PetEvent) -> None:
        state = _CODEX_STATES.get(event.event_name)
        if state is None:
            self._publish(event)
            return
        self.codex_state = state
        if state == "review":
            self.review_animation_finished = False
        elif state != "review":
            self.review_animation_finished = True
        self._emit_effective(priority=event.priority)

    def keyboard_activity_started(self) -> None:
        if self.keyboard_active:
            if self._desired_event() == "agent.working":
                self._publish(PetEvent("agent.working", source="work-activity", priority=40))
            return
        self.keyboard_active = True
        self._emit_effective(priority=40)

    def keyboard_activity_stopped(self) -> None:
        if not self.keyboard_active:
            return
        self.keyboard_active = False
        self._emit_effective(priority=40)

    def finish_codex_review_animation(self) -> None:
        if self.codex_state != "review" or self.review_animation_finished:
            return
        self.review_animation_finished = True
        self._emit_effective(priority=100)

    def reset_keyboard(self) -> None:
        self.keyboard_activity_stopped()

    def _desired_event(self) -> str:
        if self.codex_state == "waiting":
            return "agent.waiting"
        if self.codex_state == "failed":
            return "agent.error"
        if self.codex_state == "review" and not self.review_animation_finished:
            return "agent.success"
        if self.codex_state == "running" or self.keyboard_active:
            return "agent.working"
        return "agent.idle"

    def _emit_effective(self, *, priority: int) -> None:
        desired = self._desired_event()
        if desired == self.effective_event:
            return
        self.effective_event = desired
        self._publish(PetEvent(desired, source="work-activity", priority=priority))
```

- [ ] **步骤 4：补充 review 无键盘回 idle、键盘停止后双来源释放测试并验证通过**

运行：`python -m pytest tests/test_work_activity.py -q`

预期：全部 PASS。

- [ ] **步骤 5：提交仲裁器**

```bash
git add src/petnest/core/work_activity.py tests/test_work_activity.py
git commit -m "feat: 合并 Codex 与键盘工作状态"
```

### 任务 2：建立平台键盘监听协议与安全降级

**文件：**
- 创建：`src/petnest/platforms/keyboard.py`
- 创建：`tests/test_keyboard_activity.py`

- [ ] **步骤 1：编写平台工厂和 unsupported 失败测试**

```python
from petnest.platforms.keyboard import (
    UnsupportedKeyboardActivityMonitor,
    create_keyboard_activity_monitor,
)


def test_unsupported_monitor_never_invokes_callback() -> None:
    calls: list[bool] = []
    monitor = UnsupportedKeyboardActivityMonitor("darwin")

    assert monitor.supported is False
    assert monitor.start(lambda: calls.append(True)) is False
    monitor.stop()
    assert calls == []
    assert monitor.status_message == "当前版本仅支持 Windows"


def test_factory_uses_unsupported_monitor_outside_windows() -> None:
    assert isinstance(
        create_keyboard_activity_monitor("darwin"),
        UnsupportedKeyboardActivityMonitor,
    )
```

- [ ] **步骤 2：运行测试确认模块缺失**

运行：`python -m pytest tests/test_keyboard_activity.py -q`

预期：FAIL，提示模块不存在。

- [ ] **步骤 3：实现协议、unsupported 和延迟 Windows 导入**

```python
# src/petnest/platforms/keyboard.py
from __future__ import annotations

import sys
from collections.abc import Callable
from typing import Protocol


class KeyboardActivityMonitor(Protocol):
    @property
    def supported(self) -> bool:
        raise NotImplementedError

    @property
    def status_message(self) -> str:
        raise NotImplementedError

    def start(self, on_activity: Callable[[], object]) -> bool:
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError


class UnsupportedKeyboardActivityMonitor:
    def __init__(self, platform_name: str) -> None:
        self.platform_name = platform_name

    @property
    def supported(self) -> bool:
        return False

    @property
    def status_message(self) -> str:
        return "当前版本仅支持 Windows"

    def start(self, on_activity: Callable[[], object]) -> bool:
        del on_activity
        return False

    def stop(self) -> None:
        return None


def create_keyboard_activity_monitor(
    platform_name: str | None = None,
) -> KeyboardActivityMonitor:
    name = platform_name or sys.platform
    if name == "win32":
        from petnest.platforms.windows_keyboard import WindowsKeyboardActivityMonitor

        return WindowsKeyboardActivityMonitor()
    return UnsupportedKeyboardActivityMonitor(name)
```

- [ ] **步骤 4：运行协议测试**

运行：`python -m pytest tests/test_keyboard_activity.py -q`

预期：PASS。

- [ ] **步骤 5：提交平台协议**

```bash
git add src/petnest/platforms/keyboard.py tests/test_keyboard_activity.py
git commit -m "feat: 添加键盘活动监听接口"
```

### 任务 3：实现 Windows 全局低级键盘 Hook

**文件：**
- 创建：`src/petnest/platforms/windows_keyboard.py`
- 修改：`tests/test_keyboard_activity.py`

- [ ] **步骤 1：用 Hook session 替身编写线程生命周期和隐私测试**

```python
from threading import Event

from petnest.platforms.windows_keyboard import WindowsKeyboardActivityMonitor


class FakeHookSession:
    def __init__(self, *, install_ok: bool = True) -> None:
        self.install_ok = install_ok
        self.started = Event()
        self.stop_requested = Event()
        self.activity = None
        self.stopped = 0
        self.error_message = "" if install_ok else "无法安装 Windows 键盘监听"

    def run(self, on_activity) -> None:
        self.activity = on_activity
        self.started.set()
        if self.install_ok:
            self.stop_requested.wait(2)

    def request_stop(self) -> None:
        self.stopped += 1
        self.stop_requested.set()


def test_windows_monitor_emits_only_parameterless_activity() -> None:
    session = FakeHookSession()
    calls: list[tuple[object, ...]] = []
    monitor = WindowsKeyboardActivityMonitor(session_factory=lambda: session)
    assert monitor.start(lambda *args: calls.append(args)) is True

    assert session.activity is not None
    session.activity()
    monitor.stop()

    assert calls == [()]
    assert session.stopped == 1


def test_windows_monitor_install_failure_is_safe_and_retryable() -> None:
    failed = FakeHookSession(install_ok=False)
    monitor = WindowsKeyboardActivityMonitor(session_factory=lambda: failed)

    assert monitor.start(lambda: None) is False
    assert monitor.status_message == "无法安装 Windows 键盘监听"
    monitor.stop()
```

- [ ] **步骤 2：运行测试确认 Windows 实现缺失**

运行：`python -m pytest tests/test_keyboard_activity.py -q`

预期：FAIL，提示无法导入 `windows_keyboard`。

- [ ] **步骤 3：实现 monitor 线程包装和可注入 session**

```python
class WindowsKeyboardActivityMonitor:
    def __init__(self, *, session_factory=_WindowsHookSession, start_timeout: float = 1.0) -> None:
        self._session_factory = session_factory
        self._start_timeout = start_timeout
        self._session = None
        self._thread = None
        self._status_message = "已关闭"

    @property
    def supported(self) -> bool:
        return True

    @property
    def status_message(self) -> str:
        return self._status_message

    def start(self, on_activity: Callable[[], object]) -> bool:
        if self._thread is not None and self._thread.is_alive():
            return True
        session = self._session_factory()
        thread = Thread(target=session.run, args=(on_activity,), daemon=True, name="petnest-keyboard-hook")
        self._session = session
        self._thread = thread
        thread.start()
        if not session.started.wait(self._start_timeout) or not session.install_ok:
            self._status_message = session.error_message or "无法安装 Windows 键盘监听"
            session.request_stop()
            thread.join(timeout=1)
            self._session = None
            self._thread = None
            return False
        self._status_message = "监听正常"
        return True

    def stop(self) -> None:
        session, thread = self._session, self._thread
        self._session = None
        self._thread = None
        if session is not None:
            session.request_stop()
        if thread is not None:
            thread.join(timeout=1)
        self._status_message = "已关闭"
```

- [ ] **步骤 4：实现 `_WindowsHookSession` 原生边界**

实现要求：

- `run()` 记录线程 ID，创建 `HOOKPROC`，调用 `SetWindowsHookExW(WH_KEYBOARD_LL, ...)`；
- 安装结果写入 `install_ok/error_message` 后设置 `started`；
- 回调只检查 `nCode` 和 `wParam in {WM_KEYDOWN, WM_SYSKEYDOWN}`，调用无参数 `on_activity()`；
- 回调不读取 `lParam` 指向的键值结构；
- 始终返回 `CallNextHookEx`；
- 消息循环使用 `GetMessageW/TranslateMessage/DispatchMessageW`；
- `request_stop()` 调用 `PostThreadMessageW(thread_id, WM_QUIT, 0, 0)`；
- finally 调用 `UnhookWindowsHookEx`；
- 为 GetModuleHandleW、Set/Call/UnhookWindowsHookEx、PostThreadMessageW 声明 64 位安全 ctypes 签名；
- session 持有取消 Event，安装前后均检查；
- start/stop join 超时且线程仍存活时保留 session/thread 引用，标记 stopping 并禁止重复安装；
- `sys.platform != "win32"` 时 session 安装失败但模块可安全导入。

原生 session 使用以下完整边界实现，类型签名在模块导入时不触发 Win32 调用：

```python
class _WindowsHookSession:
    WH_KEYBOARD_LL = 13
    WM_KEYDOWN = 0x0100
    WM_SYSKEYDOWN = 0x0104
    WM_QUIT = 0x0012

    def __init__(self) -> None:
        self.started = Event()
        self.install_ok = False
        self.error_message = ""
        self._thread_id = 0
        self._hook = None
        self._callback = None

    def run(self, on_activity: Callable[[], object]) -> None:
        if sys.platform != "win32":
            self.error_message = "当前版本仅支持 Windows"
            self.started.set()
            return
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        self._thread_id = int(kernel32.GetCurrentThreadId())
        hook_proc_type = ctypes.WINFUNCTYPE(
            ctypes.c_ssize_t,
            ctypes.c_int,
            wintypes.WPARAM,
            wintypes.LPARAM,
        )

        @hook_proc_type
        def callback(n_code: int, w_param: int, l_param: int) -> int:
            if n_code >= 0 and int(w_param) in {self.WM_KEYDOWN, self.WM_SYSKEYDOWN}:
                on_activity()
            return int(user32.CallNextHookEx(self._hook, n_code, w_param, l_param))

        self._callback = callback
        self._hook = user32.SetWindowsHookExW(
            self.WH_KEYBOARD_LL,
            callback,
            kernel32.GetModuleHandleW(None),
            0,
        )
        if not self._hook:
            self.error_message = f"无法安装 Windows 键盘监听（错误码 {ctypes.get_last_error()}）"
            self.started.set()
            return
        self.install_ok = True
        self.started.set()
        message = wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(message))
                user32.DispatchMessageW(ctypes.byref(message))
        finally:
            if self._hook:
                user32.UnhookWindowsHookEx(self._hook)
                self._hook = None

    def request_stop(self) -> None:
        if sys.platform != "win32" or not self._thread_id:
            return
        import ctypes

        ctypes.windll.user32.PostThreadMessageW(self._thread_id, self.WM_QUIT, 0, 0)
```

- [ ] **步骤 5：运行全部键盘平台测试并提交**

运行：`python -m pytest tests/test_keyboard_activity.py -q`

预期：PASS。

```bash
git add src/petnest/platforms/windows_keyboard.py tests/test_keyboard_activity.py
git commit -m "feat: 监听 Windows 全局键盘活动"
```

### 任务 4：新增默认关闭设置和键盘活动卡片

**文件：**
- 修改：`src/petnest/models/settings.py`
- 修改：`src/petnest/core/settings_manager.py`
- 修改：`src/petnest/ui/settings_center_dialog.py`
- 修改：`tests/test_settings_manager.py`
- 修改：`tests/test_settings_dialog.py`

- [ ] **步骤 1：编写 schema 27、默认关闭和 UI 平台状态失败测试**

```python
def test_schema_26_adds_disabled_keyboard_working(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text('{"schema_version":26}', encoding="utf-8")

    loaded = SettingsManager(path).load()

    assert loaded.schema_version == 27
    assert loaded.keyboard_working_enabled is False


def test_keyboard_working_round_trips_and_rejects_non_boolean(tmp_path: Path) -> None:
    manager = SettingsManager(tmp_path / "settings.json")
    manager.save(Settings(keyboard_working_enabled=True))
    assert manager.load().keyboard_working_enabled is True
    assert Settings.from_dict({"keyboard_working_enabled": "yes"}).keyboard_working_enabled is False


def test_keyboard_activity_card_defaults_off_and_persists(qtbot) -> None:
    dialog = SettingsDialog(
        Settings(),
        keyboard_activity_supported=True,
        keyboard_activity_status="已关闭",
        initial_section="mouse_behavior",
    )
    qtbot.addWidget(dialog)

    assert dialog.keyboard_working_input.isChecked() is False
    dialog.keyboard_working_input.setChecked(True)
    assert dialog.updated_settings().keyboard_working_enabled is True


def test_keyboard_activity_card_is_disabled_outside_windows(qtbot) -> None:
    dialog = SettingsDialog(
        Settings(keyboard_working_enabled=True),
        keyboard_activity_supported=False,
        keyboard_activity_status="当前版本仅支持 Windows",
        initial_section="mouse_behavior",
    )
    qtbot.addWidget(dialog)

    assert not dialog.keyboard_working_input.isEnabled()
    assert dialog.keyboard_activity_status_label.text() == "当前版本仅支持 Windows"
```

- [ ] **步骤 2：运行设置测试确认字段和控件不存在**

运行：`python -m pytest tests/test_settings_manager.py tests/test_settings_dialog.py -q -k "keyboard or schema_26"`

预期：FAIL。

- [ ] **步骤 3：实现 schema 27 和默认关闭迁移**

```python
# settings.py
SCHEMA_VERSION = 27
keyboard_working_enabled: bool = False
```

在 `from_dict` 的布尔归一化中加入 `("keyboard_working_enabled", False)`。

```python
# settings_manager.py
if version == 26:
    migrated.setdefault("keyboard_working_enabled", False)
    migrated["schema_version"] = Settings.SCHEMA_VERSION
```

- [ ] **步骤 4：在“鼠标与行为”页添加键盘活动卡片**

构造器增加：

```python
keyboard_activity_supported: bool = False,
keyboard_activity_status: str = "已关闭",
```

卡片包含：

- `keyboard_working_input = ToggleSwitch("敲键盘时播放工作动作")`；
- 隐私说明；
- `keyboard_activity_status_label`；
- working 回退 idle 时的黄色动作缺失提示；
- unsupported 时禁用开关但保留已保存值；
- `updated_settings()` 写回字段。

- [ ] **步骤 5：运行设置测试并提交**

运行：`python -m pytest tests/test_settings_manager.py tests/test_settings_dialog.py -q`

预期：PASS。

```bash
git add src/petnest/models/settings.py src/petnest/core/settings_manager.py src/petnest/ui/settings_center_dialog.py tests/test_settings_manager.py tests/test_settings_dialog.py
git commit -m "feat: 添加键盘工作动画设置"
```

### 任务 5：装配 Qt relay、1.5 秒窗口和 Codex/Wake 仲裁

**文件：**
- 修改：`src/petnest/app.py`
- 修改：`tests/test_app_and_platforms.py`
- 修改：`tests/test_codex_link.py`
- 修改：`tests/test_state_machine.py`

- [ ] **步骤 1：扩展应用替身并编写生命周期失败测试**

```python
def _keyboard_application(
    tmp_path: Path,
    *,
    monitor: _KeyboardActivityMonitor,
    keyboard_enabled: bool,
    platform_adapter=None,
) -> PetNest:
    manager = SettingsManager(tmp_path / "settings.json")
    manager.save(
        Settings(
            keyboard_working_enabled=keyboard_enabled,
            codex_link_enabled=False,
            work_countdown_enabled=False,
            system_bored_seconds=1,
            system_sleep_seconds=2,
        )
    )
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    return PetNest(
        pets_root=tmp_path / "pets",
        settings_manager=manager,
        platform_adapter=platform_adapter,
        keyboard_activity_monitor=monitor,
        enable_tray=False,
    )


class _KeyboardActivityMonitor:
    supported = True

    def __init__(self, *, start_ok: bool = True) -> None:
        self.start_ok = start_ok
        self.started = 0
        self.stopped = 0
        self.callback = None
        self.status_message = "已关闭"

    def start(self, callback) -> bool:
        self.started += 1
        self.callback = callback
        self.status_message = "监听正常" if self.start_ok else "监听不可用"
        return self.start_ok

    def stop(self) -> None:
        self.stopped += 1
        self.callback = None
        self.status_message = "已关闭"


def test_keyboard_monitor_default_off_and_enable_disable_lifecycle(qtbot, tmp_path: Path) -> None:
    monitor = _KeyboardActivityMonitor()
    application = _keyboard_application(
        tmp_path,
        monitor=monitor,
        keyboard_enabled=False,
    )
    application.start()
    assert monitor.started == 0

    application.apply_settings(replace(application.settings, keyboard_working_enabled=True))
    assert monitor.started == 1
    application.apply_settings(replace(application.settings, keyboard_working_enabled=False))
    assert monitor.stopped == 1
    application.shutdown()


def test_keyboard_activity_uses_1500ms_window_without_restarting_animation(qtbot, tmp_path: Path) -> None:
    monitor = _KeyboardActivityMonitor()
    application = _keyboard_application(
        tmp_path,
        monitor=monitor,
        keyboard_enabled=True,
    )
    application.start()
    assert monitor.callback is not None

    monitor.callback()
    assert application.window.current_action == "working"
    assert application.keyboard_activity_timer.interval() == 1_500
    monitor.callback()
    assert application.window.current_action == "working"

    application._finish_keyboard_activity()
    assert application.window.current_action == "idle"
    application.shutdown()
```

- [ ] **步骤 2：编写 Codex 同时运行和 review 恢复测试**

```python
def _keyboard_codex_application(tmp_path: Path) -> tuple[PetNest, _KeyboardActivityMonitor]:
    monitor = _KeyboardActivityMonitor()
    application = _keyboard_application(
        tmp_path,
        monitor=monitor,
        keyboard_enabled=True,
    )
    application.settings = replace(application.settings, codex_link_enabled=True)
    return application, monitor


def test_keyboard_timeout_does_not_cancel_codex_working(qtbot, tmp_path: Path) -> None:
    application, monitor = _keyboard_codex_application(tmp_path)
    application.start()
    application.codex_link.consume(_log_event("UserPromptSubmit"))
    monitor.callback()

    application._finish_keyboard_activity()

    assert application.window.current_action == "working"
    application.shutdown()


def test_codex_review_finishes_back_to_active_keyboard(qtbot, tmp_path: Path) -> None:
    application, monitor = _keyboard_codex_application(tmp_path)
    application.start()
    monitor.callback()
    application.codex_link.consume(_log_event("Stop"))
    assert application.window.current_action == "review"

    application._finish_codex_review_animation()

    assert application.window.current_action == "working"
    assert application.codex_link.snapshot.unread_review_count == 1
    application.shutdown()
```

- [ ] **步骤 3：编写键盘从 sleep 恢复抑制 wake、鼠标恢复保留 wake 测试**

```python
def _sleeping_keyboard_application(tmp_path: Path) -> tuple[PetNest, _KeyboardActivityMonitor]:
    adapter = _IdleAdapter(idle_seconds=3)
    monitor = _KeyboardActivityMonitor()
    application = _keyboard_application(
        tmp_path,
        monitor=monitor,
        keyboard_enabled=True,
        platform_adapter=adapter,
    )
    application._check_system_idle()
    adapter.idle_seconds = 0
    return application, monitor


def _sleeping_application(tmp_path: Path) -> PetNest:
    adapter = _IdleAdapter(idle_seconds=3)
    application = _keyboard_application(
        tmp_path,
        monitor=_KeyboardActivityMonitor(),
        keyboard_enabled=False,
        platform_adapter=adapter,
    )
    application._check_system_idle()
    adapter.idle_seconds = 0
    return application


def test_keyboard_activity_from_sleep_suppresses_duplicate_wake(qtbot, tmp_path: Path) -> None:
    application, monitor = _sleeping_keyboard_application(tmp_path)
    application.start()
    monitor.callback()
    application._check_system_idle()

    assert application.window.current_action == "working"


def test_mouse_recovery_without_keyboard_still_plays_wake(qtbot, tmp_path: Path) -> None:
    application = _sleeping_application(tmp_path)
    application.start()
    application._check_system_idle()

    assert application.window.current_action == "wake"
```

- [ ] **步骤 4：实现应用装配**

构造器增加可注入参数：

```python
keyboard_activity_monitor: KeyboardActivityMonitor | None = None,
```

新增：

```python
class _KeyboardActivityRelay(QObject):
    activity = Signal()

self.work_activity = WorkActivityCoordinator(self.event_bus.publish)
self.codex_link = CodexLinkCoordinator(
    self.work_activity.handle_codex_event,
    self._handle_codex_snapshot,
)
self.keyboard_activity_monitor = keyboard_activity_monitor or create_keyboard_activity_monitor()
self._keyboard_activity_relay = _KeyboardActivityRelay(self.window)
self._keyboard_activity_relay.activity.connect(self._handle_keyboard_activity)
self.keyboard_activity_timer = QTimer(self.window)
self.keyboard_activity_timer.setSingleShot(True)
self.keyboard_activity_timer.setInterval(1_500)
self.keyboard_activity_timer.timeout.connect(self._finish_keyboard_activity)
```

实现：

- `_configure_keyboard_activity()`：按设置和 supported 启停监听；
- `_handle_keyboard_activity()`：主线程调用 `keyboard_activity_started()` 并重启 timer；
- `_finish_keyboard_activity()`：释放键盘来源；
- `_finish_codex_review_animation()`：改用 coordinator；
- `_check_system_idle()`：若事件是 `system.wake` 且 keyboard_active，抑制该次 wake；
- `apply_settings()` 检测开关变化；
- `start()` 配置监听；
- `shutdown()` 先停止 timer 和 monitor，再继续退出；
- 打开设置页时传入 supported/status；
- 切换宠物后如有效状态仍为 working，重新向新窗口应用当前有效事件。

- [ ] **步骤 5：运行应用、Codex 和状态机回归并提交**

运行：

```bash
python -m pytest tests/test_work_activity.py tests/test_keyboard_activity.py tests/test_app_and_platforms.py tests/test_codex_link.py tests/test_state_machine.py -q
```

预期：PASS。

```bash
git add src/petnest/app.py tests/test_app_and_platforms.py tests/test_codex_link.py tests/test_state_machine.py
git commit -m "feat: 联动键盘与 Codex 工作动画"
```

### 任务 6：审查、完整验证和主分支集成

**文件：**
- 验证：上述全部源码和测试
- 文档：`docs/superpowers/specs/2026-08-21-keyboard-working-animation-design.md`
- 文档：`docs/superpowers/plans/2026-08-21-keyboard-working-animation.md`

- [ ] **步骤 1：运行编译和 diff 检查**

```bash
python -m compileall -q src/petnest
git diff --check
```

预期：退出码为 0。

- [ ] **步骤 2：运行键盘/Codex 定向测试**

```bash
python -m pytest tests/test_work_activity.py tests/test_keyboard_activity.py tests/test_settings_manager.py tests/test_settings_dialog.py tests/test_app_and_platforms.py tests/test_codex_link.py tests/test_state_machine.py -q
```

预期：0 failed。

- [ ] **步骤 3：运行完整测试**

运行：`python -m pytest -q`

预期：0 failed；当前平台无法创建 symlink/junction 的既有测试允许 SKIP。

- [ ] **步骤 4：请求独立代码审查**

审查重点：

- 原生回调是否可能泄露键值；
- Hook 是否始终调用 `CallNextHookEx`；
- 安装失败、重复 start/stop 和退出是否安全；
- 后台线程是否直接操作 Qt；
- Codex 与键盘任一来源停止是否误发 idle；
- waiting/failed/review 优先级；
- keyboard wake 是否只抑制同一次键盘恢复；
- macOS 是否安全降级；
- 默认关闭和 schema 迁移。

- [ ] **步骤 5：在 Windows 主分支做实机验证**

1. 默认关闭时确认没有键盘 Hook 线程；
2. 开启并保存，在其他应用连续输入，确认立即 working；
3. 停止输入 1.5 秒，确认恢复；
4. Codex running 时停止输入，确认仍 working；
5. Codex review 时输入，确认 review 先播放，随后恢复 working；
6. 从 sleep 敲键盘，确认直接 working；
7. 关闭开关，确认解除监听；
8. 重启应用，确认设置持久化且默认策略正确。

- [ ] **步骤 6：整理中文提交并集成主分支**

主分支建议整理为：

```text
docs: 设计键盘工作动画
feat: 监听 Windows 键盘活动
feat: 联动键盘与 Codex 工作动画
```

只集成本功能文件，保留用户未跟踪素材和无关未提交修改。集成后在主分支复跑完整测试并重启 PetNest。
