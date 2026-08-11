from __future__ import annotations

import hashlib
from io import BytesIO
import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request
from zipfile import ZipFile

import pytest

from petnest.core.remote_resource_cache import RemoteResourceCache, RemoteResourceError


def _payload(path: str, content: bytes) -> dict[str, object]:
    return {
        "path": path,
        "size": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def _manifest(files: list[dict[str, object]], *, version: str = "2026.8.11") -> bytes:
    return _manifest_resources(
        [
            {
                "id": "demo",
                "type": "cursor_theme",
                "version": "1.0.0",
                "files": files,
                "metadata": {"name": "Demo"},
            }
        ],
        version=version,
    )


def _manifest_resources(resources: list[dict[str, object]], *, version: str = "2026.8.11") -> bytes:
    raw = {
        "schema_version": 1,
        "catalog_version": version,
        "resources": resources,
    }
    return json.dumps(raw).encode("utf-8")


class _Response:
    def __init__(self, content: bytes, *, status: int = 200) -> None:
        self.content = content
        self.status = status
        self._consumed = False

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, _size: int = -1) -> bytes:
        if self._consumed:
            return b""
        self._consumed = True
        return self.content


def test_sync_downloads_manifest_and_verifies_files(tmp_path: Path) -> None:
    content = b"remote cursor bytes"
    relative = "resources/cursors/demo/arrow.cur"
    manifest_bytes = _manifest([_payload(relative, content)])

    def opener(request: Request, timeout: float = 0) -> _Response:
        del timeout
        if request.full_url.endswith("/v1/manifest.json"):
            return _Response(manifest_bytes)
        if request.full_url.endswith("/v1/archive.zip"):
            return _Response(b"", status=404)
        assert request.full_url.endswith("/v1/files/resources/cursors/demo/arrow.cur")
        return _Response(content)

    cache = RemoteResourceCache(tmp_path, "https://resources.example", opener=opener)

    manifest = cache.sync()

    assert manifest.catalog_version == "2026.8.11"
    assert cache.current_root is not None
    assert (cache.current_root / relative).read_bytes() == content
    assert cache.path_for(relative) == cache.current_root / relative
    assert cache.load_current_manifest().catalog_version == "2026.8.11"  # type: ignore[union-attr]
    pointer = json.loads(cache.current_pointer_path.read_text(encoding="utf-8"))
    assert pointer["catalog_version"] == "2026.8.11"
    assert pointer["version_id"] == cache.current_root.name
    assert not (tmp_path / relative).exists()


def test_sync_keeps_previous_cache_when_a_new_file_fails(tmp_path: Path) -> None:
    old_content = b"old cursor"
    new_content = b"new cursor"
    relative = "resources/cursors/demo/arrow.cur"
    old_manifest = _manifest([_payload(relative, old_content)], version="2026.8.10")

    def old_opener(request: Request, timeout: float = 0) -> _Response:
        del timeout
        if request.full_url.endswith("manifest.json"):
            return _Response(old_manifest)
        if request.full_url.endswith("/v1/archive.zip"):
            return _Response(b"", status=404)
        return _Response(old_content)

    cache = RemoteResourceCache(tmp_path, "https://resources.example", opener=old_opener)
    cache.sync()
    old_root = cache.current_root
    assert old_root is not None
    old_pointer = (tmp_path / "current.json").read_bytes()
    new_manifest = _manifest([_payload(relative, new_content)], version="2026.8.11")

    def opener(request: Request, timeout: float = 0) -> _Response:
        del timeout
        if request.full_url.endswith("/v1/manifest.json"):
            return _Response(new_manifest)
        if request.full_url.endswith("/v1/archive.zip"):
            return _Response(b"", status=404)
        return _Response(b"wrong data")

    cache = RemoteResourceCache(tmp_path, "https://resources.example", opener=opener)

    with pytest.raises(RemoteResourceError, match="sha256"):
        cache.sync()

    assert cache.current_root == old_root
    assert (old_root / relative).read_bytes() == old_content
    assert (tmp_path / "current.json").read_bytes() == old_pointer


