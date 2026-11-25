"""Companion rendering, switching and permission regression tests."""

import json
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from petnest.core.keyboard_cat import CAT_RENDERER, CatState
from petnest.core.package_loader import PackageLoader
from petnest.core.settings_manager import SettingsManager
from petnest.models.settings import Settings
from petnest.platforms.macos_keyboard import MacOSKeyboardActivityMonitor
from petnest.ui.keyboard_cat_renderer import render_cat
from petnest.ui.pet_action_exchange_dialog import PetActionExchangeDialog
from petnest.ui.pet_window import PetWindow
from tests.test_package_validator import _write_package

ROOT = Path(__file__).resolve().parents[1] / "pets" / "keyboard_cat"


@pytest.mark.parametrize("platform, expected", [("win32", True), ("darwin", False)])
def test_first_cat_activation_defaults_and_remembers_opt_out(
    qtbot, tmp_path, monkeypatch, platform, expected
):
    from petnest.app import PetNest
    from petnest.core import keyboard_cat
    from petnest.platforms.keyboard import UnsupportedKeyboardActivityMonitor
    from tools.create_sample_pet import create_sample_pet

    monkeypatch.setattr(keyboard_cat, "sys", SimpleNamespace(platform=platform))
    pets = tmp_path / "pets"
    create_sample_pet(pets / "sample_pet")
    shutil.copytree(ROOT, pets / "keyboard_cat")
    manager = SettingsManager(tmp_path / "settings.json")
    manager.save(Settings(current_pet_id="sample_pet", work_countdown_enabled=False))

    def launch():
        app = PetNest(
            pets_root=pets, settings_manager=manager, enable_tray=False,
            keyboard_activity_monitor=UnsupportedKeyboardActivityMonitor("test"),
        )
        qtbot.addWidget(app.window)
        return app

    app = launch()
    try:
        assert not app.settings.keyboard_working_enabled
        assert app._pet_preferences("keyboard_cat")["keys"] is expected
        assert app.switch_pet("keyboard_cat")
        assert app.settings.keyboard_working_enabled is expected
        prefs = app._pet_preferences("keyboard_cat")
        app._save_pet_preferences("keyboard_cat", {**prefs, "keys": False})
        assert app.switch_pet("sample_pet")
        assert not app.settings.keyboard_working_enabled
        assert app.switch_pet("keyboard_cat")
        assert not app.settings.keyboard_working_enabled
    finally:
        app.shutdown()
    app = launch()
    try:
        assert not app.settings.keyboard_working_enabled
    finally:
        app.shutdown()


@pytest.mark.parametrize("saved_active, expected", [(False, True), (True, False)])
def test_windows_cat_startup_default_preserves_existing_active_setting(
    qtbot, tmp_path, monkeypatch, saved_active, expected
):
    from petnest.app import PetNest
    from petnest.core import keyboard_cat
    from petnest.platforms.keyboard import UnsupportedKeyboardActivityMonitor

    monkeypatch.setattr(keyboard_cat, "sys", SimpleNamespace(platform="win32"))
    pets = tmp_path / "pets"
    shutil.copytree(ROOT, pets / "keyboard_cat")
    manager = SettingsManager(tmp_path / "settings.json")
    manager.save(Settings(
        current_pet_id="keyboard_cat" if saved_active else None,
        keyboard_working_enabled=False, work_countdown_enabled=False,
    ))
    app = PetNest(
        pets_root=pets, settings_manager=manager, enable_tray=False,
        keyboard_activity_monitor=UnsupportedKeyboardActivityMonitor("test"),
    )
    qtbot.addWidget(app.window)
    try:
        assert app.settings.keyboard_working_enabled is expected
        assert app._pet_preferences("keyboard_cat")["keys"] is expected
        assert manager.load().keyboard_working_enabled is expected
    finally:
        app.shutdown()


def test_builtin_loads_and_real_keys_drive_different_pixels(qapp):
    p = PackageLoader().load(ROOT)
    assert p.renderer == CAT_RENDERER
    state = CatState()
    idle = render_cat(state, {}, dt=0)
    for key in ("A", "S", "CtrlL", "ShiftL"):
        state.key_event(key, True)
    pressed = render_cat(state, {}, dt=0)
    assert pressed != idle
    assert len(state.keys) == 4
    state.key_event("A", False)
    assert state.keys == {"S", "CtrlL", "ShiftL"}
    state.key_event("reset", False)
    assert not state.keys
    assert render_cat(CatState(), {"coat": "siamese"}, dt=0) != idle
    assert render_cat(CatState(), {"keyboard": "dark"}, dt=0) != idle
    assert idle.pixelColor(0, 0).alpha() == 0


