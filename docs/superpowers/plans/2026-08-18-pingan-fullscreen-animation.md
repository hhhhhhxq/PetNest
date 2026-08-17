# 平安全屏动画实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans` 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 为 PetNest 增加可随动作分享 ZIP 导入的全屏入场方向配置，并从指定 MP4 生成体积受控、透明且可实际播放的“平安全屏动画”动作包。

**架构：** 在 `AnimationDefinition` 中保存经过校验的 `entrance_direction`，动作包沿用现有原始定义透传机制；`WorkFinishAnimationWindow` 仅在全屏走路阶段按该字段计算画布横向轨迹，旧资源默认保持右侧入场。独立的视频构建脚本负责抽帧、主体 matte、主体稳定、RGBA PNG 优化、标准动作 ZIP 和关键帧 QA 图，不向运行时加入视频处理依赖。

**技术栈：** Python 3.12、PySide6、Pillow、现有 PetNest action-pack/validator、可选的本地 OpenCV（仅素材构建工具）、pytest/pytest-qt。

---

## 文件结构与职责

将创建或修改的文件：

- 修改 `src/petnest/models/pet_package.py`：为类型化动作定义增加 `entrance_direction` 默认值。
- 修改 `src/petnest/core/package_validator.py`：校验方向字段的作用域和值。
- 修改 `src/petnest/core/package_loader.py`：把已校验字段加载进 `AnimationDefinition`。
- 修改 `src/petnest/core/action_pack.py`：校验标准动作 ZIP 中的方向字段。
- 修改 `src/petnest/ui/work_finish_reminder.py`：按左/右/无入场方向计算全屏画布位置。
- 创建/修改 `tests/test_package_validator.py`、`tests/test_package_loader.py`：覆盖配置校验和模型加载。
- 修改 `tests/test_action_pack.py`、`tests/test_action_transfer.py`：覆盖动作包字段保留、合法值和非法值。
- 修改 `tests/test_work_finish_reminder.py`：覆盖三个方向和旧默认行为。
- 创建 `tools/build_pingan_fullscreen.py`：只负责从 MP4 构建素材 ZIP 与关键帧总览图。
- 创建 `tests/test_build_pingan_fullscreen.py`：覆盖构建脚本中不依赖真实视频的时间线、尺寸和 manifest 纯函数。
- 生成但不作为源代码维护的交付物：`artifacts/平安全屏动画.zip`、`artifacts/平安全屏动画-contact-sheet.png`。

不修改普通桌宠窗口、事件绑定、运行时依赖清单或现有旧版 `manifest.json` 下班包格式。

### 任务 1：增加并校验全屏入场方向字段

**文件：**
- 修改：`src/petnest/models/pet_package.py` 的 `AnimationDefinition`。
- 修改：`src/petnest/core/package_validator.py` 的动画校验逻辑。
- 修改：`src/petnest/core/package_loader.py` 的 `_build_package`。
- 测试：`tests/test_package_validator.py`、`tests/test_package_loader.py`。

- [ ] **步骤 1：编写失败测试，锁定字段和值域。**

在 `tests/test_package_validator.py` 增加：

```python
def test_fullscreen_animation_accepts_entrance_direction(tmp_path: Path) -> None:
    root = _write_package(tmp_path / "direction")
    config_path = root / "pet.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["animations"]["work_finish_walk"] = {
        "path": "animations/work_finish_walk",
        "scope": "fullscreen",
        "canvas": {"width": 24, "height": 18},
        "fps": 10,
        "loop": True,
        "entrance_direction": "left",
    }
    config_path.write_text(json.dumps(config), encoding="utf-8")
    _write_png(root / "animations/work_finish_walk/001.png", 24, 18)

    result = PackageValidator().validate(root)

    assert result.is_valid


@pytest.mark.parametrize("direction", ["up", "", 1, None])
def test_animation_rejects_invalid_entrance_direction(tmp_path: Path, direction: object) -> None:
    root = _write_package(tmp_path / "invalid-direction")
    config_path = root / "pet.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["animations"]["idle"]["entrance_direction"] = direction
    config_path.write_text(json.dumps(config), encoding="utf-8")

    result = PackageValidator().validate(root)

    assert not result.is_valid
    assert any("entrance_direction" in error for error in result.errors)


def test_pet_scope_cannot_declare_entrance_direction(tmp_path: Path) -> None:
    root = _write_package(tmp_path / "pet-scope-direction")
    config_path = root / "pet.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["animations"]["idle"]["entrance_direction"] = "left"
    config_path.write_text(json.dumps(config), encoding="utf-8")

    result = PackageValidator().validate(root)

    assert not result.is_valid
    assert any("全屏" in error and "entrance_direction" in error for error in result.errors)
```

