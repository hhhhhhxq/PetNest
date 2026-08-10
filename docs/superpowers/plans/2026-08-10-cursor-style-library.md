Exit code: 0
Wall time: 0.5 seconds
Output:
# 鼠标样式库实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（\`- [x]\`）语法来跟踪进度。

**目标：** 让 PetNest 在 Windows 上安全替换可选的普通箭头光标，并在关闭、退出和下一次启动时恢复用户原来的箭头样式。

**架构：** \`CursorStyleCatalog\` 只发现和校验本地样式包；\`WindowsCursorController\` 只负责 Win32 的普通箭头替换与恢复；\`PetNest\` 根据持久化设置调用控制器。设置对话框只编辑偏好并展示预览，不直接调用 Win32。首版只改变 \`OCR_NORMAL\`，其它角色以只读“使用系统默认”预留。

**技术栈：** Python 3.12、PySide6、Pillow、ctypes/Win32 User32、pytest、pytest-qt。

---

## 文件结构

- 创建：\`src/petnest/core/cursor_style_catalog.py\` — 发现样式目录、读取元数据、校验 PNG 预览和 \`.cur\` 普通箭头资源。
- 创建：\`src/petnest/platforms/windows_cursor.py\` — 隔离 \`SetSystemCursor\`、从用户 Cursor 注册表恢复 \`OCR_NORMAL\`、非 Windows 安全回退。
- 创建：\`assets/cursors/petnest-paw/style.json\`、\`arrow.png\`、\`arrow.cur\` — 深灰猫爪样式包及其预览、Windows 资源。
- 创建：\`tools/build_cursor_asset.py\` — 从透明 PNG 生成带热点的 CUR；仅用于构建资源。
- 修改：\`src/petnest/models/settings.py\`、\`src/petnest/core/settings_manager.py\` — 偏好字段与 schema 迁移。
- 修改：\`src/petnest/ui/settings_dialog.py\`、\`src/petnest/app.py\` — 设置页和应用生命周期。
- 创建：\`tests/test_cursor_style_catalog.py\`、\`tests/test_windows_cursor.py\`。
- 修改：\`tests/test_settings_manager.py\`、\`tests/test_app_and_platforms.py\`，创建或扩展 \`tests/test_settings_dialog.py\`。

### 任务 1：样式目录、元数据与资源构建

**文件：**
- 创建：\`src/petnest/core/cursor_style_catalog.py\`
- 创建：\`tools/build_cursor_asset.py\`
- 创建：\`assets/cursors/petnest-paw/style.json\`、\`arrow.png\`、\`arrow.cur\`
- 测试：\`tests/test_cursor_style_catalog.py\`

- [x] **步骤 1：编写失败的样式发现测试**

    def test_catalog_only_returns_complete_cursor_styles(tmp_path: Path) -> None:
        _write_style(tmp_path, "paw", with_cursor=True)
        _write_style(tmp_path, "broken", with_cursor=False)

        styles = CursorStyleCatalog(tmp_path).discover()

        assert [(style.identifier, style.display_name) for style in styles] == [("paw", "深灰肉垫")]
        assert styles[0].hotspot == (0, 0)

- [x] **步骤 2：运行测试验证失败**

运行：\`pytest tests/test_cursor_style_catalog.py -v\`

预期：FAIL，报错 \`ModuleNotFoundError: No module named 'petnest.core.cursor_style_catalog'\`。

- [x] **步骤 3：编写最少目录发现、样式模型和资源构建实现**

    @dataclass(frozen=True, slots=True)
    class CursorStyle:
        identifier: str
        display_name: str
        preview_path: Path
        arrow_path: Path
        hotspot: tuple[int, int]

    class CursorStyleCatalog:
        def discover(self) -> list[CursorStyle]:
            return [style for style in self._read_each_subdirectory() if style is not None]

元数据固定为：

    {"id":"petnest-paw","name":"深灰肉垫","preview":"arrow.png","arrow":"arrow.cur","hotspot":[0,0]}

\`build_cursor_asset.py\` 读取透明 PNG、等比缩放到 32×32，并写出 CUR header 中的热点 \`(0, 0)\` 和 PNG 图像数据；生成后用 Pillow 校验预览为 RGBA，并用最小 CUR header 断言校验资源。

- [x] **步骤 4：运行测试验证通过**

运行：\`pytest tests/test_cursor_style_catalog.py -v\`

预期：PASS；损坏样式被忽略，完整样式按 ID 排序返回。

- [x] **步骤 5：Commit**

    git add src/petnest/core/cursor_style_catalog.py tools/build_cursor_asset.py assets/cursors/petnest-paw tests/test_cursor_style_catalog.py
    git commit -m "feat: add cursor style catalog"

### 任务 2：Windows 普通箭头控制器与恢复机制

**文件：**
- 创建：\`src/petnest/platforms/windows_cursor.py\`
- 测试：\`tests/test_windows_cursor.py\`

- [x] **步骤 1：编写失败的 Win32 调用与恢复测试**

    def test_apply_sets_only_normal_cursor(tmp_path: Path) -> None:
        api = _FakeCursorApi()
        controller = WindowsCursorController(api=api, platform="win32")

        assert controller.apply(tmp_path / "arrow.cur") is True
        assert api.set_calls == [(api.copied_handle, OCR_NORMAL)]

    def test_restore_loads_only_users_saved_arrow() -> None:
        api = _FakeCursorApi(registry_arrow="C:/Users/me/arrow.cur")
        controller = WindowsCursorController(api=api, platform="win32")

        assert controller.restore_normal() is True
        assert api.loaded_paths == ["C:/Users/me/arrow.cur"]
        assert api.set_calls == [(api.copied_handle, OCR_NORMAL)]

- [x] **步骤 2：运行测试验证失败**

运行：\`pytest tests/test_windows_cursor.py -v\`

预期：FAIL，报错 \`ModuleNotFoundError: No module named 'petnest.platforms.windows_cursor'\`。

- [x] **步骤 3：实现 Windows API 边界**

    OCR_NORMAL = 32512

    class WindowsCursorController:
        def apply(self, cursor_path: Path) -> bool:
            loaded = self._api.load_file_cursor(cursor_path)
            return loaded is not None and self._api.set_normal_cursor(self._api.copy_cursor(loaded))

        def restore_normal(self) -> bool:
            arrow = self._api.load_saved_arrow_or_system_default()
            return arrow is not None and self._api.set_normal_cursor(self._api.copy_cursor(arrow))

用可注入 \`_CursorApi\` 包装 ctypes 与注册表读取。非 Windows 或任意 Win32 错误只返回 \`False\` 并记录日志。不得调用 \`SPI_SETCURSORS\`，因为它会重设并影响其它系统角色。

- [x] **步骤 4：运行测试验证通过**

运行：\`pytest tests/test_windows_cursor.py -v\`

预期：PASS；\`OCR_NORMAL\` 是唯一被写入的角色，非 Windows 路径安全失败。

- [x] **步骤 5：Commit**

    git add src/petnest/platforms/windows_cursor.py tests/test_windows_cursor.py
    git commit -m "feat: add Windows cursor controller"

### 任务 3：持久化偏好与异常会话标记

**文件：**
- 修改：\`src/petnest/models/settings.py\`
- 修改：\`src/petnest/core/settings_manager.py\`
- 测试：\`tests/test_settings_manager.py\`

- [x] **步骤 1：编写失败的 schema 迁移测试**

    def test_cursor_style_preferences_migrate_from_schema_14(tmp_path: Path) -> None:
        path = tmp_path / "settings.json"
        path.write_text(json.dumps({"schema_version": 14}), encoding="utf-8")

        loaded = SettingsManager(path).load()

        assert (loaded.cursor_style_enabled, loaded.cursor_style_id, loaded.cursor_restore_pending) == (False, None, False)

- [x] **步骤 2：运行测试验证失败**

运行：\`pytest tests/test_settings_manager.py::test_cursor_style_preferences_migrate_from_schema_14 -v\`

预期：FAIL，\`Settings\` 尚无 \`cursor_style_enabled\` 字段。

- [x] **步骤 3：增加设置字段与迁移**

    class Settings:
        SCHEMA_VERSION = 15
        cursor_style_enabled: bool = False
        cursor_style_id: str | None = None
        cursor_restore_pending: bool = False

迁移 14→15 写入默认值。成功替换箭头后持久化 \`cursor_restore_pending=True\`；成功恢复后写入 \`False\`。

- [x] **步骤 4：运行测试验证通过**

运行：\`pytest tests/test_settings_manager.py -v\`

预期：PASS；旧设置迁移、开关与样式 ID 均可原子往返保存。

- [x] **步骤 5：Commit**

    git add src/petnest/models/settings.py src/petnest/core/settings_manager.py tests/test_settings_manager.py
    git commit -m "feat: persist cursor style preferences"

### 任务 4：应用生命周期集成

**文件：**
- 修改：\`src/petnest/app.py\`
- 修改：\`tests/test_app_and_platforms.py\`

- [x] **步骤 1：编写失败的即时应用、退出恢复和启动自愈测试**

    def test_application_restores_pending_cursor_before_showing_window(qtbot, tmp_path: Path) -> None:
        manager = SettingsManager(tmp_path / "settings.json")
        manager.save(Settings(cursor_restore_pending=True))
        controller = _FakeCursorController()

        PetNest(settings_manager=manager, pets_root=_sample_pets(tmp_path), cursor_controller=controller, enable_tray=False)

        assert controller.restore_calls == 1
        assert manager.load().cursor_restore_pending is False

    def test_shutdown_restores_enabled_cursor(qtbot, tmp_path: Path) -> None:
        application = _application_with_enabled_cursor(qtbot, tmp_path)

        application.shutdown()

        assert application.cursor_controller.restore_calls == 1

- [x] **步骤 2：运行测试验证失败**

运行：\`pytest tests/test_app_and_platforms.py -k cursor -v\`

预期：FAIL，\`PetNest.__init__\` 尚不接受 \`cursor_controller\`。

- [x] **步骤 3：注入控制器并实现幂等生命周期调用**

    def __init__(self, *, cursor_controller: WindowsCursorController | None = None, **existing_dependencies: object) -> None:
        self.cursor_catalog = CursorStyleCatalog(bundled_cursor_styles_directory())
        self.cursor_controller = cursor_controller or WindowsCursorController()
        self._recover_pending_cursor_before_showing_window()

    def _configure_cursor_style(self) -> None:
        selected = self.cursor_catalog.get(self.settings.cursor_style_id)
        applied = self.settings.cursor_style_enabled and selected is not None and self.cursor_controller.apply(selected.arrow_path)
        self.settings = replace(self.settings, cursor_restore_pending=applied)
        self.settings_manager.save(self.settings)

\`apply_settings\` 写入设置后调用 \`_configure_cursor_style\`；\`shutdown\` 在隐藏窗口前恢复。所有路径幂等，资源不存在和平台不支持时保留系统箭头并写日志，不弹出启动阻塞错误。

- [x] **步骤 4：运行应用生命周期测试验证通过**

运行：\`pytest tests/test_app_and_platforms.py -k cursor -v\`

预期：PASS；开关、样式不存在、退出和下一次启动的恢复标记均符合预期。

- [x] **步骤 5：Commit**

    git add src/petnest/app.py tests/test_app_and_platforms.py
    git commit -m "feat: apply cursor styles safely"

### 任务 5：设置界面与完整回归

**文件：**
- 修改：\`src/petnest/ui/settings_dialog.py\`
- 创建：\`tests/test_settings_dialog.py\`
- 修改：\`src/petnest/app.py\`

- [x] **步骤 1：编写失败的设置页测试**

    def test_cursor_style_controls_disable_cleanly_and_preserve_advanced_placeholders(qtbot) -> None:
        dialog = SettingsDialog(Settings(cursor_style_enabled=False), cursor_styles=[_style("petnest-paw")])
        qtbot.addWidget(dialog)

        assert dialog.cursor_style_input.isEnabled() is False
        assert dialog.cursor_advanced_group.title() == "高级光标设置（暂未添加其它样式）"

        dialog.cursor_style_enabled_input.setChecked(True)
        assert dialog.cursor_style_input.isEnabled() is True

- [x] **步骤 2：运行测试验证失败**

运行：\`pytest tests/test_settings_dialog.py -v\`

预期：FAIL，\`SettingsDialog\` 尚未接收 \`cursor_styles\`。

- [x] **步骤 3：实现紧凑设置区**

    self.cursor_style_enabled_input = QCheckBox("使用自定义鼠标样式", self)
    self.cursor_style_input = QComboBox(self)
    self.cursor_preview = QLabel(self)
    self.restore_cursor_button = QPushButton("恢复 Windows 默认样式", self)
    self.cursor_advanced_group = QGroupBox("高级光标设置（暂未添加其它样式）", self)

下拉框列出“系统默认”和有效样式；预览随选择更新。高级区用禁用行显示忙碌、文本选择、拖拽/移动、四个调整方向均为“使用系统默认”。恢复按钮只更改表单，确认后由 \`apply_settings\` 恢复。 \`PetNest.show_settings_dialog\` 把目录发现结果传入。

- [x] **步骤 4：运行 UI 与全量测试验证通过**

运行：\`pytest tests/test_settings_dialog.py -v; pytest -q; git diff --check\`

预期：全部 PASS，无空白错误。

- [x] **步骤 5：Commit**

    git add src/petnest/ui/settings_dialog.py src/petnest/app.py tests/test_settings_dialog.py
    git commit -m "feat: add cursor style settings"

### 任务 6：Windows 实机验证与打包检查

**文件：** 无代码修改；必要时仅调整 \`PetNest.spec\` 或安装器资源包含规则。

- [x] **步骤 1：运行开发环境检查**

运行：\`$env:PYTHONPATH = "$pwd\\src"; .venv\\Scripts\\python.exe -m petnest --check\`

预期：输出以 \`PetNest 检查通过：发现\` 开头，并包含至少一个宠物包。

- [x] **步骤 2：人工验证普通箭头生命周期**

运行：\`$env:PYTHONPATH = "$pwd\\src"; .venv\\Scripts\\python.exe -m petnest\`

预期：启用猫爪后仅普通箭头变化；忙碌、文本和调整大小仍使用系统样式；关闭、退出及再次启动后普通箭头恢复。

- [x] **步骤 3：构建安装包并验证资源存在**

运行：\`build_windows.bat; Test-Path 'dist\\PetNest\\_internal\\assets\\cursors\\petnest-paw\\arrow.cur'\`

预期：构建成功且命令输出 \`True\`。

- [x] **步骤 4：Commit 打包配置调整（仅在确有改动时）**

    git add PetNest.spec installer
    git commit -m "build: bundle cursor style assets"


