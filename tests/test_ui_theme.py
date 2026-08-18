from petnest.ui.theme import COLORS, card_stylesheet, dialog_stylesheet, menu_stylesheet


def test_petnest_theme_exposes_confirmed_visual_tokens() -> None:
    assert {
        "window_background",
        "surface",
        "surface_alt",
        "accent",
        "accent_soft",
        "text",
        "muted_text",
        "border",
        "success",
        "error",
    } <= set(COLORS)
    assert COLORS["window_background"] == "#F7F1EA"
    assert COLORS["accent"] == "#D98663"


def test_petnest_theme_stylesheets_cover_common_controls() -> None:
    stylesheet = dialog_stylesheet()

    for selector in ("QPushButton", "QLineEdit", "QComboBox", "QCheckBox", "QGroupBox"):
        assert selector in stylesheet
    assert "QPushButton#primaryButton:disabled" in stylesheet
    assert "QFrame#settingsCard" in card_stylesheet()
    assert "QMenu#trayMenu" in menu_stylesheet("trayMenu")
