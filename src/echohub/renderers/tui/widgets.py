"""Building blocks for TUI pages: sections, stat strips, bars, charts, grids.

Every function returns styled lines (see ``style``) no wider than asked.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime

from ... import palette as P
from ...formatting import compact
from ...today import Attention, HeatmapDay
from .style import fit, paint, spread, width

PRIVATE = "▪"
_LEVELS = " ▁▂▃▄▅▆▇█"


def private_mark(private: bool) -> str:
    return paint(PRIVATE + " ", P.MUTED) if private else "  "


def section(title: str, meta: str, cells: int) -> str:
    """A caption, a rule, and the meta at the right end."""
    left = paint(title, P.SUBTLE, bold=True) + " "
    right = (" " + paint(meta, P.MUTED)) if meta else ""
    rule = max(0, cells - width(left) - width(right))
    if rule < 2:
        return fit(left + right, cells)
    return left + paint("─" * rule, P.BORDER_STRONG) + right


def page_title(title: str, subtitle: str, cells: int, right: str = "") -> str:
    left = paint(title, P.TEXT, bold=True) + "  " + paint(subtitle, P.MUTED)
    return spread(left, right, cells) if right else fit(left, cells)


def keycap(key: str) -> str:
    return paint(f" {key} ", P.SUBTLE, back=P.SURFACE)


def pill(text: str, colour: str = P.SUBTLE) -> str:
    return paint(f" {text} ", colour, back=P.SURFACE) if text else ""


def banner(item: Attention, cells: int) -> str:
    colour = P.LOVE if item.level == "error" else P.GOLD
    line = paint("▌", colour) + " " + paint(item.title, P.TEXT)
    if item.detail:
        line += "  " + paint(item.detail, P.MUTED)
    return fit(line, cells)


@dataclass(slots=True)
class Stat:
    caption: str
    value: str
    note: str = ""
    tone: str = P.SUBTLE


def stat_strip(stats: Sequence[Stat], cells: int) -> list[str]:
    """Headline numbers side by side: caption, value, note; │ between cells."""
    if not stats:
        return []
    divider = paint(" │ ", P.BORDER_STRONG)
    each = max(8, (cells - 3 * (len(stats) - 1)) // len(stats))
    rows = (
        [paint(stat.caption, P.MUTED) for stat in stats],
        [paint(stat.value, P.TEXT, bold=True) for stat in stats],
        [paint(stat.note, stat.tone) for stat in stats],
    )
    lines = [divider.join(fit(cell, each) for cell in row) for row in rows]
    if not any(stat.note for stat in stats):
        lines.pop()
    return [fit(line, cells) for line in lines]


def hbar(share: float, cells: int, colour: str, track: str = P.BORDER) -> str:
    """A thin line bar on a dim track, like the desktop app's 4 px bars.
    Anything above zero shows at least one cell."""
    share = max(0.0, min(1.0, share))
    filled = min(cells, max(1 if share > 0 else 0, round(share * cells)))
    return paint("━" * filled, colour) + paint("━" * (cells - filled), track)


def diff_bar(added: int, removed: int, peak: int, half: int = 5) -> str:
    """−removed, a love bar growing left of a centre tick, a foam bar growing
    right, +added. Log scale, full at 5,000 lines, like the desktop app."""
    top = min(max(peak, 1), 5000)
    scale = 1 / math.log1p(top)

    def cells(value: int) -> int:
        if value <= 0:
            return 0
        return min(half, max(1, round(half * math.log1p(value) * scale)))

    left, right = cells(removed), cells(added)
    return (
        paint(f"−{_short(removed)}".rjust(6), P.LOVE if removed else P.MUTED)
        + " "
        + " " * (half - left)
        + paint("━" * left, P.LOVE)
        + paint("│", P.BORDER_STRONG)
        + paint("━" * right, P.FOAM)
        + " " * (half - right)
        + " "
        + paint(f"+{_short(added)}".ljust(6), P.FOAM if added else P.MUTED)
    )


DIFF_WIDTH = 6 + 1 + 5 + 1 + 5 + 1 + 6


def _short(value: int) -> str:
    return compact(value)


def age_tone(value: str) -> str:
    """TEXT under a day old, SUBTLE under 30 days, MUTED after that."""
    try:
        when = datetime.fromisoformat(value)
    except ValueError:
        return P.MUTED
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    days = (datetime.now(UTC) - when).total_seconds() / 86400
    if days < 1:
        return P.TEXT
    if days < 30:
        return P.SUBTLE
    return P.MUTED


def column_chart(
    values: Sequence[int | None],
    labels: Sequence[str],
    cells: int,
    rows: int,
    colour: str,
) -> list[str]:
    """Thin vertical bars filling ``cells`` × ``rows``: the peak's value on
    top, then the bars, then the first, middle and last labels. Small marks
    with clear gaps; missing values (None) stay blank."""
    if rows < 3 or not values:
        return []
    height = rows - 2
    step = max(1, cells // len(values))
    bar = 2 if step >= 4 else 1
    shown = list(values)[-(cells // step) :]
    shown_labels = list(labels)[-len(shown) :]
    peak = max((value for value in shown if value is not None), default=0)
    scale = peak or 1
    peak_index = max(range(len(shown)), key=lambda i: (shown[i] or 0, i))
    pad = (step - bar) // 2

    label = [" "] * cells
    if peak:
        text = compact(peak)
        centre = peak_index * step + pad + bar // 2
        start = max(0, min(cells - len(text), centre - len(text) // 2))
        label[start : start + len(text)] = list(text)
    lines = [paint("".join(label).rstrip(), P.TEXT)]
    for row in range(height, 0, -1):
        out: list[str] = []
        for value in shown:
            if value is None:
                out.append(" " * step)
                continue
            fill = max(0.0, min(8.0, value / scale * height * 8 - (row - 1) * 8))
            if row == 1 and value > 0 and fill < 1:
                fill = 1
            if row == 1 and value == 0:
                mark = paint("▁" * bar, P.BORDER_STRONG)
            else:
                mark = paint(_LEVELS[int(fill)] * bar, colour)
            out.append(" " * pad + mark + " " * (step - bar - pad))
        lines.append(fit("".join(out), cells))
    lines.append(_axis(shown_labels, step, cells, pad + bar // 2))
    return lines


def _axis(labels: Sequence[str], step: int, cells: int, centre: int) -> str:
    """First, middle and last label, each centred under its bar."""
    if not labels:
        return ""
    line = [" "] * cells
    for pick in sorted({0, len(labels) // 2, len(labels) - 1}):
        text = labels[pick]
        start = pick * step + centre - len(text) // 2
        start = max(0, min(cells - len(text), start))
        if all(char == " " for char in line[max(0, start - 1) : start + len(text) + 1]):
            line[start : start + len(text)] = list(text)
    return paint("".join(line).rstrip(), P.MUTED)


def heat_levels(days: Sequence[HeatmapDay]) -> list[int]:
    """Quartiles of active days, as GitHub does, so one huge day doesn't wash
    out the rest."""
    nonzero = sorted(day.count for day in days if day.count > 0)
    if not nonzero:
        return []
    return [
        nonzero[min(len(nonzero) - 1, int(len(nonzero) * q))] for q in (0.25, 0.5, 0.75)
    ]


def _level(count: int, thresholds: list[int]) -> int:
    if count <= 0 or not thresholds:
        return 0
    return 1 + sum(count > threshold for threshold in thresholds)


def heatmap(
    days: Sequence[HeatmapDay], today: date, cells: int, *, wide: bool | None = None
) -> list[str]:
    """Weeks as columns, Sunday on top, newest weeks kept when space runs out.

    Two cells per week (a gap after each square) when they all fit, else one.
    Eight lines: months, then the seven weekdays.
    """
    weeks = [list(days[i : i + 7]) for i in range(0, len(days), 7)]
    label = 4
    room = max(1, cells - label)
    if wide is None:
        wide = len(weeks) * 2 <= room
    step = 2 if wide else 1
    weeks = weeks[-(room // step) :]
    thresholds = heat_levels([day for week in weeks for day in week])
    months = [" "] * (len(weeks) * step)
    last_month = 0
    for column, week in enumerate(weeks):
        first = next((day for day in week if day.count >= 0), None)
        if first is None:
            continue
        if first.day.month != last_month and first.day.day <= 7:
            name = first.day.strftime("%b")
            start = column * step
            if all(c == " " for c in months[max(0, start - 1) : start + 3]):
                months[start : start + 3] = list(name)[: len(months) - start]
            last_month = first.day.month
    lines = [" " * label + paint("".join(months)[: len(weeks) * step], P.MUTED)]
    names = {1: "Mon", 3: "Wed", 5: "Fri"}
    for row in range(7):
        out = [paint(names.get(row, "").ljust(label), P.MUTED)]
        for week in weeks:
            day = week[row] if row < len(week) else None
            if day is None or day.count < 0 or day.day > today:
                out.append(" " * step)
                continue
            colour = P.HEAT[_level(day.count, thresholds)]
            mark = paint("■", P.ROSE if day.day == today else colour)
            out.append(mark + (" " if wide else ""))
        lines.append(fit("".join(out), cells))
    return lines


def heat_legend() -> str:
    return (
        paint("Less ", P.MUTED)
        + "".join(paint("■", shade) + " " for shade in P.HEAT)
        + paint("More", P.MUTED)
    )


def scrollbar(total: int, offset: int, rows: int) -> list[str]:
    """A one-cell bar: track blank, thumb ▐ where the view sits."""
    if total <= rows or rows <= 0:
        return [" "] * rows
    size = max(1, round(rows * rows / total))
    top = round((rows - size) * offset / max(1, total - rows))
    return [
        paint("▐", P.BORDER_STRONG) if top <= row < top + size else " "
        for row in range(rows)
    ]
