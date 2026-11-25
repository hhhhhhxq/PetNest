"""Appearance persistence, editing transactions and animated layer regressions."""

from copy import deepcopy
import sys

import pytest
from PySide6.QtCore import QPointF, QTimer

from petnest.core.cat_appearance import COATS, PRESETS, apply_preset, saved_palettes, switch_appearance
from petnest.core.keyboard_cat import CatState, cat_preferences
from petnest.core.settings_manager import SettingsManager
from petnest.models.settings import Settings
from petnest.ui.cat_appearance_dialog import CatAppearanceDialog
from petnest.ui.keyboard_cat_renderer import render_cat


def test_malformed_palettes_are_bounded_and_normalized():
    raw = {"colors": {"fur": "#aabbcc", "point": "red", "eyes": [], "keys": "#12345678", "unknown": "#123456"},
           "white_markings": {"face": {}, "chest": float("nan"), "paws": 5, "amount": -2}}
    result = cat_preferences(raw)
    assert result["colors"] == {"fur": "#AABBCC"}
    assert result["white_markings"] == {"face": "none", "chest": 0, "paws": 1, "amount": 0}
    assert not saved_palettes([None, {"name": "bad", "coat": []}])
    assert len(saved_palettes([{"name": "猫", "coat": "tabby"}] * 100)) == 24


def test_coat_presets_preserve_keyboard_and_interaction_preferences():
    original = cat_preferences({"keyboard": "dark", "colors": {"keys": "#88AABB", "fur": "#FFFFFF"}})
    original.update(keys=True, follow=True, scale=1.3)
    value = apply_preset(original, "棕灰虎斑加白")
    assert value["colors"]["keys"] == "#88AABB"
    assert value["keyboard"] == "dark" and value["follow"] and value["keys"]
    assert value["scale"] == 1.3
    assert value["white_markings"]["face"] == "blaze"
    assert original["colors"]["fur"] == "#FFFFFF"


def test_editor_cancel_is_isolated_and_saved_palette_roundtrips(qtbot, tmp_path):
    original = {**cat_preferences({}), "keys": True, "scale": 1.2}
    snapshot = deepcopy(original)
    editor = CatAppearanceDialog(original)
    qtbot.addWidget(editor)
    editor.coat.setCurrentIndex(editor.coat.findData("tabby"))
    editor.fields["fur"].hex.setText("#7799BB")
    editor.fields["fur"]._typed("#7799BB")
    editor.face.setCurrentIndex(editor.face.findData("blaze"))
    editor.markings["paws"][0].setValue(72)
    editor.palette_name.setText("我的虎斑")
    editor._save_palette()
    assert original == snapshot
    result = editor.result_preferences()
    manager = SettingsManager(tmp_path / "settings.json")
    manager.save(Settings(pet_preferences={"keyboard_cat": result}))
    loaded = manager.load().pet_preferences["keyboard_cat"]
    other = CatAppearanceDialog(loaded)
    qtbot.addWidget(other)
    other._load_saved(1)
    assert other.draft["coat"] == "tabby"
    assert other.draft["colors"]["fur"] == "#7799BB"
    assert other.draft["white_markings"]["paws"] == 0.72
    assert other.draft["white_markings"]["face"] == "blaze"
    assert other.draft["keys"] is True
    editor.reject()
    other.reject()
    assert original == snapshot


def test_tortie_has_two_coat_channels_and_only_one_tabby_type(qtbot):
    editor = CatAppearanceDialog(apply_preset({}, "玳瑁琥珀"))
    qtbot.addWidget(editor)
    assert not editor.fields["point"].isHidden()
    assert editor.fields["secondary"].isHidden()
    assert [key for key in COATS if "tabby" in key] == ["tabby"]
    editor.coat.setCurrentIndex(editor.coat.findData("calico"))
    assert not editor.fields["secondary"].isHidden()
    editor.reject()