def test_sync_or_cached_returns_last_good_manifest_when_network_is_down(tmp_path: Path) -> None:
    content = b"cached cursor"
    relative = "resources/cursors/demo/arrow.cur"
    manifest_bytes = _manifest([_payload(relative, content)])

    def seed_opener(request: Request, timeout: float = 0) -> _Response:
        del timeout
        if request.full_url.endswith("manifest.json"):
            return _Response(manifest_bytes)
        if request.full_url.endswith("/v1/archive.zip"):
            return _Response(b"", status=404)
        return _Response(content)

    RemoteResourceCache(tmp_path, "https://resources.example", opener=seed_opener).sync()

    def opener(request: Request, timeout: float = 0) -> _Response:
        del request, timeout
        raise OSError("offline")

    cache = RemoteResourceCache(tmp_path, "https://resources.example", opener=opener)

    manifest = cache.sync_or_cached()

    assert manifest is not None
    assert manifest.resource("demo") is not None
    assert cache.current_root is not None


def test_corrupt_download_is_not_committed(tmp_path: Path) -> None:
    relative = "resources/cursors/demo/arrow.cur"
    manifest_bytes = _manifest([_payload(relative, b"expected")])

    def opener(request: Request, timeout: float = 0) -> _Response:
        del timeout
        if request.full_url.endswith("manifest.json"):
            return _Response(manifest_bytes)
        if request.full_url.endswith("/v1/archive.zip"):
            return _Response(b"", status=404)
        return _Response(b"wrong")

    cache = RemoteResourceCache(tmp_path, "https://resources.example", opener=opener)

    with pytest.raises(RemoteResourceError):
        cache.sync()
    assert not (tmp_path / "current.json").exists()
    assert not list((tmp_path / "versions").glob("*")) if (tmp_path / "versions").exists() else True


def test_sync_uses_verified_github_archive_when_worker_exposes_it(tmp_path: Path) -> None:
    content = b"archive cursor bytes"
    relative = "resources/cursors/demo/arrow.cur"
    manifest_bytes = _manifest([_payload(relative, content)])
    archive_buffer = BytesIO()
    with ZipFile(archive_buffer, "w") as archive:
        archive.writestr("hhhhhhxq-petnest-resources-abcdef/resources/cursors/demo/arrow.cur", content)
    archive_bytes = archive_buffer.getvalue()

    def opener(request: Request, timeout: float = 0) -> _Response:
        del timeout
        if request.full_url.endswith("/v1/manifest.json"):
            return _Response(manifest_bytes)
        assert request.full_url.endswith("/v1/archive.zip")
        return _Response(archive_bytes)

    cache = RemoteResourceCache(tmp_path, "https://resources.example", opener=opener)

    cache.sync()

    assert cache.current_root is not None
    assert (cache.current_root / relative).read_bytes() == content


def test_sync_falls_back_to_files_when_archive_route_returns_http_404(tmp_path: Path) -> None:
    content = b"legacy worker cursor bytes"
    relative = "resources/cursors/demo/arrow.cur"
    manifest_bytes = _manifest([_payload(relative, content)])

    def opener(request: Request, timeout: float = 0) -> _Response:
        del timeout
        if request.full_url.endswith("/v1/manifest.json"):
            return _Response(manifest_bytes)
        if request.full_url.endswith("/v1/archive.zip"):
            raise HTTPError(request.full_url, 404, "Not Found", {}, BytesIO())
        assert request.full_url.endswith("/v1/files/resources/cursors/demo/arrow.cur")
        return _Response(content)

    cache = RemoteResourceCache(tmp_path, "https://resources.example", opener=opener)

    cache.sync()

    assert cache.current_root is not None
    assert (cache.current_root / relative).read_bytes() == content


