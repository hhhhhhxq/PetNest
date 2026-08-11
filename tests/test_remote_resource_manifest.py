from __future__ import annotations

import hashlib
import json

import pytest

from petnest.core.remote_resource_manifest import ManifestError, ResourceManifest


def _file(path: str = "resources/cursors/demo/arrow.cur", content: bytes = b"cursor") -> dict[str, object]:
    return {
        "path": path,
        "size": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def _manifest(*resources: dict[str, object]) -> dict[str, object]:
    return {
        "schema_version": 1,
        "catalog_version": "2026.8.11",
        "resources": list(resources),
    }


def _resource(identifier: str = "demo", resource_type: str = "cursor_theme", **overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "id": identifier,
        "type": resource_type,
        "version": "1.0.0",
        "files": [_file()],
        "metadata": {"name": "Demo"},
    }
    value.update(overrides)
    return value


def test_parses_resources_and_exposes_safe_relative_paths() -> None:
    manifest = ResourceManifest.from_dict(_manifest(_resource()))

    resource = manifest.resource("demo")
    assert resource is not None
    assert resource.type == "cursor_theme"
    assert resource.files[0].path == "resources/cursors/demo/arrow.cur"
    assert resource.files[0].relative_path.parts == ("resources", "cursors", "demo", "arrow.cur")
    assert manifest.resources_of_type("cursor_theme") == (resource,)


def test_rejects_unknown_schema_version() -> None:
    raw = _manifest(_resource())
    raw["schema_version"] = 2

    with pytest.raises(ManifestError, match="schema"):
        ResourceManifest.from_dict(raw)


@pytest.mark.parametrize(
    "path",
    ["../secret", "/absolute/file", "C:/absolute/file", "resources\\bad\\file", "resources/./file"],
)
def test_rejects_unsafe_file_paths(path: str) -> None:
    raw = _manifest(_resource(files=[_file(path)]))

    with pytest.raises(ManifestError, match="path"):
        ResourceManifest.from_dict(raw)


def test_rejects_duplicate_resource_ids_and_invalid_hashes() -> None:
    duplicate = _manifest(_resource(), _resource())
    with pytest.raises(ManifestError, match="duplicate"):
        ResourceManifest.from_dict(duplicate)

    invalid_hash = _manifest(_resource(files=[{"path": _file()["path"], "size": 6, "sha256": "not-a-hash"}]))
    with pytest.raises(ManifestError, match="sha256"):
        ResourceManifest.from_dict(invalid_hash)


def test_rejects_file_path_prefix_conflicts() -> None:
    parent = _resource(files=[_file("resources/effects/demo")])
    child = _resource(
        "other",
        "interaction_effect",
        files=[_file("resources/effects/demo/frame.png")],
    )

    with pytest.raises(ManifestError, match="父路径"):
        ResourceManifest.from_dict(_manifest(parent, child))

    nested = _manifest(
        _resource(files=[_file("resources/a")]),
        _resource("other", "interaction_effect", files=[_file("resources/a/b")]),
        _resource("third", "interaction_effect", files=[_file("resources/a-b")]),
    )
    with pytest.raises(ManifestError, match="父路径"):
        ResourceManifest.from_dict(nested)


def test_json_round_trip_preserves_catalog() -> None:
    raw = _manifest(_resource("demo", "countdown_background"))

    manifest = ResourceManifest.from_bytes(json.dumps(raw).encode("utf-8"))

    assert manifest.catalog_version == "2026.8.11"
    assert manifest.resource("demo").type == "countdown_background"  # type: ignore[union-attr]
