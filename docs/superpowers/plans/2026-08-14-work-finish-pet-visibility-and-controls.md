# 下班提醒宠物显隐与大按钮实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 全屏下班提醒期间可靠地临时隐藏桌面宠物，并在提醒结束时按用户最终意图恢复；同时将左上角操作区改成更醒目的纵向大按钮。

**架构：** 新增一个不依赖 Qt 的显隐租约对象，仅负责记录“提醒是否拥有恢复责任”；应用层集中执行窗口显隐、倒计时附属窗口和托盘文字同步。所有提醒结束路径调用同一个关闭入口，托盘和二次启动的显示操作会接管租约，异常恢复失败后仍以窗口真实状态提供“显示”保底。

**技术栈：** Python 3.12、PySide6、pytest、pytest-qt、不可变/小状态对象、Qt signals。

---

## 文件结构

- 创建 `src/petnest/core/pet_visibility_lease.py`：实现纯状态的提醒显隐租约，不操作 Qt 窗口。
- 创建 `tests/test_pet_visibility_lease.py`：覆盖获取、重复获取、释放和用户接管。
- 修改 `src/petnest/ui/tray_icon.py`：托盘菜单依据真实窗口状态决定下一步动作，并提供公开同步方法。
- 修改 `src/petnest/app.py`：集中显隐、管理租约、统一关闭提醒和异常恢复。
- 修改 `src/petnest/ui/work_finish_reminder.py`：暴露控制窗被外部关闭信号，并调整操作面板布局。
- 修改 `tests/test_app_and_platforms.py`：验证提醒生命周期、托盘接管、异常保底、切换/重载和退出行为。
- 修改 `tests/test_work_finish_reminder.py`：验证外部关闭信号和纵向大按钮布局。
- 修改或创建托盘测试文件：在现有托盘测试位置验证菜单文字始终匹配 `window.isVisible()`。

### 任务 1：纯显隐租约

**文件：**
- 创建：`src/petnest/core/pet_visibility_lease.py`
- 创建：`tests/test_pet_visibility_lease.py`

- [ ] **步骤 1：编写失败的租约状态测试**

```python
from petnest.core.pet_visibility_lease import PetVisibilityLease


def test_visible_pet_creates_one_restore_responsibility() -> None:
    lease = PetVisibilityLease()

    assert lease.acquire(was_visible=True)
    assert not lease.acquire(was_visible=False)
    assert lease.release()
    assert not lease.release()


def test_hidden_pet_never_creates_restore_responsibility() -> None:
    lease = PetVisibilityLease()

    assert not lease.acquire(was_visible=False)
    assert not lease.release()


def test_user_takeover_cancels_automatic_restore() -> None:
    lease = PetVisibilityLease()
    assert lease.acquire(was_visible=True)

    lease.user_took_control()

    assert not lease.release()


def test_cancel_for_shutdown_never_requests_show() -> None:
    lease = PetVisibilityLease()
    assert lease.acquire(was_visible=True)

    lease.cancel()

    assert not lease.is_active
    assert not lease.release()
```

- [ ] **步骤 2：运行测试并确认因模块缺失而失败**

运行：

```powershell
& '..\..\.venv\Scripts\python.exe' -m pytest tests/test_pet_visibility_lease.py -q
```

预期：收集阶段 `ModuleNotFoundError: petnest.core.pet_visibility_lease`。

- [ ] **步骤 3：实现最小租约对象**

```python
from dataclasses import dataclass


@dataclass(slots=True)
class PetVisibilityLease:
    is_active: bool = False
    _restore_required: bool = False

    def acquire(self, *, was_visible: bool) -> bool:
        if self.is_active:
            return False
        self.is_active = True
        self._restore_required = bool(was_visible)
        return self._restore_required

    def user_took_control(self) -> None:
        self.cancel()

    def release(self) -> bool:
        should_restore = self.is_active and self._restore_required
        self.cancel()
        return should_restore

    def cancel(self) -> None:
        self.is_active = False
        self._restore_required = False
```

导出 `PetVisibilityLease`，不加入定时器、回调或 Qt 依赖。

- [ ] **步骤 4：运行测试确认通过**

运行同一步骤 2，预期 `4 passed`。

- [ ] **步骤 5：提交任务 1**

```powershell
git add -- src/petnest/core/pet_visibility_lease.py tests/test_pet_visibility_lease.py
git commit -m "feat: track work-finish pet visibility lease"
```

### 任务 2：集中宠物显隐并同步托盘真实状态

**文件：**
- 修改：`src/petnest/ui/tray_icon.py:225-236`
- 修改：`src/petnest/app.py:405-428,561-564,1360-1400`
- 修改：`tests/test_app_and_platforms.py`
- 测试：包含 `PetTrayIcon` 的现有测试文件；若不存在则创建 `tests/test_tray_icon.py`

