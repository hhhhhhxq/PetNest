# Codex 自动发现与默认联动实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 让新用户默认允许 Codex 基础联动，并以真实安装证据、Codex Home、日志可读性与格式验证驱动状态；自动发现失败时允许用户安全指定数据目录。

**架构：** 新增独立 `codex_discovery.py`，将安装证据、候选目录、日志探测和最终可用性状态从增量日志播放器中分离。`PetNest` 只消费结构化可用性结果，负责定时重试、重配现有 watcher/Hook/plugin 和刷新设置页；设置页只展示普通状态并收集用户目录选择。

**技术栈：** Python 3.12、PySide6、dataclass/StrEnum、pathlib、pytest、pytest-qt。

---

## 文件结构

- 创建 `src/petnest/core/codex_discovery.py`：安装证据、候选 Codex Home、日志探测、自动选择和可用性状态的唯一职责模块。
- 创建 `tests/test_codex_discovery.py`：Windows/macOS 发现、候选排序、格式/权限/路径边界和手动覆盖测试。
- 修改 `src/petnest/core/codex_session_log.py`：允许切换已验证的 Codex Home，并保持 EOF 基线和脱敏解析行为。
- 修改 `src/petnest/core/codex_link.py`：允许 Hook manager 切换 Codex Home。
- 修改 `src/petnest/core/codex_plugin.py`：允许插件 CLI 环境切换 Codex Home，不改变 marketplace 安全边界。
- 修改 `src/petnest/models/settings.py`：schema 26、默认允许联动和 `codex_home_override`。
- 修改 `src/petnest/core/settings_manager.py`：旧配置迁移与显式关闭保留。
- 修改 `src/petnest/app.py`：发现服务装配、30 秒重试、真实状态和运行时重新配置。
- 修改 `src/petnest/ui/settings_center_dialog.py`：真实可用性文案、失败时目录选择、高级详情中的重新选择/恢复自动。
- 修改 `tests/test_settings_manager.py`、`tests/test_codex_session_log.py`、`tests/test_codex_link.py`、`tests/test_codex_plugin.py`、`tests/test_app_and_platforms.py`、`tests/test_settings_dialog.py`：对应回归和集成测试。
- 修改 `tests/conftest.py`：隔离测试进程与用户真实 `CODEX_HOME`，避免默认开启后读取本机会话。

### 任务 1：建立发现结果模型和只读日志探测

**文件：**
- 创建：`src/petnest/core/codex_discovery.py`
- 创建：`tests/test_codex_discovery.py`

- [ ] **步骤 1：编写可用日志、无 sessions、不可读和不兼容格式的失败测试**

```python
from __future__ import annotations

from datetime import date
import json
from pathlib import Path

from petnest.core.codex_discovery import (
    CodexAvailabilityState,
    CodexHomeCandidate,
    CodexLogSourceProbe,
)

TODAY = date(2026, 8, 21)


def _session_path(home: Path, name: str = "rollout-session.jsonl") -> Path:
    path = home / "sessions" / "2026" / "08" / "21" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _write_session(path: Path, *, session_id: str | None = "session-1") -> None:
    payload = {} if session_id is None else {"session_id": session_id}
    path.write_text(
        json.dumps({"type": "session_meta", "payload": payload}) + "\n"
        + json.dumps(
            {
                "type": "event_msg",
                "payload": {"type": "task_started", "turn_id": "turn-1"},
            }
        )
        + "\n",
        encoding="utf-8",
    )


def test_probe_reports_ready_only_after_validating_session_structure(tmp_path: Path) -> None:
    home = tmp_path / ".codex"
    _write_session(_session_path(home))

    result = CodexLogSourceProbe(today=lambda: TODAY).probe(
        CodexHomeCandidate(home, source="default", manual=False)
    )

    assert result.state is CodexAvailabilityState.READY
    assert result.can_watch is True
    assert result.sessions_path == (home / "sessions").resolve()


def test_probe_distinguishes_waiting_for_sessions_from_not_codex(tmp_path: Path) -> None:
    home = tmp_path / ".codex"
    home.mkdir()

    result = CodexLogSourceProbe(today=lambda: TODAY).probe(
        CodexHomeCandidate(home, source="app-server", manual=False)
    )

    assert result.state is CodexAvailabilityState.WAITING_FOR_SESSIONS
    assert result.can_watch is True


def test_probe_marks_missing_session_id_incompatible(tmp_path: Path) -> None:
    home = tmp_path / ".codex"
    _write_session(_session_path(home, "not-a-uuid.jsonl"), session_id=None)

    result = CodexLogSourceProbe(today=lambda: TODAY).probe(
        CodexHomeCandidate(home, source="default", manual=False)
    )

    assert result.state is CodexAvailabilityState.INCOMPATIBLE
    assert result.can_watch is False
    assert "session_id" in result.technical_reason


def test_probe_accepts_new_session_with_only_valid_metadata(tmp_path: Path) -> None:
    home = tmp_path / ".codex"
    path = _session_path(home)
    path.write_text(
        json.dumps({"type": "session_meta", "payload": {"session_id": "session-new"}}) + "\n",
        encoding="utf-8",
    )

    result = CodexLogSourceProbe(today=lambda: TODAY).probe(
        CodexHomeCandidate(home, source="app-server", manual=False)
    )

    assert result.state is CodexAvailabilityState.READY
    assert result.can_watch is True


def test_probe_distinguishes_unreadable_file_from_incompatible_json(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / ".codex"
    _write_session(_session_path(home))

    def deny_open(_path: Path, *_args, **_kwargs):
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "open", deny_open)
    result = CodexLogSourceProbe(today=lambda: TODAY).probe(
        CodexHomeCandidate(home, source="default", manual=False)
    )

    assert result.state is CodexAvailabilityState.UNREADABLE
    assert result.can_watch is False
```

- [ ] **步骤 2：运行测试并确认因模块缺失而失败**

运行：`python -m pytest tests/test_codex_discovery.py -q`

预期：收集阶段失败，提示 `ModuleNotFoundError: petnest.core.codex_discovery`。

- [ ] **步骤 3：实现最小状态模型、候选模型和有界探测器**