在 `tests/test_package_loader.py` 增加：

```python
def test_loader_preserves_fullscreen_entrance_direction(tmp_path: Path) -> None:
    root = _write_package(tmp_path / "loaded-direction")
    config_path = root / "pet.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["animations"]["work_finish_walk"] = {
        "path": "animations/work_finish_walk",
        "scope": "fullscreen",
        "canvas": {"width": 24, "height": 18},
        "fps": 10,
        "loop": True,
        "entrance_direction": "none",
    }
    config_path.write_text(json.dumps(config), encoding="utf-8")
    _write_png(root / "animations/work_finish_walk/001.png", 24, 18)

    package = PackageLoader().load(root)

    assert package.animations["work_finish_walk"].entrance_direction == "none"
    assert package.animations["idle"].entrance_direction == "right"
```

- [ ] **步骤 2：运行定向测试，确认当前实现失败。**

运行：`pytest tests/test_package_validator.py tests/test_package_loader.py -k entrance_direction -q`

预期：FAIL；当前模型没有该属性，且校验器不识别方向字段。

- [ ] **步骤 3：实现最小字段模型和校验。**

在 `AnimationDefinition` 的默认字段末尾加入：

```python
entrance_direction: str = "right"
```

在 `package_validator.py` 增加模块常量并在 `_validate_animation` 中调用：

```python
_ENTRANCE_DIRECTIONS = {"left", "right", "none"}

def _validate_entrance_direction(
    name: str,
    definition: Mapping[str, object],
    result: ValidationResult,
) -> None:
    if "entrance_direction" not in definition:
        return
    direction = definition["entrance_direction"]
    if definition.get("scope", "pet") != "fullscreen":
        result.errors.append(f"动画 {name}：只有全屏动画可以声明 entrance_direction")
    elif not isinstance(direction, str) or direction not in _ENTRANCE_DIRECTIONS:
        result.errors.append(f"动画 {name} 的 entrance_direction 必须是 left、right 或 none")
```

在 `_validate_animation` 确认 `definition` 为映射后调用该函数；在 loader 构造器中加入：

```python
entrance_direction=str(definition.get("entrance_direction", "right")),
```

- [ ] **步骤 4：运行定向测试，确认通过。**

运行：`pytest tests/test_package_validator.py -k entrance_direction tests/test_package_loader.py -k entrance_direction -q`

预期：全部 PASS。

- [ ] **步骤 5：提交字段层变更。**

```bash
git add src/petnest/models/pet_package.py src/petnest/core/package_validator.py src/petnest/core/package_loader.py tests/test_package_validator.py tests/test_package_loader.py
git commit -m "feat: add fullscreen entrance direction"
```

### 任务 2：让标准动作 ZIP 校验并保留方向配置

**文件：**
- 修改：`src/petnest/core/action_pack.py` 的 `_validate_action_definition`。
- 测试：`tests/test_action_pack.py`、`tests/test_action_transfer.py`。

现有 `extract_pet_actions`、`_manifest_for_export` 和 `ActionInstaller` 会复制原始动作定义，因此不另加一套转换格式；只补充边界校验并用 round-trip 测试锁定透传行为。

- [ ] **步骤 1：编写失败测试。**

