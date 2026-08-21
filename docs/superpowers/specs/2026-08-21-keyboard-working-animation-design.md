# 键盘活动 Working 动画设计

## 背景与目标

PetNest 已能根据 Codex 任务状态播放 `working`，但用户在其他应用中实际敲键盘时，桌宠没有对应的工作反馈。本功能新增一个默认关闭的“键盘活动”开关：Windows 用户全局敲键盘时播放当前宠物的 working 动画，最后一次按键后 1.5 秒自动释放；同时开启 Codex 联动时，两种来源共享 working，不得互相错误取消。

目标：

- Windows 上识别全局键盘按下活动，不要求 PetNest 窗口获得焦点；
- 第一次按键立即进入 working，连续输入刷新 1.5 秒活动窗口；
- Codex running 与键盘活动合并为同一个有效 working 状态；
- Codex waiting、failed 和尚未播放完的 review 优先于键盘 working；
- 不记录或传递具体按键、输入内容、快捷键、输入法内容和目标窗口；
- 设置开关默认关闭，升级不得替用户开启；
- 第一版只支持 Windows；macOS 和其他平台安全显示暂不支持；
- 不破坏现有系统空闲、唤醒、鼠标交互和 Codex 气泡行为。

## 非目标

- 不统计键盘使用次数、速度或输入时长；
- 不识别具体字符、快捷键组合或应用程序；
- 不把鼠标活动算作键盘 working；
- 不在第一版实现 macOS 输入监控权限申请；
- 不新增独立的键盘动画素材槽位，继续使用当前 `agent.working` 解析出的动作；
- 不改变 Codex 日志、Hook、未读任务和气泡协议。

## 当前唤醒机制

现有 Windows 系统空闲检测每秒调用 `GetLastInputInfo`，得到距离最后一次系统输入的时间。它同时包含键盘和鼠标：超过阈值产生 `system.bored` / `system.sleep`，恢复输入时产生一次 `system.wake`。

键盘 working 不能复用该接口，因为它无法区分键盘和鼠标，也无法可靠表示持续输入。新功能使用独立的全局键盘活动监听；现有空闲与唤醒逻辑保持不变。

## 架构

### `KeyboardActivityMonitor`

新增平台无关协议，只暴露活动事件和能力状态：

```python
class KeyboardActivityMonitor(Protocol):
    @property
    def supported(self) -> bool: ...

    @property
    def status_message(self) -> str: ...

    def start(self, on_activity: Callable[[], object]) -> bool: ...

    def stop(self) -> None: ...
```

业务层只能收到无参数的 `on_activity()`，协议中没有键值、扫描码、窗口句柄或文本字段，从接口边界阻止内容进入 PetNest。

实现：

- `WindowsKeyboardActivityMonitor`：Windows 全局低级键盘 Hook；
- `UnsupportedKeyboardActivityMonitor`：macOS、Linux 和未知平台的显式安全降级；
- `create_keyboard_activity_monitor()`：根据 `sys.platform` 选择实现。

### Windows 监听线程

Windows 实现使用 `SetWindowsHookExW(WH_KEYBOARD_LL)`，在独立 daemon 线程中运行 Win32 消息循环：

- 只根据 Hook 消息是否为 `WM_KEYDOWN` 或 `WM_SYSKEYDOWN` 判断活动；
- 不解引用或保存 `KBDLLHOOKSTRUCT` 中的键码字段；
- 回调只触发无参数活动通知并立即调用 `CallNextHookEx`；
- Hook 安装失败时返回 `False` 并提供脱敏状态；
- `stop()` 使用线程消息结束循环、调用 `UnhookWindowsHookEx`，并做有界 join；
- 重复 start/stop 必须幂等；
- HHOOK/HMODULE 相关 Win32 API 必须声明 64 位安全 ctypes 签名；
- 会话持有取消 Event；安装或停止超时后若线程仍存活，monitor 保留引用并禁止重复 Hook；
- 非 Windows 环境导入该模块不得执行 Win32 调用。

原生 Hook 回调在后台线程执行，不能直接操作 Qt 或宠物状态。应用层使用 `_KeyboardActivityRelay(QObject)` 的无参数 Signal，将活动排队送回 Qt 主线程。

