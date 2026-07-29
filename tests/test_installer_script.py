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
    assert "CreateInputOptionPage" not in contents
    assert "--set-pets-root" in contents
    assert 'pets\\sample_pet;pets\\sample_pet' not in build_script
    assert "src\\petnest_launcher.py" in build_script
    assert "%LocalAppData%\\Programs\\Inno Setup 6\\ISCC.exe" in build_script
