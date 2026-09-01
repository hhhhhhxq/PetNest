# 宠物旁轻量便签本实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 在宠物悬浮入口旁增加一个与现有道具箱同风格的便签本按钮，打开严格匹配最终原型的三页型本地便签本，并支持翻页、目录、自动保存、提醒、删除、清空和恢复。

**架构：** 纯 Python 核心层负责页面模型、原子 JSON 存储、标题派生、回收站与提醒时间计算；独立 PySide6 窗口负责最终原型对应的显示与编辑；现有宠物悬浮工具窗只增加入口和信号，`PetNest` 负责生命周期编排。便签正文与提醒内容不进入普通设置文件或日志。

**技术栈：** Python 3.12、PySide6 6.11、pytest、pytest-qt、JSON 原子文件写入、现有 Lucide SVG 渲染器。

---

## 文件结构

### 新建

- `src/petnest/core/quick_notebook_store.py`：页面模型、标题派生、CRUD、当前类型顺序、回收站和原子持久化。
- `src/petnest/core/quick_notebook_reminders.py`：一次、每天、每周提醒的下一次触发、完成和稍后计算。
- `src/petnest/ui/quick_notebook_window.py`：最终原型的一本式窗口、侧页签、三页型、目录、确认层和屏幕避让。
- `src/petnest/ui/quick_notebook_reminder.py`：宠物旁到期提醒卡片。
- `tests/test_quick_notebook_store.py`：存储、标题、翻页、删除与恢复测试。
- `tests/test_quick_notebook_reminders.py`：提醒计算测试。
- `tests/test_quick_notebook_window.py`：窗口视觉结构、交互和自适应测试。
- `tests/test_quick_notebook_reminder.py`：到期提醒卡片测试。

### 修改

- `src/petnest/models/settings.py`、`src/petnest/core/settings_manager.py`：开关与 schema 迁移。
- `src/petnest/ui/lucide_icons.py`、`src/petnest/ui/interaction_item_toolbox.py`：笔记本矢量图标与双入口。
- `src/petnest/ui/pet_window.py`、`src/petnest/app.py`：hover 和应用生命周期。
- `src/petnest/ui/settings_center_dialog.py`：设置开关。
- `tests/test_settings_manager.py`、`tests/test_settings_dialog.py`、`tests/test_interaction_item_toolbox.py`、`tests/test_pet_window.py`、`tests/test_app_and_platforms.py`：回归覆盖。
- `README.md`：用户说明和隐私边界。

## 任务 1：设置字段与向后迁移

**文件：**
- 修改：`src/petnest/models/settings.py`
- 修改：`src/petnest/core/settings_manager.py`
- 修改：`tests/test_settings_manager.py`

- [ ] **步骤 1：编写失败测试**

```python
def test_quick_notebook_defaults_to_disabled() -> None:
    assert Settings().quick_notebook_enabled is False


def test_migration_adds_quick_notebook_without_changing_other_values(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    raw = Settings(always_on_top=False).to_dict()
    raw.pop("quick_notebook_enabled", None)
    raw["schema_version"] = 28
    path.write_text(json.dumps(raw), encoding="utf-8")
    settings = SettingsManager(path).load()
    assert settings.quick_notebook_enabled is False
    assert settings.always_on_top is False
    assert settings.schema_version == 29
```

- [ ] **步骤 2：运行测试验证失败**

运行：`.venv\Scripts\python.exe -m pytest tests/test_settings_manager.py -k quick_notebook -v`

预期：FAIL，`Settings` 没有 `quick_notebook_enabled`。

- [ ] **步骤 3：实现 schema 29**

```python
class Settings:
    SCHEMA_VERSION = 29
    quick_notebook_enabled: bool = False
```

在 `Settings.from_dict` 的布尔值校验列表加入 `("quick_notebook_enabled", False)`，并在 `_migrate` 末尾加入：

