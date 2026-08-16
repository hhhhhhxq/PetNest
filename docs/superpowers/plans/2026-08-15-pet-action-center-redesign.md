# 宠物与动作中心统一流程改版实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 将宠物导入、动作导入、动作时长编辑和动作导出统一到一个无嵌套对话框的四页管理中心，并把旧托盘入口收敛为“宠物与动作…”。

**架构：** 先建立统一页面与底部命令协议，再把精灵图导入和动画时长编辑从现有 `QDialog` 中提取为可复用 `QWidget`；旧对话框只作为兼容外壳。`PetActionExchangeDialog` 负责导航、统一标题和统一底部操作，业务页负责状态与命令；应用层通过带回滚的回调保存动作时长并重载运行时。

**技术栈：** Python 3.12、PySide6、pytest、pytest-qt、Pillow、现有 PetNest 导入器与 `AnimationActionSynchronizer`

---

## 文件结构

### 新建文件

- `src/petnest/ui/exchange_page.py`：统一页面底部状态、主次命令和离开守卫协议。
- `src/petnest/ui/spritesheet_import_content.py`：不拥有顶层窗口的精灵图表单、检测、手动帧选择和导入逻辑。
- `src/petnest/ui/animation_timing_editor.py`：不负责保存文件的动作列表、时间线编辑、草稿和预览组件。
- `src/petnest/ui/animation_editor_page.py`：宠物选择、保存回调、恢复动作和未保存离开守卫。
- `tests/test_exchange_page.py`：统一页面协议测试。
- `tests/test_spritesheet_import_content.py`：精灵图内容组件测试。
- `tests/test_animation_timing_editor.py`：动画编辑内容组件与草稿测试。
- `tests/test_animation_editor_page.py`：编辑页保存、失败保留和离开守卫测试。

### 修改文件

- `src/petnest/ui/spritesheet_import_dialog.py`：改为组合 `SpriteSheetImportContent` 的兼容外壳。
- `src/petnest/ui/pet_import_page.py`：改为单一来源、自动识别、动态配置和确认的三步向导。
- `src/petnest/ui/animation_editor_dialog.py`：改为组合 `AnimationTimingEditor` 的兼容外壳。
- `src/petnest/ui/action_import_page.py`：接入共享底部命令，移除页面内重复底栏，支持刷新宠物列表。
- `src/petnest/ui/action_export_page.py`：接入共享底部命令，移除页面内重复底栏，支持刷新宠物列表。
- `src/petnest/ui/pet_action_exchange_dialog.py`：四页导航、动态标题、统一底部命令和离开守卫。
- `src/petnest/app.py`：传入动作保存回调，保存失败回滚，安装后刷新中心，不再打开独立编辑器。
- `src/petnest/ui/tray_icon.py`：删除三个重复动作及其回调参数，只保留统一入口。
- `tests/test_spritesheet_import_dialog.py`：验证旧对话框复用内容组件且能力不回退。
- `tests/test_pet_import_page.py`：覆盖自动识别、三步状态、草稿和确认前不写盘。
- `tests/test_animation_editor_dialog.py`：验证旧对话框复用编辑组件且旧公开行为可用。
- `tests/test_action_import_page.py`：验证共享主命令与宠物刷新。
- `tests/test_action_export_page.py`：验证共享主命令与宠物刷新。
- `tests/test_pet_action_exchange_dialog.py`：验证四页、统一底栏和导航守卫。
- `tests/test_pet_action_exchange_app.py`：验证中心路由、动作保存回滚和安装后刷新。
- `tests/test_tray_exchange_entry.py`：验证统一入口存在且旧入口消失。
- `tests/test_pet_window.py`：删除旧托盘入口断言，保留宠物库基础管理断言。
- `tests/test_app_and_platforms.py`：将独立动画编辑器集成测试改为中心保存回调测试。

## 任务 1：建立统一页面与底部命令协议

**文件：**
- 创建：`src/petnest/ui/exchange_page.py`
- 创建：`tests/test_exchange_page.py`

- [ ] **步骤 1：编写失败的协议测试**

```python
from petnest.ui.exchange_page import ExchangeFooterState, ExchangePage


def test_exchange_page_publishes_status_and_footer_changes(qtbot: object) -> None:
    page = ExchangePage()
    qtbot.addWidget(page)
    changes: list[ExchangeFooterState] = []
    page.footer_changed.connect(lambda: changes.append(page.footer_state()))

    page.set_footer(
        status="已读取来源",
        primary_text="下一步",
        primary_enabled=True,
        secondary_text="上一步",
    )

    assert changes[-1] == ExchangeFooterState(
        status="已读取来源",
        primary_text="下一步",
        primary_enabled=True,
        secondary_text="上一步",
        secondary_enabled=True,
    )
    assert page.request_leave() is True
```

- [ ] **步骤 2：运行测试确认协议尚不存在**

运行：`python -m pytest tests/test_exchange_page.py -v`

预期：FAIL，报错 `ModuleNotFoundError: No module named 'petnest.ui.exchange_page'`。

- [ ] **步骤 3：实现最小共享协议**

