"""把动作分享包安装到宠物目录，并提供逐动作冲突决策。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
import json
import os
from pathlib import Path, PureWindowsPath
import re
import shutil
import tempfile
from uuid import uuid4

from .action_pack import ActionPack
from .package_validator import PackageValidator


class ActionInstallError(ValueError):
    """动作无法安装或安装事务已回滚。"""


class ConflictKind(StrEnum):
    REPLACE = "replace"
    RENAME = "rename"
    SKIP = "skip"


@dataclass(frozen=True, slots=True)
class ConflictDecision:
    kind: ConflictKind
    name: str | None = None

    @classmethod
    def replace(cls) -> "ConflictDecision":
        return cls(ConflictKind.REPLACE)

    @classmethod
    def rename(cls, name: str) -> "ConflictDecision":
        return cls(ConflictKind.RENAME, name)

    @classmethod
    def skip(cls) -> "ConflictDecision":
        return cls(ConflictKind.SKIP)


@dataclass(frozen=True, slots=True)
class InstallResult:
    target_root: Path
    installed: tuple[str, ...]
    skipped: tuple[str, ...]
    renamed: dict[str, str]
    original_config: bytes = field(repr=False)
    committed_config: bytes = field(repr=False)
    created_revision_dirs: tuple[Path, ...]
    superseded_dirs: tuple[Path, ...]

    def rollback(self) -> tuple[str, ...]:
        """原子恢复导入前配置，再尽力清理本次新增的修订目录。"""

        config_path = self.target_root / "pet.json"
        try:
            if config_path.read_bytes() != self.committed_config:
                raise ActionInstallError("pet.json 在动作安装后发生变化，拒绝自动覆盖")
            _replace_bytes_atomically(config_path, self.original_config)
        except ActionInstallError:
            raise
        except Exception as error:
            raise ActionInstallError(f"动作配置恢复失败，新资源已保留：{error}") from error
        return _cleanup_directories(
            self.created_revision_dirs,
            allowed_root=self.target_root / "animations" / ".revisions",
        )

    def finalize(self) -> tuple[str, ...]:
        """配置重载成功后，尽力删除已不再被任何动作引用的旧目录。"""

        try:
            config = _read_config(self.target_root / "pet.json")
            animations = config.get("animations")
            if not isinstance(animations, Mapping):
                return ("无法清理旧动作：当前 animations 不是对象",)
            referenced = _referenced_directories(self.target_root, animations)
        except ActionInstallError as error:
            return (f"无法清理旧动作：{error}",)
        removable = tuple(
            path
            for path in self.superseded_dirs
            if not any(reference == path or reference.is_relative_to(path) for reference in referenced)
        )
        return _cleanup_directories(removable, allowed_root=self.target_root / "animations")


@dataclass(frozen=True, slots=True)
class _InstallPlan:
    source_name: str
    target_name: str
    action: object
    replace_existing: bool


_SAFE_NAME = re.compile(r"^[^\\/:*?\"<>|\x00-\x1f]+$")
_WINDOWS_RESERVED_NAMES = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}


def install_actions(
    target_pet: Path,
    pack: ActionPack,
    decisions: Mapping[str, ConflictDecision] | None = None,
    *,
    import_bindings: bool = False,
) -> InstallResult:
    """安装到不可变动作修订目录，仅以 ``pet.json`` 作为提交点。"""

    raw_target = Path(target_pet).expanduser()
    if raw_target.is_symlink():
        raise ActionInstallError("目标宠物不能是符号链接")
    target = raw_target.resolve()
    _reject_symlinks(target)
    config_path = target / "pet.json"
    try:
        original_config = config_path.read_bytes()
    except OSError as error:
        raise ActionInstallError(f"pet.json 无法读取：{error}") from error
    config = _read_config(config_path)
    animations = config.get("animations")
    if not isinstance(animations, Mapping):
        raise ActionInstallError("目标宠物的 animations 必须是对象")
    decisions = decisions or {}
    plans, skipped, renamed = _build_plans(pack, animations, decisions)
    if not plans:
        return InstallResult(target, (), tuple(skipped), dict(renamed), original_config, original_config, (), ())

    candidate_config = json.loads(json.dumps(config, ensure_ascii=False))
    candidate_animations = candidate_config.get("animations")
    if not isinstance(candidate_animations, dict):
        raise ActionInstallError("目标宠物的 animations 必须是对象")
    created: list[Path] = []
    superseded: list[Path] = []
    try:
        revisions_root = _prepare_revisions_root(target)
        for plan in plans:
            if plan.replace_existing:
                old_definition = candidate_animations.get(plan.target_name)
                if isinstance(old_definition, Mapping):
                    superseded.append(_managed_animation_directory(target, old_definition.get("path")))
            created.append(_install_one(target, revisions_root, candidate_animations, plan, renamed))
        if import_bindings:
            _merge_bindings(
                candidate_config,
                pack,
                renamed,
                candidate_animations,
                {plan.source_name for plan in plans},
            )
        committed_config = _encode_config(candidate_config)
        _validate_candidate(target, committed_config, {plan.target_name for plan in plans})
        _replace_bytes_atomically(config_path, committed_config)
    except Exception as error:
        cleanup_warnings = _cleanup_directories(tuple(created), allowed_root=target / "animations" / ".revisions")
        if isinstance(error, ActionInstallError):
            if cleanup_warnings:
                raise ActionInstallError(f"{error}；{'；'.join(cleanup_warnings)}") from error
            raise
        detail = f"动作安装失败，原配置未改动：{error}"
        if cleanup_warnings:
            detail += f"；{'；'.join(cleanup_warnings)}"
        raise ActionInstallError(detail) from error
    return InstallResult(
        target_root=target,
        installed=tuple(plan.target_name for plan in plans),
        skipped=tuple(skipped),
        renamed=dict(renamed),
        original_config=original_config,
        committed_config=committed_config,
        created_revision_dirs=tuple(created),
        superseded_dirs=tuple(dict.fromkeys(superseded)),
    )


def _build_plans(
    pack: ActionPack,
    existing: Mapping[object, object],
    decisions: Mapping[str, ConflictDecision],
) -> tuple[list[_InstallPlan], list[str], dict[str, str]]:
    plans: list[_InstallPlan] = []
    skipped: list[str] = []
    renamed: dict[str, str] = {}
    occupied: dict[str, str] = {}
    for name in existing:
        if not isinstance(name, str):
            raise ActionInstallError("目标宠物动作名称必须是字符串")
        safe_existing = _safe_name(name)
        key = _action_key(safe_existing)
        if key in occupied:
            raise ActionInstallError(f"目标宠物包含大小写不一致的重复动作：{name}")
        occupied[key] = safe_existing
    planned_targets: set[str] = set()
    for source_name, action in pack.actions.items():
        if not isinstance(source_name, str):
            raise ActionInstallError("分享包动作名称必须是字符串")
        source_name = _safe_name(source_name)
        source_key = _action_key(source_name)
        existing_name = occupied.get(source_key)
        decision = decisions.get(source_name, ConflictDecision.replace())
        if not isinstance(decision, ConflictDecision):
            raise ActionInstallError(f"动作 {source_name} 的冲突决定无效")
        if decision.kind is ConflictKind.SKIP:
            skipped.append(source_name)
            continue
        target_name = existing_name if existing_name is not None else source_name
        replace_existing = existing_name is not None and decision.kind is ConflictKind.REPLACE
        if decision.kind is ConflictKind.RENAME:
            if not decision.name:
                raise ActionInstallError(f"动作 {source_name} 的新名称不能为空")
            target_name = _safe_name(decision.name)
            replace_existing = False
        target_key = _action_key(target_name)
        if target_key in planned_targets:
            raise ActionInstallError(f"多个动作使用了同一个目标名称：{target_name}")
        if target_key in occupied and not replace_existing:
            raise ActionInstallError(f"动作目标名称已存在：{target_name}")
        planned_targets.add(target_key)
        if target_name != source_name:
            renamed[source_name] = target_name
        plans.append(_InstallPlan(source_name, target_name, action, replace_existing))
    return plans, skipped, renamed


def _install_one(
    target: Path,
    revisions_root: Path,
    animations: dict[str, object],
    plan: _InstallPlan,
    renamed: Mapping[str, str],
) -> Path:
    action = plan.action
    definition = getattr(action, "definition", None)
    source_root = getattr(action, "source_root", None)
    asset_paths = getattr(action, "asset_paths", None)
    if not isinstance(definition, dict) or not isinstance(source_root, Path) or not isinstance(asset_paths, tuple):
        raise ActionInstallError(f"动作 {plan.source_name} 数据不完整")
    safe_target_name = _safe_name(plan.target_name)
    revision_stem = safe_target_name[:180].rstrip(" .") or "action"
    target_dir = revisions_root / f"{revision_stem}-{uuid4().hex}"
    if target_dir.resolve().parent != revisions_root.resolve():
        raise ActionInstallError(f"动作 {plan.source_name} 的修订目录不安全")
    target_dir.mkdir()
    source_definition_path = definition.get("path")
    if not isinstance(source_definition_path, str):
        raise ActionInstallError(f"动作 {plan.source_name} 缺少资源路径")
    source_dir = (source_root / source_definition_path).resolve()
    if not source_dir.is_dir() or not source_dir.is_relative_to(source_root.resolve()):
        raise ActionInstallError(f"动作 {plan.source_name} 的资源路径不安全")
    try:
        for asset in asset_paths:
            configured_asset = Path(asset)
            if configured_asset.is_symlink():
                raise ActionInstallError(f"动作 {plan.source_name} 的资源文件不能是符号链接")
            asset_path = configured_asset.resolve()
            if not asset_path.is_file() or not asset_path.is_relative_to(source_dir):
                raise ActionInstallError(f"动作 {plan.source_name} 的资源文件不安全")
            relative = asset_path.relative_to(source_dir)
            destination = target_dir / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(asset_path, destination)
        imported_definition = json.loads(json.dumps(definition, ensure_ascii=False))
        imported_definition["path"] = target_dir.relative_to(target).as_posix()
        if isinstance(imported_definition.get("next"), str):
            imported_definition["next"] = renamed.get(imported_definition["next"], imported_definition["next"])
        animations[plan.target_name] = imported_definition
        return target_dir
    except Exception:
        shutil.rmtree(target_dir, ignore_errors=True)
        raise


def _merge_bindings(
    config: dict[str, object],
    pack: ActionPack,
    renamed: Mapping[str, str],
    animations: Mapping[str, object],
    enabled_sources: set[str],
) -> None:
    bindings = config.get("bindings")
    if not isinstance(bindings, dict):
        bindings = {}
        config["bindings"] = bindings
    for event, action in pack.bindings.items():
        if action not in enabled_sources:
            continue
        mapped = renamed.get(action, action)
        if mapped in animations:
            bindings[event] = mapped
    fallbacks = config.get("fallbacks")
    if not isinstance(fallbacks, dict):
        fallbacks = {}
        config["fallbacks"] = fallbacks
    for action, candidates in pack.fallbacks.items():
        if action not in enabled_sources:
            continue
        mapped_action = renamed.get(action, action)
        mapped_candidates = []
        for item in candidates:
            if item in pack.actions and item not in enabled_sources:
                continue
            mapped_item = renamed.get(item, item)
            if mapped_item in animations and mapped_item not in mapped_candidates:
                mapped_candidates.append(mapped_item)
        if mapped_action in animations:
            fallbacks[mapped_action] = mapped_candidates


def _managed_animation_directory(target: Path, configured: object) -> Path:
    if not isinstance(configured, str) or not configured.strip():
        raise ActionInstallError("已有动作的资源路径无效")
    path = Path(configured)
    if path.is_absolute() or PureWindowsPath(configured).is_absolute() or PureWindowsPath(configured).drive:
        raise ActionInstallError("已有动作的资源路径不安全")
    configured_path = target / path
    if configured_path.is_symlink():
        raise ActionInstallError("已有动作的资源路径不能是符号链接")
    resolved = configured_path.resolve()
    animations_root = (target / "animations").resolve()
    if resolved == animations_root or not resolved.is_relative_to(animations_root):
        raise ActionInstallError("已有动作的资源路径必须位于 animations 目录内")
    if resolved.exists() and not resolved.is_dir():
        raise ActionInstallError("已有动作资源不是目录")
    return resolved


def _prepare_revisions_root(target: Path) -> Path:
    animations_root = target / "animations"
    if animations_root.is_symlink() or not animations_root.is_dir():
        raise ActionInstallError("目标宠物的 animations 必须是常规目录")
    revisions_root = animations_root / ".revisions"
    if revisions_root.is_symlink():
        raise ActionInstallError("动作修订目录不能是符号链接")
    if revisions_root.exists() and not revisions_root.is_dir():
        raise ActionInstallError("动作修订路径不是目录")
    revisions_root.mkdir(exist_ok=True)
    return revisions_root.resolve()


def _validate_candidate(target: Path, config_bytes: bytes, expected_actions: set[str]) -> None:
    try:
        with tempfile.TemporaryDirectory(prefix=f".{target.name}.action-validate-", dir=target.parent) as temporary:
            candidate = Path(temporary) / target.name
            shutil.copytree(
                target,
                candidate,
                symlinks=True,
                ignore=shutil.ignore_patterns("pet.json"),
            )
            (candidate / "pet.json").write_bytes(config_bytes)
            validation = PackageValidator().validate(candidate)
            if not validation.is_valid:
                detail = "；".join(validation.errors) or "未知错误"
                raise ActionInstallError(f"候选包校验失败：{detail}")
            missing = sorted(expected_actions.difference(validation.frames))
            if missing:
                raise ActionInstallError(f"候选包校验失败：动作缺少有效 PNG 帧：{', '.join(missing)}")
    except ActionInstallError:
        raise
    except Exception as error:
        raise ActionInstallError(f"候选包校验失败：{error}") from error


def _encode_config(config: Mapping[str, object]) -> bytes:
    return (json.dumps(config, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _replace_bytes_atomically(path: Path, contents: bytes) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _referenced_directories(target: Path, animations: Mapping[object, object]) -> set[Path]:
    referenced: set[Path] = set()
    target_root = target.resolve()
    for definition in animations.values():
        if not isinstance(definition, Mapping):
            continue
        configured = definition.get("path")
        if not isinstance(configured, str) or not configured.strip():
            continue
        path = Path(configured)
        if path.is_absolute() or PureWindowsPath(configured).is_absolute() or PureWindowsPath(configured).drive:
            continue
        configured_path = target / path
        if configured_path.is_symlink():
            continue
        resolved = configured_path.resolve()
        if resolved.is_relative_to(target_root):
            referenced.add(resolved)
    return referenced


def _cleanup_directories(paths: tuple[Path, ...], *, allowed_root: Path) -> tuple[str, ...]:
    warnings: list[str] = []
    safe_root = allowed_root.resolve()
    for path in dict.fromkeys(paths):
        configured = Path(path)
        try:
            if configured.is_symlink():
                raise ActionInstallError(f"拒绝清理符号链接：{configured}")
            resolved = configured.resolve()
            if resolved == safe_root or not resolved.is_relative_to(safe_root):
                raise ActionInstallError(f"拒绝清理范围外目录：{configured}")
            if not resolved.exists():
                continue
            if not resolved.is_dir():
                raise ActionInstallError(f"拒绝清理非目录路径：{configured}")
            shutil.rmtree(resolved)
        except (ActionInstallError, OSError) as error:
            warnings.append(str(error))
    return tuple(warnings)


def _reject_symlinks(root: Path) -> None:
    if not root.is_dir():
        raise ActionInstallError(f"目标宠物目录不存在：{root}")
    for current, directories, filenames in os.walk(root, followlinks=False):
        current_path = Path(current)
        for name in (*directories, *filenames):
            candidate = current_path / name
            if candidate.is_symlink():
                raise ActionInstallError(f"目标宠物不能包含符号链接：{candidate}")


def _read_config(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ActionInstallError(f"pet.json 无法读取：{error}") from error
    if not isinstance(value, dict):
        raise ActionInstallError("pet.json 顶层必须是对象")
    return value


def _safe_name(name: str) -> str:
    stem = name.split(".", 1)[0].casefold()
    if (
        not _SAFE_NAME.fullmatch(name)
        or name in {".", ".."}
        or name != name.rstrip(" .")
        or stem in _WINDOWS_RESERVED_NAMES
        or PureWindowsPath(name).drive
    ):
        raise ActionInstallError(f"动作名称不安全：{name}")
    return name


def _action_key(name: str) -> str:
    """返回 Windows 文件系统下用于冲突判断的动作目录键。"""
    return name.rstrip(" .").casefold()


__all__ = [
    "ActionInstallError",
    "ConflictDecision",
    "ConflictKind",
    "InstallResult",
    "install_actions",
]
