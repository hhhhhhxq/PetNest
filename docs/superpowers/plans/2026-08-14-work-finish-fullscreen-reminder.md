# 下班全屏动画与加班提醒实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 在实际下班时刻播放当前宠物的全屏走入与躺下动画，提供“下班/再加一会”决策、持久化加班计时和每小时复提醒，并支持 ZIP/文件夹安装专属动作。

**架构：** 宠物包模型增加 `fullscreen` 动画作用域与动作级画布，普通状态机过滤这类动作但现有时长编辑器继续管理它们。纯时间状态模块驱动倒计时文字与提醒时机，独立 Qt 动画层和控制层负责显示；导入服务安全地把标准包安装为当前宠物的两个动作并原子更新 `pet.json`。

**技术栈：** Python 3.12、PySide6、Pillow、pytest、pytest-qt、zipfile、PyInstaller

---

## 文件结构

- 修改 `src/petnest/models/pet_package.py`：为动画定义增加作用域与动作级画布。
- 修改 `src/petnest/core/package_validator.py`：校验全屏作用域、独立画布及绑定限制。
- 修改 `src/petnest/core/package_loader.py`：加载新动画字段。
- 修改 `src/petnest/ui/pet_window.py`：普通桌宠状态机过滤全屏动作。
- 修改 `src/petnest/ui/animation_editor_dialog.py`：为两个下班动作显示明确用途标签。
- 创建 `src/petnest/core/work_finish_animation.py`：解析专属动作及当前宠物回退动作。
- 创建 `src/petnest/core/work_finish_state.py`：纯时间状态转换、超时与整小时节点计算。
- 修改 `src/petnest/models/settings.py`、`src/petnest/core/settings_manager.py`：持久化并迁移当天状态。
- 修改 `src/petnest/ui/work_countdown.py`：把固定/弹性实际下班时刻接入状态模块。
- 创建 `src/petnest/ui/work_finish_reminder.py`：透明全屏动画窗口和左上角控制窗口。
- 创建 `src/petnest/core/work_finish_importer.py`：ZIP/文件夹安全读取、校验、安装与回滚。
- 创建 `src/petnest/ui/work_finish_import_dialog.py`：来源选择、摘要、目标和替换确认。
- 修改 `src/petnest/ui/tray_icon.py`、`src/petnest/app.py`：增加入口并装配状态、窗口、持久化与退出清理。
- 创建 `tools/package_work_finish_sheet.py`：把本次固定 `8 × 3` 原图确定性打成标准导入目录。
- 创建/修改对应测试文件：覆盖模型、状态、UI、导入安全、应用装配和素材工具。

### 任务 1：全屏作用域动画模型

**文件：**
- 修改：`src/petnest/models/pet_package.py`
- 修改：`src/petnest/core/package_validator.py`
- 修改：`src/petnest/core/package_loader.py`
- 修改：`src/petnest/ui/pet_window.py`
- 测试：`tests/test_package_validator.py`
- 测试：`tests/test_package_loader.py`
- 测试：`tests/test_pet_window.py`

- [ ] **步骤 1：编写失败测试，定义作用域和独立画布行为**

```python
def test_fullscreen_animation_can_use_its_own_canvas(tmp_path: Path) -> None:
    root = make_package(tmp_path, canvas=(192, 208))
    write_rgba(root / "animations/work_finish_walk/001.png", size=(256, 224))
    add_animation(root, "work_finish_walk", scope="fullscreen", canvas={"width": 256, "height": 224})
    result = PackageValidator().validate(root)
    assert result.is_valid

def test_pet_scope_animation_cannot_override_canvas(tmp_path: Path) -> None:
    root = make_package(tmp_path, canvas=(192, 208))
    write_rgba(root / "animations/wrong/001.png", size=(256, 224))
    add_animation(root, "wrong", scope="pet", canvas={"width": 256, "height": 224})
    assert any("只有全屏动画" in item for item in PackageValidator().validate(root).errors)
```

- [ ] **步骤 2：运行测试并确认因字段未实现而失败**

运行：`python -m pytest tests/test_package_validator.py tests/test_package_loader.py tests/test_pet_window.py -q`
预期：新测试 FAIL，加载结果没有 `scope`/`canvas` 或 256×224 帧被包级画布拒绝。

