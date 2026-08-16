# 宠物与动作交换中心实施计划

> **执行要求：** 实施时使用 `executing-plans`；每项功能先写失败测试，再写最小实现。过程提交只留在 `codex/pet-action-exchange-center`，最终基于最新 `origin/main` 执行 `git merge --squash`，主分支只保留一个功能提交。

**目标：** 将现有“导入精灵图”和“导入下班动画”整合为一个面向普通用户的宠物/动作导入导出中心，支持完整宠物、动作分享包、旧版下班动画包以及精灵图，提供预览、冲突处理、备份和原子回滚。

**架构：** 核心层负责来源解包、类型探测、动作规范化、分享包生成、冲突决策、事务安装和完整宠物替换；UI 层使用一个入口和三个页面（导入动作、导出动作、导入宠物）。动画预览从编辑器中抽成复用控件。所有写入先在同文件系统的候选目录完成并通过现有 `PackageValidator`，之后再原子切换，失败时恢复旧资源。

**技术栈：** Python 3.11、PySide6、Pillow、pytest、现有 `PackageLoader` / `PackageValidator` / `SpriteSheetImporter`。

## 文件结构

新增核心文件：

- `src/petnest/core/exchange_source.py`：文件夹/ZIP 安全展开、大小限制、来源类型探测。
- `src/petnest/core/action_transfer.py`：可传输动作模型、完整宠物动作提取。
- `src/petnest/core/action_pack.py`：通用动作分享包读写。
- `src/petnest/core/package_transaction.py`：候选目录、备份、切换、回滚。
- `src/petnest/core/action_installer.py`：动作冲突与引用重写。
- `src/petnest/core/pet_package_importer.py`：完整宠物新增/更新。
- `src/petnest/ui/animation_preview_widget.py`：通用动画预览控件。
- `src/petnest/ui/action_export_page.py`：动作选择、预览与导出。
- `src/petnest/ui/action_import_page.py`：动作来源、目标与冲突配置。
- `src/petnest/ui/pet_import_page.py`：完整包/精灵图宠物导入。
- `src/petnest/ui/pet_action_exchange_dialog.py`：统一交换中心窗口。

修改现有文件：

- `src/petnest/core/work_finish_importer.py`：改为旧格式适配器。
- `src/petnest/ui/animation_editor_dialog.py`：复用通用预览控件。
- `src/petnest/ui/spritesheet_import_dialog.py`：拆出可嵌入页面，保留兼容对话框。
- `src/petnest/ui/tray_icon.py`、`src/petnest/app.py`：统一入口和安装后的运行时重载。
- `README.md`：用户可见格式、导入/导出和冲突说明。

每个新增核心模块对应同名测试；UI 测试沿用 `pytest-qt` 风格并使用临时宠物目录。

## Task 1：安全读取文件夹和 ZIP

**文件：**

- 新建 `src/petnest/core/exchange_source.py`
- 新建 `tests/test_exchange_source.py`

- [ ] **1.1 写失败测试：文件夹、单层外包目录和 ZIP 都归一到内容根目录**

```python
def test_materialize_zip_unwraps_one_outer_directory(tmp_path):
    archive = build_zip(tmp_path, {"shared/petnest-action-pack.json": "{}"})
    with ExchangeSource.open(archive) as source:
        assert source.root.name == "shared"
        assert (source.root / "petnest-action-pack.json").is_file()
```

- [ ] **1.2 写失败测试：拒绝路径穿越、符号链接、可执行文件、文件数和解压体积超限**

```python
@pytest.mark.parametrize("member", ["../escape.png", "/absolute.png"])
def test_rejects_unsafe_zip_member(tmp_path, member):
    archive = build_zip(tmp_path, {member: b"x"})
    with pytest.raises(UnsafeExchangeSourceError):
        ExchangeSource.open(archive)
```

- [ ] **1.3 运行并确认失败**

运行：`python -m pytest tests/test_exchange_source.py -q`

预期：因 `petnest.core.exchange_source` 不存在而失败。

- [ ] **1.4 实现上下文管理器和安全限制**

