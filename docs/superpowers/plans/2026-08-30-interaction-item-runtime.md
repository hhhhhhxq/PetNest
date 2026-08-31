# 通用互动道具运行时实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 为 PetNest 增加由宠物包声明的通用互动道具运行时，让用户从独立道具盒拖放道具到宠物并触发任意绑定动作，同时为下一版本的用户自定义配置保留稳定解析接口。

**架构：** 在宠物包模型中加入无动作语义的 `InteractionItemDefinition`，由独立 resolver 把道具 ID、动态事件名和现有 bindings/fallbacks 解析为运行时条目。Qt 道具盒负责展示和发起标准拖放，`PetWindow` 负责透明像素命中、状态机投递和生命周期清理；应用层只在现有右键菜单中增加备用入口。

**技术栈：** Python 3.11+、PySide6、Pillow、pytest、pytest-qt、现有 PetNest `PetStateMachine` / `PackageValidator` / `PackageLoader`

---

## 文件结构

- 创建 `src/petnest/core/interaction_items.py`：生成通用道具事件名，并把道具定义解析为可播放的普通宠物动作。
- 创建 `src/petnest/ui/interaction_item_toolbox.py`：独立的悬停入口、道具盘、拖放 MIME 数据和屏幕边界定位。
- 创建 `tests/test_interaction_items.py`：覆盖事件命名、fallback、全屏动作排除和未来覆盖源接口。
- 创建 `tests/test_interaction_item_toolbox.py`：覆盖道具按钮、MIME 数据、排序、展开收起和屏幕边界。
- 创建 `tests/test_pingan_interaction_items.py`：使用真实平安宠物包验证四个默认道具、动画和绑定。
- 修改 `src/petnest/models/pet_package.py`：增加不可变道具定义和 `PetPackage.interaction_items`。
- 修改 `src/petnest/core/package_validator.py`：把可选道具字段作为可隔离资源校验，记录合法图标路径。
- 修改 `src/petnest/core/package_loader.py`：加载已经通过校验的道具定义。
- 修改 `src/petnest/ui/pet_window.py`：接入 resolver、道具盒、Qt 拖放、透明像素命中、状态机和清理逻辑。
- 修改 `src/petnest/app.py`：在宠物右键菜单加入按能力显示的“打开道具盒”。
- 修改 `tests/test_package_validator.py`、`tests/test_package_loader.py`、`tests/test_pet_window.py`、`tests/test_app_and_platforms.py`：覆盖各层回归行为。
- 修改 `pets/pingan/pet.json`：登记四个动作、四个无语义 ID 道具和动态事件绑定。
- 创建 `pets/pingan/items/item_1.png` 至 `item_4.png`：四张透明统一风格道具图标。
- 修改 `README.md`：说明可选 `interaction_items` 格式和 `interaction.item.<id>` 事件。

## 任务 1：建立通用道具模型与解析器

**文件：**
- 创建：`src/petnest/core/interaction_items.py`
- 修改：`src/petnest/models/pet_package.py`
- 创建：`tests/test_interaction_items.py`

- [ ] **步骤 1：编写 resolver 的失败测试**

创建 `tests/test_interaction_items.py`，用完整的内存宠物包覆盖直接绑定、fallback、全屏目标排除、稳定事件名和覆盖源：

```python
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from petnest.core.interaction_items import (
    InteractionItemResolver,
    interaction_item_event,
)
from petnest.models.pet_package import (
    AnimationDefinition,
    Canvas,
    InteractionItemDefinition,
    PetPackage,
)


def _animation(tmp_path: Path, name: str, *, scope: str = "pet") -> AnimationDefinition:
    return AnimationDefinition(
        name=name,
        path=tmp_path,
        fps=8,
        loop=name == "idle",
        next_animation=None if name == "idle" else "context",
        priority=10 if name == "idle" else 70,
        interruptible=name == "idle",
        scope=scope,
    )


def _package(tmp_path: Path) -> PetPackage:
    icon = tmp_path / "item.png"
    item = InteractionItemDefinition("item_1", "任意道具", icon)
    animations = {
        "idle": _animation(tmp_path, "idle"),
        "wave": _animation(tmp_path, "wave"),
        "fullscreen": _animation(tmp_path, "fullscreen", scope="fullscreen"),
    }
    return PetPackage(
        root=tmp_path,
        identifier="test_pet",
        name="Test Pet",
        version="1",
        canvas=Canvas(16, 16),
        animations=animations,
        bindings={"interaction.item.item_1": "wave"},
        fallbacks={},
        interaction_items=(item,),
    )


def test_item_event_uses_generic_stable_prefix() -> None:
    assert interaction_item_event("item_1") == "interaction.item.item_1"


def test_resolver_keeps_order_and_resolves_bound_pet_action(tmp_path: Path) -> None:
    resolved = InteractionItemResolver().resolve(_package(tmp_path))

    assert [(item.definition.identifier, item.event_name, item.action_name) for item in resolved] == [
        ("item_1", "interaction.item.item_1", "wave")
    ]


def test_resolver_uses_fallback_but_excludes_fullscreen_and_unbound_items(tmp_path: Path) -> None:
    package = _package(tmp_path)
    items = (
        package.interaction_items[0],
        InteractionItemDefinition("item_2", "无绑定", tmp_path / "two.png"),
        InteractionItemDefinition("item_3", "全屏", tmp_path / "three.png"),
    )
    package = replace(
        package,
        interaction_items=items,
        bindings={
            "interaction.item.item_1": "missing",
            "interaction.item.item_3": "fullscreen",
        },
        fallbacks={"missing": ("wave",)},
    )

    resolved = InteractionItemResolver().resolve(package)

    assert [item.definition.identifier for item in resolved] == ["item_1"]
    assert resolved[0].action_name == "wave"


def test_resolver_accepts_future_definition_and_binding_overrides(tmp_path: Path) -> None:
    package = _package(tmp_path)
    override = InteractionItemDefinition("custom_1", "自定义", tmp_path / "custom.png")

    resolved = InteractionItemResolver().resolve(
        package,
        definitions=(override,),
        bindings={"interaction.item.custom_1": "wave"},
    )

    assert [item.definition.identifier for item in resolved] == ["custom_1"]
```