在 `tests/test_action_pack.py` 增加一个全屏 `walk` 定义，断言 `load_action_pack` 返回的 `definition["entrance_direction"] == "left"`；再构造 `entrance_direction="up"` 的 manifest，断言抛出 `ActionPackError` 且错误包含 `entrance_direction`。

在 `tests/test_action_transfer.py` 的 `write_pet` 中为全屏 `walk` 增加 `entrance_direction: "left"`，并断言 `extract_pet_actions(root)["walk"].definition["entrance_direction"] == "left"`。

- [ ] **步骤 2：运行失败测试。**

运行：`pytest tests/test_action_pack.py tests/test_action_transfer.py -k entrance_direction -q`

预期：非法值目前不会被拒绝，新增断言失败。

- [ ] **步骤 3：实现动作包值域校验。**

在 `_validate_action_definition` 的 `scope` 校验之后加入：

```python
direction = definition.get("entrance_direction")
if direction is not None:
    if scope != "fullscreen":
        raise ActionPackError(f"动作 {name}：只有全屏动作可以声明 entrance_direction")
    if direction not in {"left", "right", "none"}:
        raise ActionPackError(f"动作 {name} 的 entrance_direction 必须是 left、right 或 none")
```

- [ ] **步骤 4：运行动作包测试。**

运行：`pytest tests/test_action_pack.py tests/test_action_transfer.py -q`

预期：全部 PASS，并证明合法字段从宠物包提取、导出、读取后保持不变。

- [ ] **步骤 5：提交动作包变更。**

```bash
git add src/petnest/core/action_pack.py tests/test_action_pack.py tests/test_action_transfer.py
git commit -m "feat: preserve fullscreen entrance direction in action packs"
```

### 任务 3：按方向移动全屏动画窗口

**文件：**
- 修改：`src/petnest/ui/work_finish_reminder.py` 的 `WorkFinishAnimationWindow`。
- 测试：`tests/test_work_finish_reminder.py`。

- [ ] **步骤 1：编写失败测试。**

沿用现有 `test_animation_moves_from_offscreen_right_to_center_and_holds_last_lie_frame`，增加 `replace` 后的 fullscreen walk definition，并新增：

```python
def test_animation_moves_from_offscreen_left_to_center(qtbot, tmp_path: Path) -> None:
    now = [0.0]
    package = _package(tmp_path)
    walk = replace(
        package.animations["idle"],
        name="work_finish_walk",
        scope="fullscreen",
        canvas=Canvas(24, 18),
        entrance_direction="left",
    )
    package = replace(package, animations={**package.animations, "work_finish_walk": walk})
    reminder = WorkFinishReminder(clock=lambda: now[0])
    qtbot.addWidget(reminder.animation_window)
    qtbot.addWidget(reminder.control_window)

    reminder.show_for(package, QRect(0, 0, 1000, 800), datetime.now())
    assert reminder.animation_window.current_frame_rect().right() < 0

    now[0] = 4.0
    reminder.animation_window._refresh_frame()
    rect = reminder.animation_window.current_frame_rect()
    assert abs(rect.center().x() - 500) <= 1
    reminder.hide()


def test_animation_with_none_direction_starts_centered(qtbot, tmp_path: Path) -> None:
    package = _package(tmp_path)
    walk = replace(
        package.animations["idle"],
        name="work_finish_walk",
        scope="fullscreen",
        canvas=Canvas(24, 18),
        entrance_direction="none",
    )
    package = replace(package, animations={**package.animations, "work_finish_walk": walk})
    reminder = WorkFinishReminder()
    qtbot.addWidget(reminder.animation_window)
    qtbot.addWidget(reminder.control_window)

    reminder.show_for(package, QRect(0, 0, 1000, 800), datetime.now())
    rect = reminder.animation_window.current_frame_rect()

    assert abs(rect.center().x() - 500) <= 1
    reminder.hide()
```

- [ ] **步骤 2：运行测试确认旧实现失败。**

