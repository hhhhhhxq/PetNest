# 鼠标跟随模式实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 让桌宠可缩小并鼠标穿透地跟随全局光标，移动时临时播放行走动作，静止时恢复既有状态。

**架构：** 新建纯逻辑 `MouseFollowController` 负责采样、静止判定和屏幕边界定位；`PetWindow` 提供不破坏状态机的动作覆盖层；应用层负责计时器、设置和菜单入口。

**技术栈：** Python 3.12、PySide6、pytest、pytest-qt。

---

## 文件与职责

- 创建：`src/petnest/core/mouse_follow.py` — 鼠标采样状态与安全定位的纯逻辑。
- 修改：`src/petnest/models/settings.py`、`src/petnest/core/settings_manager.py` — 跟随偏好及迁移。
- 修改：`src/petnest/ui/pet_window.py` — 缩放/动作覆盖、鼠标穿透、倒计时隐藏。
- 修改：`src/petnest/app.py`、`src/petnest/ui/settings_dialog.py`、`src/petnest/ui/tray_icon.py` — 计时器与设置、菜单入口。
- 修改：`tests/test_settings_manager.py`、`tests/test_pet_window.py`；创建 `tests/test_mouse_follow.py` — 行为覆盖。

### 任务 1：跟随计算核心

- [ ] **步骤 1：编写失败测试**

在 `tests/test_mouse_follow.py` 测试：首次采样不移动；坐标变化进入 moving；150ms 后变为静止；光标接近右下边界时目标位置翻转且完整位于 `QRect` 内。

- [ ] **步骤 2：运行失败测试**

运行：`pytest tests/test_mouse_follow.py -v`
预期：FAIL，原因是 `petnest.core.mouse_follow` 不存在。

- [ ] **步骤 3：实现纯逻辑**

创建 `MouseFollowController(stationary_ms=150, offset=8)`，提供 `sample(cursor: QPoint, now_ms: int) -> bool`、主方向和水平朝向，以及 `target_position(cursor: QPoint, pet_size: QSize, screen: QRect) -> QPoint`；后者优先右下，空间不足时翻转，最终 clamp 至屏幕可用区域。

- [ ] **步骤 4：验证**

运行：`pytest tests/test_mouse_follow.py -v`
预期：PASS。

### 任务 2：窗口显示覆盖层

- [ ] **步骤 1：编写失败测试**

在 `tests/test_pet_window.py` 创建含 `walk` 的测试包，测试 `set_follow_motion(True)` 播放 walk，系统状态变更不打断画面；`set_follow_motion(False)` 恢复状态机当前动作。另测无 walk 时使用 drag、启用跟随隐藏倒计时并设置 `WindowTransparentForInput`。

- [ ] **步骤 2：运行失败测试**

运行：`pytest tests/test_pet_window.py -k follow -v`
预期：FAIL，原因是 `PetWindow` 尚无跟随接口。

- [ ] **步骤 3：实现窗口接口**

在 `PetWindow` 增加 `set_follow_mode(enabled, scale)` 与 `set_follow_motion(moving)`。保存普通缩放，跟随时缩放为 `max(min_scale, normal_scale * scale)`；用 `_follow_action` 覆盖 `_play_current_action`，停止时恢复状态机动作。跟随动作完成后在移动期间重新播放；倒计时保留原文本但不绘制、不占尺寸；开启 `WindowTransparentForInput` 并重新 show 应用旗标。

- [ ] **步骤 4：验证**

运行：`pytest tests/test_pet_window.py -k follow -v`
预期：PASS。

### 任务 3：设置和运行时控制

- [ ] **步骤 1：编写失败测试**

在 `tests/test_settings_manager.py` 测试新用户默认 `mouse_follow_enabled=False`、`mouse_follow_scale=0.45`，并测试保存/读取及旧 schema 升级。

- [ ] **步骤 2：运行失败测试**

运行：`pytest tests/test_settings_manager.py -k follow -v`
预期：FAIL，新字段不存在。

- [ ] **步骤 3：实现控制路径**

将设置 schema 升级，设置页加入“跟随鼠标”和百分比输入。`PetNest` 以 20ms `QTimer` 读取 `QCursor.pos()`，用控制器移动窗口并调用 `set_follow_motion`；停用后停止 timer、恢复普通显示并保存当前静态位置。托盘与宠物右键菜单加入同一可勾选 action。

- [ ] **步骤 4：验证**

运行：`pytest tests/test_settings_manager.py -k follow -v && pytest tests/test_app_and_platforms.py tests/test_pet_window.py -v`
预期：PASS。

### 任务 4：完整验证与提交

- [ ] **步骤 1：运行全量测试**

运行：`pytest -q`
预期：全部通过；平台符号链接测试允许保持既有 skipped。

- [ ] **步骤 2：检查改动范围**

运行：`git diff --check && git status --short`
预期：无空白错误；不暂存 `pets/`、`tmp/` 或个人导出文件。

- [ ] **步骤 3：提交**

运行：`git add src/petnest/core/mouse_follow.py src/petnest/models/settings.py src/petnest/core/settings_manager.py src/petnest/ui/pet_window.py src/petnest/app.py src/petnest/ui/settings_dialog.py src/petnest/ui/tray_icon.py tests/test_mouse_follow.py tests/test_settings_manager.py tests/test_pet_window.py docs/superpowers/specs/2026-08-10-mouse-follow-design.md docs/superpowers/plans/2026-08-10-mouse-follow-mode.md && git commit -m "feat: add mouse follow mode"`
