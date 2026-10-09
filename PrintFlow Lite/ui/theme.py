"""
Podbase WORK dizaino sistema (UI_DIZAINAS.md)
--------------------------------------------
Spalvų žetonai, šriftai ir viso programos QSS stilius šviesiai ir tamsiai temai.
Jokių šešėlių, gradientų ar papildomų spalvų – tik dokumente aprašyti žetonai.
"""

import os
import sys

from PySide6.QtGui import QFontDatabase, QFont, QColor

LIGHT = {
    "page": "#F8F8F7", "card": "#FFFFFF", "fill": "#F0F0EE", "pressed": "#E7E7E5",
    "text": "#171717", "secondary": "#5F5F5F", "muted": "#8A8A8A", "disabled": "#B5B5B5",
    "border": "#E7E7E5", "divider": "#EEEEEC", "strong": "#D8D8D5",
    "primary": "#111111", "primary_hover": "#2A2A2A", "on_primary": "#FFFFFF", "focus": "#111111",
}

DARK = {
    "page": "#121212", "card": "#1E1E1E", "fill": "#2E2E2D", "pressed": "#2C2C2B",
    "text": "#F5F5F5", "secondary": "#A3A3A0", "muted": "#A3A3A0", "disabled": "#5F5F5F",
    "border": "#2C2C2B", "divider": "#2C2C2B", "strong": "#2E2E2D",
    "primary": "#2D2D2D", "primary_hover": "#2E2E2D", "on_primary": "#F5F5F5", "focus": "#A3A3A0",
}

# Būsenų spalvos ir šviesūs fonai
STATUS = {
    "success": ("#198754", "#EAF7EF"),
    "warning": ("#B7791F", "#FFF7E6"),
    "error": ("#D64545", "#FDEEEE"),
    "info": ("#3478F6", "#EEF4FF"),
}

FONT_FAMILY = "Inter"
_fonts_loaded = False


def resource_path(*parts) -> str:
    """Kelias iki programos resursų (veikia ir PyInstaller --onefile režimu)."""
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *parts)


def load_fonts() -> str:
    """Įkelia Inter (fonts/). Jei nepavyksta – Segoe UI."""
    global _fonts_loaded, FONT_FAMILY
    if _fonts_loaded:
        return FONT_FAMILY
    _fonts_loaded = True
    ok = False
    for name in ("Inter-Regular.ttf", "Inter-Medium.ttf", "Inter-SemiBold.ttf", "Inter-Bold.ttf"):
        path = resource_path("fonts", name)
        if os.path.exists(path) and QFontDatabase.addApplicationFont(path) >= 0:
            ok = True
    FONT_FAMILY = "Inter" if ok else "Segoe UI"
    return FONT_FAMILY


def tokens(theme: str) -> dict:
    return DARK if theme == "dark" else LIGHT


def mix(c1: str, c2: str, t: float) -> str:
    """Sumaišo dvi spalvas: t=0 ➔ c1, t=1 ➔ c2."""
    a, b = QColor(c1), QColor(c2)
    return QColor(
        round(a.red() + (b.red() - a.red()) * t),
        round(a.green() + (b.green() - a.green()) * t),
        round(a.blue() + (b.blue() - a.blue()) * t),
    ).name()


def status_colors(kind: str, theme: str) -> tuple:
    """(spalva, fonas, rėmelis) būsenai pagal temą."""
    if kind == "neutral":
        t = tokens(theme)
        return t["secondary"], t["fill"], t["border"]
    color, light_bg = STATUS[kind]
    if theme == "dark":
        card = DARK["card"]
        return color, mix(card, color, 0.16), mix(card, color, 0.35)
    return color, light_bg, mix(light_bg, color, 0.22)


def tnum_font(base: QFont) -> QFont:
    """Lygaus pločio skaitmenys (tnum) kintantiems skaičiams."""
    f = QFont(base)
    try:
        f.setFeature(QFont.Tag("tnum"), 1)
    except Exception:
        pass
    return f


