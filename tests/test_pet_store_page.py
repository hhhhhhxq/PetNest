from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import Event

from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QMessageBox, QPushButton
import pytest

from petnest.core.pet_package_importer import PetImportResult
from petnest.core.pet_store_cache import CatalogLoadResult
from petnest.core.pet_store_catalog import PetStoreCatalog, PetStoreFile, PetStoreItem
from petnest.core.pet_store_service import PetStoreInstallResult, PetStoreLocalConflict
from petnest.core.pet_store_state import PetStoreStatus
from petnest.ui.pet_store_page import PetStorePage
from tests.test_pet_store_catalog import _catalog, _pet


@dataclass(frozen=True)
class _InstallCall:
    pet_id: str
    allow_local_replace: bool


class _Service:
    def __init__(self, tmp_path: Path, *, offline: bool = False) -> None:
        miffy = _pet(
            "miffy",
            name="棉花糖米菲",
            author="PetNest",
            tags=["治愈系", "兔兔"],
        )
        dundun = _pet(
            "dundun",
            name="团团猫球",
            author="PetNest",
            tags=["治愈系", "猫猫"],
        )
        raw = _catalog(miffy, dundun)
        raw["featured_pet_id"] = "miffy"
        self.catalog = PetStoreCatalog.from_dict(raw)
        self.offline = offline
        self.statuses = {
            "miffy": PetStoreStatus.NOT_ADOPTED,
            "dundun": PetStoreStatus.ADOPTED,
        }
        self.media: dict[str, Path] = {}
        for item in self.catalog.pets:
            cover = tmp_path / f"{item.identifier}-cover.png"
            Image.new("RGBA", (32, 32), (20, 30, 40, 255)).save(cover)
            preview = tmp_path / f"{item.identifier}-preview.png"
            Image.new("RGBA", (item.idle_preview.frame_width * 4, 32), (40, 30, 20, 255)).save(preview)
            self.media[item.cover.sha256] = cover
            self.media[item.idle_preview.sha256] = preview
        self.install_calls: list[_InstallCall] = []
        self.confirmed: list[str] = []
        self.install_error: Exception | None = None
        self.package_overrides: dict[str, PetStoreFile] = {}

    def load_catalog(self) -> CatalogLoadResult:
        return CatalogLoadResult(self.catalog, self.offline)

    def status_for(self, item: PetStoreItem) -> PetStoreStatus:
        return self.statuses[item.identifier]

    def package_for(self, item: PetStoreItem) -> PetStoreFile:
        return self.package_overrides.get(item.identifier, item.package)

    def load_media(self, remote: PetStoreFile, *, cancel: Event | None = None) -> Path:
        return self.media[remote.sha256]

    def install(
        self,
        item: PetStoreItem,
        *,
        allow_local_replace: bool = False,
        progress: object = None,
        cancel: Event | None = None,
    ) -> PetStoreInstallResult:
        self.install_calls.append(_InstallCall(item.identifier, allow_local_replace))
        if self.install_error is not None and not allow_local_replace:
            raise self.install_error
        if callable(progress):
            progress(item.package.size, item.package.size)
        imported = PetImportResult(item.identifier, Path("pets") / item.identifier, None, False)
        return PetStoreInstallResult(item, imported)

    def confirm_install(self, result: PetStoreInstallResult) -> None:
        self.confirmed.append(result.item.identifier)
        self.statuses[result.item.identifier] = PetStoreStatus.ADOPTED


def test_store_page_filters_by_name_author_tag_and_adopted(qtbot: object, tmp_path: Path) -> None:
    service = _Service(tmp_path)
    page = PetStorePage(service, run_tasks_inline=True)  # type: ignore[arg-type]
    qtbot.addWidget(page)
    page.activate()

    page.search_input.setText("米菲")
    assert page.visible_pet_ids() == ["miffy"]
    page.search_input.setText("")
    page.select_tag("猫猫")
    assert page.visible_pet_ids() == ["dundun"]


def test_filtered_cards_reflow_from_first_grid_slot(qtbot: object, tmp_path: Path) -> None:
    page = PetStorePage(_Service(tmp_path), run_tasks_inline=True)  # type: ignore[arg-type]
    qtbot.addWidget(page)
    page.activate()

    page.select_tag("猫猫")

    layout_index = page.cards_layout.indexOf(page._cards["dundun"])
    assert page.cards_layout.getItemPosition(layout_index) == (0, 0, 1, 1)


def test_adopted_filter_includes_existing_local_pets(qtbot: object, tmp_path: Path) -> None:
    service = _Service(tmp_path)
    service.statuses["dundun"] = PetStoreStatus.LOCAL_EXISTING
    page = PetStorePage(service, run_tasks_inline=True)  # type: ignore[arg-type]
    qtbot.addWidget(page)
    page.activate()

    page.select_tag("已领养")

    assert page.visible_pet_ids() == ["dundun"]