```python
# src/petnest/core/codex_discovery.py
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum
import json
from pathlib import Path


class CodexAvailabilityState(StrEnum):
    DISABLED = "disabled"
    DETECTING = "detecting"
    NOT_DETECTED = "not_detected"
    DATA_ONLY = "data_only"
    WAITING_FOR_SESSIONS = "waiting_for_sessions"
    UNREADABLE = "unreadable"
    INCOMPATIBLE = "incompatible"
    READY = "ready"
    ACTIVE = "active"


@dataclass(frozen=True, slots=True)
class CodexHomeCandidate:
    home: Path
    source: str
    manual: bool


@dataclass(frozen=True, slots=True)
class CodexLinkAvailability:
    state: CodexAvailabilityState
    message: str
    codex_detected: bool
    evidence: tuple[str, ...] = ()
    selected_home: Path | None = None
    sessions_path: Path | None = None
    manual_override: bool = False
    can_watch: bool = False
    technical_reason: str = ""


class CodexLogSourceProbe:
    def __init__(
        self,
        *,
        today: Callable[[], date] = date.today,
        max_files: int = 64,
        max_probe_bytes: int = 64 * 1024,
    ) -> None:
        self._today = today
        self._max_files = max(1, max_files)
        self._max_probe_bytes = max(1024, max_probe_bytes)

    def probe(self, candidate: CodexHomeCandidate) -> CodexLinkAvailability:
        home = candidate.home.expanduser().resolve()
        sessions = home / "sessions"
        if not home.is_dir():
            return CodexLinkAvailability(
                state=CodexAvailabilityState.NOT_DETECTED,
                message="未找到 Codex 数据目录",
                codex_detected=False,
                selected_home=home,
                manual_override=candidate.manual,
                technical_reason="Codex Home 不存在",
            )
        if not sessions.exists():
            return CodexLinkAvailability(
                state=CodexAvailabilityState.WAITING_FOR_SESSIONS,
                message="等待 Codex 创建本地任务",
                codex_detected=False,
                evidence=(candidate.source,),
                selected_home=home,
                sessions_path=sessions,
                manual_override=candidate.manual,
                can_watch=True,
            )
        files = self._candidate_files(sessions)
        if not files:
            return CodexLinkAvailability(
                state=CodexAvailabilityState.WAITING_FOR_SESSIONS,
                message="等待 Codex 创建本地任务",
                codex_detected=False,
                evidence=(candidate.source,),
                selected_home=home,
                sessions_path=sessions,
                manual_override=candidate.manual,
                can_watch=True,
            )
        reasons: list[str] = []
        for path in files:
            compatible, reason = self._probe_file(path)
            if compatible:
                return CodexLinkAvailability(
                    state=CodexAvailabilityState.READY,
                    message="联动已准备好，等待新的任务",
                    codex_detected=False,
                    evidence=(candidate.source,),
                    selected_home=home,
                    sessions_path=sessions,
                    manual_override=candidate.manual,
                    can_watch=True,
                )
            reasons.append(reason)
        state = (
            CodexAvailabilityState.UNREADABLE
            if any(reason.startswith("无法读取") for reason in reasons)
            else CodexAvailabilityState.INCOMPATIBLE
        )
        message = (
            "无法读取 Codex 本地日志"
            if state is CodexAvailabilityState.UNREADABLE
            else "当前 Codex 版本暂不支持基础联动"
        )
        return CodexLinkAvailability(
            state=state,
            message=message,
            codex_detected=False,
            evidence=(candidate.source,),
            selected_home=home,
            sessions_path=sessions,
            manual_override=candidate.manual,
            can_watch=False,
            technical_reason="; ".join(reasons[:3]),
        )

    def _candidate_files(self, sessions: Path) -> tuple[Path, ...]:
        current = self._today()
        directories = tuple(
            sessions / f"{day:%Y}" / f"{day:%m}" / f"{day:%d}"
            for day in (current - timedelta(days=1), current)
        )
        files: list[Path] = []
        for directory in directories:
            if not directory.is_dir() or _is_link_like(directory):
                continue
            files.extend(
                path
                for path in directory.glob("*.jsonl")
                if path.is_file() and not _is_link_like(path)
            )
        files.sort(key=lambda path: str(path).casefold())
        return tuple(files[-self._max_files :])

    def _probe_file(self, path: Path) -> tuple[bool, str]:
        try:
            with path.open("rb") as stream:
                raw = stream.read(self._max_probe_bytes)
        except OSError as error:
            return False, f"无法读取 {path.name}: {error}"
        session_id: str | None = None
        invalid_status_event = ""
        for line in raw.splitlines():
            try:
                document = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if not isinstance(document, dict):
                continue
            payload = document.get("payload")
            if document.get("type") == "session_meta" and isinstance(payload, dict):
                value = payload.get("session_id")
                if isinstance(value, str) and 0 < len(value) <= 200:
                    session_id = value
            if document.get("type") == "event_msg" and isinstance(payload, dict):
                event_type = payload.get("type")
                if event_type in {"task_started", "task_complete", "turn_aborted"}:
                    turn_id = payload.get("turn_id")
                    if not isinstance(turn_id, str) or not 0 < len(turn_id) <= 200:
                        invalid_status_event = f"{path.name} 的 {event_type} 缺少 turn_id"
        if session_id is None:
            return False, f"{path.name} 缺少 session_id"
        if invalid_status_event:
            return False, invalid_status_event
        return True, ""


def _is_link_like(path: Path) -> bool:
    try:
        return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())
    except OSError:
        return True
```

- [ ] **步骤 4：运行发现测试验证通过**

运行：`python -m pytest tests/test_codex_discovery.py -q`

预期：上述测试全部 PASS。

- [ ] **步骤 5：提交模型与探测器**

```bash
git add src/petnest/core/codex_discovery.py tests/test_codex_discovery.py
git commit -m "feat: probe Codex log availability"
```

### 任务 2：发现 Windows/macOS 安装证据和全部 Codex Home 候选

**文件：**
- 修改：`src/petnest/core/codex_discovery.py`
- 测试：`tests/test_codex_discovery.py`

- [ ] **步骤 1：编写候选不短路、Windows Desktop 优先和 macOS 应用包测试**

```python
def test_home_discovery_keeps_app_server_candidate_when_stale_default_exists(tmp_path: Path) -> None:
    default = tmp_path / ".codex"
    actual = tmp_path / "profiles" / "current"
    default.mkdir()
    actual.mkdir(parents=True)
    discovery = CodexHomeDiscovery(
        environment={},
        user_home=tmp_path,
        app_home_provider=lambda: actual,
    )

    candidates = discovery.candidates(None)

    assert [item.home for item in candidates] == [actual.resolve(), default.resolve()]


def test_windows_detector_prefers_desktop_exe_over_path_cmd(tmp_path: Path) -> None:
    desktop = tmp_path / "LocalAppData" / "OpenAI" / "Codex" / "bin" / "v1" / "codex.exe"
    desktop.parent.mkdir(parents=True)
    desktop.write_bytes(b"exe")
    detector = CodexInstallationDetector(
        platform_name="win32",
        environment={"LOCALAPPDATA": str(tmp_path / "LocalAppData")},
        user_home=tmp_path,
        which=lambda _name: str(tmp_path / "node" / "codex.CMD"),
    )

    evidence = detector.detect()

    assert evidence[0].kind == "desktop"
    assert evidence[0].path == desktop.resolve()


def test_macos_detector_finds_system_and_user_app_bundles(tmp_path: Path) -> None:
    system_app = tmp_path / "Applications" / "Codex.app"
    user_app = tmp_path / "Users" / "me" / "Applications" / "Codex.app"
    system_app.mkdir(parents=True)
    user_app.mkdir(parents=True)
    detector = CodexInstallationDetector(
        platform_name="darwin",
        environment={},
        user_home=tmp_path / "Users" / "me",
        application_roots=(tmp_path / "Applications", user_app.parent),
        which=lambda _name: None,
    )

    evidence = detector.detect()

    assert {item.path for item in evidence if item.kind == "desktop"} == {
        system_app.resolve(),
        user_app.resolve(),
    }
```