@pytest.mark.parametrize("size", [(940, 760), (800, 620)])
def test_editor_controls_are_reachable_and_do_not_overlap(qtbot, size):
    editor = CatAppearanceDialog(cat_preferences({}))
    qtbot.addWidget(editor)
    editor.resize(*size)
    editor.show()
    qtbot.wait(10)
    from PySide6.QtWidgets import QScrollArea
    scroll = editor.findChild(QScrollArea)
    assert scroll.horizontalScrollBar().maximum() == 0
    scroll.ensureWidgetVisible(editor.presets)
    qtbot.wait(10)
    assert scroll.viewport().rect().contains(editor.presets.mapTo(scroll.viewport(), editor.presets.rect().center()))
    assert editor.rect().contains(editor.palette_name.mapTo(editor, editor.palette_name.rect().center()))
    assert editor.palette_name.mapTo(editor, editor.palette_name.rect().center()).y() < scroll.y()
    editor.reject()


def test_switching_styles_restores_colors_and_markings_after_reopening(qtbot, tmp_path):
    original = cat_preferences({"coat": "tabby", "keyboard": "cream"})
    editor = CatAppearanceDialog(original)
    qtbot.addWidget(editor)
    editor.set_color("fur", "#7744AA")
    editor.set_color("eyes", "#3388CC")
    editor.set_color("keys", "#CCAA88")
    editor.face.setCurrentIndex(editor.face.findData("blaze"))
    editor.markings["paws"][0].setValue(72)
    editor.coat.setCurrentIndex(editor.coat.findData("shaded"))
    editor.set_color("fur", "#AA5577")
    editor.keyboard.setCurrentIndex(editor.keyboard.findData("dark"))
    editor.set_color("keys", "#445577")
    manager = SettingsManager(tmp_path / "settings.json")
    manager.save(Settings(pet_preferences={"keyboard_cat": editor.result_preferences()}))
    editor.reject()
    reopened = CatAppearanceDialog(manager.load().pet_preferences["keyboard_cat"])
    qtbot.addWidget(reopened)
    reopened.coat.setCurrentIndex(reopened.coat.findData("tabby"))
    assert reopened.draft["colors"]["fur"] == "#7744AA"
    assert reopened.draft["colors"]["eyes"] == "#3388CC"
    assert reopened.draft["white_markings"]["paws"] == 0.72
    assert reopened.draft["white_markings"]["face"] == "blaze"
    assert reopened.draft["colors"]["keys"] == "#445577"
    reopened.keyboard.setCurrentIndex(reopened.keyboard.findData("cream"))
    assert reopened.draft["colors"]["keys"] == "#CCAA88"
    reopened.coat.setCurrentIndex(reopened.coat.findData("shaded"))
    assert reopened.draft["colors"]["fur"] == "#AA5577"
    reopened.reject()
    assert not original["colors"]
    assert "appearance_memory" not in original


def test_accidental_preset_and_reset_can_be_undone(qtbot):
    editor = CatAppearanceDialog(cat_preferences({"coat": "tabby"}))
    qtbot.addWidget(editor)
    editor.set_color("fur", "#AABBCC")
    editor.palette_name.setText("刚调好的猫")
    editor._preset_selected(editor.presets.findData("银灰虎斑"))
    assert editor.draft["colors"]["fur"] != "#AABBCC"
    editor.undo_button.click()
    assert editor.draft["colors"]["fur"] == "#AABBCC"
    assert editor.palette_name.text() == "刚调好的猫"
    editor._reset()
    assert not editor.draft["colors"]
    editor.undo_button.click()
    assert editor.draft["colors"]["fur"] == "#AABBCC"
    editor.reject()


def test_memory_ignores_malformed_and_unknown_entries():
    options = cat_preferences({"coat": "tabby"})
    options["appearance_memory"] = {"coats": {"shaded": {"colors": {"fur": "#aabbcc", "keys": "#FFFFFF"}, "white_markings": {"paws": 900}}, "other": {}}, "keyboards": []}
    result = switch_appearance(options, coat="shaded")
    assert result["colors"] == {"fur": "#AABBCC"}
    assert result["white_markings"]["paws"] == 1
    assert "other" not in result["appearance_memory"]["coats"]


