"""Tema visual aplikasi: palet terang, font, dan stylesheet global (QSS).

Warna diambil dari satu set token agar semua halaman konsisten. Tombol diberi varian lewat
properti dinamis `variant` (lihat `variant()`), label lewat properti `role`.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication, QWidget

# ---------- token warna ----------
BG = "#F3F5F9"
SURFACE = "#FFFFFF"
SURFACE_ALT = "#F8FAFC"
BORDER = "#E2E8F0"
BORDER_STRONG = "#CBD5E1"
TEXT = "#0F172A"
TEXT_SOFT = "#334155"
MUTED = "#64748B"
SUBTLE = "#94A3B8"
PRIMARY = "#2563EB"
PRIMARY_HOVER = "#1D4ED8"
PRIMARY_PRESSED = "#1E40AF"
PRIMARY_SOFT = "#EFF6FF"
PRIMARY_SOFT_BORDER = "#BFDBFE"
SUCCESS = "#16A34A"
SUCCESS_HOVER = "#15803D"
DANGER = "#DC2626"
DANGER_SOFT = "#FEF2F2"
DANGER_BORDER = "#FCA5A5"
SLATE = "#334155"
VIDEO_BG = "#0F172A"

# Path QSS harus memakai garis miring maju, juga di Windows
ASSETS = Path(__file__).with_name("assets").as_posix()

FONT_FAMILIES = ["Segoe UI Variable Text", "Segoe UI", "Inter", "Noto Sans", "Ubuntu"]


def variant(widget: QWidget, name: str) -> QWidget:
    """Tandai tombol: "primary", "success", "danger", atau "ghost"."""
    widget.setProperty("variant", name)
    return widget


def role(widget: QWidget, name: str) -> QWidget:
    """Tandai label: "muted", "caption", "title", "subtitle", "callout", atau "brand"."""
    widget.setProperty("role", name)
    return widget


STYLESHEET = f"""
QWidget {{ color: {TEXT}; }}
QMainWindow, QDialog, QTabWidget > QWidget {{ background: {BG}; }}
QToolTip {{
    background: {TEXT}; color: white; border: none; padding: 6px 8px; border-radius: 6px;
}}

/* ---------- tab ---------- */
QTabWidget::pane {{ border: none; border-top: 1px solid {BORDER}; background: {BG}; }}
QTabBar {{ qproperty-drawBase: 0; background: transparent; }}
QTabBar::tab {{
    background: transparent; color: {MUTED}; font-weight: 600;
    padding: 12px 18px 10px; margin-right: 2px;
    border: none; border-bottom: 3px solid transparent;
}}
QTabBar::tab:hover:!selected {{ color: {TEXT}; border-bottom-color: {BORDER_STRONG}; }}
QTabBar::tab:selected {{ color: {PRIMARY}; border-bottom-color: {PRIMARY}; }}

/* ---------- kartu ---------- */
QGroupBox {{
    background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 12px;
    margin-top: 22px; padding: 14px 14px 12px; font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin; subcontrol-position: top left;
    left: 4px; top: 0; padding: 0 4px; color: {TEXT_SOFT}; font-size: 13px;
}}
QFrame[card="true"] {{
    background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 12px;
}}
QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}

/* ---------- label ---------- */
QLabel[role="muted"] {{ color: {MUTED}; }}
QLabel[role="caption"] {{ color: {MUTED}; font-size: 11px; }}
QLabel[role="title"] {{ font-size: 22px; font-weight: 700; }}
QLabel[role="subtitle"] {{ color: {MUTED}; font-size: 15px; }}
QLabel[role="brand"] {{ font-size: 15px; font-weight: 700; color: {TEXT}; padding: 0 8px; }}
QLabel[role="callout"] {{
    background: {PRIMARY_SOFT}; color: {PRIMARY_PRESSED};
    border: 1px solid {PRIMARY_SOFT_BORDER}; border-left: 4px solid {PRIMARY};
    border-radius: 8px; padding: 12px 14px; font-size: 17px; font-weight: 600;
}}

