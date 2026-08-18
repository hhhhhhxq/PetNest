# 正在使用的宠物动作安全更新实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 让当前正在运行的宠物可以安全导入动作，并彻底消除提交失败时误删整个宠物目录的风险。

**架构：** 通用 `PackageTransaction` 以显式状态区分“备份路径已生成”和“原目录已移动”。动作导入不再提交整个候选宠物目录，而是先把动作写入不可变的 `.revisions` 子目录，验证合并配置后仅原子替换 `pet.json`；应用重载成功后清理旧动作，失败则恢复旧配置。

**技术栈：** Python 3.12、`pathlib`、`tempfile`、`os.replace`、PySide6、pytest、pytest-qt。

---

## 文件结构

- 修改 `src/petnest/core/package_transaction.py`：修正整包事务的提交状态和恢复错误报告。
- 修改 `tests/test_package_transaction.py`：覆盖第一次改名失败、候选提交失败和二次恢复失败。
- 修改 `src/petnest/core/action_installer.py`：实现动作修订目录、候选包校验、配置原子提交、回滚和延迟清理。
- 修改 `tests/test_action_installer.py`：覆盖热更新、失败不变性、路径安全、回滚与清理。
- 修改 `src/petnest/app.py`：当前宠物重载失败时调用动作安装回滚，成功后再清理旧资源。
- 修改 `tests/test_pet_action_exchange_app.py`：覆盖当前宠物成功、重载失败恢复和非当前宠物清理。

### 任务 1：修复通用目录事务误删原目录

**文件：**
- 修改：`src/petnest/core/package_transaction.py:71-89`
- 测试：`tests/test_package_transaction.py`

- [ ] **步骤 1：编写第一次改名失败的回归测试**

```python
def test_first_rename_failure_keeps_original_target(tmp_path, monkeypatch):
    target = tmp_path / "pet"
    target.mkdir()
    (target / "pet.json").write_bytes(b"before")
    original_rename = Path.rename

    def fail_original_move(path: Path, destination: Path):
        if path == target:
            raise PermissionError("locked")
        return original_rename(path, destination)

    monkeypatch.setattr(Path, "rename", fail_original_move)
    with pytest.raises(PackageTransactionError, match="原目录未改动"):
        with PackageTransaction(target, lambda _: None) as transaction:
            transaction.candidate.joinpath("pet.json").write_bytes(b"after")
            transaction.commit()

    assert target.joinpath("pet.json").read_bytes() == b"before"
```

- [ ] **步骤 2：运行测试并确认它因原目录被删除而失败**

运行：`.venv\Scripts\python.exe -m pytest tests/test_package_transaction.py::test_first_rename_failure_keeps_original_target -q`

预期：FAIL，`target/pet.json` 不再存在，证明测试捕获现有缺陷。

- [ ] **步骤 3：实现显式移动状态和准确错误信息**

```python
original_moved = False
try:
    if self.target.exists():
        backup = self.target.parent / f".{self.target.name}.rollback-{uuid4().hex}"
        self.target.rename(backup)
        original_moved = True
        self._backup = backup
    candidate.rename(self.target)
except Exception as error:
    if not original_moved:
        raise PackageTransactionError(f"原子切换失败，原目录未改动：{error}") from error
    # 只在原目录确实移动后恢复 backup；恢复失败时保留并报告 backup 路径。
```

- [ ] **步骤 4：补充候选提交失败和恢复失败测试**

测试必须断言：候选改名失败会恢复 `before`；备份恢复也失败时错误包含 `.rollback-` 路径且不包含“已恢复原目录”。

- [ ] **步骤 5：运行事务测试**

运行：`.venv\Scripts\python.exe -m pytest tests/test_package_transaction.py -q`

预期：全部 PASS。

- [ ] **步骤 6：提交任务 1**

```powershell
git add -- src/petnest/core/package_transaction.py tests/test_package_transaction.py
git commit -m "fix: preserve pet directory when transaction commit fails"
```