- [ ] **步骤 3：实现最小模型、校验和状态机过滤**

```python
@dataclass(frozen=True, slots=True)
class AnimationDefinition:
    # 保留现有字段
    scope: str = "pet"
    canvas: Canvas | None = None

def _animation_canvas(definition: Mapping[str, Any], package_canvas: tuple[int, int] | None, name: str, result: ValidationResult) -> tuple[int, int] | None:
    scope = definition.get("scope", "pet")
    if scope not in {"pet", "fullscreen"}:
        result.errors.append(f"动画 {name} 的 scope 必须是 pet 或 fullscreen")
        return package_canvas
    if scope == "pet" and "canvas" in definition:
        result.errors.append(f"动画 {name}：只有全屏动画可以声明独立 canvas")
        return package_canvas
    return PackageValidator._validate_canvas_mapping(definition.get("canvas"), result, f"动画 {name}") if scope == "fullscreen" else package_canvas
```

`PetWindow` 构建普通状态机时传入 `{name: item for name, item in package.animations.items() if item.scope == "pet"}`；全屏动作保留在 `package.animations` 供编辑器和提醒层使用。

- [ ] **步骤 4：运行相关测试确认通过**

运行：`python -m pytest tests/test_package_validator.py tests/test_package_loader.py tests/test_pet_window.py -q`
预期：全部 PASS。

- [ ] **步骤 5：提交模型变更**

```powershell
git add src/petnest/models/pet_package.py src/petnest/core/package_validator.py src/petnest/core/package_loader.py src/petnest/ui/pet_window.py tests/test_package_validator.py tests/test_package_loader.py tests/test_pet_window.py
git commit -m "feat: support fullscreen animation scope"
```

### 任务 2：下班动画解析与编辑器复用

**文件：**
- 创建：`src/petnest/core/work_finish_animation.py`
- 修改：`src/petnest/ui/animation_editor_dialog.py`
- 测试：`tests/test_work_finish_animation.py`
- 测试：`tests/test_animation_editor_dialog.py`

- [ ] **步骤 1：编写失败测试，锁定专属动作和回退顺序**

```python
def test_resolver_prefers_complete_fullscreen_pair(package_factory) -> None:
    package = package_factory(actions={"idle": "pet", "sleep": "pet", "work_finish_walk": "fullscreen", "work_finish_lie_down": "fullscreen"})
    resolved = resolve_work_finish_animation(package)
    assert resolved.walk.name == "work_finish_walk"
    assert resolved.lie_down.name == "work_finish_lie_down"
    assert resolved.is_specialized

def test_resolver_uses_current_pet_only(package_factory) -> None:
    package = package_factory(actions={"idle": "pet", "sleep": "pet"})
    resolved = resolve_work_finish_animation(package)
    assert resolved.walk.name == "idle"
    assert resolved.lie_down.name == "sleep"
    assert not resolved.is_specialized
```

- [ ] **步骤 2：运行测试确认解析器不存在**

运行：`python -m pytest tests/test_work_finish_animation.py tests/test_animation_editor_dialog.py -q`
预期：FAIL，`petnest.core.work_finish_animation` 无法导入。

- [ ] **步骤 3：实现解析器并添加编辑器标签**

```python
@dataclass(frozen=True, slots=True)
class WorkFinishAnimationSet:
    walk: AnimationDefinition | None
    lie_down: AnimationDefinition | None
    is_specialized: bool

def resolve_work_finish_animation(package: PetPackage) -> WorkFinishAnimationSet:
    walk = package.animations.get("work_finish_walk")
    lie = package.animations.get("work_finish_lie_down")
    if walk and lie and walk.scope == lie.scope == "fullscreen":
        return WorkFinishAnimationSet(walk, lie, True)
    return WorkFinishAnimationSet(
        package.animations.get("walk") or package.animations.get("idle"),
        package.animations.get("sleep") or package.animations.get("idle"),
        False,
    )
```

在 `_TRIGGER_TEXT` 增加 `work_finish_walk: "全屏下班提醒 · 走路循环"` 和 `work_finish_lie_down: "全屏下班提醒 · 躺下过渡"`。现有 `_source_durations`、预览与 `updated_frame_durations()` 不分支复用。