```python
@dataclass
class ExchangeLimits:
    max_files: int = 2000
    max_uncompressed_bytes: int = 512 * 1024 * 1024
    blocked_suffixes: tuple[str, ...] = (".exe", ".dll", ".bat", ".cmd", ".ps1")

class ExchangeSource:
    @classmethod
    def open(cls, path: Path, limits: ExchangeLimits | None = None) -> "ExchangeSource": ...
    def __enter__(self) -> "ExchangeSource": ...
    def __exit__(self, *_: object) -> None: ...
```

ZIP 只允许普通文件和目录；先校验所有成员再解压；临时目录随上下文释放。外包目录只在根目录恰好有一个目录且没有有效清单时展开一层。

- [ ] **1.5 运行测试并提交**

运行：`python -m pytest tests/test_exchange_source.py -q`

预期：全部通过。

提交：`git add src/petnest/core/exchange_source.py tests/test_exchange_source.py && git commit -m "feat: add safe exchange source reader"`

## Task 2：探测来源类型并提取可传输动作

**文件：**

- 新建 `src/petnest/core/action_transfer.py`
- 修改 `src/petnest/core/exchange_source.py`
- 新建 `tests/test_action_transfer.py`
- 修改 `tests/test_exchange_source.py`

- [ ] **2.1 写失败测试：准确探测完整宠物、通用动作包、旧版下班包和精灵图**

```python
@pytest.mark.parametrize(("marker", "kind"), [
    ("pet.json", SourceKind.PET_PACKAGE),
    ("petnest-action-pack.json", SourceKind.ACTION_PACK),
    ("work-finish-manifest.json", SourceKind.LEGACY_WORK_FINISH),
])
def test_detects_manifest_type(tmp_path, marker, kind): ...
```

同时测试一个目录出现多个标记时抛出 `AmbiguousExchangeSourceError`；单张 PNG 返回 `SourceKind.SPRITESHEET`，普通未知目录返回明确错误。

- [ ] **2.2 写失败测试：从 `pet.json` 原始字典提取全部动作字段**

```python
def test_extract_actions_preserves_supported_animation_fields(pet_dir):
    actions = extract_pet_actions(pet_dir)
    assert actions["walk"].definition["next"] == "idle"
    assert actions["walk"].definition["frame_durations_ms"] == [80, 120]
    assert actions["walk"].scope == "pet"
```

测试保留 `path`、`fps`、`loop`、`next`、`priority`、`interruptible`、`restart_on_reenter`、`frame_durations_ms`、`speed_multiplier`、`frames`、`scope`、`canvas`；拒绝资源路径逃出宠物目录。

- [ ] **2.3 运行并确认失败**

运行：`python -m pytest tests/test_exchange_source.py tests/test_action_transfer.py -q`

预期：缺少来源枚举和动作提取 API。

- [ ] **2.4 实现来源枚举、动作模型和原始 JSON 白名单提取**

```python
class SourceKind(StrEnum):
    PET_PACKAGE = "pet-package"
    ACTION_PACK = "action-pack"
    LEGACY_WORK_FINISH = "legacy-work-finish"
    SPRITESHEET = "spritesheet"

@dataclass(frozen=True)
class TransferAction:
    name: str
    definition: dict[str, object]
    asset_paths: tuple[Path, ...]
    scope: str
```

不要先转成 `AnimationDefinition` 再导出，避免把 `pet.json` 使用的 `next` 字段误写成内部属性名 `next_animation`。

- [ ] **2.5 运行测试并提交**

运行：`python -m pytest tests/test_exchange_source.py tests/test_action_transfer.py -q`

预期：全部通过。

提交：`git add src/petnest/core/exchange_source.py src/petnest/core/action_transfer.py tests/test_exchange_source.py tests/test_action_transfer.py && git commit -m "feat: detect exchange sources and extract actions"`

## Task 3：生成和读取通用动作分享包

**文件：**

- 新建 `src/petnest/core/action_pack.py`
- 新建 `tests/test_action_pack.py`

- [ ] **3.1 写失败测试：多选动作导出 ZIP 并能往返读取**