- [ ] **步骤 1：编写托盘真实状态的失败测试**

```python
def test_tray_visibility_action_uses_actual_window_state(qtbot, package) -> None:
    window = PetWindow(package)
    qtbot.addWidget(window)
    requested: list[bool] = []
    tray = PetTrayIcon(window, on_visibility_changed=requested.append)

    window.hide()
    tray.sync_visibility_action()
    assert tray.toggle_visibility_action.text() == "显示"

    tray.toggle_visibility_action.trigger()
    assert requested == [True]
```

测试必须证明回调存在时托盘不先自行修改窗口，而是把由真实状态计算出的目标值交给应用。

- [ ] **步骤 2：编写提醒开始隐藏和结束恢复的失败测试**

在 `tests/test_app_and_platforms.py` 的下班提醒测试旁添加：

```python
def test_work_finish_prompt_temporarily_hides_and_restores_visible_pet(qtbot, tmp_path) -> None:
    application = _work_finish_application(qtbot, tmp_path)
    application.window.show()

    _trigger_work_finish(application)
    assert not application.window.isVisible()

    application.work_finish_reminder.control_window.continue_button.click()
    assert application.window.isVisible()
    application.shutdown()


def test_work_finish_prompt_does_not_restore_pet_hidden_before_prompt(qtbot, tmp_path) -> None:
    application = _work_finish_application(qtbot, tmp_path)
    application.window.hide()

    _trigger_work_finish(application)
    application.work_finish_reminder.control_window.finish_button.click()

    assert not application.window.isVisible()
    application.shutdown()
```

测试辅助函数创建全天工作日设置，并用 `17:59:59 -> 18:00:00` 两次刷新稳定触发提醒。

- [ ] **步骤 3：运行新测试确认按预期失败**

运行：

```powershell
& '..\..\.venv\Scripts\python.exe' -m pytest tests/test_app_and_platforms.py -k "work_finish_prompt_temporarily or hidden_before_prompt" tests/test_tray_icon.py -q
```

预期：宠物在提示后仍可见，且 `sync_visibility_action` 尚不存在。

- [ ] **步骤 4：实现托盘公开同步入口**

将托盘显隐改为：

```python
def sync_visibility_action(self) -> None:
    self.toggle_visibility_action.setText("隐藏" if self.window.isVisible() else "显示")

def _toggle_visibility(self) -> None:
    target_visible = not self.window.isVisible()
    if self._on_visibility_changed is not None:
        self._on_visibility_changed(target_visible)
    else:
        self.window.setVisible(target_visible)
    self.sync_visibility_action()
```

构造结束时调用一次 `sync_visibility_action()`。

- [ ] **步骤 5：在应用层实现集中显隐和租约获取/释放**

在 `PetNest.__init__` 创建 `PetVisibilityLease`。拆分两个入口：

```python
def _apply_pet_visibility(self, visible: bool) -> None:
    try:
        self.window.setVisible(visible)
        self.work_countdown.set_pet_visible(visible)
    finally:
        if self.tray is not None:
            self.tray.sync_visibility_action()

def _set_pet_visibility(self, visible: bool) -> None:
    self._work_finish_visibility_lease.user_took_control()
    self._apply_pet_visibility(visible)

def _hide_pet_for_work_finish(self) -> None:
    if self._work_finish_visibility_lease.acquire(was_visible=self.window.isVisible()):
        self._apply_pet_visibility(False)

def _restore_pet_after_work_finish(self) -> None:
    should_restore = self._work_finish_visibility_lease.release()
    if should_restore:
        try:
            self._apply_pet_visibility(True)
        except Exception:
            LOGGER.exception("下班提醒结束后恢复宠物失败，可从托盘菜单选择‘显示’")
            if self.tray is not None:
                self.tray.sync_visibility_action()
```

`reveal()` 继续调用 `_set_pet_visibility(True)`，从而表示用户接管。

- [ ] **步骤 6：在提醒显示与关闭路径接入租约**

显示前调用 `_hide_pet_for_work_finish()`。增加统一入口：

```python
def _close_work_finish_reminder(self, *, restore_pet: bool = True) -> None:
    self.work_finish_reminder.hide()
    self.work_countdown.set_work_finish_prompt_visible(False)
    if restore_pet:
        self._restore_pet_after_work_finish()
    else:
        self._work_finish_visibility_lease.cancel()
```

“下班”“再加一会”、`_record_work_finish_state()` 收到 `None/finished` 时都使用该入口；关闭应用时使用 `restore_pet=False`，避免退出过程中重新显示。

