"""从平安猫视频构建可导入 PetNest 的全屏动作分享包。"""

from __future__ import annotations

from argparse import ArgumentParser
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import sys
import tempfile
from typing import Any
from zipfile import ZipFile

from PIL import Image, ImageDraw

try:  # OpenCV 只供素材构建工具使用，不是 PetNest 运行时依赖。
    import cv2
    import numpy as np
except ImportError:  # pragma: no cover - exercised only on a machine without the tool extras.
    cv2 = None
    np = None


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
REMBG_PATH = os.environ.get("PETNEST_REMBG_PATH")
if REMBG_PATH and REMBG_PATH not in sys.path:
    sys.path.insert(0, REMBG_PATH)

CANVAS = (960, 540)
OUTPUT_FPS = 12.0
WALK_SECONDS = 4.0
LIE_END_SECONDS = 8.5
MAX_TARGET_BYTES = 60 * 1024 * 1024
MAX_UNPACKED_BYTES = 128 * 1024 * 1024
_REMBG_SESSION: Any | None = None
_REMBG_REMOVE: Any | None = None

# 源视频坐标中的少量人工关键框。框覆盖主体与很窄的接触区域，帧间按时间插值。
DEFAULT_BBOX_KEYFRAMES: tuple[tuple[float, tuple[int, int, int, int]], ...] = (
    (0.0, (0, 190, 610, 450)),
    (1.0, (70, 190, 650, 450)),
    (2.0, (100, 180, 760, 460)),
    (3.0, (140, 120, 740, 510)),
    (4.0, (280, 130, 570, 500)),
    (5.0, (100, 250, 880, 390)),
    (6.0, (0, 250, 960, 390)),
    (7.0, (0, 250, 1000, 390)),
    (8.0, (200, 240, 780, 410)),
    (8.5, (220, 240, 760, 410)),
)


@dataclass(frozen=True, slots=True)
class ProcessedFrame:
    """一个已稳定到目标画布的透明帧。"""

    timestamp: float
    image: Image.Image


def sample_indices(frame_count: int, source_fps: float, output_fps: float) -> list[int]:
    """按输出 FPS 采样源帧，去重并始终保留最后一个未越界的时间点。"""

    if frame_count <= 0 or source_fps <= 0 or output_fps <= 0:
        raise ValueError("视频帧数和 FPS 必须为正数")
    step = source_fps / output_fps
    count = math.ceil(frame_count / step)
    result: list[int] = []
    for position in range(count):
        index = min(frame_count - 1, round(position * step))
        if not result or result[-1] != index:
            result.append(index)
    return result


def split_phase_indices(
    indices: list[int],
    *,
    fps: float,
    walk_seconds: float = WALK_SECONDS,
    lie_end_seconds: float | None = None,
) -> tuple[list[int], list[int]]:
    """按输出时间线拆出行走和躺下阶段。"""

    if fps <= 0 or walk_seconds < 0:
        raise ValueError("阶段时间和 FPS 必须有效")
    walk_end = min(len(indices), round(walk_seconds * fps))
    lie_end = len(indices) if lie_end_seconds is None else min(len(indices), round(lie_end_seconds * fps))
    if lie_end < walk_end:
        lie_end = walk_end
    return indices[:walk_end], indices[walk_end:lie_end]


def frame_durations_ms(count: int, fps: float) -> list[int]:
    """用累计四舍五入生成总时长精确的正整数毫秒数组。"""

    if count <= 0 or fps <= 0:
        raise ValueError("帧数和 FPS 必须为正数")
    return [
        max(1, round((index + 1) * 1000 / fps) - round(index * 1000 / fps))
        for index in range(count)
    ]


def build_manifest(
    *,
    name: str,
    canvas: tuple[int, int],
    walk_count: int,
    lie_count: int,
) -> dict[str, Any]:
    """构建标准动作分享清单；资源路径由导出器重写。"""

    width, height = canvas
    return {
        "type": "petnest-action-pack",
        "schema_version": 1,
        "name": name,
        "source_pet": {
            "id": "pingan_fullscreen_source",
            "name": "平安",
            "version": "1.0.0",
        },
        "description": "平安猫透明全屏下班动画",
        "animations": {
            "work_finish_walk": {
                "path": "animations/work_finish_walk",
                "scope": "fullscreen",
                "canvas": {"width": width, "height": height},
                "fps": OUTPUT_FPS,
                "loop": True,
                "priority": 20,
                "entrance_direction": "left",
                "frame_durations_ms": frame_durations_ms(walk_count, OUTPUT_FPS),
            },
            "work_finish_lie_down": {
                "path": "animations/work_finish_lie_down",
                "scope": "fullscreen",
                "canvas": {"width": width, "height": height},
                "fps": OUTPUT_FPS,
                "loop": False,
                "priority": 20,
                "frame_durations_ms": frame_durations_ms(lie_count, OUTPUT_FPS),
            },
        },
    }