- [ ] **步骤 2：运行测试确认缺少模型和 resolver**

运行：

```bash
.venv/Scripts/python.exe -m pytest tests/test_interaction_items.py -q
```

预期：测试收集失败，提示无法导入 `InteractionItemDefinition` 或 `petnest.core.interaction_items`。

- [ ] **步骤 3：添加模型和最小解析实现**

在 `src/petnest/models/pet_package.py` 的 `PetPackage` 之前加入：

```python
@dataclass(frozen=True, slots=True)
class InteractionItemDefinition:
    """宠物包声明的无动作语义互动道具。"""

    identifier: str
    label: str
    icon: Path
```

在 `PetPackage` 的最后一个默认字段位置加入：

```python
    interaction_items: tuple[InteractionItemDefinition, ...] = field(default_factory=tuple)
```

创建 `src/petnest/core/interaction_items.py`：

```python
"""把无语义道具定义解析为当前宠物可触发的动作。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from petnest.core.fallback_resolver import FallbackResolver, GLOBAL_PLACEHOLDER
from petnest.models.pet_package import InteractionItemDefinition, PetPackage


INTERACTION_ITEM_EVENT_PREFIX = "interaction.item."


def interaction_item_event(item_id: str) -> str:
    return f"{INTERACTION_ITEM_EVENT_PREFIX}{item_id}"


@dataclass(frozen=True, slots=True)
class ResolvedInteractionItem:
    definition: InteractionItemDefinition
    event_name: str
    action_name: str


class InteractionItemResolver:
    def resolve(
        self,
        package: PetPackage,
        *,
        definitions: Sequence[InteractionItemDefinition] | None = None,
        bindings: Mapping[str, str] | None = None,
    ) -> tuple[ResolvedInteractionItem, ...]:
        source_definitions = tuple(definitions) if definitions is not None else package.interaction_items
        source_bindings = bindings if bindings is not None else package.bindings
        fallback_resolver = FallbackResolver(package.fallbacks)
        pet_actions = {
            name for name, definition in package.animations.items() if definition.scope == "pet"
        }
        resolved: list[ResolvedInteractionItem] = []
        for definition in source_definitions:
            event_name = interaction_item_event(definition.identifier)
            requested = source_bindings.get(event_name)
            if requested is None:
                continue
            action_name = fallback_resolver.resolve(requested, pet_actions)
            action = package.animations.get(action_name)
            if action_name == GLOBAL_PLACEHOLDER or action is None or action.scope != "pet":
                continue
            resolved.append(ResolvedInteractionItem(definition, event_name, action_name))
        return tuple(resolved)


__all__ = [
    "INTERACTION_ITEM_EVENT_PREFIX",
    "InteractionItemResolver",
    "ResolvedInteractionItem",
    "interaction_item_event",
]
```

- [ ] **步骤 4：运行 resolver 测试并确认通过**

运行：

```bash
.venv/Scripts/python.exe -m pytest tests/test_interaction_items.py -q
```

预期：`4 passed`。

- [ ] **步骤 5：提交领域模型**

```bash
git add src/petnest/models/pet_package.py src/petnest/core/interaction_items.py tests/test_interaction_items.py
git commit -m "feat: add generic interaction item resolver"
```

## 任务 2：校验并加载宠物包道具声明

**文件：**
- 修改：`src/petnest/core/package_validator.py`
- 修改：`src/petnest/core/package_loader.py`
- 修改：`tests/test_package_validator.py`
- 修改：`tests/test_package_loader.py`

- [ ] **步骤 1：为合法、隔离失败和旧包兼容编写失败测试**

在 `tests/test_package_validator.py` 追加：

```python
def test_interaction_items_validate_icons_and_isolate_bad_entries(tmp_path: Path) -> None:
    root = _write_package(
        tmp_path / "items",
        interaction_items=[
            {"id": "item_1", "label": "可用", "icon": "items/one.png"},
            {"id": "item_1", "label": "重复", "icon": "items/two.png"},
            {"id": "Bad ID", "label": "非法", "icon": "../outside.png"},
        ],
    )
    _write_png(root / "items" / "one.png", 32, 32)
    _write_png(root / "items" / "two.png", 32, 32)

    result = PackageValidator().validate(root)

    assert result.is_valid
    assert result.interaction_item_icons == {"item_1": (root / "items" / "one.png").resolve()}
    assert any("重复" in warning for warning in result.warnings)
    assert any("ID" in warning for warning in result.warnings)


def test_interaction_item_icon_requires_rgba_png_with_safe_size(tmp_path: Path) -> None:
    root = _write_package(
        tmp_path / "bad-icons",
        interaction_items=[
            {"id": "rgb", "label": "RGB", "icon": "items/rgb.png"},
            {"id": "huge", "label": "超限", "icon": "items/huge.png"},
        ],
    )
    _write_png(root / "items" / "rgb.png", 32, 32, alpha=False)
    _write_png(root / "items" / "huge.png", 513, 1)

    result = PackageValidator().validate(root)

    assert result.is_valid
    assert result.interaction_item_icons == {}
    assert len(result.warnings) == 2
```

在 `tests/test_package_loader.py` 追加：

```python
def test_loader_builds_only_valid_interaction_items(tmp_path: Path) -> None:
    root = _write_package(
        tmp_path / "loaded-items",
        interaction_items=[
            {"id": "item_1", "label": "第一个", "icon": "items/one.png"},
            {"id": "bad", "label": "损坏", "icon": "items/missing.png"},
        ],
    )
    _write_png(root / "items" / "one.png", 32, 32)

    package = PackageLoader().load(root)

    assert [(item.identifier, item.label) for item in package.interaction_items] == [
        ("item_1", "第一个")
    ]
    assert package.interaction_items[0].icon == (root / "items" / "one.png").resolve()


def test_loader_keeps_old_packages_item_free(tmp_path: Path) -> None:
    package = PackageLoader().load(_write_package(tmp_path / "legacy"))

    assert package.interaction_items == ()
```

