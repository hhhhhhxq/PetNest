from __future__ import annotations

from io import BytesIO
import hashlib
import json
from pathlib import Path
from threading import Event
from urllib.error import HTTPError, URLError

from PIL import Image
import pytest

from petnest.core.pet_store_cache import (
    PetStoreCache,
    PetStoreDownloadCancelled,
    PetStoreDownloadError,
)
from petnest.core.pet_store_catalog import PetStoreCatalog, PetStoreFile


class _Response:
    def __init__(self, payload: bytes, *, chunk_size: int | None = None) -> None:
        self._stream = BytesIO(payload)
        self._chunk_size = chunk_size

    def read(self, size: int = -1) -> bytes:
        if self._chunk_size is not None and size > self._chunk_size:
            size = self._chunk_size
        return self._stream.read(size)

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_args: object) -> None:
        return None


class _ReadTimeoutResponse(_Response):
    def __init__(self) -> None:
        super().__init__(b"")

    def read(self, size: int = -1) -> bytes:
        del size
        raise TimeoutError("read operation timed out")


def _file(path: str, payload: bytes) -> dict[str, object]:
    return {"path": path, "size": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}


def _catalog_bytes(*, package: bytes = b"package") -> bytes:
    cover = _png_bytes()
    preview = _png_bytes(width=8, height=4)
    raw = {
        "schema_version": 1,
        "generated_at": "2026-08-18T07:15:00Z",
        "featured_pet_id": "sample_pet",
        "pets": [
            {
                "id": "sample_pet",
                "name": "Sample Pet",
                "author": "PetNest",
                "summary": "A small companion",
                "tags": ["official"],
                "updated_at": "2026-08-18T07:13:49Z",
                "action_count": 1,
                "capabilities": [],
                "cover": _file("store/pets/sample_pet/cover.png", cover),
                "idle_preview": {
                    **_file("store/pets/sample_pet/idle-preview.png", preview),
                    "frame_width": 4,
                    "frame_height": 4,
                    "frame_count": 2,
                    "frame_durations_ms": [100, 100],
                },
                "package": _file("store/pets/sample_pet/package.zip", package),
            }
        ],
    }
    return json.dumps(raw).encode("utf-8")


def _png_bytes(*, width: int = 4, height: int = 4) -> bytes:
    stream = BytesIO()
    Image.new("RGBA", (width, height), (10, 20, 30, 255)).save(stream, format="PNG")
    return stream.getvalue()


def test_fetch_catalog_replaces_only_with_valid_payload(tmp_path: Path) -> None:
    payload = _catalog_bytes()
    urls: list[str] = []

    def opener(request: object, timeout: float = 0) -> _Response:
        urls.append(request.full_url)  # type: ignore[attr-defined]
        assert timeout == 20.0
        return _Response(payload)

    cache = PetStoreCache(tmp_path, "https://assets.example/", opener=opener)

    result = cache.fetch_catalog_or_cached()

    assert result.offline is False
    assert result.catalog.pet("sample_pet") is not None
    assert (tmp_path / "catalog-v2.json").read_bytes() == payload
    assert urls == ["https://assets.example/v2/store/catalog.json"]


def test_fetch_catalog_prefers_v2_and_writes_a_versioned_cache(tmp_path: Path) -> None:
    payload = _catalog_bytes()
    urls: list[str] = []

    def opener(request: object, timeout: float = 0) -> _Response:
        del timeout
        urls.append(request.full_url)  # type: ignore[attr-defined]
        return _Response(payload)

    result = PetStoreCache(
        tmp_path,
        "https://assets.example",
        opener=opener,
    ).fetch_catalog_or_cached()

    assert result.offline is False
    assert urls == ["https://assets.example/v2/store/catalog.json"]
    assert (tmp_path / "catalog-v2.json").read_bytes() == payload
    assert not (tmp_path / "catalog-v1.json").exists()


def test_valid_v2_catalog_is_used_even_when_cache_write_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _catalog_bytes()
    urls: list[str] = []
    cache = PetStoreCache(
        tmp_path,
        "https://assets.example",
        opener=lambda request, timeout=0: (
            urls.append(request.full_url),  # type: ignore[attr-defined]
            _Response(payload),
        )[1],
    )

    def fail_write(_path: Path, _payload: bytes) -> None:
        raise OSError("read-only cache")

    monkeypatch.setattr(cache, "_atomic_write", fail_write)

    result = cache.fetch_catalog_or_cached()

    assert result.offline is False
    assert result.catalog.pet("sample_pet") is not None
    assert urls == ["https://assets.example/v2/store/catalog.json"]