```python
"""宠物与动作中心页面的统一底部命令协议。"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget


@dataclass(frozen=True, slots=True)
class ExchangeFooterState:
    status: str
    primary_text: str
    primary_enabled: bool = True
    secondary_text: str | None = None
    secondary_enabled: bool = True


class ExchangePage(QWidget):
    footer_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._footer_state = ExchangeFooterState("", "继续", False)

    def footer_state(self) -> ExchangeFooterState:
        return self._footer_state

    def set_footer(
        self,
        *,
        status: str,
        primary_text: str,
        primary_enabled: bool = True,
        secondary_text: str | None = None,
        secondary_enabled: bool = True,
    ) -> None:
        self._footer_state = ExchangeFooterState(
            status, primary_text, primary_enabled, secondary_text, secondary_enabled
        )
        self.footer_changed.emit()

    def trigger_primary(self) -> None:
        raise NotImplementedError

    def trigger_secondary(self) -> None:
        return

    def request_leave(self) -> bool:
        return True

    def deactivate(self) -> None:
        return


__all__ = ["ExchangeFooterState", "ExchangePage"]
```

- [ ] **步骤 4：运行协议测试**

运行：`python -m pytest tests/test_exchange_page.py -v`

预期：PASS，1 项通过。

- [ ] **步骤 5：提交共享协议**

```bash
git add src/petnest/ui/exchange_page.py tests/test_exchange_page.py
git commit -m "refactor: add exchange page command contract"
```

## 任务 2：提取可复用精灵图内容组件

**文件：**
- 创建：`src/petnest/ui/spritesheet_import_content.py`
- 创建：`tests/test_spritesheet_import_content.py`
- 修改：`src/petnest/ui/spritesheet_import_dialog.py`
- 修改：`tests/test_spritesheet_import_dialog.py`

- [ ] **步骤 1：编写内容组件与兼容外壳的失败测试**

```python
from pathlib import Path

from petnest.ui.spritesheet_import_content import SpriteSheetImportContent
from petnest.ui.spritesheet_import_dialog import SpriteSheetImportDialog
from tests.test_spritesheet_importer import _spritesheet


def test_content_imports_without_owning_a_dialog(qtbot: object, tmp_path: Path) -> None:
    source = _spritesheet(tmp_path / "cat.png")
    content = SpriteSheetImportContent(tmp_path / "pets", show_source_picker=False)
    qtbot.addWidget(content)
    content.set_source(source)
    content.pet_id_input.setText("content_cat")

    result = content.import_selected()

    assert not content.isWindow()
    assert result is not None
    assert result.package_id == "content_cat"


def test_legacy_dialog_wraps_the_same_content(qtbot: object, tmp_path: Path) -> None:
    dialog = SpriteSheetImportDialog(tmp_path / "pets")
    qtbot.addWidget(dialog)

    assert isinstance(dialog.content, SpriteSheetImportContent)
    assert dialog.source_input is dialog.content.source_input
    assert dialog.manual_selection_panel is dialog.content.manual_selection_panel
```

- [ ] **步骤 2：运行测试确认组件尚不存在**

运行：`python -m pytest tests/test_spritesheet_import_content.py tests/test_spritesheet_import_dialog.py -v`

预期：FAIL，新模块无法导入。

- [ ] **步骤 3：移动现有内容逻辑并定义无窗口 API**

将 `SpriteGridHint`、`SourceDropZone`、触发说明、源文件检查、宠物信息、自动／手动模式、缩略图选择和 `SpriteSheetImporter.import_file` 调用移动到 `SpriteSheetImportContent(QWidget)`。该类不创建标题栏、步骤栏、`QDialogButtonBox`，也不调用 `accept()`、`reject()` 或 `QMessageBox`。

新增的公开入口必须采用以下签名和结果约定：

```python
class SpriteSheetImportContent(QWidget):
    status_changed = Signal(str)
    dirty_changed = Signal(bool)

    def __init__(
        self,
        pets_root: Path,
        *,
        show_source_picker: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._pets_root = Path(pets_root)
        self._show_source_picker = show_source_picker
        self._importer = SpriteSheetImporter()
        self._inspection: SpriteSheetInspection | None = None
        self._selected_columns: dict[str, set[int]] = {}
        self._build_content()

    def set_source(self, source: Path) -> None:
        self.source_input.setText(str(Path(source)))

    def is_dirty(self) -> bool:
        return bool(
            self.source_input.text().strip()
            or self.pet_id_input.text().strip()
            or self.name_input.text().strip()
            or self.manual_select_radio.isChecked()
        )

    def import_selected(self) -> SpriteSheetImportResult | None:
        source_text = self.source_input.text().strip()
        identifier = self.pet_id_input.text().strip()
        if not source_text or not identifier:
            self._set_status("请选择 PNG 文件并填写宠物 ID。")
            return None
        try:
            result = self._importer.import_file(
                Path(source_text),
                self._pets_root,
                identifier,
                name=self.name_input.text().strip() or None,
                selected_columns_by_action=(
                    self._manual_columns() if self.manual_select_radio.isChecked() else None
                ),
            )
        except (OSError, SpriteSheetImportError) as error:
            self._set_status(f"导入失败：{error}")
            return None
        self._set_status(f"导入完成：{result.package_root}")
        return result
```

`show_source_picker=False` 时隐藏源文件卡片，但保留 `source_input` 和检查逻辑供统一向导注入路径；宠物信息、模式与手动帧面板始终保留。

- [ ] **步骤 4：将旧对话框改为兼容外壳**

`SpriteSheetImportDialog` 只创建原窗口标题、步骤提示、统一滚动容器和底部取消／导入按钮，然后嵌入 `SpriteSheetImportContent(show_source_picker=True)`。为当前调用者保留以下别名：

```python
self.content = SpriteSheetImportContent(pets_root, show_source_picker=True, parent=window_shell)
for name in (
    "source_input", "source_dropzone", "rules_label", "pet_id_input", "name_input",
    "auto_skip_radio", "manual_select_radio", "manual_selection_panel", "action_list",
    "thumbnail_area", "content_scroll", "content_container", "initial_content", "status_label",
):
    setattr(self, name, getattr(self.content, name))

def import_selected(self) -> None:
    result = self.content.import_selected()
    if result is None:
        return
    self.imported_result = result
    self.accept()
```