- [ ] **步骤 2：运行定向测试并确认新增断言失败**

运行：

```bash
.venv/Scripts/python.exe -m pytest tests/test_package_validator.py tests/test_package_loader.py -q
```

预期：新增测试失败，指出 `ValidationResult` 没有 `interaction_item_icons`，且 loader 尚未填充 `interaction_items`。

- [ ] **步骤 3：实现可隔离的道具资源校验**

在 `src/petnest/core/package_validator.py` 增加常量和结果字段：

```python
_INTERACTION_ITEM_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_MAX_INTERACTION_ITEMS = 8
_MAX_INTERACTION_ICON_SIZE = 512


@dataclass(slots=True)
class ValidationResult:
    root: Path
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    config: dict[str, Any] | None = None
    frames: dict[str, tuple[Path, ...]] = field(default_factory=dict)
    interaction_item_icons: dict[str, Path] = field(default_factory=dict)
```

在 `validate()` 完成 bindings 校验后调用：

```python
        self._validate_interaction_items(parsed.get("interaction_items"), root, result)
```

加入以下校验方法；所有道具问题进入 warnings，因此单条损坏不会使整个宠物包失效：

```python
    @staticmethod
    def _validate_interaction_items(items: object, root: Path, result: ValidationResult) -> None:
        if items is None:
            return
        if not isinstance(items, list):
            result.warnings.append("interaction_items 必须是数组，已忽略")
            return
        if len(items) > _MAX_INTERACTION_ITEMS:
            result.warnings.append(f"interaction_items 最多 {_MAX_INTERACTION_ITEMS} 项，超出部分已忽略")
        seen: set[str] = set()
        for index, item in enumerate(items[:_MAX_INTERACTION_ITEMS], start=1):
            if not isinstance(item, Mapping):
                result.warnings.append(f"互动道具第 {index} 项必须是对象")
                continue
            item_id = item.get("id")
            label = item.get("label")
            icon = item.get("icon")
            if not isinstance(item_id, str) or _INTERACTION_ITEM_ID.fullmatch(item_id) is None:
                result.warnings.append(f"互动道具第 {index} 项的 ID 不合法")
                continue
            if item_id in seen:
                result.warnings.append(f"互动道具 ID {item_id} 重复，已忽略")
                continue
            seen.add(item_id)
            if not isinstance(label, str) or not 1 <= len(label.strip()) <= 40:
                result.warnings.append(f"互动道具 {item_id} 的 label 长度必须为 1–40")
                continue
            path = PackageValidator._safe_interaction_icon(root, icon, item_id, result)
            if path is not None:
                result.interaction_item_icons[item_id] = path

    @staticmethod
    def _safe_interaction_icon(
        root: Path,
        configured_path: object,
        item_id: str,
        result: ValidationResult,
    ) -> Path | None:
        if not isinstance(configured_path, str) or not configured_path.strip():
            result.warnings.append(f"互动道具 {item_id} 的 icon 必须是非空相对路径")
            return None
        candidate = Path(configured_path)
        resolved = (root / candidate).resolve()
        if candidate.is_absolute() or PureWindowsPath(configured_path).is_absolute() or not resolved.is_relative_to(root):
            result.warnings.append(f"互动道具 {item_id} 的图标路径必须位于包目录内")
            return None
        if resolved.suffix.casefold() != ".png" or not resolved.is_file():
            result.warnings.append(f"互动道具 {item_id} 的图标必须是存在的 PNG")
            return None
        try:
            with Image.open(resolved) as image:
                image.load()
                if "A" not in image.getbands():
                    result.warnings.append(f"互动道具 {item_id} 的图标缺少透明通道")
                    return None
                if image.width > _MAX_INTERACTION_ICON_SIZE or image.height > _MAX_INTERACTION_ICON_SIZE:
                    result.warnings.append(f"互动道具 {item_id} 的图标尺寸不能超过 512 × 512")
                    return None
        except (OSError, UnidentifiedImageError) as error:
            result.warnings.append(f"互动道具 {item_id} 的图标无法读取：{error}")
            return None
        return resolved
```

- [ ] **步骤 4：让 loader 只构造已校验道具**

在 `src/petnest/core/package_loader.py` 导入 `InteractionItemDefinition`，并在构造 `PetPackage` 时增加：

```python
            interaction_items=_interaction_items(config.get("interaction_items"), result.interaction_item_icons),
```

在文件末尾增加：

```python
def _interaction_items(
    raw_items: object,
    icons: Mapping[str, Path],
) -> tuple[InteractionItemDefinition, ...]:
    if not isinstance(raw_items, list):
        return ()
    loaded: list[InteractionItemDefinition] = []
    seen: set[str] = set()
    for raw in raw_items:
        if not isinstance(raw, Mapping):
            continue
        item_id = raw.get("id")
        label = raw.get("label")
        if (
            not isinstance(item_id, str)
            or not isinstance(label, str)
            or item_id not in icons
            or item_id in seen
        ):
            continue
        seen.add(item_id)
        loaded.append(InteractionItemDefinition(item_id, label.strip(), icons[item_id]))
    return tuple(loaded)
```

- [ ] **步骤 5：运行包层测试并确认通过**

运行：

```bash
.venv/Scripts/python.exe -m pytest tests/test_package_validator.py tests/test_package_loader.py tests/test_interaction_items.py -q
```

预期：全部通过。

- [ ] **步骤 6：提交包格式支持**

```bash
git add src/petnest/core/package_validator.py src/petnest/core/package_loader.py tests/test_package_validator.py tests/test_package_loader.py
git commit -m "feat: load package-defined interaction items"
```

## 任务 3：创建独立道具盒和拖放源控件

**文件：**
- 创建：`src/petnest/ui/interaction_item_toolbox.py`
- 创建：`tests/test_interaction_item_toolbox.py`

- [ ] **步骤 1：编写道具盒失败测试**

创建 `tests/test_interaction_item_toolbox.py`：

