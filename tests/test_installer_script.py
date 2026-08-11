"""Windows 安装脚本的发布关键项检查。"""

from pathlib import Path


def test_installer_writes_the_sample_pet_directly_to_the_selected_library() -> None:
    contents = Path("installer/PetNest.iss").read_text(encoding="utf-8")
    build_script = Path("build_windows.bat").read_text(encoding="utf-8")

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
    assert "--set-pets-root" in contents
    assert 'pets\\sample_pet;pets\\sample_pet' not in build_script
    assert "src\\petnest_launcher.py" in build_script
    assert "%LocalAppData%\\Programs\\Inno Setup 6\\ISCC.exe" in build_script
    assert "PetNestUpdater" in build_script
    assert "Source: \"..\\dist\\PetNestUpdater.exe\"" in contents
    assert "skipifsilent" in contents


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