- [ ] **步骤 2：运行新测试并确认缺少 detector/discovery 类型**

运行：`python -m pytest tests/test_codex_discovery.py -q`

预期：FAIL，提示无法导入 `CodexHomeDiscovery` 或 `CodexInstallationDetector`。

- [ ] **步骤 3：实现注入式安装检测和候选收集**

```python
@dataclass(frozen=True, slots=True)
class CodexInstallEvidence:
    kind: str
    detail: str
    path: Path | None = None


class CodexInstallationDetector:
    def __init__(
        self,
        *,
        platform_name: str,
        environment: Mapping[str, str],
        user_home: Path,
        which: Callable[[str], str | None] = shutil.which,
        application_roots: tuple[Path, ...] | None = None,
    ) -> None:
        self._platform_name = platform_name
        self._environment = environment
        self._user_home = user_home.expanduser().resolve()
        self._which = which
        self._application_roots = application_roots

    def detect(self) -> tuple[CodexInstallEvidence, ...]:
        evidence: list[CodexInstallEvidence] = []
        if self._platform_name == "win32":
            local = self._environment.get("LOCALAPPDATA")
            if local:
                desktop = sorted(
                    Path(local).glob("OpenAI/Codex/bin/*/codex.exe"),
                    key=lambda path: path.stat().st_mtime_ns if path.is_file() else 0,
                    reverse=True,
                )
                if desktop:
                    evidence.append(CodexInstallEvidence("desktop", "Codex Desktop", desktop[0].resolve()))
        elif self._platform_name == "darwin":
            roots = self._application_roots or (
                Path("/Applications"),
                self._user_home / "Applications",
            )
            for root in roots:
                app = root / "Codex.app"
                if app.is_dir():
                    evidence.append(CodexInstallEvidence("desktop", "Codex.app", app.resolve()))
        command = self._which("codex")
        if command:
            evidence.append(CodexInstallEvidence("cli", "PATH 中的 Codex CLI", Path(command).resolve()))
        configured = self._environment.get("CODEX_HOME")
        if configured and configured.strip():
            evidence.append(
                CodexInstallEvidence("configured-home", "CODEX_HOME", Path(configured).expanduser().resolve())
            )
        default = self._user_home / ".codex"
        if default.is_dir():
            evidence.append(CodexInstallEvidence("data", "默认 Codex 数据目录", default.resolve()))
        return tuple(evidence)


class CodexHomeDiscovery:
    def __init__(
        self,
        *,
        environment: Mapping[str, str],
        user_home: Path,
        app_home_provider: Callable[[], Path | None],
    ) -> None:
        self._environment = environment
        self._user_home = user_home.expanduser().resolve()
        self._app_home_provider = app_home_provider

    def candidates(self, manual_home: Path | None) -> tuple[CodexHomeCandidate, ...]:
        if manual_home is not None:
            return (
                CodexHomeCandidate(
                    normalize_selected_codex_home(manual_home),
                    source="manual",
                    manual=True,
                ),
            )
        raw: list[tuple[Path, str]] = []
        configured = self._environment.get("CODEX_HOME")
        if configured and configured.strip():
            raw.append((Path(configured).expanduser(), "environment"))
        try:
            app_home = self._app_home_provider()
        except (OSError, RuntimeError, ValueError):
            app_home = None
        if app_home is not None:
            raw.append((app_home, "app-server"))
        raw.append((self._user_home / ".codex", "default"))
        candidates: list[CodexHomeCandidate] = []
        seen: set[Path] = set()
        for path, source in raw:
            resolved = path.expanduser().resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            candidates.append(CodexHomeCandidate(resolved, source, False))
        candidates.sort(key=lambda item: {"environment": 0, "app-server": 1, "default": 2}[item.source])
        return tuple(candidates)
```

实现要求：

- app-server 成功返回值、`CODEX_HOME`、默认 `~/.codex` 全部进入候选后按来源优先级排序；
- 候选使用规范化绝对路径去重；
- app-server 异常只增加脱敏诊断，不阻止其他候选；
- 手动目录存在时只返回手动候选；
- Windows Desktop 路径优先于 PATH `.CMD`；
- macOS 检测 `/Applications/Codex.app` 和 `~/Applications/Codex.app`；
- 仅有 `.codex` 数据目录时 evidence kind 为 `data`，不等同强安装证据。

- [ ] **步骤 4：运行候选和跨平台测试验证通过**

运行：`python -m pytest tests/test_codex_discovery.py -q`

预期：PASS。

- [ ] **步骤 5：提交跨平台发现**

```bash
git add src/petnest/core/codex_discovery.py tests/test_codex_discovery.py
git commit -m "feat: discover Codex installations and homes"
```

### 任务 3：实现候选选择、手动覆盖和统一可用性服务

**文件：**
- 修改：`src/petnest/core/codex_discovery.py`
- 测试：`tests/test_codex_discovery.py`

- [ ] **步骤 1：编写兼容源胜过旧目录、手动失败不静默切换的测试**

```python
def test_service_selects_compatible_candidate_instead_of_first_existing_directory(tmp_path: Path) -> None:
    stale = tmp_path / ".codex"
    actual = tmp_path / "profile"
    stale.mkdir()
    _write_session(_session_path(actual))
    service = _service(tmp_path, homes=(stale, actual))

    availability = service.discover(None)

    assert availability.state is CodexAvailabilityState.READY
    assert availability.selected_home == actual.resolve()


def test_invalid_manual_home_is_reported_without_switching_to_auto_candidate(tmp_path: Path) -> None:
    actual = tmp_path / "auto"
    _write_session(_session_path(actual))
    manual = tmp_path / "missing-manual"
    service = _service(tmp_path, homes=(actual,))

    availability = service.discover(manual)

    assert availability.state is CodexAvailabilityState.NOT_DETECTED
    assert availability.selected_home == manual.resolve()
    assert availability.manual_override is True
    assert "自动查找另有可用目录" in availability.technical_reason


def test_selecting_sessions_directory_normalizes_to_codex_home(tmp_path: Path) -> None:
    home = tmp_path / ".codex"
    _write_session(_session_path(home))

    normalized = normalize_selected_codex_home(home / "sessions")

    assert normalized == home.resolve()
```