```python
from __future__ import annotations

from pathlib import Path

from PIL import Image
from PySide6.QtCore import QPoint, QRect, QSize

from petnest.core.interaction_items import ResolvedInteractionItem
from petnest.models.pet_package import InteractionItemDefinition
from petnest.ui.interaction_item_toolbox import (
    INTERACTION_ITEM_MIME,
    InteractionItemButton,
    InteractionItemToolbox,
    clamp_toolbox_position,
)


def _item(tmp_path: Path, item_id: str, label: str) -> ResolvedInteractionItem:
    icon = tmp_path / f"{item_id}.png"
    Image.new("RGBA", (32, 32), (255, 128, 64, 255)).save(icon)
    return ResolvedInteractionItem(
        InteractionItemDefinition(item_id, label, icon),
        f"interaction.item.{item_id}",
        "wave",
    )


def test_item_button_exposes_only_the_generic_item_id_mime(qtbot, tmp_path: Path) -> None:
    button = InteractionItemButton(_item(tmp_path, "item_1", "道具"))
    qtbot.addWidget(button)

    mime = button.mime_data()

    assert mime.hasFormat(INTERACTION_ITEM_MIME)
    assert bytes(mime.data(INTERACTION_ITEM_MIME)).decode("utf-8") == "item_1"


def test_toolbox_preserves_item_order_and_toggles_panel(qtbot, tmp_path: Path) -> None:
    toolbox = InteractionItemToolbox()
    qtbot.addWidget(toolbox)
    toolbox.set_items((_item(tmp_path, "item_2", "第二"), _item(tmp_path, "item_1", "第一")))

    assert [button.item.definition.identifier for button in toolbox.item_buttons] == ["item_2", "item_1"]
    assert not toolbox.is_expanded

    toolbox.open_panel()
    assert toolbox.is_expanded
    toolbox.collapse()
    assert not toolbox.is_expanded


def test_toolbox_position_flips_and_clamps_inside_available_screen() -> None:
    available = QRect(0, 0, 300, 200)
    size = QSize(120, 80)

    right_edge = clamp_toolbox_position(QRect(270, 80, 20, 20), available, size)
    bottom_edge = clamp_toolbox_position(QRect(100, 190, 20, 20), available, size)

    assert right_edge.x() == 142
    assert 0 <= right_edge.y() <= 120
    assert 0 <= bottom_edge.x() <= 180
    assert bottom_edge.y() == 120
```

- [ ] **步骤 2：运行测试确认控件模块缺失**

运行：

```bash
set QT_QPA_PLATFORM=offscreen
.venv/Scripts/python.exe -m pytest tests/test_interaction_item_toolbox.py -q
```

预期：测试收集失败，提示 `petnest.ui.interaction_item_toolbox` 不存在。

- [ ] **步骤 3：实现可测试的 MIME、布局和定位 API**

创建 `src/petnest/ui/interaction_item_toolbox.py`，实现以下稳定公开接口：

```python
from collections.abc import Sequence

from PySide6.QtCore import QEvent, QMimeData, QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QDrag, QEnterEvent, QGuiApplication, QIcon, QMouseEvent
from PySide6.QtWidgets import QApplication, QFrame, QGridLayout, QHBoxLayout, QToolButton, QWidget

from petnest.core.interaction_items import ResolvedInteractionItem
from petnest.ui.lucide_icons import lucide_icon


INTERACTION_ITEM_MIME = "application/x-petnest-interaction-item"


def clamp_toolbox_position(pet_rect: QRect, available: QRect, size: QSize) -> QPoint:
    x = pet_rect.right() + 8
    if x + size.width() > available.right() + 1:
        x = pet_rect.left() - size.width() - 8
    x = max(available.left(), min(x, available.right() - size.width() + 1))
    y = max(available.top(), min(pet_rect.top(), available.bottom() - size.height() + 1))
    return QPoint(x, y)
```

`InteractionItemButton(QToolButton)` 保存 `item`，通过 `mime_data()` 返回只含 UTF-8 item ID 的 `QMimeData`，并在左键移动超过系统阈值后发起标准拖放：

```python
class InteractionItemButton(QToolButton):
    def __init__(self, item: ResolvedInteractionItem, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.item = item
        self._press_position: QPoint | None = None
        self.setToolTip(item.definition.label)
        self.setAccessibleName(item.definition.label)
        self.setIcon(QIcon(str(item.definition.icon)))
        self.setIconSize(QSize(36, 36))
        self.setFixedSize(52, 52)

    def mime_data(self) -> QMimeData:
        mime = QMimeData()
        mime.setData(
            INTERACTION_ITEM_MIME,
            self.item.definition.identifier.encode("utf-8"),
        )
        return mime

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._press_position = event.position().toPoint() if event.button() == Qt.MouseButton.LeftButton else None
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._press_position is None or not event.buttons() & Qt.MouseButton.LeftButton:
            super().mouseMoveEvent(event)
            return
        distance = (event.position().toPoint() - self._press_position).manhattanLength()
        if distance < QApplication.startDragDistance():
            super().mouseMoveEvent(event)
            return
        self._press_position = None
        drag = QDrag(self)
        drag.setMimeData(self.mime_data())
        drag.setPixmap(self.icon().pixmap(self.iconSize()))
        drag.setHotSpot(QPoint(self.iconSize().width() // 2, self.iconSize().height() // 2))
        drag.exec(Qt.DropAction.MoveAction)
```

`InteractionItemToolbox(QFrame)` 必须：

- 使用 `Qt.Tool | Qt.FramelessWindowHint | Qt.WindowDoesNotAcceptFocus | Qt.WindowStaysOnTopHint`。
- 提供 `hover_changed = Signal(bool)`。
- 暴露 `item_buttons: tuple[InteractionItemButton, ...]` 和 `is_expanded`。
- `set_items()` 按 resolver 顺序重建最多八个按钮，并用两行四列网格展示。
- `open_panel()`、`collapse()`、`hide_all()` 明确控制状态。
- `show_for(pet_rect)` 和 `reposition(pet_rect)` 使用当前屏幕 `availableGeometry()` 与 `clamp_toolbox_position()`。
- launcher 使用 `package-open` Lucide 图标；道具按钮使用包内 PNG，不引入任何食物类别图标。
- `enterEvent`/`leaveEvent` 分别发送 `hover_changed(True/False)`。