运行：`pytest tests/test_work_finish_reminder.py -k "moves_from_offscreen_left or none_direction" -q`

预期：FAIL；当前窗口总是从右侧起点计算。

- [ ] **步骤 3：实现方向读取与坐标计算。**

在窗口初始化中加入 `_entrance_direction = "right"`；`show_for` 从 `animation.walk.entrance_direction` 读取（无 walk 时仍为 `right`）。将坐标计算拆成私有函数：

```python
def _walking_x(self, progress: float) -> int:
    centered_x = (self.width() - self.target_frame_width) // 2
    if self._entrance_direction == "none":
        return centered_x
    start_x = -self.target_frame_width if self._entrance_direction == "left" else self.width()
    return round(start_x + (centered_x - start_x) * progress)
```

`current_frame_rect` 在 walking 阶段调用 `_walking_x(progress)`；非 walking 阶段继续使用 `centered_x`。方向值已经由包校验器保证，窗口保留 `right` 兜底以便直接构造旧测试模型。

- [ ] **步骤 4：运行全屏窗口测试。**

运行：`pytest tests/test_work_finish_reminder.py -q`

预期：全部 PASS，旧右侧行为、左侧行为、居中行为和末帧保持均通过。

- [ ] **步骤 5：提交播放器变更。**

```bash
git add src/petnest/ui/work_finish_reminder.py tests/test_work_finish_reminder.py
git commit -m "feat: support directional fullscreen entrances"
```

### 任务 4：实现视频到动作 ZIP 的构建工具

**文件：**
- 创建：`tools/build_pingan_fullscreen.py`。
- 测试：`tests/test_build_pingan_fullscreen.py`。

- [ ] **步骤 1：先为纯函数写失败测试。**

覆盖以下可独立测试的函数：

```python
def test_sample_timeline_uses_12_fps_and_preserves_duration() -> None:
    indices = sample_indices(frame_count=240, source_fps=24.0, output_fps=12.0)
    assert len(indices) == 120
    assert indices[:3] == [0, 2, 4]
    assert indices[-1] == 238


def test_split_frames_uses_four_second_walk_boundary() -> None:
    walk, lie = split_phase_indices(list(range(120)), fps=12.0, walk_seconds=4.0)
    assert len(walk) == 48
    assert len(lie) == 72


def test_manifest_has_two_fullscreen_actions_and_left_entrance() -> None:
    manifest = build_manifest(name="平安全屏动画", canvas=(960, 540), walk_count=48, lie_count=72)
    assert manifest["animations"]["work_finish_walk"]["entrance_direction"] == "left"
    assert manifest["animations"]["work_finish_lie_down"]["scope"] == "fullscreen"
```

- [ ] **步骤 2：运行纯函数测试确认失败。**

运行：`pytest tests/test_build_pingan_fullscreen.py -q`

预期：FAIL；构建模块尚未存在。

- [ ] **步骤 3：实现可重复的视频处理流水线。**

脚本接受：

```text
python tools/build_pingan_fullscreen.py \
  "D:/downloaded/背景尽量纯色好抠图。猫从画面左侧走到画面中心后面对镜头躺下，.mp4" \
  --output "artifacts/平安全屏动画.zip" \
  --contact-sheet "artifacts/平安全屏动画-contact-sheet.png"
```

实现要点：

