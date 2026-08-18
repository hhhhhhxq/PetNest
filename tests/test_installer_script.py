"""Windows 安装脚本的发布关键项检查。"""

from pathlib import Path


def test_installer_writes_the_sample_pet_directly_to_the_selected_library() -> None:
    contents = Path("installer/PetNest.iss").read_text(encoding="utf-8")
    build_script = Path("build_windows.bat").read_text(encoding="utf-8")
    ignored = Path(".gitignore").read_text(encoding="utf-8")

    assert 'dist\\PetNest\\*' in contents
    assert 'Excludes: "pets\\*"' in contents
    assert 'Source: "..\\pets\\sample_pet\\*"; DestDir: "{code:GetPetsRoot}\\sample_pet"' in contents
    assert "Check: SamplePetNeedsRepair" in contents
    assert "function SamplePetNeedsRepair" in contents
    assert "not FileExists(AddBackslash(GetPetsRoot('')) + 'sample_pet\\pet.json')" in contents
    assert "not FileExists(AddBackslash(GetPetsRoot('')) + 'sample_pet\\animations\\idle\\001.png')" in contents
    assert "ShouldInstallSamplePet" not in contents
    assert "CreateInputDirPage" in contents
    assert "{localappdata}\\PetNest\\pets" in contents
    assert "DefaultPetsRoot" in contents
    assert "\\PetNest\\pets" in contents
    assert "CreateInputOptionPage" in contents
    assert "FirewallPage" in contents
    assert "PrivilegesRequired=admin" in contents
    assert "OutputBaseFilename=PetNest-Setup-{#AppVersion}" in contents
    assert "--set-pets-root" in contents
    assert 'pets\\sample_pet;pets\\sample_pet' not in build_script
    assert "src\\petnest_launcher.py" in build_script
    assert "%LocalAppData%\\Programs\\Inno Setup 6\\ISCC.exe" in build_script
    assert "--name PetNestUpdateHost" in build_script
    assert "google-services.json;." in build_script
    assert "PETNEST_FIREBASE_CONFIG" in build_script
    assert '--add-data "%PETNEST_FIREBASE_CONFIG%;."' in build_script
    assert 'if not exist "%PETNEST_FIREBASE_CONFIG%"' in build_script
    assert "/google-services.json" in ignored
    assert "Source: \"..\\dist\\PetNestUpdateHost.exe\"" in contents
    assert "Source: \"..\\dist\\PetNestUpdater.exe\"" not in contents
    assert "skipifsilent" in contents


def test_release_version_is_consistent_across_python_and_installer() -> None:
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    package = Path("src/petnest/__init__.py").read_text(encoding="utf-8")
    installer = Path("installer/PetNest.iss").read_text(encoding="utf-8")

    assert 'version = "0.1.6"' in pyproject
    assert '__version__ = "0.1.6"' in package
    assert '#define AppVersion "0.1.6"' in installer


def test_installer_and_application_use_the_dedicated_app_icon() -> None:
    contents = Path("installer/PetNest.iss").read_text(encoding="utf-8")
    build_script = Path("build_windows.bat").read_text(encoding="utf-8")

    assert Path("assets/icons/petnest-app.ico").is_file()
    assert "SetupIconFile=..\\assets\\icons\\petnest-app.ico" in contents
    assert "--icon assets\\icons\\petnest-app.ico" in build_script


def test_updater_entrypoint_is_standard_library_only() -> None:
    contents = Path("src/petnest_updater.py").read_text(encoding="utf-8")

    assert "def main" in contents
    assert "run_installer" in contents
    assert "PySide6" not in contents


def test_release_manifest_generator_is_checked_in() -> None:
    contents = Path("tools/create_app_update_manifest.py").read_text(encoding="utf-8")

    assert "sha256" in contents
    assert "schema_version" in contents
    assert "app-update.json" in contents
    assert "macos-x64" in contents
