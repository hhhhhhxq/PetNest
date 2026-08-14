# 打卡卡片紧凑尺寸与屏幕避让实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 让打卡卡片每次显示时恢复紧凑尺寸，并按右、左、下、上的顺序选择当前屏幕内不遮挡宠物的位置。

**架构：** 在 `work_countdown.py` 中增加一个不依赖窗口状态的纯定位函数，独立测试四向选择和极端降级；`ClockInCard` 负责按当前屏幕可用范围重算固定尺寸；`WorkCountdownWindow` 负责取得宠物全局矩形和所在屏幕，先更新内容与尺寸，再定位并显示。

**技术栈：** Python 3.12、PySide6 Qt Widgets、pytest、pytest-qt

---

## 文件结构

- 修改：`src/petnest/ui/work_countdown.py`——新增纯定位函数、紧凑尺寸方法和屏幕感知显示顺序。
- 修改：`tests/test_work_countdown.py`——覆盖异常放大恢复、四向避让、任务栏边界和极端降级。

### 任务 1：纯定位算法

**文件：**
- 修改：`src/petnest/ui/work_countdown.py`
- 测试：`tests/test_work_countdown.py`

- [ ] **步骤 1：编写失败的定位测试**

在测试导入中加入 `QRect`、`QSize` 和 `clock_in_card_position`，新增以下测试：

```python
def test_clock_in_card_position_prefers_right_then_flips_left() -> None:
    available = QRect(0, 0, 1000, 700)
    card = QSize(240, 120)

    assert clock_in_card_position(QRect(300, 200, 160, 160), card, available) == QPoint(472, 219)
    assert clock_in_card_position(QRect(820, 200, 160, 160), card, available) == QPoint(568, 219)


def test_clock_in_card_position_uses_below_then_above_when_sides_do_not_fit() -> None:
    available = QRect(0, 0, 500, 700)
    card = QSize(240, 120)

    assert clock_in_card_position(QRect(170, 180, 160, 160), card, available) == QPoint(129, 352)
    assert clock_in_card_position(QRect(170, 560, 160, 120), card, available) == QPoint(129, 428)


def test_clock_in_card_position_fallback_stays_visible_and_minimizes_overlap() -> None:
    available = QRect(100, 50, 300, 240)
    card = QSize(260, 200)
    pet = QRect(140, 80, 220, 180)

    point = clock_in_card_position(pet, card, available)
    placed = QRect(point, card)

    assert available.adjusted(8, 8, -8, -8).contains(placed)
    assert point == QPoint(119, 82)
```

- [ ] **步骤 2：运行定位测试验证失败**

运行：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_work_countdown.py -k "clock_in_card_position" -v
```

预期：测试收集失败，提示 `clock_in_card_position` 尚未定义。

- [ ] **步骤 3：实现最少纯定位函数**

在 `work_countdown.py` 中导入 `QRect`、`QSize`，增加常量和函数：

```python
CLOCK_IN_CARD_GAP = 12
CLOCK_IN_CARD_SCREEN_MARGIN = 8


def clock_in_card_position(
    pet_rect: QRect,
    card_size: QSize,
    available: QRect,
    *,
    gap: int = CLOCK_IN_CARD_GAP,
    margin: int = CLOCK_IN_CARD_SCREEN_MARGIN,
) -> QPoint:
    safe = available.adjusted(margin, margin, -margin, -margin)
    width = min(max(1, card_size.width()), max(1, safe.width()))
    height = min(max(1, card_size.height()), max(1, safe.height()))
    size = QSize(width, height)

    def clamp(value: int, lower: int, upper: int) -> int:
        return lower if upper < lower else max(lower, min(value, upper))

    vertical = clamp(
        pet_rect.center().y() - height // 2,
        safe.top(),
        safe.bottom() - height + 1,
    )
    horizontal = clamp(
        pet_rect.center().x() - width // 2,
        safe.left(),
        safe.right() - width + 1,
    )
    candidates = (
        QPoint(pet_rect.right() + 1 + gap, vertical),
        QPoint(pet_rect.left() - gap - width, vertical),
        QPoint(horizontal, pet_rect.bottom() + 1 + gap),
        QPoint(horizontal, pet_rect.top() - gap - height),
    )
    for point in candidates:
        placed = QRect(point, size)
        if safe.contains(placed) and not placed.intersects(pet_rect):
            return point

    fitted = []
    for index, point in enumerate(candidates):
        fitted_point = QPoint(
            clamp(point.x(), safe.left(), safe.right() - width + 1),
            clamp(point.y(), safe.top(), safe.bottom() - height + 1),
        )
        placed = QRect(fitted_point, size)
        overlap = placed.intersected(pet_rect)
        overlap_area = max(0, overlap.width()) * max(0, overlap.height())
        fitted.append((overlap_area, index, fitted_point))
    return min(fitted, key=lambda item: (item[0], item[1]))[2]
