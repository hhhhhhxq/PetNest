# PetNest 设置中心与快捷菜单重设计实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 `superpowers:executing-plans` 逐任务执行本计划，并在实现前完成全部设计图确认。

**目标：** 按已确认的 11 张设计图，重做 PetNest 的设置中心、托盘菜单、宠物右键菜单、导入向导和动画编辑器的视觉与窗口入口关系，同时保持互动窗口和现有设置数据行为不变。

**架构：** 使用一个共享的 PetNest 视觉令牌与 Qt 样式辅助模块，统一颜色、圆角、间距、按钮和菜单状态；设置中心由一个窗口承载五个分类视图，设置与鼠标样式入口通过分类定位复用该窗口；导入向导和动画编辑器继续保持独立窗口。菜单、窗口和业务层通过现有回调连接，不改变 Settings、宠物包和互动服务的数据接口。

**技术栈：** Python 3.12、PySide6、pytest、pytest-qt、SVG 设计图、现有 PetNest PNG/ICO/光标资源。

---

## 0. 设计确认门控

**文件：**
- 创建：`docs/superpowers/designs/01-tray-context-menu.svg` 至 `docs/superpowers/designs/11-animation-editor-per-frame.svg`
- 参考：`docs/superpowers/specs/2026-08-13-settings-center-and-context-menus-design.md`

- [ ] **步骤 1：按规格顺序制作设计图**

  先制作托盘菜单、宠物菜单、设置中心五个分类、导入向导两个状态、动画编辑器两个状态。每张图使用固定画布、暖色奶油背景、统一卡片和菜单令牌，并只引用现有图标/宠物/倒计时/光标素材。

- [ ] **步骤 2：每张图单独获得用户确认**

  每次只展示当前图，说明该图对应的窗口状态、可复用素材和需要确认的重点。用户要求修改时只更新当前图；未获得确认前不制作下一张，也不修改应用代码。

- [ ] **步骤 3：确认切图需求**

  对每张确认图扫描无法由 Qt 控件、文字、现有图标或现有资源表达的装饰元素。只有确有必要时才在 `assets/ui/` 增加透明切图，并记录文件名、像素尺寸、透明边距和使用位置。

## 1. 共享视觉基础

**文件：**
- 创建：`src/petnest/ui/theme.py`
- 测试：`tests/test_ui_theme.py`
- 参考：`src/petnest/ui/lan_interaction_dialog.py:828-856`、`src/petnest/app.py:1257-1292`

- [ ] **步骤 1：编写视觉令牌测试**

  测试 `theme.py` 导出的颜色令牌包含 `window_background`、`surface`、`surface_alt`、`accent`、`accent_soft`、`text`、`muted_text`、`border`、`success` 和 `error`；测试主题样式函数返回非空字符串并包含 `QPushButton`、`QLineEdit`、`QComboBox`、`QCheckBox` 和 `QGroupBox` 的规则。

- [ ] **步骤 2：运行测试确认失败**

  运行：`pytest tests/test_ui_theme.py -q`

  预期：因 `petnest.ui.theme` 尚不存在而失败。

- [ ] **步骤 3：实现共享令牌与样式函数**

  在 `theme.py` 中定义不可变的颜色常量和 `dialog_stylesheet()`、`menu_stylesheet(object_name: str)`、`card_stylesheet()` 辅助函数。样式使用 `#F7F1EA`、`#FFFDF9`、`#D98663`、`#FFF0E8`、`#4B4641`、`#8F8680`、`#E8DED5` 等规格颜色，并通过透明填充和细边框模拟磨砂层，不调用平台专属背景模糊 API。

- [ ] **步骤 4：运行测试确认通过**

  运行：`pytest tests/test_ui_theme.py -q`

  预期：全部通过。

- [ ] **步骤 5：Commit**

  ```powershell
  git add src/petnest/ui/theme.py tests/test_ui_theme.py
  git commit -m "style(界面): 添加 PetNest 统一视觉令牌"
  ```

## 2. 设置中心与入口复用

**文件：**
- 创建：`src/petnest/ui/settings_center_dialog.py`
- 删除：`src/petnest/ui/settings_dialog.py`（完成迁移后）
- 修改：`src/petnest/ui/cursor_style_dialog.py`
- 修改：`src/petnest/app.py:498-524`
- 修改：`src/petnest/ui/__init__.py`
- 测试：`tests/test_settings_dialog.py`

- [ ] **步骤 1：扩展失败测试覆盖窗口与分类入口**

  在 `tests/test_settings_dialog.py` 增加以下行为断言：

  ```python
  dialog = SettingsCenterDialog(Settings(), initial_section="mouse_behavior")
  assert dialog.section_list.currentRow() == 1
  assert dialog.page_title.text() == "鼠标与行为"
  dialog.follow_mouse_input.setChecked(False)
  assert not dialog.follow_scale_input.isEnabled()
  ```

  增加测试确认“鼠标样式”入口不再实例化 `CursorStyleDialog`，而由应用层调用设置中心并传入 `initial_section="mouse_behavior"`。保留现有更新回调、远程伙伴开关和取消语义测试。

