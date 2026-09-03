"""Strict models for the untrusted PetNest pet-store catalog."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import PurePosixPath, PureWindowsPath
import re


MAX_CATALOG_BYTES = 2 * 1024 * 1024
MAX_MEDIA_SIZE = 32 * 1024 * 1024
MAX_PACKAGE_SIZE = 512 * 1024 * 1024
MAX_PACKAGE_VARIANTS = 4
_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_PACKAGE_VARIANT_FORMAT_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")


class PetStoreCatalogError(ValueError):
    """The remote store catalog is malformed or unsafe."""


@dataclass(frozen=True, slots=True)
class PetStoreFile:
    path: str
    size: int
    sha256: str

    @property
    def relative_path(self) -> PurePosixPath:
        return PurePosixPath(self.path)


@dataclass(frozen=True, slots=True)
class PetStorePackageVariant:
    format: str
    package: PetStoreFile


@dataclass(frozen=True, slots=True)
class PetStorePreview:
    file: PetStoreFile
    frame_width: int
    frame_height: int
    frame_count: int
    frame_durations_ms: tuple[int, ...]

    @property
    def path(self) -> str:
        return self.file.path

    @property
    def size(self) -> int:
        return self.file.size

    @property
    def sha256(self) -> str:
        return self.file.sha256


@dataclass(frozen=True, slots=True)
class PetStoreItem:
    identifier: str
    name: str
    author: str
    summary: str
    tags: tuple[str, ...]
    updated_at: datetime
    action_count: int
    capabilities: tuple[str, ...]
    cover: PetStoreFile
    idle_preview: PetStorePreview
    package: PetStoreFile
    package_variants: tuple[PetStorePackageVariant, ...] = ()

    @property
    def package_files(self) -> tuple[PetStoreFile, ...]:
        return (self.package, *(variant.package for variant in self.package_variants))


@dataclass(frozen=True, slots=True)
class PetStoreCatalog:
    generated_at: datetime
    featured_pet_id: str | None
    pets: tuple[PetStoreItem, ...]

    @classmethod
    def from_bytes(cls, payload: bytes) -> "PetStoreCatalog":
        if len(payload) > MAX_CATALOG_BYTES:
            raise PetStoreCatalogError("商店目录大小超过限制")
        try:
            raw = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise PetStoreCatalogError(f"商店目录不是有效 JSON：{error}") from error
        if not isinstance(raw, Mapping):
            raise PetStoreCatalogError("商店目录顶层必须是对象")
        return cls.from_dict(raw)

    @classmethod
    def from_dict(cls, raw: Mapping[str, object]) -> "PetStoreCatalog":
        if raw.get("schema_version") != 1 or isinstance(raw.get("schema_version"), bool):
            raise PetStoreCatalogError("商店目录 schema_version 必须为 1")
        generated_at = _timestamp(raw.get("generated_at"), "generated_at")
        pets_raw = raw.get("pets")
        if not isinstance(pets_raw, list):
            raise PetStoreCatalogError("pets 必须是数组")
        pets: list[PetStoreItem] = []
        ids: set[str] = set()
        paths: set[str] = set()
        for index, value in enumerate(pets_raw):
            if not isinstance(value, Mapping):
                raise PetStoreCatalogError(f"pets[{index}] 必须是对象")
            item = _item(value, paths)
            if item.identifier in ids:
                raise PetStoreCatalogError(f"宠物 ID 重复：{item.identifier}")
            ids.add(item.identifier)
            pets.append(item)
        featured = raw.get("featured_pet_id")
        if featured is not None and (not isinstance(featured, str) or featured not in ids):
            raise PetStoreCatalogError("推荐宠物必须引用目录中的商品")
        return cls(generated_at, featured, tuple(pets))

    def pet(self, identifier: str) -> PetStoreItem | None:
        return next((item for item in self.pets if item.identifier == identifier), None)

    @property
    def featured_pet(self) -> PetStoreItem | None:
        return self.pet(self.featured_pet_id) if self.featured_pet_id is not None else None


def _item(raw: Mapping[str, object], paths: set[str]) -> PetStoreItem:
    identifier = _identifier(raw.get("id"))
    name = _text(raw.get("name"), "name")
    author = _text(raw.get("author"), "author")
    summary = _text(raw.get("summary"), "summary")
    tags = _string_sequence(raw.get("tags"), "tags", allow_empty=False)
    capabilities = _string_sequence(raw.get("capabilities"), "capabilities", allow_empty=True)
    updated_at = _timestamp(raw.get("updated_at"), "updated_at")
    action_count = _positive_int(raw.get("action_count"), "action_count")
    prefix = f"store/pets/{identifier}/"
    cover = _file(raw.get("cover"), "cover", prefix, MAX_MEDIA_SIZE, paths)
    package = _file(raw.get("package"), "package", prefix, MAX_PACKAGE_SIZE, paths)
    package_variants = _package_variants(raw.get("package_variants"), prefix, paths)
    preview_raw = raw.get("idle_preview")
    if not isinstance(preview_raw, Mapping):
        raise PetStoreCatalogError("idle_preview 必须是对象")
    preview_file = _file(preview_raw, "idle_preview", prefix, MAX_MEDIA_SIZE, paths)
    frame_width = _positive_int(preview_raw.get("frame_width"), "idle_preview.frame_width")
    frame_height = _positive_int(preview_raw.get("frame_height"), "idle_preview.frame_height")
    frame_count = _positive_int(preview_raw.get("frame_count"), "idle_preview.frame_count")
    durations_raw = preview_raw.get("frame_durations_ms")
    if not isinstance(durations_raw, list) or len(durations_raw) != frame_count:
        raise PetStoreCatalogError("idle_preview frame 时间线必须与帧数一致")
    durations = tuple(
        _positive_int(value, f"idle_preview.frame_durations_ms[{index}]")
        for index, value in enumerate(durations_raw)
    )
    preview = PetStorePreview(
        preview_file, frame_width, frame_height, frame_count, durations
    )
    return PetStoreItem(
        identifier,
        name,
        author,
        summary,
        tags,
        updated_at,
        action_count,
        capabilities,
        cover,
        preview,
        package,
        package_variants,
    )


def _package_variants(
    value: object,
    prefix: str,
    paths: set[str],
) -> tuple[PetStorePackageVariant, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise PetStoreCatalogError("package_variants 必须是数组")
    if len(value) > MAX_PACKAGE_VARIANTS:
        raise PetStoreCatalogError(
            f"package_variants 数量不能超过 {MAX_PACKAGE_VARIANTS}"
        )
    variants: list[PetStorePackageVariant] = []
    formats: set[str] = set()
    for index, raw_variant in enumerate(value):
        if not isinstance(raw_variant, Mapping):
            raise PetStoreCatalogError(f"package_variants[{index}] 必须是对象")
        format_name = raw_variant.get("format")
        if not isinstance(format_name, str) or _PACKAGE_VARIANT_FORMAT_RE.fullmatch(format_name) is None:
            raise PetStoreCatalogError(f"package_variants[{index}].format 无效")
        if format_name in formats:
            raise PetStoreCatalogError(f"package_variants format 重复：{format_name}")
        formats.add(format_name)
        package = _file(
            raw_variant.get("package"),
            f"package_variants[{index}].package",
            prefix,
            MAX_PACKAGE_SIZE,
            paths,
        )
        variants.append(PetStorePackageVariant(format_name, package))
    return tuple(variants)


def _identifier(value: object) -> str:
    if not isinstance(value, str) or _ID_RE.fullmatch(value) is None:
        raise PetStoreCatalogError("宠物 id 无效")
    return value


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise PetStoreCatalogError(f"{field} 必须是非空整洁字符串")
    return value


def _string_sequence(value: object, field: str, *, allow_empty: bool) -> tuple[str, ...]:
    if not isinstance(value, list) or (not allow_empty and not value):
        raise PetStoreCatalogError(f"{field} 必须是字符串数组")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item or item != item.strip():
            raise PetStoreCatalogError(f"{field} 包含无效字符串")
        if item in result:
            raise PetStoreCatalogError(f"{field} 不能包含重复值")
        result.append(item)
    return tuple(result)


def _timestamp(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise PetStoreCatalogError(f"{field} 必须是 ISO-8601 时间")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as error:
        raise PetStoreCatalogError(f"{field} 不是有效时间") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PetStoreCatalogError(f"{field} 必须包含 UTC 偏移")
    return parsed.astimezone(UTC)


def _positive_int(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise PetStoreCatalogError(f"{field} 必须是正整数")
    return value


def _file(
    value: object,
    field: str,
    prefix: str,
    max_size: int,
    paths: set[str],
) -> PetStoreFile:
    if not isinstance(value, Mapping):
        raise PetStoreCatalogError(f"{field} 必须是文件对象")
    path = value.get("path")
    if not isinstance(path, str) or not _safe_path(path) or not path.startswith(prefix):
        raise PetStoreCatalogError(f"{field}.path 路径不安全或不属于当前宠物")
    key = path.casefold()
    if key in paths:
        raise PetStoreCatalogError(f"文件路径重复或发生 Windows 大小写碰撞：{path}")
    paths.add(key)
    size = _positive_int(value.get("size"), f"{field}.size")
    if size > max_size:
        raise PetStoreCatalogError(f"{field}.size 大小超过限制")
    digest = value.get("sha256")
    if not isinstance(digest, str) or _SHA_RE.fullmatch(digest) is None:
        raise PetStoreCatalogError(f"{field}.sha256 无效")
    return PetStoreFile(path, size, digest)


def _safe_path(value: str) -> bool:
    if "\\" in value:
        return False
    posix = PurePosixPath(value)
    windows = PureWindowsPath(value)
    return not (
        posix.is_absolute()
        or windows.is_absolute()
        or bool(windows.drive)
        or any(part in {"", ".", ".."} for part in posix.parts)
    )


__all__ = [
    "MAX_CATALOG_BYTES",
    "MAX_MEDIA_SIZE",
    "MAX_PACKAGE_SIZE",
    "MAX_PACKAGE_VARIANTS",
    "PetStoreCatalog",
    "PetStoreCatalogError",
    "PetStoreFile",
    "PetStoreItem",
    "PetStorePackageVariant",
    "PetStorePreview",
]
