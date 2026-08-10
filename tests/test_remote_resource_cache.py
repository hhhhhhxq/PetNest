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
    assert (tmp_path / relative).read_bytes() == content
    assert (tmp_path / "manifest.json").is_file()


def test_sync_keeps_previous_cache_when_a_new_file_fails(tmp_path: Path) -> None:
    old_content = b"old cursor"
    new_content = b"new cursor"
    relative = "resources/cursors/demo/arrow.cur"
    old_manifest = _manifest([_payload(relative, old_content)], version="2026.8.10")
    (tmp_path / relative).parent.mkdir(parents=True)
    (tmp_path / relative).write_bytes(old_content)
    (tmp_path / "manifest.json").write_bytes(old_manifest)
    new_manifest = _manifest([_payload(relative, new_content)], version="2026.8.11")

    def opener(request: Request, timeout: float = 0) -> _Response:
        del timeout
        if request.full_url.endswith("/v1/manifest.json"):
            return _Response(new_manifest)
        return _Response(b"wrong data")

    cache = RemoteResourceCache(tmp_path, "https://resources.example", opener=opener)

    with pytest.raises(RemoteResourceError, match="sha256"):
        cache.sync()

    assert (tmp_path / relative).read_bytes() == old_content
    assert json.loads((tmp_path / "manifest.json").read_text())['catalog_version'] == "2026.8.10"


def test_sync_or_cached_returns_last_good_manifest_when_network_is_down(tmp_path: Path) -> None:
    content = b"cached cursor"
    relative = "resources/cursors/demo/arrow.cur"
    (tmp_path / relative).parent.mkdir(parents=True)
    (tmp_path / relative).write_bytes(content)
    (tmp_path / "manifest.json").write_bytes(_manifest([_payload(relative, content)]))

    def opener(request: Request, timeout: float = 0) -> _Response:
        del request, timeout
        raise OSError("offline")

    cache = RemoteResourceCache(tmp_path, "https://resources.example", opener=opener)

    manifest = cache.sync_or_cached()

    assert manifest is not None
    assert manifest.resource("demo") is not None


def test_corrupt_download_is_not_committed(tmp_path: Path) -> None:
    relative = "resources/cursors/demo/arrow.cur"
    manifest_bytes = _manifest([_payload(relative, b"expected")])

    def opener(request: Request, timeout: float = 0) -> _Response:
        del timeout
        return _Response(manifest_bytes if request.full_url.endswith("manifest.json") else b"wrong")

    cache = RemoteResourceCache(tmp_path, "https://resources.example", opener=opener)

    with pytest.raises(RemoteResourceError):
        cache.sync()
    assert not (tmp_path / "manifest.json").exists()


def test_path_for_rejects_traversal(tmp_path: Path) -> None:
    cache = RemoteResourceCache(tmp_path, "https://resources.example")

    with pytest.raises(ValueError, match="不安全"):
        cache.path_for("resources/../secrets.txt")