`choose_source`、`_fit_initial_height` 和旧测试依赖的显示行为继续由兼容外壳委托给内容组件。

- [ ] **步骤 5：运行精灵图定向测试**

运行：`python -m pytest tests/test_spritesheet_import_content.py tests/test_spritesheet_import_dialog.py tests/test_spritesheet_importer.py -v`

预期：PASS；原精灵图测试和新组件测试全部通过。

- [ ] **步骤 6：提交内容提取**

```bash
git add src/petnest/ui/spritesheet_import_content.py src/petnest/ui/spritesheet_import_dialog.py tests/test_spritesheet_import_content.py tests/test_spritesheet_import_dialog.py
git commit -m "refactor: extract reusable spritesheet import content"
```

## 任务 3：把导入宠物改成自动识别三步向导

**文件：**
- 修改：`src/petnest/ui/pet_import_page.py`
- 修改：`tests/test_pet_import_page.py`

- [ ] **步骤 1：用三步流程测试替换模式下拉测试**

```python
import json
from pathlib import Path

from petnest.ui.pet_import_page import PetImportPage, PetImportStep
from petnest.ui.spritesheet_import_content import SpriteSheetImportContent
from tests.test_package_validator import _write_package
from tests.test_spritesheet_importer import _spritesheet


def test_pet_import_page_auto_detects_png_and_keeps_one_window(qtbot: object, tmp_path: Path) -> None:
    source = _spritesheet(tmp_path / "cat.png")
    page = PetImportPage([], tmp_path / "pets")
    qtbot.addWidget(page)

    page.load_source(source)

    assert page.current_step() is PetImportStep.CONFIGURE
    assert page.source_kind_label.text() == "PNG 精灵图"
    assert isinstance(page.spritesheet_content, SpriteSheetImportContent)
    assert not page.findChildren(__import__("PySide6").QtWidgets.QDialog)


def test_pet_import_page_does_not_write_before_final_confirmation(qtbot: object, tmp_path: Path) -> None:
    source = _spritesheet(tmp_path / "cat.png")
    pets_root = tmp_path / "pets"
    page = PetImportPage([], pets_root)
    qtbot.addWidget(page)
    page.load_source(source)
    page.spritesheet_content.pet_id_input.setText("wizard_cat")

    page.trigger_primary()

    assert page.current_step() is PetImportStep.REVIEW
    assert not (pets_root / "wizard_cat").exists()
    page.trigger_primary()
    assert (pets_root / "wizard_cat" / "pet.json").is_file()


def test_pet_import_page_auto_detects_complete_pet_folder(qtbot: object, tmp_path: Path) -> None:
    source = _write_package(tmp_path / "source")
    page = PetImportPage([], tmp_path / "pets")
    qtbot.addWidget(page)

    page.load_source(source)

    assert page.current_step() is PetImportStep.CONFIGURE
    assert page.source_kind_label.text() == "完整宠物包"
    assert "test_pet" in page.package_summary_label.text()
```

- [ ] **步骤 2：运行测试确认旧页面流程不符合预期**

运行：`python -m pytest tests/test_pet_import_page.py -v`

预期：FAIL，`PetImportStep`、`spritesheet_content` 和三步命令不存在。

- [ ] **步骤 3：实现步骤状态和单一来源区**

将 `PetImportPage` 改为 `ExchangePage` 子类，删除 `PetImportMode` 和 `mode_combo`。新增：

```python
class PetImportStep(StrEnum):
    SOURCE = "source"
    CONFIGURE = "configure"
    REVIEW = "review"


class PetImportPage(ExchangePage):
    pet_installed = Signal(str, object)

    def current_step(self) -> PetImportStep:
        return self._step

    def trigger_primary(self) -> None:
        if self._step is PetImportStep.SOURCE:
            self._choose_file()
        elif self._step is PetImportStep.CONFIGURE:
            self._prepare_review()
        else:
            self._perform_import()

    def trigger_secondary(self) -> None:
        if self._step is PetImportStep.REVIEW:
            self._set_step(PetImportStep.CONFIGURE)
        elif self._step is PetImportStep.CONFIGURE:
            self._set_step(PetImportStep.SOURCE)
```

第一步的 `ImportSourceDropZone` 接受一个本地 PNG、ZIP 或文件夹；“选择文件”使用 PNG/ZIP 过滤器，“选择文件夹”使用 `getExistingDirectory`。`load_source(Path)` 保持为测试和程序化入口。

- [ ] **步骤 4：实现识别、动态配置和确认摘要**

识别规则必须集中在一个方法：

```python
def _inspect_source(self, source: Path) -> None:
    path = Path(source).expanduser()
    if path.is_file() and path.suffix.casefold() == ".png":
        self._source_kind = SourceKind.SPRITESHEET
        self.spritesheet_content.set_source(path)
        self.configure_stack.setCurrentWidget(self.spritesheet_content)
        self.source_kind_label.setText("PNG 精灵图")
        self._set_step(PetImportStep.CONFIGURE)
        return
    with ExchangeSource.open(path) as materialized:
        kind = detect_source_kind(materialized.root)
        if kind is not SourceKind.PET_PACKAGE:
            raise PetPackageImportError("此来源不是完整宠物包；动作包请使用“导入动作”。")
        config = json.loads((materialized.root / "pet.json").read_text(encoding="utf-8"))
        validation = PackageValidator().validate(materialized.root)
        if not validation.is_valid:
            raise PetPackageImportError("宠物包校验失败：" + "；".join(validation.errors))
        self._package_metadata = _package_metadata(config)
    self._source_kind = SourceKind.PET_PACKAGE
    self.configure_stack.setCurrentWidget(self.package_options)
    self.source_kind_label.setText("完整宠物包")
    self._set_step(PetImportStep.CONFIGURE)
```

