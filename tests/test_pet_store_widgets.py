from __future__ import annotations

from pathlib import Path

from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget

from petnest.core.pet_store_catalog import PetStoreCatalog
from petnest.core.pet_store_state import PetStoreStatus
from petnest.ui.pet_store_widgets import PetStoreCard, PetStoreIdlePreview
from tests.test_pet_store_catalog import _catalog, _pet


def _item():
    item = PetStoreCatalog.from_dict(_catalog(_pet())).pet("sample_pet")
    assert item is not None
    return item


def _write_strip(path: Path, *, frame_count: int = 3, frame_size: tuple[int, int] = (24, 24)) -> Path:
    width, height = frame_size
    strip = Image.new("RGBA", (width * frame_count, height), (0, 0, 0, 0))
    for index in range(frame_count):
        frame = Image.new("RGBA", frame_size, (40 + index * 30, 20, 80, 255))
        strip.alpha_composite(frame, (index * width, 0))
    strip.save(path)
    return path


def test_store_card_displays_adopted_update_and_local_badges(qtbot: object) -> None:
    card = PetStoreCard(_item())
    qtbot.addWidget(card)

    card.set_store_status(PetStoreStatus.ADOPTED)
    assert card.status_badge.text() == "已领养"
    assert card.status_badge.property("storeStatus") == "adopted"
    card.set_store_status(PetStoreStatus.UPDATE_AVAILABLE)
    assert card.status_badge.text() == "可更新"
    card.set_store_status(PetStoreStatus.LOCAL_EXISTING)
    assert card.status_badge.text() == "本地已有"
    card.set_store_status(PetStoreStatus.NOT_ADOPTED)
    assert card.status_badge.isHidden()


def test_store_card_badge_does_not_change_card_height(qtbot: object) -> None:
    plain = PetStoreCard(_item())
    badged = PetStoreCard(_item())
    qtbot.addWidget(plain)
    qtbot.addWidget(badged)
    plain.set_store_status(PetStoreStatus.NOT_ADOPTED)
    badged.set_store_status(PetStoreStatus.LOCAL_EXISTING)
    plain.ensurePolished()
    badged.ensurePolished()

    assert badged.sizeHint().height() == plain.sizeHint().height()


def test_store_card_emits_selection_and_visible_cover_request(qtbot: object) -> None:
    viewport = QWidget()
    viewport.resize(400, 300)
    card = PetStoreCard(_item(), viewport)
    card.resize(220, 240)
    qtbot.addWidget(viewport)
    viewport.show()
    card.show()
    selected: list[str] = []
    requested: list[str] = []
    card.selected.connect(selected.append)
    card.cover_requested.connect(requested.append)

    qtbot.mouseClick(card, Qt.MouseButton.LeftButton)
    card.request_cover_if_visible(viewport)

    assert selected == ["sample_pet"]
    assert requested == ["sample_pet"]


def test_store_card_loads_cover_without_upscaling_failure(qtbot: object, tmp_path: Path) -> None:
    cover = tmp_path / "cover.png"
    Image.new("RGBA", (40, 30), (20, 30, 40, 255)).save(cover)
    card = PetStoreCard(_item())
    qtbot.addWidget(card)

    assert card.set_cover(cover) is True
    assert card.cover_label.pixmap() is not None
    assert not card.cover_label.pixmap().isNull()


def test_idle_preview_slices_horizontal_strip_and_advances_by_timeline(
    qtbot: object, tmp_path: Path
) -> None:
    strip = _write_strip(tmp_path / "preview.png")
    widget = PetStoreIdlePreview()
    qtbot.addWidget(widget)

    assert widget.load_strip(
        strip,
        frame_width=24,
        frame_height=24,
        durations_ms=(80, 120, 100),
    )
    widget.advance_frame()

    assert widget.current_frame_index == 1
    assert widget.timer.interval() == 120
    assert len(widget.frames) == 3


def test_idle_preview_rejects_bad_geometry_and_stops_timer(qtbot: object, tmp_path: Path) -> None:
    strip = _write_strip(tmp_path / "preview.png")
    widget = PetStoreIdlePreview()
    qtbot.addWidget(widget)

    assert not widget.load_strip(
        strip,
        frame_width=25,
        frame_height=24,
        durations_ms=(100, 100, 100),
    )
    widget.stop()

    assert not widget.timer.isActive()
    assert widget.frames == []


def test_idle_preview_stop_clears_previous_pet_frame(qtbot: object, tmp_path: Path) -> None:
    widget = PetStoreIdlePreview()
    qtbot.addWidget(widget)
    strip = _write_strip(tmp_path / "preview.png")
    assert widget.load_strip(
        strip,
        frame_width=24,
        frame_height=24,
        durations_ms=(80, 120, 100),
    )
    assert widget.frame_label.pixmap() is not None

    widget.stop()

    pixmap = widget.frame_label.pixmap()
    assert pixmap is None or pixmap.isNull()
