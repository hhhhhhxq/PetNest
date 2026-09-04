from pathlib import Path

from PIL import Image
from PySide6.QtCore import QPoint, Qt

from petnest.ui.drag_cursor_overlay import DragCursorOverlay


def test_drag_cursor_overlay_tracks_hotspot_without_accepting_input(
    qtbot, tmp_path: Path
) -> None:
    icon = tmp_path / "wand.png"
    Image.new("RGBA", (128, 128), (240, 180, 80, 255)).save(icon)
    overlay = DragCursorOverlay()
    qtbot.addWidget(overlay)

    overlay.show_at(QPoint(500, 300), icon, hotspot=(100, 105))

    assert overlay.isVisible()
    assert overlay.windowFlags() & Qt.WindowType.WindowTransparentForInput
    assert overlay.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus
    assert overlay.mapToGlobal(QPoint(100, 105)) == QPoint(500, 300)

    overlay.move_hotspot(QPoint(550, 340))
    assert overlay.mapToGlobal(QPoint(100, 105)) == QPoint(550, 340)

    overlay.clear()
    assert not overlay.isVisible()
