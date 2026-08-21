# 图片制作动作与资源包双流程实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法跟踪进度。本工作区存在用户的无关未提交改动，只能暂存本计划列出的文件。

**目标：** 保留现有资源包动作导入流程，并在同一页面增加只面向可触发动作槽位的多图片/图片文件夹制作流程。

**架构：** 新建核心动作槽位注册表，统一动作语义、绑定解析和默认动画字段；新建图片动作草稿构建器，负责来源检查、帧排序、画布归一和临时 ActionPack。UI 将图片草稿封装成独立内容组件，`ActionImportPage` 只负责双模式切换、共享目标宠物和统一安装回调，继续复用现有 `install_actions()` 事务安装。

**技术栈：** Python 3.12、PySide6、Pillow、pytest、pytest-qt、PetNest ActionPack/ActionInstaller。

---

## 文件结构

- 创建 `src/petnest/core/action_slots.py`：应用可触发动作注册表、当前宠物绑定解析和默认动画定义。
- 创建 `src/petnest/core/image_action_builder.py`：图片来源检查、自然排序、画布处理、临时动作包构建与清理。
- 创建 `src/petnest/ui/image_action_import_content.py`：图片选择、帧排序、速度控制、新旧预览和安装草稿 UI。
- 修改 `src/petnest/ui/action_import_page.py`：加入“从资源包提取动作 / 用图片制作动作”双模式，保留原资源包状态。
- 修改 `src/petnest/ui/animation_timing_editor.py`：动作触发文案改用统一动作槽位注册表。
- 修改 `src/petnest/ui/pet_action_exchange_dialog.py`：同步双模式页标题、底部按钮和安装完成状态。
- 修改 `src/petnest/app.py`：图片动作安装后的运行时重载、成功清空与失败保留输入。
- 创建 `tests/test_action_slots.py`：槽位集合、绑定解析和默认字段测试。
- 创建 `tests/test_image_action_builder.py`：来源、排序、画布、安全、临时包和清理测试。
- 创建 `tests/test_image_action_import_content.py`：图片模式交互和预览测试。
- 修改 `tests/test_action_import_page.py`：资源包回归、双模式状态和安装委托测试。
- 修改 `tests/test_pet_action_exchange_dialog.py`、`tests/test_app_and_platforms.py`：统一窗口底部、重载和失败回滚回归。
- 同提交 `docs/superpowers/specs/2026-08-20-image-action-import-design.md` 与本计划，不单独提交文档。

---

### 任务 1：统一可触发动作槽位

**文件：**
- 创建：`src/petnest/core/action_slots.py`
- 创建：`tests/test_action_slots.py`
- 修改：`src/petnest/ui/animation_timing_editor.py:37-55,367,395`

- [ ] **步骤 1：编写动作槽位集合和绑定解析失败测试**

```python
def package_with(tmp_path: Path, bindings: dict[str, str]) -> PetPackage:
    return PetPackage(tmp_path, "pet", "Pet", "1.0.0", Canvas(256, 256), {}, bindings, {})


def test_success_slot_uses_current_pet_binding(tmp_path: Path) -> None:
    package = package_with(tmp_path, {"agent.success": "success"})
    slot = action_slot("agent_success")
    assert resolve_slot_action(package, slot) == "success"


def test_unbound_success_slot_uses_review_and_requests_binding(tmp_path: Path) -> None:
    package = package_with(tmp_path, {})
    resolution = resolve_slot(package, action_slot("agent_success"))
    assert resolution.action_name == "review"
    assert resolution.binding == ("agent.success", "review")


def test_registry_does_not_offer_arbitrary_custom_action() -> None:
    assert "custom" not in {slot.key for slot in action_slots()}
```

- [ ] **步骤 2：运行测试确认因模块缺失而失败**

运行：`.venv/Scripts/python.exe -m pytest tests/test_action_slots.py -q`

预期：FAIL，`ModuleNotFoundError: petnest.core.action_slots`。