`_prepare_review()` 只生成只读摘要并进入 `REVIEW`，不得调用导入器。`_perform_import()` 在 PNG 路径调用 `spritesheet_content.import_selected()`，在包路径调用现有 `import_pet_package()`，成功后发出 `pet_installed`。

- [ ] **步骤 5：实现来源草稿守卫和底部状态**

`replace_source(source)` 在 `CONFIGURE` 或 `REVIEW` 且表单有内容时使用 `QMessageBox.question`；选择 No 保持当前来源和步骤，选择 Yes 后清理本来源元数据、精灵图表单和确认摘要。每次 `_set_step` 通过 `set_footer` 发布：

```python
states = {
    PetImportStep.SOURCE: ("支持 PNG、ZIP 和文件夹", "选择来源", None),
    PetImportStep.CONFIGURE: ("设置会保留，返回不会丢失", "下一步", "上一步"),
    PetImportStep.REVIEW: ("确认前不会写入宠物目录", "开始导入", "上一步"),
}
```

- [ ] **步骤 6：运行宠物导入回归**

运行：`python -m pytest tests/test_pet_import_page.py tests/test_pet_package_importer.py tests/test_spritesheet_import_content.py tests/test_spritesheet_importer.py -v`

预期：PASS；PNG、ZIP、文件夹和确认前不写盘均通过。

- [ ] **步骤 7：提交三步向导**

```bash
git add src/petnest/ui/pet_import_page.py tests/test_pet_import_page.py
git commit -m "feat: unify pet import into auto-detected wizard"
```

## 任务 4：提取动作时间编辑组件并保留旧对话框

**文件：**
- 创建：`src/petnest/ui/animation_timing_editor.py`
- 创建：`tests/test_animation_timing_editor.py`
- 修改：`src/petnest/ui/animation_editor_dialog.py`
- 修改：`tests/test_animation_editor_dialog.py`

- [ ] **步骤 1：编写草稿、恢复和兼容外壳的失败测试**

```python
from pathlib import Path

from petnest.ui.animation_editor_dialog import AnimationEditorDialog
from petnest.ui.animation_timing_editor import AnimationTimingEditor
from tests.test_pet_window import _package


def test_timing_editor_tracks_and_restores_only_current_action(qtbot: object, tmp_path: Path) -> None:
    editor = AnimationTimingEditor(_package(tmp_path))
    qtbot.addWidget(editor)
    editor.action_table.selectRow(0)
    original = editor.total_duration_spin.value()
    editor.total_duration_spin.setValue(original + 100)

    assert editor.is_dirty()
    assert "idle" in editor.updated_frame_durations()
    editor.restore_current_action()
    assert not editor.is_dirty()
    assert editor.total_duration_spin.value() == original


def test_legacy_animation_dialog_wraps_timing_editor(qtbot: object, tmp_path: Path) -> None:
    dialog = AnimationEditorDialog(_package(tmp_path))
    qtbot.addWidget(dialog)

    assert isinstance(dialog.editor, AnimationTimingEditor)
    assert dialog.action_table is dialog.editor.action_table
    assert dialog.updated_frame_durations() == dialog.editor.updated_frame_durations()
```

- [ ] **步骤 2：运行测试确认组件尚不存在**

运行：`python -m pytest tests/test_animation_timing_editor.py tests/test_animation_editor_dialog.py -v`

预期：FAIL，新模块无法导入。

- [ ] **步骤 3：把现有编辑主体移动到 `AnimationTimingEditor`**

移动动作表、总时长／逐帧模式、时间线、逐帧列表、棋盘格预览和预览计时器。内容组件继承 `QWidget`，不创建窗口标题、`QDialogButtonBox` 或保存文件操作。保留现有 `_source_durations`、`_scaled_timeline` 和 `_mode_label` 行为。

新增草稿基线和生命周期 API：

```python
class AnimationTimingEditor(QWidget):
    dirty_changed = Signal(bool)

    def __init__(self, package: PetPackage, parent: QWidget | None = None) -> None:
        self._package = package
        self._initial_timelines = {
            name: _source_durations(definition)
            for name, definition in package.animations.items()
        }
        self._timelines = dict(self._initial_timelines)
        self._changed_actions: set[str] = set()
        # 构建现有三栏控件并选择第一项

    def is_dirty(self) -> bool:
        return bool(self._changed_actions)

    def updated_frame_durations(self) -> dict[str, tuple[int, ...]]:
        return {name: self._timelines[name] for name in self._changed_actions}

    def restore_current_action(self) -> None:
        if self._current_action is None:
            return
        action = self._current_action
        self._timelines[action] = self._initial_timelines[action]
        self._modes[action] = "per_frame" if self._package.animations[action].frame_durations_ms else "total"
        self._changed_actions.discard(action)
        self._load_selected_action()
        self._emit_dirty_changed()

    def mark_saved(self, package: PetPackage) -> None:
        self._package = package
        self._initial_timelines = dict(self._timelines)
        self._changed_actions.clear()
        self._emit_dirty_changed()

    def stop_preview(self) -> None:
        self.preview_timer.stop()
```

所有改变 `_changed_actions` 的路径在更新后调用 `_emit_dirty_changed()`。

