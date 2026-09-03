from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
import hashlib
import json

import pytest

from petnest.core.pet_store_catalog import (
    MAX_CATALOG_BYTES,
    MAX_MEDIA_SIZE,
    MAX_PACKAGE_SIZE,
    PetStoreCatalog,
    PetStoreCatalogError,
    PetStoreItem,
)


def _file(path: str, content: bytes = b"asset") -> dict[str, object]:
    return {"path": path, "size": len(content), "sha256": hashlib.sha256(content).hexdigest()}


def _pet(identifier: str = "sample_pet", **overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "id": identifier,
        "name": "Sample Pet",
        "author": "PetNest",
        "summary": "A small companion",
        "tags": ["official", "light"],
        "updated_at": "2026-08-18T07:13:49Z",
        "action_count": 9,
        "capabilities": ["click", "hover"],
        "cover": _file(f"store/pets/{identifier}/cover.png"),
        "idle_preview": {
            **_file(f"store/pets/{identifier}/idle-preview.png"),
            "frame_width": 32,
            "frame_height": 32,
            "frame_count": 4,
            "frame_durations_ms": [80, 120, 100, 140],
        },
        "package": _file(f"store/pets/{identifier}/package.zip", b"package"),
    }
    value.update(overrides)
    return value


def _package_variant(
    identifier: str = "sample_pet",
    *,
    format: str = "webp-q95",
    content: bytes = b"webp-package",
) -> dict[str, object]:
    return {
        "format": format,
        "package": _file(
            f"store/pets/{identifier}/package-{format}.zip",
            content,
        ),
    }


def _catalog(*pets: dict[str, object]) -> dict[str, object]:
    return {
        "schema_version": 1,
        "generated_at": "2026-08-18T07:15:00Z",
        "featured_pet_id": pets[0]["id"] if pets else None,
        "pets": list(pets),
    }


def test_catalog_parses_featured_pet_and_preview_timeline() -> None:
    catalog = PetStoreCatalog.from_dict(_catalog(_pet()))

    pet = catalog.pet("sample_pet")
    assert pet is not None
    assert catalog.featured_pet is pet
    assert catalog.generated_at == datetime(2026, 8, 18, 7, 15, tzinfo=UTC)
    assert pet.tags == ("official", "light")
    assert pet.idle_preview.frame_count == 4
    assert pet.idle_preview.frame_durations_ms == (80, 120, 100, 140)
    assert pet.cover.relative_path.parts == ("store", "pets", "sample_pet", "cover.png")


def test_catalog_parses_optional_package_variants_without_replacing_legacy_package() -> None:
    raw_pet = _pet(package_variants=[_package_variant()])

    pet = PetStoreCatalog.from_dict(_catalog(raw_pet)).pet("sample_pet")

    assert pet is not None
    assert pet.package.path.endswith("/package.zip")
    assert len(pet.package_variants) == 1
    assert pet.package_variants[0].format == "webp-q95"
    assert pet.package_variants[0].package.path.endswith("/package-webp-q95.zip")


def test_pet_store_item_keeps_the_legacy_constructor_signature() -> None:
    parsed = PetStoreCatalog.from_dict(_catalog(_pet())).pet("sample_pet")
    assert parsed is not None

    item = PetStoreItem(
        parsed.identifier,
        parsed.name,
        parsed.author,
        parsed.summary,
        parsed.tags,
        parsed.updated_at,
        parsed.action_count,
        parsed.capabilities,
        parsed.cover,
        parsed.idle_preview,
        parsed.package,
    )

    assert item.package_variants == ()


def test_catalog_rejects_webp_only_item_without_legacy_package() -> None:
    raw_pet = _pet(package_variants=[_package_variant()])
    raw_pet.pop("package")

    with pytest.raises(PetStoreCatalogError, match="package"):
        PetStoreCatalog.from_dict(_catalog(raw_pet))


def test_catalog_rejects_duplicate_package_variant_formats() -> None:
    variants = [
        _package_variant(content=b"first"),
        {
            "format": "webp-q95",
            "package": _file("store/pets/sample_pet/package-webp-q95-second.zip", b"second"),
        },
    ]

    with pytest.raises(PetStoreCatalogError, match="format|重复"):
        PetStoreCatalog.from_dict(_catalog(_pet(package_variants=variants)))


@pytest.mark.parametrize(
    "variants",
    [
        {},
        [_package_variant(format="Bad Format")],
        [_package_variant(format=f"format-{index}") for index in range(5)],
        [
            {
                "format": "webp-q95",
                "package": _file("store/pets/other/package-webp-q95.zip"),
            }
        ],
    ],
)
def test_catalog_rejects_invalid_package_variants(variants: object) -> None:
    with pytest.raises(PetStoreCatalogError, match="package_variants|format|路径"):
        PetStoreCatalog.from_dict(_catalog(_pet(package_variants=variants)))