def test_sync_falls_back_to_files_when_archive_gateway_fails(tmp_path: Path) -> None:
    content = b"gateway fallback cursor bytes"
    relative = "resources/cursors/demo/arrow.cur"
    manifest_bytes = _manifest([_payload(relative, content)])

    def opener(request: Request, timeout: float = 0) -> _Response:
        del timeout
        if request.full_url.endswith("/v1/manifest.json"):
            return _Response(manifest_bytes)
        if request.full_url.endswith("/v1/archive.zip"):
            raise HTTPError(request.full_url, 502, "Bad Gateway", {}, BytesIO())
        assert request.full_url.endswith("/v1/files/resources/cursors/demo/arrow.cur")
        return _Response(content)

    cache = RemoteResourceCache(tmp_path, "https://resources.example", opener=opener, retry_delay=0)

    cache.sync()

    assert cache.current_root is not None
    assert (cache.current_root / relative).read_bytes() == content


def test_sync_reports_verified_byte_progress(tmp_path: Path) -> None:
    first = b"first cursor bytes"
    second = b"second cursor bytes, a little longer"
    first_path = "resources/cursors/demo/arrow.cur"
    second_path = "resources/cursors/demo/busy.cur"
    manifest_bytes = _manifest([_payload(first_path, first), _payload(second_path, second)])
    progress: list[int] = []

    def opener(request: Request, timeout: float = 0) -> _Response:
        del timeout
        if request.full_url.endswith("/v1/manifest.json"):
            return _Response(manifest_bytes)
        if request.full_url.endswith("/v1/archive.zip"):
            return _Response(b"", status=404)
        if request.full_url.endswith("/arrow.cur"):
            return _Response(first)
        assert request.full_url.endswith("/busy.cur")
        return _Response(second)

    cache = RemoteResourceCache(tmp_path, "https://resources.example", opener=opener)

    cache.sync(progress=progress.append)

    assert progress
    assert progress[-1] == 100
    assert progress == sorted(progress)


def test_sync_retries_transient_file_gateway_errors(tmp_path: Path) -> None:
    content = b"retryable cursor bytes"
    relative = "resources/cursors/demo/arrow.cur"
    manifest_bytes = _manifest([_payload(relative, content)])
    attempts = 0

    def opener(request: Request, timeout: float = 0) -> _Response:
        nonlocal attempts
        del timeout
        if request.full_url.endswith("/v1/manifest.json"):
            return _Response(manifest_bytes)
        if request.full_url.endswith("/v1/archive.zip"):
            return _Response(b"", status=404)
        attempts += 1
        if attempts == 1:
            raise HTTPError(request.full_url, 502, "Bad Gateway", {}, BytesIO())
        return _Response(content)

    cache = RemoteResourceCache(tmp_path, "https://resources.example", opener=opener, retry_delay=0)

    cache.sync()

    assert attempts == 2
    assert cache.current_root is not None


def test_sync_reuses_unchanged_files_from_current_generation(tmp_path: Path) -> None:
    unchanged = b"unchanged cursor bytes"
    old_changed = b"old busy cursor"
    new_changed = b"new busy cursor"
    unchanged_path = "resources/cursors/demo/arrow.cur"
    changed_path = "resources/cursors/demo/busy.cur"
    old_manifest = _manifest(
        [_payload(unchanged_path, unchanged), _payload(changed_path, old_changed)],
        version="2026.8.12",
    )

    def old_opener(request: Request, timeout: float = 0) -> _Response:
        del timeout
        if request.full_url.endswith("/v1/manifest.json"):
            return _Response(old_manifest)
        if request.full_url.endswith("/v1/archive.zip"):
            return _Response(b"", status=404)
        return _Response(unchanged if request.full_url.endswith("/arrow.cur") else old_changed)

    cache = RemoteResourceCache(tmp_path, "https://resources.example", opener=old_opener, retry_delay=0)
    cache.sync()
    old_root = cache.current_root
    assert old_root is not None

    new_manifest = _manifest(
        [_payload(unchanged_path, unchanged), _payload(changed_path, new_changed)],
        version="2026.8.12",
    )
    requested: list[str] = []

    def new_opener(request: Request, timeout: float = 0) -> _Response:
        del timeout
        if request.full_url.endswith("/v1/manifest.json"):
            return _Response(new_manifest)
        assert "/v1/files/" in request.full_url
        requested.append(request.full_url)
        return _Response(new_changed)

    updated_cache = RemoteResourceCache(tmp_path, "https://resources.example", opener=new_opener, retry_delay=0)
    updated = updated_cache.sync()

    assert updated.catalog_version == "2026.8.12"
    assert requested == ["https://resources.example/v1/files/resources/cursors/demo/busy.cur"]
    assert updated_cache.current_root is not None
    assert updated_cache.current_root != old_root
    assert (updated_cache.current_root / unchanged_path).read_bytes() == unchanged
    assert (updated_cache.current_root / changed_path).read_bytes() == new_changed