def _require_cv2() -> None:
    if cv2 is None or np is None:
        raise RuntimeError(
            "素材构建需要 OpenCV 和 NumPy；请安装 opencv-python-headless 与 numpy 后重试"
        )


def _rembg_remove() -> Any | None:
    """按需加载可选 U²-Net 抠图后端；未安装时返回 None 让调用方回退。"""

    global _REMBG_SESSION, _REMBG_REMOVE
    if _REMBG_REMOVE is not None:
        return _REMBG_REMOVE
    try:
        from rembg import new_session, remove
    except ImportError:
        return None
    _REMBG_SESSION = new_session("u2netp")
    _REMBG_REMOVE = remove
    return _REMBG_REMOVE


def _extract_rembg_alpha(frame_bgr: Any) -> Any | None:
    remove = _rembg_remove()
    if remove is None:
        return None
    _require_cv2()
    rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    mask_image = remove(Image.fromarray(rgb), session=_REMBG_SESSION, only_mask=True)
    alpha = np.asarray(mask_image.convert("L"), dtype=np.uint8)
    return cv2.GaussianBlur(alpha, (0, 0), 0.45)


def _interpolate_bbox(timestamp: float) -> tuple[int, int, int, int]:
    if timestamp <= DEFAULT_BBOX_KEYFRAMES[0][0]:
        return DEFAULT_BBOX_KEYFRAMES[0][1]
    for (left_time, left_box), (right_time, right_box) in zip(
        DEFAULT_BBOX_KEYFRAMES,
        DEFAULT_BBOX_KEYFRAMES[1:],
    ):
        if timestamp <= right_time:
            progress = (timestamp - left_time) / (right_time - left_time)
            return tuple(
                round(left_value + (right_value - left_value) * progress)
                for left_value, right_value in zip(left_box, right_box)
            )  # type: ignore[return-value]
    return DEFAULT_BBOX_KEYFRAMES[-1][1]


def _clamp_bbox(bbox: tuple[int, int, int, int], width: int, height: int) -> tuple[int, int, int, int]:
    x, y, box_width, box_height = bbox
    x = max(0, min(width - 2, x))
    y = max(0, min(height - 2, y))
    box_width = max(2, min(width - x, box_width))
    box_height = max(2, min(height - y, box_height))
    return x, y, box_width, box_height


