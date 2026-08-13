# Codex 用量入口解锁实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 默认隐藏托盘中的 Codex 用量入口，并允许用户在设置中心点击版本号 7 次后永久解锁。

**架构：** `Settings` 保存唯一的解锁布尔值，`SettingsCenterDialog` 只负责单窗口点击计数和发出一次解锁回调，`PetNestApplication` 负责即时保存并通知 `PetTrayIcon` 刷新动作可见性。点击计数不持久化，关闭设置窗口自然清零。

**技术栈：** Python 3.12、PySide6、dataclasses、pytest、pytest-qt

---

## 文件职责

- `src/petnest/models/settings.py`：声明持久化的 `codex_usage_unlocked` 字段并升级 schema。
- `src/petnest/core/settings_manager.py`：把 schema 20 配置迁移到 schema 21。
- `src/petnest/ui/tray_icon.py`：依据解锁状态显示或隐藏 Codex 动作。
- `src/petnest/ui/settings_center_dialog.py`：处理版本号点击和一次性解锁提示。
- `src/petnest/app.py`：即时保存解锁状态并联动托盘。
- `tests/test_settings_manager.py`：验证默认值、迁移和持久化。
- `tests/test_pet_window.py`：验证托盘动作默认隐藏及运行时显示。
- `tests/test_settings_dialog.py`：验证第 7 次点击、单次触发和窗口级计数。
- `tests/test_app_and_platforms.py`：验证应用层保存与托盘刷新。

### 任务 1：持久化解锁状态

- [x] 在 `tests/test_settings_manager.py` 添加测试：新配置默认 `False`，schema 20 迁移为 `False`，保存 `True` 后重新加载仍为 `True`。
- [x] 运行 `python -m pytest tests/test_settings_manager.py -q`，确认因字段缺失而失败。
- [x] 将 `Settings.SCHEMA_VERSION` 升为 21，新增 `codex_usage_unlocked: bool = False`，并在迁移器中为 schema 20 设置默认值。
- [x] 重跑设置测试并确认通过。

### 任务 2：托盘入口默认隐藏

- [x] 在 `tests/test_pet_window.py` 添加测试：默认构造时动作隐藏；以 `codex_usage_unlocked=True` 构造或调用刷新方法后动作可见且可触发回调。
- [x] 运行目标托盘测试，确认当前默认可见或参数缺失导致失败。
- [x] 给 `PetTrayIcon` 增加 `codex_usage_unlocked` 参数及 `set_codex_usage_unlocked()`，只控制现有动作的可见性。
- [x] 重跑托盘测试并确认通过。

### 任务 3：版本号点击 7 次解锁

- [x] 在 `tests/test_settings_dialog.py` 添加测试：前 6 次不触发，第 7 次触发一次并更新编辑副本，第 8 次不重复触发；重建窗口后未完成的计数从 0 开始。
- [x] 运行目标设置窗口测试，确认因缺少可点击标签或回调参数而失败。
- [x] 新增发出 `clicked` 信号的版本标签；设置窗口保存实例级计数，第 7 次调用 `on_unlock_codex_usage`，更新 `_settings` 并显示一次解锁提示。
- [x] 重跑设置窗口测试并确认通过。

### 任务 4：应用层即时保存和联动

- [x] 在 `tests/test_app_and_platforms.py` 添加测试：应用解锁方法把设置改为 `True`、调用 `SettingsManager.save()` 并让托盘动作可见。
- [x] 运行目标应用测试，确认因解锁方法缺失而失败。
- [x] 应用创建托盘时传入当前状态，创建设置窗口时传入解锁回调；解锁方法使用 `replace()` 更新设置、立即保存并刷新托盘。
- [x] 重跑应用测试并确认通过。

### 任务 5：综合验证

- [x] 运行 `python -m pytest tests/test_settings_manager.py tests/test_pet_window.py tests/test_settings_dialog.py tests/test_app_and_platforms.py -q`。
- [x] 运行 Codex 相关回归测试 `python -m pytest tests/test_codex_usage.py tests/test_codex_usage_sync.py tests/test_codex_usage_dialog.py -q`。
- [x] 运行 `git diff --check`，检查提交范围，并重启本地源码版 PetNest 验证其加载当前宠物包。