```python
def test_export_selected_actions_round_trips(tmp_path, pet_dir):
    output = tmp_path / "分享动作.zip"
    export_action_pack(pet_dir, ["walk", "sleep"], output)
    pack = load_action_pack(output)
    assert set(pack.actions) == {"walk", "sleep"}
    assert pack.source_pet.identifier == "pingan"
```

- [ ] **3.2 写失败测试：只复制所选动作资源、重写包内路径并可选导出绑定**

断言资源位于 `animations/<action>/...`，清单为 `petnest-action-pack.json`，未选择的文件不进入 ZIP；`include_bindings=False` 时不导出绑定和回退，开启时只保留引用已选动作的条目。

- [ ] **3.3 运行并确认失败**

运行：`python -m pytest tests/test_action_pack.py -q`

预期：模块不存在。

- [ ] **3.4 实现 schema v1、确定性 ZIP 和原子输出**

```python
ACTION_PACK_MANIFEST = "petnest-action-pack.json"

@dataclass(frozen=True)
class ActionPack:
    name: str
    source_pet: SourcePetInfo
    actions: dict[str, TransferAction]
    bindings: dict[str, str]
    fallbacks: dict[str, list[str]]
```

清单顶层写入 `type`、`schema_version`、`name`、`author`、`description`、`source_pet`、`animations`，绑定和回退为可选字段。先写同目录临时文件，成功后 `Path.replace()`，不覆盖失败前的目标 ZIP。

- [ ] **3.5 运行测试并提交**

运行：`python -m pytest tests/test_action_pack.py -q`

预期：全部通过，并校验 ZIP 内文件名顺序固定。

提交：`git add src/petnest/core/action_pack.py tests/test_action_pack.py && git commit -m "feat: add generic action share packs"`

## Task 4：事务安装动作并处理冲突

**文件：**

- 新建 `src/petnest/core/package_transaction.py`
- 新建 `src/petnest/core/action_installer.py`
- 新建 `tests/test_package_transaction.py`
- 新建 `tests/test_action_installer.py`

- [ ] **4.1 写失败测试：替换、重命名和跳过三种动作冲突**

```python
@pytest.mark.parametrize(("decision", "expected"), [
    (ConflictDecision.replace(), "walk"),
    (ConflictDecision.rename("walk_shared"), "walk_shared"),
    (ConflictDecision.skip(), None),
])
def test_install_action_conflict_decisions(target_pet, pack, decision, expected): ...
```

重命名测试同时断言动作自己的 `next`、导入的 bindings 和 fallbacks 中的引用被重写；默认 `import_bindings=False`，不得改动目标宠物绑定。

- [ ] **4.2 写失败测试：校验或切换失败时目标宠物字节不变**

```python
def test_transaction_rolls_back_when_validator_rejects(target_pet, invalid_pack):
    before = snapshot_tree(target_pet)
    with pytest.raises(ActionInstallError):
        install_actions(target_pet, invalid_pack, decisions={})
    assert snapshot_tree(target_pet) == before
```

- [ ] **4.3 运行并确认失败**

运行：`python -m pytest tests/test_package_transaction.py tests/test_action_installer.py -q`

预期：事务和安装模块不存在。

- [ ] **4.4 实现同文件系统候选目录、验证、原子切换和恢复**

```python
class PackageTransaction:
    def __init__(self, target: Path, validator: Callable[[Path], None]): ...
    def prepare(self) -> Path: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...
```

候选目录与目标目录同级；复制目标到候选目录，在候选目录应用变更并运行 `PackageValidator`。提交时先将原目录改名为恢复目录，再将候选目录改为正式名；第二步失败必须立即恢复。异常退出清理候选目录，但不得删除用户原目录。

- [ ] **4.5 实现动作安装器**

```python
def install_actions(
    target_pet: Path,
    pack: ActionPack,
    decisions: Mapping[str, ConflictDecision],
    *,
    import_bindings: bool = False,
) -> InstallResult: ...
```

