from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path

from petnest.core.pet_store_catalog import PetStoreCatalog, PetStoreItem
from petnest.core.pet_store_state import PetStoreStateStore, PetStoreStatus
from tests.test_pet_store_catalog import _catalog, _pet


def _item(package_sha: str | None = None) -> PetStoreItem:
    raw = _pet()
    if package_sha is not None:
        assert isinstance(raw["package"], dict)
        raw["package"]["sha256"] = package_sha
    item = PetStoreCatalog.from_dict(_catalog(raw)).pet("sample_pet")
    assert item is not None
    return item


def test_status_distinguishes_not_adopted_local_adopted_and_update(tmp_path: Path) -> None:
    store = PetStoreStateStore(tmp_path / "state.json")
    item = _item("a" * 64)
    pets_root = tmp_path / "pets"

    assert store.status_for(item, pets_root) is PetStoreStatus.NOT_ADOPTED
    (pets_root / item.identifier).mkdir(parents=True)
    assert store.status_for(item, pets_root) is PetStoreStatus.LOCAL_EXISTING
    store.record_install(item, installed_at=datetime(2026, 8, 18, tzinfo=UTC))
    assert store.status_for(item, pets_root) is PetStoreStatus.ADOPTED
    assert store.status_for(_item("b" * 64), pets_root) is PetStoreStatus.UPDATE_AVAILABLE


def test_missing_pet_directory_removes_stale_receipt(tmp_path: Path) -> None:
    store = PetStoreStateStore(tmp_path / "state.json")
    item = _item()
    pet_root = tmp_path / "pets" / item.identifier
    pet_root.mkdir(parents=True)
    store.record_install(item, installed_at=datetime(2026, 8, 18, tzinfo=UTC))
    pet_root.rmdir()

    assert store.status_for(item, tmp_path / "pets") is PetStoreStatus.NOT_ADOPTED
    assert store.receipt(item.identifier) is None


def test_record_install_writes_atomic_schema_and_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    store = PetStoreStateStore(path)
    item = _item("c" * 64)

    store.record_install(item, installed_at=datetime(2026, 8, 18, 8, 30, tzinfo=UTC))

    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["schema_version"] == 1
    assert raw["receipts"][item.identifier]["package_sha256"] == "c" * 64
    receipt = PetStoreStateStore(path).receipt(item.identifier)
    assert receipt is not None
    assert receipt.catalog_updated_at == item.updated_at
    assert not list(tmp_path.glob(".state.json-*.tmp"))


def test_corrupt_state_is_quarantined_and_treated_as_empty(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    path.write_text("not json", encoding="utf-8")
    store = PetStoreStateStore(path)

    assert store.load() == {}
    assert not path.exists()
    assert len(list(tmp_path.glob("state.invalid-*.json"))) == 1


def test_forget_only_removes_requested_receipt(tmp_path: Path) -> None:
    store = PetStoreStateStore(tmp_path / "state.json")
    first = _item()
    second_raw = _pet("second")
    catalog = _catalog(_pet(), second_raw)
    catalog["featured_pet_id"] = "sample_pet"
    second = PetStoreCatalog.from_dict(catalog).pet("second")
    assert second is not None
    store.record_install(first)
    store.record_install(second)

    store.forget(first.identifier)

    assert store.receipt(first.identifier) is None
    assert store.receipt(second.identifier) is not None