核心状态方法采用以下实现，确保 PetWindow 不需要操作内部布局：

```python
    @property
    def item_buttons(self) -> tuple[InteractionItemButton, ...]:
        return tuple(self._item_buttons)

    @property
    def is_expanded(self) -> bool:
        return self._panel.isVisible()

    def set_items(self, items: Sequence[ResolvedInteractionItem]) -> None:
        for button in self._item_buttons:
            self._grid.removeWidget(button)
            button.deleteLater()
        self._item_buttons = []
        for index, item in enumerate(tuple(items)[:8]):
            button = InteractionItemButton(item, self._panel)
            self._grid.addWidget(button, index // 4, index % 4)
            self._item_buttons.append(button)
        if not self._item_buttons:
            self.hide_all()
        self.adjustSize()

    def open_panel(self) -> None:
        if self._item_buttons:
            self._panel.show()
            self.adjustSize()

    def collapse(self) -> None:
        self._panel.hide()
        self.adjustSize()

    def hide_all(self) -> None:
        self.collapse()
        self.hide()

    def show_for(self, pet_rect: QRect) -> None:
        if not self._item_buttons:
            return
        self._pet_rect = QRect(pet_rect)
        self.collapse()
        self.show()
        self.reposition(pet_rect)
        self.raise_()

    def reposition(self, pet_rect: QRect) -> None:
        if not self.isVisible():
            return
        self._pet_rect = QRect(pet_rect)
        self.adjustSize()
        screen = QGuiApplication.screenAt(pet_rect.center()) or QGuiApplication.primaryScreen()
        if screen is not None:
            self.move(clamp_toolbox_position(pet_rect, screen.availableGeometry(), self.size()))
```

使用如下统一样式，不把控件规则塞进 `pet_window.py`：

```python
_TOOLBOX_STYLE = """
QFrame#interactionItemToolbox { background: rgba(255,253,249,242); border: 1px solid #E8DED5; border-radius: 12px; }
QToolButton { background: #FFFDF9; border: 1px solid #E8DED5; border-radius: 9px; padding: 6px; }
QToolButton:hover { background: #FFF0E8; border-color: #D98663; }
"""
```

- [ ] **步骤 4：运行道具盒测试并确认通过**

运行：

```bash
set QT_QPA_PLATFORM=offscreen
.venv/Scripts/python.exe -m pytest tests/test_interaction_item_toolbox.py -q
```

预期：`3 passed`。

- [ ] **步骤 5：提交独立 UI 控件**

```bash
git add src/petnest/ui/interaction_item_toolbox.py tests/test_interaction_item_toolbox.py
git commit -m "feat: add interaction item toolbox widget"
```

## 任务 4：把道具拖放接入宠物窗口和状态机

**文件：**
- 修改：`src/petnest/ui/pet_window.py`
- 修改：`tests/test_pet_window.py`

- [ ] **步骤 1：为入口、命中、拒绝和清理编写失败测试**

在 `tests/test_pet_window.py` 的 `_package()` 可选参数中加入道具构造支持，或在各测试中用 `dataclasses.replace` 添加 `InteractionItemDefinition`。追加以下行为测试：

同时在该测试文件的宠物包模型导入列表中加入 `InteractionItemDefinition`，并从 `petnest.ui.interaction_item_toolbox` 导入 `INTERACTION_ITEM_MIME`，供 Qt 拖放事件测试使用。

```python
def test_item_drop_triggers_bound_action_only_on_opaque_pet(qtbot, tmp_path: Path) -> None:
    package = _package(tmp_path)
    icon = tmp_path / "tool.png"
    Image.new("RGBA", (32, 32), (255, 128, 64, 255)).save(icon)
    item = InteractionItemDefinition("item_1", "道具", icon)
    package = replace(
        package,
        interaction_items=(item,),
        bindings={**package.bindings, "interaction.item.item_1": "click"},
    )
    window = PetWindow(package)
    qtbot.addWidget(window)

    assert not window.trigger_interaction_item("item_1", QPoint(-1, -1))
    assert window.trigger_interaction_item("item_1", window.rect().center())
    assert window.current_action == "click"


def test_item_drop_is_rejected_during_stronger_noninterruptible_action(qtbot, tmp_path: Path) -> None:
    package = _package(tmp_path)
    icon = tmp_path / "tool.png"
    Image.new("RGBA", (32, 32), (255, 128, 64, 255)).save(icon)
    item = InteractionItemDefinition("item_1", "道具", icon)
    protected = replace(package.animations["click"], priority=100, interruptible=False)
    weak = replace(package.animations["hover"], name="weak", priority=20)
    package = replace(
        package,
        interaction_items=(item,),
        animations={**package.animations, "click": protected, "weak": weak},
        bindings={**package.bindings, "interaction.item.item_1": "weak"},
    )
    window = PetWindow(package)
    qtbot.addWidget(window)
    window.handle_pet_event(PetEvent("mouse.click", source="test"))

    assert not window.trigger_interaction_item("item_1", window.rect().center())
    assert window.current_action == "click"


def test_toolbox_visibility_follows_items_interaction_modes_and_reload(qtbot, tmp_path: Path) -> None:
    package = _package(tmp_path)
    icon = tmp_path / "tool.png"
    Image.new("RGBA", (32, 32), (255, 128, 64, 255)).save(icon)
    item = InteractionItemDefinition("item_1", "道具", icon)
    with_item = replace(
        package,
        interaction_items=(item,),
        bindings={**package.bindings, "interaction.item.item_1": "click"},
    )
    window = PetWindow(with_item)
    qtbot.addWidget(window)
    window.show()

    assert window.interaction_items_available
    assert window.open_interaction_toolbox()
    assert window.interaction_toolbox.isVisible()

    window.set_mouse_interaction_enabled(False)
    assert not window.interaction_toolbox.isVisible()

    window.set_mouse_interaction_enabled(True)
    window.set_follow_mode(True, scale_multiplier=0.45)
    assert not window.open_interaction_toolbox()

    window.set_follow_mode(False, scale_multiplier=0.45)
    window.load_package(package)
    assert not window.interaction_items_available
    assert not window.interaction_toolbox.isVisible()
```