- [ ] **步骤 4：把旧对话框缩减为兼容外壳**

`AnimationEditorDialog` 仅创建标题、嵌入 `AnimationTimingEditor` 和取消／保存按钮。为现有测试和调用者转发以下属性：

```python
self.editor = AnimationTimingEditor(package, window_shell)
for name in (
    "action_table", "action_card", "editor_card", "preview_card", "frame_list",
    "duration_table", "total_radio", "per_frame_radio", "total_duration_spin",
    "total_timeline", "mode_status_label", "editor_heading_label",
    "editor_description_label", "preview_label", "preview_timer",
    "preview_play_button", "preview_frame_index",
):
    setattr(self, name, getattr(self.editor, name))

def updated_frame_durations(self) -> dict[str, tuple[int, ...]]:
    return self.editor.updated_frame_durations()

def closeEvent(self, event: QCloseEvent) -> None:
    self.editor.stop_preview()
    super().closeEvent(event)
```

需要写入后变化的 `preview_frame_index` 不做一次性整数别名，改为只读属性委托，确保预览推进测试读取实时值。

- [ ] **步骤 5：运行动画编辑定向测试**

运行：`python -m pytest tests/test_animation_timing_editor.py tests/test_animation_editor_dialog.py tests/test_animation_preview_widget.py -v`

预期：PASS；旧编辑器行为、预览计时和新草稿恢复全部通过。

- [ ] **步骤 6：提交动画编辑组件提取**

```bash
git add src/petnest/ui/animation_timing_editor.py src/petnest/ui/animation_editor_dialog.py tests/test_animation_timing_editor.py tests/test_animation_editor_dialog.py
git commit -m "refactor: extract reusable animation timing editor"
```

## 任务 5：实现统一中心内的编辑动作页面

**文件：**
- 创建：`src/petnest/ui/animation_editor_page.py`
- 创建：`tests/test_animation_editor_page.py`

- [ ] **步骤 1：编写保存、失败保留和恢复测试**

```python
from pathlib import Path

from petnest.ui.animation_editor_page import AnimationEditorPage, AnimationSaveResult
from tests.test_pet_window import _package


def test_editor_page_saves_through_callback_and_clears_dirty_state(qtbot: object, tmp_path: Path) -> None:
    package = _package(tmp_path)
    calls: list[tuple[str, dict[str, tuple[int, ...]]]] = []

    def save(selected: object, timelines: dict[str, tuple[int, ...]]) -> AnimationSaveResult:
        calls.append((selected.identifier, timelines))
        return AnimationSaveResult(True, "已保存并重载", selected)

    page = AnimationEditorPage([package], current_pet_id=package.identifier, save_timelines=save)
    qtbot.addWidget(page)
    page.editor.total_duration_spin.setValue(100)
    page.trigger_primary()

    assert calls == [(package.identifier, {"idle": (50, 50)})]
    assert not page.editor.is_dirty()
    assert page.footer_state().status == "已保存并重载"


def test_editor_page_keeps_draft_when_save_fails(qtbot: object, tmp_path: Path) -> None:
    package = _package(tmp_path)
    page = AnimationEditorPage(
        [package],
        current_pet_id=package.identifier,
        save_timelines=lambda *_: AnimationSaveResult(False, "访问被拒绝"),
    )
    qtbot.addWidget(page)
    page.editor.total_duration_spin.setValue(100)

    page.trigger_primary()

    assert page.editor.is_dirty()
    assert page.editor.updated_frame_durations()["idle"] == (50, 50)
    assert page.footer_state().status == "访问被拒绝"


def test_editor_page_secondary_command_restores_only_current_action(qtbot: object, tmp_path: Path) -> None:
    package = _package(tmp_path)
    page = AnimationEditorPage([package], current_pet_id=package.identifier, save_timelines=lambda *_: None)
    qtbot.addWidget(page)
    page.editor.total_duration_spin.setValue(100)

    page.trigger_secondary()

    assert not page.editor.is_dirty()
    assert page.editor.total_duration_spin.value() == 200
```

- [ ] **步骤 2：运行测试确认编辑页尚不存在**

运行：`python -m pytest tests/test_animation_editor_page.py -v`

预期：FAIL，新模块无法导入。

- [ ] **步骤 3：实现保存结果与页面主体**

```python
@dataclass(frozen=True, slots=True)
class AnimationSaveResult:
    success: bool
    message: str
    package: PetPackage | None = None


class AnimationEditorPage(ExchangePage):
    def __init__(
        self,
        packages: Sequence[PetPackage],
        *,
        current_pet_id: str,
        save_timelines: Callable[[PetPackage, dict[str, tuple[int, ...]]], AnimationSaveResult],
        is_pet_locked: Callable[[str], bool] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._packages = tuple(packages)
        self._save_timelines = save_timelines
        self._is_pet_locked = is_pet_locked or (lambda _identifier: False)
        self.pet_combo = QComboBox(self)
        self.editor_stack = QStackedWidget(self)
        self.editor = AnimationTimingEditor(self._selected_package(), self.editor_stack)
        self.editor.dirty_changed.connect(self._sync_footer)
        self.set_current_pet(current_pet_id)

    def trigger_primary(self) -> None:
        package = self.current_package()
        if package is None or not self.editor.is_dirty():
            return
        if self._is_pet_locked(package.identifier):
            self.set_footer(status="下班提醒显示中，请先结束提醒。", primary_text="保存并重载", primary_enabled=True, secondary_text="恢复当前动作")
            return
        result = self._save_timelines(package, self.editor.updated_frame_durations())
        if result.success and result.package is not None:
            self.editor.mark_saved(result.package)
        self._sync_footer(result.message)

    def trigger_secondary(self) -> None:
        self.editor.restore_current_action()
        self._sync_footer()
```