### `WorkActivityCoordinator`

新增纯 Python 仲裁器，统一保存：

```text
codex_state: idle | running | waiting | failed | review
keyboard_active: bool
codex_review_animation_finished: bool
```

职责：

- 接收 CodexLinkCoordinator 原本准备发布的宠物事件；
- 接收键盘活动开始和超时释放；
- 根据优先级决定唯一的最终宠物事件；
- 不处理气泡、未读、日志或 Hook；
- 有效状态变化时发布；连续按键在 working 已生效时不会重启动画，但允许重新请求 working，使被 drag/click 或最短播放保护拒绝的首次请求能够恢复。

CodexLinkCoordinator 仍负责多个任务的 running/waiting/failed/review 聚合，但其宠物事件发布函数改为传入 `WorkActivityCoordinator.handle_codex_event`；仲裁器再把最终事件发送给 EventBus。

## 状态与优先级

优先级：

```text
Codex waiting / failed
    高于
尚未播放完的 Codex review
    高于
Codex running 或 keyboard_active
    高于
idle / hover
```

### 真值表

| Codex 状态 | 键盘活动 | 最终动作 |
|---|---:|---|
| idle | false | idle / hover 上下文 |
| idle | true | working |
| running | false | working |
| running | true | working，不重播 |
| waiting | 任意 | waiting |
| failed | 任意 | error |
| review，动画未结束 | 任意 | review |
| review，动画已结束 | true | working |
| review，动画已结束 | false | idle / hover 上下文 |

### 来源结束规则

- 键盘超时但 Codex 仍 running：保持 working，不发送 idle；
- Codex 变 idle 但键盘仍 active：把 Codex 的 idle 收敛为 working；
- 两个来源都结束：发送 `agent.idle`，由现有状态机恢复 idle/hover 上下文；
- Codex 进入 waiting/failed：立即按现有高优先级动作展示；
- Codex 进入 review：完整播放一次 review；
- review 计时完成：调用仲裁器 `finish_codex_review_animation()`，根据 keyboard_active 恢复 working 或 idle；
- review 未读气泡继续保留，动画恢复 working 不等于已读。

### 与系统唤醒的关系

- 键盘功能关闭时，现有 `GetLastInputInfo → system.wake` 行为完全不变；
- 键盘功能开启且第一次按键发生在 bored/sleep 状态时，直接进入 working，并抑制由同一次键盘输入产生的 `system.wake` 动画；
- 鼠标导致的恢复输入仍播放现有 wake；
- Codex 或键盘工作状态有效期间不进入新的 bored/sleep；来源结束后由下一次空闲检查正常进入；
- 这样避免 wake 与 working 在一秒系统空闲轮询内互相覆盖，同时符合 working 高于 idle/bored/sleep 的优先级。

## 键盘活动窗口

应用层维护单次 Qt Timer：

```text
第一次活动：keyboard_active = true
每次后续活动：重新开始 1500ms timer
timer 到期：keyboard_active = false
```

要求：

- 第一次按键立即生效；
- 连续按键刷新 timer；当前已经是 working 时，同动作请求由状态机安全忽略，不重启动画；
- 若首次 working 请求被不可中断动作暂时拒绝，后续按键继续请求，直到允许切换或活动超时；
- 关闭设置时停止 timer、解除 Hook 并释放键盘来源；
- 应用退出时先停止原生监听，再销毁 Qt relay；
- 应用暂停动画不停止活动状态记录，恢复播放后按当前有效状态呈现。

## 与宠物动作和状态机的关系

键盘功能复用 `agent.working` 绑定及现有 fallback：

```text
agent.working 绑定动作
→ working
→ 宠物包 fallbacks
→ idle
```

不新增 `keyboard_working` 素材，避免同一语义维护两套动作。键盘来源发布较低业务优先级，不能主动覆盖 Codex waiting/failed/review；现有 drag/click 的不可中断约束继续由 PetStateMachine 处理。

如果当前宠物的 working 最终解析为 idle，设置页显示黄色提示，但监听仍可开启。

## 设置与迁移

设置 schema 升级并新增：