/* ---------- input ---------- */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit, QTimeEdit,
QPlainTextEdit, QTextEdit {{
    background: {SURFACE}; border: 1px solid {BORDER_STRONG}; border-radius: 8px;
    padding: 6px 10px; min-height: 22px;
    selection-background-color: {PRIMARY_SOFT_BORDER}; selection-color: {TEXT};
}}
QLineEdit:hover, QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover,
QDateEdit:hover, QPlainTextEdit:hover, QTextEdit:hover {{ border-color: {SUBTLE}; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QDateEdit:focus, QTimeEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {{
    border: 1px solid {PRIMARY}; background: {SURFACE};
}}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{
    background: {SURFACE_ALT}; color: {SUBTLE}; border-color: {BORDER};
}}
QComboBox QAbstractItemView {{
    background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px;
    selection-background-color: {PRIMARY_SOFT}; selection-color: {TEXT}; padding: 4px;
}}
QCheckBox {{ spacing: 8px; }}

/* popup auto-complete */
QListView#completerPopup, QCompleter QAbstractItemView {{
    background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 4px;
}}

/* ---------- tombol ---------- */
QPushButton {{
    background: {SURFACE}; color: {TEXT_SOFT}; font-weight: 600;
    border: 1px solid {BORDER_STRONG}; border-radius: 8px; padding: 8px 16px;
}}
QPushButton:hover {{ background: {SURFACE_ALT}; border-color: {SUBTLE}; }}
QPushButton:pressed {{ background: {BORDER}; }}
QPushButton:focus {{ border-color: {PRIMARY}; }}
QPushButton:disabled {{ color: {SUBTLE}; background: {SURFACE_ALT}; border-color: {BORDER}; }}

QPushButton[variant="primary"] {{
    background: {PRIMARY}; border-color: {PRIMARY}; color: white;
}}
QPushButton[variant="primary"]:hover {{ background: {PRIMARY_HOVER}; }}
QPushButton[variant="primary"]:pressed {{ background: {PRIMARY_PRESSED}; }}
QPushButton[variant="primary"]:disabled {{
    background: {PRIMARY_SOFT_BORDER}; border-color: {PRIMARY_SOFT_BORDER};
}}

QPushButton[variant="success"] {{
    background: {SUCCESS}; border-color: {SUCCESS}; color: white;
}}
QPushButton[variant="success"]:hover {{ background: {SUCCESS_HOVER}; }}

QPushButton[variant="danger"] {{
    background: {SURFACE}; border-color: {DANGER_BORDER}; color: {DANGER};
}}
QPushButton[variant="danger"]:hover {{ background: {DANGER_SOFT}; border-color: {DANGER}; }}

QPushButton[variant="ghost"] {{
    background: transparent; border-color: transparent; color: {TEXT_SOFT};
}}
QPushButton[variant="ghost"]:hover {{ background: {BORDER}; }}

/* ---------- tabel ---------- */
QTableView {{
    background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 10px;
    gridline-color: {SURFACE_ALT}; alternate-background-color: {SURFACE_ALT};
    selection-background-color: {PRIMARY_SOFT}; selection-color: {TEXT};
}}
QHeaderView::section {{
    background: {SURFACE_ALT}; color: {MUTED}; font-weight: 600;
    border: none; border-bottom: 1px solid {BORDER}; padding: 8px 10px;
}}
QTableCornerButton::section {{ background: {SURFACE_ALT}; border: none; }}
QTableView::item {{ padding: 0 8px; }}

/* ---------- subkontrol combobox, spinbox, checkbox ---------- */
QComboBox {{ padding-right: 30px; }}
QComboBox::drop-down {{
    subcontrol-origin: padding; subcontrol-position: center right;
    width: 28px; border: none; background: transparent;
}}
QComboBox::down-arrow {{ image: url({ASSETS}/chevron-down.svg); width: 12px; height: 12px; }}
QComboBox::down-arrow:disabled {{ image: none; }}

QSpinBox, QDoubleSpinBox, QDateEdit, QTimeEdit {{ padding-right: 26px; }}
QSpinBox::up-button, QDoubleSpinBox::up-button, QDateEdit::up-button, QTimeEdit::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button, QDateEdit::down-button,
QTimeEdit::down-button {{
    subcontrol-origin: border; width: 24px; border: none; background: transparent;
}}
QSpinBox::up-button, QDoubleSpinBox::up-button, QDateEdit::up-button, QTimeEdit::up-button {{
    subcontrol-position: top right; margin: 3px 3px 0 0;
}}
QSpinBox::down-button, QDoubleSpinBox::down-button, QDateEdit::down-button,
QTimeEdit::down-button {{
    subcontrol-position: bottom right; margin: 0 3px 3px 0;
}}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover, QDateEdit::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover,
QDateEdit::down-button:hover {{ background: {BORDER}; border-radius: 4px; }}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow, QDateEdit::up-arrow, QTimeEdit::up-arrow {{
    image: url({ASSETS}/chevron-up.svg); width: 10px; height: 10px;
}}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow, QDateEdit::down-arrow,
QTimeEdit::down-arrow {{
    image: url({ASSETS}/chevron-down.svg); width: 10px; height: 10px;
}}
QDateEdit[calendarPopup="true"]::drop-down {{
    subcontrol-origin: padding; subcontrol-position: center right;
    width: 26px; border: none; background: transparent;
}}
QDateEdit[calendarPopup="true"]::down-arrow {{
    image: url({ASSETS}/chevron-down.svg); width: 12px; height: 12px;
}}