1. 用 OpenCV 读取源视频，检查 `1280×720`、24 fps 和至少 4 秒；按 12 fps 采样偶数源帧。
2. 使用固定的少量关键帧 bbox（脚本常量，覆盖左侧行走、中心坐立、躺下和仰卧四个姿态），对相邻帧线性插值；每帧用 `cv2.grabCut` 取得主体 mask，再用开闭运算和距离变换生成稳定软 alpha。关键帧表写在脚本顶部，构建日志打印每段 bbox，便于复现和调整。
3. 将低频、贴近主体底边的地面接触区域作为软阴影候选，只保留与主体 mask 相邻的有限范围并限制最大 alpha；墙面、墙脚线、地砖纹理、反光和孤立连通区域全部清零。
4. 对行走帧按主体 bbox 中心做水平稳定，把主体放到 `960×540` 画布的中心锚点和固定垂直落地点；躺下帧沿用同一画布和落地点，保留姿态变化，不再烘焙水平入场位移。
5. 将约 0–4 秒帧写入 `work_finish_walk`，约 4 秒至首次稳定仰卧帧写入 `work_finish_lie_down`；用 83/84 ms 交替的逐帧时长保持 12 fps 总时长，末尾重复静止帧不写入。
6. 每帧以真正 RGBA PNG 写出并使用 Pillow `optimize=True`；生成临时源宠物目录，调用现有 `export_action_pack` 生成标准 `petnest-action-pack.json` 和 ZIP，确保不引入绑定。
7. 生成透明棋盘格 contact sheet，标注原视频时间戳、动作阶段和 alpha 检查状态；输出日志列出帧数、ZIP 压缩后大小和解包大小，并在超过 60 MB 目标或 128 MB 硬限制时失败。

脚本只依赖当前素材构建环境的 OpenCV、NumPy 和 Pillow；不把这些库加入 PetNest 运行时依赖。缺少 OpenCV 时应明确提示安装 `opencv-python-headless`，而不是生成空 ZIP。

- [ ] **步骤 4：运行纯函数和工具静态测试。**

运行：`pytest tests/test_build_pingan_fullscreen.py -q`

预期：PASS；随后用真实 MP4 运行构建命令，输出 ZIP、contact sheet 和构建统计。

- [ ] **步骤 5：提交处理工具和纯函数测试。**

```bash
git add tools/build_pingan_fullscreen.py tests/test_build_pingan_fullscreen.py
git commit -m "feat: add Pingan fullscreen animation builder"
```

### 任务 5：生成、导入验证并完成素材 QA

**文件：**
- 读取：`artifacts/平安全屏动画.zip`、`artifacts/平安全屏动画-contact-sheet.png`。
- 验证：`tools/validate_pet.py`、现有 action-pack/installer 测试和 PetNest 预览工具。

- [ ] **步骤 1：运行完整自动测试。**

运行：`pytest tests/test_package_validator.py tests/test_package_loader.py tests/test_action_pack.py tests/test_action_transfer.py tests/test_work_finish_reminder.py tests/test_build_pingan_fullscreen.py -q`

预期：全部 PASS。

- [ ] **步骤 2：构建实际 ZIP。**

运行：

```bash
python tools/build_pingan_fullscreen.py "D:/downloaded/背景尽量纯色好抠图。猫从画面左侧走到画面中心后面对镜头躺下，.mp4" --output "artifacts/平安全屏动画.zip" --contact-sheet "artifacts/平安全屏动画-contact-sheet.png"
```

预期：生成两个动作目录、标准清单、contact sheet；日志确认帧尺寸 `960×540`、RGBA、左侧入场字段和 ZIP/解包大小限制。

- [ ] **步骤 3：在临时宠物中验证标准动作导入。**

用现有 `load_action_pack` 检查包名、两个动作、`scope`、`canvas`、`entrance_direction` 和逐帧时长；使用现有动作安装器把 ZIP 安装到临时 `_write_package` 宠物，重新用 `PackageValidator` 和 `PackageLoader` 加载，断言两个动作完整可用且不改变 `idle`。

- [ ] **步骤 4：做透明图和时序人工 QA。**

打开 contact sheet 检查毛边、白边、地砖线、孤立阴影和主体抖动；用 `tools/preview_animation.py` 或 PetNest 交换中心预览两个动作，确认左侧进入、4 秒到中心、躺下连续、末帧停留。

- [ ] **步骤 5：运行全量回归测试并记录最终产物。**

运行：`pytest -q`

预期：现有测试集全部 PASS；最终回复中链接 ZIP 和 contact sheet，并报告实际压缩后大小、帧数、测试命令和任何保留的视觉瑕疵。
