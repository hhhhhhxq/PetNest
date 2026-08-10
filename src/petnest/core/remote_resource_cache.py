"""Download, verify, and atomically cache remote PetNest resources."""

from __future__ import annotations

from collections.abc import Callable
import hashlib
import logging
from pathlib import Path
import shutil
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
import uuid

from petnest.core.remote_resource_manifest import ManifestError, RemoteFile, ResourceManifest


LOGGER = logging.getLogger(__name__)
_CHUNK_SIZE = 1024 * 1024


class RemoteResourceError(RuntimeError):
    """Raised when the remote catalog or a downloaded file cannot be trusted."""


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
    ) -> None:
        normalized = base_url.strip().rstrip("/")
        if not normalized:
            raise ValueError("base_url 不能为空")
        self.root = Path(root)
        self.base_url = normalized
        self.timeout = timeout
        self._opener = opener or urlopen

    @property
    def manifest_path(self) -> Path:
        return self.root / "manifest.json"

    def sync(self) -> ResourceManifest:
        """Fetch and verify a complete catalog before committing it locally."""
        try:
            manifest_payload = self._fetch_bytes(self._manifest_url())
            manifest = ResourceManifest.from_bytes(manifest_payload)
        except RemoteResourceError:
            raise
        except (ManifestError, OSError, UnicodeError) as error:
            raise RemoteResourceError(f"无法读取远程资源 manifest: {error}") from error

        staging = self.root / f".staging-{uuid.uuid4().hex}"
        try:
            staging.mkdir(parents=True, exist_ok=False)
            for remote_file in manifest.files:
                staged_path = _join_relative(staging, remote_file.path)
                self._download_verified(remote_file, staged_path)

            self.root.mkdir(parents=True, exist_ok=True)
            for remote_file in manifest.files:
                staged_path = _join_relative(staging, remote_file.path)
                target_path = _join_relative(self.root, remote_file.path)
                target_path.parent.mkdir(parents=True, exist_ok=True)
                staged_path.replace(target_path)
            self._write_manifest(manifest_payload)
            return manifest
        except RemoteResourceError:
            raise
        except (OSError, HTTPError, URLError) as error:
            raise RemoteResourceError(f"无法提交远程资源缓存: {error}") from error
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    def sync_or_cached(self) -> ResourceManifest | None:
        """Prefer fresh resources, falling back to the last valid cache offline."""
        try:
            return self.sync()
        except RemoteResourceError as error:
            LOGGER.warning("远程资源同步失败，使用本地缓存：%s", error)
            return self.load_cached()

    def load_cached(self) -> ResourceManifest | None:
        """Load the last manifest, returning ``None`` if it is absent/corrupt."""
        try:
            return ResourceManifest.from_bytes(self.manifest_path.read_bytes())
        except (OSError, ManifestError):
            return None

    def path_for(self, file: RemoteFile | str) -> Path:
        """Resolve a manifest file into the cache root without path traversal."""
        relative = file.path if isinstance(file, RemoteFile) else file
        if not _is_manifest_path(relative):
            raise ValueError("资源文件路径不安全")
        return _join_relative(self.root, relative)

    def _manifest_url(self) -> str:
        return f"{self.base_url}/v1/manifest.json"

    def _file_url(self, path: str) -> str:
        return f"{self.base_url}/v1/files/{quote(path, safe='/')}"

    def _fetch_bytes(self, url: str) -> bytes:
        request = Request(url, headers={"Accept": "application/octet-stream", "User-Agent": "PetNest/0.1"})
        try:
            with self._opener(request, timeout=self.timeout) as response:
                status = getattr(response, "status", 200)
                if status is not None and status >= 400:
                    raise RemoteResourceError(f"远程服务器返回 HTTP {status}")
                return response.read()
        except RemoteResourceError:
            raise
        except (OSError, HTTPError, URLError) as error:
            raise RemoteResourceError(f"请求资源失败: {error}") from error

    def _download_verified(self, remote_file: RemoteFile, target: Path) -> None:
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
                    raise RemoteResourceError(f"下载 {remote_file.path} 失败：HTTP {status}")
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
        except (OSError, HTTPError, URLError) as error:
            target.unlink(missing_ok=True)
            raise RemoteResourceError(f"下载 {remote_file.path} 失败: {error}") from error

        actual_digest = digest.hexdigest()
        if total != remote_file.size:
            target.unlink(missing_ok=True)
            raise RemoteResourceError(
                f"文件大小不匹配: {remote_file.path} (expected {remote_file.size}, got {total})"
            )
        if actual_digest != remote_file.sha256:
            target.unlink(missing_ok=True)
            raise RemoteResourceError(f"sha256 校验失败: {remote_file.path}")

    def _write_manifest(self, payload: bytes) -> None:
        temporary = self.root / f".manifest-{uuid.uuid4().hex}.tmp"
        try:
            temporary.write_bytes(payload)
            temporary.replace(self.manifest_path)
        finally:
            temporary.unlink(missing_ok=True)


def _is_manifest_path(path: str) -> bool:
    if not path or not path.startswith("resources/") or "\\" in path:
        return False
    parts = path.split("/")
    return (
        all(part not in {"", ".", ".."} for part in parts)
        and Path(*parts).as_posix() == path
    )


def _join_relative(root: Path, path: str) -> Path:
    if not _is_manifest_path(path):
        raise RemoteResourceError(f"资源文件路径不安全: {path}")
    return root.joinpath(*path.split("/"))