- [ ] **步骤 7：运行任务 2 测试确认通过**

运行：

```powershell
& '..\..\.venv\Scripts\python.exe' -m pytest tests/test_pet_visibility_lease.py tests/test_tray_icon.py tests/test_app_and_platforms.py -k "visibility or work_finish or reveal" -q
```

预期所有选中测试通过。

- [ ] **步骤 8：提交任务 2**

```powershell
git add -- src/petnest/ui/tray_icon.py src/petnest/app.py tests/test_tray_icon.py tests/test_app_and_platforms.py
git commit -m "feat: restore pets after work-finish reminder"
```

### 任务 3：异常关闭、重复提醒、切换与退出边界

**文件：**
- 修改：`src/petnest/ui/work_finish_reminder.py`
- 修改：`src/petnest/app.py`
- 修改：`tests/test_work_finish_reminder.py`
- 修改：`tests/test_app_and_platforms.py`

- [ ] **步骤 1：编写控制窗外部关闭信号的失败测试**

```python
def test_external_control_window_close_emits_dismissed(qtbot, tmp_path) -> None:
    reminder = WorkFinishReminder()
    qtbot.addWidget(reminder.animation_window)
    qtbot.addWidget(reminder.control_window)
    dismissed: list[bool] = []
    reminder.dismissed.connect(lambda: dismissed.append(True))
    reminder.show_for(_package(tmp_path), QRect(0, 0, 1000, 800), datetime.now())

    reminder.control_window.close()

    assert dismissed == [True]
```

另加 `shutdown()` 不发 `dismissed` 的测试，防止退出触发恢复。

- [ ] **步骤 2：编写应用边界失败测试**

覆盖以下真实行为：

```python
def test_tray_show_during_prompt_takes_over_restore(...):
    _trigger_work_finish(application)
    application._set_pet_visibility(True)
    application.work_finish_reminder.control_window.continue_button.click()
    assert application.window.isVisible()


def test_repeated_prompt_and_pet_switch_keep_pet_hidden_until_close(...):
    _trigger_work_finish(application)
    application._show_work_finish_prompt(application.work_countdown.work_finish_state)
    application.switch_pet("second_pet")
    assert not application.window.isVisible()
    application.work_finish_reminder.control_window.finish_button.click()
    assert application.window.isVisible()


def test_restore_failure_leaves_tray_show_action(..., monkeypatch):
    _trigger_work_finish(application)
    monkeypatch.setattr(application.window, "setVisible", _fail_only_when_showing)
    application.work_finish_reminder.control_window.finish_button.click()
    assert application.tray.toggle_visibility_action.text() == "显示"


def test_shutdown_cancels_lease_without_showing_pet(...):
    _trigger_work_finish(application)
    application.shutdown()
    assert not application.window.isVisible()
```

- [ ] **步骤 3：运行边界测试确认失败**

运行：

```powershell
& '..\..\.venv\Scripts\python.exe' -m pytest tests/test_work_finish_reminder.py tests/test_app_and_platforms.py -k "external_control or tray_show_during or repeated_prompt or restore_failure or shutdown_cancels" -q
```

预期：缺少 `dismissed` 信号、重复获取或恢复异常行为不符合断言。

- [ ] **步骤 4：实现外部关闭通知和关机抑制**

`WorkFinishControlWindow` 在 `closeEvent` 发出 `closed`；`WorkFinishReminder` 增加 `dismissed` 信号并维护 `_shutting_down`：

```python
def _control_closed(self) -> None:
    if not self._shutting_down:
        self.dismissed.emit()

def shutdown(self) -> None:
    self._shutting_down = True
    try:
        self.hide()
        self.animation_window.close()
        self.control_window.close()
    finally:
        self._shutting_down = False
```

应用收到 `dismissed` 后调用 `_close_work_finish_reminder()`，并用 `work_countdown.finish_work()` 将外部关闭收敛为当天已下班，避免每秒重新弹出。

- [ ] **步骤 5：修正显示失败和退出边界**

`_show_work_finish_prompt()` 使用 `try/except`：显示失败时关闭已显示层、释放租约并重新抛出供倒计时日志记录。`shutdown()` 在关闭提醒前先取消租约，再隐藏宠物，确保不会在退出过程中恢复。

切换和重载仍调用 `_refresh_visible_work_finish_reminder()`；租约的重复 `acquire()` 返回 `False`，因此不会覆盖第一次提示前的可见状态。

- [ ] **步骤 6：运行边界测试和相关回归**

运行：

```powershell
& '..\..\.venv\Scripts\python.exe' -m pytest tests/test_work_finish_reminder.py tests/test_app_and_platforms.py tests/test_work_countdown.py -q
```

