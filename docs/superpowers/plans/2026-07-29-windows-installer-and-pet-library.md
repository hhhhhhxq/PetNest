# Windows 安装包与宠物库实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 生成可安装的 Windows 发行包，并让用户可在安装时选择程序目录与可选的宠物库目录。

**架构：** `Settings.pets_root` 保存安装器选定的自定义宠物库。冻结应用在没有显式测试目录时使用用户可写目录；当库为空时从随包的 `pets/` 原子复制有效宠物包。Inno Setup 的高级页调用 `PetNest.exe --set-pets-root`，不直接篡改设置 JSON。

**技术栈：** Python 3.12、PySide6、PyInstaller、Inno Setup、pytest。

---

## 文件结构

- 创建：`src/petnest/core/pet_library.py` — 解析用户宠物库并首次复制内置宠物。
- 修改：`src/petnest/models/settings.py`、`src/petnest/core/settings_manager.py` — 保存 `pets_root`。
- 修改：`src/petnest/app.py`、`src/petnest/__main__.py` — 启动时选择库、支持安装器 CLI。
- 创建：`installer/PetNest.iss` — 安装位置页和可选高级宠物库页。
- 修改：`build_windows.bat`、`requirements-dev.txt`、`README.md` — 可重复构建 Windows 安装包。
- 创建：`tests/test_pet_library.py`；修改 `tests/test_settings_manager.py`、`tests/test_app_and_platforms.py`。

### 任务 1：可写宠物库与首次复制

**文件：**
- 创建：`src/petnest/core/pet_library.py`
- 测试：`tests/test_pet_library.py`

- [x] **步骤 1：编写失败测试**

```python
def test_bootstrap_copies_only_valid_bundled_pet_packages_when_library_is_empty(tmp_path):
    source = _source_with_valid_sample_pet(tmp_path / "bundled")
    target = tmp_path / "user-pets"

    active = prepare_pet_library(target, source)

    assert active == target
    assert (target / "sample_pet" / "pet.json").exists()
```

- [x] **步骤 2：运行失败测试**

运行：`C:\Python312\python.exe -m pytest tests/test_pet_library.py::test_bootstrap_copies_only_valid_bundled_pet_packages_when_library_is_empty -q`

预期：FAIL，提示 `pet_library` 模块不存在。

- [x] **步骤 3：实现最少逻辑**

```python
def prepare_pet_library(target: Path, bundled: Path) -> Path:
    target.mkdir(parents=True, exist_ok=True)
    if PackageLoader().discover(target):
        return target
    for package in PackageLoader().discover(bundled):
        shutil.copytree(package.root, target / package.root.name, dirs_exist_ok=False)
    if not PackageLoader().discover(target):
        raise PetLibraryError("宠物库为空，且无法复制内置示例宠物")
    return target
```

- [x] **步骤 4：运行测试验证通过**

运行：`C:\Python312\python.exe -m pytest tests/test_pet_library.py -q`

预期：PASS。

### 任务 2：设置与安装器 CLI

**文件：**
- 修改：`src/petnest/models/settings.py`
- 修改：`src/petnest/__main__.py`
- 测试：`tests/test_settings_manager.py`

- [x] **步骤 1：编写失败测试**

```python
def test_set_pets_root_command_persists_an_absolute_custom_library(tmp_path, monkeypatch):
    monkeypatch.setattr(SettingsManager, "default_path", lambda: tmp_path / "settings.json")

    assert main(["--set-pets-root", str(tmp_path / "D" / "PetNestPets")]) == 0
    assert SettingsManager(tmp_path / "settings.json").load().pets_root == str((tmp_path / "D" / "PetNestPets").resolve())
```

- [x] **步骤 2：运行失败测试**

运行：`C:\Python312\python.exe -m pytest tests/test_settings_manager.py::test_set_pets_root_command_persists_an_absolute_custom_library -q`

预期：FAIL，命令行参数尚不存在。

- [x] **步骤 3：实现最少逻辑**

```python
parser.add_argument("--set-pets-root", type=Path)
if args.set_pets_root:
    root = args.set_pets_root.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    settings = SettingsManager().load()
    SettingsManager().save(replace(settings, pets_root=str(root)))
    return 0
```

- [x] **步骤 4：运行测试验证通过**

运行：`C:\Python312\python.exe -m pytest tests/test_settings_manager.py -q`

预期：PASS。

### 任务 3：冻结版启动时使用用户库

**文件：**
- 修改：`src/petnest/app.py`
- 测试：`tests/test_app_and_platforms.py`

- [x] **步骤 1：编写失败测试**

```python
def test_frozen_application_uses_custom_library_and_bootstraps_sample(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr("petnest.app.bundled_pets_directory", lambda: _bundled_sample(tmp_path))
    settings = Settings(pets_root=str(tmp_path / "custom-pets"))

    app = PetNest(settings_manager=_saved_settings(tmp_path, settings), enable_tray=False)

    assert app.pets_root == tmp_path / "custom-pets"
    assert app.package.identifier == "sample_pet"
```

- [x] **步骤 2：运行失败测试**

运行：`C:\Python312\python.exe -m pytest tests/test_app_and_platforms.py::test_frozen_application_uses_custom_library_and_bootstraps_sample -q`

预期：FAIL，应用仍直接读取内置 `pets/`。

- [x] **步骤 3：实现最少逻辑**

```python
if pets_root is not None:
    self.pets_root = pets_root
elif getattr(sys, "frozen", False):
    requested = Path(self.settings.pets_root) if self.settings.pets_root else default_user_pets_directory()
    self.pets_root = prepare_pet_library(requested, bundled_pets_directory())
else:
    self.pets_root = bundled_pets_directory()
```

- [x] **步骤 4：运行测试验证通过**

运行：`C:\Python312\python.exe -m pytest tests/test_app_and_platforms.py -q`

预期：PASS。

### 任务 4：构建与安装器

**文件：**
- 创建：`installer/PetNest.iss`
- 修改：`build_windows.bat`、`requirements-dev.txt`、`README.md`

- [x] **步骤 1：编写静态检查测试**

```python
def test_installer_includes_default_pets_and_custom_library_advanced_page():
    contents = Path("installer/PetNest.iss").read_text(encoding="utf-8")

    assert "Source: \"dist\\PetNest\\*\"" in contents
    assert "将宠物库保存到自定义位置" in contents
    assert "--set-pets-root" in contents
```

- [x] **步骤 2：运行失败测试**

运行：`C:\Python312\python.exe -m pytest tests/test_installer_script.py -q`

预期：FAIL，安装脚本不存在。

- [x] **步骤 3：实现构建脚本与 Inno Setup 脚本**

```ini
[Files]
Source: "dist\PetNest\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Run]
Filename: "{app}\PetNest.exe"; Parameters: "--set-pets-root ""{code:GetPetsRoot}"""; Flags: runhidden; Check: UseCustomPetsRoot
```

- [x] **步骤 4：运行安装脚本静态测试与 PyInstaller 构建**

运行：`C:\Python312\python.exe -m pytest tests/test_installer_script.py -q`，再运行 `build_windows.bat`。

预期：静态测试 PASS，生成 `dist\PetNest`；若本机未安装 Inno Setup，构建脚本明确提示其官方下载地址并停止在生成安装器前。

- [x] **步骤 5：全量验证与提交**

运行：`C:\Python312\python.exe -m pytest -q`；`C:\Python312\python.exe -m petnest --check`。

预期：全部通过，Windows 符号链接测试可保留既有跳过。

```powershell
git add src tests installer build_windows.bat requirements-dev.txt README.md
git commit -m "feat: add Windows installer and writable pet library"
```