### 任务 2：把动作安装改为版本化资源和配置单点提交

**文件：**
- 修改：`src/petnest/core/action_installer.py`
- 测试：`tests/test_action_installer.py`

- [ ] **步骤 1：编写热更新行为测试**

```python
def test_install_replaces_action_without_renaming_pet_root(tmp_path, monkeypatch):
    target = tmp_path / "target"
    write_pet(target)
    old_action = target / "animations" / "walk"
    original_rename = Path.rename

    def reject_root_rename(path: Path, destination: Path):
        if path == target:
            raise AssertionError("动作安装不得改名宠物根目录")
        return original_rename(path, destination)

    monkeypatch.setattr(Path, "rename", reject_root_rename)
    result = install_actions(target, build_pack(tmp_path))
    config = json.loads((target / "pet.json").read_text(encoding="utf-8"))

    assert config["animations"]["walk"]["path"].startswith("animations/.revisions/walk-")
    assert old_action.is_dir()
    assert result.created_revision_dirs
```

- [ ] **步骤 2：运行测试并确认现有整目录提交触发断言**

运行：`.venv\Scripts\python.exe -m pytest tests/test_action_installer.py::test_install_replaces_action_without_renaming_pet_root -q`

预期：FAIL，现有 `PackageTransaction.commit()` 尝试改名 `target`。

- [ ] **步骤 3：扩展安装结果为可恢复收据**

```python
@dataclass(frozen=True, slots=True)
class InstallResult:
    target_root: Path
    installed: tuple[str, ...]
    skipped: tuple[str, ...]
    renamed: dict[str, str]
    original_config: bytes = field(repr=False)
    created_revision_dirs: tuple[Path, ...]
    superseded_dirs: tuple[Path, ...]

    def rollback(self) -> tuple[str, ...]: ...
    def finalize(self) -> tuple[str, ...]: ...
```

`rollback()` 必须先原子恢复旧配置，再尽力删除新修订目录；恢复配置失败时保留新资源并抛出 `ActionInstallError`。`finalize()` 只删除当前配置不再引用、位于 `target_root/animations` 之下且不是符号链接的旧目录，并把清理失败作为警告字符串返回。

- [ ] **步骤 4：实现修订目录暂存**

为每个实际安装计划生成 `animations/.revisions/<safe-name>-<uuid>`。复制前确保 `target_root`、`animations` 和 `.revisions` 都不是符号链接；目标修订路径必须严格位于 `.revisions` 下。安装过程中不删除已有动作目录。

- [ ] **步骤 5：实现候选配置校验和原子提交**

```python
original_config = config_path.read_bytes()
created = _stage_revisions(target, plans, candidate_animations, renamed)
try:
    _validate_candidate(target, candidate_config)
    _replace_config_atomically(config_path, candidate_config)
except Exception:
    _cleanup_created_revisions(created)
    raise
```

`_validate_candidate()` 在宠物目录同级临时目录复制包内容但忽略真实 `pet.json`，写入候选配置并调用 `PackageValidator`。`_replace_config_atomically()` 在 `pet.json` 同目录写临时文件、`flush()`、`fsync()` 后调用 `os.replace()`。

- [ ] **步骤 6：补充失败与边界测试**

新增测试断言：

- 候选校验失败时旧配置、旧动作和修订目录集合不变；
- `os.replace()` 失败时旧配置字节不变且本次修订被清理；
- `rollback()` 恢复旧配置，`finalize()` 只在新配置仍生效时删除旧目录；
- 共享旧目录仍被其他动作引用时不得删除；
- 绝对路径、盘符路径、目录逃逸和符号链接永远不进入清理函数。

- [ ] **步骤 7：运行动作安装测试**

运行：`.venv\Scripts\python.exe -m pytest tests/test_action_installer.py tests/test_action_pack.py tests/test_pet_action_exchange_flow.py -q`

预期：全部 PASS。