- [ ] **步骤 2：运行测试并确认统一服务尚不存在**

运行：`python -m pytest tests/test_codex_discovery.py -q`

预期：FAIL，提示 `CodexDiscoveryService` 或 `normalize_selected_codex_home` 未定义。

- [ ] **步骤 3：实现统一服务和状态选择优先级**

```python
class CodexDiscoveryService:
    _STATE_SCORE = {
        CodexAvailabilityState.READY: 50,
        CodexAvailabilityState.WAITING_FOR_SESSIONS: 40,
        CodexAvailabilityState.UNREADABLE: 30,
        CodexAvailabilityState.INCOMPATIBLE: 20,
        CodexAvailabilityState.DATA_ONLY: 10,
        CodexAvailabilityState.NOT_DETECTED: 0,
    }

    def __init__(
        self,
        detector: CodexInstallationDetector,
        home_discovery: CodexHomeDiscovery,
        probe: CodexLogSourceProbe,
    ) -> None:
        self._detector = detector
        self._home_discovery = home_discovery
        self._probe = probe

    def discover(self, manual_home: Path | None) -> CodexLinkAvailability:
        evidence = self._detector.detect()
        candidates = self._home_discovery.candidates(manual_home)
        results = tuple(self._probe.probe(item) for item in candidates)
        if manual_home is not None:
            return self._manual_result(results, evidence)
        return self._best_auto_result(results, evidence, candidates)

    def _manual_result(
        self,
        results: tuple[CodexLinkAvailability, ...],
        evidence: tuple[CodexInstallEvidence, ...],
    ) -> CodexLinkAvailability:
        if not results:
            return CodexLinkAvailability(
                CodexAvailabilityState.NOT_DETECTED,
                "手动选择的 Codex 数据目录无效",
                self._has_strong_evidence(evidence),
                tuple(item.kind for item in evidence),
                manual_override=True,
                technical_reason="没有可验证的手动目录",
            )
        selected = results[0]
        automatic = tuple(
            self._probe.probe(candidate)
            for candidate in self._home_discovery.candidates(None)
        )
        auto_ready = any(item.state is CodexAvailabilityState.READY for item in automatic)
        reason = selected.technical_reason
        if selected.state is not CodexAvailabilityState.READY and auto_ready:
            reason = (reason + "; " if reason else "") + "自动查找另有可用目录，可恢复自动查找"
        message = (
            "已选择 Codex 数据目录，等待 Codex 创建本地任务"
            if selected.state is CodexAvailabilityState.WAITING_FOR_SESSIONS
            else selected.message
        )
        return replace(
            selected,
            message=message,
            codex_detected=selected.codex_detected or self._has_strong_evidence(evidence),
            evidence=tuple(item.kind for item in evidence),
            manual_override=True,
            technical_reason=reason,
        )

    def _best_auto_result(
        self,
        results: tuple[CodexLinkAvailability, ...],
        evidence: tuple[CodexInstallEvidence, ...],
        candidates: tuple[CodexHomeCandidate, ...],
    ) -> CodexLinkAvailability:
        strong = self._has_strong_evidence(evidence) or any(
            candidate.source == "app-server" for candidate in candidates
        )
        if not results:
            state = CodexAvailabilityState.DATA_ONLY if any(item.kind == "data" for item in evidence) else CodexAvailabilityState.NOT_DETECTED
            message = (
                "发现 Codex 数据，但未确认当前安装"
                if state is CodexAvailabilityState.DATA_ONLY
                else "未检测到 Codex，安装或启动后会自动连接"
            )
            return CodexLinkAvailability(
                state,
                message,
                strong,
                tuple(item.kind for item in evidence),
            )
        selected = max(results, key=lambda item: self._STATE_SCORE[item.state])
        if selected.state is CodexAvailabilityState.WAITING_FOR_SESSIONS and not strong:
            return replace(
                selected,
                state=CodexAvailabilityState.DATA_ONLY,
                message="发现 Codex 数据，但未确认当前安装",
                codex_detected=False,
                evidence=tuple(item.kind for item in evidence),
                can_watch=False,
            )
        if selected.state is CodexAvailabilityState.WAITING_FOR_SESSIONS and strong:
            selected = replace(selected, message="已检测到 Codex，等待创建本地任务")
        return replace(
            selected,
            codex_detected=selected.codex_detected or strong,
            evidence=tuple(item.kind for item in evidence),
        )

    @staticmethod
    def _has_strong_evidence(evidence: tuple[CodexInstallEvidence, ...]) -> bool:
        return any(item.kind in {"desktop", "cli", "configured-home"} for item in evidence)


def normalize_selected_codex_home(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.is_dir():
        raise ValueError("请选择存在的 Codex 数据目录")
    return resolved.parent if resolved.name.casefold() == "sessions" else resolved
```

该模块需要从 `dataclasses` 导入 `replace`。手动结果保留失败原因，并在高级诊断中说明自动模式是否发现其他可用候选。

- [ ] **步骤 4：运行完整发现测试**

运行：`python -m pytest tests/test_codex_discovery.py -q`

预期：PASS，且不读取或断言任何提示词正文。

- [ ] **步骤 5：提交统一发现服务**

```bash
git add src/petnest/core/codex_discovery.py tests/test_codex_discovery.py
git commit -m "feat: select verified Codex log sources"
```

### 任务 4：让 watcher、Hook 和插件安全切换 Codex Home

**文件：**
- 修改：`src/petnest/core/codex_session_log.py:42-99`
- 修改：`src/petnest/core/codex_link.py:247-280`
- 修改：`src/petnest/core/codex_plugin.py:101-130`
- 测试：`tests/test_codex_session_log.py`
- 测试：`tests/test_codex_link.py`
- 测试：`tests/test_codex_plugin.py`

- [ ] **步骤 1：编写重新配置不重放历史和三组件同 Home 的失败测试**

