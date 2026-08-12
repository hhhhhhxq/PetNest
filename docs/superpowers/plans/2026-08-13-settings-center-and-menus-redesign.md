# PetNest 设置中心与快捷菜单重设计实现计划

> **执行说明：** 设计图已全部确认，本计划直接进入实现阶段。每个阶段先补失败测试，再实现，再运行针对性测试；所有阶段完成后运行全量验证。

**目标：** 按已确认的 10 张设计图完成设置中心、托盘菜单、导入精灵图向导和动画时长编辑器的统一视觉实现，补充鼠标大小与弹性打卡，并保护互动窗口、宠物右键菜单和倒计时气泡的现有体验。

**架构：** 使用共享视觉令牌和 Qt 样式辅助模块；设置中心由一个窗口承载五个分类视图，设置与鼠标样式入口复用该窗口；导入向导和动画编辑器继续使用独立窗口；弹性打卡使用独立卡片窗口，由工作倒计时控制器管理，不改动 `PetWindow` 的倒计时绘制。

**技术栈：** Python 3.12、PySide6、pytest、pytest-qt、现有 PetNest 资源与 SVG 设计稿。

## 1. 收敛规格与已确认设计

**文件：**

- `docs/superpowers/specs/2026-08-13-settings-center-and-context-menus-design.md`
- `docs/superpowers/designs/01-tray-context-menu.svg`
- `docs/superpowers/designs/02-settings-display.svg` 至 `10-animation-editor-per-frame.svg`

- [x] 记录五分类设置中心、三个实际窗口、托盘菜单职责和宠物菜单保护边界。
- [x] 删除“动画播放中”、运行状态示例入口、“规律休息/灵活安排 + 例外下班时间”的旧表述。
- [x] 固化工作日单一选择模块、固定时段/弹性打卡模式、打卡时间钳制规则和独立打卡卡片规则。
- [x] 确认不需要新增无法绘制的装饰切图；优先复用 Qt 控件与现有资源。

## 2. 数据模型、迁移与弹性打卡纯逻辑

**文件：**

- 修改：`src/petnest/models/settings.py`
- 修改：`src/petnest/core/settings_manager.py`
- 修改：`src/petnest/ui/work_countdown.py`
- 测试：`tests/test_settings_manager.py`
- 测试：`tests/test_work_countdown.py`

- [ ] **步骤 1：补写失败测试**

  覆盖 schema 迁移和新字段默认值；覆盖 `cursor_scale` 的合法节点；覆盖弹性打卡在窗口开始前、窗口内和窗口结束后的钳制；覆盖工作日判断、跨日清理和工作时长计算。固定模式已有测试必须继续保留。

- [ ] **步骤 2：运行测试确认失败**

  ```powershell
  pytest tests/test_settings_manager.py tests/test_work_countdown.py -q
  ```

- [ ] **步骤 3：实现模型与迁移**

  将 schema 递增一个版本，加入 `cursor_scale`、`work_schedule_mode`、`clock_in_start_time`、`clock_in_end_time`、`work_duration_minutes`、`clock_in_date`、`clock_in_time`。旧文件按默认值读取；非法模式、比例和负工作时长回退到安全默认值。

- [ ] **步骤 4：实现可测试的弹性打卡计算**

  在 `work_countdown.py` 增加时间解析、有效打卡时间钳制、弹性下班时间计算和“达到允许开始时间且当天为工作日”的纯函数。保留原 `countdown_text()` 的固定模式行为和签名兼容性。

- [ ] **步骤 5：运行针对性测试并提交**

  ```powershell
  pytest tests/test_settings_manager.py tests/test_work_countdown.py -q
  git diff --check
  git add src/petnest/models/settings.py src/petnest/core/settings_manager.py src/petnest/ui/work_countdown.py tests/test_settings_manager.py tests/test_work_countdown.py
  git commit -m "feat(倒计时): 增加弹性打卡数据与时间计算"
  ```

## 3. 共享视觉基础

**文件：**

- 创建：`src/petnest/ui/theme.py`
- 测试：`tests/test_ui_theme.py`

- [ ] **步骤 1：补写失败测试**

  断言视觉令牌包含背景、卡片、强调色、文字、边框和状态色；样式函数返回包含 `QPushButton`、`QLineEdit`、`QComboBox`、`QCheckBox`、`QGroupBox` 和菜单规则的非空 QSS。

- [ ] **步骤 2：运行 `pytest tests/test_ui_theme.py -q` 确认失败。**

