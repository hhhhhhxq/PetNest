"""Offline catalog and immutable asset cache for the PetNest pet store."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path, PurePosixPath
import shutil
import tempfile
from threading import Event
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from PIL import Image, UnidentifiedImageError

from .pet_store_catalog import (
    MAX_CATALOG_BYTES,
    PetStoreCatalog,
    PetStoreCatalogError,
    PetStoreFile,
)


MAX_MEDIA_PIXELS = 16_777_216
_CHUNK_SIZE = 64 * 1024
_RETRYABLE_HTTP_STATUSES = frozenset({429, 500, 502, 503, 504})


class PetStoreDownloadError(RuntimeError):
    """A catalog or asset could not be downloaded and verified."""


class PetStoreDownloadCancelled(PetStoreDownloadError):
    """The user cancelled an in-progress immutable download."""


class _PetStoreTransientError(PetStoreDownloadError):
    """A temporary network failure that can be retried safely."""


@dataclass(frozen=True, slots=True)
class CatalogLoadResult:
    catalog: PetStoreCatalog
    offline: bool


class PetStoreCache:
    CATALOG_ROUTE = "/v1/store/catalog.json"
    FILE_ROUTE = "/v1/store/files/"

    def __init__(
        self,
        root: Path,
        base_url: str,
        *,
        opener: Callable[..., object] = urlopen,
        timeout: float = 20.0,
        retry_attempts: int = 3,
        retry_delay: float = 0.5,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.base_url = str(base_url).rstrip("/")
        self._opener = opener
        self.timeout = float(timeout)
        if retry_attempts < 1:
            raise ValueError("retry_attempts 必须至少为 1")
        if retry_delay < 0:
            raise ValueError("retry_delay 不能为负数")
        self.retry_attempts = int(retry_attempts)
        self.retry_delay = float(retry_delay)
        self.catalog_path = self.root / "catalog.json"
        self.media_root = self.root / "media"
        self.packages_root = self.root / "packages"
        self.staging_root = self.root / "staging"
        self.root.mkdir(parents=True, exist_ok=True)
        self.media_root.mkdir(parents=True, exist_ok=True)
        self.packages_root.mkdir(parents=True, exist_ok=True)
        self._clean_staging()

    def load_catalog(self) -> PetStoreCatalog | None:
        if not self.catalog_path.is_file():
            return None
        try:
            return PetStoreCatalog.from_bytes(self.catalog_path.read_bytes())
        except (OSError, PetStoreCatalogError):
            return None

    def fetch_catalog_or_cached(self) -> CatalogLoadResult:
        try:
            payload = self._fetch_catalog_bytes()
            catalog = PetStoreCatalog.from_bytes(payload)
            self._atomic_write(self.catalog_path, payload)
            return CatalogLoadResult(catalog, False)
        except (OSError, HTTPError, URLError, PetStoreCatalogError, PetStoreDownloadError) as error:
            cached = self.load_catalog()
            if cached is not None:
                return CatalogLoadResult(cached, True)
            raise PetStoreDownloadError(f"无法加载宠物商店目录：{error}") from error

    def fetch_media(
        self,
        remote: PetStoreFile,
        *,
        cancel: Event | None = None,
    ) -> Path:
        name = PurePosixPath(remote.path).name
        target = self.media_root / remote.sha256 / name
        return self._fetch_file(remote, target, cancel=cancel, validate_image=True)

    def fetch_package(
        self,
        remote: PetStoreFile,
        *,
        progress: Callable[[int, int], object] | None = None,
        cancel: Event | None = None,
    ) -> Path:
        target = self.packages_root / f"{remote.sha256}.zip"
        return self._fetch_file(
            remote,
            target,
            progress=progress,
            cancel=cancel,
            validate_image=False,
        )

    def _fetch_catalog_bytes(self) -> bytes:
        last_error: _PetStoreTransientError | None = None
        for attempt in range(self.retry_attempts):
            try:
                return self._fetch_catalog_bytes_once()
            except HTTPError as error:
                if error.code not in _RETRYABLE_HTTP_STATUSES:
                    raise PetStoreDownloadError(
                        f"商店目录请求失败：HTTP {error.code}"
                    ) from error
                last_error = _PetStoreTransientError(
                    f"商店目录请求暂时失败：HTTP {error.code}"
                )
            except (OSError, URLError) as error:
                last_error = _PetStoreTransientError(
                    f"商店目录请求暂时失败：{error}"
                )
            if attempt + 1 < self.retry_attempts:
                time.sleep(self.retry_delay * (2**attempt))
        assert last_error is not None
        raise last_error

    def _fetch_catalog_bytes_once(self) -> bytes:
        request = Request(
            f"{self.base_url}{self.CATALOG_ROUTE}",
            headers={"Accept": "application/json", "User-Agent": "PetNest-Store"},
        )
        chunks: list[bytes] = []
        total = 0
        with self._opener(request, timeout=self.timeout) as response:  # type: ignore[attr-defined]
            while True:
                chunk = response.read(_CHUNK_SIZE)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_CATALOG_BYTES:
                    raise PetStoreDownloadError("商店目录超过大小限制")
                chunks.append(chunk)
        return b"".join(chunks)

    def _fetch_file(
        self,
        remote: PetStoreFile,
        target: Path,
        *,
        progress: Callable[[int, int], object] | None = None,
        cancel: Event | None = None,
        validate_image: bool,
    ) -> Path:
        if self._cached_file_valid(target, remote, validate_image=validate_image):
            return target
        if target.exists() or target.is_symlink():
            target.unlink()
        target.parent.mkdir(parents=True, exist_ok=True)
        last_error: _PetStoreTransientError | None = None
        for attempt in range(self.retry_attempts):
            try:
                return self._fetch_file_once(
                    remote,
                    target,
                    progress=progress,
                    cancel=cancel,
                    validate_image=validate_image,
                )
            except _PetStoreTransientError as error:
                last_error = error
            if attempt + 1 < self.retry_attempts:
                self._raise_if_cancelled(cancel)
                time.sleep(self.retry_delay * (2**attempt))
        assert last_error is not None
        raise last_error

    def _fetch_file_once(
        self,
        remote: PetStoreFile,
        target: Path,
        *,
        progress: Callable[[int, int], object] | None,
        cancel: Event | None,
        validate_image: bool,
    ) -> Path:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{remote.sha256[:12]}-", suffix=".part", dir=self.staging_root
        )
        os.close(descriptor)
        temporary = Path(temporary_name)
        digest = hashlib.sha256()
        downloaded = 0
        try:
            request = Request(
                self._file_url(remote),
                headers={"Accept": "application/octet-stream", "User-Agent": "PetNest-Store"},
            )
            with self._opener(request, timeout=self.timeout) as response:  # type: ignore[attr-defined]
                with temporary.open("wb") as output:
                    while True:
                        self._raise_if_cancelled(cancel)
                        chunk = response.read(_CHUNK_SIZE)
                        if not chunk:
                            break
                        downloaded += len(chunk)
                        if downloaded > remote.size:
                            raise PetStoreDownloadError("下载内容超过目录声明大小")
                        output.write(chunk)
                        digest.update(chunk)
                        if progress is not None:
                            progress(downloaded, remote.size)
            self._raise_if_cancelled(cancel)
            if downloaded != remote.size:
                raise PetStoreDownloadError("下载内容大小与目录不一致")
            if digest.hexdigest() != remote.sha256:
                raise PetStoreDownloadError("下载内容 SHA-256 校验失败")
            if validate_image:
                self._validate_image(temporary)
            os.replace(temporary, target)
            if progress is not None and downloaded == remote.size:
                progress(downloaded, remote.size)
            return target
        except PetStoreDownloadCancelled:
            raise
        except PetStoreDownloadError:
            raise
        except HTTPError as error:
            if error.code in _RETRYABLE_HTTP_STATUSES:
                raise _PetStoreTransientError(
                    f"下载商店文件暂时失败：HTTP {error.code}"
                ) from error
            raise PetStoreDownloadError(
                f"下载商店文件失败：HTTP {error.code}"
            ) from error
        except (OSError, URLError) as error:
            raise _PetStoreTransientError(
                f"下载商店文件暂时失败：{error}"
            ) from error
        finally:
            if temporary.exists():
                temporary.unlink()

    def _cached_file_valid(
        self, target: Path, remote: PetStoreFile, *, validate_image: bool
    ) -> bool:
        if not target.is_file() or target.is_symlink():
            return False
        try:
            if target.stat().st_size != remote.size:
                return False
            if _sha256(target) != remote.sha256:
                return False
            if validate_image:
                self._validate_image(target)
        except (OSError, PetStoreDownloadError):
            return False
        return True

    def _validate_image(self, path: Path) -> None:
        try:
            with Image.open(path) as image:
                width, height = image.size
                if width <= 0 or height <= 0 or width * height > MAX_MEDIA_PIXELS:
                    raise PetStoreDownloadError("商店图片像素尺寸超过限制")
                image.verify()
            with Image.open(path) as image:
                image.load()
        except PetStoreDownloadError:
            raise
        except (OSError, UnidentifiedImageError) as error:
            raise PetStoreDownloadError(f"商店图片无法完整解码：{error}") from error

    def _file_url(self, remote: PetStoreFile) -> str:
        encoded = "/".join(quote(part, safe="") for part in remote.path.split("/"))
        return f"{self.base_url}{self.FILE_ROUTE}{encoded}?sha256={remote.sha256}"

    def _atomic_write(self, target: Path, payload: bytes) -> None:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}-", suffix=".tmp", dir=target.parent
        )
        os.close(descriptor)
        temporary = Path(temporary_name)
        try:
            temporary.write_bytes(payload)
            os.replace(temporary, target)
        finally:
            if temporary.exists():
                temporary.unlink()

    def _clean_staging(self) -> None:
        if self.staging_root.exists():
            for child in self.staging_root.iterdir():
                if child.is_dir() and not child.is_symlink():
                    shutil.rmtree(child, ignore_errors=True)
                else:
                    try:
                        child.unlink()
                    except OSError:
                        pass
        self.staging_root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _raise_if_cancelled(cancel: Event | None) -> None:
        if cancel is not None and cancel.is_set():
            raise PetStoreDownloadCancelled("下载已取消")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "CatalogLoadResult",
    "MAX_MEDIA_PIXELS",
    "PetStoreCache",
    "PetStoreDownloadCancelled",
    "PetStoreDownloadError",
]