```python
if version == 28:
    migrated.setdefault("quick_notebook_enabled", False)
    migrated["schema_version"] = Settings.SCHEMA_VERSION
```

- [ ] **步骤 4：验证并提交**

```powershell
.venv\Scripts\python.exe -m pytest tests/test_settings_manager.py -v
git add src/petnest/models/settings.py src/petnest/core/settings_manager.py tests/test_settings_manager.py
git commit -m feat:quick-notebook-setting
```

## 任务 2：页面模型、自动标题和原子存储

**文件：**
- 创建：`src/petnest/core/quick_notebook_store.py`
- 创建：`tests/test_quick_notebook_store.py`

- [ ] **步骤 1：编写标题和类型失败测试**

```python
NOW = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)


def test_display_title_prefers_custom_title_then_content() -> None:
    assert NotebookPage.note("给小林", "正文第一行\n第二行", now=NOW).display_title == "给小林"
    assert NotebookPage.note(None, "正文第一行\n第二行", now=NOW).display_title == "正文第一行"
    assert NotebookPage.todo(None, ["", "确认侧页签"], now=NOW).display_title == "确认侧页签"
    assert NotebookPage.reminder_list(None, ["", "周五交周报"], now=NOW).display_title == "周五交周报"


def test_empty_types_have_stable_fallback_titles() -> None:
    assert NotebookPage.note(None, "", now=NOW).display_title == "无标题便签"
    assert NotebookPage.todo(None, [], now=NOW).display_title == "新待办清单"
    assert NotebookPage.reminder_list(None, [], now=NOW).display_title == "新提醒列表"
```

- [ ] **步骤 2：编写存储、翻页和回收站失败测试**

```python
def test_store_round_trips_and_scopes_navigation_by_type(tmp_path: Path) -> None:
    store = QuickNotebookStore(tmp_path / "quick-notebook.json", now=lambda: NOW)
    first = store.create_page("note")
    second = store.create_page("note")
    todo = store.create_page("todo")
    store.save()
    loaded = QuickNotebookStore(tmp_path / "quick-notebook.json", now=lambda: NOW)
    loaded.load()
    assert loaded.page_ids("note") == (second.id, first.id)
    assert loaded.page_ids("todo") == (todo.id,)
    assert loaded.next_page("note", first.id) is None


def test_delete_clear_restore_and_expiry_are_recoverable(tmp_path: Path) -> None:
    current = [NOW]
    store = QuickNotebookStore(tmp_path / "quick-notebook.json", now=lambda: current[0])
    note = store.create_page("note")
    store.create_page("todo")
    store.delete_page(note.id)
    assert store.restore_page(note.id).id == note.id
    store.clear_all()
    assert store.trash_count == 2
    current[0] = datetime(2026, 9, 9, tzinfo=UTC)
    assert store.purge_expired_trash() == 2
```

- [ ] **步骤 3：运行测试验证模块不存在**

运行：`.venv\Scripts\python.exe -m pytest tests/test_quick_notebook_store.py -v`

预期：收集失败，`petnest.core.quick_notebook_store` 不存在。

- [ ] **步骤 4：实现模型和 store API**

```python
PageType = Literal["note", "todo", "reminder"]


@dataclass(slots=True)
class TodoItem:
    id: str
    text: str
    completed: bool = False
    created_at: str = ""
    completed_at: str | None = None


@dataclass(slots=True)
class ReminderItem:
    id: str
    text: str
    due_at: str | None = None
    repeat: str = "once"
    weekdays: tuple[int, ...] = ()
    enabled: bool = True
    completed: bool = False
    snoozed_until: str | None = None
    last_triggered_at: str | None = None


@dataclass(slots=True)
class NotebookPage:
    id: str
    type: PageType
    custom_title: str | None
    created_at: str
    updated_at: str
    body: str = ""
    tags: tuple[str, ...] = ()
    todo_items: list[TodoItem] = field(default_factory=list)
    reminders: list[ReminderItem] = field(default_factory=list)
```