- [ ] **步骤 3：实现视觉令牌**

  用确认稿中的奶油色、珊瑚色和细边框建立不可变令牌，提供对话框、卡片和托盘菜单样式函数；使用半透明填充和轻阴影模拟磨砂效果，不依赖系统背景模糊。

- [ ] **步骤 4：运行测试并提交。**

  ```powershell
  pytest tests/test_ui_theme.py -q
  git add src/petnest/ui/theme.py tests/test_ui_theme.py
  git commit -m "style(界面): 添加 PetNest 统一视觉令牌"
  ```

## 4. 设置中心与鼠标大小

**文件：**

- 创建：`src/petnest/ui/settings_center_dialog.py`
- 修改：`src/petnest/ui/settings_dialog.py`（保留兼容导出）
- 修改：`src/petnest/ui/app_update_dialog.py`（仅在需要时复用视觉令牌）
- 修改：`src/petnest/ui/__init__.py`
- 修改：`src/petnest/app.py`
- 修改：平台光标控制器及其测试
- 测试：`tests/test_settings_dialog.py`
- 测试：`tests/test_cursor_style_dialog.py`

- [ ] **步骤 1：补写失败测试**

  覆盖五个分类、无分类图标、`initial_section="mouse_behavior"`、跟随鼠标联动、空闲时间联动、工作日单一选择、固定/弹性字段保存、弹性模式自动启用打卡语义、应用更新按钮和鼠标滑块四节点吸附。保留旧 `SettingsDialog` 导入和已有兼容属性测试。

- [ ] **步骤 2：运行设置相关测试确认失败。**

- [ ] **步骤 3：实现设置中心**

  使用 `QListWidget + QStackedWidget` 构建一个窗口和五个页面。工作倒计时页先放唯一的工作日选择，再放固定/弹性模式：固定模式编辑统一上下班时间；弹性模式编辑允许打卡时间窗口和工作时长。移除例外下班时间、运行状态示例和自动校验说明。倒计时皮肤、间距、最小宽度和卡片高度放入高级设置。

- [ ] **步骤 4：实现鼠标大小**

  用水平滑块支持自由拖动，释放时吸附到 `80/100/125/150%`，显示当前百分比；自定义鼠标样式关闭时禁用样式、预览和滑块。应用层把比例传递给平台光标控制器，Windows 使用目标尺寸加载光标，其他平台保持安全兼容。

- [ ] **步骤 5：接入入口与单实例激活**

  `设置…`定位默认分类，`鼠标样式…`定位到鼠标与行为；二者复用设置中心实例。保留旧模块和旧类名的兼容导出，避免破坏外部导入和现有测试。

- [ ] **步骤 6：运行针对性测试并提交。**

  ```powershell
  pytest tests/test_settings_dialog.py tests/test_cursor_style_dialog.py tests/test_settings_manager.py -q
  git diff --check
  git add src/petnest/ui/settings_center_dialog.py src/petnest/ui/settings_dialog.py src/petnest/ui/__init__.py src/petnest/ui/app_update_dialog.py src/petnest/app.py src/petnest/platforms tests/test_settings_dialog.py tests/test_cursor_style_dialog.py
  git commit -m "feat(设置): 重构分类设置中心与鼠标大小"
  ```

## 5. 独立打卡卡片与应用状态接线

**文件：**

- 修改：`src/petnest/ui/work_countdown.py`
- 修改：`src/petnest/app.py`
- 不修改：`src/petnest/ui/pet_window.py` 的倒计时绘制、尺寸和皮肤逻辑
- 测试：`tests/test_work_countdown.py`
- 测试：`tests/test_pet_window.py`

- [ ] **步骤 1：补写失败测试**

  覆盖弹性模式达到开始时间后显示独立卡片、卡片包含独立时间编辑和独立打卡按钮、打卡后隐藏卡片并恢复原倒计时文本、未到开始时间或休息日不显示卡片、卡片不改变 `PetWindow` 倒计时几何属性。

- [ ] **步骤 2：运行测试确认失败。**

- [ ] **步骤 3：实现独立 `ClockInCard`**

  创建无标题栏的轻量工具窗口，使用奶油白卡片、标题、`QTimeEdit` 下拉箭头和独立“打卡”按钮。默认时间取当前时间，用户修改后保留草稿；卡片位置由工作倒计时控制器放在宠物旁，不使用倒计时背景。

- [ ] **步骤 4：接入工作倒计时控制器**

  固定模式继续沿用原 `PetWindow.set_countdown_text()`；弹性模式无记录时只显示独立卡片，打卡成功后按钳制后的有效时间计算下班时刻并把结果交给原倒计时气泡。应用层持久化当天日期与时间，跨日清理记录。