- [ ] **步骤 4：运行测试确认通过并提交**

运行：`python -m pytest tests/test_work_finish_animation.py tests/test_animation_editor_dialog.py -q`
预期：全部 PASS。

```powershell
git add src/petnest/core/work_finish_animation.py src/petnest/ui/animation_editor_dialog.py tests/test_work_finish_animation.py tests/test_animation_editor_dialog.py
git commit -m "feat: resolve work-finish animation sequences"
```

### 任务 3：纯下班状态与设置迁移

**文件：**
- 创建：`src/petnest/core/work_finish_state.py`
- 修改：`src/petnest/models/settings.py`
- 修改：`src/petnest/core/settings_manager.py`
- 测试：`tests/test_work_finish_state.py`
- 测试：`tests/test_settings_manager.py`

- [ ] **步骤 1：编写失败测试覆盖触发、加班、小时节点和超时**

```python
def test_overtime_uses_original_end_and_next_relative_hour() -> None:
    end_at = datetime(2026, 8, 14, 18, 40)
    prompting = advance_work_finish(None, datetime(2026, 8, 14, 18, 45), end_at)
    overtime = continue_overtime(prompting.state, datetime(2026, 8, 14, 18, 46))
    assert overtime.status == "overtime"
    assert overtime.next_prompt_at == datetime(2026, 8, 14, 19, 40)
    assert overtime_duration(overtime, datetime(2026, 8, 14, 18, 50)) == timedelta(minutes=10)

def test_prompt_times_out_after_thirty_absolute_minutes() -> None:
    end_at = datetime(2026, 8, 14, 18, 0)
    transition = advance_work_finish(None, end_at, end_at)
    expired = advance_work_finish(transition.state, end_at + timedelta(minutes=30), end_at)
    assert expired.state.status == "finished"
    assert not expired.should_prompt
```

- [ ] **步骤 2：运行测试确认状态 API 不存在**

运行：`python -m pytest tests/test_work_finish_state.py tests/test_settings_manager.py -q`
预期：FAIL，状态模块和 schema 22 字段不存在。

- [ ] **步骤 3：实现不可变状态转换与宽容序列化**

```python
@dataclass(frozen=True, slots=True)
class WorkFinishState:
    work_date: date
    end_at: datetime
    status: Literal["prompting", "overtime", "finished"]
    prompt_kind: Literal["initial", "hourly"] | None = None
    prompt_started_at: datetime | None = None
    next_prompt_at: datetime | None = None

@dataclass(frozen=True, slots=True)
class WorkFinishTransition:
    state: WorkFinishState
    should_prompt: bool = False
    changed: bool = False
```

实现 `advance_work_finish`、`continue_overtime`、`finish_work`、`overtime_duration`、`state_to_dict` 和 `state_from_dict`。首次补播使用 `prompt_kind="initial"`，只有从 `overtime` 到达小时节点的提醒使用 `prompt_kind="hourly"`，因此启动较晚不会被误判为用户已经选择加班。`Settings` 增加 `work_finish_state: dict[str, str | None] | None`，schema 升至 22；迁移 21→22 时设置 `None`。

- [ ] **步骤 4：运行状态与迁移测试确认通过并提交**

运行：`python -m pytest tests/test_work_finish_state.py tests/test_settings_manager.py -q`
预期：全部 PASS。

```powershell
git add src/petnest/core/work_finish_state.py src/petnest/models/settings.py src/petnest/core/settings_manager.py tests/test_work_finish_state.py tests/test_settings_manager.py
git commit -m "feat: persist work-finish overtime state"
```

### 任务 4：倒计时控制器接入状态

**文件：**
- 修改：`src/petnest/ui/work_countdown.py`
- 测试：`tests/test_work_countdown.py`

- [ ] **步骤 1：编写失败测试覆盖固定和弹性倒计时决策**