```python
def test_reconfigure_home_stops_old_source_and_baselines_new_history(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    watcher = CodexSessionLogWatcher(first / "sessions", today=lambda: TODAY)
    watcher.start()
    path = _day(second / "sessions") / "rollout-new-home.jsonl"
    path.write_bytes(_meta("session-2") + _event("task_started", "old-turn"))

    watcher.reconfigure(second)

    assert watcher.root == (second / "sessions").resolve()
    assert watcher.poll() == ()
    with path.open("ab") as stream:
        stream.write(_event("task_started", "new-turn"))
    assert watcher.poll()[0].payload["turn_id"] == "new-turn"


def test_managers_switch_only_codex_home_dependent_paths(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    hook = _manager(tmp_path, codex_home=first)
    plugin = _plugin_manager(tmp_path, hook, codex_home=first)

    hook.set_codex_home(second)
    plugin.set_codex_home(second)

    assert hook.codex_home == second.resolve()
    assert hook.hooks_path == second.resolve() / "hooks.json"
    assert plugin.codex_home == second.resolve()
    assert plugin.marketplace_path.parent.name == "plugins"


def test_plugin_receipt_check_is_local_and_does_not_call_codex_cli(tmp_path: Path) -> None:
    cli = FakeCodexCli()
    manager = _manager(tmp_path, cli)

    assert manager.has_install_receipt() is False
    assert cli.calls == []
    manager.install_or_repair()
    calls_after_install = list(cli.calls)

    assert manager.has_install_receipt() is True
    assert cli.calls == calls_after_install
```

- [ ] **步骤 2：运行定向测试确认缺少 reconfigure/setter**

运行：`python -m pytest tests/test_codex_session_log.py tests/test_codex_link.py tests/test_codex_plugin.py -q`

预期：FAIL，提示 `reconfigure` 或 `set_codex_home` 不存在。

- [ ] **步骤 3：实现最小重配接口**

```python
# codex_session_log.py
def reconfigure(self, codex_home: Path) -> None:
    was_running = self._running
    self.stop()
    home = codex_home.expanduser().resolve()
    self.root = home / "sessions"
    self.global_state_path = home / ".codex-global-state.json"
    if was_running:
        self.start()


# codex_link.py / CodexHookManager
def set_codex_home(self, codex_home: Path) -> None:
    resolved = codex_home.expanduser().resolve()
    self.codex_home = resolved
    self.hooks_path = resolved / "hooks.json"


# codex_plugin.py / CodexPluginManager
def set_codex_home(self, codex_home: Path) -> None:
    self.codex_home = codex_home.expanduser().resolve()

def has_install_receipt(self) -> bool:
    try:
        return self._read_receipt() is not None
    except (CodexLinkError, OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
```

保持 marketplace、插件材料和 PetNest metadata 路径不随 Codex Home 移动；只有 Codex 配置/CLI 环境切换。

- [ ] **步骤 4：运行三组件回归**

运行：`python -m pytest tests/test_codex_session_log.py tests/test_codex_link.py tests/test_codex_plugin.py -q`

预期：PASS。

- [ ] **步骤 5：提交重配接口**

```bash
git add src/petnest/core/codex_session_log.py src/petnest/core/codex_link.py src/petnest/core/codex_plugin.py tests/test_codex_session_log.py tests/test_codex_link.py tests/test_codex_plugin.py
git commit -m "feat: reconfigure Codex home safely"
```

### 任务 5：在应用中装配发现、30 秒重试和真实状态

**文件：**
- 修改：`src/petnest/app.py:195-235`
- 修改：`src/petnest/app.py:416-422`
- 修改：`src/petnest/app.py:924-953`
- 修改：`src/petnest/app.py:1470-1532`
- 修改：`tests/conftest.py`
- 测试：`tests/test_app_and_platforms.py`

- [ ] **步骤 1：扩展测试替身并编写启动、重试、ready 后停止扫描测试**

```python
class _CodexLogWatcher:
    def __init__(self) -> None:
        self.started = 0
        self.stopped = 0
        self.events: list[PetEvent] = []
        self.status = CodexLogSourceStatus("stopped", "未启动")
        self.configured_home: Path | None = None

    @property
    def is_running(self) -> bool:
        return self.started > self.stopped

    def reconfigure(self, codex_home: Path) -> None:
        self.configured_home = codex_home.expanduser().resolve()

    def start(self) -> None:
        self.started += 1
        self.status = CodexLogSourceStatus("waiting", "等待新的 Codex 任务")

    def stop(self) -> None:
        self.stopped += 1
        self.status = CodexLogSourceStatus("stopped", "未启动")

    def poll(self) -> tuple[PetEvent, ...]:
        events, self.events = tuple(self.events), []
        return events


class _CodexDiscoveryService:
    def __init__(self, *results: CodexLinkAvailability) -> None:
        self.results = list(results)
        self.calls: list[Path | None] = []

    def discover(self, manual_home: Path | None) -> CodexLinkAvailability:
        self.calls.append(manual_home)
        return self.results.pop(0) if len(self.results) > 1 else self.results[0]


def test_default_link_discovers_then_starts_verified_log_source(qtbot, tmp_path: Path) -> None:
    home = tmp_path / ".codex"
    discovery = _CodexDiscoveryService(
        CodexLinkAvailability(
            CodexAvailabilityState.READY,
            "联动已准备好，等待新的任务",
            True,
            ("app-server",),
            home,
            home / "sessions",
            False,
            True,
        )
    )
    watcher = _CodexLogWatcher()
    application = _application(tmp_path, discovery=discovery, watcher=watcher)

    application.start()

    assert discovery.calls == [None]
    assert watcher.configured_home == home.resolve()
    assert watcher.started == 1
    assert not application.codex_discovery_timer.isActive()
    application.shutdown()


def test_not_detected_retries_without_starting_fast_log_poll(qtbot, tmp_path: Path) -> None:
    discovery = _CodexDiscoveryService(
        CodexLinkAvailability(
            CodexAvailabilityState.NOT_DETECTED,
            "未检测到 Codex，安装或启动后会自动连接",
            False,
        )
    )
    watcher = _CodexLogWatcher()
    application = _application(tmp_path, discovery=discovery, watcher=watcher)

    application.start()

    assert application.codex_discovery_timer.interval() == 30_000
    assert application.codex_discovery_timer.isActive()
    assert watcher.started == 0
    assert application.external_server is None
    application.shutdown()
```

- [ ] **步骤 2：运行应用测试确认 constructor/timer 尚不存在**

运行：`python -m pytest tests/test_app_and_platforms.py -q -k codex`

预期：FAIL，提示 `codex_discovery` 参数或 `codex_discovery_timer` 不存在。

- [ ] **步骤 3：装配发现服务、timer 和运行时配置**

在 `PetNest.__init__` 增加可注入参数：

```python
codex_discovery: CodexDiscoveryService | None = None,
```

创建单次发现结果：

```python
self.codex_availability = CodexLinkAvailability(
    CodexAvailabilityState.DETECTING,
    "正在查找 Codex",
    False,
)
self.codex_discovery_timer = QTimer(self.window)
self.codex_discovery_timer.setInterval(30_000)
self.codex_discovery_timer.timeout.connect(self._refresh_codex_discovery)
```

实现：

