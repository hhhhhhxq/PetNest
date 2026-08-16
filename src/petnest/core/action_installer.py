"""把动作分享包安装到宠物目录，并提供逐动作冲突决策。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
import json
from pathlib import Path, PureWindowsPath
import re
import shutil

from .action_pack import ActionPack
from .package_transaction import PackageTransaction, PackageTransactionError


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
    """按冲突决策事务性安装动作，失败时保留目标宠物原样。"""

    raw_target = Path(target_pet).expanduser()
    if raw_target.is_symlink():
        raise ActionInstallError("目标宠物不能是符号链接")
    target = raw_target.resolve()
    config = _read_config(target / "pet.json")
    animations = config.get("animations")
    if not isinstance(animations, Mapping):
        raise ActionInstallError("目标宠物的 animations 必须是对象")
    decisions = decisions or {}
    plans, skipped, renamed = _build_plans(pack, animations, decisions)

    try:
        with PackageTransaction(target) as transaction:
            candidate = transaction.candidate
            candidate_config = _read_config(candidate / "pet.json")
            candidate_animations = candidate_config.get("animations")
            if not isinstance(candidate_animations, dict):
                raise ActionInstallError("目标宠物的 animations 必须是对象")
            for plan in plans:
                _install_one(candidate, candidate_animations, plan, renamed)
            if import_bindings:
                _merge_bindings(
                    candidate_config,
                    pack,
                    renamed,
                    candidate_animations,
                    {plan.source_name for plan in plans},
                )
            (candidate / "pet.json").write_text(
                json.dumps(candidate_config, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            transaction.commit()
    except ActionInstallError:
        raise
    except PackageTransactionError as error:
        raise ActionInstallError(str(error)) from error
    return InstallResult(
        target_root=target,
        installed=tuple(plan.target_name for plan in plans),
        skipped=tuple(skipped),
        renamed=dict(renamed),
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
    candidate: Path,
    animations: dict[str, object],
    plan: _InstallPlan,
    renamed: Mapping[str, str],
) -> None:
    action = plan.action
    definition = getattr(action, "definition", None)
    source_root = getattr(action, "source_root", None)
    asset_paths = getattr(action, "asset_paths", None)
    if not isinstance(definition, dict) or not isinstance(source_root, Path) or not isinstance(asset_paths, tuple):
        raise ActionInstallError(f"动作 {plan.source_name} 数据不完整")
    if plan.replace_existing:
        old_definition = animations.get(plan.target_name)
        if isinstance(old_definition, Mapping):
            _remove_animation_directory(candidate, old_definition.get("path"))
    target_dir = candidate / "animations" / _safe_name(plan.target_name)
    if target_dir.exists():
        if not target_dir.is_dir():
            raise ActionInstallError(f"动作目标不是目录：{target_dir}")
        shutil.rmtree(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    source_definition_path = definition.get("path")
    if not isinstance(source_definition_path, str):
        raise ActionInstallError(f"动作 {plan.source_name} 缺少资源路径")
    source_dir = (source_root / source_definition_path).resolve()
    if not source_dir.is_dir() or not source_dir.is_relative_to(source_root.resolve()):
        raise ActionInstallError(f"动作 {plan.source_name} 的资源路径不安全")
    for asset in asset_paths:
        asset_path = Path(asset).resolve()
        if not asset_path.is_file() or not asset_path.is_relative_to(source_dir):
            raise ActionInstallError(f"动作 {plan.source_name} 的资源文件不安全")
        relative = asset_path.relative_to(source_dir)
        destination = target_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(asset_path, destination)
    imported_definition = json.loads(json.dumps(definition, ensure_ascii=False))
    imported_definition["path"] = f"animations/{_safe_name(plan.target_name)}"
    if isinstance(imported_definition.get("next"), str):
        imported_definition["next"] = renamed.get(imported_definition["next"], imported_definition["next"])
    animations[plan.target_name] = imported_definition


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


def _remove_animation_directory(candidate: Path, configured: object) -> None:
    if not isinstance(configured, str) or not configured.strip():
        raise ActionInstallError("已有动作的资源路径无效")
    path = Path(configured)
    if path.is_absolute() or PureWindowsPath(configured).is_absolute() or PureWindowsPath(configured).drive:
        raise ActionInstallError("已有动作的资源路径不安全")
    resolved = (candidate / path).resolve()
    if not resolved.is_relative_to(candidate.resolve()):
        raise ActionInstallError("已有动作的资源路径逃逸宠物目录")
    if resolved.exists():
        if not resolved.is_dir():
            raise ActionInstallError("已有动作资源不是目录")
        shutil.rmtree(resolved)


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