实现 `display_title`、三个工厂方法，以及 `QuickNotebookStore.load/save/create_page/update_page/pages/page_ids/next_page/previous_page/delete_page/clear_all/restore_page/purge_expired_trash`。`save()` 采用临时文件、flush、fsync、replace；损坏 JSON 改名为 `.corrupt-<UTC>.bak` 后载入空数据集。

- [ ] **步骤 5：验证并提交**

```powershell
.venv\Scripts\python.exe -m pytest tests/test_quick_notebook_store.py -v
git add src/petnest/core/quick_notebook_store.py tests/test_quick_notebook_store.py
git commit -m feat:quick-notebook-store
```

## 任务 3：提醒时间计算

**文件：**
- 创建：`src/petnest/core/quick_notebook_reminders.py`
- 创建：`tests/test_quick_notebook_reminders.py`

- [ ] **步骤 1：编写失败测试**

```python
TZ = ZoneInfo("Asia/Shanghai")


def test_once_daily_weekly_and_snooze() -> None:
    due = datetime(2026, 9, 1, 18, 0, tzinfo=TZ)
    after = datetime(2026, 9, 1, 18, 1, tzinfo=TZ)
    assert next_occurrence(due, "once", (), after) is None
    assert next_occurrence(due, "daily", (), after) == datetime(2026, 9, 2, 18, 0, tzinfo=TZ)
    assert next_occurrence(due, "weekly", (0, 4), after) == datetime(2026, 9, 4, 18, 0, tzinfo=TZ)
    assert snooze_until(after) == datetime(2026, 9, 1, 18, 11, tzinfo=TZ)
```

- [ ] **步骤 2：确认失败**

运行：`.venv\Scripts\python.exe -m pytest tests/test_quick_notebook_reminders.py -v`

- [ ] **步骤 3：实现纯函数**

```python
def snooze_until(now: datetime) -> datetime:
    return now + timedelta(minutes=10)


def next_occurrence(due_at: datetime, repeat: str, weekdays: tuple[int, ...], after: datetime) -> datetime | None:
    if repeat == "once":
        return due_at if due_at > after else None
    if repeat == "daily":
        candidate = due_at
        while candidate <= after:
            candidate += timedelta(days=1)
        return candidate
    if repeat == "weekly":
        allowed = set(weekdays)
        for days in range(8):
            candidate = (after + timedelta(days=days)).replace(
                hour=due_at.hour, minute=due_at.minute, second=0, microsecond=0
            )
            if candidate > after and candidate.weekday() in allowed:
                return candidate
        return None
    raise ValueError(f"不支持的提醒重复规则：{repeat}")
```

- [ ] **步骤 4：验证并提交**

```powershell
.venv\Scripts\python.exe -m pytest tests/test_quick_notebook_reminders.py -v
git add src/petnest/core/quick_notebook_reminders.py tests/test_quick_notebook_reminders.py
git commit -m feat:quick-notebook-reminders
```

## 任务 4：矢量图标与双悬浮入口

**文件：**
- 修改：`src/petnest/ui/lucide_icons.py`
- 修改：`src/petnest/ui/interaction_item_toolbox.py`
- 修改：`tests/test_interaction_item_toolbox.py`

- [ ] **步骤 1：编写失败测试**

```python
def test_matching_toolbox_and_notebook_launchers(qtbot) -> None:
    toolbox = InteractionItemToolbox()
    qtbot.addWidget(toolbox)
    toolbox.set_notebook_enabled(True)
    assert toolbox.launcher.size() == QSize(44, 44)
    assert toolbox.notebook_launcher.size() == QSize(44, 44)
    assert toolbox.launcher.iconSize() == QSize(25, 25)
    assert toolbox.notebook_launcher.iconSize() == QSize(25, 25)
    assert toolbox.launcher_strip.layout().spacing() == 6
    assert toolbox.notebook_launcher.accessibleName() == "便签本"


def test_notebook_launcher_survives_empty_items(qtbot) -> None:
    toolbox = InteractionItemToolbox()
    qtbot.addWidget(toolbox)
    requests: list[bool] = []
    toolbox.notebook_requested.connect(lambda: requests.append(True))
    toolbox.set_items(())
    toolbox.set_notebook_enabled(True)
    toolbox.show_for(QRect(20, 20, 80, 80))
    assert toolbox.isVisible()
    assert not toolbox.launcher.isVisible()
    toolbox.notebook_launcher.click()
    assert requests == [True]
```