- [ ] **步骤 5：运行测试、编译并提交。**

  ```powershell
  pytest tests/test_work_countdown.py tests/test_pet_window.py -q
  python -m compileall -q src
  git add src/petnest/ui/work_countdown.py src/petnest/app.py tests/test_work_countdown.py tests/test_pet_window.py
  git commit -m "feat(打卡): 增加独立弹性打卡卡片"
  ```

## 6. 托盘菜单重组与宠物菜单回归

**文件：**

- 修改：`src/petnest/ui/tray_icon.py`
- 修改：`src/petnest/app.py`
- 测试：`tests/test_pet_window.py`

- [ ] **步骤 1：补写失败测试**

  断言托盘菜单包含当前宠物名称、宠物库子菜单、设置和鼠标样式入口，不包含“动画播放中”；断言宠物右键菜单项目、顺序、图标和样式对象与基线一致，且不出现导入、资源更新和退出。

- [ ] **步骤 2：运行托盘相关测试确认失败。**

- [ ] **步骤 3：实现托盘分组**

  增加不可点击的应用标题和当前宠物标题；将导入、文件夹、刷新、动画编辑、重新加载归入宠物库子菜单；保留切换宠物、互动、设置、鼠标样式、资源更新和退出。应用切换宠物时同步更新当前宠物标题。

- [ ] **步骤 4：只做宠物菜单回归保护**

  不修改宠物右键菜单源代码和样式，只增加快照式断言或基线断言。

- [ ] **步骤 5：运行测试并提交。**

  ```powershell
  pytest tests/test_pet_window.py -k "tray or context_menu" -q
  git add src/petnest/ui/tray_icon.py src/petnest/app.py tests/test_pet_window.py
  git commit -m "feat(菜单): 重组托盘菜单并保护宠物菜单"
  ```

## 7. 导入精灵图向导视觉实现

**文件：**

- 修改：`src/petnest/ui/spritesheet_import_dialog.py`
- 修改：`src/petnest/ui/theme.py`
- 测试：`tests/test_spritesheet_import_dialog.py`

- [ ] **步骤 1：补写初始、手动和失败状态测试。**
- [ ] **步骤 2：运行测试确认失败。**
- [ ] **步骤 3：保留现有导入器和自动识别逻辑，按确认稿重排为步骤标题、文件信息卡、模式选择卡、手动预览区和底部操作区。**
- [ ] **步骤 4：统一输入框、单选项、缩略图、错误提示和主按钮样式。**
- [ ] **步骤 5：运行 `pytest tests/test_spritesheet_import_dialog.py -q` 并提交。**

## 8. 动画时长编辑器视觉实现

**文件：**

- 修改：`src/petnest/ui/animation_editor_dialog.py`
- 修改：`src/petnest/ui/theme.py`
- 测试：`tests/test_animation_editor_dialog.py`

- [ ] **步骤 1：补写总时长、逐帧、未保存和取消语义测试。**
- [ ] **步骤 2：运行测试确认失败。**
- [ ] **步骤 3：保留动作列表、总时长/逐帧编辑、实时预览和定时器，按确认稿重排为左侧动作列表、中间编辑区、右侧预览区和底部保存状态。**
- [ ] **步骤 4：统一卡片、按钮、输入控件和未保存状态样式。**
- [ ] **步骤 5：运行 `pytest tests/test_animation_editor_dialog.py -q` 并提交。**

## 9. 全量回归与交付验证

**文件：**

- 参考：`src/petnest/ui/lan_interaction_dialog.py`
- 测试：现有全部 `tests/`

- [ ] **步骤 1：运行互动窗口回归测试**

  ```powershell
  pytest tests/test_lan_interactions.py -q
  ```

  只确认互动窗口原有 Tab、预览和发送流程仍在，不修改其布局。

- [ ] **步骤 2：运行全量测试与编译检查**

  ```powershell
  pytest -q
  python -m compileall -q src tests
  git diff --check
  ```

- [ ] **步骤 3：进行实际窗口或 Qt offscreen 视觉检查**

  依次检查设置中心五个分类、托盘菜单、宠物菜单、导入向导和动画编辑器；重点检查文字截断、控件联动、弹性打卡显示/打卡后状态、窗口单实例和暖色视觉令牌。确认倒计时气泡几何与绘制代码未被改动。

- [ ] **步骤 4：检查变更边界**

  只提交本计划涉及的源码、测试、规格和已确认设计图，不提交用户已有的宠物包、临时预览和其他无关未跟踪文件。

- [ ] **步骤 5：完成最终提交并汇报验证证据。**
