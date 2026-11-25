"""Preview the real library UI with isolated settings/pets and no global input hook.

PYTHONPATH=src .venv/bin/python tools/preview_pet_library.py
Add --screenshots DIR to render review images and exit (supports offscreen Qt).
"""

import argparse
import shutil
import tempfile
from pathlib import Path

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QApplication

from petnest.core.package_loader import PackageLoader
from petnest.core.cat_appearance import PRESETS, apply_preset
from petnest.ui.keyboard_preview_input import preview_key
from petnest.ui.pet_action_exchange_dialog import PetActionExchangeDialog


class PreviewInput(QObject):
    def __init__(self, page):
        super().__init__(page)
        self.page = page

    def eventFilter(self, watched, event):
        if (
            watched is QApplication.focusWidget()
            and self.page.isAncestorOf(watched)
            and event.type() in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease)
        ):
            key = preview_key(event)
            if key is not None:
                self.page.cat_key_event(key, event.type() == QEvent.Type.KeyPress)
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--screenshots", type=Path)
    parser.add_argument("--appearance", action="store_true", help="直接打开自定义配色预览")
    parser.add_argument("--preset", choices=list(PRESETS), help="从指定配色开始预览，不修改应用设置")
    args = parser.parse_args()
    app = QApplication([])
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="petnest-library-preview-") as temporary:
        pets = Path(temporary)
        for name in ("keyboard_cat", "sample_pet"):
            shutil.copytree(root / "pets" / name, pets / name)
        packages = PackageLoader().discover(pets)
        values = {
            p.identifier: {"keys": True, "look": True, "petting": True, "scale": 1.0}
            for p in packages
        }
        status = ["监听正常"]
        if args.preset:
            values["keyboard_cat"] = apply_preset(values["keyboard_cat"], args.preset)
        dialog = PetActionExchangeDialog(
            packages,
            pets,
            current_pet_id="keyboard_cat",
            preferences=lambda key: values[key],
            save_preferences=lambda key, value: values.update({key: value}),
            use_pet=lambda _: True,
            input_status=lambda: status[0],
        )
        dialog.setWindowTitle("PetNest · 页面预览（不修改当前应用和授权）")
        dialog.page_subtitle.setText("界面预览 · 换装与设置仅在此窗口生效")
        page = dialog.my_pets_page
        local_input = PreviewInput(page)
        app.installEventFilter(local_input)
        dialog.show()
        if args.appearance and not args.screenshots:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(100, page._customize)
        if args.screenshots:
            args.screenshots.mkdir(parents=True, exist_ok=True)
            app.processEvents()
            dialog.grab().save(str(args.screenshots / "pet-library-connected.png"))
            page.coat.setCurrentIndex(1)
            page.keyboard.setCurrentIndex(1)
            app.processEvents()
            dialog.grab().save(str(args.screenshots / "pet-library-siamese.png"))
            status[0] = "需要允许 PetNest 的输入监控"
            page._sync_status()
            app.processEvents()
            dialog.grab().save(str(args.screenshots / "pet-library-permission.png"))
            dialog.resize(1180, 680)
            app.processEvents()
            dialog.grab().save(str(args.screenshots / "pet-library-small.png"))
            from petnest.ui.cat_appearance_dialog import CatAppearanceDialog
            for name, preset in (("shaded", "金色渐层"), ("point-white", "灰棕重点加白"), ("tabby-white", "棕灰虎斑加白"), ("tortie", "玳瑁琥珀")):
                editor = CatAppearanceDialog(apply_preset(values["keyboard_cat"], preset), dialog)
                editor.show()
                app.processEvents()
                editor.timer.stop()
                editor.grab().save(str(args.screenshots / f"pet-appearance-{name}.png"))
                editor.close()
            dialog.close()
            return 0
        return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