预期全部通过，只有 Windows 无符号链接权限的既有 skip。

- [ ] **步骤 7：提交任务 3**

```powershell
git add -- src/petnest/ui/work_finish_reminder.py src/petnest/app.py tests/test_work_finish_reminder.py tests/test_app_and_platforms.py
git commit -m "fix: guarantee work-finish pet recovery"
```

### 任务 4：纵向大按钮面板

**文件：**
- 修改：`src/petnest/ui/work_finish_reminder.py:137-206`
- 修改：`tests/test_work_finish_reminder.py`

- [ ] **步骤 1：编写布局失败测试**

```python
def test_control_panel_uses_large_full_width_vertical_buttons(qtbot) -> None:
    control = WorkFinishControlWindow()
    qtbot.addWidget(control)
    control.show_for(QRect(0, 0, 1920, 1040), datetime.now())

    assert control.minimumWidth() >= 300
    assert control.finish_button.geometry().top() < control.continue_button.geometry().top()
    assert control.finish_button.width() == control.continue_button.width()
    assert control.finish_button.height() >= 56
    assert control.continue_button.height() >= 56
    assert control.finish_button.font().pointSize() >= 18
```

- [ ] **步骤 2：运行测试确认因现有横向小按钮失败**

运行：

```powershell
& '..\..\.venv\Scripts\python.exe' -m pytest tests/test_work_finish_reminder.py::test_control_panel_uses_large_full_width_vertical_buttons -q
```

预期：最小宽度、纵向位置或按钮高度断言失败。

- [ ] **步骤 3：实现纵向布局和尺寸**

- 控制窗 `setMinimumWidth(300)`。
- 内容边距改为约 `20, 18, 20, 20`，主布局间距约 12。
- 标题字号提升到约 20 px，倒计时约 14 px。
- 删除按钮 `QHBoxLayout`，直接把两个按钮依次加入主 `QVBoxLayout`。
- 两个按钮设置同一 `setMinimumHeight(56)` 和 expanding 水平 size policy。
- 按钮样式使用约 18 px 字号、12 px 圆角和更充足的 padding。

- [ ] **步骤 4：运行提醒 UI 测试确认通过**

运行：

```powershell
& '..\..\.venv\Scripts\python.exe' -m pytest tests/test_work_finish_reminder.py -q
```

预期全部通过。

- [ ] **步骤 5：提交任务 4**

```powershell
git add -- src/petnest/ui/work_finish_reminder.py tests/test_work_finish_reminder.py
git commit -m "style: enlarge work-finish decision controls"
```

### 任务 5：完整验证、集成与运行实例更新

**文件：**
- 不新增生产文件；只验证前述提交。

- [ ] **步骤 1：运行相关测试集合**

```powershell
& '..\..\.venv\Scripts\python.exe' -m pytest tests/test_pet_visibility_lease.py tests/test_tray_icon.py tests/test_work_finish_reminder.py tests/test_work_finish_state.py tests/test_work_countdown.py tests/test_app_and_platforms.py -q
```

预期全部通过，保留 Windows 符号链接权限 skip。

- [ ] **步骤 2：运行非应用装配完整套件**

```powershell
& '..\..\.venv\Scripts\python.exe' -m pytest -q --ignore=tests/test_app_and_platforms.py
```

预期 `0 failed`。

- [ ] **步骤 3：单独运行应用装配套件**

```powershell
& '..\..\.venv\Scripts\python.exe' -m pytest tests/test_app_and_platforms.py -q
```

预期 `0 failed`。单独进程避免现有程序更新后台线程在 Windows 全套退出时的已知不稳定性。

- [ ] **步骤 4：运行静态和包校验**

```powershell
git diff --check
$env:PYTHONPATH = (Resolve-Path 'src')
@'
from pathlib import Path
from petnest.core.package_validator import PackageValidator
result = PackageValidator().validate(Path(r'D:\installed\PetNest\pets\pingan'))
assert result.is_valid, result.errors
print('active pingan package valid')
'@ | & '..\..\.venv\Scripts\python.exe' -
```

- [ ] **步骤 5：完成前代码审查**

对设计提交后的所有差异逐文件检查，重点确认：租约只恢复自己隐藏的窗口、托盘真实状态同步、退出不恢复、外部关闭不重复弹出、异常不吞掉托盘保底。当前会话策略若禁止子代理，则执行同等范围的人工差异审查并记录结果。

- [ ] **步骤 6：使用 finishing-a-development-branch 收尾**

验证通过后提供本地合并、PR、保留或丢弃选项。若用户选择本地合并，合并到 `petnest-phase1` 后在合并结果上重跑步骤 1，并重启当前 `pythonw -m petnest` 实例加载新代码。
