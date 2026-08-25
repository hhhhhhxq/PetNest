"""macOS 打包脚本的可选 Firebase 配置检查。"""

from pathlib import Path


def test_macos_build_includes_service_management_bridge() -> None:
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    requirements = Path("requirements.txt").read_text(encoding="utf-8")
    build_script = Path("build_macos.sh").read_text(encoding="utf-8")

    marker = "pyobjc-framework-ServiceManagement>=12.2,<13; sys_platform == 'darwin'"
    assert marker in pyproject
    assert marker in requirements
    assert "--hidden-import ServiceManagement" in build_script


def test_macos_build_includes_google_services_when_present() -> None:
    contents = Path("build_macos.sh").read_text(encoding="utf-8")
    ignored = Path(".gitignore").read_text(encoding="utf-8")

    assert '[ -f "google-services.json" ]' in contents
    assert "--add-data google-services.json:." in contents
    assert "/google-services.json" in ignored
    assert "pets/sample_pet:pets/sample_pet" in contents
    assert "PetNestUpdater" in contents
    assert "src/petnest_launcher.py" in contents
    assert "codesign --force --deep --sign -" in contents
    assert "PetNest-macOS-x64-$VERSION.zip" in contents