def extract_alpha(frame_bgr: Any, bbox: tuple[int, int, int, int], background_bgr: Any | None = None) -> Any:
    """用 GrabCut 取得猫主体及其近身软阴影的 alpha。"""

    _require_cv2()
    rembg_alpha = _extract_rembg_alpha(frame_bgr)
    if rembg_alpha is not None:
        return rembg_alpha
    original_height, original_width = frame_bgr.shape[:2]
    scale = min(1.0, 640 / max(original_width, original_height))
    if scale < 1.0:
        work_frame = cv2.resize(
            frame_bgr,
            (round(original_width * scale), round(original_height * scale)),
            interpolation=cv2.INTER_AREA,
        )
        work_bbox = tuple(round(value * scale) for value in bbox)
    else:
        work_frame = frame_bgr
        work_bbox = bbox
    work_background = None
    if background_bgr is not None:
        work_background = cv2.resize(
            background_bgr,
            (work_frame.shape[1], work_frame.shape[0]),
            interpolation=cv2.INTER_AREA,
        )
    height, width = work_frame.shape[:2]
    x, y, box_width, box_height = _clamp_bbox(work_bbox, width, height)
    mask = np.full((height, width), cv2.GC_BGD, dtype=np.uint8)
    inset_x = max(3, box_width // 14)
    inset_y = max(3, box_height // 14)
    inner_x1 = min(width - 1, x + inset_x)
    inner_y1 = min(height - 1, y + inset_y)
    inner_x2 = max(inner_x1 + 1, min(width, x + box_width - inset_x))
    inner_y2 = max(inner_y1 + 1, min(height, y + box_height - inset_y))
    mask[inner_y1:inner_y2, inner_x1:inner_x2] = cv2.GC_PR_FGD
    hsv = cv2.cvtColor(work_frame, cv2.COLOR_BGR2HSV)
    saturation = hsv[:, :, 1]
    value = hsv[:, :, 2]
    yy, xx = np.ogrid[:height, :width]
    colour_core = (
        (saturation > 45)
        & (value < 245)
        & (xx >= x)
        & (xx < x + box_width)
        & (yy >= y)
        & (yy < y + box_height)
    )
    difference = None
    if work_background is not None:
        difference = cv2.cvtColor(cv2.absdiff(work_frame, work_background), cv2.COLOR_BGR2GRAY)
        inside = (xx >= x) & (xx < x + box_width) & (yy >= y) & (yy < y + box_height)
        foreground_signal = (difference > 20) & inside
        background_signal = (difference < 6) & inside
        colour_core = colour_core | foreground_signal
        mask[background_signal] = cv2.GC_BGD
    mask[colour_core] = cv2.GC_FGD
    background_model = np.zeros((1, 65), np.float64)
    foreground_model = np.zeros((1, 65), np.float64)
    try:
        cv2.grabCut(
            work_frame,
            mask,
            (x, y, box_width, box_height),
            background_model,
            foreground_model,
            3,
            cv2.GC_INIT_WITH_MASK,
        )
    except cv2.error as error:
        raise RuntimeError(f"GrabCut 无法处理 bbox={x,y,box_width,box_height}: {error}") from error
    binary = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)
    binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    core = colour_core.astype(np.uint8) * 255
    if int(cv2.countNonZero(core)) >= 50:
        core = cv2.dilate(core, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (21, 21)))
        binary = cv2.bitwise_and(binary, core)
    if difference is not None:
        difference_signal = np.where(difference > 14, 255, 0).astype(np.uint8)
        difference_signal = cv2.dilate(
            difference_signal,
            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (21, 21)),
        )
        binary = cv2.bitwise_and(binary, difference_signal)
    alpha = cv2.GaussianBlur(binary, (0, 0), 0.9)
    alpha[: max(0, y - 24), :] = 0
    alpha[min(height, y + box_height + 32) :, :] = 0
    alpha[:, : max(0, x - 36)] = 0
    alpha[:, min(width, x + box_width + 36) :] = 0
    if scale < 1.0:
        alpha = cv2.resize(alpha, (original_width, original_height), interpolation=cv2.INTER_LINEAR)
    return alpha


def stabilize_rgba(
    frame_bgr: Any,
    alpha: Any,
    *,
    canvas: tuple[int, int] = CANVAS,
    anchor_x: int | None = None,
    baseline_y: int | None = None,
) -> Image.Image:
    """缩放到透明画布，并把主体锚定到统一中心与落地点。"""

    _require_cv2()
    canvas_width, canvas_height = canvas
    source_height, source_width = frame_bgr.shape[:2]
    scaled_bgr = cv2.resize(frame_bgr, (canvas_width, canvas_height), interpolation=cv2.INTER_AREA)
    scaled_alpha = cv2.resize(alpha, (canvas_width, canvas_height), interpolation=cv2.INTER_LINEAR)
    visible = cv2.findNonZero((scaled_alpha > 24).astype(np.uint8))
    if visible is None:
        return Image.new("RGBA", canvas, (0, 0, 0, 0))
    x, y, width, height = cv2.boundingRect(visible)
    anchor_x = canvas_width // 2 if anchor_x is None else anchor_x
    baseline_y = canvas_height - 70 if baseline_y is None else baseline_y
    shift_x = int(round(anchor_x - (x + width / 2)))
    shift_y = int(round(baseline_y - (y + height)))
    rgba = np.zeros((canvas_height, canvas_width, 4), dtype=np.uint8)
    rgba[:, :, :3] = cv2.cvtColor(scaled_bgr, cv2.COLOR_BGR2RGB)
    rgba[:, :, 3] = scaled_alpha
    matrix = np.float32([[1, 0, shift_x], [0, 1, shift_y]])
    shifted = cv2.warpAffine(
        rgba,
        matrix,
        (canvas_width, canvas_height),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0, 0, 0, 0),
    )
    return Image.fromarray(shifted)


