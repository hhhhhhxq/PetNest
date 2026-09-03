from __future__ import annotations

from pathlib import Path
from threading import Event, Thread
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from petnest.core.pet_store_cache import (
    CatalogLoadResult,
    PetStoreDownloadCancelled,
    PetStoreDownloadError,
)
from petnest.core.pet_store_service import (
    PetStoreBusyError,
    PetStoreInstallResult,
    PetStoreLocalConflict,
    PetStorePetLocked,
    PetStoreService,
)
from petnest.core.pet_store_state import PetStoreStateStore, PetStoreStatus
from tests.test_pet_package_importer import write_pet
from tests.test_pet_store_catalog import _catalog, _package_variant, _pet
from petnest.core.pet_store_catalog import PetStoreCatalog, PetStoreItem


def _item() -> PetStoreItem:
    item = PetStoreCatalog.from_dict(_catalog(_pet())).pet("sample_pet")
    assert item is not None
    return item


def _package_zip(tmp_path: Path) -> Path:
    source = tmp_path / "source"
    write_pet(source, identifier="sample_pet", actions=("idle",))
    archive_path = tmp_path / "sample_pet.zip"
    with ZipFile(archive_path, "w", ZIP_DEFLATED) as archive:
        for path in sorted(source.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(source).as_posix())
    return archive_path


class _Cache:
    def __init__(self, package: Path, catalog: PetStoreCatalog | None = None) -> None:
        self.package = package
        self.catalog = catalog
        self.fetch_calls = 0
        self.fetch_remotes: list[object] = []
        self.package_by_sha: dict[str, Path] = {}
        self.errors_by_sha: dict[str, Exception] = {}

    def fetch_catalog_or_cached(self) -> CatalogLoadResult:
        assert self.catalog is not None
        return CatalogLoadResult(self.catalog, False)

    def fetch_media(self, _remote: object, *, cancel: Event | None = None) -> Path:
        return self.package

    def fetch_package(self, _remote: object, *, progress: object = None, cancel: Event | None = None) -> Path:
        self.fetch_calls += 1
        self.fetch_remotes.append(_remote)
        if cancel is not None and cancel.is_set():
            raise PetStoreDownloadCancelled("cancelled")
        digest = getattr(_remote, "sha256", "")
        error = self.errors_by_sha.get(digest)
        if error is not None:
            raise error
        if digest in self.package_by_sha:
            return self.package_by_sha[digest]
        return self.package


def _service(tmp_path: Path, *, locked: bool = False) -> tuple[PetStoreService, _Cache, PetStoreItem]:
    item = _item()
    cache = _Cache(_package_zip(tmp_path))
    state = PetStoreStateStore(tmp_path / "state.json")
    service = PetStoreService(
        cache,  # type: ignore[arg-type]
        state,
        tmp_path / "pets",
        is_pet_locked=lambda _identifier: locked,
    )
    return service, cache, item


def _variant_item() -> PetStoreItem:
    item = PetStoreCatalog.from_dict(
        _catalog(_pet(package_variants=[_package_variant()]))
    ).pet("sample_pet")
    assert item is not None
    return item


def test_install_downloads_and_imports_without_writing_receipt(tmp_path: Path) -> None:
    service, cache, item = _service(tmp_path)

    result = service.install(item)

    assert result.item is item
    assert result.pet_import.pet_id == item.identifier
    assert cache.fetch_calls == 1
    assert service.state.receipt(item.identifier) is None
    assert (tmp_path / "pets" / item.identifier / "pet.json").is_file()


def test_service_prefers_supported_webp_package_and_can_disable_variants(tmp_path: Path) -> None:
    item = _variant_item()
    cache = _Cache(_package_zip(tmp_path))
    state = PetStoreStateStore(tmp_path / "state.json")

    supported = PetStoreService(cache, state, tmp_path / "pets")  # type: ignore[arg-type]
    legacy_only = PetStoreService(
        cache,  # type: ignore[arg-type]
        state,
        tmp_path / "legacy-pets",
        supported_package_formats=frozenset(),
    )

    assert supported.package_for(item) == item.package_variants[0].package
    assert legacy_only.package_for(item) == item.package


def test_install_falls_back_to_legacy_package_when_variant_download_fails(tmp_path: Path) -> None:
    item = _variant_item()
    cache = _Cache(_package_zip(tmp_path))
    cache.errors_by_sha[item.package_variants[0].package.sha256] = PetStoreDownloadError("bad variant")
    service = PetStoreService(  # type: ignore[arg-type]
        cache,
        PetStoreStateStore(tmp_path / "state.json"),
        tmp_path / "pets",
    )

    result = service.install(item)

    assert cache.fetch_remotes == [item.package_variants[0].package, item.package]
    assert result.package == item.package


def test_install_falls_back_to_legacy_package_when_variant_import_is_invalid(tmp_path: Path) -> None:
    item = _variant_item()
    legacy = _package_zip(tmp_path)
    invalid_variant = tmp_path / "invalid-variant.zip"
    invalid_variant.write_bytes(b"not a zip")
    cache = _Cache(legacy)
    cache.package_by_sha[item.package_variants[0].package.sha256] = invalid_variant
    service = PetStoreService(  # type: ignore[arg-type]
        cache,
        PetStoreStateStore(tmp_path / "state.json"),
        tmp_path / "pets",
    )

    result = service.install(item)

    assert cache.fetch_remotes == [item.package_variants[0].package, item.package]
    assert result.package == item.package


