"""从普通图片构建动作前的来源检查、排序和安全边界。"""

from __future__ import annotations

from dataclasses import dataclass
from contextlib import contextmanager
import os
from pathlib import Path
from collections.abc import Iterator, Sequence
import tempfile
import warnings

from PIL import Image, UnidentifiedImageError

from petnest.core.package_validator import natural_sort_key
from petnest.core.action_pack import ActionPack, SourcePetInfo
from petnest.core.action_slots import ActionSlot, resolve_slot
from petnest.core.action_transfer import TransferAction
from petnest.models.pet_package import PetPackage


MAX_FRAME_COUNT = 500
MAX_FRAME_EDGE = 8192
MAX_TOTAL_PIXELS = 512_000_000
_SUPPORTED_SUFFIXES = frozenset({".png", ".webp"})
_RESOURCE_MANIFESTS = ("petnest-action-pack.json", "pet.json", "manifest.json")
_WORK_FINISH_ACTIONS = frozenset(
    {"work_finish_walk", "work_finish_lie_down", "work_finish_lie_loop"}
)


class ImageActionSourceError(ValueError):
    """图片来源不可读取、不明确或超过安全限制。"""


class OversizedFrameConfirmationRequired(ImageActionSourceError):
    """普通动作存在超出目标宠物画布的图片，需要用户确认缩小。"""


@dataclass(frozen=True, slots=True)
class ImageActionFrame:
    path: Path
    width: int
    height: int
    has_alpha: bool

    @property
    def size(self) -> tuple[int, int]:
        return self.width, self.height


@dataclass(frozen=True, slots=True)
class ImageActionDraft:
    frames: tuple[ImageActionFrame, ...]
    source_label: str

    def reordered(self, ordered_paths: Sequence[Path]) -> "ImageActionDraft":
        order = tuple(Path(path).resolve() for path in ordered_paths)
        current = {frame.path: frame for frame in self.frames}
        if len(order) != len(current) or set(order) != set(current):
            raise ImageActionSourceError("调整后的帧必须与当前图片一一对应")
        return ImageActionDraft(tuple(current[path] for path in order), self.source_label)

    def without(self, path: Path) -> "ImageActionDraft":
        target = Path(path).resolve()
        frames = tuple(frame for frame in self.frames if frame.path != target)
        if len(frames) == len(self.frames):
            raise ImageActionSourceError("要删除的帧不在当前图片中")
        if not frames:
            raise ImageActionSourceError("动作至少需要一张图片")
        return ImageActionDraft(frames, self.source_label)


def inspect_image_files(paths: Sequence[Path]) -> ImageActionDraft:
    requested = tuple(Path(path).expanduser() for path in paths)
    if not requested:
        raise ImageActionSourceError("请至少选择一张 PNG 或 WebP 图片")
    if len(requested) > MAX_FRAME_COUNT:
        raise ImageActionSourceError(f"单个动作最多支持 {MAX_FRAME_COUNT} 帧")

    resolved: list[Path] = []
    seen: set[str] = set()
    for path in requested:
        _reject_link_ancestors(path)
        if _is_link_like(path):
            raise ImageActionSourceError(f"图片不能是符号链接或目录连接：{path.name}")
        if path.suffix.casefold() not in _SUPPORTED_SUFFIXES:
            raise ImageActionSourceError(f"只支持 PNG 或 WebP 图片：{path.name}")
        if not path.is_file():
            raise ImageActionSourceError(f"图片不存在或不是文件：{path}")
        candidate = path.resolve()
        key = os.path.normcase(str(candidate))
        if key in seen:
            raise ImageActionSourceError(f"选择了重复图片：{path.name}")
        seen.add(key)
        resolved.append(candidate)

    ordered = tuple(sorted(resolved, key=natural_sort_key))
    frames: list[ImageActionFrame] = []
    total_pixels = 0
    for path in ordered:
        width, height, has_alpha = _inspect_frame(path)
        total_pixels += width * height
        if total_pixels > MAX_TOTAL_PIXELS:
            raise ImageActionSourceError(
                f"全部帧解码像素超过安全上限 {MAX_TOTAL_PIXELS:,}，请减少图片数量或尺寸"
            )
        frames.append(ImageActionFrame(path, width, height, has_alpha))
    return ImageActionDraft(tuple(frames), f"{len(frames)} 张图片")