def _read_selected_frames(source: Path, indices: list[int]) -> dict[int, Any]:
    _require_cv2()
    capture = cv2.VideoCapture(str(source))
    if not capture.isOpened():
        raise RuntimeError(f"无法打开视频：{source}")
    selected = set(indices)
    frames: dict[int, Any] = {}
    index = 0
    try:
        while selected:
            ok, frame = capture.read()
            if not ok:
                break
            if index in selected:
                frames[index] = frame
                selected.remove(index)
            index += 1
    finally:
        capture.release()
    missing = [index for index in indices if index not in frames]
    if missing:
        raise RuntimeError(f"视频读取不完整，缺少帧：{missing[:5]}")
    return frames


def _build_background(frames: list[Any]) -> Any:
    """用行走阶段的时间中值恢复浅色墙面/地面的背景参考。"""

    _require_cv2()
    if not frames:
        raise ValueError("至少需要一帧才能建立背景")
    sample = frames[:: max(1, len(frames) // 24)]
    return np.median(np.stack(sample, axis=0), axis=0).astype(np.uint8)


def _write_png_frames(frames: list[ProcessedFrame], root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for index, processed in enumerate(frames, start=1):
        processed.image.save(root / f"{index:03d}.png", format="PNG", optimize=True)


def _write_contact_sheet(
    walk: list[ProcessedFrame],
    lie_down: list[ProcessedFrame],
    destination: Path,
) -> None:
    samples = [*walk[:: max(1, len(walk) // 6)], *lie_down[:: max(1, len(lie_down) // 6)]]
    samples = samples[:12]
    tile_width, tile_height = (320, 180)
    columns = 4
    rows = math.ceil(len(samples) / columns)
    sheet = Image.new("RGB", (tile_width * columns, tile_height * rows), (238, 238, 238))
    draw = ImageDraw.Draw(sheet)
    for index, frame in enumerate(samples):
        tile = Image.new("RGBA", (tile_width, tile_height), (238, 238, 238, 255))
        checker = Image.new("RGB", (tile_width, tile_height), (236, 236, 236))
        checker_draw = ImageDraw.Draw(checker)
        for y in range(0, tile_height, 24):
            for x in range(0, tile_width, 24):
                if (x // 24 + y // 24) % 2:
                    checker_draw.rectangle((x, y, x + 24, y + 24), fill=(205, 205, 205))
        preview = frame.image.copy()
        preview.thumbnail((tile_width, tile_height), Image.Resampling.LANCZOS)
        tile.alpha_composite(checker.convert("RGBA"))
        tile.alpha_composite(preview, ((tile_width - preview.width) // 2, (tile_height - preview.height) // 2))
        sheet.paste(tile.convert("RGB"), ((index % columns) * tile_width, (index // columns) * tile_height))
        draw.text(
            ((index % columns) * tile_width + 8, (index // columns) * tile_height + 8),
            f"{frame.timestamp:.2f}s",
            fill=(20, 20, 20),
            stroke_width=2,
            stroke_fill=(245, 245, 245),
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(destination, format="PNG", optimize=True)


def _write_source_pet(root: Path, manifest: dict[str, Any], walk_root: Path, lie_root: Path) -> None:
    idle_root = root / "animations/idle"
    idle_root.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", CANVAS, (0, 0, 0, 0)).save(idle_root / "001.png", format="PNG", optimize=True)
    source_manifest = {
        "schema_version": 1,
        "id": "pingan_fullscreen_source",
        "name": "平安",
        "version": "1.0.0",
        "canvas": {"width": CANVAS[0], "height": CANVAS[1]},
        "animations": {
            "idle": {"path": "animations/idle", "fps": 1, "loop": True},
            "work_finish_walk": manifest["animations"]["work_finish_walk"],
            "work_finish_lie_down": manifest["animations"]["work_finish_lie_down"],
        },
    }
    source_manifest["animations"]["work_finish_walk"]["path"] = walk_root.relative_to(root).as_posix()
    source_manifest["animations"]["work_finish_lie_down"]["path"] = lie_root.relative_to(root).as_posix()
    (root / "pet.json").write_text(json.dumps(source_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _zip_sizes(path: Path) -> tuple[int, int]:
    with ZipFile(path) as archive:
        return path.stat().st_size, sum(item.file_size for item in archive.infolist())


def build_from_video(source: Path, output: Path, contact_sheet: Path) -> tuple[int, int, int]:
    """构建 ZIP，返回行走帧数、躺下帧数和 ZIP 字节数。"""

    _require_cv2()
    source = source.expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"视频不存在：{source}")
    capture = cv2.VideoCapture(str(source))
    if not capture.isOpened():
        raise RuntimeError(f"无法打开视频：{source}")
    try:
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        source_fps = float(capture.get(cv2.CAP_PROP_FPS))
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    finally:
        capture.release()
    if (width, height) != (1280, 720) or abs(source_fps - 24.0) > 0.1:
        raise RuntimeError(f"源视频规格应为 1280×720、24 fps，实际为 {width}×{height}、{source_fps:g} fps")
    indices = sample_indices(frame_count, source_fps, OUTPUT_FPS)
    walk_indices, lie_indices = split_phase_indices(
        indices,
        fps=OUTPUT_FPS,
        walk_seconds=WALK_SECONDS,
        lie_end_seconds=LIE_END_SECONDS,
    )
    source_frames = _read_selected_frames(source, [*walk_indices, *lie_indices])
    background = None if _rembg_remove() is not None else _build_background([source_frames[index] for index in walk_indices])
    processed: dict[int, ProcessedFrame] = {}
    for index in [*walk_indices, *lie_indices]:
        timestamp = index / source_fps
        bgr = source_frames[index]
        alpha = extract_alpha(bgr, _interpolate_bbox(timestamp), background)
        processed[index] = ProcessedFrame(timestamp, stabilize_rgba(bgr, alpha))
    walk = [processed[index] for index in walk_indices]
    lie_down = [processed[index] for index in lie_indices]
    if not walk or not lie_down:
        raise RuntimeError("视频没有生成完整的行走和躺下阶段")

    output = output.expanduser()
    contact_sheet = contact_sheet.expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pingan-fullscreen-") as temporary_name:
        temporary_root = Path(temporary_name)
        source_root = temporary_root / "source"
        walk_root = source_root / "animations/work_finish_walk"
        lie_root = source_root / "animations/work_finish_lie_down"
        _write_png_frames(walk, walk_root)
        _write_png_frames(lie_down, lie_root)
        manifest = build_manifest(
            name="平安全屏动画",
            canvas=CANVAS,
            walk_count=len(walk),
            lie_count=len(lie_down),
        )
        _write_source_pet(source_root, manifest, walk_root, lie_root)
        from petnest.core.action_pack import export_action_pack

        export_action_pack(
            source_root,
            ["work_finish_walk", "work_finish_lie_down"],
            output,
            name="平安全屏动画",
            author="PetNest",
            description="平安猫透明全屏下班动画",
        )
    _write_contact_sheet(walk, lie_down, contact_sheet)
    zipped_bytes, unpacked_bytes = _zip_sizes(output)
    if zipped_bytes > MAX_TARGET_BYTES:
        raise RuntimeError(f"ZIP 体积 {zipped_bytes / 1024 / 1024:.1f} MB 超过 60 MB 目标")
    if unpacked_bytes > MAX_UNPACKED_BYTES:
        raise RuntimeError(f"ZIP 解包体积 {unpacked_bytes / 1024 / 1024:.1f} MB 超过 128 MB 限制")
    return len(walk), len(lie_down), zipped_bytes


def main() -> int:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="源 MP4 路径")
    parser.add_argument("--output", type=Path, default=Path("artifacts/平安全屏动画.zip"))
    parser.add_argument("--contact-sheet", type=Path, default=Path("artifacts/平安全屏动画-contact-sheet.png"))
    args = parser.parse_args()
    try:
        walk_count, lie_count, zipped_bytes = build_from_video(args.source, args.output, args.contact_sheet)
    except (FileNotFoundError, RuntimeError, ValueError) as error:
        print(f"构建失败：{error}", file=sys.stderr)
        return 1
    print(
        f"已生成 {args.output}：行走 {walk_count} 帧，躺下 {lie_count} 帧，"
        f"ZIP {zipped_bytes / 1024 / 1024:.1f} MB；关键帧图 {args.contact_sheet}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
