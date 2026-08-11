"""Download, verify, and atomically cache remote PetNest resources."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import shutil
from threading import Lock
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
import uuid
from zipfile import BadZipFile, ZipFile, ZipInfo

from petnest.core.remote_resource_manifest import ManifestError, RemoteFile, RemoteResource, ResourceManifest


LOGGER = logging.getLogger(__name__)
_CHUNK_SIZE = 1024 * 1024
_DOWNLOAD_WORKERS = 8
_VERSION_RETENTION = 2
_RETRYABLE_HTTP_STATUSES = frozenset({429, 500, 502, 503, 504})


class RemoteResourceError(RuntimeError):
    """Raised when the remote catalog or a downloaded file cannot be trusted."""


class RemoteResourceHTTPError(RemoteResourceError):
    """A remote endpoint returned an HTTP error, retaining its status code."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


class RemoteResourceTransientError(RemoteResourceError):
    """A network error that is safe to retry for one resource file."""


@dataclass(frozen=True, slots=True)
class ResourceSyncFailure:
    """One resource that could not be activated during a partial sync."""

    identifier: str
    error: str


@dataclass(frozen=True, slots=True)
class ResourceSyncResult:
    """Result of an independent resource sync.

    Successful resources are already active when this result is returned.  A
    failed resource keeps its previous generation (or the bundled fallback if
    it had never been downloaded).
    """

    manifest: ResourceManifest
    applied_resource_ids: tuple[str, ...] = ()
    removed_resource_ids: tuple[str, ...] = ()
    failures: tuple[ResourceSyncFailure, ...] = ()

    @property
    def complete(self) -> bool:
        return not self.failures