替换动作时移除该动作旧资源；重命名必须验证目标名不冲突且符合现有动作命名规则；复制资源后更新候选 `pet.json`，最后统一验证。

- [ ] **4.6 运行测试并提交**

运行：`python -m pytest tests/test_package_transaction.py tests/test_action_installer.py tests/test_package_validator.py -q`

预期：全部通过。

提交：`git add src/petnest/core/package_transaction.py src/petnest/core/action_installer.py tests/test_package_transaction.py tests/test_action_installer.py && git commit -m "feat: install shared actions transactionally"`

## Task 5：完整宠物新增与更新

**文件：**

- 新建 `src/petnest/core/pet_package_importer.py`
- 新建 `tests/test_pet_package_importer.py`

- [ ] **5.1 写失败测试：新增宠物和同 ID 更新**

```python
def test_import_new_pet_installs_validated_package(pets_root, source_pet):
    result = import_pet_package(source_pet, pets_root)
    assert result.pet_id == "pingan"
    assert (pets_root / "pingan" / "pet.json").is_file()
```

更新默认完整替换；先在 `<pets-root>/.backups/<id>/<timestamp>.zip` 生成可恢复备份。测试备份包含更新前的 `pet.json` 和动画文件。

- [ ] **5.2 写失败测试：可保留只存在于本地的动作**

```python
def test_update_can_preserve_local_only_actions(pets_root, source_pet):
    result = import_pet_package(source_pet, pets_root, preserve_local_actions=True)
    manifest = load_json(pets_root / "pingan" / "pet.json")
    assert "local_dance" in manifest["animations"]
```

若本地独有动作依赖的资源或引用无法安全迁移，更新预检应阻止写入并说明具体动作，而不是静默丢失。

- [ ] **5.3 写失败测试：无效包、备份失败和安装失败都不改变现状**

运行：`python -m pytest tests/test_pet_package_importer.py -q`

预期：模块不存在。

- [ ] **5.4 实现完整宠物导入服务**

```python
@dataclass(frozen=True)
class PetImportOptions:
    preserve_local_actions: bool = False
    create_backup: bool = True

def import_pet_package(source: Path, pets_root: Path, options: PetImportOptions) -> PetImportResult: ...
```

`.backups` 没有根级 `pet.json`，现有 `PackageLoader.discover()` 会自然忽略；仍补测试锁定此行为。备份 ZIP 也使用临时文件后原子改名。

- [ ] **5.5 运行测试并提交**

运行：`python -m pytest tests/test_pet_package_importer.py tests/test_package_loader.py tests/test_package_validator.py -q`

预期：全部通过。

提交：`git add src/petnest/core/pet_package_importer.py tests/test_pet_package_importer.py tests/test_package_loader.py && git commit -m "feat: import and update complete pet packages"`

## Task 6：兼容旧版下班动画包

**文件：**

- 修改 `src/petnest/core/work_finish_importer.py`
- 修改 `tests/test_work_finish_importer.py`
- 修改 `src/petnest/core/action_transfer.py`
- 修改 `tests/test_action_transfer.py`

- [ ] **6.1 写失败测试：旧包转换为两个普通可传输动作**

```python
def test_legacy_work_finish_pack_adapts_to_transfer_actions(legacy_pack):
    imported = load_transfer_source(legacy_pack)
    assert set(imported.actions) == {"work_finish_enter", "work_finish_lie"}
    assert imported.legacy is True
```

使用仓库当前支持的真实旧清单字段名，不额外发明第二套兼容格式。

- [ ] **6.2 写失败测试：旧入口行为保持兼容**

现有 `WorkFinishImporter` 对合法包仍返回相同结果；内部委托通用动作安装器。测试缺失进入/躺下动作时继续返回用户可理解的错误。

- [ ] **6.3 运行并确认失败**

运行：`python -m pytest tests/test_work_finish_importer.py tests/test_action_transfer.py -q`

预期：新的适配 API 尚未存在。

- [ ] **6.4 实现适配器并去除重复复制逻辑**

只在边界层把旧清单映射为 `ActionPack`；冲突、路径安全、验证和事务全部复用 Task 1–4。

