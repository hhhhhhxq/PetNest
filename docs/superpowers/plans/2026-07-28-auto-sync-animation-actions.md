# 自动同步动作资源实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 用户将 PNG 帧放入 `animations/<动作名>/` 后，点击“重新加载当前宠物”即可自动登记并播放该动作。

**架构：** 新增核心同步器，负责发现、默认定义、校验及原子写入。`PetNest.reload_current_pet` 调用它，再按原有路径加载包、应用时长覆盖并通过托盘反馈。

**技术栈：** Python 3.12、标准库 `json`/`tempfile`/`os.replace`、既有 `PackageValidator`、PySide6、pytest、pytest-qt。

---

## 文件结构

- 新建：`src/petnest/core/animation_action_synchronizer.py` — 动作目录发现、配置生成、原子写入。
- 修改：`src/petnest/core/__init__.py` — 导出同步器 API。
- 修改：`src/petnest/app.py` — 重载时同步并反馈。
- 新建：`tests/test_animation_action_synchronizer.py` — 核心同步测试。
- 修改：`tests/test_app_and_platforms.py` — 应用重载集成测试。

### 任务 1：定义同步器测试

**文件：**
- 创建：`tests/test_animation_action_synchronizer.py`

- [ ] **步骤 1：编写未登记 `sleep` 的失败测试**

```python
def test_sync_registers_unconfigured_sleep_directory(tmp_path: Path) -> None:
    root = _write_package(tmp_path / "cat")
    _write_png(root / "animations" / "sleep" / "001.png")
    _write_png(root / "animations" / "sleep" / "002.png")
    result = AnimationActionSynchronizer().sync(root)
    config = json.loads((root / "pet.json").read_text(encoding="utf-8"))
    assert result.added == (SyncedAction("sleep", 2),)
    assert config["animations"]["sleep"] == {"path": "animations/sleep", "fps": 10, "loop": True, "priority": 20}
```

- [ ] **步骤 2：编写 `wake`、已登记与空资源的失败测试**

```python
def test_sync_makes_wake_a_one_shot_context_animation(tmp_path: Path) -> None:
    root = _write_package(tmp_path / "cat")
    _write_png(root / "animations" / "wake" / "001.png")
    AnimationActionSynchronizer().sync(root)
    config = json.loads((root / "pet.json").read_text(encoding="utf-8"))
    assert config["animations"]["wake"] == {"path": "animations/wake", "fps": 10, "loop": False, "priority": 20, "next": "context"}

def test_sync_ignores_registered_empty_and_non_png_directories(tmp_path: Path) -> None:
    root = _write_package(tmp_path / "cat")
    (root / "animations" / "empty").mkdir()
    (root / "animations" / "notes").mkdir()
    (root / "animations" / "notes" / "readme.txt").write_text("x", encoding="utf-8")
    assert AnimationActionSynchronizer().sync(root).added == ()
```

- [ ] **步骤 3：编写候选校验失败不改原文件的测试**

```python
def test_sync_keeps_original_configuration_when_candidate_is_invalid(tmp_path: Path) -> None:
    root = _write_package(tmp_path / "cat")
    _write_png(root / "animations" / "sleep" / "001.png", width=99, height=16)
    original = (root / "pet.json").read_text(encoding="utf-8")
    with pytest.raises(AnimationActionSyncError, match="画布尺寸"):
        AnimationActionSynchronizer().sync(root)
    assert (root / "pet.json").read_text(encoding="utf-8") == original
```

- [ ] **步骤 4：运行失败测试**

运行：`python -m pytest tests/test_animation_action_synchronizer.py -q`

预期：FAIL，提示缺少 `petnest.core.animation_action_synchronizer`。

### 任务 2：实现核心同步器

**文件：**
- 创建：`src/petnest/core/animation_action_synchronizer.py`
- 修改：`src/petnest/core/__init__.py`
- 测试：`tests/test_animation_action_synchronizer.py`

- [ ] **步骤 1：实现结果类型和默认动作定义**

```python
@dataclass(frozen=True, slots=True)
class SyncedAction:
    name: str
    frame_count: int

def _default_definition(action: str) -> dict[str, object]:
    item: dict[str, object] = {"path": f"animations/{action}", "fps": 10, "loop": action != "wake", "priority": 20}
    if action == "wake":
        item["next"] = "context"
    return item
```

