from __future__ import annotations

import hashlib
import json
from pathlib import Path
from urllib.request import Request

import pytest

from petnest.core.remote_resource_cache import RemoteResourceCache, RemoteResourceError


def _payload(path: str, content: bytes) -> dict[str, object]:
    return {
        "path": path,
        "size": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def _manifest(files: list[dict[str, object]], *, version: str = "2026.8.11") -> bytes:
    raw = {
        "schema_version": 1,
        "catalog_version": version,
        "resources": [
            {
                "id": "demo",
                "type": "cursor_theme",
                "version": "1.0.0",
                "files": files,
                "metadata": {"name": "Demo"},
            }
        ],
    }
    return json.dumps(raw).encode("utf-8")


class _Response:
    def __init__(self, content: bytes) -> None:
        self.content = content
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
        return _Response(old_manifest if request.full_url.endswith("manifest.json") else old_content)

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
        return _Response(manifest_bytes if request.full_url.endswith("manifest.json") else content)

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
        return _Response(manifest_bytes if request.full_url.endswith("manifest.json") else b"wrong")

    cache = RemoteResourceCache(tmp_path, "https://resources.example", opener=opener)

    with pytest.raises(RemoteResourceError):
        cache.sync()
    assert not (tmp_path / "current.json").exists()
    assert not list((tmp_path / "versions").glob("*")) if (tmp_path / "versions").exists() else True


def test_path_for_rejects_traversal(tmp_path: Path) -> None:
    cache = RemoteResourceCache(tmp_path, "https://resources.example")

    with pytest.raises(ValueError, match="不安全"):
        cache.path_for("resources/../secrets.txt")