@pytest.mark.parametrize("name", list(PRESETS))
def test_all_presets_render_animate_and_keep_transparency(qapp, name):
    options = apply_preset({}, name)
    state = CatState()
    neutral = render_cat(state, options)
    assert neutral.pixelColor(0, 0).alpha() == 0
    for key in ("A", "S", "D"):
        state.key_event(key, True)
    for _ in range(8):
        moved = render_cat(state, options, cursor=QPointF(280, 140))
    assert moved != neutral
    assert moved.pixelColor(359, 0).alpha() == 0
    state.reset()
    assert not state.keys


@pytest.mark.skipif(sys.platform != "darwin", reason="native coat geometry")
def test_custom_eyes_have_no_black_fur_residue_and_instances_are_independent(qapp):
    light = {"coat": "black", "colors": {"fur": "#EEDDBB", "eyes": "#6699DD"}}
    image = render_cat(CatState(), light, dt=0)
    # Below both irises: previously the raster replacement excluded these pixels.
    for x in (166, 202):
        rgb = image.pixelColor(x, 138)
        assert rgb.red() > 150 and rgb.green() > 130
    render_cat(CatState(), apply_preset({}, "玳瑁琥珀"), dt=0)
    assert render_cat(CatState(), light, dt=0) == image
    assert render_cat(CatState(), {}, dt=0) != image


@pytest.mark.skipif(sys.platform != "darwin", reason="native coat geometry")
def test_white_markings_and_keyboard_colors_change_the_correct_layers(qapp):
    base = cat_preferences({"coat": "tabby"})
    bare = render_cat(CatState(), base, dt=0)
    white = deepcopy(base)
    white["white_markings"].update(chest=0.8, paws=0.7, face="inverted_v")
    marked = render_cat(CatState(), white, dt=0)
    assert marked.copy(140, 100, 90, 145) != bare.copy(140, 100, 90, 145)
    custom = deepcopy(base)
    custom["colors"] = {"case": "#734978", "keys": "#E8CDEA", "accent": "#FF00FF"}
    keyboard = render_cat(CatState(), custom, dt=0)
    assert keyboard.copy(130, 70, 110, 165) == bare.copy(130, 70, 110, 165)
    assert keyboard.copy(100, 240, 195, 60) != bare.copy(100, 240, 195, 60)


def test_qt_fallback_uses_the_same_recipes(qapp, monkeypatch):
    import petnest.ui.keyboard_cat_renderer as renderer
    monkeypatch.setattr(renderer, "sys", type("Platform", (), {"platform": "linux"}))
    frames = [render_cat(CatState(), apply_preset({}, name), dt=0) for name in PRESETS]
    assert all(frame.pixelColor(0, 0).alpha() == 0 for frame in frames)
    assert all(frames[0] != frame for frame in frames[1:])


def test_library_editor_save_updates_active_pet_and_survives_switch(qtbot, tmp_path):
    import shutil
    from pathlib import Path
    from tests.test_pet_action_exchange_app import _application
    shutil.copytree(Path(__file__).resolve().parents[1] / "pets/keyboard_cat", tmp_path / "pets/keyboard_cat")
    app = _application(tmp_path, qtbot)
    qtbot.addWidget(app.window)
    try:
        assert app.switch_pet("keyboard_cat")
        app.show_pet_action_exchange_dialog("我的宠物")
        qtbot.addWidget(app._pet_action_exchange_dialog)
        page = app._pet_action_exchange_dialog.my_pets_page

        def finish_editor():
            editor = page._appearance_dialog
            editor.draft = apply_preset(editor.draft, "灰棕重点加白")
            editor.set_color("eyes", "#7799CC")
            editor.accept()

        QTimer.singleShot(0, finish_editor)
        page._customize()
        assert app.window.cat_preferences["colors"]["eyes"] == "#7799CC"
        assert app.window.cat_preferences["white_markings"]["face"] == "inverted_v"
        page.coat.setCurrentIndex(page.coat.findData("tabby"))
        page.coat.setCurrentIndex(page.coat.findData("siamese"))
        assert app.window.cat_preferences["colors"]["eyes"] == "#7799CC"
        assert app.window.cat_preferences["white_markings"]["face"] == "inverted_v"
        assert app.switch_pet("sample_pet")
        assert app.switch_pet("keyboard_cat")
        assert app.window.cat_preferences["colors"]["eyes"] == "#7799CC"
        assert app.settings_manager.load().pet_preferences["keyboard_cat"]["white_markings"]["paws"] == 0.65
    finally:
        if app._pet_action_exchange_dialog is not None:
            app._pet_action_exchange_dialog.close()
        app.shutdown()