```python
def _refresh_codex_discovery(self) -> None:
    if not self.settings.codex_link_enabled:
        self.codex_discovery_timer.stop()
        return
    override = Path(self.settings.codex_home_override) if self.settings.codex_home_override else None
    availability = self.codex_discovery.discover(override)
    self.codex_availability = availability
    if availability.can_watch and availability.selected_home is not None:
        self._apply_codex_home(availability.selected_home)
        self._configure_codex_log_watcher()
    else:
        self.codex_log_timer.stop()
        self.codex_log_watcher.stop()
    if availability.state in {CodexAvailabilityState.READY, CodexAvailabilityState.ACTIVE}:
        self.codex_discovery_timer.stop()
    else:
        self.codex_discovery_timer.start()
    self._refresh_codex_link_runtime_view()


def _apply_codex_home(self, codex_home: Path) -> None:
    resolved = codex_home.expanduser().resolve()
    if self.codex_log_watcher.root.parent != resolved:
        self.codex_log_watcher.reconfigure(resolved)
    self.codex_hook_manager.set_codex_home(resolved)
    self.codex_plugin_manager.set_codex_home(resolved)


def _configure_codex_log_watcher(self) -> None:
    enabled = (
        self.settings.codex_link_enabled
        and self.settings.codex_link_log_fallback_enabled
        and self.codex_availability.can_watch
    )
    if enabled:
        if not self.codex_log_watcher.is_running:
            self.codex_log_watcher.start()
        self.codex_log_timer.start()
    else:
        self.codex_log_timer.stop()
        if self.codex_log_watcher.is_running:
            self.codex_log_watcher.stop()


def _configure_external_event_server(self, *, restart: bool = False) -> None:
    precise_source_configured = (
        self.codex_hook_status.installed
        or self.codex_plugin_manager.has_install_receipt()
    )
    needed = self.settings.external_event_server_enabled or (
        self.settings.codex_link_enabled and precise_source_configured
    )
    if self.external_server is not None and (restart or not needed):
        server, self.external_server = self.external_server, None
        server.stop()
    if needed and self.external_server is None:
        self._start_external_server()
```

在 `_configure_codex_plugin()` 成功产生安装收据后调用 `_configure_external_event_server()`；停用插件后再次调用，使未被其他功能使用的端口服务停止。基础 JSONL 联动不依赖该端口。

测试隔离写入 `tests/conftest.py`：

```python
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolate_codex_home_from_real_user(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "isolated-codex-home"))
```

显式测试 `CODEX_HOME` 的用例可在测试体内再次 `monkeypatch.setenv` 覆盖该值。

`WAITING_FOR_SESSIONS` 允许启动 watcher，使新创建的首个会话文件从 offset 0 被捕获；`NOT_DETECTED/UNREADABLE/INCOMPATIBLE` 不启动 250ms 日志轮询。关闭联动时同时停止两个 timer 和 watcher。

- [ ] **步骤 4：运行 Codex 应用测试**

运行：`python -m pytest tests/test_app_and_platforms.py -q -k codex`

预期：PASS。

- [ ] **步骤 5：提交应用装配**

```bash
git add src/petnest/app.py tests/test_app_and_platforms.py
git commit -m "feat: orchestrate Codex discovery states"
```

### 任务 6：默认允许联动并安全迁移手动目录设置

**文件：**
- 修改：`src/petnest/models/settings.py:35-124`
- 修改：`src/petnest/core/settings_manager.py:209-218`
- 测试：`tests/test_settings_manager.py:236-293`

- [ ] **步骤 1：编写新用户默认开启、显式关闭保留和 schema 迁移测试**

```python
def test_new_users_allow_codex_link_without_installing_plugin(tmp_path: Path) -> None:
    settings = SettingsManager(tmp_path / "settings.json").load()

    assert settings.codex_link_enabled is True
    assert settings.codex_home_override is None


def test_schema_25_preserves_explicitly_disabled_link_and_adds_auto_home(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps({"schema_version": 25, "codex_link_enabled": False}),
        encoding="utf-8",
    )

    loaded = SettingsManager(path).load()

    assert loaded.schema_version == 26
    assert loaded.codex_link_enabled is False
    assert loaded.codex_home_override is None


def test_preference_missing_in_old_schema_uses_new_enabled_default(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"schema_version": 23}), encoding="utf-8")

    loaded = SettingsManager(path).load()

    assert loaded.codex_link_enabled is True


def test_codex_home_override_round_trips_and_rejects_non_strings(tmp_path: Path) -> None:
    manager = SettingsManager(tmp_path / "settings.json")
    manager.save(Settings(codex_home_override="D:/CodexProfile"))
    assert manager.load().codex_home_override == "D:/CodexProfile"
    assert Settings.from_dict({"codex_home_override": ["bad"]}).codex_home_override is None
```

- [ ] **步骤 2：运行设置测试并确认旧默认/旧 schema 断言失败**

运行：`python -m pytest tests/test_settings_manager.py -q`

预期：FAIL，实际默认仍为 `False`，schema 仍为 25。

- [ ] **步骤 3：实现 schema 26 和逐版本迁移**

```python
# settings.py
SCHEMA_VERSION = 26
codex_link_enabled: bool = True
codex_link_show_attention_bubbles: bool = True
codex_link_show_review_bubbles: bool = True
codex_link_log_fallback_enabled: bool = True
codex_home_override: str | None = None
```

`from_dict` 使用 `("codex_link_enabled", True)` 归一化非法布尔，并把非空字符串以外的 `codex_home_override` 归一化为 `None`。

```python
# settings_manager.py
if version == 23:
    migrated.setdefault("codex_link_enabled", True)
    migrated.setdefault("codex_link_show_attention_bubbles", True)
    migrated.setdefault("codex_link_show_review_bubbles", True)
    migrated["schema_version"] = 24
    version = 24
if version == 24:
    migrated.setdefault("codex_link_log_fallback_enabled", True)
    migrated["schema_version"] = 25
    version = 25
if version == 25:
    migrated.setdefault("codex_home_override", None)
    migrated["schema_version"] = Settings.SCHEMA_VERSION
```

- [ ] **步骤 4：运行设置回归**

运行：`python -m pytest tests/test_settings_manager.py -q`

预期：PASS。

- [ ] **步骤 5：提交默认值与迁移**

```bash
git add src/petnest/models/settings.py src/petnest/core/settings_manager.py tests/test_settings_manager.py
git commit -m "feat: enable Codex link for new users"
```

### 任务 7：设置页展示真实状态并允许选择数据目录

**文件：**
- 修改：`src/petnest/ui/settings_center_dialog.py:264-317`
- 修改：`src/petnest/ui/settings_center_dialog.py:797-1050`
- 修改：`src/petnest/app.py:1020-1095`
- 测试：`tests/test_settings_dialog.py:39-220`
- 测试：`tests/test_app_and_platforms.py`