def test_sync_partial_activates_successful_resource_and_keeps_failed_resource(
    tmp_path: Path,
) -> None:
    old_cursor = b"old cursor"
    old_effect = b"old effect"
    cursor_path = "resources/cursors/demo/arrow.cur"
    effect_path = "resources/effects/spark/frames/0001.png"
    old_manifest = _manifest_resources(
        [
            {
                "id": "demo",
                "type": "cursor_theme",
                "version": "1.0.0",
                "files": [_payload(cursor_path, old_cursor)],
                "metadata": {"name": "Demo"},
            },
            {
                "id": "spark",
                "type": "interaction_effect",
                "version": "1.0.0",
                "files": [_payload(effect_path, old_effect)],
                "metadata": {"name": "Spark"},
            },
        ],
        version="2026.8.10",
    )

    def old_opener(request: Request, timeout: float = 0) -> _Response:
        del timeout
        if request.full_url.endswith("manifest.json"):
            return _Response(old_manifest)
        if request.full_url.endswith("archive.zip"):
            return _Response(b"", status=404)
        return _Response(old_cursor if request.full_url.endswith("arrow.cur") else old_effect)

    cache = RemoteResourceCache(tmp_path, "https://resources.example", opener=old_opener, retry_delay=0)
    cache.sync()
    old_root = cache.current_root
    assert old_root is not None

    new_cursor = b"new cursor"
    new_effect = b"new effect"
    new_manifest = _manifest_resources(
        [
            {
                "id": "demo",
                "type": "cursor_theme",
                "version": "1.1.0",
                "files": [_payload(cursor_path, new_cursor)],
                "metadata": {"name": "Demo"},
            },
            {
                "id": "spark",
                "type": "interaction_effect",
                "version": "1.1.0",
                "files": [_payload(effect_path, new_effect)],
                "metadata": {"name": "Spark"},
            },
        ],
        version="2026.8.11",
    )

    def new_opener(request: Request, timeout: float = 0) -> _Response:
        del timeout
        if request.full_url.endswith("manifest.json"):
            return _Response(new_manifest)
        assert "/v1/files/" in request.full_url
        if request.full_url.endswith("arrow.cur"):
            return _Response(new_cursor)
        raise HTTPError(request.full_url, 502, "Bad Gateway", {}, BytesIO())

    result = RemoteResourceCache(tmp_path, "https://resources.example", opener=new_opener, retry_delay=0).sync_partial()

    assert result.applied_resource_ids == ("demo",)
    assert [failure.identifier for failure in result.failures] == ["spark"]
    updated_root = cache.current_root
    assert updated_root is not None and updated_root != old_root
    assert (updated_root / cursor_path).read_bytes() == new_cursor
    assert (updated_root / effect_path).read_bytes() == old_effect
    active = cache.load_current_manifest()
    assert active is not None
    assert active.resource("demo").version == "1.1.0"  # type: ignore[union-attr]
    assert active.resource("spark").version == "1.0.0"  # type: ignore[union-attr]

    reloaded = RemoteResourceCache(tmp_path, "https://resources.example", opener=new_opener, retry_delay=0)
    assert reloaded.current_root == updated_root
    assert (reloaded.current_root / effect_path).read_bytes() == old_effect  # type: ignore[union-attr]


