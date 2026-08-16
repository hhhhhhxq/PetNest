"""将完整宠物包中的动画转换为可分享的动作对象。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
import json
from pathlib import Path, PureWindowsPath


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
    """探测目录、ZIP 解包后的目录或单张 PNG 的来源类型。"""

    path = Path(source).expanduser()
    if path.is_file():
        if path.suffix.casefold() == ".png":
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
        asset_paths = tuple(
            sorted(
                (item for item in animation_root.rglob("*") if item.is_file()),
                key=lambda item: item.relative_to(root).as_posix().casefold(),
            )
        )
        if not asset_paths:
            raise ActionTransferError(f"动画 {name} 没有可分享的资源")
        if any(item.is_symlink() for item in asset_paths):
            raise ActionTransferError(f"动画 {name} 不能包含符号链接")
        definition = json.loads(json.dumps(dict(raw_definition), ensure_ascii=False))
        actions[name] = TransferAction(
            name=name,
            definition=definition,
            asset_paths=asset_paths,
            scope=str(raw_definition.get("scope", "pet")),
            source_root=root,
        )
    return actions


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
    pngs = tuple(item for item in root.iterdir() if item.is_file() and item.suffix.casefold() == ".png")
    if len(pngs) == 1:
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
]