```python
def test_countdown_requests_prompt_once_and_shows_overtime(qtbot: QtBot) -> None:
    pet = StubPetWindow()
    prompts: list[datetime] = []
    states: list[WorkFinishState] = []
    countdown = configured_countdown(pet, on_prompt=prompts.append, on_state=states.append)
    countdown.refresh(datetime(2026, 8, 14, 18, 0))
    countdown.refresh(datetime(2026, 8, 14, 18, 0, 1))
    assert len(prompts) == 1
    countdown.continue_overtime(datetime(2026, 8, 14, 18, 1))
    countdown.refresh(datetime(2026, 8, 14, 18, 2))
    assert pet.texts[-1] == "你已加班 00:02:00"
```

- [ ] **步骤 2：运行测试确认 configure/决策方法缺失**

运行：`python -m pytest tests/test_work_countdown.py -q`
预期：新测试 FAIL，`continue_overtime` 或回调参数不存在。

- [ ] **步骤 3：最小接入状态模块**

给 `configure` 增加 `work_finish_state`、`on_work_finish_state`、`on_work_finish_prompt`；固定模式从每日排班计算 `end_at`，弹性模式复用 `elastic_work_end_at`。新增 `continue_overtime(now=None)` 和 `finish_work(now=None)`，每次状态字节变化才回调持久化，每个 `should_prompt` 转换只调用一次显示回调。

- [ ] **步骤 4：运行完整倒计时测试确认通过并提交**

运行：`python -m pytest tests/test_work_countdown.py -q`
预期：全部 PASS。

```powershell
git add src/petnest/ui/work_countdown.py tests/test_work_countdown.py
git commit -m "feat: drive overtime reminders from countdown"
```

### 任务 5：全屏动画层与控制层

**文件：**
- 创建：`src/petnest/ui/work_finish_reminder.py`
- 测试：`tests/test_work_finish_reminder.py`

- [ ] **步骤 1：编写失败 Qt 测试覆盖几何、阶段和按钮**

```python
def test_reminder_uses_full_screen_and_ninety_two_percent_frame_width(qtbot: QtBot, package_factory) -> None:
    geometry = QRect(100, 50, 1000, 800)
    reminder = WorkFinishReminder()
    qtbot.addWidget(reminder.animation_window)
    qtbot.addWidget(reminder.control_window)
    reminder.show_for(package_factory(), geometry, datetime(2026, 8, 14, 18, 0))
    assert reminder.animation_window.geometry() == geometry
    assert reminder.animation_window.target_frame_width == 920
    assert reminder.animation_window.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
```

- [ ] **步骤 2：运行测试确认窗口模块不存在**

运行：`python -m pytest tests/test_work_finish_reminder.py -q`
预期：FAIL，模块无法导入。

- [ ] **步骤 3：实现透明窗口、时间线和控制窗口**

`WorkFinishAnimationWindow` 使用 `Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus`、`WA_TranslucentBackground` 和 `WA_TransparentForMouseEvents`。以 `monotonic()` 计算 4 秒位移和后续一次性躺下时间线；绘制宽度为窗口宽度的 92%，从 `x=window.width()` 线性移动至居中。无帧时窗口隐藏。

`WorkFinishControlWindow` 发出 `finish_requested`、`continue_requested`，以绝对 `prompt_started_at + 30min` 更新剩余时间。`WorkFinishReminder` 统一 `show_for`、`hide`、`set_package` 和 `shutdown`。

- [ ] **步骤 4：运行 UI 测试确认通过并提交**

运行：`python -m pytest tests/test_work_finish_reminder.py -q`
预期：全部 PASS。

```powershell
git add src/petnest/ui/work_finish_reminder.py tests/test_work_finish_reminder.py
git commit -m "feat: add fullscreen work-finish reminder UI"
```

### 任务 6：ZIP/文件夹安全导入服务

**文件：**
- 创建：`src/petnest/core/work_finish_importer.py`
- 测试：`tests/test_work_finish_importer.py`

- [ ] **步骤 1：编写失败测试覆盖等价导入和安全拒绝**