- [ ] **步骤 3：实现注册表和解析 API**

```python
@dataclass(frozen=True, slots=True)
class ActionSlot:
    key: str
    label: str
    category: str
    canonical_action: str
    binding_event: str | None
    fps: float
    loop: bool
    priority: int
    interruptible: bool
    next_animation: str | None = None
    scope: str = "pet"


@dataclass(frozen=True, slots=True)
class ResolvedActionSlot:
    slot: ActionSlot
    action_name: str
    binding: tuple[str, str] | None


def resolve_slot(package: PetPackage, slot: ActionSlot) -> ResolvedActionSlot:
    bound = package.bindings.get(slot.binding_event) if slot.binding_event else None
    action_name = bound or slot.canonical_action
    binding = None if slot.binding_event is None or bound else (slot.binding_event, action_name)
    return ResolvedActionSlot(slot, action_name, binding)
```

注册表 key 必须固定为：`idle`；`mouse_hover/mouse_click/mouse_drag/mouse_drop`；`move_walk/move_walk_left/move_walk_right/move_walk_up/move_walk_down/move_drag_left/move_drag_right/move_drag_up/move_drag_down`；`agent_working/agent_waiting/agent_success/agent_error`；`system_bored/system_sleep/system_wake`；`work_finish_walk/work_finish_lie_down/work_finish_lie_loop`。其 canonical action 分别使用现有标准名称。不暴露 `codex_running_left` 和任意名称。

- [ ] **步骤 4：让时长编辑器复用注册表文案并运行测试**

运行：`.venv/Scripts/python.exe -m pytest tests/test_action_slots.py tests/test_animation_timing_editor.py -q`

预期：全部 PASS；未知的旧动作仍以动作名展示，不再显示“自定义动作”作为可创建选项。

- [ ] **步骤 5：提交任务 1（包含规格与计划）**

```text
git add src/petnest/core/action_slots.py src/petnest/ui/animation_timing_editor.py tests/test_action_slots.py docs/superpowers/specs/2026-08-20-image-action-import-design.md docs/superpowers/plans/2026-08-20-image-action-import.md
git commit -m feat:image-action-slots
```

---

### 任务 2：图片来源草稿与安全检查

**文件：**
- 创建：`src/petnest/core/image_action_builder.py`
- 创建：`tests/test_image_action_builder.py`

- [ ] **步骤 1：编写多选、文件夹和自然排序失败测试**

```python
def test_inspect_files_naturally_sorts_png_and_webp(tmp_path: Path) -> None:
    frames = make_images(tmp_path, ["10.webp", "2.png", "1.png"])
    draft = inspect_image_files(frames)
    assert [frame.path.name for frame in draft.frames] == ["1.png", "2.png", "10.webp"]


def test_folder_rejects_nested_directories(tmp_path: Path) -> None:
    make_image(tmp_path / "1.png")
    (tmp_path / "another-action").mkdir()
    with pytest.raises(ImageActionSourceError, match="具体动作文件夹"):
        inspect_image_folder(tmp_path)


def test_folder_with_pet_manifest_points_to_resource_mode(tmp_path: Path) -> None:
    (tmp_path / "pet.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ImageActionSourceError, match="从资源包提取动作"):
        inspect_image_folder(tmp_path)
```

- [ ] **步骤 2：运行测试确认缺失 API**

运行：`.venv/Scripts/python.exe -m pytest tests/test_image_action_builder.py -q`

预期：FAIL，无法导入 `inspect_image_files`。

- [ ] **步骤 3：实现不可变草稿、帧错误和限制**

```python
MAX_FRAME_COUNT = 500
MAX_FRAME_EDGE = 8192
MAX_TOTAL_PIXELS = 512_000_000

@dataclass(frozen=True, slots=True)
class ImageActionFrame:
    path: Path
    width: int
    height: int
    has_alpha: bool

@dataclass(frozen=True, slots=True)
class ImageActionDraft:
    frames: tuple[ImageActionFrame, ...]
    source_label: str

    def reordered(self, ordered_paths: Sequence[Path]) -> "ImageActionDraft": ...
```

