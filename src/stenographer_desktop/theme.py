# SPDX-License-Identifier: GPL-3.0-or-later
"""The fixed dark "Ink rail" theme: tokens, stylesheet, palette, font and rail icons.

The desktop never follows the system light/dark theme; its ground is the
dictation pill's own colour. Everything here is pure except the functions that
take a QApplication, which import PySide6 lazily so this module and its tests
stay importable without Qt.
"""

from __future__ import annotations

import dataclasses
import logging
from importlib.resources import files

from stenographer_desktop.icons import icon_svg

logger = logging.getLogger(__name__)

BRAND_FONT_FILE = "Caveat-wght.ttf"
BRAND_FONT_FAMILY = "Caveat"
BODY_POINT_SIZE = 16
_THEME_PROPERTY = "stenographerTheme"


@dataclasses.dataclass(frozen=True)
class Tokens:
    ground: str = "#18181B"
    panel: str = "#232326"
    stripe: str = "#26262a"
    raised: str = "#2a2a30"
    line: str = "#34343a"
    control_border: str = "#47474f"
    text: str = "#ffffff"
    muted: str = "#a1a1aa"
    accent: str = "#b3c4ff"
    amber: str = "#F59E0B"
    panel_radius: int = 10
    control_radius: int = 8
    rail_item_radius: int = 12
    control_height: int = 36
    rail_width: int = 96
    rail_item: int = 64
    icon_px: int = 20
    quill_px: int = 60
    table_row_height: int = 38
    body_pt: int = BODY_POINT_SIZE
    caption_pt: int = 15
    section_pt: int = 19
    title_pt: int = 25
    brand_pt: int = 33
    headline_pt: int = 45
    rail_label_px: int = 18

    def colours(self) -> tuple[str, ...]:
        return (
            self.ground,
            self.panel,
            self.stripe,
            self.raised,
            self.line,
            self.control_border,
            self.text,
            self.muted,
            self.accent,
            self.amber,
        )


TOKENS = Tokens()