def test_variant_download_cancellation_does_not_fall_back(tmp_path: Path) -> None:
    item = _variant_item()
    cache = _Cache(_package_zip(tmp_path))
    cache.errors_by_sha[item.package_variants[0].package.sha256] = PetStoreDownloadCancelled("cancelled")
    service = PetStoreService(  # type: ignore[arg-type]
        cache,
        PetStoreStateStore(tmp_path / "state.json"),
        tmp_path / "pets",
    )

    with pytest.raises(PetStoreDownloadCancelled):
        service.install(item)

    assert cache.fetch_remotes == [item.package_variants[0].package]


def test_cancel_after_invalid_variant_import_stops_before_cached_legacy_fallback(tmp_path: Path) -> None:
    item = _variant_item()
    legacy = _package_zip(tmp_path)
    invalid_variant = tmp_path / "invalid-cancelled-variant.zip"
    invalid_variant.write_bytes(b"not a zip")
    cancel = Event()

    class CancelAfterVariantCache(_Cache):
        def fetch_package(
            self,
            remote: object,
            *,
            progress: object = None,
            cancel: Event | None = None,
        ) -> Path:
            self.fetch_calls += 1
            self.fetch_remotes.append(remote)
            if remote == item.package_variants[0].package:
                assert cancel is not None
                cancel.set()
                return invalid_variant
            return legacy

    cache = CancelAfterVariantCache(legacy)
    service = PetStoreService(  # type: ignore[arg-type]
        cache,
        PetStoreStateStore(tmp_path / "state.json"),
        tmp_path / "pets",
    )

    with pytest.raises(PetStoreDownloadCancelled):
        service.install(item, cancel=cancel)

    assert cache.fetch_remotes == [item.package_variants[0].package]
    assert not (tmp_path / "pets" / item.identifier).exists()


def test_confirm_install_records_selected_variant_and_status_accepts_all_current_packages(tmp_path: Path) -> None:
    item = _variant_item()
    cache = _Cache(_package_zip(tmp_path))
    service = PetStoreService(  # type: ignore[arg-type]
        cache,
        PetStoreStateStore(tmp_path / "state.json"),
        tmp_path / "pets",
    )

    result = service.install(item)
    service.confirm_install(result)

    receipt = service.state.receipt(item.identifier)
    assert receipt is not None
    assert receipt.package_sha256 == item.package_variants[0].package.sha256
    assert service.status_for(item) is PetStoreStatus.ADOPTED


def test_confirm_install_writes_receipt_only_after_runtime_accepts_result(tmp_path: Path) -> None:
    service, _cache, item = _service(tmp_path)
    result = service.install(item)

    service.confirm_install(result)

    receipt = service.state.receipt(item.identifier)
    assert receipt is not None
    assert receipt.package_sha256 == item.package.sha256


def test_install_requires_confirmation_for_untracked_same_id(tmp_path: Path) -> None:
    service, cache, item = _service(tmp_path)
    (tmp_path / "pets" / item.identifier).mkdir(parents=True)

    with pytest.raises(PetStoreLocalConflict):
        service.install(item)

    assert cache.fetch_calls == 0


def test_locked_pet_fails_before_download(tmp_path: Path) -> None:
    service, cache, item = _service(tmp_path, locked=True)

    with pytest.raises(PetStorePetLocked):
        service.install(item)

    assert cache.fetch_calls == 0


def test_rollback_install_removes_new_pet_and_does_not_write_receipt(tmp_path: Path) -> None:
    service, _cache, item = _service(tmp_path)
    result = service.install(item)

    service.rollback_install(result)

    assert not (tmp_path / "pets" / item.identifier).exists()
    assert service.state.receipt(item.identifier) is None


def test_install_propagates_cancel_without_importing(tmp_path: Path) -> None:
    service, _cache, item = _service(tmp_path)
    cancel = Event()
    cancel.set()

    with pytest.raises(PetStoreDownloadCancelled):
        service.install(item, cancel=cancel)

    assert not (tmp_path / "pets" / item.identifier).exists()


def test_second_concurrent_install_is_rejected(tmp_path: Path) -> None:
    service, cache, item = _service(tmp_path)
    started = Event()
    release = Event()
    original_fetch = cache.fetch_package

    def blocking_fetch(*args: object, **kwargs: object) -> Path:
        started.set()
        assert release.wait(timeout=3)
        return original_fetch(*args, **kwargs)

    cache.fetch_package = blocking_fetch  # type: ignore[method-assign]
    failures: list[Exception] = []

    def first_install() -> None:
        try:
            service.install(item)
        except Exception as error:  # pragma: no cover - assertion reports unexpected worker errors.
            failures.append(error)

    worker = Thread(target=first_install)
    worker.start()
    assert started.wait(timeout=3)
    try:
        with pytest.raises(PetStoreBusyError):
            service.install(item)
    finally:
        release.set()
        worker.join(timeout=3)
    assert not failures


def test_service_forwards_catalog_media_and_status(tmp_path: Path) -> None:
    service, cache, item = _service(tmp_path)
    cache.catalog = PetStoreCatalog.from_dict(_catalog(_pet()))

    assert service.load_catalog().catalog.pet(item.identifier) is not None
    assert service.load_media(item.cover) == cache.package
    assert service.status_for(item) is PetStoreStatus.NOT_ADOPTED