```python
keyboard_working_enabled: bool = False
```

迁移规则：

- 新用户默认 `False`；
- 所有旧 schema 补 `False`；
- 已保存的有效布尔值原样保留；
- 非布尔损坏值归一化为 `False`；
- 该设置与 `codex_link_enabled` 相互独立。

## 设置页

位置：“鼠标与行为”页，新卡片“键盘活动”。

普通内容：

```text
键盘活动

[开关] 敲键盘时播放工作动作

在其他应用输入时也会生效。
PetNest 只识别键盘活动，不记录按键或输入内容。

状态：已关闭 / 监听正常 / 监听不可用 / 当前版本仅支持 Windows
```

规则：

- Windows：开关可用；开启失败时自动回退为未运行状态，但保留用户设置，允许下次启动重试；
- macOS/其他平台：开关禁用，显示“当前版本仅支持 Windows”；
- working 缺失时显示：“当前宠物缺少‘任务进行中’动作，键盘活动会保持待机。”；
- 不放入 Codex 联动页，避免暗示它依赖 Codex；
- 不增加按键计数、超时输入框或高级参数，1.5 秒为第一版固定行为。

## 生命周期

### 启动

1. 加载设置；
2. 创建平台 keyboard monitor 和 Qt relay；
3. 仅在 `keyboard_working_enabled=True` 时安装 Hook；
4. 安装成功显示“监听正常”；失败显示“监听不可用”；
5. 默认关闭时不得安装全局 Hook。

### 设置变化

- 关闭 → 停止 1.5 秒 timer、解除 Hook、释放 keyboard_active；
- 开启 → 尝试安装 Hook；成功后等待第一次按键；
- 重复保存相同设置不得重复安装 Hook。

### 切换宠物

监听器不重启。若键盘仍 active，新宠物根据自己的 `agent.working` 绑定和 fallback 呈现。

### 退出

1. 停止键盘活动 timer；
2. 解除 Windows Hook 并终止消息线程；
3. 清空 coordinator 键盘状态；
4. 继续现有应用退出流程。

## 错误和隐私边界

- 原生回调 API 不包含键值参数；
- PetEvent payload 始终为空；
- 不写入键盘活动日志、配置历史或统计文件；
- Hook 错误只记录错误码和阶段，不记录按键数据；
- 安装失败不影响 Codex 联动、系统空闲、桌宠和其他设置；
- 停止失败时仍尝试退出消息线程，应用退出不得无限等待；
- 高权限应用或系统安全策略导致部分按键不可见时，不推断或伪造输入。

## 测试与验收

### 纯状态测试

- 键盘首次活动产生 working；
- 1.5 秒超时后恢复 idle；
- 连续活动不重复 working；
- Codex running + 键盘停止仍 working；
- Codex idle + 键盘 active 仍 working；
- waiting/failed 不被键盘覆盖；
- review 未完成不被覆盖；
- review 完成且键盘 active 恢复 working；
- review 完成且键盘 inactive 恢复 idle。

### Windows monitor 测试

- Hook 安装成功、失败和幂等；
- KEYDOWN/SYSKEYDOWN 触发无参数 activity；
- KEYUP 和未知消息不触发；
- stop 解除 Hook 并结束线程；
- 测试替身确认没有键值离开平台模块；
- 非 Windows 导入安全。

### 应用与设置测试

- 默认关闭不安装 Hook；
- 开启/关闭即时应用并持久化；
- unsupported 平台开关禁用；
- 监听失败安全降级；
- 缺少 working 时显示提示；
- Codex 与键盘同时工作不重启动画；
- 停用任一来源不会错误取消另一来源；
- 系统 wake 行为保持原样；
- 键盘从 bored/sleep 恢复时进入 working 且不重播 wake，鼠标恢复仍播放 wake；
- 现有 Codex、设置、状态机和完整测试全部通过。

## 发布范围

- 第一版发布 Windows 全局键盘 working；
- macOS 和其他平台显示暂不支持，不申请权限；
- 后续实现 macOS 时复用 `KeyboardActivityMonitor` 和 `WorkActivityCoordinator`，不修改业务仲裁规则。