- [ ] **6.5 运行测试并提交**

运行：`python -m pytest tests/test_work_finish_importer.py tests/test_action_transfer.py tests/test_action_installer.py -q`

预期：新旧测试全部通过。

提交：`git add src/petnest/core/work_finish_importer.py src/petnest/core/action_transfer.py tests/test_work_finish_importer.py tests/test_action_transfer.py && git commit -m "refactor: adapt legacy work finish packs"`

## Task 7：抽取可复用动画预览控件

**文件：**

- 新建 `src/petnest/ui/animation_preview_widget.py`
- 新建 `tests/test_animation_preview_widget.py`
- 修改 `src/petnest/ui/animation_editor_dialog.py`
- 修改 `tests/test_animation_editor_dialog.py`

- [ ] **7.1 写失败测试：控件按 FPS 或逐帧时长播放**

```python
def test_preview_uses_frame_durations_when_present(qtbot, preview_widget, animation):
    preview_widget.set_animation(animation)
    assert preview_widget.next_delay_ms() == animation.frame_durations_ms[0]
```

覆盖暂停/继续、循环、透明棋盘格、缩放但保持纵横比、资源缺失时停止定时器并显示错误占位。

- [ ] **7.2 写失败测试：编辑器继续保留原预览行为**

断言编辑器创建 `AnimationPreviewWidget`，切换动作会刷新预览，关闭窗口后没有活动预览计时器。

- [ ] **7.3 运行并确认失败**

运行：`python -m pytest tests/test_animation_preview_widget.py tests/test_animation_editor_dialog.py -q`

预期：通用控件尚不存在。

- [ ] **7.4 移动 `CheckerboardLabel` 和播放状态，编辑器改为组合控件**

```python
class AnimationPreviewWidget(QWidget):
    def set_animation(self, definition: Mapping[str, object], root: Path) -> None: ...
    def set_playing(self, playing: bool) -> None: ...
    def clear(self) -> None: ...
```

保持 `_TRIGGER_TEXT` 在编辑器自身；只抽取真正通用的画面与时间轴，不改变编辑器数据模型。

- [ ] **7.5 运行测试并提交**

运行：`python -m pytest tests/test_animation_preview_widget.py tests/test_animation_editor_dialog.py -q`

预期：全部通过。

提交：`git add src/petnest/ui/animation_preview_widget.py src/petnest/ui/animation_editor_dialog.py tests/test_animation_preview_widget.py tests/test_animation_editor_dialog.py && git commit -m "refactor: extract reusable animation preview"`

## Task 8：动作导出页面

**文件：**

- 新建 `src/petnest/ui/action_export_page.py`
- 新建 `tests/test_action_export_page.py`

- [ ] **8.1 写失败测试：列出宠物全部动作并支持搜索、范围筛选和多选**

```python
def test_export_page_lists_every_animation(qtbot, loaded_pet):
    page = ActionExportPage([loaded_pet])
    qtbot.addWidget(page)
    assert page.visible_action_names() == set(loaded_pet.animations)
```

范围筛选至少覆盖普通宠物动作、全屏动作和全部；筛选只影响显示，不应清除已选择项。页面显示“已选 N 项”。

- [ ] **8.2 写失败测试：选中动作可预览并导出一个 ZIP**

模拟文件保存选择，断言调用 `export_action_pack()` 的动作集合准确；没有选择时导出按钮禁用；导出成功展示目标路径和“打开所在文件夹”操作。

- [ ] **8.3 运行并确认失败**

运行：`python -m pytest tests/test_action_export_page.py -q`

预期：页面模块不存在。

- [ ] **8.4 实现动作列表模型、详情预览和导出选项**

页面左侧为宠物和动作列表，右侧复用 `AnimationPreviewWidget`；高级选项只展示“同时分享动作绑定”，默认关闭。面向用户的文案使用“动作包”，不出现 schema、manifest、scope。

- [ ] **8.5 运行测试并提交**

运行：`python -m pytest tests/test_action_export_page.py tests/test_animation_preview_widget.py tests/test_action_pack.py -q`