`sync(package_root)` 只扫描 `animations/` 直接子目录，按不区分大小写名称排序，只接受含直接 `.png` 文件且未在 `animations` 中声明的目录。

- [ ] **步骤 2：实现校验后原子替换**

```python
candidate = {**config, "animations": {**animations, **new_definitions}}
validation = self._validator.validate(candidate_root)
if not validation.is_valid:
    raise AnimationActionSyncError("；".join(validation.errors))
os.replace(temporary_config, config_path)
```

临时包目录为校验器提供原始资源和候选 `pet.json`。读取、校验、写入或替换失败都删除临时文件并抛出 `AnimationActionSyncError`；原配置保持不变。没有候选动作时不改写文件。

- [ ] **步骤 3：从 `src/petnest/core/__init__.py` 导出 `AnimationActionSynchronizer`、`AnimationActionSyncError`、`AnimationActionSyncResult` 和 `SyncedAction`。**

- [ ] **步骤 4：运行同步器测试**

运行：`python -m pytest tests/test_animation_action_synchronizer.py -q`

预期：全部 PASS。

- [ ] **步骤 5：提交核心同步器**

运行：`git add src/petnest/core/animation_action_synchronizer.py src/petnest/core/__init__.py tests/test_animation_action_synchronizer.py; git commit -m "feat: auto-register animation directories on reload"`

预期：创建只含核心同步器和测试的提交。

### 任务 3：接入重载与托盘反馈

**文件：**
- 修改：`src/petnest/app.py`
- 修改：`tests/test_app_and_platforms.py`

- [ ] **步骤 1：编写应用重载的失败测试**

```python
def test_reloading_current_pet_registers_actions_and_reports_them(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    application = _application_with_sample_pet(qtbot, tmp_path, enable_tray=True)
    _write_png(tmp_path / "pets" / "sample_pet" / "animations" / "sleep" / "001.png")
    messages: list[str] = []
    application.tray.showMessage = lambda _title, text: messages.append(text)  # type: ignore[method-assign]
    assert application.reload_current_pet() is True
    assert "sleep" in application.package.animations
    assert messages == ["已自动登记：sleep（1 帧）"]
```

- [ ] **步骤 2：运行失败测试**

运行：`python -m pytest tests/test_app_and_platforms.py::test_reloading_current_pet_registers_actions_and_reports_them -q`

预期：FAIL，因为当前重载没有同步目录或反馈。

- [ ] **步骤 3：调用同步器并显示结果**

```python
sync_result = self.action_synchronizer.sync(previous.root)
reloaded = self._apply_animation_overrides(self.loader.load(previous.root))
details = "、".join(f"{item.name}（{item.frame_count} 帧）" for item in sync_result.added)
self.tray.showMessage("PetNest", f"已自动登记：{details}")
```

同步或加载失败时复用现有异常保护，不能替换窗口或 `self.package` 的旧包。空目录与非 PNG 目录不提示。

- [ ] **步骤 4：运行应用测试**

运行：`python -m pytest tests/test_app_and_platforms.py -q`

预期：全部 PASS。

- [ ] **步骤 5：提交应用集成**

运行：`git add src/petnest/app.py tests/test_app_and_platforms.py; git commit -m "feat: report synchronized pet actions"`

预期：创建应用集成提交。

### 任务 4：全量验证与本地睡眠资源回归

**文件：**
- 测试：`tests/test_animation_action_synchronizer.py`
- 测试：`tests/test_app_and_platforms.py`

- [ ] **步骤 1：运行全量验证**

运行：`python -m compileall -q src tools; python -m pytest -q; git diff --check`

预期：编译成功、全部测试 PASS、`git diff --check` 无输出。

- [ ] **步骤 2：只读核验当前用户资源**

运行：`python -c "from pathlib import Path; print(len(list(Path('pets/dundunmaoqiu2/animations/sleep').glob('*.png'))))"`

预期：输出 `6`。不要将 `pets/dundunmaoqiu2/` 纳入 Git；实际点击重载后才更新该宠物的本地配置。