def test_store_grid_stays_top_aligned_with_three_stable_columns(qtbot: object, tmp_path: Path) -> None:
    page = PetStorePage(_Service(tmp_path), run_tasks_inline=True)  # type: ignore[arg-type]
    qtbot.addWidget(page)
    page.activate()

    assert page.cards_layout.alignment() & Qt.AlignmentFlag.AlignTop
    assert [page.cards_layout.columnStretch(index) for index in range(3)] == [1, 1, 1]
    assert page.scroll_content.objectName() == "petStoreScrollContent"
    page.select_tag("已领养")
    assert page.visible_pet_ids() == ["dundun"]


def test_page_uses_curated_recommendation_wording(qtbot: object, tmp_path: Path) -> None:
    page = PetStorePage(_Service(tmp_path), run_tasks_inline=True)  # type: ignore[arg-type]
    qtbot.addWidget(page)
    page.activate()

    texts = {label.text() for label in page.findChildren(QLabel)}
    assert "精选推荐" in texts
    assert "本周推荐" not in texts


def test_page_hides_recommendation_when_catalog_has_no_featured_pet(
    qtbot: object, tmp_path: Path
) -> None:
    service = _Service(tmp_path)
    raw = _catalog(
        _pet("miffy", name="棉花糖米菲", tags=["兔兔"]),
        _pet("dundun", name="团团猫球", tags=["猫猫"]),
    )
    raw["featured_pet_id"] = None
    service.catalog = PetStoreCatalog.from_dict(raw)
    page = PetStorePage(service, run_tasks_inline=True)  # type: ignore[arg-type]
    qtbot.addWidget(page)

    page.activate()

    assert page.hero.isHidden()


def test_detail_footer_only_offers_adopt_update_or_disabled_adopted(
    qtbot: object, tmp_path: Path
) -> None:
    service = _Service(tmp_path)
    page = PetStorePage(service, run_tasks_inline=True)  # type: ignore[arg-type]
    qtbot.addWidget(page)
    page.activate()

    page.show_detail("miffy")
    assert page.footer_state().primary_text == "领养"
    service.statuses["miffy"] = PetStoreStatus.ADOPTED
    page.refresh_statuses()
    assert page.footer_state().primary_text == "已领养"
    assert page.footer_state().primary_enabled is False
    service.statuses["miffy"] = PetStoreStatus.UPDATE_AVAILABLE
    page.refresh_statuses()
    assert page.footer_state().primary_text == "更新"
    button_texts = {button.text() for button in page.findChildren(QPushButton)}
    assert "切换使用" not in button_texts
    assert "重新下载" not in button_texts


def test_page_keeps_cached_catalog_and_marks_offline(qtbot: object, tmp_path: Path) -> None:
    page = PetStorePage(_Service(tmp_path, offline=True), run_tasks_inline=True)  # type: ignore[arg-type]
    qtbot.addWidget(page)
    page.activate()

    assert page.offline_badge.isVisibleTo(page)
    assert page.visible_pet_ids() == ["miffy", "dundun"]


def test_page_confirms_local_same_id_before_replacing(
    qtbot: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = _Service(tmp_path)
    service.install_error = PetStoreLocalConflict("本地已有")
    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes),
    )
    page = PetStorePage(service, run_tasks_inline=True)  # type: ignore[arg-type]
    qtbot.addWidget(page)
    page.activate()
    page.show_detail("miffy")

    page.trigger_primary()

    assert service.install_calls[-1] == _InstallCall("miffy", True)


def test_install_is_confirmed_only_after_host_completion(qtbot: object, tmp_path: Path) -> None:
    service = _Service(tmp_path)
    page = PetStorePage(service, run_tasks_inline=True)  # type: ignore[arg-type]
    qtbot.addWidget(page)
    page.activate()
    page.show_detail("miffy")
    ready: list[tuple[str, object]] = []
    page.pet_install_ready.connect(lambda pet_id, result: ready.append((pet_id, result)))

    page.trigger_primary()
    assert service.confirmed == []
    assert ready and ready[0][0] == "miffy"
    page.complete_install("领养完成")

    assert service.confirmed == ["miffy"]
    assert page.footer_state().primary_text == "已领养"


def test_store_page_displays_the_package_selected_for_this_client(qtbot: object, tmp_path: Path) -> None:
    service = _Service(tmp_path)
    service.package_overrides["miffy"] = PetStoreFile(
        "store/pets/miffy/package-webp-q95.zip",
        10 * 1024 * 1024,
        "a" * 64,
    )
    page = PetStorePage(service, run_tasks_inline=True)  # type: ignore[arg-type]
    qtbot.addWidget(page)

    page.activate()
    page.show_detail("miffy")

    assert page._cards["miffy"].size_label.text() == "10.0 MB"
    assert "10.0 MB" in page.detail_facts.text()


def test_production_worker_loads_catalog_and_preview_without_blocking(qtbot: object, tmp_path: Path) -> None:
    service = _Service(tmp_path)
    page = PetStorePage(service)  # type: ignore[arg-type]
    qtbot.addWidget(page)
    page.show()

    page.activate()
    qtbot.waitUntil(lambda: page.visible_pet_ids() == ["miffy", "dundun"], timeout=3000)
    page.show_detail("miffy")
    qtbot.waitUntil(lambda: bool(page.preview.frames), timeout=3000)

    assert len(page.preview.frames) == 4