class RemoteResourceCache:
    """Keep a verified copy of resources under a user-writable directory.

    ``base_url`` is the public Worker URL, without the ``/v1`` suffix.  The
    GitHub token is intentionally not used by this client; it stays in the
    Worker secret environment.
    """

    def __init__(
        self,
        root: Path,
        base_url: str,
        *,
        timeout: float = 20.0,
        opener: Callable[..., Any] | None = None,
        retry_attempts: int = 3,
        retry_delay: float = 0.5,
        seed_root: Path | None = None,
    ) -> None:
        normalized = base_url.strip().rstrip("/")
        if not normalized:
            raise ValueError("base_url 不能为空")
        self.root = Path(root)
        self.base_url = normalized
        self.timeout = timeout
        self._opener = opener or urlopen
        if retry_attempts < 1:
            raise ValueError("retry_attempts 必须至少为 1")
        if retry_delay < 0:
            raise ValueError("retry_delay 不能为负数")
        self.retry_attempts = retry_attempts
        self.retry_delay = retry_delay
        self.seed_root = Path(seed_root) if seed_root is not None else None
        self._sync_lock = Lock()

    @property
    def manifest_path(self) -> Path:
        """Legacy root manifest path retained for older cache layouts."""
        return self.root / "manifest.json"

    @property
    def current_pointer_path(self) -> Path:
        return self.root / "current.json"

    @property
    def versions_path(self) -> Path:
        return self.root / "versions"

    @property
    def current_root(self) -> Path | None:
        """Return the validated immutable directory selected by current.json."""
        try:
            pointer = json.loads(self.current_pointer_path.read_text(encoding="utf-8"))
            version_id = pointer.get("version_id")
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return self._legacy_root()
        if not isinstance(version_id, str) or not _VERSION_ID.fullmatch(version_id):
            return self._legacy_root()
        candidate = self.versions_path / version_id
        return candidate if candidate.is_dir() else self._legacy_root()

    def _legacy_root(self) -> Path | None:
        """Return a verified pre-versioned cache root for one-time migration."""
        if self.versions_path.is_dir() and any(
            item.is_dir() and _VERSION_ID.fullmatch(item.name) for item in self.versions_path.iterdir()
        ):
            # A versioned view has already been materialized. Never resurrect
            # the stale legacy tree when its pointer is damaged.
            return None
        resources_root = self.root / "resources"
        if not resources_root.is_dir():
            return None
        try:
            manifest = ResourceManifest.from_bytes(self.manifest_path.read_bytes())
        except (OSError, ManifestError):
            return None
        if not all(_file_matches(_join_relative(self.root, remote_file.path), remote_file) for remote_file in manifest.files):
            return None
        return self.root

    def load_current_manifest(self) -> ResourceManifest | None:
        current = self.current_root
        if current is None:
            return None
        try:
            return ResourceManifest.from_bytes((current / "manifest.json").read_bytes())
        except (OSError, ManifestError):
            return None

    def sync(self, *, progress: Callable[[int], object] | None = None) -> ResourceManifest:
        """Fetch and verify a catalog, requiring every resource to succeed.

        The legacy API remains strict for callers that expect an exception on
        failure.  The update coordinator uses :meth:`sync_partial` so
        independent resources can be activated one by one.
        """
        result = self.sync_partial(progress=progress)
        if result.failures:
            details = "；".join(f"{failure.identifier}: {failure.error}" for failure in result.failures)
            raise RemoteResourceError(f"部分资源更新失败：{details}")
        return result.manifest

    def sync_partial(self, *, progress: Callable[[int], object] | None = None) -> ResourceSyncResult:
        """Synchronize resources independently and activate each successful one."""
        try:
            manifest_payload = self._fetch_bytes(self._manifest_url())
            manifest = ResourceManifest.from_bytes(manifest_payload)
        except RemoteResourceError:
            raise
        except (ManifestError, OSError, UnicodeError) as error:
            raise RemoteResourceError(f"无法读取远程资源 manifest: {error}") from error

        progress_reporter = _ProgressReporter(sum(file.size for file in manifest.files), progress)
        staging = self.root / "staging" / uuid.uuid4().hex
        with self._sync_lock:
            return self._sync_partial_locked(manifest, staging, progress_reporter)

    def _sync_partial_locked(
        self,
        manifest: ResourceManifest,
        staging: Path,
        progress: "_ProgressReporter",
    ) -> ResourceSyncResult:
        current_root = self.current_root
        active_manifest = self.load_current_manifest() if current_root is not None else None
        applied_resource_ids: list[str] = []
        removed_resource_ids: list[str] = []
        failures: list[ResourceSyncFailure] = []
        prepared: dict[str, tuple[RemoteFile, ...]] = {}
        old_resources: dict[str, RemoteResource | None] = {}
        try:
            staging.mkdir(parents=True, exist_ok=False)

            # Removed resources are independent too.  If materializing the
            # new view fails, the previous resource remains available.
            if active_manifest is not None:
                for old_resource in active_manifest.resources:
                    if manifest.resource(old_resource.identifier) is not None:
                        continue
                    try:
                        next_manifest = _without_resource(active_manifest, old_resource.identifier, manifest.catalog_version)
                        current_root = self._commit_view(
                            current_root,
                            next_manifest,
                            staging,
                            old_resource=old_resource,
                        )
                        active_manifest = next_manifest
                        removed_resource_ids.append(old_resource.identifier)
                    except (OSError, RemoteResourceError, URLError) as error:
                        failures.append(ResourceSyncFailure(old_resource.identifier, str(error) or error.__class__.__name__))

            # Stage reusable files first.  A resource is either unchanged and
            # already valid, or it gets a complete private file set before any
            # view switch is attempted.
            for resource in manifest.resources:
                previous = active_manifest.resource(resource.identifier) if active_manifest is not None else None
                if (
                    previous is not None
                    and _resource_signature(previous) == _resource_signature(resource)
                    and self._resource_files_valid(current_root, resource)
                ):
                    for remote_file in resource.files:
                        progress.file_completed(remote_file.size)
                    continue
                try:
                    pending = self._stage_reusable_files(
                        resource,
                        previous,
                        current_root,
                        staging,
                        progress,
                    )
                    prepared[resource.identifier] = tuple(pending)
                    old_resources[resource.identifier] = previous
                except (OSError, RemoteResourceError, URLError) as error:
                    failures.append(ResourceSyncFailure(resource.identifier, str(error) or error.__class__.__name__))

            pending_count = sum(len(files) for files in prepared.values())
            if (
                current_root is None
                and active_manifest is None
                and pending_count == len(manifest.files)
                and pending_count > 0
            ):
                try:
                    # The archive is only an optimization for a truly cold
                    # cache. Once any local generation or bundled seed exists,
                    # per-resource requests preserve independent failures.
                    self._download_archive(staging, manifest, progress)
                    prepared = {identifier: () for identifier in prepared}
                except RemoteResourceError as error:
                    # The archive is an optional transport optimization.  Any
                    # gateway error or corrupt archive falls back to the
                    # resource-scoped file requests so one bad transport does
                    # not block unrelated resources.
                    LOGGER.warning("资源归档不可用，回退逐资源下载：%s", error)
                    _remove_staged_files(staging, manifest.files)

            for resource in manifest.resources:
                if resource.identifier not in prepared:
                    continue
                pending = list(prepared[resource.identifier])
                previous = old_resources.get(resource.identifier)
                if pending:
                    try:
                        self._download_manifest_files(pending, staging, progress)
                    except (OSError, RemoteResourceError, URLError) as error:
                        self._remove_staged_resource(staging, resource)
                        failures.append(ResourceSyncFailure(resource.identifier, str(error) or error.__class__.__name__))
                        continue
                if not self._resource_files_valid(staging, resource):
                    self._remove_staged_resource(staging, resource)
                    failures.append(ResourceSyncFailure(resource.identifier, "资源文件校验失败"))
                    continue
                try:
                    next_manifest = _with_resource(active_manifest, resource, manifest.catalog_version)
                    current_root = self._commit_view(
                        current_root,
                        next_manifest,
                        staging,
                        old_resource=previous,
                        new_resource=resource,
                    )
                    active_manifest = next_manifest
                    applied_resource_ids.append(resource.identifier)
                except (OSError, RemoteResourceError, URLError) as error:
                    self._remove_staged_resource(staging, resource)
                    failures.append(ResourceSyncFailure(resource.identifier, str(error) or error.__class__.__name__))

            # Keep catalog metadata/order aligned with the remote manifest.
            # A failed resource intentionally remains represented by its old
            # entry, so the next check keeps the update available.
            if active_manifest is None and not manifest.resources and not failures:
                current_root = self._commit_view(None, manifest, staging)
                active_manifest = manifest
            elif active_manifest is not None and (not failures or applied_resource_ids or removed_resource_ids):
                normalized = _ordered_active_manifest(active_manifest, manifest)
                legacy_view = current_root is not None and current_root.resolve() == self.root.resolve()
                if normalized != active_manifest or legacy_view:
                    try:
                        current_root = self._commit_view(
                            current_root,
                            normalized,
                            staging,
                        )
                        active_manifest = normalized
                    except (OSError, RemoteResourceError, URLError) as error:
                        # Earlier resource switches are already valid. Keep
                        # them active and leave the badge for this metadata
                        # view retry instead of hiding the partial success.
                        failures.append(ResourceSyncFailure("catalog", str(error) or error.__class__.__name__))
            if not failures:
                self._prune_old_versions(current_root)
                progress.complete()
            return ResourceSyncResult(
                manifest=manifest,
                applied_resource_ids=tuple(applied_resource_ids),
                removed_resource_ids=tuple(removed_resource_ids),
                failures=tuple(failures),
            )
        except RemoteResourceError:
            raise
        except (OSError, URLError) as error:
            raise RemoteResourceError(f"无法提交远程资源缓存: {error}") from error
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    def fetch_manifest(self) -> ResourceManifest:
        """Fetch and validate only the catalog, without downloading its files."""
        try:
            return ResourceManifest.from_bytes(self._fetch_bytes(self._manifest_url()))
        except RemoteResourceError:
            raise
        except (ManifestError, OSError, UnicodeError) as error:
            raise RemoteResourceError(f"无法读取远程资源 manifest: {error}") from error

    def sync_or_cached(self) -> ResourceManifest | None:
        """Prefer fresh resources, falling back to the last valid cache offline."""
        try:
            return self.sync()
        except RemoteResourceError as error:
            LOGGER.warning("远程资源同步失败，使用本地缓存：%s", error)
            return self.load_cached()

    def load_cached(self) -> ResourceManifest | None:
        """Load the last manifest, returning ``None`` if it is absent/corrupt."""
        current = self.load_current_manifest()
        if current is not None:
            return current
        try:
            return ResourceManifest.from_bytes(self.manifest_path.read_bytes())
        except (OSError, ManifestError):
            return None

    def path_for(self, file: RemoteFile | str) -> Path:
        """Resolve a manifest file into the cache root without path traversal."""
        relative = file.path if isinstance(file, RemoteFile) else file
        if not _is_manifest_path(relative):
            raise ValueError("资源文件路径不安全")
        return _join_relative(self.current_root or self.root, relative)

    def _manifest_url(self) -> str:
        return f"{self.base_url}/v1/manifest.json"

    def _file_url(self, path: str) -> str:
        return f"{self.base_url}/v1/files/{quote(path, safe='/')}"

    def _archive_url(self) -> str:
        return f"{self.base_url}/v1/archive.zip"

    def _fetch_bytes(self, url: str) -> bytes:
        request = Request(url, headers={"Accept": "application/octet-stream", "User-Agent": "PetNest/0.1"})
        try:
            with self._opener(request, timeout=self.timeout) as response:
                status = getattr(response, "status", 200)
                if status is not None and status >= 400:
                    raise RemoteResourceHTTPError(status, f"远程服务器返回 HTTP {status}")
                return response.read()
        except RemoteResourceError:
            raise
        except HTTPError as error:
            raise RemoteResourceHTTPError(error.code, f"请求资源失败：HTTP {error.code}") from error
        except (OSError, URLError) as error:
            raise RemoteResourceError(f"请求资源失败: {error}") from error

    def _download_verified(self, remote_file: RemoteFile, target: Path) -> None:
        last_error: RemoteResourceError | None = None
        for attempt in range(self.retry_attempts):
            try:
                self._download_verified_once(remote_file, target)
                return
            except RemoteResourceHTTPError as error:
                if error.status not in _RETRYABLE_HTTP_STATUSES:
                    raise
                last_error = error
            except RemoteResourceTransientError as error:
                last_error = error
            if attempt + 1 < self.retry_attempts:
                time.sleep(self.retry_delay * (2**attempt))
        assert last_error is not None
        raise last_error

    def _download_verified_once(self, remote_file: RemoteFile, target: Path) -> None:
        request = Request(
            self._file_url(remote_file.path),
            headers={"Accept": "application/octet-stream", "User-Agent": "PetNest/0.1"},
        )
        digest = hashlib.sha256()
        total = 0
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self._opener(request, timeout=self.timeout) as response, target.open("wb") as stream:
                status = getattr(response, "status", 200)
                if status is not None and status >= 400:
                    raise RemoteResourceHTTPError(status, f"下载 {remote_file.path} 失败：HTTP {status}")
                while True:
                    chunk = response.read(_CHUNK_SIZE)
                    if not chunk:
                        break
                    stream.write(chunk)
                    digest.update(chunk)
                    total += len(chunk)
        except RemoteResourceError:
            target.unlink(missing_ok=True)
            raise
        except HTTPError as error:
            target.unlink(missing_ok=True)
            raise RemoteResourceHTTPError(error.code, f"下载 {remote_file.path} 失败：HTTP {error.code}") from error
        except (OSError, URLError) as error:
            target.unlink(missing_ok=True)
            raise RemoteResourceTransientError(f"下载 {remote_file.path} 失败: {error}") from error

        actual_digest = digest.hexdigest()
        if total != remote_file.size:
            target.unlink(missing_ok=True)
            raise RemoteResourceError(
                f"文件大小不匹配: {remote_file.path} (expected {remote_file.size}, got {total})"
            )
        if actual_digest != remote_file.sha256:
            target.unlink(missing_ok=True)
            raise RemoteResourceError(f"sha256 校验失败: {remote_file.path}")

    def _download_archive(self, staging: Path, manifest: ResourceManifest, progress: "_ProgressReporter") -> None:
        """下载 Worker 提供的 GitHub zipball，并按 manifest 解包校验。"""
        archive_path = staging.parent / f"{staging.name}.zip"
        request = Request(
            self._archive_url(),
            headers={"Accept": "application/zip", "User-Agent": "PetNest/0.1"},
        )
        try:
            with self._opener(request, timeout=self.timeout) as response, archive_path.open("wb") as stream:
                status = getattr(response, "status", 200)
                if status is not None and status >= 400:
                    raise RemoteResourceHTTPError(status, f"下载资源归档失败：HTTP {status}")
                while True:
                    chunk = response.read(_CHUNK_SIZE)
                    if not chunk:
                        break
                    stream.write(chunk)
        except RemoteResourceError:
            archive_path.unlink(missing_ok=True)
            raise
        except HTTPError as error:
            archive_path.unlink(missing_ok=True)
            raise RemoteResourceHTTPError(error.code, f"下载资源归档失败：HTTP {error.code}") from error
        except (OSError, HTTPError, URLError) as error:
            archive_path.unlink(missing_ok=True)
            raise RemoteResourceError(f"下载资源归档失败: {error}") from error

        try:
            self._extract_archive(archive_path, staging, manifest)
            for remote_file in manifest.files:
                progress.file_completed(remote_file.size)
        except (BadZipFile, OSError, KeyError) as error:
            raise RemoteResourceError(f"资源归档无效: {error}") from error
        finally:
            archive_path.unlink(missing_ok=True)

    def _extract_archive(
        self,
        archive_path: Path,
        staging: Path,
        manifest: ResourceManifest,
    ) -> None:
        with ZipFile(archive_path) as archive:
            entries: dict[str, ZipInfo] = {}
            for info in archive.infolist():
                if info.is_dir():
                    continue
                relative = _archive_relative_path(info.filename)
                if relative is not None:
                    if relative in entries:
                        raise RemoteResourceError(f"资源归档包含重复路径: {relative}")
                    entries[relative] = info
            for remote_file in manifest.files:
                info = entries.get(remote_file.path)
                if info is None:
                    raise RemoteResourceError(f"资源归档缺少文件: {remote_file.path}")
                target = _join_relative(staging, remote_file.path)
                target.parent.mkdir(parents=True, exist_ok=True)
                digest = hashlib.sha256()
                total = 0
                with archive.open(info) as source, target.open("wb") as stream:
                    while True:
                        chunk = source.read(_CHUNK_SIZE)
                        if not chunk:
                            break
                        stream.write(chunk)
                        digest.update(chunk)
                        total += len(chunk)
                if total != remote_file.size or digest.hexdigest() != remote_file.sha256:
                    target.unlink(missing_ok=True)
                    raise RemoteResourceError(f"归档中的文件校验失败: {remote_file.path}")

    def _download_manifest_files(
        self,
        remote_files: list[RemoteFile],
        staging: Path,
        progress: "_ProgressReporter",
    ) -> None:
        """并行下载互不相交的文件，仍在全部完成后才提交版本指针。"""
        if not remote_files:
            return
        workers = min(_DOWNLOAD_WORKERS, len(remote_files))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="petnest-resource") as executor:
            futures = [
                executor.submit(self._download_verified, remote_file, _join_relative(staging, remote_file.path))
                for remote_file in remote_files
            ]
            for remote_file, future in zip(remote_files, futures, strict=True):
                future.result()
                progress.file_completed(remote_file.size)

    def _stage_reusable_files(
        self,
        resource: RemoteResource,
        previous: RemoteResource | None,
        current_root: Path | None,
        staging: Path,
        progress: "_ProgressReporter",
    ) -> list[RemoteFile]:
        """Copy matching files for one resource and return network pending files."""
        pending: list[RemoteFile] = []
        for remote_file in resource.files:
            source: Path | None = None
            source_is_seed = False
            if previous is not None and current_root is not None:
                candidate = _join_relative(current_root, remote_file.path)
                if _file_matches(candidate, remote_file):
                    source = candidate
            if source is None:
                candidate = _bundled_resource_path(self.seed_root, remote_file)
                if candidate is not None and _file_matches(candidate, remote_file):
                    source = candidate
                    source_is_seed = True
            if source is None:
                pending.append(remote_file)
                continue
            target = _join_relative(staging, remote_file.path)
            target.parent.mkdir(parents=True, exist_ok=True)
            if source_is_seed:
                _copy_file_contents(source, target)
            else:
                _copy_file(source, target)
            progress.file_completed(remote_file.size)
        return pending

    @staticmethod
    def _resource_files_valid(root: Path | None, resource: RemoteResource) -> bool:
        return root is not None and all(_file_matches(_join_relative(root, file.path), file) for file in resource.files)

    @staticmethod
    def _remove_staged_resource(staging: Path, resource: RemoteResource) -> None:
        for remote_file in resource.files:
            target = _join_relative(staging, remote_file.path)
            target.unlink(missing_ok=True)
            _prune_empty_parents(target.parent, staging)

    def _commit_view(
        self,
        base_root: Path | None,
        new_manifest: ResourceManifest,
        staging: Path,
        *,
        old_resource: RemoteResource | None = None,
        new_resource: RemoteResource | None = None,
    ) -> Path:
        """Materialize a new mixed-resource view and switch its pointer atomically."""
        view_staging = staging / f"view-{uuid.uuid4().hex}"
        try:
            if base_root is not None and base_root.is_dir():
                _clone_active_view(base_root, self.root, view_staging)
            else:
                view_staging.mkdir(parents=True, exist_ok=False)
            if old_resource is not None:
                _remove_resource_from_tree(view_staging, old_resource)
            _overlay_bundled_fallbacks(self.seed_root, view_staging)
            if new_resource is not None:
                for remote_file in new_resource.files:
                    source = _join_relative(staging, remote_file.path)
                    if not _file_matches(source, remote_file):
                        raise RemoteResourceError(f"资源文件校验失败: {remote_file.path}")
                    target = _join_relative(view_staging, remote_file.path)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    _copy_file(source, target)

            manifest_payload = new_manifest.to_bytes()
            manifest_path = view_staging / "manifest.json"
            manifest_path.unlink(missing_ok=True)
            manifest_path.write_bytes(manifest_payload)
            digest = hashlib.sha256(manifest_payload).hexdigest()
            version_id = f"{new_manifest.catalog_version}-{digest[:12]}"
            version_root = self.versions_path / version_id
            if version_root.exists():
                # Never delete an immutable view (it may still be selected by
                # another process after a crash); use a fresh id instead.
                version_id = f"{new_manifest.catalog_version}-{hashlib.sha256(manifest_payload + uuid.uuid4().bytes).hexdigest()[:12]}"
                version_root = self.versions_path / version_id
            self.versions_path.mkdir(parents=True, exist_ok=True)
            view_staging.replace(version_root)
            self._write_pointer(
                {
                    "schema_version": 2,
                    "catalog_version": new_manifest.catalog_version,
                    "version_id": version_id,
                    "manifest_sha256": digest,
                    "resource_ids": [resource.identifier for resource in new_manifest.resources],
                }
            )
            return version_root
        finally:
            shutil.rmtree(view_staging, ignore_errors=True)

    def _write_pointer(self, payload: dict[str, object]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.root / f".current-{uuid.uuid4().hex}.tmp"
        try:
            temporary.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
            temporary.replace(self.current_pointer_path)
        finally:
            temporary.unlink(missing_ok=True)

    def _prune_old_versions(self, active_root: Path | None) -> None:
        """Keep the active view and one recent rollback view only.

        A cleanup failure must never turn a successful resource update into a
        failed update.  Symlinked or malformed entries are ignored so cleanup
        cannot escape the cache's ``versions`` directory.
        """
        if active_root is None:
            return
        versions_root = self.versions_path
        try:
            versions_resolved = versions_root.resolve()
            active_resolved = active_root.resolve()
            if (
                active_root.is_symlink()
                or not active_root.is_dir()
                or active_resolved.parent != versions_resolved
            ):
                return
            candidates: list[tuple[int, Path]] = []
            for candidate in versions_root.iterdir():
                if candidate.is_symlink() or not candidate.is_dir() or not _VERSION_ID.fullmatch(candidate.name):
                    continue
                try:
                    candidates.append((candidate.stat().st_mtime_ns, candidate))
                except OSError:
                    continue
            candidates.sort(key=lambda item: (item[0], item[1].name), reverse=True)
            keep = {active_root.name}
            for _mtime, candidate in candidates:
                if len(keep) >= _VERSION_RETENTION:
                    break
                keep.add(candidate.name)
            for _mtime, candidate in candidates:
                if candidate.name in keep:
                    continue
                try:
                    if candidate.resolve().parent != versions_resolved:
                        continue
                    shutil.rmtree(candidate)
                except (OSError, RuntimeError) as error:
                    LOGGER.warning("无法清理旧资源缓存版本 %s：%s", candidate, error)
        except (OSError, RuntimeError) as error:
            LOGGER.warning("无法扫描旧资源缓存版本：%s", error)


def _clone_tree(source: Path, target: Path) -> None:
    """Clone an immutable view, preferring hard links to avoid duplicate bytes."""
    shutil.copytree(source, target, copy_function=_link_or_copy)


def _clone_active_view(source: Path, cache_root: Path, target: Path) -> None:
    """Clone only view data, excluding legacy cache control files."""
    if source.resolve() != cache_root.resolve():
        _clone_tree(source, target)
        return
    target.mkdir(parents=True, exist_ok=False)
    source_resources = source / "resources"
    if source_resources.is_dir():
        _clone_tree(source_resources, target / "resources")
    source_manifest = source / "manifest.json"
    if source_manifest.is_file():
        _copy_file(source_manifest, target / "manifest.json")


def _overlay_bundled_fallbacks(seed_root: Path | None, target: Path) -> None:
    """Keep trusted bundled defaults visible for resources not yet applied."""
    if seed_root is None:
        return
    mappings = (
        (seed_root / "assets" / "cursors", target / "resources" / "cursors"),
        (seed_root / "assets" / "countdown", target / "resources" / "countdown"),
        (seed_root / "effects", target / "resources" / "effects"),
    )
    for source_root, target_root in mappings:
        if not source_root.is_dir():
            continue
        for source in source_root.rglob("*"):
            if not source.is_file():
                continue
            destination = target_root / source.relative_to(source_root)
            if destination.exists():
                continue
            try:
                _copy_file_contents(source, destination)
            except OSError:
                LOGGER.warning("无法写入默认资源回退文件：%s", destination, exc_info=True)


def _link_or_copy(source: str, target: str) -> None:
    destination = Path(target)
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, target)
    except OSError:
        shutil.copyfile(source, target)


