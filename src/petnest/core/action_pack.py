"""通用动作分享包的导出、读取和生命周期管理。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import json
import os
from pathlib import Path, PureWindowsPath
import re
import tempfile
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from .action_transfer import ActionTransferError, TransferAction
from .exchange_source import ExchangeSource


ACTION_PACK_MANIFEST = "petnest-action-pack.json"
ACTION_PACK_TYPE = "petnest-action-pack"
ACTION_PACK_SCHEMA_VERSION = 1
_SAFE_ACTION_NAME = re.compile(r"^[^\\/:*?\"<>|\x00-\x1f]+$")
_WINDOWS_RESERVED_NAMES = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}


class ActionPackError(ValueError):
    """动作分享包无效或无法安全生成。"""


@dataclass(frozen=True, slots=True)
class SourcePetInfo:
    identifier: str
    name: str
    version: str


@dataclass(slots=True)
class ActionPack:
    """已读取的动作包；ZIP 读取出的临时目录由 `close` 清理。"""

    name: str
    source_pet: SourcePetInfo
    actions: dict[str, TransferAction]
    bindings: dict[str, str] = field(default_factory=dict)
    fallbacks: dict[str, list[str]] = field(default_factory=dict)
    root: Path | None = None
    _source: ExchangeSource | None = field(default=None, repr=False)

    def close(self) -> None:
        if self._source is not None:
            self._source.__exit__(None, None, None)
            self._source = None

    def __enter__(self) -> "ActionPack":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def export_action_pack(
    pet_root: Path,
    selected_actions: Sequence[str],
    output: Path,
    *,
    include_bindings: bool = False,
    name: str | None = None,
    author: str | None = None,
    description: str | None = None,
) -> Path:
    """把指定动作和资源原子导出为一个通用动作 ZIP。"""

    root = Path(pet_root).expanduser().resolve()
    config = _read_json_object(root / "pet.json", "pet.json")
    try:
        from .action_transfer import extract_pet_actions

        available = extract_pet_actions(root)
    except ActionTransferError as error:
        raise ActionPackError(str(error)) from error
    selected = _unique_names(selected_actions)
    if not selected:
        raise ActionPackError("至少选择一个动作")
    missing = [item for item in selected if item not in available]
    if missing:
        raise ActionPackError(f"找不到要导出的动作：{', '.join(missing)}")

    source_info = SourcePetInfo(
        identifier=_required_string(config.get("id"), "pet.json.id"),
        name=str(config.get("name", config["id"])),
        version=str(config.get("version", "0.0.0")),
    )
    selected_map = {item: available[item] for item in selected}
    manifest = _manifest_for_export(
        config,
        source_info,
        selected_map,
        include_bindings=include_bindings,
        name=name or f"{source_info.name} 动作",
        author=author if author is not None else _optional_string(config.get("author")),
        description=description if description is not None else _optional_string(config.get("description")),
    )
    destination = Path(output).expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with ZipFile(temporary, "w", compression=ZIP_DEFLATED) as archive:
            archive.writestr(_zip_info(ACTION_PACK_MANIFEST), _json_bytes(manifest))
            for action_name in sorted(selected_map):
                action = selected_map[action_name]
                animation_root = _animation_root(action)
                for asset in sorted(action.asset_paths, key=lambda item: item.as_posix().casefold()):
                    relative = asset.relative_to(animation_root).as_posix()
                    archive_name = f"animations/{_safe_action_name(action_name)}/{relative}"
                    archive.write(asset, archive_name)
        os.replace(temporary, destination)
    except (OSError, ValueError) as error:
        if temporary.exists():
            temporary.unlink()
        raise ActionPackError(f"导出动作包失败：{error}") from error
    return destination


def load_action_pack(source: Path) -> ActionPack:
    """加载动作文件夹或 ZIP，并保留其资源目录直到 `close`。"""

    try:
        materialized = ExchangeSource.open(Path(source))
    except Exception as error:
        if isinstance(error, ActionPackError):
            raise
        raise ActionPackError(str(error)) from error
    try:
        root = materialized.root
        manifest = _read_json_object(root / ACTION_PACK_MANIFEST, ACTION_PACK_MANIFEST)
        if manifest.get("type") != ACTION_PACK_TYPE:
            raise ActionPackError("不是 PetNest 动作分享包")
        if manifest.get("schema_version") != ACTION_PACK_SCHEMA_VERSION:
            raise ActionPackError("动作分享包版本不受支持")
        source_pet = _source_pet_info(manifest.get("source_pet"))
        actions = _load_actions(root, manifest.get("animations"))
        bindings = _string_map(manifest.get("bindings"), "bindings")
        fallbacks = _string_list_map(manifest.get("fallbacks"), "fallbacks")
        result = ActionPack(
            name=str(manifest.get("name", source_pet.name)),
            source_pet=source_pet,
            actions=actions,
            bindings=bindings,
            fallbacks=fallbacks,
            root=root,
            _source=materialized,
        )
        return result
    except Exception:
        materialized.__exit__(None, None, None)
        raise


def _manifest_for_export(
    config: Mapping[str, object],
    source_pet: SourcePetInfo,
    actions: Mapping[str, TransferAction],
    *,
    include_bindings: bool,
    name: str,
    author: str | None,
    description: str | None,
) -> dict[str, object]:
    definitions: dict[str, object] = {}
    selected_names = set(actions)
    for action_name, action in actions.items():
        definition = json.loads(json.dumps(action.definition, ensure_ascii=False))
        definition["path"] = f"animations/{_safe_action_name(action_name)}"
        definitions[action_name] = definition
    manifest: dict[str, object] = {
        "type": ACTION_PACK_TYPE,
        "schema_version": ACTION_PACK_SCHEMA_VERSION,
        "name": name,
        "source_pet": {
            "id": source_pet.identifier,
            "name": source_pet.name,
            "version": source_pet.version,
        },
        "animations": definitions,
    }
    if author:
        manifest["author"] = author
    if description:
        manifest["description"] = description
    if include_bindings:
        bindings = _string_map(config.get("bindings"), "bindings")
        selected_bindings = {event: action for event, action in bindings.items() if action in selected_names}
        if selected_bindings:
            manifest["bindings"] = selected_bindings
        fallbacks = _string_list_map(config.get("fallbacks"), "fallbacks")
        selected_fallbacks = {
            action: [candidate for candidate in candidates if candidate in selected_names or candidate == "idle"]
            for action, candidates in fallbacks.items()
            if action in selected_names
        }
        if selected_fallbacks:
            manifest["fallbacks"] = selected_fallbacks
    return manifest


def _load_actions(root: Path, value: object) -> dict[str, TransferAction]:
    if not isinstance(value, Mapping) or not value:
        raise ActionPackError("动作分享包必须包含至少一个动作")
    actions: dict[str, TransferAction] = {}
    for name, raw_definition in value.items():
        if not isinstance(name, str) or not name.strip():
            raise ActionPackError("动作名称必须是非空字符串")
        _safe_action_name(name)
        if not isinstance(raw_definition, Mapping):
            raise ActionPackError(f"动作 {name} 的定义必须是对象")
        animation_root = _safe_directory(root, raw_definition.get("path"), name)
        children = tuple(animation_root.iterdir())
        if any(item.is_symlink() for item in children):
            raise ActionPackError(f"动作 {name} 不能包含符号链接")
        if any(item.is_dir() for item in children):
            raise ActionPackError(f"动作 {name} 的 PNG 帧必须直接位于动作目录中")
        assets = tuple(sorted((item for item in children if item.is_file()), key=lambda item: item.as_posix().casefold()))
        if not assets:
            raise ActionPackError(f"动作 {name} 没有资源")
        if any(item.suffix.casefold() != ".png" for item in assets):
            raise ActionPackError(f"动作 {name} 只能包含 PNG 帧")
        _validate_action_definition(name, raw_definition, len(assets))
        definition = json.loads(json.dumps(dict(raw_definition), ensure_ascii=False))
        actions[name] = TransferAction(
            name=name,
            definition=definition,
            asset_paths=assets,
            scope=str(raw_definition.get("scope", "pet")),
            source_root=root,
        )
    return actions


def _animation_root(action: TransferAction) -> Path:
    configured = action.definition.get("path")
    if not isinstance(configured, str):
        raise ActionPackError(f"动作 {action.name} 缺少资源路径")
    return (action.source_root / configured).resolve()


def _safe_directory(root: Path, configured: object, name: str) -> Path:
    if not isinstance(configured, str) or not configured.strip():
        raise ActionPackError(f"动作 {name} 的路径必须是非空相对路径")
    candidate = Path(configured)
    if candidate.is_absolute() or PureWindowsPath(configured).is_absolute() or PureWindowsPath(configured).drive:
        raise ActionPackError(f"动作 {name} 的路径必须位于分享包内")
    resolved = (root / candidate).resolve()
    if not resolved.is_relative_to(root) or not resolved.is_dir():
        raise ActionPackError(f"动作 {name} 的资源目录不存在或逃逸")
    return resolved


def _safe_action_name(name: str) -> str:
    stem = name.split(".", 1)[0].casefold()
    if (
        not _SAFE_ACTION_NAME.fullmatch(name)
        or name in {".", ".."}
        or name != name.rstrip(" .")
        or stem in _WINDOWS_RESERVED_NAMES
        or PureWindowsPath(name).drive
    ):
        raise ActionPackError(f"动作名称不安全：{name}")
    return name


def _validate_action_definition(name: str, definition: Mapping[str, object], frame_count: int) -> None:
    fps = definition.get("fps")
    if isinstance(fps, bool) or not isinstance(fps, (int, float)) or fps <= 0:
        raise ActionPackError(f"动作 {name} 的 FPS 必须大于 0")
    if not isinstance(definition.get("loop"), bool):
        raise ActionPackError(f"动作 {name} 的 loop 必须是布尔值")
    scope = definition.get("scope", "pet")
    if scope not in {"pet", "fullscreen"}:
        raise ActionPackError(f"动作 {name} 的 scope 必须是 pet 或 fullscreen")
    direction = definition.get("entrance_direction")
    if direction is not None:
        if scope != "fullscreen":
            raise ActionPackError(f"动作 {name}：只有全屏动作可以声明 entrance_direction")
        if not isinstance(direction, str) or direction not in {"left", "right", "none"}:
            raise ActionPackError(f"动作 {name} 的 entrance_direction 必须是 left、right 或 none")
    if scope == "fullscreen":
        canvas = definition.get("canvas")
        if not isinstance(canvas, Mapping):
            raise ActionPackError(f"动作 {name} 的全屏 canvas 必须是对象")
        width, height = canvas.get("width"), canvas.get("height")
        if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in (width, height)):
            raise ActionPackError(f"动作 {name} 的全屏 canvas 尺寸必须是正整数")
    durations = definition.get("frame_durations_ms")
    if durations is not None:
        if not isinstance(durations, list) or len(durations) != frame_count:
            raise ActionPackError(f"动作 {name} 的逐帧时长必须与 PNG 帧一一对应")
        if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in durations):
            raise ActionPackError(f"动作 {name} 的逐帧时长必须全部为正整数")
    multiplier = definition.get("speed_multiplier", 1.0)
    if isinstance(multiplier, bool) or not isinstance(multiplier, (int, float)) or multiplier <= 0:
        raise ActionPackError(f"动作 {name} 的 speed_multiplier 必须大于 0")


def _source_pet_info(value: object) -> SourcePetInfo:
    if not isinstance(value, Mapping):
        raise ActionPackError("source_pet 必须是对象")
    return SourcePetInfo(
        identifier=_required_string(value.get("id"), "source_pet.id"),
        name=str(value.get("name", value["id"])),
        version=str(value.get("version", "0.0.0")),
    )


def _string_map(value: object, label: str) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, Mapping) or any(not isinstance(key, str) or not isinstance(item, str) for key, item in value.items()):
        raise ActionPackError(f"{label} 必须是字符串到字符串的映射")
    return {str(key): str(item) for key, item in value.items()}


def _string_list_map(value: object, label: str) -> dict[str, list[str]]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ActionPackError(f"{label} 必须是动作名到字符串数组的映射")
    result: dict[str, list[str]] = {}
    for key, items in value.items():
        if not isinstance(key, str) or not isinstance(items, list) or not all(isinstance(item, str) for item in items):
            raise ActionPackError(f"{label} 必须是动作名到字符串数组的映射")
        result[key] = list(items)
    return result


def _read_json_object(path: Path, label: str) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ActionPackError(f"{label} 无法读取：{error}") from error
    if not isinstance(value, dict):
        raise ActionPackError(f"{label} 顶层必须是对象")
    return value


def _required_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ActionPackError(f"{label} 必须是非空字符串")
    return value.strip()


def _optional_string(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _unique_names(names: Sequence[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for name in names:
        if not isinstance(name, str):
            raise ActionPackError("动作名称必须是字符串")
        if name not in seen:
            seen.add(name)
            result.append(name)
    return result


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _zip_info(name: str) -> ZipInfo:
    info = ZipInfo(name)
    info.date_time = (1980, 1, 1, 0, 0, 0)
    info.compress_type = ZIP_DEFLATED
    return info


__all__ = [
    "ACTION_PACK_MANIFEST",
    "ActionPack",
    "ActionPackError",
    "SourcePetInfo",
    "export_action_pack",
    "load_action_pack",
]