def stylesheet(tokens: Tokens = TOKENS, *, font_family: str = BRAND_FONT_FAMILY) -> str:
    """Render the single application stylesheet, including its typeface."""
    t = tokens
    quoted_family = '"' + font_family.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return f"""
QWidget {{
    font-family: {quoted_family};
    font-size: {t.body_pt}pt;
}}
QMainWindow, QDialog, QWidget#railFrame, QScrollArea, QScrollArea > QWidget > QWidget {{
    background: {t.ground};
    color: {t.text};
}}
QFrame#railLine, QFrame#rule {{
    background: {t.line};
    border: none;
}}
QLabel {{
    color: {t.text};
    background: transparent;
}}
QLabel[role="brand"] {{
    font-size: {t.brand_pt}pt;
    font-weight: 600;
}}
QLabel[role="title"] {{
    font-size: {t.title_pt}pt;
    color: {t.muted};
}}
QLabel[role="caption"] {{
    font-size: {t.caption_pt}pt;
    color: {t.muted};
}}
QLabel[role="section"] {{
    font-size: {t.section_pt}pt;
    color: {t.muted};
    padding-top: 10px;
}}
QLabel[role="headline"] {{
    font-size: {t.headline_pt}pt;
    font-weight: 700;
}}
QLabel[role="muted"] {{
    color: {t.muted};
}}
QLabel[role="dot"] {{
    background: {t.amber};
    border-radius: 4px;
    min-width: 8px;
    max-width: 8px;
    min-height: 8px;
    max-height: 8px;
}}
QLabel[role="dot"][state="off"] {{
    background: {t.muted};
}}
QListWidget#rail {{
    background: transparent;
    border: none;
    outline: 0;
    font-size: {t.rail_label_px}px;
}}
QListWidget#rail::item {{
    color: {t.muted};
    border-radius: {t.rail_item_radius}px;
    padding: 6px 0;
}}
QListWidget#rail::item:hover {{
    background: {t.raised};
}}
QListWidget#rail::item:selected {{
    background: {t.raised};
    color: {t.accent};
}}
QPushButton {{
    background: {t.panel};
    color: {t.text};
    border: 1px solid {t.control_border};
    border-radius: {t.control_radius}px;
    min-height: {t.control_height}px;
    padding: 0 14px;
}}
QPushButton:hover {{
    background: {t.raised};
}}
QPushButton:pressed {{
    background: {t.ground};
}}
QPushButton:disabled {{
    color: {t.muted};
    border-color: {t.line};
}}
QPushButton:focus, QPushButton:default {{
    border-color: {t.accent};
}}
QDialogButtonBox QPushButton {{
    min-width: 88px;
}}
QLineEdit, QSpinBox, QComboBox {{
    background: {t.panel};
    color: {t.text};
    border: 1px solid {t.control_border};
    border-radius: {t.control_radius}px;
    min-height: {t.control_height}px;
    padding: 0 10px;
    selection-background-color: {t.raised};
    selection-color: {t.text};
}}
QTextEdit {{
    background: {t.panel};
    color: {t.text};
    border: 1px solid {t.control_border};
    border-radius: {t.panel_radius}px;
    padding: 6px 10px;
    selection-background-color: {t.raised};
    selection-color: {t.text};
}}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QTextEdit:focus {{
    border-color: {t.accent};
}}
QSpinBox::up-button, QSpinBox::down-button {{
    subcontrol-origin: border;
    width: 18px;
    border: none;
    background: transparent;
}}
QSpinBox::up-arrow, QSpinBox::down-arrow {{
    width: 8px;
    height: 8px;
}}
QComboBox::drop-down {{
    width: 24px;
    border: none;
    background: transparent;
}}
QComboBox::down-arrow {{
    width: 8px;
    height: 8px;
}}
QComboBox QAbstractItemView {{
    background: {t.panel};
    color: {t.text};
    border: 1px solid {t.control_border};
    border-radius: {t.control_radius}px;
    selection-background-color: {t.raised};
    selection-color: {t.text};
    outline: 0;
}}
QCheckBox {{
    color: {t.text};
    spacing: 8px;
}}
QCheckBox::indicator {{
    width: 18px;
    height: 18px;
    border: 1px solid {t.control_border};
    border-radius: 4px;
    background: {t.panel};
}}
QCheckBox::indicator:checked {{
    background: {t.accent};
    border-color: {t.accent};
}}
QCheckBox::indicator:focus {{
    border-color: {t.accent};
}}
QTabWidget::pane {{
    background: {t.panel};
    border: 1px solid {t.line};
    border-radius: {t.panel_radius}px;
    top: -1px;
}}
QTabBar {{
    outline: 0;
}}
QTabBar::tab {{
    background: transparent;
    color: {t.muted};
    padding: 8px 14px;
    border-bottom: 2px solid transparent;
}}
QTabBar::tab:hover {{
    color: {t.text};
}}
QTabBar::tab:selected {{
    color: {t.text};
    border-bottom: 2px solid {t.accent};
}}
QTableWidget {{
    background: {t.panel};
    alternate-background-color: {t.stripe};
    color: {t.text};
    gridline-color: {t.line};
    border: 1px solid {t.line};
    border-radius: {t.panel_radius}px;
    outline: 0;
}}
QTableWidget::item {{
    padding: 4px 8px;
    border: none;
}}
QTableWidget::item:selected {{
    background: {t.raised};
    color: {t.text};
}}
QHeaderView {{
    background: {t.panel};
    border: none;
}}
QHeaderView::section {{
    background: {t.panel};
    color: {t.muted};
    border: none;
    border-bottom: 1px solid {t.line};
    padding: 6px 8px;
}}
QHeaderView::section:first {{
    border-top-left-radius: {t.panel_radius}px;
}}
QHeaderView::section:last {{
    border-top-right-radius: {t.panel_radius}px;
}}
QTableCornerButton::section {{
    background: {t.panel};
    border: none;
}}
QScrollBar:vertical {{
    background: {t.ground};
    width: 10px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {t.control_border};
    border-radius: 5px;
    min-height: 24px;
}}
QScrollBar:horizontal {{
    background: {t.ground};
    height: 10px;
    margin: 0;
}}
QScrollBar::handle:horizontal {{
    background: {t.control_border};
    border-radius: 5px;
    min-width: 24px;
}}
QScrollBar::add-line, QScrollBar::sub-line {{
    width: 0;
    height: 0;
}}
QScrollBar::add-page, QScrollBar::sub-page {{
    background: none;
}}
QStatusBar {{
    background: {t.ground};
    color: {t.muted};
    border-top: 1px solid {t.line};
}}
QStatusBar::item {{
    border: none;
}}
QMessageBox {{
    background: {t.ground};
}}
QMessageBox QLabel {{
    color: {t.text};
}}
QToolTip {{
    background: {t.panel};
    color: {t.text};
    border: 1px solid {t.control_border};
    padding: 4px 8px;
}}
"""


