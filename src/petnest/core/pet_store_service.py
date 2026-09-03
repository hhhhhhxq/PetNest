"""Business orchestration for browsing and adopting store pets."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from threading import Event, Lock

from .pet_package_importer import (
    PetImportResult,
    PetPackageImportError,
    import_pet_package,
    rollback_pet_import,
)
from .pet_store_cache import (
    CatalogLoadResult,
    PetStoreCache,
    PetStoreDownloadCancelled,
    PetStoreDownloadError,
)
from .pet_store_catalog import PetStoreFile, PetStoreItem
from .pet_store_state import PetStoreStateStore, PetStoreStatus


class PetStoreServiceError(RuntimeError):
    """A store operation cannot continue safely."""


class PetStoreLocalConflict(PetStoreServiceError):
    """A same-ID local pet has no store receipt and needs confirmation."""


class PetStorePetLocked(PetStoreServiceError):
    """The target pet is currently leased by a runtime feature."""


class PetStoreBusyError(PetStoreServiceError):
    """Another store install is already active."""


@dataclass(frozen=True, slots=True)
class PetStoreInstallResult:
    item: PetStoreItem
    pet_import: PetImportResult
    package: PetStoreFile | None = None


class PetStoreService:
    DEFAULT_SUPPORTED_PACKAGE_FORMATS = frozenset({"webp-q95"})

    def __init__(
        self,
        cache: PetStoreCache,
        state: PetStoreStateStore,
        pets_root: Path,
        *,
        is_pet_locked: Callable[[str], bool] | None = None,
        supported_package_formats: frozenset[str] | None = None,
    ) -> None:
        self.cache = cache
        self.state = state
        self.pets_root = Path(pets_root).expanduser().resolve()
        self._is_pet_locked = is_pet_locked or (lambda _identifier: False)
        self.supported_package_formats = (
            self.DEFAULT_SUPPORTED_PACKAGE_FORMATS
            if supported_package_formats is None
            else frozenset(supported_package_formats)
        )
        self._install_lock = Lock()

    def load_catalog(self) -> CatalogLoadResult:
        return self.cache.fetch_catalog_or_cached()

    def status_for(self, item: PetStoreItem) -> PetStoreStatus:
        return self.state.status_for(item, self.pets_root)

    def package_for(self, item: PetStoreItem) -> PetStoreFile:
        for variant in item.package_variants:
            if variant.format in self.supported_package_formats:
                return variant.package
        return item.package

    def load_media(
        self, remote: PetStoreFile, *, cancel: Event | None = None
    ) -> Path:
        return self.cache.fetch_media(remote, cancel=cancel)

    def install(
        self,
        item: PetStoreItem,
        *,
        allow_local_replace: bool = False,
        progress: Callable[[int, int], object] | None = None,
        cancel: Event | None = None,
    ) -> PetStoreInstallResult:
        if not self._install_lock.acquire(blocking=False):
            raise PetStoreBusyError("已有宠物正在领养或更新")
        try:
            if self._is_pet_locked(item.identifier):
                raise PetStorePetLocked("当前宠物正在显示下班提醒，请先结束提醒")
            status = self.status_for(item)
            if status is PetStoreStatus.LOCAL_EXISTING and not allow_local_replace:
                raise PetStoreLocalConflict("本地已有同 ID 宠物，需要确认备份并替换")
            preferred = self.package_for(item)
            candidates = (preferred,) if preferred == item.package else (preferred, item.package)
            for remote in candidates:
                if cancel is not None and cancel.is_set():
                    raise PetStoreDownloadCancelled("宠物包下载已取消")
                try:
                    package = self.cache.fetch_package(
                        remote,
                        progress=progress,
                        cancel=cancel,
                    )
                    imported = import_pet_package(package, self.pets_root)
                    return PetStoreInstallResult(item, imported, remote)
                except PetStoreDownloadCancelled:
                    raise
                except (PetStoreDownloadError, PetPackageImportError):
                    if remote == item.package:
                        raise
            raise PetStoreServiceError("没有可用的宠物包")
        finally:
            self._install_lock.release()

    def confirm_install(self, result: PetStoreInstallResult) -> None:
        self.state.record_install(result.item, package=result.package)

    def rollback_install(self, result: PetStoreInstallResult) -> None:
        rollback_pet_import(result.pet_import, self.pets_root)


__all__ = [
    "PetStoreBusyError",
    "PetStoreInstallResult",
    "PetStoreLocalConflict",
    "PetStorePetLocked",
    "PetStoreService",
    "PetStoreServiceError",
]