- [ ] **步骤 8：提交任务 2**

```powershell
git add -- src/petnest/core/action_installer.py tests/test_action_installer.py
git commit -m "fix: install actions without replacing live pet directory"
```

### 任务 3：应用层在重载后完成提交或回滚

**文件：**
- 修改：`src/petnest/app.py:882-890`
- 测试：`tests/test_pet_action_exchange_app.py`

- [ ] **步骤 1：编写当前宠物重载失败测试**

```python
def test_action_install_handler_rolls_back_when_current_pet_reload_fails(...):
    calls = []
    result = SimpleNamespace(
        rollback=lambda: calls.append("rollback"),
        finalize=lambda: calls.append("finalize"),
    )
    reload_results = iter((False, True))
    monkeypatch.setattr(application, "reload_current_pet", lambda: next(reload_results))

    application._handle_actions_exchange_installed(application.package.identifier, result)

    assert calls == ["rollback"]
```

- [ ] **步骤 2：运行测试并确认现有处理器没有调用回滚**

运行：`.venv\Scripts\python.exe -m pytest tests/test_pet_action_exchange_app.py::test_action_install_handler_rolls_back_when_current_pet_reload_fails -q`

预期：FAIL，`calls` 为空。

- [ ] **步骤 3：实现当前宠物提交协调**

```python
if identifier == self.package.identifier:
    if self.reload_current_pet():
        warnings = _finalize_action_install(result)
    else:
        _rollback_action_install(result)
        self.packages = self.loader.discover(self.pets_root)
        restored = self.reload_current_pet()
else:
    warnings = _finalize_action_install(result)
```

回滚或第二次重载失败时使用 `QMessageBox.critical` 明确提示；成功恢复时使用 warning 说明导入未生效但旧宠物已恢复。清理警告只写日志，不把已成功更新改判为失败。

- [ ] **步骤 4：补充成功和非当前宠物测试**

断言当前宠物重载成功后调用 `finalize()`；非当前宠物不调用 `reload_current_pet()` 且调用 `finalize()`；回滚自身失败时不调用 `finalize()` 并显示严重错误。

- [ ] **步骤 5：运行应用集成测试**

运行：`.venv\Scripts\python.exe -m pytest tests/test_pet_action_exchange_app.py tests/test_action_import_page.py tests/test_pet_action_exchange_dialog.py -q`

预期：全部 PASS。

- [ ] **步骤 6：提交任务 3**

```powershell
git add -- src/petnest/app.py tests/test_pet_action_exchange_app.py
git commit -m "fix: roll back live action update when reload fails"
```

### 任务 4：完整验证与安全审查

**文件：**
- 检查：`src/petnest/core/package_transaction.py`
- 检查：`src/petnest/core/action_installer.py`
- 检查：`src/petnest/app.py`
- 检查：本计划涉及的全部测试文件

- [ ] **步骤 1：运行针对性测试集合**

运行：

```powershell
.venv\Scripts\python.exe -m pytest tests/test_package_transaction.py tests/test_action_installer.py tests/test_action_pack.py tests/test_pet_action_exchange_flow.py tests/test_pet_action_exchange_app.py tests/test_action_import_page.py tests/test_pet_action_exchange_dialog.py -q
```

预期：全部 PASS。

- [ ] **步骤 2：运行完整测试套件**

运行：`.venv\Scripts\python.exe -m pytest -q`

预期：零失败；仅保留与 Windows 符号链接权限相关的既有 skip。

- [ ] **步骤 3：执行静态差异检查**

运行：

```powershell
git diff --check
git status --short
git diff --stat HEAD~3..HEAD
```

确认没有空白错误，没有纳入用户未跟踪素材，变更范围与规格一致。

- [ ] **步骤 4：按验收标准复核**

逐项确认：动作安装不改名宠物根目录；首次目录改名失败不删除原目录；当前宠物重载失败恢复旧配置；旧资源只在重载成功后安全清理。