预期：全部通过。

提交：`git add src/petnest/ui/action_export_page.py tests/test_action_export_page.py && git commit -m "feat: add action export page"`

## Task 9：动作导入页面

**文件：**

- 新建 `src/petnest/ui/action_import_page.py`
- 新建 `tests/test_action_import_page.py`

- [ ] **9.1 写失败测试：接受动作包、完整宠物和旧版下班包**

```python
@pytest.mark.parametrize("source_kind", [
    SourceKind.ACTION_PACK,
    SourceKind.PET_PACKAGE,
    SourceKind.LEGACY_WORK_FINISH,
])
def test_action_import_page_loads_supported_source(qtbot, source_kind, source_factory): ...
```

选择完整宠物时列出其全部动作供勾选；选择动作包时默认全选；旧版包给出“旧版下班动画，已自动兼容”的轻提示。

- [ ] **9.2 写失败测试：每个冲突可选替换、重命名或跳过**

冲突行默认“替换”；重命名时即时验证名称；非冲突动作显示“新增”。“同时导入动作绑定”默认关闭。只有所有冲突决定有效时安装按钮可用。

- [ ] **9.3 写失败测试：当前宠物正在显示下班提醒时阻止修改**

页面接收 `is_pet_locked(pet_id)` 回调；锁定时不调用安装器，并提示先结束当前提醒。其他宠物仍可安装。

- [ ] **9.4 运行并确认失败**

运行：`python -m pytest tests/test_action_import_page.py -q`

预期：页面模块不存在。

- [ ] **9.5 实现来源摘要、目标宠物、动作选择、冲突表和预览**

安装完成后发出 `actions_installed(pet_id, result)` 信号，让应用层统一重载；页面不直接操纵当前宠物窗口。

- [ ] **9.6 运行测试并提交**

运行：`python -m pytest tests/test_action_import_page.py tests/test_action_installer.py tests/test_work_finish_importer.py -q`

预期：全部通过。

提交：`git add src/petnest/ui/action_import_page.py tests/test_action_import_page.py && git commit -m "feat: add action import page"`

## Task 10：宠物导入页面并嵌入精灵图流程

**文件：**

- 新建 `src/petnest/ui/pet_import_page.py`
- 新建 `tests/test_pet_import_page.py`
- 修改 `src/petnest/ui/spritesheet_import_dialog.py`
- 修改 `tests/test_spritesheet_import_dialog.py`

- [ ] **10.1 写失败测试：页面可选择“文件夹/ZIP”或“精灵图”**

```python
def test_pet_import_page_switches_source_mode(qtbot):
    page = PetImportPage()
    page.select_mode(PetImportMode.SPRITESHEET)
    assert page.sprite_sheet_page.isVisibleTo(page)
```

文件夹/ZIP 模式显示来源宠物名称、ID、版本和动作数量；同 ID 时明确标记为“更新现有宠物”。

- [ ] **10.2 写失败测试：更新默认整包替换，可勾选保留本地独有动作**

新增宠物不显示保留选项；更新宠物时默认不勾选，用户勾选后把 `preserve_local_actions=True` 传给核心服务，并显示将创建备份的说明。

- [ ] **10.3 写失败测试：现有精灵图导入流程可作为页面复用**

把原对话框主体抽为 `SpriteSheetImportPage`，保留 `SpriteSheetImportDialog` 薄包装器。现有帧数、行列、FPS、透明背景、动作映射和预览测试必须继续通过。

- [ ] **10.4 运行并确认失败**

运行：`python -m pytest tests/test_pet_import_page.py tests/test_spritesheet_import_dialog.py -q`

预期：新页面和可嵌入组件不存在。

- [ ] **10.5 实现宠物包导入与嵌入式精灵图流程**

两个来源模式都在完成后发出 `pet_installed(pet_id, result)`；完整宠物使用 `PetPackageImporter`，精灵图继续使用 `SpriteSheetImporter`，从而完整复用已有帧数调整能力。

- [ ] **10.6 运行测试并提交**