QCheckBox::indicator {{
    width: 18px; height: 18px; border: 1px solid {BORDER_STRONG}; border-radius: 5px;
    background: {SURFACE};
}}
QCheckBox::indicator:hover {{ border-color: {PRIMARY}; }}
QCheckBox::indicator:checked {{
    background: {PRIMARY}; border-color: {PRIMARY}; image: url({ASSETS}/check.svg);
}}
QCheckBox::indicator:disabled {{ background: {SURFACE_ALT}; border-color: {BORDER}; }}

/* ---------- tombol ganti kamera di atas tampilan kamera ---------- */
QToolButton#cameraSwitch {{
    background: rgba(15, 23, 42, 0.72); color: white; font-weight: 600;
    border: 1px solid rgba(255, 255, 255, 0.25); border-radius: 8px; padding: 6px 12px;
}}
QToolButton#cameraSwitch:hover {{ background: rgba(37, 99, 235, 0.9); }}
QToolButton#cameraSwitch::menu-indicator {{ image: none; width: 0; }}

/* ---------- lain-lain ---------- */
QProgressBar {{
    background: {BORDER}; border: none; border-radius: 8px; min-height: 18px;
    text-align: center; color: {TEXT_SOFT}; font-weight: 600;
}}
QProgressBar::chunk {{ background: {PRIMARY}; border-radius: 8px; }}

QSplitter::handle:horizontal {{
    background: {BORDER_STRONG}; margin: 48px 3px; border-radius: 1px;
}}
QSplitter::handle:horizontal:hover {{ background: {PRIMARY}; }}

QStatusBar {{
    background: {SURFACE}; border-top: 1px solid {BORDER}; color: {MUTED}; padding: 2px 8px;
}}
QStatusBar::item {{ border: none; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle {{ background: {BORDER_STRONG}; border-radius: 3px; }}
QScrollBar::handle:vertical {{ min-height: 32px; }}
QScrollBar::handle:horizontal {{ min-width: 32px; }}
QScrollBar::handle:hover {{ background: {SUBTLE}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
"""


def _palette() -> QPalette:
    p = QPalette()
    colors = {
        QPalette.ColorRole.Window: BG,
        QPalette.ColorRole.WindowText: TEXT,
        QPalette.ColorRole.Base: SURFACE,
        QPalette.ColorRole.AlternateBase: SURFACE_ALT,
        QPalette.ColorRole.Text: TEXT,
        QPalette.ColorRole.PlaceholderText: SUBTLE,
        QPalette.ColorRole.Button: SURFACE,
        QPalette.ColorRole.ButtonText: TEXT_SOFT,
        QPalette.ColorRole.Highlight: PRIMARY,
        QPalette.ColorRole.HighlightedText: "#FFFFFF",
        QPalette.ColorRole.ToolTipBase: TEXT,
        QPalette.ColorRole.ToolTipText: "#FFFFFF",
        QPalette.ColorRole.Link: PRIMARY,
        QPalette.ColorRole.Mid: BORDER,
        QPalette.ColorRole.Midlight: SURFACE_ALT,
        QPalette.ColorRole.Dark: BORDER_STRONG,
        QPalette.ColorRole.Light: SURFACE,
    }
    for color_role, value in colors.items():
        p.setColor(color_role, QColor(value))
    for color_role in (
        QPalette.ColorRole.Text,
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.ButtonText,
    ):
        p.setColor(QPalette.ColorGroup.Disabled, color_role, QColor(SUBTLE))
    return p


def apply_theme(app: QApplication) -> None:
    """Tema terang yang sama di semua OS (tidak mengikuti mode gelap sistem)."""
    app.setStyle("Fusion")
    try:
        app.styleHints().setColorScheme(Qt.ColorScheme.Light)
    except AttributeError:  # Qt < 6.8
        pass
    app.setPalette(_palette())
    font = QFont()
    font.setFamilies(FONT_FAMILIES)
    font.setPointSize(10)
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    app.setFont(font)
    app.setStyleSheet(STYLESHEET)
