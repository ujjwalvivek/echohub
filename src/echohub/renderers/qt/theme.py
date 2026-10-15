"""Rose Pine tokens for the Qt renderer.

Surfaces use Rose Pine's darkest variant (main, base #191724). Accents and the
type scale follow devhub-gpui and helide's Foundation.xaml so the apps read as
one family. Corners are square throughout, like Zed.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from PySide6.QtGui import QColor, QFont, QFontDatabase

# Surfaces, darkest first.
BASE = "#191724"
PANEL = "#1f1d2e"
SURFACE = "#26233a"
HOVER = "#26233a"
SELECTED = "#2f2c45"
BORDER = "#2a2740"
BORDER_STRONG = "#403d52"

# Text.
TEXT = "#e0def4"
SUBTLE = "#908caa"
MUTED = "#6e6a86"

# Rose Pine accents and their roles.
ROSE = "#ebbcba"  # app accent
LOVE = "#eb6f92"  # error
GOLD = "#f6c177"  # warning
FOAM = "#9ccfd8"  # positive / up
PINE = "#31748f"
IRIS = "#c4a7e7"

ACCENT = ROSE
# The red every Windows close button uses; devhub-gpui matches it too.
SUCCESS = FOAM
WARNING = GOLD
ERROR = LOVE

# Series colours for categories (languages), in Rose Pine order.
SERIES = (
    FOAM,
    ROSE,
    IRIS,
    GOLD,
    PINE,
    LOVE,
    "#a3be8c",
    "#d7827e",
    "#56949f",
    "#907aa9",
)

# Contribution heatmap, empty to busiest.
HEAT = ("#2a2740", "#24435a", "#31748f", "#5fa2b4", "#9ccfd8")

# Type scale in pixels (helide: caption 9 … title 27).
CAPTION = 9
SMALL = 10
BODY = 11
MEDIUM = 12
LARGE = 13
DISPLAY = 17
TITLE = 27

# Spacing in pixels. Pages use GAP between blocks and PAGE_X/PAGE_Y as margins;
# cards pad with CARD_X/CARD_Y; list rows with ROW_X/ROW_Y.
GAP = 8
PAGE_X = 16
PAGE_Y = 12
CARD_X = 10
CARD_Y = 8
ROW_X = 6
ROW_Y = 3

_UI_FAMILIES = ("Segoe UI Variable Text", "Segoe UI", "Inter", "Noto Sans")
_MONO_FAMILIES = ("Cascadia Mono", "Consolas", "JetBrains Mono", "DejaVu Sans Mono")


@dataclass(frozen=True, slots=True)
class Fonts:
    ui: str
    mono: str


def _first_installed(candidates: tuple[str, ...], fallback: str) -> str:
    installed = set(QFontDatabase.families())
    return next((family for family in candidates if family in installed), fallback)


def resolve_fonts() -> Fonts:
    """Pick installed families; call after the QApplication exists."""
    return Fonts(
        ui=_first_installed(_UI_FAMILIES, QFont().defaultFamily()),
        mono=_first_installed(_MONO_FAMILIES, "monospace"),
    )


def font(
    family: str, size: int, *, weight: QFont.Weight = QFont.Weight.Normal
) -> QFont:
    value = QFont(family)
    value.setPixelSize(size)
    value.setWeight(weight)
    value.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return value


def color(value: str) -> QColor:
    return QColor(value)


_RANKED: dict[str, str] = {}


def rank_series(names: Iterable[str]) -> None:
    """Hand out SERIES colours in rank order (biggest language first), so the
    categories that matter most get the most distinct colours."""
    _RANKED.clear()
    for index, name in enumerate(names):
        _RANKED[name] = SERIES[index % len(SERIES)]


def series_color(name: str) -> str:
    """The colour for a category, the same in every view."""
    if name == "No code":
        return MUTED
    ranked = _RANKED.get(name)
    if ranked is not None:
        return ranked
    total = sum((index + 1) * ord(char) for index, char in enumerate(name))
    return SERIES[total % len(SERIES)]


def stylesheet(fonts: Fonts) -> str:
    return f"""
    QWidget {{
        background: {BASE};
        color: {TEXT};
        font-family: "{fonts.ui}";
        font-size: {BODY}px;
    }}
    QToolTip {{
        background: {SURFACE}; color: {TEXT};
        border: 1px solid {BORDER_STRONG}; padding: 3px 6px;
    }}
    #TitleBar {{ background: {PANEL}; border-bottom: 1px solid {BORDER}; }}
    #TitleBar QLabel {{ background: transparent; }}
    #TitleText {{ color: {SUBTLE}; font-size: {SMALL}px; font-weight: 600; }}
    #TitlePage {{ color: {MUTED}; font-size: {SMALL}px; }}
    #Sidebar {{ background: {PANEL}; border-right: 1px solid {BORDER}; }}
    #Statusbar {{ background: {PANEL}; border-top: 1px solid {BORDER}; }}
    #Statusbar QLabel {{ background: transparent; color: {MUTED}; font-size: {SMALL}px; }}
    #Statusbar QLabel#Key {{
        font-family: "{fonts.mono}"; font-size: {CAPTION}px; color: {SUBTLE};
        background: {SURFACE}; border: 1px solid {BORDER_STRONG}; padding: 0 4px;
    }}
    #Statusbar QLabel#KeyHint {{ color: {MUTED}; }}
    #Statusbar QLabel#StatusMono {{ font-family: "{fonts.mono}"; font-size: {CAPTION}px; color: {MUTED}; }}
    #StatusDivider {{ background: {BORDER_STRONG}; border: none; }}
    #Brand {{ background: transparent; color: {TEXT}; font-size: {LARGE}px; font-weight: 600; }}
    #PageTitle {{ background: transparent; font-size: {DISPLAY}px; font-weight: 600; }}
    #PageSubtitle {{ background: transparent; color: {MUTED}; font-size: {SMALL}px; }}
    #Card {{ background: {PANEL}; border: 1px solid {BORDER}; }}
    #Card QLabel {{ background: transparent; }}
    #CardTitle {{ color: {SUBTLE}; font-size: {SMALL}px; font-weight: 600; }}
    #CardMeta {{ color: {MUTED}; font-size: {SMALL}px; }}
    #Banner {{ background: {PANEL}; border: 1px solid {BORDER}; border-left: 2px solid {WARNING}; }}
    #Banner[level="error"] {{ border-left-color: {ERROR}; }}
    #Banner QLabel {{ background: transparent; }}
    #StatValue {{ font-size: {DISPLAY}px; font-weight: 600; }}
    #StatLabel {{ color: {MUTED}; font-size: {SMALL}px; }}
    #StatNote {{ color: {SUBTLE}; font-size: {SMALL}px; }}
    #Divider {{ background: {BORDER}; }}
    #Row {{ background: transparent; }}
    #Row QLabel, #Row QWidget {{ background: transparent; }}
    #Row:hover {{ background: {HOVER}; }}
    #Muted {{ color: {MUTED}; }}
    #Subtle {{ color: {SUBTLE}; }}
    #Mono {{ font-family: "{fonts.mono}"; font-size: {SMALL}px; color: {SUBTLE}; }}
    #Good {{ color: {SUCCESS}; }}
    #Warn {{ color: {WARNING}; }}
    #Bad {{ color: {ERROR}; }}
    #Pill, #Row #Pill, #Detail QLabel#Pill {{
        background: {SELECTED}; color: {SUBTLE};
        padding: 0 4px; font-family: "{fonts.mono}"; font-size: {CAPTION}px;
    }}
    QPushButton#Primary {{
        background: {ACCENT}; color: {BASE}; border: none;
        padding: 2px 10px; font-weight: 600;
    }}
    QPushButton#Primary:hover {{ background: #f2cfcd; }}
    QPushButton#Primary:disabled {{ background: {SELECTED}; color: {MUTED}; }}
    QPushButton#Ghost {{
        background: transparent; color: {SUBTLE}; border: 1px solid {BORDER_STRONG};
        padding: 3px 10px;
    }}
    QPushButton#Ghost:hover {{ background: {HOVER}; color: {TEXT}; }}
    QPushButton#Ghost:disabled {{ color: {MUTED}; }}
    QScrollArea {{ border: none; background: transparent; }}
    QScrollBar:vertical {{ background: transparent; width: 7px; margin: 0; }}
    QScrollBar::handle:vertical {{ background: {SELECTED}; min-height: 24px; }}
    QScrollBar::handle:vertical:hover {{ background: {BORDER_STRONG}; }}
    QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{
        background: none; height: 0; width: 0;
    }}
    QTableView {{
        background: {PANEL}; border: 1px solid {BORDER}; gridline-color: transparent;
        outline: 0;
    }}
    /* Table cells and headers are painted in table.py (_Cells, _Header). */
    QTableCornerButton::section {{ background: {PANEL}; border: none; }}
    QListWidget {{ background: {PANEL}; border: 1px solid {BORDER}; outline: 0; }}
    QTreeWidget#KeyTree {{ background: {PANEL}; border: 1px solid {BORDER}; outline: 0; }}
    #ViewerHead {{ background: {PANEL}; border: 1px solid {BORDER}; border-bottom: none; }}
    #ViewerHead QLabel {{ background: transparent; }}
    #KeyPath {{ font-family: "{fonts.mono}"; font-size: {BODY}px; }}
    #KeyKind {{ font-family: "{fonts.mono}"; font-size: {CAPTION}px; color: {MUTED}; }}
    QPlainTextEdit#JsonView {{
        background: {BASE}; border: 1px solid {BORDER}; color: {TEXT};
        font-family: "{fonts.mono}"; font-size: {BODY}px;
    }}
    QScrollBar:horizontal {{ background: transparent; height: 7px; margin: 0; }}
    QScrollBar::handle:horizontal {{ background: {SELECTED}; min-width: 24px; }}
    QScrollBar::handle:horizontal:hover {{ background: {BORDER_STRONG}; }}
    QListWidget::item {{ padding: 2px 6px; color: {SUBTLE}; }}
    QListWidget::item:hover {{ background: {HOVER}; color: {TEXT}; }}
    QListWidget::item:selected {{ background: {SELECTED}; color: {TEXT}; }}
    QPlainTextEdit {{
        background: {PANEL}; border: 1px solid {BORDER}; color: {SUBTLE};
        font-family: "{fonts.mono}"; font-size: {SMALL}px; selection-background-color: {SELECTED};
    }}
    QLineEdit {{
        background: {PANEL}; border: 1px solid {BORDER}; padding: 3px 6px; color: {TEXT};
        selection-background-color: {SELECTED};
    }}
    QLineEdit:focus {{ border-color: {ACCENT}; }}
    QCheckBox {{ background: transparent; color: {SUBTLE}; spacing: 6px; }}
    QCheckBox::indicator {{ width: 10px; height: 10px; border: 1px solid {BORDER_STRONG}; background: {PANEL}; }}
    QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
    QPushButton#Tab {{
        background: transparent; color: {SUBTLE}; border: none;
        border-bottom: 2px solid transparent; padding: 4px 10px;
    }}
    QPushButton#Tab:hover {{ color: {TEXT}; }}
    QPushButton#Tab:checked {{ color: {TEXT}; border-bottom-color: {ACCENT}; }}
    QPushButton#Year {{
        background: transparent; color: {MUTED}; border: none; padding: 0;
        font-family: "{fonts.mono}"; font-size: {CAPTION}px;
    }}
    QPushButton#Year:hover {{ color: {TEXT}; }}
    QPushButton#Year:checked {{ color: {ACCENT}; }}
    #Detail {{ background: {PANEL}; border-left: 1px solid {BORDER}; }}
    #Detail QLabel {{ background: transparent; }}
    #Detail QLabel#DetailTitle {{ font-size: {MEDIUM + 2}px; font-weight: 600; color: {TEXT}; }}
    #Detail QLabel#DetailPath {{ font-family: "{fonts.mono}"; font-size: {CAPTION}px; color: {MUTED}; }}
    #WelcomeTitle {{ color: {TEXT}; font-size: {DISPLAY}px; font-weight: 600; }}
    #WelcomeState {{ color: {TEXT}; font-size: {MEDIUM}px; font-weight: 600; }}
    #WelcomeValue {{ color: {SUBTLE}; font-family: "{fonts.mono}"; font-size: {SMALL}px; }}
    QProgressBar#WelcomeProgress {{ background: {BORDER}; border: none; }}
    #MiniStrip {{ background: {BASE}; border: 1px solid {BORDER}; }}
    #MiniDivider {{ background: {BORDER}; border: none; }}
    #Detail QLabel#MiniCaption {{ color: {MUTED}; font-size: {CAPTION}px; font-weight: 600; }}
    #Detail QLabel#MiniValue {{ color: {TEXT}; font-family: "{fonts.mono}"; font-size: {MEDIUM}px; }}
    #Detail QLabel#FactLabel {{ color: {MUTED}; }}
    #Detail QLabel#FactValue {{ color: {TEXT}; font-family: "{fonts.mono}"; font-size: {SMALL}px; }}
    QProgressBar {{ background: transparent; border: none; }}
    QProgressBar::chunk {{ background: {ACCENT}; }}
    """