运行：`python -m pytest tests/test_pet_import_page.py tests/test_spritesheet_import_dialog.py tests/test_spritesheet_importer.py -q`

预期：全部通过。

提交：`git add src/petnest/ui/pet_import_page.py src/petnest/ui/spritesheet_import_dialog.py tests/test_pet_import_page.py tests/test_spritesheet_import_dialog.py && git commit -m "feat: add unified pet import page"`

## Task 11：统一交换中心、托盘入口和安全运行时重载

**文件：**

- 新建 `src/petnest/ui/pet_action_exchange_dialog.py`
- 新建 `tests/test_pet_action_exchange_dialog.py`
- 修改 `src/petnest/ui/tray_icon.py`
- 修改 `tests/test_tray_icon.py`
- 修改 `src/petnest/app.py`
- 修改 `tests/test_app_and_platforms.py`

- [ ] **11.1 写失败测试：统一窗口包含导入宠物、导入动作、导出动作三个入口**

```python
def test_exchange_dialog_has_three_pages(qtbot, app_services):
    dialog = PetActionExchangeDialog(app_services)
    assert dialog.page_names() == ["导入宠物", "导入动作", "导出动作"]
```

窗口记住上次页面；从旧快捷入口打开时直接定位相应页面。

- [ ] **11.2 写失败测试：托盘菜单只提供一个主入口，旧调用仍能路由**

将原“导入精灵图…”和“导入下班动画…”替换为“宠物与动作…”；保留应用内部兼容方法，分别打开导入宠物的精灵图模式和导入动作页面，避免现有调用方立即失效。

- [ ] **11.3 写失败测试：当前宠物安装后重载失败会恢复旧运行状态**

```python
def test_runtime_reload_failure_restores_previous_pet(app, installed_pet):
    app.reload_pet_package = Mock(side_effect=InvalidPackageError())
    app.on_pet_resources_installed(installed_pet)
    assert app.current_pet.identifier == "previous"
    assert app.pet_window.isVisible()
```

非当前宠物只刷新宠物目录，不打断当前动画。当前宠物重载前保存宠物 ID、动作和可见性；失败时恢复；最终保底调用现有“显示宠物”路径，用户也能从托盘“显示”恢复。

- [ ] **11.4 写失败测试：提醒可见时锁定当前宠物安装**

应用层提供唯一锁定判断，不能只靠按钮禁用；即使直接调用安装信号也需拒绝，防止全屏提醒使用中的资源被替换。

- [ ] **11.5 运行并确认失败**

运行：`python -m pytest tests/test_pet_action_exchange_dialog.py tests/test_tray_icon.py tests/test_app_and_platforms.py -q`

预期：统一窗口和新路由不存在。

- [ ] **11.6 实现窗口、路由和重载边界**

窗口只负责编排三个页面；应用层持有宠物目录刷新、当前宠物重载和提醒锁定逻辑。所有成功/失败提示都包含目标宠物与动作数量，错误信息可复制。

- [ ] **11.7 运行测试并提交**

运行：`python -m pytest tests/test_pet_action_exchange_dialog.py tests/test_tray_icon.py tests/test_app_and_platforms.py tests/test_work_finish_reminder.py -q`

预期：全部通过。

提交：`git add src/petnest/ui/pet_action_exchange_dialog.py src/petnest/ui/tray_icon.py src/petnest/app.py tests/test_pet_action_exchange_dialog.py tests/test_tray_icon.py tests/test_app_and_platforms.py && git commit -m "feat: integrate pet and action exchange center"`

## Task 12：端到端验收、用户说明和单提交合入

**文件：**

- 新建 `tests/test_pet_action_exchange_flow.py`
- 修改 `README.md`

- [ ] **12.1 写端到端失败测试：导出、改名导入、重载后可播放**

```python
def test_export_import_and_reload_flow(tmp_path, source_pet, target_pet, app):
    archive = export_action_pack(source_pet, ["walk", "lie"], tmp_path / "share.zip")
    install_actions(target_pet, load_action_pack(archive), decisions={"walk": rename("friend_walk")})
    loaded = PackageLoader(target_pet.parent).load(target_pet.name)
    assert "friend_walk" in loaded.animations
```

