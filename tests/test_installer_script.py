"""Windows 安装脚本的发布关键项检查。"""

from pathlib import Path


def test_installer_shows_an_editable_default_pets_root() -> None:
    contents = Path("installer/PetNest.iss").read_text(encoding="utf-8")
    build_script = Path("build_windows.bat").read_text(encoding="utf-8")

    assert 'dist\\PetNest\\*' in contents
    assert "CreateInputDirPage" in contents
    assert "{localappdata}\\PetNest\\pets" in contents
    assert "直接输入路径或点击“浏览…”选择文件夹" in contents
    assert "CreateInputOptionPage" not in contents
    assert "--set-pets-root" in contents
    assert 'pets\\sample_pet;pets\\sample_pet' in build_script
    assert "src\\petnest_launcher.py" in build_script
    assert "%LocalAppData%\\Programs\\Inno Setup 6\\ISCC.exe" in build_script
