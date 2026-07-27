# 动画时间线与精灵图导入实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 为精灵图导入增加内容检测和手动帧选择，并让动画按逐帧时长及用户覆盖播放。

**架构：** 导入器负责检测格位、产生连续帧与默认时长；包模型与播放器负责时间线；设置保存动作覆盖；两个 PySide6 对话框分别承担导入选择和运行时编辑。应用层只负责把已保存覆盖应用到当前包并重新载入窗口。

**技术栈：** Python 3.12、Pillow、PySide6、pytest。

---

### 任务 1：时间线模型与播放

**文件：**
- 修改：`src/petnest/models/pet_package.py`
- 修改：`src/petnest/core/package_loader.py`
- 修改：`src/petnest/core/package_validator.py`
- 修改：`src/petnest/core/animation_player.py`
- 测试：`tests/test_animation_player.py`、`tests/test_package_validator.py`

- [ ] 编写并运行逐帧时长优先于 FPS、非法时间线被拒绝的失败测试。
- [ ] 为动作模型增加 `frame_durations_ms` 与 `speed_multiplier`，加载、校验并让播放器返回当前帧的等待时间。
- [ ] 运行上述测试并确认通过。

### 任务 2：精灵图内容检测与导入

**文件：**
- 修改：`src/petnest/core/spritesheet_importer.py`
- 修改：`tools/import_spritesheet.py`
- 测试：`tests/test_spritesheet_importer.py`、`tests/test_import_spritesheet_tool.py`

- [ ] 编写并运行自动跳过透明格位、手动保留指定格位的失败测试。
- [ ] 新增格位检测结果，按选择导出连续帧，并写入帧时长和来源元数据。
- [ ] 运行导入器测试并确认通过。

### 任务 3：导入选择界面

**文件：**
- 修改：`src/petnest/ui/spritesheet_import_dialog.py`
- 测试：`tests/test_spritesheet_import_dialog.py`

- [ ] 编写并运行“手动模式才显示缩略图选择”的失败测试。
- [ ] 增加模式单选、动作侧栏、触发说明和可点击缩略图；将选择传给导入器。
- [ ] 运行对话框测试并确认通过。

### 任务 4：设置覆盖与动画编辑器

**文件：**
- 修改：`src/petnest/models/settings.py`
- 修改：`src/petnest/core/settings_manager.py`
- 创建：`src/petnest/ui/animation_editor_dialog.py`
- 修改：`src/petnest/ui/tray_icon.py`
- 修改：`src/petnest/app.py`
- 修改：`src/petnest/ui/pet_window.py`
- 测试：`tests/test_settings_manager.py`、`tests/test_app_and_platforms.py`、`tests/test_pet_window.py`

- [ ] 编写并运行设置覆盖往返和变帧时长重新设置计时器的失败测试。
- [ ] 保存每宠物每动作的覆盖，提供动作/时机/帧数/总时长/速度编辑器，并保存后重载当前包。
- [ ] 运行覆盖、窗口及应用测试并确认通过。

### 任务 5：全量验证

**文件：**
- 修改：`README.md`

- [ ] 说明两种导入模式和速度编辑入口。
- [ ] 运行 `python -m pytest -q` 与 `python -m compileall -q src tools`。
- [ ] 用真实精灵图做一次不覆盖现有宠物目录的导入验证。