- [ ] **步骤 1：编写状态文案、失败入口、手动选择和恢复自动测试**

```python
def _availability(
    state: CodexAvailabilityState,
    *,
    home: Path | None = None,
    manual: bool = False,
) -> CodexLinkAvailability:
    messages = {
        CodexAvailabilityState.NOT_DETECTED: "未检测到 Codex，安装或启动后会自动连接",
        CodexAvailabilityState.READY: "联动已准备好，等待新的任务",
    }
    return CodexLinkAvailability(
        state=state,
        message=messages[state],
        codex_detected=state is CodexAvailabilityState.READY,
        selected_home=home,
        sessions_path=home / "sessions" if home is not None else None,
        manual_override=manual,
        can_watch=state is CodexAvailabilityState.READY,
    )


def _not_detected() -> CodexLinkAvailability:
    return _availability(CodexAvailabilityState.NOT_DETECTED)


def _ready(home: Path | None) -> CodexLinkAvailability:
    assert home is not None
    return _availability(CodexAvailabilityState.READY, home=home, manual=True)


def test_codex_page_shows_not_detected_without_claiming_link_is_normal(qtbot) -> None:
    availability = CodexLinkAvailability(
        CodexAvailabilityState.NOT_DETECTED,
        "未检测到 Codex，安装或启动后会自动连接",
        False,
    )
    dialog = SettingsDialog(
        Settings(codex_link_enabled=True),
        codex_availability=availability,
        initial_section="codex_link",
    )
    qtbot.addWidget(dialog)

    assert dialog.codex_link_runtime_label.text() == availability.message
    assert "联动正常" not in dialog.codex_link_runtime_label.text()
    assert not dialog.codex_choose_home_button.isHidden()


def test_codex_page_hides_manual_choice_in_ready_main_flow(qtbot) -> None:
    availability = _availability(CodexAvailabilityState.READY, home=Path("D:/Codex"))
    dialog = SettingsDialog(Settings(), codex_availability=availability, initial_section="codex_link")
    qtbot.addWidget(dialog)

    assert dialog.codex_choose_home_button.isHidden()
    dialog.codex_advanced_details_button.click()
    assert not dialog.codex_reselect_home_button.isHidden()


def test_selecting_sessions_folder_passes_normalized_home_to_callback(qtbot, tmp_path, monkeypatch) -> None:
    selected = tmp_path / ".codex" / "sessions"
    selected.mkdir(parents=True)
    calls: list[Path | None] = []
    monkeypatch.setattr(
        "petnest.ui.settings_center_dialog.QFileDialog.getExistingDirectory",
        lambda *_args, **_kwargs: str(selected),
    )
    dialog = SettingsDialog(
        Settings(),
        codex_availability=_not_detected(),
        on_set_codex_home_override=lambda home: calls.append(home) or _ready(home),
        initial_section="codex_link",
    )
    qtbot.addWidget(dialog)

    qtbot.mouseClick(dialog.codex_choose_home_button, Qt.MouseButton.LeftButton)

    assert calls == [selected.parent.resolve()]
```

- [ ] **步骤 2：运行设置页测试确认新参数和按钮不存在**

运行：`python -m pytest tests/test_settings_dialog.py -q -k codex`

预期：FAIL，提示 `codex_availability` 或 `codex_choose_home_button` 不存在。

- [ ] **步骤 3：实现可用性参数、状态映射和目录选择**

在 dialog 构造器增加：

```python
codex_availability: CodexLinkAvailability | None = None,
on_set_codex_home_override: Callable[[Path | None], CodexLinkAvailability] | None = None,
```

主卡：

- `NOT_DETECTED/DATA_ONLY/UNREADABLE/INCOMPATIBLE` 显示“选择 Codex 数据目录”；
- `READY/ACTIVE/WAITING_FOR_SESSIONS` 隐藏主卡选择按钮；
- `running/waiting/failed/review` 继续优先于可用性文案；
- 不再把旧 `codex_link_source == "waiting"` 映射为“联动正常”。

高级详情：

- 当前 Codex Home、sessions、证据和技术原因；
- “重新选择…”调用 `QFileDialog.getExistingDirectory`；
- 手动模式显示“恢复自动查找”；
- 自动模式隐藏或禁用恢复按钮。

应用 callback：

```python
def _set_codex_home_override(self, home: Path | None) -> CodexLinkAvailability:
    self.settings = replace(
        self.settings,
        codex_home_override=str(home) if home is not None else None,
    )
    self.settings_manager.save(self.settings)
    self._refresh_codex_discovery()
    return self.codex_availability
```

- [ ] **步骤 4：运行设置页和应用设置测试**

运行：`python -m pytest tests/test_settings_dialog.py tests/test_app_and_platforms.py -q -k codex`

预期：PASS。

- [ ] **步骤 5：提交用户状态与手动选择**

```bash
git add src/petnest/ui/settings_center_dialog.py src/petnest/app.py tests/test_settings_dialog.py tests/test_app_and_platforms.py
git commit -m "feat: guide Codex log source selection"
```

### 任务 8：补齐端到端状态、隐私和精确连接回退

**文件：**
- 修改：`src/petnest/app.py`
- 修改：`src/petnest/ui/settings_center_dialog.py`
- 测试：`tests/test_app_and_platforms.py`
- 测试：`tests/test_codex_session_log.py`
- 测试：`tests/test_settings_dialog.py`

- [ ] **步骤 1：编写 ready→running→review、无 Codex 静默和不兼容不猜测测试**

