"""导入完整宠物包，并安全更新已有宠物。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path, PureWindowsPath
import re
import shutil
import tempfile
from zipfile import ZIP_DEFLATED, ZipFile

from .exchange_source import ExchangeSource
from .package_transaction import PackageTransaction, PackageTransactionError
from .package_validator import PackageValidator


class PetPackageImportError(ValueError):
    """完整宠物包无效、备份失败或安装失败。"""


@dataclass(frozen=True, slots=True)
class PetImportOptions:
    preserve_local_actions: bool = False
    create_backup: bool = True


@dataclass(frozen=True, slots=True)
class PetImportResult:
    pet_id: str
    pet_root: Path
    backup_path: Path | None
    replaced_existing: bool


_PET_ID_PATTERN = re.compile(r"[a-z][a-z0-9_-]*\Z")


def import_pet_package(
    source: Path,
    pets_root: Path,
    options: PetImportOptions | None = None,
) -> PetImportResult:
    """新增或更新完整宠物包；更新前默认创建可恢复备份。"""

    options = options or PetImportOptions()
    root_of_pets = Path(pets_root).expanduser().resolve()
    root_of_pets.mkdir(parents=True, exist_ok=True)
    try:
        materialized = ExchangeSource.open(Path(source))
    except Exception as error:
        raise PetPackageImportError(f"无法读取宠物来源：{error}") from error
    try:
        source_root = materialized.root
        validation = PackageValidator().validate(source_root)
        if not validation.is_valid or validation.config is None:
            detail = "；".join(validation.errors) or "未知错误"
            raise PetPackageImportError(f"源宠物包校验失败：{detail}")
        source_config = validation.config
        identifier = _validate_pet_id(source_config.get("id"))
        destination = root_of_pets / identifier
        replacing = destination.exists()
        existing_config = _read_config(destination / "pet.json") if replacing and options.preserve_local_actions else None
        backup_path: Path | None = None
        if replacing and options.create_backup:
            try:
                backup_path = _create_backup(destination, root_of_pets, identifier)
            except Exception as error:
                raise PetPackageImportError(f"创建宠物备份失败：{error}") from error
        try:
            with PackageTransaction(destination) as transaction:
                candidate = transaction.candidate
                _replace_candidate_with_source(candidate, source_root)
                candidate_config = _read_config(candidate / "pet.json")
                if options.preserve_local_actions and existing_config is not None:
                    _preserve_local_actions(destination, existing_config, source_config, candidate, candidate_config)
                (candidate / "pet.json").write_text(
                    json.dumps(candidate_config, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                transaction.commit()
        except (PetPackageImportError, PackageTransactionError) as error:
            raise PetPackageImportError(f"安装宠物包失败，原资源未改变：{error}") from error
        return PetImportResult(identifier, destination, backup_path, replacing)
    finally:
        materialized.__exit__(None, None, None)


def _replace_candidate_with_source(candidate: Path, source_root: Path) -> None:
    if candidate.exists():
        shutil.rmtree(candidate)
    candidate.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_root, candidate, dirs_exist_ok=True, symlinks=False)


def _preserve_local_actions(
    existing_root: Path,
    existing_config: Mapping[str, object],
    source_config: Mapping[str, object],
    candidate: Path,
    candidate_config: dict[str, object],
) -> None:
    old_animations = existing_config.get("animations")
    new_animations = candidate_config.get("animations")
    source_animations = source_config.get("animations")
    if not isinstance(old_animations, Mapping) or not isinstance(new_animations, dict) or not isinstance(source_animations, Mapping):
        raise PetPackageImportError("无法保留本地动作：animations 结构不合法")
    local_names = [name for name in old_animations if isinstance(name, str) and name not in source_animations]
    for name in local_names:
        old_definition = old_animations[name]
        if not isinstance(old_definition, Mapping):
            raise PetPackageImportError(f"无法保留本地动作 {name}：定义不合法")
        old_path = _safe_resource_directory(existing_root, old_definition.get("path"), name)
        destination = candidate / "animations" / name
        if destination.exists():
            shutil.rmtree(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(old_path, destination, symlinks=False)
        definition = json.loads(json.dumps(dict(old_definition), ensure_ascii=False))
        definition["path"] = f"animations/{name}"
        new_animations[name] = definition
    _preserve_local_bindings(existing_config, candidate_config, set(local_names), set(new_animations))


def _preserve_local_bindings(
    existing_config: Mapping[str, object],
    candidate_config: dict[str, object],
    local_names: set[str],
    all_names: set[str],
) -> None:
    old_bindings = existing_config.get("bindings")
    new_bindings = candidate_config.get("bindings")
    if isinstance(old_bindings, Mapping):
        if not isinstance(new_bindings, dict):
            new_bindings = {}
            candidate_config["bindings"] = new_bindings
        for event, action in old_bindings.items():
            if isinstance(event, str) and isinstance(action, str) and action in local_names and event not in new_bindings:
                new_bindings[event] = action
    old_fallbacks = existing_config.get("fallbacks")
    new_fallbacks = candidate_config.get("fallbacks")
    if isinstance(old_fallbacks, Mapping):
        if not isinstance(new_fallbacks, dict):
            new_fallbacks = {}
            candidate_config["fallbacks"] = new_fallbacks
        for action, candidates in old_fallbacks.items():
            if action not in local_names or not isinstance(candidates, list):
                continue
            filtered = [item for item in candidates if isinstance(item, str) and item in all_names]
            if filtered:
                new_fallbacks[action] = filtered


def _create_backup(package_root: Path, pets_root: Path, identifier: str) -> Path:
    if not package_root.is_dir():
        raise OSError(f"目标宠物目录不存在：{package_root}")
    backup_root = pets_root / ".backups" / identifier
    backup_root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{identifier}-{timestamp}.", suffix=".tmp", dir=backup_root
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    destination = backup_root / f"{timestamp}.zip"
    try:
        with ZipFile(temporary, "w", compression=ZIP_DEFLATED) as archive:
            for file_path in sorted((item for item in package_root.rglob("*") if item.is_file()), key=lambda item: item.relative_to(package_root).as_posix()):
                archive.write(file_path, file_path.relative_to(package_root).as_posix())
        os.replace(temporary, destination)
    except Exception:
        if temporary.exists():
            temporary.unlink()
        raise
    return destination


def _read_config(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PetPackageImportError(f"pet.json 无法读取：{error}") from error
    if not isinstance(value, dict):
        raise PetPackageImportError("pet.json 顶层必须是对象")
    return value


def _safe_resource_directory(root: Path, configured: object, name: str) -> Path:
    if not isinstance(configured, str) or not configured.strip():
        raise PetPackageImportError(f"动作 {name} 的路径无效")
    candidate = Path(configured)
    if candidate.is_absolute() or PureWindowsPath(configured).is_absolute() or PureWindowsPath(configured).drive:
        raise PetPackageImportError(f"动作 {name} 的路径不安全")
    resolved = (root / candidate).resolve()
    if not resolved.is_relative_to(root.resolve()) or not resolved.is_dir():
        raise PetPackageImportError(f"动作 {name} 的资源目录不存在或逃逸")
    return resolved


def _validate_pet_id(value: object) -> str:
    if not isinstance(value, str) or not _PET_ID_PATTERN.fullmatch(value.strip()):
        raise PetPackageImportError("宠物 ID 必须以小写字母开头，只能包含小写字母、数字、- 或 _")
    return value.strip()


__all__ = [
    "PetImportOptions",
    "PetImportResult",
    "PetPackageImportError",
    "import_pet_package",
]