@pytest.mark.skipif(sys.platform != "darwin", reason="CoreGraphics bitmap coordinates")
def test_native_limb_sampling_and_paw_overlap(tmp_path):
    """Sample the actual coat; overlapping arm and paw must never make a hole."""
    import subprocess
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    harness = tmp_path / "main.swift"
    harness.write_text('''
import AppKit
let ctx = CGContext(data: nil, width: 360, height: 320, bitsPerComponent: 8,
    bytesPerRow: 1440, space: CGColorSpaceCreateDeviceRGB(),
    bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
ctx.translateBy(x: 0, y: 320); ctx.scaleBy(x: 1, y: -1)
ctx.translateBy(x: 8, y: 5); ctx.scaleBy(x: 1.1, y: 0.9)
let appearance = PetAppearance()
ctx.setFillColor(NSColor(srgbRed: 0.85, green: 0.65, blue: 0.42, alpha: 1).cgColor)
ctx.fill(CGRect(x: 150, y: 160, width: 30, height: 30))
let sample = appearance.shoulderColor(ctx, at: CGPoint(x: 160, y: 170)).usingColorSpace(.deviceRGB)!
precondition(abs(sample.redComponent - 0.85) < 0.01)
precondition(abs(sample.greenComponent - 0.65) < 0.01)
precondition(abs(sample.blueComponent - 0.42) < 0.01)
// Out-of-bounds or transparent pixels fall back safely to the base coat.
precondition(appearance.shoulderColor(ctx, at: CGPoint(x: -100, y: -100)) == appearance.fur)
let canvas = CGContext(data: nil, width: 100, height: 100, bitsPerComponent: 8,
    bytesPerRow: 400, space: CGColorSpaceCreateDeviceRGB(),
    bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
canvas.translateBy(x: 0, y: 100); canvas.scaleBy(x: 1, y: -1)
let corners = [CGPoint(x: 40, y: 10), CGPoint(x: 60, y: 10),
               CGPoint(x: 60, y: 80), CGPoint(x: 40, y: 80)]
// Real animated limbs and ellipses can have opposite winding directions.
for points in [corners, Array(corners.reversed())] {
    canvas.clear(CGRect(x: 0, y: 0, width: 100, height: 100))
    let arm = CGMutablePath(); arm.move(to: points[0])
    for point in points.dropFirst() { arm.addLine(to: point) }
    arm.closeSubpath()
    appearance.limb(canvas, path: arm, paw: CGRect(x: 38, y: 70, width: 24, height: 20),
                    start: CGPoint(x: 50, y: 10), end: CGPoint(x: 50, y: 80))
    let pixels = canvas.data!.assumingMemoryBound(to: UInt8.self)
    for y in 73...85 {
        for x in 46...54 {
            precondition(pixels[y * 400 + x * 4 + 3] == 255, "Hole in overlapping paw")
        }
    }
    precondition(pixels[3] == 0, "Outside silhouette must stay transparent")
    precondition(pixels[11 * 400 + 50 * 4 + 3] < 100, "Keep the soft shoulder blend")
}
''')
    executable = tmp_path / "shoulder-check"
    subprocess.run(["xcrun", "swiftc", "-O", *map(str, sorted((root / "native/kurocat").glob("*.swift"))),
                    str(harness), "-framework", "AppKit", "-framework", "QuartzCore", "-o", str(executable)],
                   check=True, capture_output=True, text=True)
    subprocess.run([str(executable)], check=True, capture_output=True, text=True)
