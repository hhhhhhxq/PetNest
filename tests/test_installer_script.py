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
    assert "assets\\generated" not in build_script.casefold()
    assert "assets\\countdown;assets\\countdown" in build_script
    assert "assets\\cursors;assets\\cursors" in build_script
    assert "assets\\icons;assets\\icons" in build_script


def test_macos_build_only_bundles_the_neutral_sample_pet() -> None:
    contents = Path("build_macos.sh").read_text(encoding="utf-8")

    assert "--add-data pets/sample_pet:pets/sample_pet" in contents
    assert "--add-data pets:pets" not in contents
    assert "--add-data assets:assets" not in contents
    assert "--add-data assets/countdown:assets/countdown" in contents
    assert "--add-data assets/cursors:assets/cursors" in contents
    assert "--add-data assets/icons:assets/icons" in contents


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


def test_installer_offers_the_exported_godot_client_as_an_optional_component() -> None:
    contents = Path("installer/PetNest.iss").read_text(encoding="utf-8")
    build_script = Path("build_windows.bat").read_text(encoding="utf-8")

    assert 'Name: "standard"' in contents
    assert 'Name: "advanced"' in contents
    assert 'FileExists("..\\dist\\PetNestGodot\\PetNestGodot.exe")' in contents
    assert 'DestDir: "{app}\\advanced"' in contents
    assert "PetNest 高级版" in contents
    assert "clients\\godot\\build-windows.ps1 -Optional" in build_script
    assert 'PETNEST_BUILD_GODOT%"=="0' in build_script
    godot_build = Path("clients/godot/build-windows.ps1").read_text(encoding="utf-8")
    assert 'Join-Path $RepositoryRoot "effects"' in godot_build
    assert "Copy-Item -LiteralPath $EffectsDirectory" in godot_build