def apply_brand_font(app) -> str:
    """Register the bundled Caveat face and return its actual family name.

    When the asset cannot be registered, the stylesheet uses the platform font
    so a broken install still shows a usable window.
    """
    from PySide6.QtGui import QFontDatabase

    path = files("stenographer") / "assets" / "fonts" / BRAND_FONT_FILE
    font_id = QFontDatabase.addApplicationFont(str(path))
    families = QFontDatabase.applicationFontFamilies(font_id) if font_id >= 0 else []
    if not families:
        logger.warning("desktop: brand_font_unavailable file=%s", BRAND_FONT_FILE)
        return app.font().family()
    return families[0]


def palette(tokens: Tokens = TOKENS):
    """Palette matching the stylesheet, so painted widgets agree with styled ones."""
    from PySide6.QtGui import QColor, QPalette

    role = QPalette.ColorRole
    group = QPalette.ColorGroup
    p = QPalette()
    for colour_role, value in (
        (role.Window, tokens.ground),
        (role.Base, tokens.panel),
        (role.AlternateBase, tokens.stripe),
        (role.Button, tokens.panel),
        (role.WindowText, tokens.text),
        (role.Text, tokens.text),
        (role.ButtonText, tokens.text),
        (role.BrightText, tokens.text),
        (role.PlaceholderText, tokens.muted),
        (role.Highlight, tokens.raised),
        (role.HighlightedText, tokens.text),
        (role.ToolTipBase, tokens.panel),
        (role.ToolTipText, tokens.text),
        (role.Link, tokens.accent),
        (role.Mid, tokens.line),
        (role.Dark, tokens.line),
        (role.Shadow, tokens.line),
        (role.Light, tokens.control_border),
        (role.Midlight, tokens.control_border),
    ):
        p.setColor(colour_role, QColor(value))
    for disabled_role in (role.WindowText, role.Text, role.ButtonText):
        p.setColor(group.Disabled, disabled_role, QColor(tokens.muted))
    return p


def navigation_icon(name: str, tokens: Tokens = TOKENS):
    """Muted icon normally, accent while the rail item is selected; 1x and 2x pixmaps."""
    from PySide6.QtGui import QIcon, QPixmap

    icon = QIcon()
    for colour, modes in (
        (tokens.muted, (QIcon.Mode.Normal,)),
        (tokens.accent, (QIcon.Mode.Selected, QIcon.Mode.Active)),
    ):
        for ratio in (1, 2):
            pixmap = QPixmap()
            pixmap.loadFromData(icon_svg(name, colour, tokens.icon_px * ratio).encode(), "SVG")
            pixmap.setDevicePixelRatio(ratio)
            for mode in modes:
                icon.addPixmap(pixmap, mode)
    return icon


def apply_theme(app) -> None:
    """Style, register the font, and set the palette and stylesheet once.

    Fusion is required before any widget exists: platform styles ignore the
    palette for app-owned message boxes and combo popups. Native system dialogs
    keep their host rendering and font.
    """
    if app.property(_THEME_PROPERTY):
        return
    app.setStyle("Fusion")
    font_family = apply_brand_font(app)
    app.setPalette(palette())
    app.setStyleSheet(stylesheet(font_family=font_family))
    app.setProperty(_THEME_PROPERTY, True)
