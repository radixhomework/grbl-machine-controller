"""Application theme: palette + stylesheet from the radixhomework.github.io chart.

Chart (assets/css/style.css of radixhomework.github.io):
  root-black  #1E211C   text
  ivory       #FDFAF3   surfaces
  moss green  #4D5947   primary
  earth brown #76604E   muted text
  copper      #9A7656   accent
  faded pink  #8A5E61   radish / alerts
  parchment   #D8D0BD   panel fill
  background  #FCFCFA
  border      rgba(30, 33, 28, 0.20)
  display font: Cormorant Garamond (Georgia fallback); body: Source Sans 3 (Segoe UI fallback)
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

ROOT_BLACK = "#1E211C"
IVORY = "#FDFAF3"
MOSS = "#4D5947"
EARTH_BROWN = "#76604E"
COPPER = "#9A7656"
RADISH = "#8A5E61"
PARCHMENT = "#D8D0BD"
BACKGROUND = "#FCFCFA"
BORDER = "rgba(30, 33, 28, 0.20)"

BODY_FONT = '"Source Sans 3", "Segoe UI", Arial, sans-serif'
DISPLAY_FONT = '"Cormorant Garamond", Georgia, serif'

APP_QSS = f"""
QGroupBox {{
    background: {IVORY};
    border: 1px solid {BORDER};
    margin-top: 12px;
    padding: 8px 4px 4px 4px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 8px;
    padding: 0 4px;
    color: {MOSS};
    font-family: {DISPLAY_FONT};
    font-size: 15px;
    font-weight: 600;
    letter-spacing: 1px;
}}
QPushButton {{
    background: {IVORY};
    border: 1px solid {BORDER};
    padding: 4px 10px;
}}
QPushButton:hover {{
    border-color: {COPPER};
    color: {COPPER};
}}
QPushButton:pressed {{
    background: {PARCHMENT};
}}
QPushButton:checked {{
    background: {MOSS};
    color: {IVORY};
    border-color: {MOSS};
}}
QPushButton:disabled {{
    color: rgba(30, 33, 28, 0.35);
    border-color: rgba(30, 33, 28, 0.12);
}}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {IVORY};
    border: 1px solid {BORDER};
    padding: 2px 4px;
}}
QComboBox::drop-down {{ border: none; width: 16px; }}
QComboBox QAbstractItemView {{
    background: {IVORY};
    border: 1px solid {BORDER};
    selection-background-color: {MOSS};
    selection-color: {IVORY};
}}
QTreeWidget, QTreeView {{
    background: {IVORY};
    alternate-background-color: rgba(216, 208, 189, 0.35);
    border: 1px solid {BORDER};
}}
QHeaderView::section {{
    background: {PARCHMENT};
    border: none;
    border-right: 1px solid {BORDER};
    padding: 4px;
    color: {ROOT_BLACK};
    font-weight: 600;
}}
QProgressBar {{
    border: 1px solid {BORDER};
    background: {IVORY};
    text-align: center;
    max-height: 14px;
}}
QProgressBar::chunk {{ background: {MOSS}; }}
QMenuBar {{ background: {IVORY}; border-bottom: 1px solid {BORDER}; }}
QMenuBar::item {{ padding: 4px 10px; }}
QMenuBar::item:selected {{ background: {PARCHMENT}; }}
QMenu {{ background: {IVORY}; border: 1px solid {BORDER}; }}
QMenu::item:selected {{ background: {MOSS}; color: {IVORY}; }}
QStatusBar {{
    background: {IVORY};
    border-top: 1px solid {BORDER};
    color: {EARTH_BROWN};
}}
QSplitter::handle {{ background: {PARCHMENT}; }}
QSplitter::handle:hover {{ background: {COPPER}; }}
QScrollBar:vertical {{ background: transparent; width: 10px; }}
QScrollBar::handle:vertical {{ background: {PARCHMENT}; min-height: 24px; }}
QScrollBar::handle:vertical:hover {{ background: {COPPER}; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{
    height: 0; width: 0; background: none; border: none;
}}
QToolTip {{
    background: {IVORY};
    color: {ROOT_BLACK};
    border: 1px solid {MOSS};
    padding: 3px;
}}
"""


def apply_theme(app: QApplication) -> None:
    """Apply the radixhomework chart: warm palette + control stylesheet."""
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(BACKGROUND))
    palette.setColor(QPalette.WindowText, QColor(ROOT_BLACK))
    palette.setColor(QPalette.Base, QColor(IVORY))
    palette.setColor(QPalette.AlternateBase, QColor(PARCHMENT))
    palette.setColor(QPalette.Text, QColor(ROOT_BLACK))
    palette.setColor(QPalette.Button, QColor(IVORY))
    palette.setColor(QPalette.ButtonText, QColor(ROOT_BLACK))
    palette.setColor(QPalette.Highlight, QColor(MOSS))
    palette.setColor(QPalette.HighlightedText, QColor(IVORY))
    palette.setColor(QPalette.ToolTipBase, QColor(IVORY))
    palette.setColor(QPalette.ToolTipText, QColor(ROOT_BLACK))
    palette.setColor(QPalette.PlaceholderText, QColor(EARTH_BROWN))
    palette.setColor(QPalette.Mid, QColor(PARCHMENT))
    palette.setColor(QPalette.Dark, QColor(PARCHMENT))
    app.setPalette(palette)
    app.setFont(QFont("Source Sans 3", 10))   # falls back to the default family if absent
    app.setStyleSheet(APP_QSS)