页面布局使用顶部宠物选择器和 `AnimationTimingEditor` 三栏主体，不创建窗口外壳或自己的底部按钮。

- [ ] **步骤 4：实现未保存离开守卫和宠物刷新**

`request_leave()` 使用一个 `QMessageBox`，明确提供保存、放弃、取消：保存调用 `trigger_primary()` 且仅在脏状态清除后返回 True；放弃返回 True；取消返回 False。`deactivate()` 调用 `editor.stop_preview()`。

`refresh_packages(packages, current_pet_id)` 按 ID 重建宠物选择器，保留仍存在的当前选择；若当前有草稿，必须先通过 `request_leave()`。切换宠物采用同一守卫。

- [ ] **步骤 5：运行编辑页测试**

运行：`python -m pytest tests/test_animation_editor_page.py tests/test_animation_timing_editor.py -v`

预期：PASS；成功清草稿、失败保草稿、恢复当前动作和离开守卫全部通过。

- [ ] **步骤 6：提交编辑动作页面**

```bash
git add src/petnest/ui/animation_editor_page.py tests/test_animation_editor_page.py
git commit -m "feat: add animation editor page to exchange center"
```

## 任务 6：集成四页导航和真正统一的底部操作区

**文件：**
- 修改：`src/petnest/ui/action_import_page.py`
- 修改：`src/petnest/ui/action_export_page.py`
- 修改：`src/petnest/ui/pet_action_exchange_dialog.py`
- 修改：`tests/test_action_import_page.py`
- 修改：`tests/test_action_export_page.py`
- 修改：`tests/test_pet_action_exchange_dialog.py`

- [ ] **步骤 1：编写四页与统一底栏失败测试**

```python
from petnest.ui.animation_editor_page import AnimationSaveResult
from petnest.ui.pet_action_exchange_dialog import PetActionExchangeDialog


def test_exchange_dialog_has_four_pages_and_one_footer(qtbot: object, tmp_path: Path) -> None:
    package = PackageLoader().load(_write_package(tmp_path / "pet"))
    dialog = PetActionExchangeDialog(
        [package],
        tmp_path / "pets",
        current_pet_id=package.identifier,
        save_animation_timelines=lambda selected, _: AnimationSaveResult(True, "已保存", selected),
    )
    qtbot.addWidget(dialog)

    assert dialog.page_names() == ["导入宠物", "导入动作", "编辑动作", "导出动作"]
    assert dialog.findChildren(__import__("PySide6").QtWidgets.QDialogButtonBox) == []
    assert dialog.primary_button.parentWidget() is dialog.window_shell
    assert dialog.secondary_button.parentWidget() is dialog.window_shell


def test_exchange_dialog_routes_footer_command_to_active_page(qtbot: object, tmp_path: Path, monkeypatch: object) -> None:
    package = PackageLoader().load(_write_package(tmp_path / "pet"))
    dialog = _dialog(package, tmp_path)
    qtbot.addWidget(dialog)
    calls: list[bool] = []
    monkeypatch.setattr(dialog.action_export_page, "trigger_primary", lambda: calls.append(True))

    dialog.select_page("导出动作")
    dialog.primary_button.click()

    assert calls == [True]
```

- [ ] **步骤 2：运行测试确认当前只有三页且底栏重复**

运行：`python -m pytest tests/test_pet_action_exchange_dialog.py tests/test_action_import_page.py tests/test_action_export_page.py -v`

预期：FAIL，页面列表仍缺少“编辑动作”，且页面尚未实现共享命令。

- [ ] **步骤 3：让动作导入和导出页接入 `ExchangePage`**

`ActionImportPage`：

```python
class ActionImportPage(ExchangePage):
    def trigger_primary(self) -> None:
        self.install_selected()

    def _sync_footer(self, status: str | None = None) -> None:
        self.set_footer(
            status=status or "导入完整宠物时可只选择其中部分动作。",
            primary_text="安装选中动作",
            primary_enabled=bool(self.selected_action_names()) and self._target_package() is not None,
        )

    def deactivate(self) -> None:
        return
```

删除页面内 `install_button` 和底部布局；原来写 `status_label.setText` 的位置改为 `_sync_footer(message)`。保留一个隐藏的 `status_label` 兼容属性，并在 `_sync_footer` 同步文本，直至旧测试迁移完成。

`ActionExportPage` 同样实现 `trigger_primary()` 调用 `_choose_output()`，用 `_sync_footer()` 发布“已选 N 项”和 `primary_enabled`，`deactivate()` 停止 `preview`。删除页面内 `export_button` 和重复状态栏。

两页都新增 `refresh_packages(packages, current_pet_id)`，按 ID 重建组合框并刷新内容。

- [ ] **步骤 4：重建统一窗口外壳**

`PetActionExchangeDialog` 构造函数新增：

```python
def __init__(
    self,
    packages: Sequence[PetPackage],
    pets_root: Path,
    *,
    current_pet_id: str,
    save_animation_timelines: Callable[[PetPackage, dict[str, tuple[int, ...]]], AnimationSaveResult],
    is_pet_locked: Callable[[str], bool] | None = None,
    parent: QWidget | None = None,
) -> None:
```

按顺序创建四页，并只在 `window_shell` 底部创建：`footer_status_label`、`secondary_button`、`primary_button`。`_sync_footer()` 从当前 `ExchangePage.footer_state()` 同步文案、可见性和 enabled 状态。