def test_native_window_switch_releases_keys_and_restores_frames(qtbot, tmp_path):
    cat = PackageLoader().load(ROOT)
    original = PackageLoader().load(_write_package(tmp_path / "original"))
    window = PetWindow(cat)
    qtbot.addWidget(window)
    window.set_cat_preferences({"coat": "siamese"})
    window.cat_key_event("A", True)
    window.cat_key_event("CtrlL", True)
    window._on_animation_tick()
    assert window.is_opaque_at(182, 120)
    assert not window.is_opaque_at(0, 0)
    window.set_paused(True)
    assert not window.animation_timer.isActive()
    window.load_package(original)
    assert not window.cat_state.keys
    assert window._cat_image is None
    window.set_paused(False)
    assert window.current_pixmap.width() == original.canvas.width
    window.load_package(cat)
    assert not window.cat_state.keys


def test_library_browsing_is_not_activation_and_only_shows_relevant_controls(
    qtbot, tmp_path
):
    original = PackageLoader().load(_write_package(tmp_path / "original"))
    cat = PackageLoader().load(ROOT)
    saved = {}
    activated = []
    dialog = PetActionExchangeDialog(
        [original, cat],
        tmp_path,
        current_pet_id=original.identifier,
        preferences=lambda ident: saved.get(ident, {}),
        save_preferences=lambda ident, value: saved.update({ident: value}),
        use_pet=lambda ident: activated.append(ident) or True,
    )
    qtbot.addWidget(dialog)
    dialog.show()
    page = dialog.my_pets_page
    assert dialog.current_page_name() == "我的宠物"
    page.pet_list.setCurrentRow(1)
    assert not activated
    assert not page.outfit.isHidden()
    assert page.edit_button.isHidden()
    page.coat.setCurrentIndex(1)
    assert saved[cat.identifier]["coat"] == "siamese"
    page.trigger_primary()
    assert activated == [cat.identifier]
    assert not page.footer_state().primary_enabled
    page.pet_list.setCurrentRow(0)
    assert page.outfit.isHidden()
    assert not page.edit_button.isHidden()
    assert all(p.renderer == "frames" for p in dialog.animation_editor_page._packages)
    dialog.close()


def test_app_remembers_per_pet_appearance_scale_and_follow(qtbot, tmp_path):
    from petnest.app import PetNest
    from petnest.platforms.keyboard import UnsupportedKeyboardActivityMonitor
    from tools.create_sample_pet import create_sample_pet

    pets = tmp_path / "pets"
    create_sample_pet(pets / "sample_pet")
    shutil.copytree(ROOT, pets / "keyboard_cat")
    manager = SettingsManager(tmp_path / "settings.json")
    manager.save(
        Settings(current_pet_id="sample_pet", scale=0.8, work_countdown_enabled=False)
    )
    app = PetNest(
        pets_root=pets,
        settings_manager=manager,
        enable_tray=False,
        keyboard_activity_monitor=UnsupportedKeyboardActivityMonitor("test"),
    )
    qtbot.addWidget(app.window)
    try:
        assert app.switch_pet("keyboard_cat")
        preferences = app._pet_preferences("keyboard_cat")
        preferences.update(
            coat="siamese", keyboard="dark", scale=1.2, follow=True, keys=True
        )
        app._save_pet_preferences("keyboard_cat", preferences)
        assert app.window.cat_preferences["coat"] == "siamese"
        app.window.cat_key_event("Q", True)
        assert app.switch_pet("sample_pet")
        assert not app.window.cat_state.keys
        assert app.settings.scale == 0.8
        assert not app.settings.mouse_follow_enabled
        assert app.switch_pet("keyboard_cat")
        assert app.settings.scale == 1.2
        assert app.settings.mouse_follow_enabled
        assert app.window.cat_preferences["keyboard"] == "dark"
        assert manager.load().pet_preferences["keyboard_cat"]["coat"] == "siamese"
        serialized = json.loads(manager.path.read_text(encoding="utf-8"))
        assert "Q" not in serialized["pet_preferences"]["keyboard_cat"]
    finally:
        app.shutdown()


