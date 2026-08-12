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
        QDialog, QWidget#settingsCenter {{
            background: {c['window_background']};
            color: {c['text']};
            font-size: 13px;
        }}
        QLabel {{
            color: {c['text']};
        }}
        QLabel#pageTitle {{
            color: {c['text']};
            font-size: 22px;
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
        QPushButton#primaryButton:hover {{
            background: #C87555;
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
