"""将完整宠物包中的动画转换为可分享的动作对象。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
import json
from pathlib import Path, PureWindowsPath

from PIL import Image, UnidentifiedImageError

from .package_validator import natural_sort_key


class SourceKind(StrEnum):
    PET_PACKAGE = "pet-package"
    ACTION_PACK = "action-pack"
    LEGACY_WORK_FINISH = "legacy-work-finish"
    SPRITESHEET = "spritesheet"


class ActionTransferError(ValueError):
    """来源宠物或动作定义无法安全转换。"""


class AmbiguousExchangeSourceError(ActionTransferError):
    """来源同时包含多个互斥的交换格式标记。"""


class UnknownExchangeSourceError(ActionTransferError):
    """来源没有可识别的 PetNest 格式。"""


@dataclass(frozen=True, slots=True)
class TransferAction:
    """一个动作及其原始定义和资源文件。"""

    name: str
    definition: dict[str, object]
    asset_paths: tuple[Path, ...]
    scope: str
    source_root: Path


def detect_source_kind(source: Path) -> SourceKind:
    """探测目录、ZIP 解包后的目录或单张 PNG/WebP 的来源类型。"""

    path = Path(source).expanduser()
    if path.is_file():
        if path.suffix.casefold() in {".png", ".webp"}:
            return SourceKind.SPRITESHEET
        from .exchange_source import ExchangeSource

        try:
            with ExchangeSource.open(path) as materialized:
                return _detect_directory_kind(materialized.root)
        except ActionTransferError:
            raise
        except Exception as error:
            raise UnknownExchangeSourceError(f"无法识别交换来源：{source}") from error
    if path.is_dir():
        return _detect_directory_kind(path.resolve())
    raise UnknownExchangeSourceError(f"交换来源不存在：{source}")


def extract_pet_actions(pet_root: Path) -> dict[str, TransferAction]:
    """读取 `pet.json`，保留动作原始字段并收集动作资源。"""

    root = Path(pet_root).expanduser().resolve()
    config = _read_json_object(root / "pet.json", "pet.json")
    animations = config.get("animations")
    if not isinstance(animations, Mapping):
        raise ActionTransferError("pet.json 的 animations 必须是对象")

    actions: dict[str, TransferAction] = {}
    for name, raw_definition in animations.items():
        if not isinstance(name, str) or not name.strip():
            raise ActionTransferError("动画名称必须是非空字符串")
        if not isinstance(raw_definition, Mapping):
            raise ActionTransferError(f"动画 {name} 的定义必须是对象")
        configured_path = raw_definition.get("path")
        animation_root = _safe_directory(root, configured_path, name)
        children = tuple(animation_root.iterdir())
        if any(item.is_symlink() for item in children):
            raise ActionTransferError(f"动画 {name} 不能包含符号链接")
        if any(item.is_dir() for item in children):
            raise ActionTransferError(f"动画 {name} 的 PNG 帧必须直接位于动作目录中")
        asset_paths = tuple(
            sorted(
                (item for item in children if item.is_file()),
                key=lambda item: item.relative_to(root).as_posix().casefold(),
            )
        )
        if not asset_paths:
            raise ActionTransferError(f"动画 {name} 没有可分享的资源")
        if any(item.suffix.casefold() != ".png" for item in asset_paths):
            raise ActionTransferError(f"动画 {name} 只能包含 PNG 帧")
        definition = json.loads(json.dumps(dict(raw_definition), ensure_ascii=False))
        actions[name] = TransferAction(
            name=name,
            definition=definition,
            asset_paths=asset_paths,
            scope=str(raw_definition.get("scope", "pet")),
            source_root=root,
        )
    return actions


def load_legacy_work_finish_pack(root: Path):
    """把旧版 `manifest.json` 下班包适配为两个标准全屏动作。"""

    from .action_pack import ActionPack, SourcePetInfo

    package_root = Path(root).expanduser().resolve()
    manifest = _read_json_object(package_root / "manifest.json", "manifest.json")
    name = manifest.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ActionTransferError("manifest.name 必须是非空字符串")
    canvas_value = manifest.get("canvas")
    if not isinstance(canvas_value, Mapping):
        raise ActionTransferError("manifest.canvas 必须是对象")
    width, height = canvas_value.get("width"), canvas_value.get("height")
    if any(isinstance(item, bool) or not isinstance(item, int) or item <= 0 for item in (width, height)):
        raise ActionTransferError("manifest.canvas 尺寸必须是正整数")
    phases: dict[str, tuple[Path, float, tuple[Path, ...], list[int] | None]] = {}
    phase_labels = ("walk", "lie_down") + (("lie_loop",) if "lie_loop" in manifest else ())
    for label in phase_labels:
        value = manifest.get(label)
        if not isinstance(value, Mapping):
            raise ActionTransferError(f"manifest.{label} 必须是对象")
        phase_path = _safe_directory(package_root, value.get("path"), label)
        fps = value.get("fps")
        if isinstance(fps, bool) or not isinstance(fps, (int, float)) or fps <= 0:
            raise ActionTransferError(f"manifest.{label}.fps 必须大于 0")
        frames = tuple(sorted((item for item in phase_path.iterdir() if item.is_file() and item.suffix.casefold() == ".png"), key=natural_sort_key))
        if not frames:
            raise ActionTransferError(f"{label} 没有 PNG 帧")
        for frame in frames:
            try:
                with Image.open(frame) as image:
                    image.load()
                    if "A" not in image.getbands() or image.size != (width, height):
                        raise ActionTransferError(f"PNG 帧 {frame.name} 必须是 {width}×{height} RGBA")
            except (OSError, UnidentifiedImageError) as error:
                raise ActionTransferError(f"PNG 帧 {frame.name} 无法读取：{error}") from error
        durations = value.get("frame_durations_ms")
        parsed_durations: list[int] | None = None
        if durations is not None:
            if not isinstance(durations, list) or len(durations) != len(frames) or any(
                isinstance(item, bool) or not isinstance(item, int) or item <= 0 for item in durations
            ):
                raise ActionTransferError(f"{label} 的逐帧时长必须与 PNG 帧一一对应")
            parsed_durations = list(durations)
        phases[label] = (phase_path, float(fps), frames, parsed_durations)
    actions: dict[str, TransferAction] = {}
    for label, action_name, loop in (
        ("walk", "work_finish_walk", True),
        ("lie_down", "work_finish_lie_down", False),
        ("lie_loop", "work_finish_lie_loop", True),
    ):
        if label not in phases:
            continue
        phase_path, fps, frames, durations = phases[label]
        definition: dict[str, object] = {
            "path": phase_path.relative_to(package_root).as_posix(),
            "scope": "fullscreen",
            "canvas": {"width": width, "height": height},
            "fps": fps,
            "loop": loop,
            "priority": 20,
        }
        if durations is not None:
            definition["frame_durations_ms"] = durations
        actions[action_name] = TransferAction(
            name=action_name,
            definition=definition,
            asset_paths=frames,
            scope="fullscreen",
            source_root=package_root,
        )
    return ActionPack(
        name=name.strip(),
        source_pet=SourcePetInfo("legacy-work-finish", name.strip(), "legacy"),
        actions=actions,
        root=package_root,
    )


def _detect_directory_kind(root: Path) -> SourceKind:
    markers = [
        (root / "pet.json", SourceKind.PET_PACKAGE),
        (root / "petnest-action-pack.json", SourceKind.ACTION_PACK),
        (root / "manifest.json", SourceKind.LEGACY_WORK_FINISH),
    ]
    present = [kind for marker, kind in markers if marker.is_file()]
    if len(present) > 1:
        raise AmbiguousExchangeSourceError("来源同时包含多个格式清单，无法判断导入类型")
    if present:
        return present[0]
    spritesheets = tuple(
        item for item in root.iterdir()
        if item.is_file() and item.suffix.casefold() in {".png", ".webp"}
    )
    if len(spritesheets) == 1:
        return SourceKind.SPRITESHEET
    raise UnknownExchangeSourceError("来源不是完整宠物、动作包、旧版下班动画包或精灵图")


def _read_json_object(path: Path, label: str) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ActionTransferError(f"{label} 无法读取：{error}") from error
    if not isinstance(value, dict):
        raise ActionTransferError(f"{label} 顶层必须是对象")
    return value


def _safe_directory(root: Path, configured_path: object, name: str) -> Path:
    if not isinstance(configured_path, str) or not configured_path.strip():
        raise ActionTransferError(f"动画 {name} 的路径必须是非空相对路径")
    candidate = Path(configured_path)
    if candidate.is_absolute() or PureWindowsPath(configured_path).is_absolute() or PureWindowsPath(configured_path).drive:
        raise ActionTransferError(f"动画 {name} 的路径必须位于宠物包内")
    resolved = (root / candidate).resolve()
    if not resolved.is_relative_to(root) or not resolved.is_dir():
        raise ActionTransferError(f"动画 {name} 的路径逃逸或目录不存在")
    return resolved


__all__ = [
    "ActionTransferError",
    "AmbiguousExchangeSourceError",
    "SourceKind",
    "TransferAction",
    "UnknownExchangeSourceError",
    "detect_source_kind",
    "extract_pet_actions",
    "load_legacy_work_finish_pack",
]