- [ ] **步骤 2：确认失败**

运行：`.venv\Scripts\python.exe -m pytest tests/test_interaction_item_toolbox.py -k notebook -v`

- [ ] **步骤 3：增加 `notebook` SVG 节点**

```python
"notebook": (
    '<rect x="5" y="3" width="15" height="18" rx="2"/>'
    '<path d="M9 3v18"/>'
    '<path d="M3 7h4"/><path d="M3 12h4"/><path d="M3 17h4"/>'
    '<path d="M12 8h5"/><path d="M12 12h5"/><path d="M12 16h3"/>'
),
```

- [ ] **步骤 4：实现 launcher strip 和可见规则**

```python
notebook_requested = Signal()

self.launcher_strip = QWidget(self)
strip_layout = QHBoxLayout(self.launcher_strip)
strip_layout.setContentsMargins(0, 0, 0, 0)
strip_layout.setSpacing(6)
strip_layout.addWidget(self.launcher)
self.notebook_launcher = QToolButton(self.launcher_strip)
self.notebook_launcher.setObjectName("quickNotebookLauncher")
self.notebook_launcher.setIcon(lucide_icon("notebook", color="#A84F30", fill="#F1B292", size=25))
self.notebook_launcher.setIconSize(QSize(25, 25))
self.notebook_launcher.setFixedSize(44, 44)
self.notebook_launcher.setToolTip("便签本")
self.notebook_launcher.setAccessibleName("便签本")
self.notebook_launcher.clicked.connect(self.notebook_requested)
strip_layout.addWidget(self.notebook_launcher)
```

实现 `set_notebook_enabled(enabled)`；`show_for` 在“有道具或便签开启”时显示。无道具时隐藏原道具 launcher，但保留便签入口；道具面板展开行为不变。

- [ ] **步骤 5：验证并提交**

```powershell
.venv\Scripts\python.exe -m pytest tests/test_interaction_item_toolbox.py -v
git add src/petnest/ui/lucide_icons.py src/petnest/ui/interaction_item_toolbox.py tests/test_interaction_item_toolbox.py
git commit -m feat:quick-notebook-launcher
```

## 任务 5：窗口骨架、侧页签与定位

**文件：**
- 创建：`src/petnest/ui/quick_notebook_window.py`
- 创建：`tests/test_quick_notebook_window.py`

- [ ] **步骤 1：编写失败测试**

```python
def test_place_notebook_prefers_right_then_flips_left() -> None:
    available = QRect(0, 0, 800, 600)
    assert place_notebook(QRect(100, 200, 80, 80), QSize(390, 448), available).x() == 189
    assert place_notebook(QRect(700, 200, 80, 80), QSize(390, 448), available).x() == 301


def test_window_matches_final_shell(qtbot) -> None:
    window = QuickNotebookWindow()
    qtbot.addWidget(window)
    assert window.objectName() == "quickNotebookWindow"
    assert window.width() <= 390
    assert [b.property("pageType") for b in window.type_tabs] == ["note", "todo", "reminder"]
    assert window.findChild(QWidget, "notebookAppHeader") is None
    assert window.findChild(QWidget, "notebookSearch") is None
    assert window.findChild(QWidget, "notebookPinButton") is None
    assert window.delete_button.accessibleName() == "删除当前便签"
```

- [ ] **步骤 2：确认失败**