def test_macos_permission_denial_is_passive(monkeypatch):
    requested = []
    q = SimpleNamespace(
        CGPreflightListenEventAccess=lambda: False,
        CGRequestListenEventAccess=lambda: requested.append(True),
    )
    monkeypatch.setitem(sys.modules, "Quartz", q)
    monkeypatch.setitem(sys.modules, "CoreFoundation", SimpleNamespace())
    monitor = MacOSKeyboardActivityMonitor()
    assert not monitor.start(lambda: None)
    assert not requested
    assert "输入监控" in monitor.status_message
    monitor.stop()


def test_macos_tap_delivers_key_up_modifiers_and_resets(monkeypatch):
    events = []
    callbacks = []
    enabled = []
    removed = []
    q = SimpleNamespace(
        CGPreflightListenEventAccess=lambda: True,
        kCGEventKeyDown=10,
        kCGEventKeyUp=11,
        kCGEventFlagsChanged=12,
        kCGEventLeftMouseDown=1,
        kCGEventLeftMouseUp=2,
        kCGEventRightMouseDown=3,
        kCGEventRightMouseUp=4,
        kCGEventTapDisabledByTimeout=100,
        kCGEventTapDisabledByUserInput=101,
        kCGKeyboardEventKeycode=9,
        kCGEventSourceStateCombinedSessionState=0,
        kCGSessionEventTap=1,
        kCGHeadInsertEventTap=0,
        kCGEventTapOptionListenOnly=1,
        CGEventTapCreate=lambda *args: callbacks.append(args[-2]) or object(),
        CGEventTapEnable=lambda tap, value: enabled.append(value),
        CGEventGetIntegerValueField=lambda e, field: e,
        CGEventSourceKeyState=lambda source, code: True,
    )
    cf = SimpleNamespace(
        CFMachPortCreateRunLoopSource=lambda *a: object(),
        CFRunLoopGetMain=lambda: object(),
        kCFRunLoopCommonModes="common",
        CFRunLoopAddSource=lambda *a: None,
        CFRunLoopRemoveSource=lambda *a: removed.append(True),
        CFMachPortInvalidate=lambda *a: None,
    )
    monkeypatch.setitem(sys.modules, "Quartz", q)
    monkeypatch.setitem(sys.modules, "CoreFoundation", cf)
    monitor = MacOSKeyboardActivityMonitor()
    monitor.set_key_handler(lambda *e: events.append(e))
    assert monitor.start(lambda: None)
    callback = callbacks[0]
    callback(None, 10, 0, None)
    callback(None, 12, 56, None)
    callback(None, 11, 0, None)
    assert events == [("A", True), ("ShiftL", True), ("A", False)]
    callback(None, 100, 0, None)
    assert events[-1] == ("reset", False)
    monitor.stop()
    assert removed and enabled[-1] is False


def test_malformed_renderer_is_rejected_and_preferences_are_normalized(tmp_path):
    from petnest.core.keyboard_cat import cat_preferences
    from petnest.core.package_validator import PackageValidator

    assert cat_preferences({"coat": [], "keyboard": {}, "look": "yes"}) == {
        "coat": "black",
        "keyboard": "cream",
        "look": False,
        "petting": True,
        "sleep_enabled": True,
        "sleep_seconds": 40,
        "colors": {},
        "white_markings": {"face": "none", "chest": 0.0, "paws": 0.0, "amount": 0.55},
    }
    root = _write_package(tmp_path / "bad")
    raw = json.loads((root / "pet.json").read_text(encoding="utf-8"))
    raw["renderer"] = []
    (root / "pet.json").write_text(json.dumps(raw))
    assert not PackageValidator().validate(root).is_valid


def test_builtin_is_added_to_existing_library_without_overwriting(tmp_path):
    from petnest.core.pet_library import install_keyboard_cat

    library = tmp_path / "library"
    _write_package(library / "original")
    install_keyboard_cat(library, ROOT.parent)
    assert {p.identifier for p in PackageLoader().discover(library)} >= {"keyboard_cat"}
    config = library / "keyboard_cat" / "pet.json"
    raw = json.loads(config.read_text(encoding="utf-8"))
    raw["name"] = "我的键盘猫"
    config.write_text(json.dumps(raw))
    install_keyboard_cat(library, ROOT.parent)
    assert json.loads(config.read_text(encoding="utf-8"))["name"] == "我的键盘猫"


def test_stale_queued_keys_cannot_reach_new_pet(qtbot, tmp_path):
    from tests.test_pet_action_exchange_app import _application

    app = _application(tmp_path, qtbot)
    try:
        old = app._physical_key_generation
        app._configure_physical_keys()
        seen = []
        app.window.cat_key_event = lambda *args: seen.append(args)
        app._handle_physical_key(old, "A", True)
        assert seen == []
    finally:
        app.shutdown()