同时增加一个 Qt 事件层测试：用 `QMimeData` 写入 `INTERACTION_ITEM_MIME`，构造 `QDragMoveEvent` 和 `QDropEvent`，验证透明点 ignore、非透明点 accept，且成功 drop 后高亮被清理。

- [ ] **步骤 2：运行 PetWindow 定向测试并确认失败**

运行：

```bash
set QT_QPA_PLATFORM=offscreen
.venv/Scripts/python.exe -m pytest tests/test_pet_window.py -k "interaction_item or item_drop or toolbox" -q
```

预期：失败，指出 `trigger_interaction_item`、`interaction_items_available` 和 `interaction_toolbox` 尚不存在。

- [ ] **步骤 3：创建 PetWindow 道具生命周期和事件 API**

在 `src/petnest/ui/pet_window.py` 的 Qt 导入中加入 `QMimeData`、`QDragEnterEvent`、`QDragMoveEvent`、`QDragLeaveEvent`、`QDropEvent`；同时导入 `InteractionItemResolver`、`INTERACTION_ITEM_MIME` 和 `InteractionItemToolbox`。

在 `PetWindow.__init__` 中：

```python
        self.setAcceptDrops(True)
        self._interaction_item_resolver = InteractionItemResolver()
        self._interaction_items = self._interaction_item_resolver.resolve(package)
        self._interaction_drop_active = False
        self._pet_pointer_over = False
        self._toolbox_pointer_over = False
        self._interaction_hide_timer = QTimer(self)
        self._interaction_hide_timer.setSingleShot(True)
        self._interaction_hide_timer.setInterval(180)
        self._interaction_hide_timer.timeout.connect(self._hide_interaction_toolbox_if_idle)
        self.interaction_toolbox = InteractionItemToolbox(None)
        self.interaction_toolbox.set_items(self._interaction_items)
        self.interaction_toolbox.hover_changed.connect(self._set_toolbox_pointer_over)
```

提供以下稳定方法和属性：

```python
    @property
    def interaction_items_available(self) -> bool:
        return bool(self._interaction_items)

    def open_interaction_toolbox(self) -> bool:
        if not self._interaction_can_show():
            return False
        self.interaction_toolbox.show_for(self._global_window_rect())
        self.interaction_toolbox.open_panel()
        return True

    def trigger_interaction_item(self, item_id: str, position: QPoint) -> bool:
        item = next((candidate for candidate in self._interaction_items if candidate.definition.identifier == item_id), None)
        if item is None or not self._mouse_interaction_enabled or self._follow_mode_enabled:
            return False
        if not self.is_opaque_at(position.x(), position.y()):
            return False
        transition = self.state_machine.handle(
            PetEvent(item.event_name, source="interaction-item", payload={"item_id": item_id})
        )
        if not transition.changed:
            return False
        self._play_current_action()
        self.interaction_toolbox.hide_all()
        return True
```

`_interaction_can_show()` 必须同时要求：有已解析道具、鼠标交互开启、未启用跟随模式、宠物窗口可见。

- [ ] **步骤 4：接入 hover 入口、Qt 拖放和绘制反馈**

按以下规则修改事件覆盖方法：

- `enterEvent` 设置 `_pet_pointer_over = True`，有道具时显示收起状态 launcher，并继续发送现有 `mouse.enter`。
- `leaveEvent` 设置 `_pet_pointer_over = False` 并启动 180ms 隐藏计时器；原有 `mouse.leave` 行为不变。
- toolbox 的 `hover_changed(True)` 停止隐藏计时器；`False` 再启动计时器。
- `dragEnterEvent` 只接受 MIME 中属于 `_interaction_items` 的 ID。
- `dragMoveEvent` 仅在 `is_opaque_at()` 为真时 `acceptProposedAction()`，并设置 `_interaction_drop_active = True`。
- `dragLeaveEvent` 清除 `_interaction_drop_active` 并刷新。
- `dropEvent` 调用 `trigger_interaction_item()`；返回真时接受 `MoveAction`，返回假时 ignore；两条路径都清除高亮。
- `paintEvent` 在宠物 pixmap 绘制完成后、倒计时绘制前，用 `QPen(QColor("#D98663"), 2)` 在 `pet_rect.adjusted(1, 1, -1, -1)` 绘制圆角命中框；只有 `_interaction_drop_active` 为真时绘制。

在 `moveEvent` 中调用 `interaction_toolbox.reposition(self._global_window_rect())`。在 `set_mouse_interaction_enabled(False)`、`set_follow_mode(True)`、`load_package()`、`hideEvent()` 和 `closeEvent()` 中调用统一 `_clear_interaction_ui()`；`load_package()` 还要重新运行 resolver 并 `set_items()`。

拖放事件使用以下共同解码与收尾路径，避免 enter、move、drop 三处产生不同判断：

```python
    def _interaction_item_id(self, mime: QMimeData) -> str | None:
        if not mime.hasFormat(INTERACTION_ITEM_MIME):
            return None
        try:
            item_id = bytes(mime.data(INTERACTION_ITEM_MIME)).decode("utf-8")
        except UnicodeDecodeError:
            return None
        known = {item.definition.identifier for item in self._interaction_items}
        return item_id if item_id in known else None

    def _set_interaction_drop_active(self, active: bool) -> None:
        if self._interaction_drop_active == active:
            return
        self._interaction_drop_active = active
        self.update()

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if self._interaction_item_id(event.mimeData()) is None:
            event.ignore()
            return
        event.acceptProposedAction()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:  # noqa: N802
        item_id = self._interaction_item_id(event.mimeData())
        point = event.position().toPoint()
        accepted = item_id is not None and self.is_opaque_at(point.x(), point.y())
        self._set_interaction_drop_active(accepted)
        if accepted:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:  # noqa: N802
        self._set_interaction_drop_active(False)
        event.accept()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        item_id = self._interaction_item_id(event.mimeData())
        accepted = item_id is not None and self.trigger_interaction_item(
            item_id,
            event.position().toPoint(),
        )
        self._set_interaction_drop_active(False)
        if accepted:
            event.setDropAction(Qt.DropAction.MoveAction)
            event.accept()
        else:
            event.ignore()
```