def build_qss(theme: str) -> str:
    t = tokens(theme)
    ff = FONT_FAMILY
    succ, succ_bg, _ = status_colors("success", theme)
    err, err_bg, _ = status_colors("error", theme)
    return f"""
* {{ font-family: '{ff}', 'Segoe UI', sans-serif; font-size: 14px; color: {t['text']}; outline: none; }}
QMainWindow, QWidget#page, QStackedWidget, QScrollArea, QScrollArea > QWidget > QWidget {{ background: {t['page']}; }}
QToolTip {{ background: {t['card']}; color: {t['text']}; border: 1px solid {t['border']}; padding: 6px 8px; border-radius: 12px; }}

/* Viršutinė juosta ir skirtukai */
QFrame#topbar {{ background: {t['card']}; border: none; border-bottom: 1px solid {t['border']}; }}
QFrame#tabbar {{ background: {t['card']}; border: none; border-bottom: 1px solid {t['border']}; }}
QPushButton#tab {{ background: transparent; border: none; border-bottom: 2px solid transparent; border-radius: 0;
    color: {t['secondary']}; font-size: 13px; font-weight: 500; padding: 0; min-height: 42px; }}
QPushButton#tab:hover {{ color: {t['text']}; background: transparent; }}
QPushButton#tab:checked {{ color: {t['text']}; border-bottom: 2px solid {t['text']}; }}

/* Kortelės */
QFrame#card {{ background: {t['card']}; border: 1px solid {t['border']}; border-radius: 16px; }}
QFrame#card QLabel, QFrame#card QFrame#plain {{ background: transparent; }}
QFrame#divider {{ background: {t['divider']}; border: none; max-height: 1px; min-height: 1px; }}

/* Tekstų rolės */
QLabel {{ background: transparent; }}
QLabel[role="title"] {{ font-size: 22px; font-weight: 600; }}
QLabel[role="subtitle"] {{ font-size: 17px; font-weight: 600; }}
QLabel[role="appname"] {{ font-size: 15px; font-weight: 600; }}
QLabel[role="strong"] {{ font-weight: 600; }}
QLabel[role="secondary"] {{ font-size: 13px; color: {t['secondary']}; }}
QLabel[role="label"] {{ font-size: 13px; font-weight: 600; }}
QLabel[role="caption"] {{ font-size: 12px; color: {t['muted']}; }}
QLabel[role="section"] {{ font-size: 11px; font-weight: 600; color: {t['muted']}; letter-spacing: 1px; }}
QLabel[role="error"] {{ font-size: 13px; color: {err}; }}

/* Mygtukai */
QPushButton {{ background: {t['card']}; color: {t['text']}; border: 1px solid {t['border']}; border-radius: 12px;
    min-height: 38px; padding: 0 14px; font-weight: 500; }}
QPushButton:hover {{ background: {t['fill']}; }}
QPushButton:pressed {{ background: {t['pressed']}; }}
QPushButton:disabled {{ color: {t['disabled']}; }}
QPushButton[variant="primary"] {{ background: {t['primary']}; color: {t['on_primary']}; border: 1px solid {t['primary']}; font-weight: 600; }}
QPushButton[variant="primary"]:hover {{ background: {t['primary_hover']}; }}
QPushButton[variant="primary"]:disabled {{ background: {t['strong']}; border-color: {t['strong']}; color: {t['on_primary']}; }}
QPushButton[variant="success"] {{ background: {succ}; color: #FFFFFF; border: none; font-weight: 600; }}
QPushButton[variant="danger"] {{ color: {err}; }}
QPushButton[variant="danger"]:hover {{ background: {err_bg}; }}
QPushButton[variant="danger-solid"] {{ background: {err}; color: #FFFFFF; border: none; font-weight: 600; }}
QPushButton[variant="ghost"] {{ background: transparent; border: none; }}
QPushButton[variant="ghost"]:hover {{ background: {t['fill']}; }}
QPushButton[variant="icon"] {{ background: transparent; border: none; min-height: 36px; max-height: 36px;
    min-width: 36px; max-width: 36px; padding: 0; }}
QPushButton[variant="icon"]:hover {{ background: {t['fill']}; }}
QPushButton[size="small"] {{ min-height: 30px; max-height: 32px; padding: 0 10px; font-size: 13px; }}
QPushButton[size="large"] {{ min-height: 46px; padding: 0 20px; }}

/* Laukai */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{ background: {t['card']}; border: 1px solid {t['border']}; border-radius: 12px;
    min-height: 38px; padding: 0 12px; selection-background-color: {t['pressed']}; selection-color: {t['text']}; }}
QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover {{ border-color: {t['strong']}; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border-color: {t['focus']}; }}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{ color: {t['disabled']}; background: {t['page']}; }}
QLineEdit[invalid="true"] {{ border-color: {err}; }}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
    width: 0; border: none; }}
QComboBox::drop-down {{ border: none; width: 28px; }}
QComboBox QAbstractItemView {{ background: {t['card']}; border: 1px solid {t['border']}; border-radius: 12px; padding: 4px;
    selection-background-color: {t['fill']}; selection-color: {t['text']}; }}

/* Lentelės ir sąrašai */
QTableWidget, QListWidget {{ background: {t['card']}; border: none; gridline-color: transparent;
    selection-background-color: {t['fill']}; selection-color: {t['text']}; alternate-background-color: {t['card']}; }}
QTableWidget::item {{ border-bottom: 1px solid {t['divider']}; padding: 0 8px; }}
QTableWidget::item:hover, QListWidget::item:hover {{ background: {t['fill']}; }}
QTableWidget::item:selected, QListWidget::item:selected {{ background: {t['fill']}; color: {t['text']}; }}
QListWidget::item {{ border-radius: 12px; padding: 0 12px; min-height: 40px; }}
QHeaderView {{ background: {t['card']}; border: none; }}
QHeaderView::section {{ background: {t['card']}; color: {t['muted']}; font-size: 11px; font-weight: 600;
    border: none; border-bottom: 1px solid {t['border']}; padding: 0 12px; min-height: 36px; text-align: left; }}
QTableCornerButton::section {{ background: {t['card']}; border: none; }}

/* Slinkties juostos */
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {t['strong']}; border-radius: 3px; min-height: 30px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {t['strong']}; border-radius: 3px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ background: none; border: none; width: 0; height: 0; }}

/* Žurnalas */
QTextEdit#log {{ background: {t['card']}; border: none; font-size: 13px; }}

/* Segmentų valdiklis */
QFrame#segmented {{ background: {t['fill']}; border: none; border-radius: 12px; }}
QPushButton#segment {{ background: transparent; border: 1px solid transparent; border-radius: 10px; min-height: 30px; max-height: 32px;
    padding: 0 14px; color: {t['secondary']}; font-size: 13px; font-weight: 500; }}
QPushButton#segment:checked {{ background: {t['card']}; border: 1px solid {t['border']}; color: {t['text']}; }}

/* Plokščių eilutės produktų formoje */
QFrame#plateRow {{ background: {t['card']}; border: 1px solid {t['border']}; border-radius: 12px; }}
QFrame#plateRow[off="true"] {{ background: {t['page']}; border: 1px dashed {t['strong']}; }}
QLabel#platePos {{ font-weight: 600; color: {t['secondary']}; }}

/* Dialogai */
QFrame#dialogCard {{ background: {t['card']}; border: 1px solid {t['border']}; border-radius: 24px; }}
"""