@pytest.mark.parametrize(
    "path",
    ["../package.zip", "/package.zip", "C:/package.zip", "store\\pets\\x.zip", "store/pets/./x"],
)
def test_catalog_rejects_unsafe_store_paths(path: str) -> None:
    with pytest.raises(PetStoreCatalogError, match="path|路径"):
        PetStoreCatalog.from_dict(_catalog(_pet(package=_file(path))))


def test_catalog_rejects_paths_outside_own_pet_directory() -> None:
    with pytest.raises(PetStoreCatalogError, match="路径"):
        PetStoreCatalog.from_dict(
            _catalog(_pet(cover=_file("store/pets/other/cover.png")))
        )


def test_catalog_rejects_duplicate_ids_and_case_colliding_paths() -> None:
    with pytest.raises(PetStoreCatalogError, match="重复"):
        PetStoreCatalog.from_dict(_catalog(_pet(), _pet()))

    preview = deepcopy(_pet()["idle_preview"])
    assert isinstance(preview, dict)
    preview["path"] = "store/pets/sample_pet/COVER.PNG"
    with pytest.raises(PetStoreCatalogError, match="路径|Windows"):
        PetStoreCatalog.from_dict(_catalog(_pet(idle_preview=preview)))


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("updated_at", "not-a-date", "updated_at"),
        ("updated_at", "2026-08-18T07:13:49", "UTC|偏移"),
        ("action_count", 0, "action_count"),
        ("tags", ["ok", "ok"], "tags|标签"),
        ("capabilities", ["click", "click"], "capabilities|能力"),
    ],
)
def test_catalog_rejects_invalid_item_fields(field: str, value: object, message: str) -> None:
    with pytest.raises(PetStoreCatalogError, match=message):
        PetStoreCatalog.from_dict(_catalog(_pet(**{field: value})))


def test_catalog_rejects_invalid_hashes_sizes_and_preview_timeline() -> None:
    bad_hash = _file("store/pets/sample_pet/package.zip")
    bad_hash["sha256"] = "bad"
    with pytest.raises(PetStoreCatalogError, match="sha256"):
        PetStoreCatalog.from_dict(_catalog(_pet(package=bad_hash)))

    oversized_media = _file("store/pets/sample_pet/cover.png")
    oversized_media["size"] = MAX_MEDIA_SIZE + 1
    with pytest.raises(PetStoreCatalogError, match="大小|size"):
        PetStoreCatalog.from_dict(_catalog(_pet(cover=oversized_media)))

    oversized_package = _file("store/pets/sample_pet/package.zip")
    oversized_package["size"] = MAX_PACKAGE_SIZE + 1
    with pytest.raises(PetStoreCatalogError, match="大小|size"):
        PetStoreCatalog.from_dict(_catalog(_pet(package=oversized_package)))

    preview = deepcopy(_pet()["idle_preview"])
    assert isinstance(preview, dict)
    preview["frame_durations_ms"] = [100]
    with pytest.raises(PetStoreCatalogError, match="时间线|frame"):
        PetStoreCatalog.from_dict(_catalog(_pet(idle_preview=preview)))


def test_catalog_requires_featured_pet_to_exist_and_schema_one() -> None:
    raw = _catalog(_pet())
    raw["featured_pet_id"] = "missing"
    with pytest.raises(PetStoreCatalogError, match="推荐"):
        PetStoreCatalog.from_dict(raw)

    raw = _catalog(_pet())
    raw["schema_version"] = 2
    with pytest.raises(PetStoreCatalogError, match="schema"):
        PetStoreCatalog.from_dict(raw)


def test_catalog_allows_nonempty_catalog_without_featured_pet() -> None:
    raw = _catalog(_pet())
    raw["featured_pet_id"] = None

    catalog = PetStoreCatalog.from_dict(raw)

    assert catalog.featured_pet_id is None
    assert catalog.featured_pet is None


def test_catalog_from_bytes_rejects_large_or_invalid_json() -> None:
    with pytest.raises(PetStoreCatalogError, match="大小|目录"):
        PetStoreCatalog.from_bytes(b" " * (MAX_CATALOG_BYTES + 1))
    with pytest.raises(PetStoreCatalogError, match="JSON"):
        PetStoreCatalog.from_bytes(b"not json")


def test_catalog_json_round_trip() -> None:
    raw = _catalog(_pet())

    catalog = PetStoreCatalog.from_bytes(json.dumps(raw).encode("utf-8"))

    assert catalog.pet("sample_pet") is not None
