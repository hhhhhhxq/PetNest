# 光标可见间隔与独立设置页实现计划

> 面向 AI 代理的工作者：必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框跟踪进度。

**目标：** 让跟随宠物与自定义光标的可见边缘保持 8px 间隔，并把光标选项移到独立对话框。

**架构：** CursorStyleCatalog 读取主题包、预先计算的可见边界和可选角色资源；MouseFollowController 接收四边边界并按当前翻转方向定位。CursorStyleDialog 独立编辑光标主题，应用层从托盘打开它并只替换主题实际包含的角色。

**技术栈：** Python 3.12、PySide6、Pillow、pytest、pytest-qt。

---

## 文件结构

- 修改：tools/build_cursor_asset.py、assets/cursors/petnest-paw/style.json、src/petnest/core/cursor_style_catalog.py、src/petnest/platforms/windows_cursor.py。
- 修改：src/petnest/core/mouse_follow.py、src/petnest/app.py。
- 创建：src/petnest/ui/cursor_style_dialog.py、tests/test_cursor_style_dialog.py。
- 修改：src/petnest/ui/settings_dialog.py、src/petnest/ui/tray_icon.py、tests/test_cursor_style_catalog.py、tests/test_mouse_follow.py、tests/test_settings_dialog.py。

### 任务 1：样式可见边界

**文件：**
- 修改：src/petnest/core/cursor_style_catalog.py
- 修改：tools/build_cursor_asset.py
- 修改：assets/cursors/petnest-paw/style.json
- 测试：tests/test_cursor_style_catalog.py

- [ ] **步骤 1：编写失败的边界读取测试**

    def test_catalog_reads_optional_follow_bounds(tmp_path: Path) -> None:
        _write_style(tmp_path, "paw", with_cursor=True, follow_bounds=[2, 1, 31, 30])
        style = CursorStyleCatalog(tmp_path).discover()[0]
        assert style.follow_bounds == (2, 1, 31, 30)

- [ ] **步骤 2：运行测试验证失败**

运行：.venv\Scripts\python.exe -m pytest tests/test_cursor_style_catalog.py -v

预期：FAIL，CursorStyle 没有 follow_bounds 属性。

- [ ] **步骤 3：实现边界模型和生成规则**

    @dataclass(frozen=True, slots=True)
    class CursorStyle:
        identifier: str
        display_name: str
        preview_path: Path
        arrow_path: Path
        hotspot: tuple[int, int]
        follow_bounds: tuple[int, int, int, int] | None

构建脚本对 64×64 CUR 帧的 alpha 通道调用 getbbox()，将 [left, top, right, bottom] 写入样式 JSON。目录解析仅接受四个非负整数且 left <= right、top <= bottom；不存在时返回 None。目录还会识别 busy、text、move、resize_horizontal、resize_vertical、resize_diag_1、resize_diag_2 的可选 CUR 文件并忽略缺失项。

- [ ] **步骤 4：运行测试验证通过**

运行：.venv\Scripts\python.exe -m pytest tests/test_cursor_style_catalog.py -v

预期：PASS；包含边界的样式被读取，缺失边界的旧样式仍可发现。

- [ ] **步骤 5：Commit**

    git add tools/build_cursor_asset.py assets/cursors/petnest-paw/style.json src/petnest/core/cursor_style_catalog.py tests/test_cursor_style_catalog.py
    git commit -m "feat: record cursor visual bounds"

### 任务 2：按可见边缘定位跟随宠物

**文件：**
- 修改：src/petnest/core/mouse_follow.py、src/petnest/app.py
- 测试：tests/test_mouse_follow.py、tests/test_app_and_platforms.py

- [ ] **步骤 1：编写失败的左右翻转定位测试**

    def test_target_position_keeps_gap_after_cursor_visible_bounds() -> None:
        controller = MouseFollowController(offset=8)
        target = controller.target_position(
            QPoint(100, 200), QSize(80, 80), QRect(0, 0, 800, 600),
            visible_bounds=(2, 1, 32, 31),
        )
        assert target == QPoint(140, 239)

- [ ] **步骤 2：运行测试验证失败**

运行：.venv\Scripts\python.exe -m pytest tests/test_mouse_follow.py -v

预期：FAIL，target_position 不接受 visible_bounds。

- [ ] **步骤 3：实现边界感知定位**

    def target_position(self, cursor, pet_size, screen, *, visible_bounds=None):
        left, top, right, bottom = visible_bounds or (0, 0, 0, 0)
        x = cursor.x() + right + self.offset
        y = cursor.y() + bottom + self.offset
        if x + pet_size.width() > screen.right() + 1:
            x = cursor.x() + left - self.offset - pet_size.width()
        if y + pet_size.height() > screen.bottom() + 1:
            y = cursor.y() + top - self.offset - pet_size.height()
        return self._clamp(QPoint(x, y), pet_size, screen)