运行：`set QT_QPA_PLATFORM=offscreen && .venv\Scripts\python.exe -m pytest tests/test_quick_notebook_window.py -k shell -v`

- [ ] **步骤 3：实现窗口 flags、定位和外壳**

```python
flags = Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
super().__init__(parent, flags)
self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
self.setObjectName("quickNotebookWindow")
```

`place_notebook` 按右、左、下、上尝试，间距 `9px`，结果约束在 `availableGeometry()`；均不足时选宠物重叠面积最小的位置。三个侧页签颜色为 `#9E8ACB/#75A876/#D39C54`，非活动 `43×43`，活动宽 `88`，右边缘覆盖纸页接缝 `1px`。其余 QSS 数值逐项复制规格第 5 节。

- [ ] **步骤 4：增加窄屏无裁切测试**

```python
def test_fit_keeps_footer_buttons_and_tabs_visible(qtbot) -> None:
    window = QuickNotebookWindow()
    qtbot.addWidget(window)
    fitted = window.fit_to_available_geometry(QRect(0, 0, 360, 520))
    assert fitted.width() <= 360
    assert fitted.height() <= 520
    assert window.footer.geometry().bottom() <= window.rect().bottom()
    assert window.new_button.geometry().right() <= window.rect().right()
```

- [ ] **步骤 5：验证并提交**

```powershell
set QT_QPA_PLATFORM=offscreen
.venv\Scripts\python.exe -m pytest tests/test_quick_notebook_window.py -v
git add src/petnest/ui/quick_notebook_window.py tests/test_quick_notebook_window.py
git commit -m feat:quick-notebook-window-shell
```

## 任务 6：三页型、目录、翻页和自动保存

**文件：**
- 修改：`src/petnest/ui/quick_notebook_window.py`
- 修改：`tests/test_quick_notebook_window.py`
- 修改：`tests/test_quick_notebook_store.py`

- [ ] **步骤 1：编写失败测试**

```python
def test_type_switch_scopes_directory_and_count(qtbot, tmp_path: Path) -> None:
    store = QuickNotebookStore(tmp_path / "quick-notebook.json")
    store.create_page("note")
    store.create_page("note")
    store.create_page("todo")
    window = QuickNotebookWindow(store=store)
    qtbot.addWidget(window)
    window.select_type("note")
    assert window.page_count_label.text() == "2 / 2"
    assert len(window.directory_titles()) == 2
    window.select_type("todo")
    assert window.page_count_label.text() == "1 / 1"
    assert len(window.directory_titles()) == 1


def test_optional_title_tracks_first_line_until_customized(qtbot, tmp_path: Path) -> None:
    store = QuickNotebookStore(tmp_path / "quick-notebook.json")
    page = store.create_page("note")
    window = QuickNotebookWindow(store=store)
    qtbot.addWidget(window)
    window.show_page(page.id)
    window.note_editor.setPlainText("自动标题\n正文")
    qtbot.wait(550)
    assert window.title_editor.text() == "自动标题"
    window.set_custom_title("自定义标题")
    window.note_editor.setPlainText("新首行")
    qtbot.wait(550)
    assert window.title_editor.text() == "自定义标题"
```

- [ ] **步骤 2：确认失败**

运行：`set QT_QPA_PLATFORM=offscreen && .venv\Scripts\python.exe -m pytest tests/test_quick_notebook_window.py -k "type_switch or optional_title" -v`

- [ ] **步骤 3：实现页面堆栈和编辑器 API**

```python
self.page_stack = QStackedWidget(self.paper)
self.note_editor = QPlainTextEdit(self.page_stack)
self.todo_editor = TodoListEditor(self.page_stack)
self.reminder_editor = ReminderListEditor(self.page_stack)
self.save_timer = QTimer(self)
self.save_timer.setSingleShot(True)
self.save_timer.setInterval(500)
self.save_timer.timeout.connect(self.flush_current_page)
```