统一清理与刷新方法固定为：

```python
    def _clear_interaction_ui(self) -> None:
        self._interaction_hide_timer.stop()
        self._interaction_drop_active = False
        self._pet_pointer_over = False
        self._toolbox_pointer_over = False
        self.interaction_toolbox.hide_all()
        self.update()

    def _refresh_interaction_items(self) -> None:
        self._interaction_items = self._interaction_item_resolver.resolve(self.package)
        self.interaction_toolbox.set_items(self._interaction_items)
```

- [ ] **步骤 5：运行 PetWindow 与状态机回归测试**

运行：

```bash
set QT_QPA_PLATFORM=offscreen
.venv/Scripts/python.exe -m pytest tests/test_pet_window.py tests/test_state_machine.py tests/test_interaction_item_toolbox.py tests/test_interaction_items.py -q
```

预期：全部通过；现有宠物拖动阈值、单击、倒计时双击和上下文恢复测试无回归。

- [ ] **步骤 6：提交 PetWindow 集成**

```bash
git add src/petnest/ui/pet_window.py tests/test_pet_window.py
git commit -m "feat: drop interaction items onto pets"
```

## 任务 5：增加右键菜单备用入口

**文件：**
- 修改：`src/petnest/app.py`
- 修改：`tests/test_app_and_platforms.py`

- [ ] **步骤 1：编写菜单能力测试**

在 `tests/test_app_and_platforms.py` 追加测试，使用无道具示例包验证隐藏，再通过 `replace()` 给当前 `application.package` 和 `application.window` 加入一个可解析道具，验证显示与触发：

在该测试文件现有导入区加入 `from PIL import Image`（若尚未存在）以及 `from petnest.models.pet_package import InteractionItemDefinition`。

```python
def test_pet_context_menu_shows_item_entry_only_when_current_pet_supports_it(qtbot, tmp_path: Path, monkeypatch) -> None:
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    application = PetNest(
        pets_root=tmp_path / "pets",
        settings_manager=SettingsManager(tmp_path / "settings.json"),
        enable_tray=False,
    )
    qtbot.addWidget(application.window)

    application._sync_pet_context_menu()
    assert not application.interaction_items_action.isVisible()

    icon = tmp_path / "item.png"
    Image.new("RGBA", (32, 32), (255, 128, 64, 255)).save(icon)
    item = InteractionItemDefinition("item_1", "道具", icon)
    package = replace(
        application.package,
        interaction_items=(item,),
        bindings={**application.package.bindings, "interaction.item.item_1": "click"},
    )
    application.package = package
    application.window.load_package(package)
    opened: list[bool] = []
    monkeypatch.setattr(application.window, "open_interaction_toolbox", lambda: opened.append(True) or True)

    application._sync_pet_context_menu()
    application.interaction_items_action.trigger()

    assert application.interaction_items_action.isVisible()
    assert opened == [True]
    application.shutdown()
```

- [ ] **步骤 2：运行菜单测试确认 action 缺失**

运行：

```bash
set QT_QPA_PLATFORM=offscreen
.venv/Scripts/python.exe -m pytest tests/test_app_and_platforms.py -k pet_context_menu -q
```

预期：新增测试失败，提示 `interaction_items_action` 不存在。

- [ ] **步骤 3：在现有宠物右键菜单接入同一个道具盒**

在 `PetNest.__init__` 创建危险预警动作之后加入：

```python
        self.interaction_items_action = self.pet_context_menu.addAction("打开道具盒")
        self.interaction_items_action.triggered.connect(self.window.open_interaction_toolbox)
```

在 `_sync_pet_context_menu()` 加入：

```python
        self.interaction_items_action.setVisible(self.window.interaction_items_available)
```

不要在 app 层复制道具列表、动作解析或拖放逻辑。

- [ ] **步骤 4：运行菜单和应用回归测试**

运行：

```bash
set QT_QPA_PLATFORM=offscreen
.venv/Scripts/python.exe -m pytest tests/test_app_and_platforms.py -k "pet_context_menu or switch_pet or reload_current_pet" -q
```

预期：全部通过。

- [ ] **步骤 5：提交菜单入口**

```bash
git add src/petnest/app.py tests/test_app_and_platforms.py
git commit -m "feat: expose pet item toolbox from context menu"
```

## 任务 6：为平安登记四个默认道具

**文件：**
- 修改：`pets/pingan/pet.json`
- 创建：`pets/pingan/items/item_1.png`
- 创建：`pets/pingan/items/item_2.png`
- 创建：`pets/pingan/items/item_3.png`
- 创建：`pets/pingan/items/item_4.png`
- 创建：`tests/test_pingan_interaction_items.py`

- [ ] **步骤 1：先写真实宠物包集成测试**

创建 `tests/test_pingan_interaction_items.py`：

```python
from pathlib import Path

from petnest.core.interaction_items import InteractionItemResolver
from petnest.core.package_loader import PackageLoader


PINGAN_ROOT = Path(__file__).parents[1] / "pets" / "pingan"


def test_pingan_exposes_four_generic_items_bound_to_existing_actions() -> None:
    package = PackageLoader().load(PINGAN_ROOT)
    resolved = InteractionItemResolver().resolve(package)

    assert [(item.definition.identifier, item.definition.label, item.action_name) for item in resolved] == [
        ("item_1", "猫条", "eat_treat"),
        ("item_2", "饭碗", "eat_food"),
        ("item_3", "水碗", "drink_water"),
        ("item_4", "猫砂盆", "litter_box"),
    ]
    for action_name in ("eat_treat", "eat_food", "drink_water", "litter_box"):
        action = package.animations[action_name]
        assert len(action.frames) == 12
        assert not action.loop
        assert not action.interruptible
        assert action.next_animation == "context"
        assert action.scope == "pet"
```