```python
@pytest.mark.parametrize("source_kind", ["folder", "zip"])
def test_import_installs_two_scoped_actions_atomically(tmp_path: Path, source_kind: str) -> None:
    pet = make_pet_package(tmp_path / "pet")
    source = make_work_finish_bundle(tmp_path / "bundle", source_kind=source_kind)
    result = WorkFinishImporter().install(source, pet)
    config = json.loads((pet / "pet.json").read_text(encoding="utf-8"))
    assert result.walk_frames == 8
    assert config["animations"]["work_finish_walk"]["scope"] == "fullscreen"
    assert PackageValidator().validate(pet).is_valid

def test_zip_path_traversal_is_rejected_without_changing_pet(tmp_path: Path) -> None:
    pet = make_pet_package(tmp_path / "pet")
    before = snapshot_tree(pet)
    source = make_zip(tmp_path / "bad.zip", {"../escape.png": b"bad"})
    with pytest.raises(WorkFinishImportError, match="路径"):
        WorkFinishImporter().inspect(source)
    assert snapshot_tree(pet) == before
```

- [ ] **步骤 2：运行测试确认导入服务不存在**

运行：`python -m pytest tests/test_work_finish_importer.py -q`
预期：FAIL，模块无法导入。

- [ ] **步骤 3：实现检查、限额、候选校验和回滚**

定义 `WorkFinishBundle`、`WorkFinishImportResult` 和 `WorkFinishImportError`。限制最多 256 个文件、128 MiB 解压大小、100:1 压缩比；拒绝绝对路径、`..`、驱动器路径、重复的大小写折叠路径和符号链接。安装时在宠物包同级临时目录复制完整候选包，修改候选 `pet.json` 后运行 `PackageValidator`；通过后用备份目录交换两个动作目录和配置，异常时恢复。

- [ ] **步骤 4：运行导入服务测试确认通过并提交**

运行：`python -m pytest tests/test_work_finish_importer.py -q`
预期：全部 PASS。

```powershell
git add src/petnest/core/work_finish_importer.py tests/test_work_finish_importer.py
git commit -m "feat: import work-finish animation bundles"
```

### 任务 7：导入 UI、托盘入口与应用装配

**文件：**
- 创建：`src/petnest/ui/work_finish_import_dialog.py`
- 修改：`src/petnest/ui/tray_icon.py`
- 修改：`src/petnest/app.py`
- 测试：`tests/test_work_finish_import_dialog.py`
- 测试：`tests/test_app_and_platforms.py`

- [ ] **步骤 1：编写失败测试覆盖入口、持久化、换宠和退出**

```python
def test_app_persists_overtime_choice_and_closes_reminder_on_shutdown(qtbot: QtBot, tmp_path: Path) -> None:
    application = make_application(tmp_path)
    application.work_countdown.refresh(datetime(2026, 8, 14, 18, 0))
    application.work_finish_reminder.control_window.continue_button.click()
    assert application.settings.work_finish_state["status"] == "overtime"
    application.shutdown()
    assert not application.work_finish_reminder.animation_window.isVisible()
    assert not application.work_finish_reminder.control_window.isVisible()
```

- [ ] **步骤 2：运行 UI/应用测试确认新入口不存在**

运行：`python -m pytest tests/test_work_finish_import_dialog.py tests/test_app_and_platforms.py -q`
预期：FAIL，导入对话框、托盘动作或提醒装配属性不存在。

- [ ] **步骤 3：实现导入对话框与应用连接**

对话框允许选择 `.zip` 或目录，调用 `inspect` 展示当前宠物、名称、画布、8/13 等帧数；确认后调用 `install`。托盘新增“导入下班动画…”。`PetNest` 创建提醒对象，将状态回调保存为 `replace(self.settings, work_finish_state=state_to_dict(state))`，将按钮连接到倒计时控制器，并在 `switch_pet`、`reload_current_pet`、资源导入和 `shutdown` 时更新或清理提醒。

- [ ] **步骤 4：运行应用测试确认通过并提交**

运行：`python -m pytest tests/test_work_finish_import_dialog.py tests/test_app_and_platforms.py -q`
预期：全部 PASS。

```powershell
git add src/petnest/ui/work_finish_import_dialog.py src/petnest/ui/tray_icon.py src/petnest/app.py tests/test_work_finish_import_dialog.py tests/test_app_and_platforms.py
git commit -m "feat: wire work-finish reminder and importer"
```

### 任务 8：确定性素材打包与本地 `pingan` 安装