`select_type()` 先 flush，再读取该类型的 last page。翻页只使用 `store.page_ids(active_type)`，首尾禁用。目录层只加载当前类型，加入“回收站”和“清空全部便签…”。待办支持新增、编辑、勾选、取消和上下移动；提醒支持标题、启用、时间和 `once/daily/weekly`。

普通正文使用 `QTextEdit.ExtraSelection` 跟随当前光标行绘制 `#FFF0E8` 浅底和 `#D98663` 左侧提示；失去编辑焦点时清除 selection，不能使用固定横线背景。

- [ ] **步骤 4：增加删除、清空和恢复测试**

```python
def test_delete_clear_and_restore_update_visible_pages(qtbot, tmp_path: Path) -> None:
    store = QuickNotebookStore(tmp_path / "quick-notebook.json")
    note = store.create_page("note")
    store.create_page("todo")
    window = QuickNotebookWindow(store=store)
    qtbot.addWidget(window)
    window.confirm_delete_page(note.id)
    assert store.trash_count == 1
    window.confirm_clear_all()
    assert store.trash_count == 2
    window.restore_from_trash(note.id)
    assert store.page(note.id) is not None
```

- [ ] **步骤 5：验证并提交**

```powershell
set QT_QPA_PLATFORM=offscreen
.venv\Scripts\python.exe -m pytest tests/test_quick_notebook_store.py tests/test_quick_notebook_window.py -v
git add src/petnest/ui/quick_notebook_window.py tests/test_quick_notebook_window.py tests/test_quick_notebook_store.py
git commit -m feat:quick-notebook-page-types
```

## 任务 7：到期提醒卡片

**文件：**
- 创建：`src/petnest/ui/quick_notebook_reminder.py`
- 创建：`tests/test_quick_notebook_reminder.py`

- [ ] **步骤 1：编写失败测试**

```python
def test_reminder_card_is_persistent_and_exposes_actions(qtbot) -> None:
    card = QuickNotebookReminderCard()
    qtbot.addWidget(card)
    completed: list[str] = []
    card.completed.connect(completed.append)
    card.show_reminder("r1", "把方案发给小林", QRect(100, 100, 80, 80))
    assert card.isVisible()
    assert card.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    assert card.findChild(QTimer, "dismissTimer") is None
    card.complete_button.click()
    assert completed == ["r1"]
```

- [ ] **步骤 2：确认失败**

运行：`set QT_QPA_PLATFORM=offscreen && .venv\Scripts\python.exe -m pytest tests/test_quick_notebook_reminder.py -v`

- [ ] **步骤 3：实现持久卡片**

使用 `Qt.Tool | FramelessWindowHint | WindowStaysOnTopHint`，不使用全屏、声音或自动消失计时器。显示标题、时间和“完成”“稍后 10 分钟”“打开便签”，复用 `place_notebook` 的方向候选与屏幕约束。

- [ ] **步骤 4：验证并提交**

```powershell
set QT_QPA_PLATFORM=offscreen
.venv\Scripts\python.exe -m pytest tests/test_quick_notebook_reminder.py -v
git add src/petnest/ui/quick_notebook_reminder.py tests/test_quick_notebook_reminder.py
git commit -m feat:quick-notebook-reminder-card
```

## 任务 8：宠物窗口与应用生命周期

**文件：**
- 修改：`src/petnest/ui/pet_window.py`
- 修改：`src/petnest/app.py`
- 修改：`tests/test_pet_window.py`
- 修改：`tests/test_app_and_platforms.py`

- [ ] **步骤 1：编写 PetWindow 失败测试**

```python
def test_pet_hover_shows_notebook_launcher_and_emits_request(qtbot, sample_package) -> None:
    window = PetWindow(sample_package)
    qtbot.addWidget(window)
    requests: list[bool] = []
    window.quick_notebook_requested.connect(lambda: requests.append(True))
    window.set_quick_notebook_enabled(True)
    window.enterEvent(QEnterEvent(QPointF(1, 1), QPointF(1, 1), QPointF(1, 1)))
    assert window.interaction_toolbox.notebook_launcher.isVisible()
    window.interaction_toolbox.notebook_launcher.click()
    assert requests == [True]
```