- [ ] **步骤 2：运行真实包测试确认配置尚未登记**

运行：

```bash
.venv/Scripts/python.exe -m pytest tests/test_pingan_interaction_items.py -q
```

预期：失败，四个动作或 `interaction_items` 尚未出现在加载后的平安包中。

- [ ] **步骤 3：生成并检查四张透明道具图标**

先读取 `imagegen` 技能，再分别生成四张 `256 × 256` 透明 PNG。四次生成使用相同基础提示，仅替换主体：

```text
为 PetNest 轻 3D 奶油色桌宠 UI 制作单个道具图标：{猫条包装 / 盛着猫粮的浅色饭碗 / 盛着清水的浅蓝水碗 / 奶油色猫砂盆}。圆润、温暖、轻微 3D 塑料与陶瓷质感，正面略俯视，柔和粉橙描边，无文字，无角色，无场景，无投影边框，主体居中，四周留 12% 透明边距，完全透明背景，256×256 PNG。四张图标保持相同视角、光线、描边粗细和饱和度。
```

将输出分别保存为 `pets/pingan/items/item_1.png`、`item_2.png`、`item_3.png`、`item_4.png`。逐张使用本地图片查看工具确认透明背景、无文字、主体未裁切和风格一致；不通过的单张重新生成，不改动已经通过的图标。

- [ ] **步骤 4：以无语义 ID 更新平安配置**

用 `apply_patch` 在 `pets/pingan/pet.json` 增加四个普通动作，统一使用：

```json
{
  "fps": 8,
  "loop": false,
  "priority": 70,
  "interruptible": false,
  "next": "context"
}
```

各动作路径依次为 `animations/eat_treat`、`animations/eat_food`、`animations/drink_water`、`animations/litter_box`。增加：

```json
"interaction_items": [
  {"id": "item_1", "label": "猫条", "icon": "items/item_1.png"},
  {"id": "item_2", "label": "饭碗", "icon": "items/item_2.png"},
  {"id": "item_3", "label": "水碗", "icon": "items/item_3.png"},
  {"id": "item_4", "label": "猫砂盆", "icon": "items/item_4.png"}
]
```

在现有 `bindings` 中增加：

```json
"interaction.item.item_1": "eat_treat",
"interaction.item.item_2": "eat_food",
"interaction.item.item_3": "drink_water",
"interaction.item.item_4": "litter_box"
```

不要为这些动作添加到 `idle` 的 fallback；若对应动作资源损坏，resolver 应隐藏道具，而不是让投放只播放 idle。

- [ ] **步骤 5：校验真实宠物包与集成测试**

运行：

```bash
.venv/Scripts/python.exe tools/validate_pet.py pets/pingan
.venv/Scripts/python.exe -m pytest tests/test_pingan_interaction_items.py -q
```

预期：校验器报告宠物包有效，集成测试 `1 passed`。

- [ ] **步骤 6：提交平安默认内容**

```bash
git add pets/pingan/pet.json pets/pingan/items tests/test_pingan_interaction_items.py
git commit -m "feat: add default interaction items for pingan"
```

## 任务 7：文档、兼容性与完整验证

**文件：**
- 修改：`README.md`

- [ ] **步骤 1：补充宠物包格式文档**

在 `README.md` 宠物包字段表中增加：

```markdown
| `interaction_items` | 可选的无语义互动道具列表；每项包含包内唯一 `id`、显示 `label` 和包内 RGBA PNG `icon`。 |
```

在 bindings 说明后增加完整示例，明确投放事件按 `interaction.item.<id>` 生成，ID 不代表食物、水或其他固定类别，动作仍由 `bindings` 任意绑定；没有有效道具的宠物不显示道具盒。

- [ ] **步骤 2：运行格式和定向测试**

运行：

```bash
git diff --check
set QT_QPA_PLATFORM=offscreen
.venv/Scripts/python.exe -m pytest tests/test_interaction_items.py tests/test_interaction_item_toolbox.py tests/test_package_validator.py tests/test_package_loader.py tests/test_pet_window.py tests/test_app_and_platforms.py tests/test_pingan_interaction_items.py -q
```

预期：`git diff --check` 无输出且退出码为 0，所有定向测试通过。

- [ ] **步骤 3：运行完整测试套件**

运行：

```bash
set QT_QPA_PLATFORM=offscreen
.venv/Scripts/python.exe -m pytest -q
```

预期：退出码为 0，无失败和错误。

- [ ] **步骤 4：执行真实包和安装检查**

运行：

```bash
.venv/Scripts/python.exe tools/validate_pet.py pets/pingan
.venv/Scripts/python.exe -m petnest --check
```

预期：两条命令均退出码为 0；平安包有效，安装检查发现至少一个可用宠物包。

- [ ] **步骤 5：人工桌面验收**

用 `run.bat` 启动应用并逐项确认：

1. 平安悬停时出现道具盒按钮，其他无道具宠物不出现。
2. 从宠物身体拖动仍只移动宠物；从道具盘拖动只移动图标副本。
3. 四个图标拖到平安非透明区域分别播放正确一次性动作，结束后恢复当前上下文。
4. 拖到透明区域或桌面空白处取消，不播放动作。
5. 跟随鼠标、关闭鼠标交互、切换宠物、重新加载、隐藏宠物和退出时不残留道具窗。
6. 在多屏边缘、100%/150%/200% DPI 和宠物最小/最大缩放下，道具盒保持在可用屏幕内。

- [ ] **步骤 6：提交文档与最终整理**

```bash
git add README.md
git commit -m "docs: document package interaction items"
git status --short
```

预期：本任务相关文件没有未提交修改；工作区中原先存在的无关文件保持原状。