```python
def _log_event(event_name: str) -> PetEvent:
    return PetEvent(
        "codex.hook",
        source="codex-log",
        payload={
            "hook_event_name": event_name,
            "session_id": "session-1",
            "turn_id": "turn-1",
        },
    )


def _application_with_availability(
    tmp_path: Path,
    availability: CodexLinkAvailability,
) -> tuple[PetNest, _CodexLogWatcher]:
    settings_manager = SettingsManager(tmp_path / "settings.json")
    settings_manager.save(Settings(codex_link_enabled=True, work_countdown_enabled=False))
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    watcher = _CodexLogWatcher()
    application = PetNest(
        pets_root=tmp_path / "pets",
        settings_manager=settings_manager,
        codex_discovery=_CodexDiscoveryService(availability),
        codex_log_watcher=watcher,
        enable_tray=False,
    )
    return application, watcher


def _ready_application(tmp_path: Path) -> tuple[PetNest, _CodexLogWatcher]:
    home = tmp_path / ".codex"
    return _application_with_availability(
        tmp_path,
        CodexLinkAvailability(
            CodexAvailabilityState.READY,
            "联动已准备好，等待新的任务",
            True,
            ("app-server",),
            home,
            home / "sessions",
            False,
            True,
        ),
    )


def _not_detected_application(tmp_path: Path) -> PetNest:
    application, _watcher = _application_with_availability(
        tmp_path,
        CodexLinkAvailability(
            CodexAvailabilityState.NOT_DETECTED,
            "未检测到 Codex，安装或启动后会自动连接",
            False,
        ),
    )
    return application


def test_discovery_and_log_events_drive_plain_runtime_states(qtbot, tmp_path: Path) -> None:
    application, watcher = _ready_application(tmp_path)
    application.start()
    application._show_settings_center("codex_link")
    dialog = application._settings_center_dialog
    assert dialog is not None
    assert dialog.codex_link_runtime_label.text() == "联动已准备好，等待新的任务"

    watcher.events.append(_log_event("UserPromptSubmit"))
    application._poll_codex_logs()
    assert dialog.codex_link_runtime_label.text() == "Codex 正在工作"

    watcher.events.append(_log_event("Stop"))
    application._poll_codex_logs()
    assert dialog.codex_link_runtime_label.text() == "任务已完成"
    application.shutdown()


def test_default_enabled_without_codex_shows_no_bubble(qtbot, tmp_path: Path) -> None:
    application = _not_detected_application(tmp_path)
    application.start()

    assert application.settings.codex_link_enabled is True
    assert application.window.codex_status_text is None
    assert application.codex_discovery_timer.isActive()
    application.shutdown()


def test_incompatible_log_never_publishes_guessed_pet_state(tmp_path: Path) -> None:
    watcher = CodexSessionLogWatcher(tmp_path / "sessions", today=lambda: TODAY)
    watcher.start()
    path = _day(tmp_path / "sessions") / "rollout-bad.jsonl"
    path.write_text('{"type":"event_msg","payload":{"type":"task_started"}}\n', encoding="utf-8")

    assert watcher.poll() == ()
    assert watcher.status.state == "incompatible"
```

- [ ] **步骤 2：运行端到端测试，确认旧状态映射或兼容判定失败**

运行：`python -m pytest tests/test_app_and_platforms.py tests/test_codex_session_log.py tests/test_settings_dialog.py -q -k codex`

预期：至少一项 FAIL；旧实现可能把 waiting 显示为“联动正常”或保持 waiting 而不报告不兼容。

- [ ] **步骤 3：收敛最终状态优先级和诊断**

实现状态优先级：

```python
TASK_STATUS_TEXT = {
    "running": "Codex 正在工作",
    "waiting": "需要你处理",
    "failed": "执行遇到问题",
    "review": "任务已完成",
}

def _plain_codex_status(task_state: str, availability: CodexLinkAvailability) -> str:
    if task_state in TASK_STATUS_TEXT:
        return TASK_STATUS_TEXT[task_state]
    return availability.message
```

当日志 watcher 收到首条真实事件时，将 availability 从 `READY` 更新为 `ACTIVE`；插件事件仍把 `codex_link_source` 升级为 `hook`。`UNREADABLE/INCOMPATIBLE` 页面推荐精确连接，但不自动点击或安装。诊断只输出 evidence kind、路径、状态和 bounded reason。

验收要求：插件失败不停止基础发现或已经可用的日志监听；插件状态与基础 availability 分别保存和展示。

- [ ] **步骤 4：运行全部 Codex 定向测试**

运行：

```bash
python -m pytest tests/test_codex_discovery.py tests/test_codex_session_log.py tests/test_codex_link.py tests/test_codex_plugin.py tests/test_settings_manager.py tests/test_settings_dialog.py tests/test_app_and_platforms.py -q
```

预期：PASS；平台不支持的符号链接测试可按既有条件 SKIP。

- [ ] **步骤 5：提交端到端收敛**

```bash
git add src/petnest/app.py src/petnest/core/codex_session_log.py src/petnest/ui/settings_center_dialog.py tests/test_app_and_platforms.py tests/test_codex_session_log.py tests/test_settings_dialog.py
git commit -m "fix: report real Codex linkage state"
```

### 任务 9：完成审查、跨平台验证和集成

**文件：**
- 验证：`src/petnest/core/codex_discovery.py`
- 验证：`assets/codex-plugins/petnest-status-link`
- 验证：全部 `tests/`

- [ ] **步骤 1：运行插件 validator**

Windows 当前环境运行：

```bash
C:\Users\pc\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe C:\Users\pc\.codex\skills\.system\plugin-creator\scripts\validate_plugin.py assets\codex-plugins\petnest-status-link
```

预期：`Plugin validation passed`。

- [ ] **步骤 2：运行编译和 diff 检查**

```bash
python -m compileall -q src/petnest
git diff --check
```

预期：两条命令退出码均为 0。

- [ ] **步骤 3：运行完整测试**

运行：`python -m pytest -q`

预期：0 failed；只有当前平台无法创建符号链接/junction 的既有测试允许 SKIP。

- [ ] **步骤 4：请求代码审查并修复 Critical/Important 问题**

审查范围必须包含：

- 手动目录是否可能跨边界写入或删除；
- 多候选是否错误选择第一个存在的旧目录；
- 默认开启是否覆盖现有显式 `false`；
- macOS 发现是否错误依赖 Windows 路径；
- 不兼容日志是否会猜测任务状态；
- 发现定时器和 250ms watcher 是否会重复启动或退出后残留；
- 精确插件失败是否仍保留基础发现。

- [ ] **步骤 5：在 Windows 主分支运行实机验证**

1. 启动 PetNest；
2. 确认发现当前 `C:\Users\pc\.codex`；
3. 新建 Codex 任务，确认 working；
4. 任务完成，确认 review；
5. 打开任务，确认待查看清除；
6. 临时指定另一个测试 Codex Home，确认不重放历史；
7. 恢复自动查找；
8. 关闭联动，确认两个 timer 和 watcher 停止。

- [ ] **步骤 6：执行 macOS 发布前验证或明确记录阻塞**

在可用 Mac 上执行：

```bash
python -m pytest tests/test_codex_discovery.py tests/test_codex_session_log.py -q
```

然后用当前 Codex Desktop 创建真实任务，记录 app-server `codexHome`、实际 sessions 路径、working、review 和已读清除结果。若当前没有 Mac 主机，提交可以完成，但发布说明必须明确“macOS 真实 Codex 日志联动尚待实机验证”，不得声称已验证。

- [ ] **步骤 7：提交审查修复并准备集成**

```bash
git add src tests docs/superpowers/specs/2026-08-21-codex-auto-discovery-and-default-link-design.md docs/superpowers/plans/2026-08-21-codex-auto-discovery-and-default-link.md
git commit -m "test: verify Codex auto discovery"
```

确认 `git status --short` 中只有用户原有的无关改动，然后将本功能提交集成到实际 `main`，重启 PetNest 并再次确认 `127.0.0.1:18486` 正常监听。
