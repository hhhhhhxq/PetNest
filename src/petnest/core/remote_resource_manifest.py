"""Remote resource manifest parsing and validation.

The manifest is the trust boundary between the public Worker endpoint and the
desktop application.  It only describes files below ``resources/`` and every
file carries a size and SHA-256 digest before it can be cached.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import PurePosixPath
import re
from types import MappingProxyType
from typing import Any, Mapping


class ManifestError(ValueError):
    """Raised when a remote manifest is malformed or unsafe."""


_SUPPORTED_SCHEMA = 1
_RESOURCE_TYPES = frozenset({"cursor_theme", "interaction_effect", "countdown_background"})
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_VERSION = re.compile(r"^\d+\.\d+\.\d+$")
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
# Runtime resources are small image/cursor assets. Keep malformed catalogs
# from becoming unbounded memory or disk sinks while leaving room for effects.
MAX_MANIFEST_BYTES = 8 * 1024 * 1024
MAX_RESOURCE_COUNT = 1024
MAX_FILE_COUNT = 20_000
MAX_FILE_SIZE = 64 * 1024 * 1024
MAX_CATALOG_SIZE = 512 * 1024 * 1024
_WINDOWS_RESERVED_NAMES = frozenset(
    {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
)


@dataclass(frozen=True, slots=True)
class RemoteFile:
    """One file described by the manifest."""

    path: str
    size: int
    sha256: str

    @property
    def relative_path(self) -> PurePosixPath:
        """Return the validated POSIX path without trusting platform parsing."""
        return PurePosixPath(self.path)


@dataclass(frozen=True, slots=True)
class RemoteResource:
    """A versioned cursor, effect, or countdown resource."""

    identifier: str
    type: str
    version: str
    files: tuple[RemoteFile, ...]
    metadata: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ResourceManifest:
    """Validated remote catalog."""

    schema_version: int
    catalog_version: str
    resources: tuple[RemoteResource, ...]

    @classmethod
    def from_bytes(cls, payload: bytes) -> "ResourceManifest":
        if len(payload) > MAX_MANIFEST_BYTES:
            raise ManifestError("manifest 超过允许大小")
        try:
            raw = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
            raise ManifestError(f"manifest JSON 无效: {error}") from error
        return cls.from_dict(raw)

    @classmethod
    def from_text(cls, payload: str) -> "ResourceManifest":
        if len(payload.encode("utf-8")) > MAX_MANIFEST_BYTES:
            raise ManifestError("manifest 超过允许大小")
        try:
            raw = json.loads(payload)
        except (json.JSONDecodeError, RecursionError) as error:
            raise ManifestError(f"manifest JSON 无效: {error}") from error
        return cls.from_dict(raw)

    @classmethod
    def from_dict(cls, raw: object) -> "ResourceManifest":
        if not isinstance(raw, Mapping):
            raise ManifestError("manifest 根节点必须是对象")

        schema_version = raw.get("schema_version")
        if type(schema_version) is not int or schema_version != _SUPPORTED_SCHEMA:
            raise ManifestError(f"不支持的 manifest schema_version: {schema_version!r}")

        catalog_version = raw.get("catalog_version")
        if not isinstance(catalog_version, str) or not _VERSION.fullmatch(catalog_version):
            raise ManifestError("catalog_version 必须是 x.y.z 版本号")

        raw_resources = raw.get("resources")
        if not isinstance(raw_resources, list):
            raise ManifestError("resources 必须是数组")

        resources: list[RemoteResource] = []
        identifiers: set[str] = set()
        file_paths: set[str] = set()
        total_file_count = 0
        total_catalog_size = 0
        for index, raw_resource in enumerate(raw_resources):
            if index >= MAX_RESOURCE_COUNT:
                raise ManifestError("资源数量超过允许上限")
            resource = _parse_resource(raw_resource, index, file_paths)
            if resource.identifier in identifiers:
                raise ManifestError(f"duplicate resource id: {resource.identifier}")
            total_file_count += len(resource.files)
            total_catalog_size += sum(remote_file.size for remote_file in resource.files)
            if total_file_count > MAX_FILE_COUNT:
                raise ManifestError("资源文件数量超过允许上限")
            if any(remote_file.size > MAX_FILE_SIZE for remote_file in resource.files):
                raise ManifestError("单个资源文件超过允许大小")
            if total_catalog_size > MAX_CATALOG_SIZE:
                raise ManifestError("资源总大小超过允许上限")
            identifiers.add(resource.identifier)
            resources.append(resource)

        for path in file_paths:
            parts = path.split("/")
            for index in range(1, len(parts)):
                parent = "/".join(parts[:index])
                if parent in file_paths:
                    raise ManifestError(f"资源路径冲突: {parent} 是 {path} 的父路径")

        normalized_paths: dict[str, str] = {}
        for path in file_paths:
            normalized = _windows_normalized_path(path)
            previous = normalized_paths.get(normalized)
            if previous is not None:
                raise ManifestError(f"资源路径在 Windows 下冲突: {previous} 与 {path}")
            normalized_paths[normalized] = path
        for normalized, path in normalized_paths.items():
            parts = normalized.split("/")
            for index in range(1, len(parts)):
                parent = "/".join(parts[:index])
                if parent in normalized_paths:
                    raise ManifestError(f"资源路径在 Windows 下冲突: {path} 的父路径")

        return cls(schema_version, catalog_version, tuple(resources))

    def resource(self, identifier: str) -> RemoteResource | None:
        """Find a resource by its stable id."""
        return next((item for item in self.resources if item.identifier == identifier), None)

    def resources_of_type(self, resource_type: str) -> tuple[RemoteResource, ...]:
        """Return resources of one supported type in manifest order."""
        return tuple(item for item in self.resources if item.type == resource_type)

    @property
    def files(self) -> tuple[RemoteFile, ...]:
        """Flatten all files for cache download."""
        return tuple(file for resource in self.resources for file in resource.files)

    def to_bytes(self) -> bytes:
        """Serialize the validated manifest for an atomically materialized view."""
        resources = [
            {
                "id": resource.identifier,
                "type": resource.type,
                "version": resource.version,
                "files": [
                    {"path": file.path, "size": file.size, "sha256": file.sha256}
                    for file in resource.files
                ],
                "metadata": dict(resource.metadata),
            }
            for resource in self.resources
        ]
        return json.dumps(
            {"schema_version": self.schema_version, "catalog_version": self.catalog_version, "resources": resources},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")


def _parse_resource(raw: object, index: int, known_paths: set[str]) -> RemoteResource:
    if not isinstance(raw, Mapping):
        raise ManifestError(f"resources[{index}] 必须是对象")
    identifier = raw.get("id")
    if not isinstance(identifier, str) or not _IDENTIFIER.fullmatch(identifier):
        raise ManifestError(f"resources[{index}].id 无效")
    resource_type = raw.get("type")
    if not isinstance(resource_type, str) or resource_type not in _RESOURCE_TYPES:
        raise ManifestError(f"资源 {identifier} 的 type 不受支持")
    version = raw.get("version")
    if not isinstance(version, str) or not _VERSION.fullmatch(version):
        raise ManifestError(f"资源 {identifier} 的 version 无效")

    raw_files = raw.get("files")
    if not isinstance(raw_files, list) or not raw_files:
        raise ManifestError(f"资源 {identifier} 必须包含 files")
    files = tuple(_parse_file(item, identifier, known_paths) for item in raw_files)

    metadata = raw.get("metadata", {})
    if not isinstance(metadata, Mapping):
        raise ManifestError(f"资源 {identifier} 的 metadata 必须是对象")
    return RemoteResource(identifier, resource_type, version, files, MappingProxyType(dict(metadata)))


def _parse_file(raw: object, identifier: str, known_paths: set[str]) -> RemoteFile:
    if not isinstance(raw, Mapping):
        raise ManifestError(f"资源 {identifier} 的文件描述必须是对象")
    path = raw.get("path")
    if not isinstance(path, str) or not _is_safe_path(path):
        raise ManifestError(f"资源 {identifier} 的 path 不安全")
    if path in known_paths:
        raise ManifestError(f"duplicate file path: {path}")
    known_paths.add(path)
    size = raw.get("size")
    if type(size) is not int or size < 0:
        raise ManifestError(f"文件 {path} 的 size 无效")
    digest = raw.get("sha256")
    if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
        raise ManifestError(f"文件 {path} 的 sha256 无效")
    return RemoteFile(path, size, digest.lower())


def _is_safe_path(path: str) -> bool:
    if not path or "\\" in path or "\x00" in path or ":" in path:
        return False
    if path.startswith("/") or re.match(r"^[A-Za-z]:", path):
        return False
    parts = path.split("/")
    if not parts or parts[0] != "resources":
        return False
    if any(
        part in {"", ".", ".."}
        or part.rstrip(" .") != part
        or part.casefold().split(".", 1)[0] in _WINDOWS_RESERVED_NAMES
        for part in parts
    ):
        return False
    return PurePosixPath(path).as_posix() == path


def _windows_normalized_path(path: str) -> str:
    """Return the case/trim normalization used by Windows file lookup."""
    return "/".join(part.rstrip(" .").casefold() for part in path.split("/"))


def sha256_bytes(payload: bytes) -> str:
    """Return the lowercase SHA-256 digest used by cache verification."""
    return hashlib.sha256(payload).hexdigest()