只允许 PNG/WebP；逐个执行 Pillow `verify()` 与受限 `load()`；拒绝 symlink、junction、非文件、重复路径、空来源、超过帧数/边长/总像素限制。文件夹只读取直接子文件并在存在任何子目录时拒绝。

- [ ] **步骤 4：补充损坏图片、链接、重复和资源上限测试并运行**

运行：`.venv/Scripts/python.exe -m pytest tests/test_image_action_builder.py -q`

预期：全部 PASS。

- [ ] **步骤 5：提交任务 2**

```text
git add src/petnest/core/image_action_builder.py tests/test_image_action_builder.py
git commit -m feat:image-action-source
```

---

### 任务 3：画布归一与临时 ActionPack

**文件：**
- 修改：`src/petnest/core/image_action_builder.py`
- 修改：`tests/test_image_action_builder.py`
- 复用：`src/petnest/core/action_pack.py`、`src/petnest/core/action_installer.py`

- [ ] **步骤 1：编写普通画布、超大帧确认和绑定包测试**

```python
def test_build_centers_small_frames_on_target_canvas(tmp_path: Path) -> None:
    package = package_with_canvas(tmp_path, 256, 256)
    draft = inspect_image_files([make_image(tmp_path / "small.png", (64, 80))])
    with build_image_action_pack(package, action_slot("mouse_click"), draft, fps=12) as pack:
        frame = Image.open(pack.actions["click"].asset_paths[0])
        assert frame.size == (256, 256)
        assert frame.mode == "RGBA"


def test_oversized_frame_requires_explicit_fit(tmp_path: Path) -> None:
    package = package_with_canvas(tmp_path, 256, 256)
    draft = inspect_image_files([make_image(tmp_path / "large.png", (512, 256))])
    with pytest.raises(OversizedFrameConfirmationRequired):
        build_image_action_pack(package, action_slot("mouse_click"), draft, fps=12)


def test_missing_binding_is_included_in_pack(tmp_path: Path) -> None:
    package = package_with_canvas(tmp_path, 256, 256, bindings={})
    draft = inspect_image_files([make_image(tmp_path / "done.png", (256, 256))])
    with build_image_action_pack(package, action_slot("agent_success"), draft, fps=12) as pack:
        assert pack.bindings == {"agent.success": "review"}
```

- [ ] **步骤 2：运行测试确认缺失构建函数**

运行：`.venv/Scripts/python.exe -m pytest tests/test_image_action_builder.py -q`

预期：FAIL，`build_image_action_pack` 未定义。

- [ ] **步骤 3：实现上下文管理的临时包构建器**

```python
@contextmanager
def build_image_action_pack(
    package: PetPackage,
    slot: ActionSlot,
    draft: ImageActionDraft,
    *,
    fps: float,
    fit_oversized: bool = False,
) -> Iterator[ActionPack]:
    with TemporaryDirectory(prefix="petnest-image-action-") as temporary:
        root = Path(temporary)
        resolution = resolve_slot(package, slot)
        # 转 RGBA、居中补画布；仅在 fit_oversized=True 时等比缩小。
        # 生成 TransferAction 与必要 binding，再 yield ActionPack。
        yield pack
```

普通动作输出目标宠物 canvas；首次创建下班全屏动作时以所有帧最大宽高建立画布，已有任一下班全屏动作时复用其 canvas。三个下班阶段画布冲突时拒绝继续；`work_finish_walk` 接收 left/right/none 进入方向。动作 definition 完全来自槽位 preset，瞬时动作写入 `next: context`。

- [ ] **步骤 4：使用真实 `install_actions()` 验证替换与失败恢复**