```

将函数加入 `__all__`。

- [ ] **步骤 4：运行定位测试验证通过**

运行同一步骤 2。预期：3 个定位测试通过。

### 任务 2：卡片紧凑尺寸与屏幕感知集成

**文件：**
- 修改：`src/petnest/ui/work_countdown.py`
- 测试：`tests/test_work_countdown.py`

- [ ] **步骤 1：编写失败的尺寸与集成测试**

新增测试：

```python
def test_clock_in_card_recovers_from_accidental_full_screen_size(qtbot: QtBot) -> None:
    parent = QWidget()
    qtbot.addWidget(parent)
    card = ClockInCard(parent)
    card.resize(1600, 700)

    fitted = card.fit_to_available_geometry(QRect(0, 0, 1920, 1040))

    assert card.size() == fitted
    assert card.width() < 500
    assert card.height() < 300
    assert card.minimumSize() == card.maximumSize()


def test_clock_in_card_size_is_capped_to_small_available_geometry(qtbot: QtBot) -> None:
    parent = QWidget()
    qtbot.addWidget(parent)
    card = ClockInCard(parent)

    fitted = card.fit_to_available_geometry(QRect(0, 0, 210, 150))

    assert fitted.width() <= 194
    assert fitted.height() <= 134
```

另在已有弹性打卡卡片测试中断言卡片矩形包含在模拟屏幕可用区域内，且宠物靠右时卡片位于宠物左侧。

- [ ] **步骤 2：运行新增测试验证失败**

运行：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_work_countdown.py -k "recovers_from_accidental or capped_to_small" -v
```

预期：失败，提示 `ClockInCard.fit_to_available_geometry` 尚未定义。

- [ ] **步骤 3：实现紧凑尺寸和显示顺序**

在 `ClockInCard` 中保存提示标签、启用换行，并加入：

```python
def fit_to_available_geometry(self, available: QRect) -> QSize:
    safe_width = max(1, available.width() - 2 * CLOCK_IN_CARD_SCREEN_MARGIN)
    safe_height = max(1, available.height() - 2 * CLOCK_IN_CARD_SCREEN_MARGIN)
    self.setMinimumSize(0, 0)
    self.setMaximumSize(16_777_215, 16_777_215)
    if self.layout() is not None:
        self.layout().activate()
    natural = self.sizeHint().expandedTo(self.minimumSizeHint())
    width = min(max(1, natural.width()), safe_width)
    height_for_width = self.layout().heightForWidth(width) if self.layout() is not None else -1
    height = max(natural.height(), height_for_width) if height_for_width >= 0 else natural.height()
    fitted = QSize(width, min(max(1, height), safe_height))
    self.setFixedSize(fitted)
    return fitted
```

同时从 `PySide6.QtGui` 导入 `QGuiApplication`。在 `WorkCountdownWindow._position_card()` 中：

1. 使用 `mapToGlobal(QPoint(0, 0))` 和宠物尺寸构造全局 `QRect`；
2. 使用 `QGuiApplication.screenAt(pet_rect.center())`，再回退到宠物屏幕和主屏幕；
3. 调用 `fit_to_available_geometry()`；
4. 调用 `clock_in_card_position()` 并移动卡片。

将 `_refresh_elastic()` 的顺序改为先 `show_for()` 更新内容，再 `_position_card()`，最后 `show()`。

- [ ] **步骤 4：运行工作倒计时测试验证通过**

运行：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_work_countdown.py -v
```

预期：全部通过。

### 任务 3：回归验证

**文件：**
- 验证：`src/petnest/ui/work_countdown.py`
- 验证：`tests/test_work_countdown.py`

- [ ] **步骤 1：检查格式和冲突标记**

运行：

```powershell
git diff --check
rg -n "^(<<<<<<<|=======|>>>>>>>)" src tests
```

预期：`git diff --check` 退出码 0；`rg` 无匹配。

- [ ] **步骤 2：运行相关测试套件**

运行：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_work_countdown.py tests\test_settings_dialog.py tests\test_pet_window.py tests\test_app_and_platforms.py
```

预期：无失败；Windows 符号链接权限测试可以跳过。

- [ ] **步骤 3：运行完整测试套件**

运行：

```powershell
.\.venv\Scripts\python.exe -m pytest
```

预期：无失败；仅允许已有的平台权限跳过项。

- [ ] **步骤 4：提交实现**

只暂存本计划、生产代码和对应测试，不包含工作区中原有的宠物资源、临时文件或未提交的设置测试修改：

```powershell
git add docs/superpowers/plans/2026-08-14-clock-in-card-layout.md src/petnest/ui/work_countdown.py tests/test_work_countdown.py
git commit -m "fix: keep clock-in card compact and visible"
```