def _copy_file(source: Path, target: Path) -> None:
    """Copy without modifying a hard-linked source in an older view."""
    target.unlink(missing_ok=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    _link_or_copy(str(source), str(target))


def _copy_file_contents(source: Path, target: Path) -> None:
    """Copy bundled seed bytes rather than linking into the install bundle."""
    target.unlink(missing_ok=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)


def _remove_resource_from_tree(root: Path, resource: RemoteResource) -> None:
    for remote_file in resource.files:
        target = _join_relative(root, remote_file.path)
        target.unlink(missing_ok=True)
        _prune_empty_parents(target.parent, root)


def _remove_staged_files(staging: Path, remote_files: tuple[RemoteFile, ...]) -> None:
    for remote_file in remote_files:
        target = _join_relative(staging, remote_file.path)
        target.unlink(missing_ok=True)
        _prune_empty_parents(target.parent, staging)


def _prune_empty_parents(directory: Path, stop: Path) -> None:
    current = directory
    stop = stop.resolve()
    while current != stop and current != current.parent:
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent


def _with_resource(
    active_manifest: ResourceManifest | None,
    resource: RemoteResource,
    catalog_version: str,
) -> ResourceManifest:
    resources = list(active_manifest.resources) if active_manifest is not None else []
    for index, existing in enumerate(resources):
        if existing.identifier == resource.identifier:
            resources[index] = resource
            break
    else:
        resources.append(resource)
    return ResourceManifest(1, catalog_version, tuple(resources))


def _without_resource(active_manifest: ResourceManifest, identifier: str, catalog_version: str) -> ResourceManifest:
    return ResourceManifest(
        1,
        catalog_version,
        tuple(resource for resource in active_manifest.resources if resource.identifier != identifier),
    )


def _ordered_active_manifest(active_manifest: ResourceManifest, remote_manifest: ResourceManifest) -> ResourceManifest:
    active = {resource.identifier: resource for resource in active_manifest.resources}
    ordered = [active[resource.identifier] for resource in remote_manifest.resources if resource.identifier in active]
    remote_ids = {resource.identifier for resource in remote_manifest.resources}
    ordered.extend(resource for resource in active_manifest.resources if resource.identifier not in remote_ids)
    return ResourceManifest(1, remote_manifest.catalog_version, tuple(ordered))


def _resource_signature(resource: RemoteResource) -> tuple[object, ...]:
    metadata = json.dumps(dict(resource.metadata), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    files = tuple((file.path, file.size, file.sha256) for file in resource.files)
    return resource.identifier, resource.type, resource.version, files, metadata


def _is_manifest_path(path: str) -> bool:
    if not path or not path.startswith("resources/") or "\\" in path:
        return False
    parts = path.split("/")
    return (
        all(part not in {"", ".", ".."} for part in parts)
        and Path(*parts).as_posix() == path
    )


def _archive_relative_path(name: str) -> str | None:
    """Map a GitHub zipball entry to its safe ``resources/...`` path."""
    parts = name.split("/")
    if not parts or any(part in {"", ".", ".."} for part in parts):
        return None
    if parts[0] == "resources":
        candidate = "/".join(parts)
    elif len(parts) >= 2:
        candidate = "/".join(parts[1:])
    else:
        return None
    return candidate if _is_manifest_path(candidate) else None


class _ProgressReporter:
    """将已校验文件字节数转换为最多 101 次的单调百分比通知。"""

    def __init__(self, total: int, callback: Callable[[int], object] | None) -> None:
        self._total = max(0, total)
        self._callback = callback
        self._completed = 0
        self._last = -1
        self._lock = Lock()

    def file_completed(self, size: int) -> None:
        if self._callback is None:
            return
        with self._lock:
            self._completed += max(0, size)
            percentage = 99 if self._total == 0 else min(99, self._completed * 100 // self._total)
            if percentage == self._last:
                return
            self._last = percentage
        self._callback(percentage)

    def complete(self) -> None:
        if self._callback is None:
            return
        with self._lock:
            if self._last == 100:
                return
            self._last = 100
        self._callback(100)


_VERSION_ID = re.compile(r"^\d+\.\d+\.\d+-[0-9a-f]{12}$")


def _join_relative(root: Path, path: str) -> Path:
    if not _is_manifest_path(path):
        raise RemoteResourceError(f"资源文件路径不安全: {path}")
    return root.joinpath(*path.split("/"))


def _file_matches(path: Path, remote_file: RemoteFile) -> bool:
    try:
        if not path.is_file() or path.stat().st_size != remote_file.size:
            return False
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while True:
                chunk = stream.read(_CHUNK_SIZE)
                if not chunk:
                    break
                digest.update(chunk)
        return digest.hexdigest() == remote_file.sha256
    except OSError:
        return False


def _bundled_resource_path(seed_root: Path | None, remote_file: RemoteFile) -> Path | None:
    if seed_root is None:
        return None
    parts = remote_file.path.split("/")
    if len(parts) < 3 or parts[0] != "resources":
        return None
    category_root = {
        "cursors": seed_root / "assets" / "cursors",
        "countdown": seed_root / "assets" / "countdown",
        "effects": seed_root / "effects",
    }.get(parts[1])
    return category_root.joinpath(*parts[2:]) if category_root is not None else None