添加集成测试：构建点击动作包后以 `ConflictDecision.replace()` 安装；断言目标帧、定义和绑定更新。注入 `os.replace` 失败并断言原目录和 `pet.json` 字节不变。

运行：`.venv/Scripts/python.exe -m pytest tests/test_image_action_builder.py tests/test_action_installer.py -q`

预期：全部 PASS。

- [ ] **步骤 5：提交任务 3**

```text
git add src/petnest/core/image_action_builder.py tests/test_image_action_builder.py
git commit -m feat:image-action-pack
```

---

### 任务 4：图片制作内容组件

**文件：**
- 创建：`src/petnest/ui/image_action_import_content.py`
- 创建：`tests/test_image_action_import_content.py`
- 复用：`src/petnest/ui/animation_preview_widget.py`

- [ ] **步骤 1：编写目标动作、帧排序和预览失败测试**

```python
def test_content_lists_only_registered_slots_and_current_binding(qtbot, package) -> None:
    content = ImageActionImportContent((package,), current_pet_id=package.identifier)
    qtbot.addWidget(content)
    assert content.target_combo.currentData() == package.identifier
    assert "自定义动作" not in [content.slot_combo.itemText(i) for i in range(content.slot_combo.count())]


def test_reorder_updates_preview_order(qtbot, image_paths) -> None:
    content.load_files(image_paths)
    content.move_frame(2, 0)
    assert content.ordered_paths()[0] == image_paths[2]
    assert content.preview.frame_count == len(image_paths)
```

- [ ] **步骤 2：运行测试确认组件缺失**

运行：`.venv/Scripts/python.exe -m pytest tests/test_image_action_import_content.py -q`

预期：FAIL，模块无法导入。

- [ ] **步骤 3：实现组件 UI 与公开协议**

```python
class ImageActionImportContent(QWidget):
    draft_changed = Signal()

    def selected_package(self) -> PetPackage | None: ...
    def selected_slot(self) -> ActionSlot | None: ...
    def ordered_paths(self) -> tuple[Path, ...]: ...
    def fps(self) -> float: ...
    def fit_oversized(self) -> bool: ...
    def build_pack(self) -> ContextManager[ActionPack]: ...
    def clear_after_success(self) -> None: ...
```

UI 包含目标宠物、分组动作下拉框、添加图片、选择文件夹、拖放区、可内部移动的缩略图列表、删除按钮、总时长/FPS、`AnimationPreviewWidget` 和当前动作对比预览。大图出现时显示显式“等比缩小以适应”复选框。

- [ ] **步骤 4：补充失败保留、成功清空和目标宠物切换测试**

运行：`.venv/Scripts/python.exe -m pytest tests/test_image_action_import_content.py -q`

预期：全部 PASS。

- [ ] **步骤 5：提交任务 4**

```text
git add src/petnest/ui/image_action_import_content.py tests/test_image_action_import_content.py
git commit -m feat:image-action-content
```

---

### 任务 5：导入动作页双模式与统一安装状态

**文件：**
- 修改：`src/petnest/ui/action_import_page.py`
- 修改：`src/petnest/ui/pet_action_exchange_dialog.py`
- 修改：`tests/test_action_import_page.py`
- 修改：`tests/test_pet_action_exchange_dialog.py`

- [ ] **步骤 1：编写双模式名称、状态保留和资源包回归测试**

```python
def test_action_page_has_approved_two_modes(qtbot, packages, pets_root) -> None:
    page = ActionImportPage(packages, pets_root)
    assert page.resource_mode_button.text() == "从资源包提取动作"
    assert page.image_mode_button.text() == "用图片制作动作"


def test_switching_modes_preserves_both_drafts(qtbot, page, action_pack, image_paths) -> None:
    page.load_source(action_pack)
    page.select_image_mode()
    page.image_content.load_files(image_paths)
    page.select_resource_mode()
    assert page.source_input.text() == str(action_pack)
    page.select_image_mode()
    assert page.image_content.ordered_paths() == tuple(image_paths)
```