导航切换必须先执行：

```python
def _select_row(self, row: int) -> None:
    current = self.current_page()
    if current is not None and row != self.stack.currentIndex() and not current.request_leave():
        with QSignalBlocker(self.navigation):
            self.navigation.setCurrentRow(self.stack.currentIndex())
        return
    if current is not None:
        current.deactivate()
    self.stack.setCurrentIndex(row)
    self.page_title.setText(self._page_labels[row])
    self.page_subtitle.setText(self._page_subtitles[row])
    self._sync_footer()
```

`closeEvent` 和 `reject` 也调用当前页 `request_leave()`；拒绝时忽略事件并保持窗口。

- [ ] **步骤 5：实现统一刷新与资源释放**

新增 `refresh_packages(packages, current_pet_id)`，依次调用四个页面的同名方法；宠物导入页只更新“是否为更新”的识别依据，动作导入、编辑和导出页更新宠物选择器。关闭窗口时调用所有页 `deactivate()`，动作导入页额外关闭持有的临时 `ActionPack`。

- [ ] **步骤 6：运行统一中心测试**

运行：`python -m pytest tests/test_pet_action_exchange_dialog.py tests/test_pet_import_page.py tests/test_action_import_page.py tests/test_animation_editor_page.py tests/test_action_export_page.py -v`

预期：PASS；四页顺序、底部路由、刷新和离开守卫通过。

- [ ] **步骤 7：提交统一窗口集成**

```bash
git add src/petnest/ui/action_import_page.py src/petnest/ui/action_export_page.py src/petnest/ui/pet_action_exchange_dialog.py tests/test_action_import_page.py tests/test_action_export_page.py tests/test_pet_action_exchange_dialog.py
git commit -m "feat: unify exchange center navigation and footer"
```

## 任务 7：接入应用层安全保存、重载和中心刷新

**文件：**
- 修改：`src/petnest/app.py`
- 修改：`tests/test_pet_action_exchange_app.py`
- 修改：`tests/test_app_and_platforms.py`

- [ ] **步骤 1：编写应用保存成功和重载失败回滚测试**

```python
import json


def test_app_saves_editor_page_timeline_and_reloads_current_pet(qtbot: object, tmp_path: Path) -> None:
    application = _application(tmp_path, qtbot)

    result = application._save_animation_timelines(application.package, {"idle": (180, 90, 120, 160)})

    saved = json.loads((application.package.root / "pet.json").read_text(encoding="utf-8"))
    assert result.success
    assert result.package is application.package
    assert saved["animations"]["idle"]["frame_durations_ms"] == [180, 90, 120, 160]


def test_app_restores_pet_json_when_runtime_reload_fails(qtbot: object, tmp_path: Path, monkeypatch: object) -> None:
    application = _application(tmp_path, qtbot)
    config_path = application.package.root / "pet.json"
    before = config_path.read_bytes()
    monkeypatch.setattr(application, "reload_current_pet", lambda: False)

    result = application._save_animation_timelines(application.package, {"idle": (180, 90, 120, 160)})

    assert not result.success
    assert config_path.read_bytes() == before
```

- [ ] **步骤 2：运行测试确认应用还依赖独立对话框**

运行：`python -m pytest tests/test_pet_action_exchange_app.py tests/test_app_and_platforms.py -k "exchange or animation_editor" -v`

预期：FAIL，`_save_animation_timelines` 不存在，统一中心也没有编辑页回调。

- [ ] **步骤 3：实现带配置快照的保存回调**

在 `PetNest` 中新增：

```python
def _save_animation_timelines(
    self,
    package: PetPackage,
    timelines: dict[str, tuple[int, ...]],
) -> AnimationSaveResult:
    if self._is_pet_locked_for_exchange(package.identifier):
        return AnimationSaveResult(False, "当前宠物正在显示下班提醒，请先结束提醒。")
    try:
        snapshot = self.action_synchronizer.snapshot_config_bytes(package.root)
        self.action_synchronizer.update_frame_durations(package.root, timelines)
    except AnimationActionSyncError as error:
        return AnimationSaveResult(False, f"无法保存动画时长：{error}")

    try:
        if package.identifier == self.package.identifier:
            if not self.reload_current_pet():
                raise AnimationActionSyncError("当前宠物重新载入失败")
            refreshed = self.package
        else:
            refreshed = self.loader.load(package.root)
            self.packages = [
                refreshed if item.identifier == refreshed.identifier else item
                for item in self.packages
            ]
    except Exception as error:
        try:
            self.action_synchronizer.restore_config_bytes(package.root, snapshot)
            if package.identifier == self.package.identifier:
                self.reload_current_pet()
        except AnimationActionSyncError as restore_error:
            return AnimationSaveResult(False, f"重载失败且配置恢复失败：{restore_error}")
        return AnimationSaveResult(False, f"保存未生效，已恢复原配置：{error}")
    return AnimationSaveResult(True, "已保存并重载", refreshed)
```

- [ ] **步骤 4：把中心构造和旧方法路由到新页面**

创建 `PetActionExchangeDialog` 时传入 `current_pet_id=self.package.identifier` 和 `save_animation_timelines=self._save_animation_timelines`。`show_animation_editor_dialog()` 改为兼容路由：

```python
def show_animation_editor_dialog(self) -> None:
    self.show_pet_action_exchange_dialog("编辑动作")
```

`show_spritesheet_import_dialog()` 和 `show_work_finish_import_dialog()` 继续分别路由“导入宠物”和“导入动作”。移除 `app.py` 对 `AnimationEditorDialog` 的直接导入和 `exec()` 保存路径。

