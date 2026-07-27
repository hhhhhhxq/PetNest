"""独立预览一个宠物动作，不启动完整桌宠。"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QApplication, QLabel

from petnest.core.animation_player import AnimationPlayer
from petnest.core.package_loader import PackageLoader


def _pixmap(frame: object) -> QPixmap:
    from PIL import Image

    if not isinstance(frame, Image.Image):
        return QPixmap()
    rgba = frame.convert("RGBA")
    image = QImage(rgba.tobytes("raw", "RGBA"), rgba.width, rgba.height, QImage.Format.Format_RGBA8888).copy()
    return QPixmap.fromImage(image)


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="独立预览 PetNest 动画")
    parser.add_argument("package", type=Path, help="宠物包目录")
    parser.add_argument("action", help="动作名")
    parser.add_argument("--fps", type=float, help="临时覆盖 FPS")
    args = parser.parse_args(arguments)
    try:
        package = PackageLoader().load(args.package)
        definition = package.animations[args.action]
    except (KeyError, OSError, ValueError) as error:
        print(f"无法预览：{error}", file=sys.stderr)
        return 1
    application = QApplication(sys.argv)
    player = AnimationPlayer()
    player.play(definition)
    fps = args.fps or definition.fps
    if fps <= 0:
        print("FPS 必须大于 0", file=sys.stderr)
        return 2
    label = QLabel()
    label.setWindowTitle(f"{package.name} · {args.action}（空格暂停）")
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setStyleSheet("background: #263238;")
    label.resize(package.canvas.width, package.canvas.height)

    def render() -> None:
        label.setPixmap(_pixmap(player.current_frame))
        player.advance()

    timer = QTimer(label)
    timer.timeout.connect(render)
    timer.start(max(1, round(1000 / fps)))
    render()
    label.show()
    print(f"预览：{args.action}，{len(definition.frames)} 帧，{fps:g} FPS，画布 {package.canvas.width}×{package.canvas.height}")
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