- [ ] **步骤 2：编写应用编排失败测试**

```python
def test_application_toggles_notebook_and_saves_on_shutdown(qtbot, tmp_path: Path) -> None:
    application = PetNest(
        pets_root=tmp_path / "pets",
        settings_manager=SettingsManager(tmp_path / "settings.json"),
        enable_tray=False,
    )
    qtbot.addWidget(application.window)
    application.apply_settings(replace(application.settings, quick_notebook_enabled=True))
    application._toggle_quick_notebook()
    assert application.quick_notebook_window.isVisible()
    application._toggle_quick_notebook()
    assert not application.quick_notebook_window.isVisible()
    application.shutdown()
    assert (tmp_path / "quick-notebook.json").exists()
```

- [ ] **步骤 3：确认失败**

运行：`set QT_QPA_PLATFORM=offscreen && .venv\Scripts\python.exe -m pytest tests/test_pet_window.py tests/test_app_and_platforms.py -k quick_notebook -v`

- [ ] **步骤 4：连接现有 hover 生命周期**

```python
quick_notebook_requested = Signal()

self.interaction_toolbox.notebook_requested.connect(self.quick_notebook_requested)

def set_quick_notebook_enabled(self, enabled: bool) -> None:
    self.interaction_toolbox.set_notebook_enabled(enabled)

def quick_notebook_anchor_rect(self) -> QRect:
    return self._global_window_rect()
```

把 `_interaction_can_show()` 拆成“道具是否可用”和“悬浮工具窗是否可见”两个判定，确保无道具时便签入口仍出现。`moveEvent` 继续只发 `position_changed`，不让 `PetWindow` 依赖便签窗口类。

- [ ] **步骤 5：在 PetNest 中创建并编排**

```python
self.quick_notebook_store = QuickNotebookStore(
    self.settings_manager.path.parent / "quick-notebook.json"
)
self.quick_notebook_store.load()
self.quick_notebook_window = QuickNotebookWindow(store=self.quick_notebook_store)
self.quick_notebook_reminder = QuickNotebookReminderCard()
self.window.quick_notebook_requested.connect(self._toggle_quick_notebook)
self.window.position_changed.connect(self._reposition_quick_notebook)
```

实现 `_configure_quick_notebook/_toggle_quick_notebook/_reposition_quick_notebook/_poll_quick_notebook_reminders`。提醒 timer 间隔 `30_000ms`，启动后立即扫描。宠物隐藏时使用托盘 `showMessage("PetNest 提醒", text)`，宠物可见时显示提醒卡片。`shutdown()` 依次停止 timer、flush、保存 store、关闭提醒卡片和笔记本窗口。

- [ ] **步骤 6：验证并提交**

```powershell
set QT_QPA_PLATFORM=offscreen
.venv\Scripts\python.exe -m pytest tests/test_pet_window.py tests/test_app_and_platforms.py -k quick_notebook -v
git add src/petnest/ui/pet_window.py src/petnest/app.py tests/test_pet_window.py tests/test_app_and_platforms.py
git commit -m feat:quick-notebook-lifecycle
```

## 任务 9：设置页面与用户文档

**文件：**
- 修改：`src/petnest/ui/settings_center_dialog.py`
- 修改：`tests/test_settings_dialog.py`
- 修改：`README.md`

- [ ] **步骤 1：编写设置 UI 失败测试**

```python
def test_display_page_edits_quick_notebook_setting(qtbot) -> None:
    dialog = SettingsCenterDialog(Settings(quick_notebook_enabled=False))
    qtbot.addWidget(dialog)
    assert dialog.quick_notebook_input.text() == "宠物旁便签本"
    dialog.quick_notebook_input.setChecked(True)
    assert dialog.result_settings().quick_notebook_enabled is True
```