def test_sync_partial_removes_resource_missing_from_remote_catalog(tmp_path: Path) -> None:
    cursor = b"cursor"
    effect = b"effect"
    fallback_effect = b"bundled effect fallback"
    cursor_path = "resources/cursors/demo/arrow.cur"
    effect_path = "resources/effects/spark/frames/0001.png"
    old_manifest = _manifest_resources(
        [
            {
                "id": "demo",
                "type": "cursor_theme",
                "version": "1.0.0",
                "files": [_payload(cursor_path, cursor)],
                "metadata": {},
            },
            {
                "id": "spark",
                "type": "interaction_effect",
                "version": "1.0.0",
                "files": [_payload(effect_path, effect)],
                "metadata": {},
            },
        ],
        version="2026.8.10",
    )
    seed_root = tmp_path / "bundle"
    seed_file = seed_root / "effects" / "spark" / "frames" / "0001.png"
    seed_file.parent.mkdir(parents=True)
    seed_file.write_bytes(fallback_effect)

    def old_opener(request: Request, timeout: float = 0) -> _Response:
        del timeout
        if request.full_url.endswith("manifest.json"):
            return _Response(old_manifest)
        if request.full_url.endswith("archive.zip"):
            return _Response(b"", status=404)
        return _Response(cursor if request.full_url.endswith("arrow.cur") else effect)

    cache = RemoteResourceCache(tmp_path, "https://resources.example", opener=old_opener, seed_root=seed_root)
    cache.sync()

    new_manifest = _manifest_resources(
        [
            {
                "id": "demo",
                "type": "cursor_theme",
                "version": "1.0.0",
                "files": [_payload(cursor_path, cursor)],
                "metadata": {},
            }
        ],
        version="2026.8.11",
    )

    def new_opener(request: Request, timeout: float = 0) -> _Response:
        del timeout
        assert request.full_url.endswith("manifest.json")
        return _Response(new_manifest)

    result = RemoteResourceCache(tmp_path, "https://resources.example", opener=new_opener, seed_root=seed_root).sync_partial()

    assert result.removed_resource_ids == ("spark",)
    assert result.failures == ()
    assert cache.current_root is not None
    assert (cache.current_root / cursor_path).read_bytes() == cursor
    assert (cache.current_root / effect_path).read_bytes() == fallback_effect
    active = cache.load_current_manifest()
    assert active is not None
    assert [resource.identifier for resource in active.resources] == ["demo"]


def test_sync_partial_keeps_bundled_fallbacks_for_failed_new_resources(tmp_path: Path) -> None:
    cursor = b"new cursor"
    effect_default = b"bundled effect"
    effect_remote = b"remote effect"
    cursor_path = "resources/cursors/demo/arrow.cur"
    effect_path = "resources/effects/spark/frames/0001.png"
    manifest_bytes = _manifest_resources(
        [
            {
                "id": "demo",
                "type": "cursor_theme",
                "version": "1.0.0",
                "files": [_payload(cursor_path, cursor)],
                "metadata": {},
            },
            {
                "id": "spark",
                "type": "interaction_effect",
                "version": "1.0.0",
                "files": [_payload(effect_path, effect_remote)],
                "metadata": {},
            },
        ]
    )
    seed_root = tmp_path / "bundle"
    seed_file = seed_root / "effects" / "spark" / "frames" / "0001.png"
    seed_file.parent.mkdir(parents=True)
    seed_file.write_bytes(effect_default)

    def opener(request: Request, timeout: float = 0) -> _Response:
        del timeout
        if request.full_url.endswith("manifest.json"):
            return _Response(manifest_bytes)
        if request.full_url.endswith("archive.zip"):
            return _Response(b"", status=404)
        if request.full_url.endswith("arrow.cur"):
            return _Response(cursor)
        raise HTTPError(request.full_url, 502, "Bad Gateway", {}, BytesIO())

    cache = RemoteResourceCache(tmp_path / "cache", "https://resources.example", opener=opener, seed_root=seed_root, retry_delay=0)
    result = cache.sync_partial()

    assert result.applied_resource_ids == ("demo",)
    assert [failure.identifier for failure in result.failures] == ["spark"]
    assert cache.current_root is not None
    assert (cache.current_root / cursor_path).read_bytes() == cursor
    assert (cache.current_root / effect_path).read_bytes() == effect_default


