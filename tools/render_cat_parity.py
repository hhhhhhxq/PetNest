"""Render repeatable cat scenarios, or compare artifacts from two real OS runners.

PYTHONPATH=src python tools/render_cat_parity.py render OUTPUT
python tools/render_cat_parity.py compare MAC_OUTPUT WINDOWS_OUTPUT
"""

import argparse
import json
from pathlib import Path


def render(output):
    from PySide6.QtWidgets import QApplication
    from petnest.core.cat_appearance import COATS, KEYBOARDS, PRESETS, apply_preset
    from petnest.core.cat_motion import CatMotion, Point, Spring, SpringPoint
    from petnest.core.keyboard_cat import cat_preferences
    from petnest.ui.cat_scene import CatScene

    app = QApplication.instance() or QApplication([])
    output.mkdir(parents=True, exist_ok=True)
    manifest = {}
    scenarios = [
        (
            f"preset-{i}-{keyboard}",
            cat_preferences({**apply_preset({}, name), "keyboard": keyboard}),
            "idle",
        )
        for i, name in enumerate(PRESETS)
        for keyboard in KEYBOARDS
    ]
    actions = ("left", "right", "typing", "mouse", "multi", "petting", "sleep", "reset")
    for coat in COATS:
        for action in actions:
            scenarios.append(
                (f"{coat}-{action}", cat_preferences({"coat": coat}), action)
            )
    for name, options, action in scenarios:
        motion, scene = CatMotion(), CatScene(options)
        for frame in range(1, 97):
            if action in ("typing", "multi", "reset") and frame in (12, 20, 28):
                motion.key_event({12: "A", 20: "S", 28: "ShiftL"}[frame], True)
            if action in ("typing", "reset") and frame == 40:
                for key in ("A", "S", "ShiftL"):
                    motion.key_event(key, False)
            if action == "reset" and frame == 50:
                motion.key_event("reset", False)
            if action in ("mouse", "multi") and frame == 10:
                motion.key_event("MouseLeft", True)
            if action == "mouse" and frame == 60:
                motion.key_event("MouseLeft", False)
            cursor = None
            if action == "left":
                cursor = Point(-200, 80)
            if action == "right":
                cursor = Point(600, 80)
            if action in ("mouse", "multi"):
                cursor = Point(-200 if frame % 12 < 6 else 600, 80)
            if action == "petting":
                cursor = Point(176 + frame % 4 * 5, 124)
            motion.step(
                1 / 30,
                cursor,
                petting=action == "petting",
                idle=90 if action == "sleep" else 0,
            )
            if frame not in (1, 18, 48, 96):
                continue
            filename = f"{name}-{frame:03}.png"
            assert scene.draw(motion).save(str(output / filename))
            snapshot = {}
            for key, value in vars(motion).items():
                if isinstance(value, Spring):
                    snapshot[key] = round(value.value, 8)
                elif isinstance(value, SpringPoint):
                    snapshot[key] = [round(value.point.x, 8), round(value.point.y, 8)]
                elif isinstance(value, (bool, float, int)):
                    snapshot[key] = round(value, 8)
            snapshot["keys"] = list(motion.keys)
            snapshot["badges"] = [
                (b.label, round(b.age, 8)) for b in motion.floatingKeycaps
            ]
            manifest[filename] = snapshot
    (output / "motion.json").write_text(
        json.dumps(manifest, sort_keys=True, indent=2), encoding="utf-8"
    )
    print(f"Rendered {len(manifest)} frames from {len(scenarios)} scenarios")
    app.quit()


def compare(a, b):
    from PIL import Image, ImageChops, ImageStat

    left = json.loads((a / "motion.json").read_text(encoding="utf-8"))
    right = json.loads((b / "motion.json").read_text(encoding="utf-8"))
    assert left == right, "Motion state differs between OS runners"
    worst_mean, worst_fraction = 0, 0
    for name in left:
        x, y = Image.open(a / name).convert("RGBA"), Image.open(b / name).convert(
            "RGBA"
        )
        assert x.size == y.size == (360, 320), name
        # Compare premultiplied pixels; hidden RGB in fully transparent pixels is irrelevant.
        diff = ImageChops.difference(x.convert("RGBa"), y.convert("RGBa"))
        mean = sum(ImageStat.Stat(diff).mean) / 4
        fraction = sum(max(pixel) > 16 for pixel in diff.getdata()) / (360 * 320)
        worst_mean, worst_fraction = max(worst_mean, mean), max(
            worst_fraction, fraction
        )
        assert (
            mean <= 0.15 and fraction <= 0.002
        ), f"{name}: MAE={mean:.4f}, changed={fraction:.4%}"
    print(
        f"PASS: {len(left)} frames; identical motion; worst MAE={worst_mean:.5f}, changed={worst_fraction:.5%}"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    draw = commands.add_parser("render")
    draw.add_argument("output", type=Path)
    check = commands.add_parser("compare")
    check.add_argument("first", type=Path)
    check.add_argument("second", type=Path)
    args = parser.parse_args()
    if args.command == "render":
        render(args.output)
    else:
        compare(args.first, args.second)


if __name__ == "__main__":
    main()