- [ ] **步骤 2：确认失败**

运行：`set QT_QPA_PLATFORM=offscreen && .venv\Scripts\python.exe -m pytest tests/test_settings_dialog.py -k quick_notebook -v`

- [ ] **步骤 3：实现设置控件**

在 `_build_display_page` 的窗口行为卡片中增加：

```python
self.quick_notebook_input = ToggleSwitch("宠物旁便签本", card)
self.quick_notebook_input.setChecked(self._settings.quick_notebook_enabled)
form.addRow("便捷记录", self.quick_notebook_input)
```

在 `result_settings()` 的 `replace` 参数中加入 `quick_notebook_enabled=self.quick_notebook_input.isChecked()`。

- [ ] **步骤 4：更新 README**

在“当前功能与边界”说明三页型便签本；在“隐私与日志”说明内容保存到用户配置目录的 `quick-notebook.json`，不上传、不写日志；注明第一版没有搜索、云同步和附件。

- [ ] **步骤 5：验证并提交**

```powershell
set QT_QPA_PLATFORM=offscreen
.venv\Scripts\python.exe -m pytest tests/test_settings_dialog.py tests/test_settings_manager.py -v
git add src/petnest/ui/settings_center_dialog.py tests/test_settings_dialog.py README.md
git commit -m feat:quick-notebook-settings-ui
```

## 任务 10：一比一视觉复核与完整回归

**文件：**
- 修改：`src/petnest/ui/quick_notebook_window.py`（只修正复核发现的差异）
- 修改：`src/petnest/ui/interaction_item_toolbox.py`（只修正复核发现的差异）
- 修改：相关测试文件
- 参考：`.superpowers/brainstorm/notes-20260829/content/notebook-final-v1.html`

- [ ] **步骤 1：运行聚焦测试**

```powershell
set QT_QPA_PLATFORM=offscreen
.venv\Scripts\python.exe -m pytest tests/test_quick_notebook_store.py tests/test_quick_notebook_reminders.py tests/test_quick_notebook_window.py tests/test_quick_notebook_reminder.py tests/test_interaction_item_toolbox.py tests/test_settings_manager.py tests/test_settings_dialog.py -v
```

预期：全部 PASS。

- [ ] **步骤 2：生成 Qt 实际截图**

在 `tests/test_quick_notebook_window.py` 增加可显式调用的截图 helper：

```python
def save_visual_states(window: QuickNotebookWindow, output: Path) -> None:
    for page_type in ("note", "todo", "reminder"):
        window.select_type(page_type)
        window.grab().save(str(output / f"notebook-{page_type}.png"))
    window.open_directory()
    window.grab().save(str(output / "notebook-directory.png"))
```

截图保存在 `artifacts/quick-notebook-visual-qa/`，不提交二进制截图。

- [ ] **步骤 3：逐项对照最终原型**

逐项核对：入口尺寸与间距；无线圈/无顶部栏/无搜索/无图钉；圆角、纸色、边框和阴影；侧页签接缝、颜色和活动宽度；标题、正文和当前行提示；垃圾桶；底栏；目录/确认/回收站；100%/125%/150% DPI 与窄屏。每发现一项差异，先加入失败断言，再做最小布局或 QSS 修改并重新截图。

- [ ] **步骤 4：运行完整验证**

```powershell
.venv\Scripts\python.exe -m pytest
.venv\Scripts\python.exe -m compileall -q src tests
git diff --check
```

预期：`1496` 个基线测试加全部新增测试通过，平台能力相关测试保持 skip；编译和 diff 检查退出码为 `0`。

- [ ] **步骤 5：最终提交**

```powershell
git add src tests README.md
git commit -m feat:complete-quick-notebook
```

提交前运行 `git status --short`，确认没有把用户原有的未跟踪资源、宠物素材、构建产物或其他原型会话文件加入暂存区。
