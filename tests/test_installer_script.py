"""Windows 安装脚本的发布关键项检查。"""

from pathlib import Path


def test_installer_includes_app_files_and_optional_custom_pets_root_page() -> None:
    contents = Path("installer/PetNest.iss").read_text(encoding="utf-8")
    build_script = Path("build_windows.bat").read_text(encoding="utf-8")

    assert 'dist\\PetNest\\*' in contents
    assert "将宠物库保存到自定义位置" in contents
    assert "--set-pets-root" in contents
    assert 'pets\\sample_pet;pets\\sample_pet' in build_script
    assert "src\\petnest_launcher.py" in build_script
    assert "%LocalAppData%\\Programs\\Inno Setup 6\\ISCC.exe" in build_script
