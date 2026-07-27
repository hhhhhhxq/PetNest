"""用 Pillow 程序化生成透明、可分发的 PetNest 示例宠物。"""

from __future__ import annotations

import argparse
import json
from math import sin
from pathlib import Path
from typing import Sequence

from PIL import Image, ImageDraw

CANVAS_SIZE = 256
ACTION_SPECS: dict[str, tuple[int, bool, int, bool]] = {
    "idle": (4, True, 8, True),
    "hover": (4, True, 10, True),
    "click": (3, False, 12, False),
    "drag": (3, True, 10, False),
    "drop": (3, False, 12, False),
    "working": (4, True, 10, True),
    "waiting": (4, True, 8, True),
    "success": (4, False, 12, False),
    "error": (4, False, 12, False),
}


def create_sample_pet(destination: Path) -> Path:
    """生成完整 ``sample_pet``；所有帧均由本脚本直接创建。"""
    root = destination.resolve()
    root.mkdir(parents=True, exist_ok=True)
    config = _config()
    (root / "pet.json").write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    preview: Image.Image | None = None
    for action, (count, _loop, _fps, _interruptible) in ACTION_SPECS.items():
        directory = root / "animations" / action
        directory.mkdir(parents=True, exist_ok=True)
        for index in range(count):
            frame = _draw_frame(action, index, count)
            frame.save(directory / f"{index + 1:03d}.png")
            if action == "idle" and index == 0:
                preview = frame
    if preview is not None:
        preview.save(root / "preview.png")
    return root


def _config() -> dict[str, object]:
    animations: dict[str, object] = {}
    for name, (_count, loop, fps, interruptible) in ACTION_SPECS.items():
        item: dict[str, object] = {
            "path": f"animations/{name}",
            "fps": fps,
            "loop": loop,
            "priority": {"idle": 10, "hover": 30, "click": 50, "drag": 80, "drop": 70, "working": 60, "waiting": 60, "success": 100, "error": 100}[name],
            "interruptible": interruptible,
        }
        if not loop:
            item["next"] = "context"
        animations[name] = item
    return {
        "schema_version": 1,
        "id": "sample_pet",
        "name": "Sample Pet",
        "version": "1.0.0",
        "author": "PetNest",
        "description": "由 Pillow 程序化生成的透明示例宠物。",
        "canvas": {"width": CANVAS_SIZE, "height": CANVAS_SIZE},
        "display": {"default_scale": 0.6, "min_scale": 0.25, "max_scale": 2.0, "alpha_hit_test_threshold": 10},
        "animations": animations,
        "bindings": {
            "mouse.enter": "hover", "mouse.leave": "idle", "mouse.click": "click",
            "mouse.drag_start": "drag", "mouse.drag_end": "drop",
            "agent.working": "working", "agent.waiting": "waiting",
            "agent.success": "success", "agent.error": "error",
        },
        "fallbacks": {
            "hover": ["idle"], "click": ["hover", "idle"], "drag": ["hover", "idle"],
            "drop": ["hover", "idle"], "working": ["idle"], "waiting": ["idle"],
            "success": ["idle"], "error": ["idle"],
        },
        "idle_variants": [{"animation": "idle", "weight": 100}],
    }


def _draw_frame(action: str, index: int, count: int) -> Image.Image:
    """绘制简洁圆形宠物，不依赖任何来源不明的二进制素材。"""
    image = Image.new("RGBA", (CANVAS_SIZE, CANVAS_SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    phase = index / max(1, count - 1)
    bob = int(sin(phase * 6.283) * 6)
    colour = {
        "idle": (102, 184, 255, 255), "hover": (142, 211, 255, 255), "click": (255, 191, 96, 255),
        "drag": (164, 130, 255, 255), "drop": (133, 201, 166, 255), "working": (94, 156, 255, 255),
        "waiting": (151, 164, 184, 255), "success": (85, 201, 122, 255), "error": (239, 103, 103, 255),
    }[action]
    cx, cy = CANVAS_SIZE // 2, CANVAS_SIZE // 2 + bob
    radius = 76 + (5 if action == "hover" else 0)
    draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=colour, outline=(255, 255, 255, 220), width=5)
    eye_y = cy - 12
    if action == "click":
        draw.arc((cx - 44, eye_y - 7, cx - 10, eye_y + 20), 180, 350, fill=(20, 45, 80, 255), width=5)
        draw.arc((cx + 10, eye_y - 7, cx + 44, eye_y + 20), 190, 360, fill=(20, 45, 80, 255), width=5)
    else:
        draw.ellipse((cx - 42, eye_y - 12, cx - 20, eye_y + 14), fill=(20, 45, 80, 255))
        draw.ellipse((cx + 20, eye_y - 12, cx + 42, eye_y + 14), fill=(20, 45, 80, 255))
    draw.arc((cx - 30, cy + 8, cx + 30, cy + 42), 10, 170, fill=(20, 45, 80, 255), width=5)
    if action == "success":
        draw.line((cx - 15, cy - 85, cx - 2, cy - 72, cx + 24, cy - 104), fill=(255, 255, 255, 255), width=8)
    if action == "error":
        draw.line((cx - 16, cy - 100, cx + 16, cy - 68), fill=(255, 255, 255, 255), width=7)
        draw.line((cx + 16, cy - 100, cx - 16, cy - 68), fill=(255, 255, 255, 255), width=7)
    return image


def main(arguments: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成 PetNest sample_pet")
    parser.add_argument("destination", nargs="?", default="pets/sample_pet", help="目标目录")
    args = parser.parse_args(arguments)
    print(f"已生成示例宠物：{create_sample_pet(Path(args.destination))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