PetNest 仅在当前自定义样式已启用且可发现时传入该样式边界；系统默认或缺失边界传 None。

- [ ] **步骤 4：运行测试验证通过**

运行：.venv\Scripts\python.exe -m pytest tests/test_mouse_follow.py tests/test_app_and_platforms.py -k "follow or cursor" -v

预期：PASS；右下和翻转到左上的位置均保留 8px 空隙，默认样式位置不变。

- [ ] **步骤 5：Commit**

    git add src/petnest/core/mouse_follow.py src/petnest/app.py tests/test_mouse_follow.py tests/test_app_and_platforms.py
    git commit -m "feat: keep pets clear of cursor artwork"

### 任务 3：独立光标设置页

**文件：**
- 创建：src/petnest/ui/cursor_style_dialog.py、tests/test_cursor_style_dialog.py
- 修改：src/petnest/ui/settings_dialog.py、src/petnest/ui/tray_icon.py、src/petnest/app.py、src/petnest/platforms/windows_cursor.py、tests/test_settings_dialog.py

- [ ] **步骤 1：编写失败的独立页和常规设置页测试**

    def test_cursor_style_dialog_round_trips_selected_style(qtbot, tmp_path: Path) -> None:
        dialog = CursorStyleDialog(Settings(), cursor_styles=[_style(tmp_path)])
        qtbot.addWidget(dialog)
        dialog.cursor_style_enabled_input.setChecked(True)
        assert dialog.updated_settings().cursor_style_id == "petnest-paw"

    def test_regular_settings_dialog_has_no_cursor_controls(qtbot) -> None:
        dialog = SettingsDialog(Settings())
        qtbot.addWidget(dialog)
        assert not hasattr(dialog, "cursor_style_enabled_input")

- [ ] **步骤 2：运行测试验证失败**

运行：.venv\Scripts\python.exe -m pytest tests/test_cursor_style_dialog.py tests/test_settings_dialog.py -v

预期：FAIL，CursorStyleDialog 尚不存在，且常规设置页仍有光标控件。

- [ ] **步骤 3：实现独立页、托盘入口和应用保存**

CursorStyleDialog 包含开关、主题下拉框、预览、说明、恢复按钮和只读“本主题已包含”角色清单；updated_settings 使用 dataclasses.replace 返回光标字段变更后的 Settings。缺少资源的角色显示“使用系统默认”。

PetTrayIcon 新增 on_cursor_styles 回调和“鼠标样式…”动作，紧接“设置…”添加。应用层 show_cursor_style_dialog 确认后调用 apply_settings。WindowsCursorController 新增按角色应用和恢复方法；应用层仅请求主题实际存在的角色，关闭或退出时只恢复这些角色。将原有光标控件及帮助方法从 SettingsDialog 删除。

- [ ] **步骤 4：运行界面与全量测试验证通过**

运行：.venv\Scripts\python.exe -m pytest tests/test_cursor_style_dialog.py tests/test_settings_dialog.py -v；.venv\Scripts\python.exe -m pytest -q；git diff --check

预期：全部 PASS；独立页面保存后立即应用，普通设置页不再显示光标部分。

- [ ] **步骤 5：Commit**

    git add src/petnest/ui/cursor_style_dialog.py src/petnest/ui/settings_dialog.py src/petnest/ui/tray_icon.py src/petnest/app.py tests/test_cursor_style_dialog.py tests/test_settings_dialog.py
    git commit -m "feat: split cursor style settings into its own dialog"

### 任务 4：实机与安装包验证

**文件：** 无代码修改；只验证当前发布产物。

- [ ] **步骤 1：运行系统光标和跟随间隔检查**

运行：$env:PYTHONPATH = "$pwd\src"; .venv\Scripts\python.exe -m petnest

预期：启用深灰肉垫且跟随鼠标时，猫爪右下可见边缘到宠物保持 8px；靠近右下屏幕边缘时宠物翻转到猫爪左上，仍不重叠。

- [ ] **步骤 2：构建并检查安装包资源**

运行：build_windows.bat；Test-Path 'dist\PetNest\_internal\assets\cursors\petnest-paw\arrow.cur'

预期：构建成功，命令输出 True。

- [ ] **步骤 3：Commit 打包配置调整（仅在确有改动时）**

    git add PetNest.spec installer
    git commit -m "build: bundle cursor visual gap resources"