- [ ] **步骤 2：运行针对性测试确认失败**

  运行：`pytest tests/test_settings_dialog.py -q`

  预期：因 `SettingsCenterDialog` 和 `initial_section` 入口尚未实现而失败。

- [ ] **步骤 3：实现设置中心窗口**

  将现有设置表单拆成一个 `QDialog` 和五个页面构建函数：`_build_display_page()`、`_build_mouse_behavior_page()`、`_build_idle_page()`、`_build_countdown_page()`、`_build_app_update_page()`。窗口左侧使用 `QListWidget` 分类导航，右侧使用 `QStackedWidget`，底部使用“取消”和“应用并关闭”。所有控件仍使用现有属性名或兼容属性名，以减少业务层和测试改动。

  设置编辑副本继续通过 `updated_settings()` 返回；将原有每日下班时间、倒计时主题和尺寸字段迁移到工作倒计时页；将光标启用、样式下拉框、预览和角色覆盖说明迁移到鼠标与行为页。使用 `QSignalBlocker` 或统一联动函数避免初始化时触发错误状态。

- [ ] **步骤 4：迁移鼠标样式入口**

  将 `CursorStyleDialog` 中的光标控件构建逻辑提取为设置中心的页面组件；在 `PetNest.show_cursor_style_dialog()` 中调用设置中心，传入 `initial_section="mouse_behavior"`，确认后调用同一个 `apply_settings()`。删除旧的独立鼠标样式窗口导出，保留光标目录和平台能力判断。

- [ ] **步骤 5：实现单实例窗口复用**

  在 `PetNest` 上保存设置中心、导入向导和动画编辑器的活动窗口引用。入口调用时若引用存在且未销毁，则调用 `showNormal()`、`raise_()`、`activateWindow()`；窗口关闭时清空引用。对话框仍可按现有模态方式运行，但重复入口不能产生重复实例。

- [ ] **步骤 6：运行针对性测试确认通过**

  运行：`pytest tests/test_settings_dialog.py tests/test_cursor_style_dialog.py -q`

  预期：设置分类、联动状态、更新入口和设置保存测试全部通过。

- [ ] **步骤 7：Commit**

  ```powershell
  git add src/petnest/ui/settings_center_dialog.py src/petnest/ui/cursor_style_dialog.py src/petnest/ui/__init__.py src/petnest/app.py tests/test_settings_dialog.py tests/test_cursor_style_dialog.py
  git rm src/petnest/ui/settings_dialog.py
  git commit -m "feat(设置): 重构分类设置中心与鼠标样式入口"
  ```

## 3. 托盘菜单与宠物右键菜单

**文件：**
- 修改：`src/petnest/ui/tray_icon.py`
- 修改：`src/petnest/app.py:242-268, 464-480, 1257-1292`
- 修改：`src/petnest/ui/theme.py`
- 测试：`tests/test_pet_window.py`

- [ ] **步骤 1：增加菜单结构失败测试**

  测试托盘菜单文本包含“当前宠物：”、不包含“动画播放中”，并能找到“宠物库”子菜单；测试宠物菜单只包含缩放、暂停/继续、置顶、跟随鼠标、互动、隐藏和设置，不包含导入、资源更新和退出。

- [ ] **步骤 2：运行测试确认失败**

  运行：`pytest tests/test_pet_window.py -k "tray or context_menu" -q`

  预期：现有菜单结构与新断言不一致而失败。

- [ ] **步骤 3：实现托盘菜单分组**

  在 `PetTrayIcon` 中增加不可点击的应用标题和当前宠物标题动作；把导入、打开文件夹、刷新、动画编辑和重新加载移动到“宠物库”子菜单；保留互动、设置、鼠标样式、资源更新和退出入口；删除任何“动画播放中”状态动作。当前宠物名称通过 `set_current_pet_name()` 更新，菜单显示时与应用状态同步。

- [ ] **步骤 4：统一宠物右键菜单样式和内容**

  保留宠物名称与缩放比例标题，继续动态同步缩放按钮、暂停文案、置顶勾选和跟随鼠标勾选；使用共享 `menu_stylesheet()` 替换当前单独的蓝色系统风格，采用奶油白表面、珊瑚橙选中底色和低对比度分隔线。

- [ ] **步骤 5：运行测试确认通过**

  运行：`pytest tests/test_pet_window.py -k "tray or context_menu" -q`

  预期：菜单结构和既有动态状态测试全部通过。

- [ ] **步骤 6：Commit**

  ```powershell
  git add src/petnest/ui/tray_icon.py src/petnest/app.py src/petnest/ui/theme.py tests/test_pet_window.py
  git commit -m "feat(菜单): 重组托盘与宠物快捷菜单"
  ```