- [ ] **步骤 2：运行测试确认双模式控件缺失**

运行：`.venv/Scripts/python.exe -m pytest tests/test_action_import_page.py tests/test_pet_action_exchange_dialog.py -q`

预期：FAIL，`resource_mode_button` 不存在。

- [ ] **步骤 3：把现有资源包 UI 放入资源模式容器并接入图片组件**

使用两个可互斥的分段按钮和 `QStackedWidget`。现有 `_pack`、`source_input`、动作列表和冲突表不重建、不改识别路径；图片模式持有一个 `ImageActionImportContent`。`trigger_primary()` 按当前模式调用 `install_selected()` 或 `install_image_action()`。

- [ ] **步骤 4：实现图片安装、进度、成功和失败协议**

```python
def install_image_action(self) -> None:
    self._installing = True
    self._sync_footer("正在处理图片…")
    QApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
    with self.image_content.build_pack() as pack:
        result = install_actions(
            package.root,
            pack,
            decisions={action_name: ConflictDecision.replace()},
            import_bindings=True,
        )
    self._sync_footer("动作已写入，正在重新加载目标宠物…")
    self.actions_installed.emit(package.identifier, result)
```

`complete_install()` 只清空当前成功模式；`complete_install_failure()` 结束 busy 状态但保留图片草稿。窗口底部主按钮在图片模式显示“安装动作”或“替换动作”。

- [ ] **步骤 5：运行页面和窗口测试**

运行：`.venv/Scripts/python.exe -m pytest tests/test_action_import_page.py tests/test_pet_action_exchange_dialog.py tests/test_image_action_import_content.py -q`

预期：全部 PASS，原资源包测试不改断言即可继续通过。

- [ ] **步骤 6：提交任务 5**

```text
git add src/petnest/ui/action_import_page.py src/petnest/ui/pet_action_exchange_dialog.py tests/test_action_import_page.py tests/test_pet_action_exchange_dialog.py
git commit -m feat:image-action-import-ui
```

---

### 任务 6：应用重载、整体审查与主分支集成

**文件：**
- 修改：`src/petnest/app.py`
- 修改：`tests/test_app_and_platforms.py`
- 审查修复仅限本计划“文件结构”列出的文件；发现超出范围的问题时停止并单独报告。

- [ ] **步骤 1：编写当前宠物替换后重载与失败保留测试**

```python
def test_image_action_install_reloads_current_pet_and_clears_only_after_success(...):
    application._handle_actions_exchange_installed(current_pet_id, result)
    assert application.package.animations["click"].frames[0].is_file()
    assert dialog.action_import_page.image_content.ordered_paths() == ()


def test_reload_failure_restores_action_and_keeps_image_draft(...):
    application._handle_actions_exchange_installed(current_pet_id, result)
    assert original_pet_json.read_bytes() == before
    assert dialog.action_import_page.image_content.ordered_paths() == selected_paths
```

- [ ] **步骤 2：运行应用测试确认必要行为缺失或回归**

运行：`.venv/Scripts/python.exe -m pytest tests/test_app_and_platforms.py -q -k action`

预期：新增测试先 FAIL，原因是成功/失败完成协议未区分图片模式草稿。

- [ ] **步骤 3：最小调整应用完成回调并运行相关回归**

运行：

```text
.venv/Scripts/python.exe -m pytest tests/test_action_slots.py tests/test_image_action_builder.py tests/test_image_action_import_content.py tests/test_action_import_page.py tests/test_pet_action_exchange_dialog.py tests/test_action_installer.py tests/test_action_transfer.py tests/test_app_and_platforms.py -q
```

预期：全部 PASS，平台不允许创建 symlink/junction 的既有测试可 SKIP。

- [ ] **步骤 4：使用 requesting-code-review 审查动作槽位、事务边界和 UI 流程**