def test_missed_key_release_reaches_desktop_and_both_previews(qtbot, tmp_path):
    from dataclasses import replace
    from petnest.ui.cat_appearance_dialog import CatAppearanceDialog
    from tests.test_pet_action_exchange_app import _application

    app = _application(tmp_path, qtbot)
    cat = PackageLoader().load(ROOT)
    app.packages = (*app.packages, cat)
    editor = None
    try:
        assert app.switch_pet(cat.identifier)
        app.settings = replace(app.settings, keyboard_working_enabled=True)
        app.keyboard_activity_monitor = SimpleNamespace(
            status_message="监听正常", reconcile_keys=lambda keys: keys & {"S"},
            stop=lambda: None,
        )
        app._keyboard_monitor_running = True
        app.show_pet_action_exchange_dialog()
        page = app._pet_action_exchange_dialog.my_pets_page
        editor = CatAppearanceDialog({}, page)
        qtbot.addWidget(editor)
        page._appearance_dialog = editor
        editor.show()
        for key in ("A", "S"):
            app._handle_physical_key(app._physical_key_generation, key, True)
        states = (app.window.cat_state, page._preview_state, editor.state)
        assert all(state.keys == {"A", "S"} for state in states)
        app._reconcile_physical_keys()
        assert all(state.keys == {"S"} for state in states)

        def failed_reconcile(keys):
            raise RuntimeError("input unavailable")

        app.keyboard_activity_monitor.reconcile_keys = failed_reconcile
        app._reconcile_physical_keys()
        assert all(not state.keys for state in states)
    finally:
        if editor is not None:
            editor.close()
        if app._pet_action_exchange_dialog is not None:
            app._pet_action_exchange_dialog.close()
        app.shutdown()


def test_deactivation_clears_local_appearance_preview_keys(qtbot, tmp_path):
    from PySide6.QtCore import QEvent
    from petnest.ui.cat_appearance_dialog import CatAppearanceDialog

    cat = PackageLoader().load(ROOT)
    dialog = PetActionExchangeDialog([cat], tmp_path, current_pet_id=cat.identifier)
    qtbot.addWidget(dialog)
    dialog.show()
    page = dialog.my_pets_page
    editor = CatAppearanceDialog({}, page)
    qtbot.addWidget(editor)
    page._appearance_dialog = editor
    editor.show()
    try:
        page.cat_key_event("A", True)
        assert editor.state.keys == {"A"}
        page.eventFilter(page, QEvent(QEvent.Type.ApplicationDeactivate))
        assert not editor.state.keys
        assert not page._preview_state.keys
    finally:
        editor.close()
        dialog.close()


def test_layout_fits_with_permission_controls(qtbot, tmp_path):
    cat = PackageLoader().load(ROOT)
    dialog = PetActionExchangeDialog(
        [cat],
        tmp_path,
        current_pet_id=cat.identifier,
        preferences=lambda _: {"keys": True},
    )
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.wait(10)
    assert (
        dialog.my_pets_page.minimumSizeHint().height() <= dialog.my_pets_page.height()
    )


def test_authorization_target_selects_enclosing_app(monkeypatch, tmp_path):
    bundle = tmp_path / "PetNest.app"
    monkeypatch.setattr(sys, "executable", str(bundle / "Contents/MacOS/PetNest"))
    assert MacOSKeyboardActivityMonitor.authorization_target() == bundle.resolve()


def test_permission_poll_starts_after_grant_and_stops_after_revocation(qtbot, tmp_path):
    from dataclasses import replace

    from tests.test_pet_action_exchange_app import _application

    app = _application(tmp_path, qtbot)
    allowed = [False]
    starts, stops = [], []
    monitor = SimpleNamespace(
        supported=True,
        permission_granted=lambda: allowed[0],
        start=lambda callback: starts.append(True) or allowed[0],
        stop=lambda: stops.append(True),
    )
    app.keyboard_activity_monitor = monitor
    app.settings = replace(app.settings, keyboard_working_enabled=True)
    try:
        app._poll_keyboard_permission()
        assert not starts
        allowed[0] = True
        app._poll_keyboard_permission()
        assert app._keyboard_monitor_running
        assert len(starts) == 1
        app._poll_keyboard_permission()
        assert len(starts) == 1
        app.window.cat_state.keys.add("A")
        allowed[0] = False
        app._poll_keyboard_permission()
        assert not app._keyboard_monitor_running
        assert not app.window.cat_state.keys
        assert stops == [True]
    finally:
        app.shutdown()
