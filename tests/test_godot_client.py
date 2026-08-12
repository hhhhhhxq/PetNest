"""Godot 高级客户端的可选跨运行时一致性测试。"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess

import pytest


def _godot_executable() -> str | None:
    configured = os.environ.get("PETNEST_GODOT_EXE")
    if configured and Path(configured).is_file():
        return configured
    for command in ("godot4", "godot"):
        discovered = shutil.which(command)
        if discovered:
            return discovered
    local = Path(r"D:\Tools\Godot\4.7.1\Godot_v4.7.1-stable_win64_console.exe")
    return str(local) if local.is_file() else None


def test_godot_shared_package_and_settings_contract() -> None:
    executable = _godot_executable()
    if executable is None:
        pytest.skip("Godot 4.7.1 不在当前构建机上")

    completed = subprocess.run(
        [executable, "--headless", "--path", "clients/godot", "--script", "res://tests/smoke_test.gd"],
        check=False,
        capture_output=True,
        text=True,
        timeout=45,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "PetNest Godot smoke tests passed" in completed.stdout


def test_godot_packages_the_windows_native_alpha_presenter() -> None:
    project = Path("clients/godot/project.godot").read_text(encoding="utf-8")
    main_script = Path("clients/godot/src/main.gd").read_text(encoding="utf-8")
    build_script = Path("clients/godot/build-windows.ps1").read_text(encoding="utf-8")
    presenter_client = Path("clients/godot/src/windows_native_presenter.gd").read_text(encoding="utf-8")
    presenter = Path("clients/godot/windows-native-presenter.ps1").read_text(encoding="utf-8")

    assert 'renderer/rendering_method="gl_compatibility"' in project
    assert 'window/size/transparent=false' in project
    assert 'window/per_pixel_transparency/allowed=true' in project
    assert 'window.transparent = use_transparent_desktop' in main_script
    assert 'OS.get_name() == "macOS"' in main_script
    assert "_configure_native_presenter()" in main_script
    assert "_sync_native_presenter()" in main_script
    assert "_sync_native_countdown()" in main_script
    assert 'settings.get("countdown_placement", "above")' in main_script
    assert "desktop_strip_size = usable.size" in main_script
    assert 'settings["godot_pet_y"] = base_pet_position.y' in main_script
    assert "walk_target = Vector2(" in main_script
    assert "windows-native-presenter.ps1" in build_script
    assert "COMMAND_PORT := 18488" in presenter_client
    assert "EVENT_PORT := 18489" in presenter_client
    assert "present_countdown" in presenter_client
    assert '"-HostProcessId", str(OS.get_process_id())' in presenter_client
    assert "UpdateLayeredWindow" in presenter
    assert "Format32bppPArgb" in presenter
    assert "HtTransparent" in presenter
    assert "HideHostRenderWindow" in presenter
    assert "ShowWindow" in presenter
    assert "SetProcessDpiAwarenessContext" in presenter
    assert "EnablePerMonitorDpiAwareness" in presenter
    assert 'case "COUNTDOWN"' in presenter
    assert "PetNestCardWindow" in presenter
    assert "SetWindowPos" in presenter
    assert "HwndTopmost" in presenter
    assert "EnforceTopmost" in presenter
    assert "HostProcessIsRunning" in presenter
    assert "Process.GetProcessById" in presenter
    assert "GetLastInputInfo" in presenter
    assert 'SendEvent("IDLE\\t"' in presenter
    assert 'case "CURSOR"' in presenter
    assert 'SendEvent("CURSOR_APPLIED\\t0")' in presenter
    assert "SetSystemCursor" in presenter
    assert "SystemParametersInfo" in presenter
    assert 'case "FOCUS_POPUP"' in presenter
    assert "SetForegroundWindow" in presenter
    assert 'kind == "IDLE"' in presenter_client
    assert 'kind == "CURSOR_APPLIED"' in presenter_client


def test_godot_advanced_exposes_manual_import_cursor_and_update_entries() -> None:
    main_script = Path("clients/godot/src/main.gd").read_text(encoding="utf-8")
    importer = Path("clients/godot/src/spritesheet_importer.gd").read_text(encoding="utf-8")
    import_dialog = Path("clients/godot/src/spritesheet_import_dialog.gd").read_text(encoding="utf-8")
    settings_dialog = Path("clients/godot/src/settings_dialog.gd").read_text(encoding="utf-8")
    build_script = Path("clients/godot/build-windows.ps1").read_text(encoding="utf-8")

    assert "selected_columns_by_action: Dictionary" in importer
    assert "手动选择所需帧" in import_dialog
    assert "cursor_style_enabled" in settings_dialog
    assert 'target.add_item("检查程序更新…", MENU_APP_UPDATE)' in main_script
    assert 'target.add_item("检查远程资源更新…", MENU_RESOURCE_UPDATE)' in main_script
    assert '"--maintenance"' in main_script
    assert "PetNest.exe" in main_script
    assert "assets\\cursors" in build_script


def test_godot_native_context_menu_opens_on_release_and_closes_before_rebuild() -> None:
    main_script = Path("clients/godot/src/main.gd").read_text(encoding="utf-8")
    scene = Path("clients/godot/src/main.tscn").read_text(encoding="utf-8")

    assert 'button == MOUSE_BUTTON_RIGHT and kind == "up"' in main_script
    assert "func _on_menu_id_pressed(identifier: int) -> void:\n\t# Close first" in main_script
    assert "\tmenu.hide()" in main_script
    assert "\tcontext_menu.hide()" in main_script
    assert "\t_build_menu.call_deferred()" in main_script
    assert 'context_menu.popup()' in main_script
    assert 'context_menu.grab_focus()' in main_script
    assert 'native_presenter.focus_host_popup()' in main_script
    assert 'context_menu.min_size = Vector2i(270, 0)' in main_script
    assert 'add_theme_font_size_override("font_size", 21)' in main_script
    assert 'add_theme_constant_override("v_separation", 10)' in main_script
    assert '[node name="ContextMenu" type="PopupMenu" parent="."]' in scene
    assert "prefer_native_menu = false" in scene
    assert 'menu = NodePath("../Menu")' in scene


def test_godot_advanced_has_macos_window_idle_export_and_shared_features() -> None:
    project = Path("clients/godot/project.godot").read_text(encoding="utf-8")
    presets = Path("clients/godot/export_presets.cfg").read_text(encoding="utf-8")
    main_script = Path("clients/godot/src/main.gd").read_text(encoding="utf-8")
    settings_store = Path("clients/godot/src/settings_store.gd").read_text(encoding="utf-8")
    bridge_client = Path("clients/godot/src/macos_idle_bridge.gd").read_text(encoding="utf-8")
    bridge = Path("clients/godot/macos-idle-bridge.c").read_text(encoding="utf-8")
    build_script = Path("clients/godot/build-macos.sh").read_text(encoding="utf-8")
    root_build_script = Path("build_macos.sh").read_text(encoding="utf-8")

    assert 'window/per_pixel_transparency/allowed=true' in project
    assert 'textures/vram_compression/import_etc2_astc=true' in project
    assert 'name="macOS"' in presets
    assert 'binary_format/architecture="universal"' in presets
    assert 'application/bundle_identifier="com.petnest.advanced"' in presets
    assert 'var use_transparent_desktop := OS.get_name() == "macOS"' in main_script
    assert 'window.size = usable.size' in main_script
    assert 'DisplayServer.window_set_mouse_passthrough(_pet_polygon())' in main_script
    assert '_configure_macos_idle_bridge()' in main_script
    assert '_set_macos_startup(enabled)' in main_script
    assert '"--cursor-action", "apply" if enabled else "restore"' in main_script
    assert 'Library").path_join("Application Support").path_join("PetNest")' in settings_store
    assert 'path_join("Resources").path_join("pets")' in settings_store
    assert 'EVENT_PORT := 18490' in bridge_client
    assert 'path_join("Helpers").path_join("macos-idle-bridge")' in bridge_client
    assert 'IOServiceMatching("IOHIDSystem")' in bridge
    assert 'CFSTR("HIDIdleTime")' in bridge
    assert 'HELPERS="$CONTENTS/Helpers"' in build_script
    assert '-arch x86_64 -arch arm64' in build_script
    assert 'pets/sample_pet' in build_script
    assert 'cp -R "$REPOSITORY_ROOT/pets/sample_pet"' in build_script
    assert 'sh clients/godot/build-macos.sh' in root_build_script