## 4. 导入向导视觉重做

**文件：**
- 修改：`src/petnest/ui/spritesheet_import_dialog.py`
- 修改：`src/petnest/ui/theme.py`
- 修改：`src/petnest/app.py:601-606`
- 测试：`tests/test_spritesheet_import_dialog.py`

- [ ] **步骤 1：增加导入向导状态测试**

  测试初始状态显示步骤标题、文件选择、宠物 ID、显示名称、自动识别/手动选择选项和导入主按钮；测试有效文件进入手动选择模式后仍能显示动作列表与帧缩略图；测试失败时保留窗口并显示错误状态。

- [ ] **步骤 2：运行测试确认失败**

  运行：`pytest tests/test_spritesheet_import_dialog.py -q`

  预期：新状态对象名称或视觉结构断言失败。

- [ ] **步骤 3：按确认图重排导入向导**

  保留现有 `SpriteSheetImporter`、自动识别和手动列选择逻辑；将窗口重排为顶部步骤指示、文件信息卡、导入模式卡、手动预览区、底部状态与操作区。用共享样式统一 `QLineEdit`、单选按钮、列表、缩略图按钮、错误提示和“导入”主按钮。

- [ ] **步骤 4：运行导入测试确认通过**

  运行：`pytest tests/test_spritesheet_import_dialog.py -q`

  预期：全部通过。

- [ ] **步骤 5：Commit**

  ```powershell
  git add src/petnest/ui/spritesheet_import_dialog.py src/petnest/ui/theme.py src/petnest/app.py tests/test_spritesheet_import_dialog.py
  git commit -m "style(导入): 统一精灵图导入向导视觉"
  ```

## 5. 动画编辑器视觉重做

**文件：**
- 修改：`src/petnest/ui/animation_editor_dialog.py`
- 修改：`src/petnest/ui/theme.py`
- 修改：`src/petnest/app.py:620-650`
- 测试：`tests/test_animation_editor_dialog.py`

- [ ] **步骤 1：增加两种编辑状态测试**

  测试动作表首次选中时默认进入总时长编辑，目标总时长控件可用、逐帧列表隐藏；切换逐帧模式后目标总时长控件禁用、逐帧列表和预览可见；修改时显示未保存提示，取消不写入，保存只返回已修改动作。

- [ ] **步骤 2：运行测试确认失败**

  运行：`pytest tests/test_animation_editor_dialog.py -q`

  预期：新布局状态断言失败或测试文件缺少新增用例。

- [ ] **步骤 3：按确认图重排动画编辑器**

  保留现有动作表、总时长/逐帧模式、逐帧输入、实时预览和定时器；将窗口重排为顶部标题说明、左侧动作列表、中间编辑卡、右侧预览卡、底部未保存状态和“保存并重载”主按钮。使用共享样式替换预览区蓝灰色旧样式，并为已修改动作提供明确但低干扰的状态标记。

- [ ] **步骤 4：运行动画编辑器测试确认通过**

  运行：`pytest tests/test_animation_editor_dialog.py -q`

  预期：全部通过。

- [ ] **步骤 5：Commit**

  ```powershell
  git add src/petnest/ui/animation_editor_dialog.py src/petnest/ui/theme.py src/petnest/app.py tests/test_animation_editor_dialog.py
  git commit -m "style(动画): 统一动画编辑器视觉与状态"
  ```

## 6. 互动窗口回归保护与全量验证

**文件：**
- 修改：`tests/test_lan_interactions.py`
- 修改：`tests/test_app_and_platforms.py`
- 参考：`src/petnest/ui/lan_interaction_dialog.py`

- [ ] **步骤 1：增加互动窗口不变性断言**

  使用现有互动测试确认 `LanInteractionDialog` 仍包含附近设备/远程伙伴 Tab、快捷互动/文字/动效 Tab、动效预览和发送回调；不修改互动布局实现。

- [ ] **步骤 2：运行互动回归测试**

  运行：`pytest tests/test_lan_interactions.py -q`

  预期：全部通过。

- [ ] **步骤 3：运行全量测试和编译检查**

  运行：`pytest -q`; `python -m compileall -q src tests`; `git diff --check`

  预期：pytest 退出码为 0，compileall 无输出并退出码为 0，git diff --check 无输出并退出码为 0。

- [ ] **步骤 4：执行真实窗口视觉检查**

  在可用桌面环境启动应用，依次打开设置中心五个分类、托盘菜单、宠物菜单、导入向导和动画编辑器；检查窗口尺寸、文字截断、控件联动、菜单层级、按钮可点击区域和暖色视觉令牌。互动窗口打开后仅确认原布局和功能仍在。

- [ ] **步骤 5：Commit**

  ```powershell
  git add tests/test_lan_interactions.py tests/test_app_and_platforms.py
  git commit -m "test(界面): 增加设置与菜单视觉回归验证"
  ```