**文件：**
- 创建：`tools/package_work_finish_sheet.py`
- 创建：`tests/test_package_work_finish_sheet.py`
- 本地生成但不暂存：原工作区 `pets/pingan/animations/work_finish_walk/*.png`
- 本地生成但不暂存：原工作区 `pets/pingan/animations/work_finish_lie_down/*.png`
- 本地修改但不暂存：原工作区 `pets/pingan/pet.json`

- [ ] **步骤 1：编写失败测试锁定 8/7/6 切帧结果**

```python
def test_packager_exports_expected_rgba_frames(tmp_path: Path) -> None:
    sheet = make_sheet(tmp_path / "sheet.png", columns=8, rows=3, cell=(256, 224))
    output = tmp_path / "bundle"
    package_sheet(sheet, output)
    assert len(list((output / "walk").glob("*.png"))) == 8
    assert len(list((output / "lie-down").glob("*.png"))) == 13
    with Image.open(output / "lie-down/013.png") as frame:
        assert frame.size == (256, 224)
        assert frame.mode == "RGBA"
```

- [ ] **步骤 2：运行测试确认工具函数不存在**

运行：`python -m pytest tests/test_package_work_finish_sheet.py -q`
预期：FAIL，工具或 `package_sheet` 无法导入。

- [ ] **步骤 3：实现固定布局打包工具**

工具验证输入恰为 `2048 × 672`，按 256×224 格子导出第一行 8 帧，以及第二行前 7 帧加第三行前 6 帧，并生成标准 `manifest.json`。输出使用新目录或空目录，不覆盖已有包。

- [ ] **步骤 4：运行工具测试确认通过并提交工具**

运行：`python -m pytest tests/test_package_work_finish_sheet.py -q`
预期：PASS。

```powershell
git add tools/package_work_finish_sheet.py tests/test_package_work_finish_sheet.py
git commit -m "feat: package work-finish sprite sheets"
```

- [ ] **步骤 5：在原工作区本地安装用户素材但不暂存 `pingan`**

运行打包工具处理 `C:\Users\pc\AppData\Local\Temp\codex-clipboard-fdbc7a33-7268-4c8f-af66-3cc424caf253.png`，再使用 `WorkFinishImporter.install()` 安装到 `F:\Desktop Projects\PetNest\pets\pingan`。运行 `PackageValidator().validate(...)`，预期 `is_valid=True`；确认 `git status` 中没有暂存任何 `pets/pingan` 文件。

### 任务 9：完整验证与视觉验收

**文件：**
- 生成但不提交：`tmp/work-finish-qa/contact-sheet.png`
- 生成但不提交：`tmp/work-finish-qa/fullscreen-reminder.png`

- [ ] **步骤 1：运行定向测试**

运行：

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest tests/test_package_validator.py tests/test_package_loader.py tests/test_work_finish_animation.py tests/test_work_finish_state.py tests/test_work_countdown.py tests/test_work_finish_reminder.py tests/test_work_finish_importer.py tests/test_work_finish_import_dialog.py tests/test_package_work_finish_sheet.py -q
```

预期：全部 PASS，0 failed。

- [ ] **步骤 2：运行完整测试套件**

运行：`python -m pytest`
预期：0 failed；只允许基线已有的 Windows 符号链接权限跳过。

- [ ] **步骤 3：运行构建检查**

运行：`python -m PyInstaller --noconfirm --clean --onedir --windowed --name PetNest-QA --icon assets/icons/petnest-app.ico --paths src --add-data "assets;assets" src/petnest_launcher.py`
预期：退出码 0，`dist/PetNest-QA/PetNest-QA.exe` 存在。

- [ ] **步骤 4：生成并检查视觉证据**

用 Pillow 生成 21 帧接触表；以 Qt 测试夹具在 1920×1080 虚拟几何上捕获动画中央最终态，确认绘制目标宽度约 1766 像素、透明背景、左上角按钮可读、猫保持宽高比且没有黑底。

- [ ] **步骤 5：检查提交与工作区范围**

运行：`git status --short`、`git diff --check`、`git log --oneline --decorate -12`。预期功能 worktree 无未提交实现文件；原工作区只保留用户原有未提交内容和本地 `pingan` 安装，未暂存任何无关文件。

完成后使用 `superpowers:requesting-code-review` 审查规格覆盖与回归风险，再使用 `superpowers:finishing-a-development-branch` 选择集成方式。