def test_fetch_catalog_falls_back_to_v1_when_v2_is_missing(tmp_path: Path) -> None:
    payload = _catalog_bytes()
    urls: list[str] = []

    def opener(request: object, timeout: float = 0) -> _Response:
        del timeout
        url = request.full_url  # type: ignore[attr-defined]
        urls.append(url)
        if "/v2/" in url:
            raise HTTPError(url, 404, "missing", None, None)
        return _Response(payload)

    result = PetStoreCache(
        tmp_path,
        "https://assets.example",
        opener=opener,
        retry_delay=0,
    ).fetch_catalog_or_cached()

    assert result.offline is False
    assert urls == [
        "https://assets.example/v2/store/catalog.json",
        "https://assets.example/v1/store/catalog.json",
    ]
    assert (tmp_path / "catalog-v1.json").read_bytes() == payload


def test_fetch_catalog_falls_back_to_v1_when_v2_payload_is_invalid(tmp_path: Path) -> None:
    payload = _catalog_bytes()
    urls: list[str] = []

    def opener(request: object, timeout: float = 0) -> _Response:
        del timeout
        url = request.full_url  # type: ignore[attr-defined]
        urls.append(url)
        return _Response(b"not-json" if "/v2/" in url else payload)

    result = PetStoreCache(
        tmp_path,
        "https://assets.example",
        opener=opener,
    ).fetch_catalog_or_cached()

    assert result.offline is False
    assert result.catalog.pet("sample_pet") is not None
    assert urls == [
        "https://assets.example/v2/store/catalog.json",
        "https://assets.example/v1/store/catalog.json",
    ]


def test_load_catalog_keeps_v1_and_v2_caches_separate(tmp_path: Path) -> None:
    v1 = _catalog_bytes(package=b"v1")
    v2 = _catalog_bytes(package=b"v2")
    (tmp_path / "catalog-v1.json").write_bytes(v1)
    (tmp_path / "catalog-v2.json").write_bytes(v2)
    cache = PetStoreCache(tmp_path, "https://assets.example")

    assert cache.load_catalog("v1") == PetStoreCatalog.from_bytes(v1)
    assert cache.load_catalog("v2") == PetStoreCatalog.from_bytes(v2)


def test_v2_failure_uses_v2_cache_without_requesting_v1(tmp_path: Path) -> None:
    payload = _catalog_bytes(package=b"cached-v2")
    (tmp_path / "catalog-v2.json").write_bytes(payload)
    urls: list[str] = []

    def opener(request: object, timeout: float = 0) -> _Response:
        del timeout
        urls.append(request.full_url)  # type: ignore[attr-defined]
        raise URLError("offline")

    result = PetStoreCache(
        tmp_path,
        "https://assets.example",
        opener=opener,
        retry_attempts=1,
    ).fetch_catalog_or_cached()

    assert result.offline is True
    assert result.catalog == PetStoreCatalog.from_bytes(payload)
    assert urls == ["https://assets.example/v2/store/catalog.json"]


def test_v1_cache_wins_over_unversioned_cache_when_both_network_routes_fail(tmp_path: Path) -> None:
    v1 = _catalog_bytes(package=b"cached-v1")
    old = _catalog_bytes(package=b"old-unversioned")
    (tmp_path / "catalog-v1.json").write_bytes(v1)
    (tmp_path / "catalog.json").write_bytes(old)

    result = PetStoreCache(
        tmp_path,
        "https://assets.example",
        opener=lambda _request, timeout=0: (_ for _ in ()).throw(URLError("offline")),
        retry_attempts=1,
    ).fetch_catalog_or_cached()

    assert result.offline is True
    assert result.catalog == PetStoreCatalog.from_bytes(v1)


def test_invalid_v2_cache_is_skipped_in_favor_of_valid_v1_cache(tmp_path: Path) -> None:
    v1 = _catalog_bytes(package=b"cached-v1")
    (tmp_path / "catalog-v2.json").write_bytes(b"not-json")
    (tmp_path / "catalog-v1.json").write_bytes(v1)

    result = PetStoreCache(
        tmp_path,
        "https://assets.example",
        opener=lambda _request, timeout=0: (_ for _ in ()).throw(URLError("offline")),
        retry_attempts=1,
    ).fetch_catalog_or_cached()

    assert result.offline is True
    assert result.catalog == PetStoreCatalog.from_bytes(v1)


def test_fetch_catalog_falls_back_to_last_valid_cache(tmp_path: Path) -> None:
    (tmp_path / "catalog.json").write_bytes(_catalog_bytes())

    def opener(_request: object, timeout: float = 0) -> _Response:
        raise URLError("offline")

    result = PetStoreCache(tmp_path, "https://assets.example", opener=opener).fetch_catalog_or_cached()

    assert result.offline is True
    assert result.catalog.featured_pet_id == "sample_pet"


def test_fetch_catalog_retries_one_transient_timeout(tmp_path: Path) -> None:
    attempts = 0

    def opener(_request: object, timeout: float = 0) -> _Response:
        nonlocal attempts
        del timeout
        attempts += 1
        if attempts == 1:
            raise TimeoutError("connect timed out")
        return _Response(_catalog_bytes())

    cache = PetStoreCache(
        tmp_path,
        "https://assets.example",
        opener=opener,
        retry_delay=0,
    )

    result = cache.fetch_catalog_or_cached()

    assert result.offline is False
    assert attempts == 2