def inspect_image_folder(folder: Path) -> ImageActionDraft:
    source = Path(folder).expanduser()
    _reject_link_ancestors(source)
    if _is_link_like(source):
        raise ImageActionSourceError("图片文件夹不能是符号链接或目录连接")
    if not source.is_dir():
        raise ImageActionSourceError(f"图片文件夹不存在：{source}")
    root = source.resolve()
    for manifest in _RESOURCE_MANIFESTS:
        if (root / manifest).is_file():
            raise ImageActionSourceError("该文件夹是资源包，请切换到“从资源包提取动作”")
    try:
        children = tuple(root.iterdir())
    except OSError as error:
        raise ImageActionSourceError(f"无法读取图片文件夹：{error}") from error
    if any(child.is_dir() or _is_link_like(child) for child in children):
        raise ImageActionSourceError("文件夹包含子文件夹，请选择直接存放帧图片的具体动作文件夹")
    images = tuple(
        child
        for child in children
        if child.is_file() and child.suffix.casefold() in _SUPPORTED_SUFFIXES
    )
    if not images:
        raise ImageActionSourceError("文件夹中没有 PNG 或 WebP 图片")
    draft = inspect_image_files(images)
    return ImageActionDraft(draft.frames, root.name or str(root))


@contextmanager
def build_image_action_pack(
    package: PetPackage,
    slot: ActionSlot,
    draft: ImageActionDraft,
    *,
    fps: float,
    fit_oversized: bool = False,
    entrance_direction: str | None = None,
) -> Iterator[ActionPack]:
    if isinstance(fps, bool) or not isinstance(fps, (int, float)) or fps <= 0:
        raise ImageActionSourceError("动作 FPS 必须大于 0")
    if not draft.frames:
        raise ImageActionSourceError("动作至少需要一张图片")
    ordered_paths = tuple(frame.path for frame in draft.frames)
    draft = inspect_image_files(ordered_paths).reordered(ordered_paths)
    _validate_image_install_target(package.root)
    canvas = image_action_canvas(package, slot, draft)
    oversized = tuple(
        frame.path.name
        for frame in draft.frames
        if frame.width > canvas[0] or frame.height > canvas[1]
    )
    if oversized and not fit_oversized:
        raise OversizedFrameConfirmationRequired(
            f"图片超出目标动作画布，需要确认等比缩小：{', '.join(oversized)}"
        )
    output_pixels = canvas[0] * canvas[1] * len(draft.frames)
    if output_pixels > MAX_TOTAL_PIXELS:
        raise ImageActionSourceError(
            f"归一化后的输出画布总像素超过安全上限 {MAX_TOTAL_PIXELS:,}，请减少帧数或图片尺寸"
        )
    resolution = resolve_slot(package, slot)
    with tempfile.TemporaryDirectory(prefix="petnest-image-action-") as temporary:
        root = Path(temporary)
        animation_root = root / "animations" / resolution.action_name
        if not animation_root.resolve().is_relative_to(root.resolve()):
            raise ImageActionSourceError("动作输出路径超出临时目录")
        animation_root.mkdir(parents=True)
        output_paths: list[Path] = []
        for index, source_frame in enumerate(draft.frames, start=1):
            output = animation_root / f"{index:04d}.png"
            _render_frame(source_frame.path, output, canvas, fit_oversized=fit_oversized)
            output_paths.append(output)
        definition: dict[str, object] = {
            "path": f"animations/{resolution.action_name}",
            "fps": float(fps),
            "loop": slot.loop,
            "priority": slot.priority,
            "interruptible": slot.interruptible,
            "scope": slot.scope,
        }
        if slot.next_animation is not None:
            definition["next"] = slot.next_animation
        if slot.scope == "fullscreen":
            definition["canvas"] = {"width": canvas[0], "height": canvas[1]}
            direction = entrance_direction or slot.entrance_direction or "none"
            if direction not in {"left", "right", "none"}:
                raise ImageActionSourceError("全屏动作进入方向必须是 left、right 或 none")
            definition["entrance_direction"] = direction
        action = TransferAction(
            name=resolution.action_name,
            definition=definition,
            asset_paths=tuple(output_paths),
            scope=slot.scope,
            source_root=root,
        )
        bindings = dict([resolution.binding]) if resolution.binding is not None else {}
        fallbacks = (
            {resolution.action_name: ["idle"]}
            if slot.scope == "pet" and resolution.action_name != "idle"
            else {}
        )
        yield ActionPack(
            name=f"{package.name} · {slot.label}",
            source_pet=SourcePetInfo(package.identifier, package.name, package.version),
            actions={resolution.action_name: action},
            bindings=bindings,
            fallbacks=fallbacks,
            root=root,
        )