def test_sync_seeds_matching_bundled_resources_without_network_download(tmp_path: Path) -> None:
    content = b"bundled countdown skin"
    relative = "resources/countdown/cream.png"
    manifest_bytes = _manifest([_payload(relative, content)])
    seed_root = tmp_path / "bundle"
    bundled = seed_root / "assets" / "countdown" / "cream.png"
    bundled.parent.mkdir(parents=True)
    bundled.write_bytes(content)

    def opener(request: Request, timeout: float = 0) -> _Response:
        del timeout
        if request.full_url.endswith("/v1/manifest.json"):
            return _Response(manifest_bytes)
        raise AssertionError(f"bundled file should be reused: {request.full_url}")

    cache = RemoteResourceCache(tmp_path / "cache", "https://resources.example", opener=opener, seed_root=seed_root)

    cache.sync()

    assert cache.current_root is not None
    assert (cache.current_root / relative).read_bytes() == content


def test_sync_migrates_verified_legacy_cache_without_redownloading(tmp_path: Path) -> None:
    content = b"legacy cursor bytes"
    relative = "resources/cursors/demo/arrow.cur"
    manifest_bytes = _manifest([_payload(relative, content)])
    legacy_file = tmp_path / relative
    legacy_file.parent.mkdir(parents=True)
    legacy_file.write_bytes(content)
    (tmp_path / "manifest.json").write_bytes(manifest_bytes)

    def opener(request: Request, timeout: float = 0) -> _Response:
        del timeout
        if request.full_url.endswith("manifest.json"):
            return _Response(manifest_bytes)
        raise AssertionError(f"legacy file should be reused: {request.full_url}")

    cache = RemoteResourceCache(tmp_path, "https://resources.example", opener=opener)
    assert cache.current_root == tmp_path

    cache.sync_partial()

    assert cache.current_root is not None
    assert cache.current_root != tmp_path
    assert (cache.current_root / relative).read_bytes() == content
    assert (tmp_path / "current.json").is_file()


def test_sync_applies_empty_catalog_to_clear_update_state(tmp_path: Path) -> None:
    manifest_bytes = _manifest_resources([], version="2026.8.12")

    def opener(request: Request, timeout: float = 0) -> _Response:
        del timeout
        assert request.full_url.endswith("manifest.json")
        return _Response(manifest_bytes)

    cache = RemoteResourceCache(tmp_path, "https://resources.example", opener=opener)
    result = cache.sync_partial()

    assert result.complete
    assert cache.current_root is not None
    assert cache.load_current_manifest() is not None
    assert cache.load_current_manifest().resources == ()  # type: ignore[union-attr]


def test_sync_prunes_old_versions_after_a_complete_update(tmp_path: Path) -> None:
    relative = "resources/cursors/demo/arrow.cur"
    content = b"stable cursor"
    roots: list[Path] = []

    for index in range(4):
        manifest_bytes = _manifest([_payload(relative, content)], version=f"2026.8.{10 + index}")

        def opener(request: Request, timeout: float = 0, *, payload=manifest_bytes) -> _Response:
            del timeout
            if request.full_url.endswith("/v1/manifest.json"):
                return _Response(payload)
            if request.full_url.endswith("/v1/archive.zip"):
                return _Response(b"", status=404)
            return _Response(content)

        cache = RemoteResourceCache(tmp_path, "https://resources.example", opener=opener, retry_delay=0)
        cache.sync()
        current = cache.current_root
        assert current is not None
        roots.append(current)

    version_roots = {path for path in (tmp_path / "versions").iterdir() if path.is_dir()}

    assert version_roots == set(roots[-2:])
    assert cache.current_root == roots[-1]


def test_path_for_rejects_traversal(tmp_path: Path) -> None:
    cache = RemoteResourceCache(tmp_path, "https://resources.example")

    with pytest.raises(ValueError, match="不安全"):
        cache.path_for("resources/../secrets.txt")
