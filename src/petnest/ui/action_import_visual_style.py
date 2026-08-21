"""Visual contract translated directly from action-import-redesign-v4.html."""

from __future__ import annotations


TOKENS: dict[str, str | int] = {
    "window_background": "#fdf9f5",
    "top_background": "#fffdfa",
    "sidebar_background": "#fbf4ef",
    "panel_background": "#fffdfa",
    "mode_background": "#f4e9e2",
    "summary_background": "#faf0e9",
    "text": "#4c423d",
    "muted": "#95837a",
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


def action_import_stylesheet() -> str:
    """Return a style scoped to the complete pet/action exchange dialog."""

    t = TOKENS
    return f"""
        QDialog#petActionExchangeDialog {{
            background: {t['window_background']};
            color: {t['text']};
            font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI";
            font-size: 12px;
        }}
        QFrame#actionExchangeShell {{
            background: {t['window_background']};
            border: 1px solid #e7d8cf;
            border-radius: {t['window_radius']}px;
        }}
        QFrame#actionExchangeTopBar {{
            background: {t['top_background']};
            border: none;
            border-bottom: 1px solid #eee1d8;
        }}
        QLabel#actionExchangeLogo {{
            background: #fbe7dc;
            border: none;
            border-radius: 9px;
        }}
        QLabel#actionExchangeAppTitle {{
            color: {t['text']};
            font-size: 13px;
            font-weight: 600;
        }}
        QFrame#actionExchangeSidebar {{
            background: {t['sidebar_background']};
            border: none;
            border-right: 1px solid #eee1d8;
        }}
        QListWidget#settingsNavigation {{
            background: transparent;
            border: none;
            outline: none;
            padding: 6px 0;
        }}
        QListWidget#settingsNavigation::item {{
            color: #88776e;
            background: transparent;
            border: none;
            border-radius: 9px;
            padding: 9px 11px;
            margin: 2px 0;
        }}
        QListWidget#settingsNavigation::item:selected {{
            color: {t['accent']};
            background: #fde9df;
            font-weight: 600;
        }}
        QWidget#actionExchangeMain {{
            background: {t['window_background']};
        }}
        QLabel#pageTitle {{
            color: {t['text']};
            font-size: 19px;
            font-weight: 600;
        }}
        QWidget#actionImportPage QLabel#mutedLabel,
        QWidget#actionImportPage QLabel#actionImportMuted,
        QLabel#actionExchangeSubtitle,
        QLabel#actionExchangeTargetLabel {{
            color: {t['muted']};
        }}
        QFrame#actionImportModeSwitch {{
            background: {t['mode_background']};
            border: 1px solid {t['border']};
            border-radius: {t['mode_radius']}px;
        }}
        QFrame#actionImportModeSwitch QRadioButton {{
            color: {t['text']};
            background: transparent;
            border: none;
            border-radius: 8px;
            padding: 9px;
        }}
        QFrame#actionImportModeSwitch QRadioButton::indicator {{
            width: 0;
            height: 0;
        }}
        QFrame#actionImportModeSwitch QRadioButton:checked {{
            color: {t['accent']};
            background: {t['panel_background']};
            font-weight: 600;
        }}
        QFrame#actionImportPanel {{
            background: {t['panel_background']};
            border: 1px solid {t['border']};
            border-radius: {t['panel_radius']}px;
        }}
        QLabel#actionImportPanelTitle {{
            color: {t['text']};
            font-weight: 600;
        }}
        QLabel#actionImportCount {{
            color: #9a8880;
            font-size: 10px;
        }}
        QLabel#actionImportTarget {{
            color: #7c6b63;
            background: {t['summary_background']};
            border: none;
            border-radius: 8px;
            padding: 7px 9px;
            font-size: 10px;
        }}
        QFrame#actionImportFrameHint {{
            background: transparent;
            border: none;
        }}
        QFrame#resourceSourceDropZone {{
            background: #fff8f3;
            border: 1px dashed #d9b6a5;
            border-radius: 10px;
        }}
        QFrame#resourceSummaryCard {{
            background: {t['summary_background']};
            border: none;
            border-radius: 9px;
        }}
        QTableWidget#resourceActionTable {{
            background: transparent;
            alternate-background-color: #fdf9f5;
            border: none;
            gridline-color: #eee2da;
            outline: none;
            selection-background-color: transparent;
        }}
        QTableWidget#resourceActionTable QHeaderView::section {{
            background: transparent;
            color: #9a8880;
            border: none;
            border-bottom: 1px solid #eee2da;
            padding: 6px 7px;
            font-size: 10px;
        }}
        QTableWidget#resourceActionTable QComboBox {{
            padding: 5px 6px;
            min-height: 16px;
        }}
        QWidget#actionImportPage QLineEdit,
        QWidget#actionImportPage QSpinBox,
        QWidget#actionImportPage QDoubleSpinBox,
        QWidget#actionImportPage QComboBox,
        QComboBox#actionImportTargetPet {{
            color: {t['text']};
            background: #ffffff;
            border: 1px solid #dfcfc5;
            border-radius: 8px;
            padding: 7px 9px;
        }}
        QWidget#actionImportPage QPushButton {{
            color: {t['text']};
            background: transparent;
            border: 1px solid #dfcfc6;
            border-radius: 8px;
            padding: 6px 8px;
        }}
        QWidget#actionImportPage QPushButton:hover {{
            color: {t['accent']};
            border-color: #cf896c;
        }}
        QPushButton#actionImportSecondary {{
            padding: 6px 8px;
            font-size: 11px;
        }}
        QPushButton#primaryButton {{
            color: #ffffff;
            background: {t['primary']};
            border: none;
            border-radius: 9px;
            padding: 9px 15px;
            font-weight: 600;
        }}
        QPushButton#primaryButton:disabled {{
            color: #a99a93;
            background: #e7dcd5;
        }}
        QListWidget#imageActionFrameList {{
            background: transparent;
            border: none;
            outline: none;
        }}
        QFrame#imageFrameCard {{
            background: #fffaf7;
            border: 1px solid #e5d3c9;
            border-radius: 9px;
        }}
        QFrame#imageFrameCard QLabel[checkerboard="true"] {{
            border: none;
            border-radius: 7px;
        }}
        QToolButton#frameDeleteButton {{
            color: #9d8980;
            background: rgba(255, 253, 250, 220);
            border: none;
            border-radius: 6px;
        }}
        QToolButton#frameDeleteButton:hover {{
            color: #bd4f43;
            background: #fde5df;
        }}
        QWidget#actionImportPage QLabel[checkerboard="true"] {{
            border: none;
            border-radius: 10px;
        }}
    """


__all__ = ["TOKENS", "action_import_stylesheet"]
