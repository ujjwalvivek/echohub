"""Rose Pine colour tokens shared by the desktop and terminal renderers.

Surfaces use Rose Pine's darkest variant (main, base #191724). No Qt here, so
the terminal renderer can use the palette without loading PySide6.
"""

from __future__ import annotations

from collections.abc import Iterable

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


def blend(a: str, b: str, t: float) -> str:
    """Mix two #rrggbb colours: t=0 gives a, t=1 gives b."""
    av = [int(a[i : i + 2], 16) for i in (1, 3, 5)]
    bv = [int(b[i : i + 2], 16) for i in (1, 3, 5)]
    t = max(0.0, min(1.0, t))
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(av, bv))