再覆盖完整宠物 ZIP 更新、保留本地动作、旧版下班包导入、绑定默认不导入、无效 ZIP 不留半成品、备份可重新导入。

- [ ] **12.2 运行端到端测试并修复最小问题**

运行：`python -m pytest tests/test_pet_action_exchange_flow.py -q`

预期：先因尚未串起服务而失败，修复后通过。

- [ ] **12.3 更新 README 用户说明**

说明以下内容：

- “宠物与动作…”入口在哪里；
- 完整宠物文件夹或 ZIP 可直接导入，外层文件夹/ZIP 名称无要求；
- 不要求普通用户手写 JSON；
- 从完整宠物中可只选择部分动作导入；
- 动作分享通过页面多选、预览并自动生成 ZIP；
- 精灵图导入仍可调整帧数、行列和 FPS；
- 更新同 ID 宠物会先备份，默认完整替换，可选择保留本地独有动作；
- 动作冲突的替换、重命名、跳过含义；
- 旧版下班动画包仍可导入。

- [ ] **12.4 运行静态与完整测试**

运行：

```powershell
python -m compileall -q src
python -m pytest -q
git diff --check
```

预期：三个命令退出码均为 0；没有空白错误、失败或跳过新增关键测试。

- [ ] **12.5 Windows 手工验收**

在测试宠物副本上逐项确认：

1. 托盘打开交换中心，三个页面可切换。
2. 导出普通动作和全屏动作，预览速度与动画时长编辑器一致。
3. 把生成 ZIP 导入另一宠物，分别验证替换、重命名、跳过。
4. 导入一个完整宠物文件夹和同内容 ZIP，外层名称不同也成功。
5. 更新当前宠物和非当前宠物；确认备份产生，重载后宠物可见。
6. 下班全屏提醒显示时，当前宠物安装被阻止；关闭提醒后可安装。
7. 从精灵图创建宠物，确认帧数调整功能仍在。
8. 导入旧版下班动画包，并用下班倒计时触发验证进入和躺下动作。
9. 模拟损坏资源，确认安装失败且原宠物仍可正常显示；托盘“显示”仍可恢复可见性。

- [ ] **12.6 提交文档与端到端测试**

提交：`git add tests/test_pet_action_exchange_flow.py README.md && git commit -m "test: verify pet and action exchange workflows"`

- [ ] **12.7 在功能分支做最终复核**

运行：

```powershell
git status --short
git log --oneline origin/main..HEAD
python -m pytest -q
```

预期：工作区干净；过程提交只存在于 `codex/pet-action-exchange-center`；全量测试通过。

- [ ] **12.8 基于最新主分支压缩合入**

先取得用户确认并在主工作区执行：

```powershell
git fetch origin
git switch main
git pull --ff-only origin main
git merge --squash codex/pet-action-exchange-center
python -m pytest -q
git commit -m "feat: add pet and action exchange center"
git push origin main
```

如果本地主分支仍使用历史名称但跟踪 `origin/main`，先核对分支和 upstream，再按仓库真实状态操作；不得再次创建或推送 `petnest-phase1` 远端分支。只有测试通过后才提交、推送。最终 `main` 相对合入前只新增一个功能提交，内容与功能分支一致。

## 完成标准

- 普通用户无需制作特定目录结构或手写 JSON，就能从 UI 导出可分享动作 ZIP。
- 完整宠物文件夹/ZIP、动作分享包、旧版下班包、精灵图均从同一入口导入。
- 动作列表覆盖宠物的所有动画类型，支持预览、多选和逐项冲突决定。
- 帧数/FPS/逐帧时长沿用现有能力，不产生第二套时间配置。
- 更新有备份，任何失败不留下半安装状态；当前宠物重载失败可恢复并可由托盘“显示”保底。
- 下班提醒期间不会替换正在播放的当前宠物资源。
- 全量自动测试、Windows 手工验收、`git diff --check` 均通过。
- 主分支最终只有一个该功能的新增提交。