def image_action_canvas(
    package: PetPackage,
    slot: ActionSlot,
    draft: ImageActionDraft,
) -> tuple[int, int]:
    if slot.scope != "fullscreen":
        return package.canvas.width, package.canvas.height
    canvases = {
        (definition.canvas.width, definition.canvas.height)
        for name, definition in package.animations.items()
        if name in _WORK_FINISH_ACTIONS
        and definition.scope == "fullscreen"
        and definition.canvas is not None
    }
    if len(canvases) > 1:
        raise ImageActionSourceError("当前宠物的下班全屏动作画布不一致，请先修复现有动作")
    if canvases:
        return next(iter(canvases))
    return (
        max(frame.width for frame in draft.frames),
        max(frame.height for frame in draft.frames),
    )


def _inspect_frame(path: Path) -> tuple[int, int, bool]:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path) as image:
                image.load()
                width, height = image.size
                has_alpha = "A" in image.getbands() or "transparency" in image.info
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        raise ImageActionSourceError(f"无法读取图片 {path.name}：{error}") from error
    if width <= 0 or height <= 0:
        raise ImageActionSourceError(f"图片尺寸无效：{path.name}")
    if width > MAX_FRAME_EDGE or height > MAX_FRAME_EDGE:
        raise ImageActionSourceError(
            f"图片 {path.name} 超过单边 {MAX_FRAME_EDGE} 像素的安全上限"
        )
    return width, height, has_alpha


def _render_frame(
    source: Path,
    destination: Path,
    canvas_size: tuple[int, int],
    *,
    fit_oversized: bool,
) -> None:
    try:
        with Image.open(source) as opened:
            frame = opened.convert("RGBA")
    except (OSError, UnidentifiedImageError) as error:
        raise ImageActionSourceError(f"处理图片 {source.name} 失败：{error}") from error
    if frame.width > canvas_size[0] or frame.height > canvas_size[1]:
        if not fit_oversized:
            raise OversizedFrameConfirmationRequired(f"图片 {source.name} 需要确认等比缩小")
        frame.thumbnail(canvas_size, Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
    offset = ((canvas_size[0] - frame.width) // 2, (canvas_size[1] - frame.height) // 2)
    canvas.alpha_composite(frame, offset)
    canvas.save(destination, format="PNG")


def _is_link_like(path: Path) -> bool:
    try:
        return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())
    except OSError:
        return True


def _reject_link_ancestors(path: Path) -> None:
    current = Path(path).absolute()
    while True:
        if _is_link_like(current):
            raise ImageActionSourceError(f"图片来源路径的祖先不能是符号链接或目录连接：{current}")
        parent = current.parent
        if parent == current:
            return
        current = parent


def _validate_image_install_target(target: Path) -> None:
    raw = Path(target).expanduser()
    if _is_link_like(raw):
        raise ImageActionSourceError("目标宠物目录不能是符号链接或目录连接")
    if not raw.exists():
        return
    root = raw.resolve()
    try:
        for item in root.rglob("*"):
            if _is_link_like(item):
                raise ImageActionSourceError(f"目标宠物包含不安全的链接：{item.name}")
            if not item.resolve().is_relative_to(root):
                raise ImageActionSourceError(f"目标宠物路径超出宠物目录：{item.name}")
    except OSError as error:
        raise ImageActionSourceError(f"无法检查目标宠物目录：{error}") from error


__all__ = [
    "ImageActionDraft",
    "ImageActionFrame",
    "ImageActionSourceError",
    "OversizedFrameConfirmationRequired",
    "MAX_FRAME_COUNT",
    "MAX_FRAME_EDGE",
    "MAX_TOTAL_PIXELS",
    "inspect_image_files",
    "inspect_image_folder",
    "build_image_action_pack",
    "image_action_canvas",
]