审查必须核对：没有不可触发自定义动作；资源包路径未改变；大图不会静默裁剪；临时目录和目标路径不跟随链接；失败保留输入并恢复目标宠物；模式切换不泄漏 ActionPack 临时来源。

- [ ] **步骤 5：运行完整验证**

运行：

```text
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m compileall -q src/petnest
git diff --check
```

预期：pytest 0 failures；compileall exit 0；diff check 无错误。

- [ ] **步骤 6：提交审查修复、精确暂存并集成**

只暂存本计划列出的文件，确认 `git diff --cached --name-only` 后提交：

```text
git commit -m feat:image-action-import
```

将功能提交 cherry-pick 到 `F:\Desktop Projects\PetNest` 的 `main`，在主分支运行相关回归，重启 PetNest，并确认 `127.0.0.1:18486` 恢复监听。

---

### 任务 7：按 v4 原型重构图片帧工作区

**文件：**
- 修改：`src/petnest/ui/image_action_import_content.py`
- 修改：`tests/test_image_action_import_content.py`

- [x] **步骤 1：先写失败测试**

验证动作选择仍为下拉框；帧控件使用 IconMode/网格布局；每个帧卡片存在右上角删除按钮；拖动后 `ordered_paths()` 同步；播放设置和实时预览位于帧网格之后；页面不存在可见的当前/新动作对比切换。

- [x] **步骤 2：运行红灯测试**

运行：`.venv\Scripts\python.exe -m pytest tests\test_image_action_import_content.py -q`

预期：旧版垂直列表和右侧预览结构断言失败。

- [x] **步骤 3：实现帧卡片和单列布局**

创建内部 `ImageFrameCard`，包含缩略图、序号、文件名和右上角删除按钮；`QListWidget` 使用 `IconMode`、`Adjust`、`LeftToRight`、`setWrapping(True)` 和内部移动。删除信号按路径更新 `ImageActionDraft`，移动完成后按 item 顺序重建草稿。移除可见的当前动作预览与切换条，仅保留实际动作文本提示和一个实时预览。

- [x] **步骤 4：验证**

运行：`.venv\Scripts\python.exe -m pytest tests\test_image_action_import_content.py tests\test_action_import_page.py -q`

预期：全部 PASS。

---

### 任务 8：按 v4 原型重构资源包提取页

**文件：**
- 修改：`src/petnest/ui/action_import_page.py`
- 修改：`tests/test_action_import_page.py`
- 修改：`tests/test_pet_action_exchange_dialog.py`

- [x] **步骤 1：先写失败测试**

验证资源模式具有左右两个卡片区域；来源摘要在左；动作表在右；每个动作行包含勾选、动作名、帧数、scope 和安装方式；切换勾选会更新底部数量与安装按钮；原资源识别、冲突决定和事务安装测试保持通过。

- [x] **步骤 2：实现资源动作表**

保留 `action_list` 和 `conflict_table` 兼容属性，但将可见交互合并为 `resource_action_table`。读取来源时按 ActionPack 动作创建行；无冲突显示“新增动作”，冲突行提供“替换现有动作 / 另存为新动作 / 跳过”；另存时自动生成不冲突的动作名。`selected_action_names()` 与 `_conflict_decisions()` 改为从表格行读取。

- [x] **步骤 3：验证**

运行：`.venv\Scripts\python.exe -m pytest tests\test_action_import_page.py tests\test_pet_action_exchange_dialog.py tests\test_action_pack.py tests\test_action_installer.py -q`

预期：全部 PASS。

---

### 任务 9：原型截图复核与收尾

- [x] **步骤 1：在 1220×760 窗口分别截图两个模式**
- [x] **步骤 2：与 `action-import-redesign-v4.html` 对照模式选中态、帧网格、删除位置、预览顺序、资源摘要、动作表和底部按钮**
- [x] **步骤 3：运行相关测试、逐文件全量测试、compileall 和 diff check**
- [ ] **步骤 4：提交、重启 PetNest，并再次截图复核运行版本**
