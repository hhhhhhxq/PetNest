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

from .exchange_source import ExchangeLimits, ExchangeSource
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
        if destination.is_symlink():
            raise PetPackageImportError("宠物目标不能是符号链接")
        try:
            if not destination.resolve(strict=False).is_relative_to(root_of_pets):
                raise PetPackageImportError("宠物目标必须位于宠物目录内")
        except OSError as error:
            raise PetPackageImportError(f"宠物目标路径无法解析：{error}") from error
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


def rollback_pet_import(result: PetImportResult, pets_root: Path) -> None:
    """Undo one completed import after the runtime rejects the installed package."""

    root = Path(pets_root).expanduser().resolve()
    expected = (root / result.pet_id).resolve(strict=False)
    target = Path(result.pet_root).expanduser().resolve(strict=False)
    if target != expected or not target.is_relative_to(root):
        raise PetPackageImportError("回滚目标不在宠物目录内")
    if result.replaced_existing:
        backup = result.backup_path
        if backup is None or not backup.is_file() or backup.is_symlink():
            raise PetPackageImportError("更新宠物没有可用备份")
        backup_root = (root / ".backups" / result.pet_id).resolve(strict=False)
        if not backup.resolve().is_relative_to(backup_root):
            raise PetPackageImportError("宠物备份路径不安全")
        import_pet_package(
            backup,
            root,
            PetImportOptions(create_backup=False),
        )
        return
    if target.is_symlink():
        raise PetPackageImportError("回滚目标不能是符号链接")
    if target.exists():
        if not target.is_dir():
            raise PetPackageImportError("回滚目标不是宠物目录")
        shutil.rmtree(target)


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
        safe_name = _safe_action_name(name)
        old_definition = old_animations[name]
        if not isinstance(old_definition, Mapping):
            raise PetPackageImportError(f"无法保留本地动作 {name}：定义不合法")
        old_path = _safe_resource_directory(existing_root, old_definition.get("path"), name)
        animations_root = (candidate / "animations").resolve()
        destination = animations_root / safe_name
        if not destination.resolve(strict=False).is_relative_to(animations_root):
            raise PetPackageImportError(f"无法保留本地动作 {name}：目标路径不安全")
        if destination.exists():
            shutil.rmtree(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        _reject_symlinks(old_path, name)
        shutil.copytree(old_path, destination, symlinks=False)
        definition = json.loads(json.dumps(dict(old_definition), ensure_ascii=False))
        definition["path"] = f"animations/{safe_name}"
        new_animations[safe_name] = definition
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
        files: list[Path] = []
        total_bytes = 0
        limits = ExchangeLimits()
        for current, directories, filenames in os.walk(package_root, followlinks=False):
            current_path = Path(current)
            for name in directories:
                directory = current_path / name
                if directory.is_symlink():
                    raise OSError(f"备份不能包含符号链接：{directory}")
            for name in filenames:
                file_path = current_path / name
                if file_path.is_symlink():
                    raise OSError(f"备份不能包含符号链接：{file_path}")
                if file_path.suffix.casefold() in limits.blocked_suffixes:
                    raise OSError(f"备份不能包含可执行文件：{file_path.name}")
                if not file_path.is_file():
                    raise OSError(f"备份包含不可归档文件：{file_path}")
                total_bytes += file_path.stat().st_size
                files.append(file_path)
        if len(files) > limits.max_files:
            raise OSError("备份文件数量超出限制")
        if total_bytes > limits.max_uncompressed_bytes:
            raise OSError("备份体积超出限制")
        with ZipFile(temporary, "w", compression=ZIP_DEFLATED) as archive:
            for file_path in sorted(files, key=lambda item: item.relative_to(package_root).as_posix()):
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


_SAFE_ACTION_NAME = re.compile(r"^[^\\/:*?\"<>|\x00-\x1f]+$")
_WINDOWS_RESERVED_NAMES = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}


def _safe_action_name(name: str) -> str:
    stem = name.split(".", 1)[0].casefold()
    if (
        not _SAFE_ACTION_NAME.fullmatch(name)
        or name in {".", ".."}
        or name != name.rstrip(" .")
        or stem in _WINDOWS_RESERVED_NAMES
        or PureWindowsPath(name).drive
    ):
        raise PetPackageImportError(f"动作名称不安全：{name}")
    return name


def _reject_symlinks(root: Path, action_name: str) -> None:
    for current, directories, filenames in os.walk(root, followlinks=False):
        current_path = Path(current)
        for name in (*directories, *filenames):
            candidate = current_path / name
            if candidate.is_symlink():
                raise PetPackageImportError(f"无法保留本地动作 {action_name}：资源不能包含符号链接")


def _validate_pet_id(value: object) -> str:
    if not isinstance(value, str) or not _PET_ID_PATTERN.fullmatch(value.strip()):
        raise PetPackageImportError("宠物 ID 必须以小写字母开头，只能包含小写字母、数字、- 或 _")
    return value.strip()


__all__ = [
    "PetImportOptions",
    "PetImportResult",
    "PetPackageImportError",
    "import_pet_package",
    "rollback_pet_import",
]
