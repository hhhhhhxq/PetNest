"""v4 原型设计令牌、专用 QSS 和 Lucide 图标测试。"""

from __future__ import annotations

from petnest.ui.action_import_visual_style import TOKENS, action_import_stylesheet
from petnest.ui.lucide_icons import ACTION_IMPORT_ICON_NAMES, lucide_icon


def test_visual_tokens_match_the_approved_v4_prototype() -> None:
    assert TOKENS == {
        "window_background": "#fdf9f5",
        "top_background": "#fffdfa",
        "sidebar_background": "#fbf4ef",
        "panel_background": "#fffdfa",
        "mode_background": "#f4e9e2",
        "summary_background": "#faf0e9",
        "text": "#4c423d",
        "muted": "#7c6b63",
        "accent": "#c7603e",
        "primary": "#d97955",
        "border": "#eadbd2",
        "window_radius": 20,
        "top_height": 56,
        "sidebar_width": 145,
        "main_padding": 17,
        "panel_radius": 13,
        "panel_padding": 11,
        "mode_radius": 11,
        "mode_padding": 5,
        "frame_height": 82,
        "frame_gap": 7,
        "frame_delete_size": 20,
        "preview_height": 170,
    }


def test_every_prototype_lucide_icon_renders(qtbot: object) -> None:
    assert ACTION_IMPORT_ICON_NAMES == (
        "cat",
        "package-plus",
        "store",
        "film",
        "timer",
        "package-open",
        "package-search",
        "list-checks",
        "images",
        "folder-open",
        "play",
        "gallery-horizontal",
        "list-tree",
    )
    for name in ACTION_IMPORT_ICON_NAMES:
        icon = lucide_icon(name, color="#c7603e", size=18)
        assert not icon.isNull(), name
        assert not icon.pixmap(18, 18).isNull(), name


def test_action_import_stylesheet_is_scoped_and_uses_prototype_colors() -> None:
    stylesheet = action_import_stylesheet()

    assert "QDialog#petActionExchangeDialog" in stylesheet
    assert "#fdf9f5" in stylesheet
    assert "#c7603e" in stylesheet
    assert "#d97955" in stylesheet
    assert "QFrame#actionImportPanel" in stylesheet
    assert "QFrame#actionImportModeSwitch" in stylesheet
    assert "QWidget#actionImportPage QLineEdit" in stylesheet
    assert 'font-family: "PingFang SC", "Hiragino Sans GB"' in stylesheet
    assert TOKENS["muted"] == "#7c6b63"
    assert f"color: {TOKENS['muted']};" in stylesheet
    assert "\n        QLineEdit," not in stylesheet
    assert "\n        QPushButton {{" not in stylesheet