def test_fetch_catalog_without_valid_cache_reports_network_error(tmp_path: Path) -> None:
    def opener(_request: object, timeout: float = 0) -> _Response:
        raise URLError("offline")

    with pytest.raises(PetStoreDownloadError, match="offline|目录"):
        PetStoreCache(tmp_path, "https://assets.example", opener=opener).fetch_catalog_or_cached()


def test_fetch_package_caches_verified_bytes_and_reports_progress(tmp_path: Path) -> None:
    payload = b"abcdefgh"
    remote = PetStoreFile(
        "store/pets/sample_pet/package.zip", len(payload), hashlib.sha256(payload).hexdigest()
    )
    calls: list[str] = []
    progress: list[tuple[int, int]] = []

    def opener(request: object, timeout: float = 0) -> _Response:
        calls.append(request.full_url)  # type: ignore[attr-defined]
        return _Response(payload, chunk_size=3)

    cache = PetStoreCache(tmp_path, "https://assets.example", opener=opener)

    first = cache.fetch_package(remote, progress=lambda current, total: progress.append((current, total)))
    second = cache.fetch_package(remote)

    assert first == second == tmp_path / "packages" / f"{remote.sha256}.zip"
    assert first.read_bytes() == payload
    assert calls == [
        f"https://assets.example/v1/store/files/store/pets/sample_pet/package.zip?sha256={remote.sha256}"
    ]
    assert progress[-1] == (len(payload), len(payload))


def test_fetch_package_retries_transient_read_timeout(tmp_path: Path) -> None:
    payload = b"abcdefgh"
    remote = PetStoreFile(
        "store/pets/sample_pet/package.zip",
        len(payload),
        hashlib.sha256(payload).hexdigest(),
    )
    attempts = 0

    def opener(_request: object, timeout: float = 0) -> _Response:
        nonlocal attempts
        del timeout
        attempts += 1
        return _ReadTimeoutResponse() if attempts == 1 else _Response(payload)

    cache = PetStoreCache(
        tmp_path,
        "https://assets.example",
        opener=opener,
        retry_delay=0,
    )

    path = cache.fetch_package(remote)

    assert path.read_bytes() == payload
    assert attempts == 2


def test_download_rejects_digest_mismatch_and_removes_staging(tmp_path: Path) -> None:
    expected = b"good"
    remote = PetStoreFile(
        "store/pets/sample_pet/package.zip", len(expected), hashlib.sha256(expected).hexdigest()
    )
    attempts = 0

    def opener(*_args: object, **_kwargs: object) -> _Response:
        nonlocal attempts
        attempts += 1
        return _Response(b"bad!")

    cache = PetStoreCache(
        tmp_path,
        "https://assets.example",
        opener=opener,
        retry_delay=0,
    )

    with pytest.raises(PetStoreDownloadError, match="SHA-256"):
        cache.fetch_package(remote)

    assert not list((tmp_path / "staging").glob("*"))
    assert attempts == 1


def test_download_can_be_cancelled_before_installable_file_is_cached(tmp_path: Path) -> None:
    payload = b"abcdefgh"
    remote = PetStoreFile(
        "store/pets/sample_pet/package.zip", len(payload), hashlib.sha256(payload).hexdigest()
    )
    cancel = Event()

    def progress(current: int, _total: int) -> None:
        if current >= 3:
            cancel.set()

    cache = PetStoreCache(
        tmp_path,
        "https://assets.example",
        opener=lambda *_a, **_k: _Response(payload, chunk_size=3),
    )

    with pytest.raises(PetStoreDownloadCancelled):
        cache.fetch_package(remote, progress=progress, cancel=cancel)

    assert not (tmp_path / "packages" / f"{remote.sha256}.zip").exists()


@pytest.mark.parametrize("case", ["invalid", "oversized"])
def test_fetch_media_rejects_invalid_or_oversized_images(tmp_path: Path, case: str) -> None:
    payload = b"not an image" if case == "invalid" else _png_bytes(width=4097, height=4097)
    remote = PetStoreFile(
        "store/pets/sample_pet/cover.png", len(payload), hashlib.sha256(payload).hexdigest()
    )
    cache = PetStoreCache(
        tmp_path, "https://assets.example", opener=lambda *_a, **_k: _Response(payload)
    )

    with pytest.raises(PetStoreDownloadError, match="图片|像素"):
        cache.fetch_media(remote)


def test_constructor_cleans_only_staging_artifacts(tmp_path: Path) -> None:
    stale = tmp_path / "staging" / "old-run"
    stale.mkdir(parents=True)
    (stale / "part").write_bytes(b"partial")
    cached = tmp_path / "packages" / "keep.zip"
    cached.parent.mkdir(parents=True)
    cached.write_bytes(b"keep")

    PetStoreCache(tmp_path, "https://assets.example", opener=lambda *_a, **_k: _Response(b""))

    assert not stale.exists()
    assert cached.read_bytes() == b"keep"