- [ ] **步骤 5：安装后刷新中心而不是立即关闭**

`_handle_pet_exchange_installed` 与 `_handle_actions_exchange_installed` 完成库扫描、切换或重载后，调用：

```python
if self._pet_action_exchange_dialog is not None:
    self._pet_action_exchange_dialog.refresh_packages(self.packages, self.package.identifier)
```

删除两个处理方法末尾的 `close()`，让成功状态留在当前页面。运行时重载失败仍保留原有警告和完整宠物备份恢复逻辑。

- [ ] **步骤 6：运行应用集成与同步器测试**

运行：`python -m pytest tests/test_pet_action_exchange_app.py tests/test_app_and_platforms.py tests/test_animation_action_synchronizer.py -v`

预期：PASS；保存、回滚、旧方法路由和安装后刷新全部通过。

- [ ] **步骤 7：提交应用集成**

```bash
git add src/petnest/app.py tests/test_pet_action_exchange_app.py tests/test_app_and_platforms.py
git commit -m "feat: save animation timelines through exchange center"
```

## 任务 8：删除托盘重复入口

**文件：**
- 修改：`src/petnest/ui/tray_icon.py`
- 修改：`src/petnest/app.py`
- 修改：`tests/test_tray_exchange_entry.py`
- 修改：`tests/test_pet_window.py`

- [ ] **步骤 1：先把托盘测试改成最终菜单要求**

```python
def test_tray_exposes_only_unified_pet_action_entry(qtbot: object, tmp_path: Path) -> None:
    window = PetWindow(_package(tmp_path))
    qtbot.addWidget(window)
    tray = PetTrayIcon(window)
    labels = [action.text() for action in tray.pet_library_menu.actions() if not action.isSeparator()]

    assert labels == [
        "宠物与动作…",
        "打开宠物文件夹",
        "刷新宠物列表",
        "重新加载当前宠物",
    ]
    assert "导入精灵图…" not in labels
    assert "导入下班动画…" not in labels
    assert "编辑动画时长…" not in labels
```

- [ ] **步骤 2：运行测试确认旧入口仍存在**

运行：`python -m pytest tests/test_tray_exchange_entry.py tests/test_pet_window.py -k "tray" -v`

预期：FAIL，菜单仍包含三个旧入口。

- [ ] **步骤 3：删除动作、回调参数和应用构造传参**

从 `PetTrayIcon.__init__` 删除 `on_import`、`on_import_work_finish`、`on_edit_animations` 参数和对应实例字段；删除 `import_action`、`import_work_finish_action`、`edit_animations_action` 的创建、连接、菜单插入，以及 `_import`、`_import_work_finish`、`_edit_animations` 方法。

`PetNest` 创建托盘时删除三个对应参数，只保留：

```python
on_exchange=self.show_pet_action_exchange_dialog,
on_open_pets_folder=self.open_pets_folder,
on_refresh_pets=self.refresh_pets,
on_reload=self.reload_current_pet,
```

兼容路由方法继续留在 `PetNest`，但不再由托盘展示。

- [ ] **步骤 4：运行托盘和应用入口测试**

运行：`python -m pytest tests/test_tray_exchange_entry.py tests/test_tray_icon.py tests/test_pet_window.py tests/test_pet_action_exchange_app.py -v`

预期：PASS；宠物库只剩统一入口和三个基础管理项。

- [ ] **步骤 5：提交托盘收敛**

```bash
git add src/petnest/ui/tray_icon.py src/petnest/app.py tests/test_tray_exchange_entry.py tests/test_pet_window.py
git commit -m "refactor: remove duplicate pet library tray entries"
```

## 任务 9：完整验证与交付检查

**文件：**
- 检查：`src/petnest/ui/*.py`
- 检查：`src/petnest/app.py`
- 检查：`tests/*.py`

- [ ] **步骤 1：运行格式与语法检查**

运行：`git diff --check`

预期：无输出，退出码为 0。

运行：`python -m compileall -q src tests`

预期：无输出，退出码为 0。

- [ ] **步骤 2：运行统一中心完整定向测试**

运行：

```bash
python -m pytest tests/test_exchange_page.py tests/test_spritesheet_import_content.py tests/test_spritesheet_import_dialog.py tests/test_pet_import_page.py tests/test_action_import_page.py tests/test_animation_timing_editor.py tests/test_animation_editor_dialog.py tests/test_animation_editor_page.py tests/test_action_export_page.py tests/test_pet_action_exchange_dialog.py tests/test_pet_action_exchange_app.py tests/test_tray_exchange_entry.py -v
```

预期：全部通过，无失败、错误或意外跳过。

- [ ] **步骤 3：运行导入安全和下班提醒边界回归**

运行：

```bash
python -m pytest tests/test_exchange_source.py tests/test_pet_package_importer.py tests/test_action_installer.py tests/test_action_pack.py tests/test_package_validator.py tests/test_package_transaction.py tests/test_work_finish_reminder.py tests/test_work_finish_animation.py -v
```

预期：全部通过；Windows 无符号链接权限时只允许现有条件跳过。

- [ ] **步骤 4：运行全量测试**

运行：`python -m pytest -q`

预期：所有测试通过；跳过数量只包含平台或符号链接权限导致的既有条件跳过。

- [ ] **步骤 5：检查提交和工作区**

运行：`git status --short --branch`

预期：显示 `## codex/pet-action-exchange-center`，没有未跟踪或未提交文件。

运行：`git log --oneline -10`

预期：能看到本计划各任务的独立提交，提交顺序与任务依赖一致。
