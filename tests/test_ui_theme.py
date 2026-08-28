from petnest.ui.theme import (
    COLORS,
    FONT_FAMILY,
    card_stylesheet,
    dialog_stylesheet,
    menu_stylesheet,
)


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


def test_light_animation_editor_explicitly_overrides_dark_system_text_colors() -> None:
    stylesheet = dialog_stylesheet()

    assert FONT_FAMILY.startswith('"PingFang SC", "Hiragino Sans GB"')
    assert f"font-family: {FONT_FAMILY};" in stylesheet
    assert "QFrame#modeSwitch QRadioButton {" in stylesheet
    assert f"color: {COLORS['text']};" in stylesheet
    assert "QTableWidget#animationActionTable::item" in stylesheet


def test_light_theme_covers_controls_that_otherwise_inherit_dark_system_palette() -> None:
    stylesheet = dialog_stylesheet()

    assert COLORS["muted_text"] == "#746B66"
    for selector in (
        "QListWidget, QTableWidget, QTreeWidget",
        "QHeaderView::section",
        "QComboBox QAbstractItemView",
        "QTextEdit, QPlainTextEdit",
        "QProgressBar",
        "QToolTip",
        "QCheckBox:disabled, QRadioButton:disabled",
        "QPushButton:disabled, QToolButton:disabled",
    ):
        assert selector in stylesheet
    assert f"selection-background-color: {COLORS['accent_soft']};" in stylesheet
    assert f"selection-color: {COLORS['accent']};" in stylesheet
    assert f"placeholder-text-color: {COLORS['muted_text']};" in stylesheet
