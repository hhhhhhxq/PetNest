"""PetNest 统一的暖色奶油风视觉令牌和 Qt 样式。"""

from __future__ import annotations

COLORS = {
    "window_background": "#F7F1EA",
    "surface": "#FFFDF9",
    "surface_alt": "#FBF7F2",
    "accent": "#D98663",
    "accent_soft": "#FFF0E8",
    "text": "#4B4641",
    "muted_text": "#8F8680",
    "border": "#E8DED5",
    "success": "#6D9A7A",
    "error": "#C66C62",
}


def dialog_stylesheet() -> str:
    """返回设置、导入和编辑窗口共用的轻量 QSS。"""
    c = COLORS
    return f"""
        QDialog, QWidget#settingsCenter, QWidget#codexUsageContent {{
            background: {c['window_background']};
            color: {c['text']};
            font-size: 13px;
            font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI";
        }}
        QFrame#windowShell {{
            background: rgba(255, 253, 249, 232);
            border: 1px solid rgba(255, 255, 255, 210);
            border-radius: 22px;
        }}
        QFrame#headerBar {{
            background: rgba(255, 248, 243, 210);
            border: 1px solid rgba(255, 255, 255, 180);
            border-radius: 16px;
        }}
        QFrame#settingsSidebar {{
            background: rgba(251, 244, 238, 175);
            border: 1px solid rgba(255, 255, 255, 150);
            border-radius: 18px;
        }}
        QFrame#contentPane {{
            background: transparent;
            border: none;
        }}
        QFrame#statusCard {{
            background: rgba(255, 255, 255, 145);
            border: 1px solid rgba(255, 255, 255, 180);
            border-radius: 15px;
        }}
        QFrame#previewCard {{
            background: rgba(255, 240, 232, 190);
            border: 1px solid rgba(255, 255, 255, 185);
            border-radius: 16px;
        }}
        QFrame#petStoreHero {{
            background: #FFF0E8;
            border: 1px solid #F1D5C7;
            border-radius: 18px;
        }}
        QFrame#petStoreCard {{
            background: {c['surface']};
            border: 1px solid {c['border']};
            border-radius: 14px;
        }}
        QFrame#petStoreCard:hover {{
            background: #FFF9F5;
            border-color: {c['accent']};
        }}
        QFrame#petStoreCover, QFrame#petStorePreview {{
            background: #F3ECE6;
            border: 1px solid #E9DED5;
            border-radius: 13px;
        }}
        QLabel#petStoreCoverLabel {{
            color: #B9AAA0;
            font-size: 28px;
        }}
        QLabel#petStoreName {{
            color: {c['text']};
            font-size: 15px;
            font-weight: 700;
        }}
        QLabel#petStoreBadge {{
            background: #7A706A;
            color: #FFFFFF;
            border-radius: 9px;
            padding: 4px 8px;
            font-size: 11px;
            font-weight: 700;
        }}
        QLabel#petStoreBadge[storeStatus="adopted"] {{
            background: #3F5147;
        }}
        QLabel#petStoreBadge[storeStatus="update_available"] {{
            background: {c['accent']};
        }}
        QLabel#petStoreBadge[storeStatus="local_existing"] {{
            background: #7A706A;
        }}
        QPushButton#petStoreChip {{
            background: {c['surface']};
            border: 1px solid {c['border']};
            border-radius: 13px;
            padding: 5px 10px;
        }}
        QPushButton#petStoreChip:checked {{
            background: {c['text']};
            color: #FFFFFF;
            border-color: {c['text']};
        }}
        QFrame#stepBar {{
            background: rgba(255, 248, 243, 190);
            border: 1px solid rgba(255, 255, 255, 170);
            border-radius: 14px;
        }}
        QFrame#sourceCard, QFrame#petInfoCard {{
            background: rgba(255, 253, 249, 228);
            border: 1px solid {c['border']};
            border-radius: 16px;
        }}
        QFrame#manualActionCard, QFrame#manualFrameCard {{
            background: rgba(255, 253, 249, 228);
            border: 1px solid {c['border']};
            border-radius: 16px;
        }}
        QListWidget#manualActionList {{
            background: transparent;
            border: none;
            outline: none;
        }}
        QListWidget#manualActionList::item {{
            color: {c['text']};
            background: {c['surface_alt']};
            border: 1px solid {c['border']};
            border-radius: 11px;
            padding: 8px 10px;
            margin: 3px 0;
        }}
        QListWidget#manualActionList::item:selected {{
            color: #A85D3E;
            background: {c['accent_soft']};
            border: 1px solid #E8C7B8;
        }}
        QScrollArea#manualThumbnailArea, QScrollArea#manualThumbnailArea > QWidget, QScrollArea#manualThumbnailArea > QWidget > QWidget {{
            background: transparent;
            border: none;
        }}
        QToolButton#frameOption {{
            background: {c['surface_alt']};
            color: {c['text']};
            border: 1px solid {c['border']};
            border-radius: 12px;
            padding: 8px;
        }}
        QToolButton#frameOption:checked {{
            background: {c['accent_soft']};
            color: #A85D3E;
            border: 2px solid {c['accent']};
        }}
        QLabel#selectionBadge {{
            background: {c['accent_soft']};
            color: #A85D3E;
            border-radius: 10px;
            padding: 7px 12px;
            font-weight: 700;
        }}
        QFrame#sourceDropzone {{
            background: {c['surface_alt']};
            border: 1px dashed #D8C5B9;
            border-radius: 14px;
        }}
        QFrame#modeOption {{
            background: {c['surface_alt']};
            border: 1px solid {c['border']};
            border-radius: 12px;
        }}
        QFrame#modeOption:hover {{
            border: 1px solid {c['accent']};
            background: {c['accent_soft']};
        }}
        QFrame#modeSwitch, QFrame#totalTimeline {{
            background: {c['surface_alt']};
            border: 1px solid {c['border']};
            border-radius: 10px;
        }}
        QFrame#workdaySelector, QFrame#scheduleModeSwitch, QFrame#advancedSettings {{
            background: {c['surface_alt']};
            border: 1px solid {c['border']};
            border-radius: 12px;
        }}
        QFrame#scheduleModeSwitch QRadioButton {{
            background: transparent;
            padding: 7px 10px;
            border-radius: 8px;
        }}
        QFrame#scheduleModeSwitch QRadioButton:checked {{
            background: {c['surface']};
            color: {c['accent']};
            font-weight: 700;
        }}
        QFrame#scheduleModeSwitch QRadioButton::indicator,
        QFrame#modeSwitch QRadioButton::indicator {{
            width: 0px;
            height: 0px;
            border: none;
            background: transparent;
        }}
        QToolButton#advancedSettings {{
            text-align: left;
            color: {c['text']};
            font-weight: 600;
        }}
        QFrame#modeSwitch QRadioButton {{
            background: transparent;
            padding: 7px 10px;
            border-radius: 8px;
        }}
        QFrame#modeSwitch QRadioButton:checked {{
            background: {c['accent_soft']};
            color: {c['accent']};
            font-weight: 700;
        }}
        QLabel {{
            color: {c['text']};
        }}
        QLabel#pageTitle {{
            color: {c['text']};
            font-size: 22px;
            font-weight: 700;
        }}
        QLabel#contentTitle {{
            color: {c['text']};
            font-size: 28px;
            font-weight: 700;
        }}
        QLabel#contentDescription {{
            color: {c['muted_text']};
            font-size: 14px;
        }}
        QLabel#accentValue {{
            color: #A85D3E;
            font-size: 17px;
            font-weight: 700;
        }}
        QLabel#pageDescription, QLabel#mutedLabel {{
            color: {c['muted_text']};
        }}
        QListWidget#settingsNavigation {{
            background: transparent;
            border: none;
            outline: none;
            padding: 8px 4px;
        }}
        QListWidget#settingsNavigation::item {{
            color: {c['muted_text']};
            padding: 11px 14px;
            margin: 3px 0;
            border-radius: 9px;
        }}
        QListWidget#settingsNavigation::item:hover {{
            background: {c['accent_soft']};
            color: {c['text']};
        }}
        QListWidget#settingsNavigation::item:selected {{
            background: {c['accent_soft']};
            color: {c['accent']};
            font-weight: 700;
        }}
        QListWidget#settingsNavigation::item:selected:active {{
            background: {c['accent_soft']};
            color: {c['accent']};
        }}
        QTableWidget#animationActionTable, QListWidget#animationFrameList {{
            background: rgba(255, 253, 249, 155);
            border: 1px solid {c['border']};
            border-radius: 12px;
            gridline-color: transparent;
            outline: none;
        }}
        QTableWidget#animationActionTable::item, QListWidget#animationFrameList::item {{
            padding: 8px;
            border-radius: 8px;
        }}
        QTableWidget#animationActionTable::item:selected, QListWidget#animationFrameList::item:selected {{
            background: {c['accent_soft']};
            color: {c['accent']};
        }}
        QFrame#settingsCard {{
            background: rgba(255, 253, 249, 228);
            border: 1px solid {c['border']};
            border-radius: 12px;
        }}
        QGroupBox {{
            background: rgba(255, 253, 249, 220);
            border: 1px solid {c['border']};
            border-radius: 12px;
            margin-top: 12px;
            padding: 16px 12px 12px 12px;
            font-weight: 700;
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            left: 12px;
            padding: 0 5px;
            color: {c['text']};
        }}
        QLineEdit, QSpinBox, QDoubleSpinBox, QTimeEdit, QComboBox {{
            background: {c['surface']};
            color: {c['text']};
            border: 1px solid {c['border']};
            border-radius: 8px;
            padding: 7px 9px;
            min-height: 18px;
        }}
        QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QTimeEdit:focus, QComboBox:focus {{
            border: 1px solid {c['accent']};
        }}
        QComboBox::drop-down {{
            border: none;
            width: 24px;
        }}
        QCheckBox {{
            spacing: 8px;
            padding: 4px 0;
        }}
        QCheckBox::indicator {{
            width: 17px;
            height: 17px;
            border-radius: 5px;
            border: 1px solid {c['border']};
            background: {c['surface']};
        }}
        QCheckBox::indicator:checked {{
            background: {c['accent']};
            border-color: {c['accent']};
        }}
        QCheckBox#toggleSwitch {{
            spacing: 10px;
            padding: 4px 0;
            background: transparent;
            border: none;
        }}
        QCheckBox#toggleSwitch::indicator {{
            width: 0px;
            height: 0px;
            border: none;
            background: transparent;
        }}
        QCheckBox#toggleSwitch::indicator:checked {{
            background: {c['accent']};
            border-color: {c['accent']};
        }}
        QRadioButton {{
            spacing: 8px;
            padding: 5px 0;
        }}
        QPushButton {{
            background: {c['surface']};
            color: {c['text']};
            border: 1px solid {c['border']};
            border-radius: 9px;
            padding: 8px 15px;
            min-height: 18px;
        }}
        QPushButton:hover {{
            background: {c['accent_soft']};
            border-color: {c['accent']};
        }}
        QPushButton#primaryButton {{
            background: {c['accent']};
            color: #FFFFFF;
            border-color: {c['accent']};
            font-weight: 700;
        }}
        QPushButton#petStoreHeroButton {{
            background: {c['accent']};
            color: #FFFFFF;
            border-color: {c['accent']};
            font-weight: 700;
        }}
        QPushButton#primaryButton:hover {{
            background: #C87555;
        }}
        QPushButton#primaryButton:disabled {{
            background: #D8CEC6;
            color: {c['muted_text']};
            border-color: #D8CEC6;
        }}
        QSlider::groove:horizontal {{
            height: 5px;
            background: {c['border']};
            border-radius: 3px;
        }}
        QSlider::handle:horizontal {{
            width: 18px;
            margin: -7px 0;
            background: {c['accent']};
            border: 2px solid {c['surface']};
            border-radius: 9px;
        }}
        QScrollArea {{
            background: transparent;
            border: none;
        }}
        QWidget#petStoreScrollContent {{
            background: transparent;
        }}
        QAbstractScrollArea#settingsScroll, QScrollArea#settingsScroll > QWidget, QScrollArea#settingsScroll > QWidget > QWidget {{
            background: transparent;
            border: none;
        }}
        QStackedWidget#settingsPageStack, QWidget#settingsPage {{
            background: transparent;
        }}
        QDialogButtonBox {{
            border-top: 1px solid {c['border']};
            padding-top: 10px;
        }}
    """


def card_stylesheet() -> str:
    """返回单独卡片可复用的 QSS。"""
    c = COLORS
    return f"""
        QFrame#settingsCard {{
            background: {c['surface']};
            border: 1px solid {c['border']};
            border-radius: 12px;
        }}
    """


def menu_stylesheet(object_name: str = "trayMenu") -> str:
    """返回托盘菜单的奶油风样式；宠物右键菜单不调用此函数。"""
    c = COLORS
    return f"""
        QMenu#{object_name} {{
            background: rgba(255, 253, 249, 248);
            color: {c['text']};
            border: 1px solid {c['border']};
            border-radius: 12px;
            padding: 7px;
            font-size: 13px;
            font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI";
        }}
        QMenu#{object_name}::item {{
            padding: 8px 30px 8px 12px;
            margin: 1px 0;
            border-radius: 7px;
        }}
        QMenu#{object_name}::item:selected {{
            background: {c['accent_soft']};
            color: {c['text']};
        }}
        QMenu#{object_name}::item:disabled {{
            color: {c['muted_text']};
        }}
        QMenu#{object_name}::separator {{
            height: 1px;
            background: {c['border']};
            margin: 6px 8px;
        }}
    """
