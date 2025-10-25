from __future__ import annotations

import json
import os
import select
import shutil
import sys
import threading
import time
from collections.abc import Callable
from contextlib import contextmanager
from typing import final

from .. import theme as T
from ..engine import EchopointEngine, ProgressUpdate
from ..formatting import bar, compact, human_bytes, human_kb, relative_time, short_date
from ..models import DashboardState, Project

ESC = "\x1b"
RESET = "\x1b[0m"
BOLD = "\x1b[1m"
TEXT = T.ansi(T.TEXT)
SUB = T.ansi(T.SUBTEXT0)
MUTED = T.ansi(T.OVERLAY1)
BLUE = T.ansi(T.BLUE)
GREEN = T.ansi(T.GREEN)
RED = T.ansi(T.RED)
PEACH = T.ansi(T.PEACH)
MAUVE = T.ansi(T.MAUVE)
SURFACE = T.ansi(T.SURFACE1)


def _plain(text: str) -> str:
    import re

    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def _len(text: str) -> int:
    return len(_plain(text))


def _fit(text: str, width: int, *, bg: str | None = None) -> str:
    if width <= 0:
        return ""
    plain = _plain(text)
    if len(plain) > width:
        plain = plain[: max(0, width - 1)] + "…"
        prefix = bg or ""
        return prefix + plain + RESET
    prefix = bg or ""
    return prefix + text + " " * (width - len(plain)) + RESET


def _ansi_color(hex_color: str) -> str:
    return T.ansi(hex_color)


@contextmanager
def _raw_terminal():
    if os.name == "nt" or not sys.stdin.isatty():
        yield
        return
    import termios
    import tty

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        yield
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _read_key() -> str | None:
    if os.name == "nt":
        import msvcrt

        if not msvcrt.kbhit():
            return None
        ch = msvcrt.getwch()
        if ch in ("\x00", "\xe0"):
            nxt = msvcrt.getwch()
            return {"H": "up", "P": "down", "K": "left", "M": "right"}.get(nxt, nxt)
        return ch
    if not sys.stdin.isatty():
        return None
    ready, _, _ = select.select([sys.stdin], [], [], 0)
    if not ready:
        return None
    ch = sys.stdin.read(1)
    if ch == ESC:
        ready, _, _ = select.select([sys.stdin], [], [], 0.01)
        if ready:
            seq = sys.stdin.read(2)
            return {"[A": "up", "[B": "down", "[C": "right", "[D": "left"}.get(
                seq, ESC + seq
            )
    return ch


ProjectColumn = tuple[str, int, Callable[[Project], str]]


@final
class TuiApp:
    views: tuple[str, ...] = (
        "PULSE",
        "PROJECTS",
        "CONSTELLATION",
        "ACTIVITY",
        "ECOLOGY",
        "CONTRIBUTIONS",
        "SOURCES",
        "INSPECTOR",
    )

    def __init__(self, engine: EchopointEngine):
        self.engine = engine
        self.view = 0
        self.running = True
        self.progress: ProgressUpdate | None = None
        self.message = ""
        self._worker: threading.Thread | None = None
        self._indeterminate = 0
        self.offsets: dict[str, int] = {
            "projects": 0,
            "project_col": 0,
            "activity": 0,
            "ecology_left": 0,
            "ecology_right": 0,
            "sources": 0,
            "inspector_left": 0,
            "inspector_right": 0,
            "contrib": -1,
        }
        self.const_index: int = 0
        self.source_tab: int = 0
        self.inspector_pane = 0
        self.ecology_pane = 0
        self._dirty = True

    def _redraw(self) -> None:
        self._dirty = True

    def _background(self, action: Callable[[], object], label: str) -> None:
        if self._worker and self._worker.is_alive():
            return
        self.message = label

        def run():
            try:
                action()
                self.message = "Ready"
            except Exception as exc:  # noqa: BLE001 > background TUI task boundary
                self.message = f"ERROR: {exc}"
            finally:
                self.progress = None
                self._redraw()

        self._worker = threading.Thread(target=run, daemon=True)
        self._worker.start()

    def _set_progress(self, u: ProgressUpdate) -> None:
        self.progress = u
        self._redraw()

    def refresh(self) -> None:
        self._background(
            lambda: self.engine.refresh(self._set_progress), "Refreshing source"
        )

    def check(self) -> None:
        self._background(
            lambda: self.engine.sync(progress=self._set_progress),
            "Checking for changes",
        )

    def _header(self, width: int, state: DashboardState) -> list[str]:
        tabs = "  ".join(
            f"{BOLD}{BLUE if i == self.view else MUTED}{i + 1}:{name}{RESET}"
            for i, name in enumerate(self.views)
        )
        return [
            _fit(
                f"{BOLD}{TEXT}ECHOHUB | TELEMETRY DECK{RESET}   "
                f"{MUTED}snapshot {relative_time(state.meta.last_updated)} "
                f"· {state.raw_key_count} keys{RESET}",
                width,
            ),
            _fit(tabs, width),
            _fit(SURFACE + "─" * width + RESET, width),
        ]

    def _metrics(self, state: DashboardState, width: int) -> list[str]:
        t = state.analytics.totals
        vals = [
            ("PROJECTS", compact(t.get("projects", 0))),
            ("COMMITS", compact(t.get("commits", 0))),
            ("CODE", human_bytes(t.get("language_bytes", 0))),
            ("CHURN", compact(t.get("recent_churn", 0))),
            ("ARTIFACTS", compact(t.get("packages", 0))),
            ("STATUS", f"{sum(s.ok for s in state.statuses)}/{len(state.statuses)}"),
        ]
        cell = max(14, width // len(vals))
        top = ""
        bottom = ""
        for k, v in vals:
            top += f"{MUTED}{k:<{cell}}{RESET}"
            bottom += f"{BOLD}{TEXT}{v:<{cell}}{RESET}"
        return [_fit(top, width), _fit(bottom, width)]

    def _pulse(self, state: DashboardState, width: int, height: int) -> list[str]:
        lines = self._metrics(state, width) + [
            "",
            f"{BOLD}{TEXT}RECENTLY ACTIVE PROJECTS{RESET}  {MUTED}exact snapshot values · no synthetic activity metric{RESET}",
        ]
        head = (
            f"{'PROJECT':20} {'LAST PUSH':10} {'CACHED':>6} {'CHURN':>8} {'RELEASE':14}"
        )
        lines.append(MUTED + head + RESET)
        for p in sorted(state.projects, key=lambda p: p.pushed_at or "", reverse=True)[
            : max(4, height - 13)
        ]:
            churn = sum(c.churn for c in p.commits)
            lines.append(
                f"{TEXT}{p.alias[:20]:20}{RESET} {SUB}{relative_time(p.pushed_at):10} {len(p.commits):6} {compact(churn):>8} {(p.latest_release.tag if p.latest_release else '-')[:14]:14}{RESET}"
            )
        if state.statuses and len(lines) < height - 3:
            lines += [
                "",
                f"{BOLD}{TEXT}STATUS{RESET}  "
                + "  ".join(
                    f"{GREEN if s.ok else RED}{'●' if s.ok else '×'}{RESET} {s.label} {MUTED}{f'{s.latency_ms:.0f}ms' if s.latency_ms is not None else '-'}{RESET}"
                    for s in state.statuses
                ),
            ]
        return lines

    PROJECT_COLUMNS: tuple[ProjectColumn, ...] = (
        ("LANG", 12, lambda p: p.dominant_language),
        ("CODE BYTES", 11, lambda p: human_bytes(p.language_bytes)),
        ("REPO SIZE", 10, lambda p: human_kb(p.size_kb)),
        ("COMMITS", 8, lambda p: compact(p.commit_count)),
        ("STARS", 6, lambda p: str(p.stars)),
        ("FORKS", 6, lambda p: str(p.forks)),
        ("ISSUES", 6, lambda p: str(p.open_issues)),
        ("WATCH", 6, lambda p: str(p.watchers)),
        ("TOP CONT", 8, lambda p: str(len(p.contributors))),
        ("CHURN", 8, lambda p: compact(sum(c.churn for c in p.commits))),
        ("RELEASES", 8, lambda p: str(len(p.releases))),
        ("TAGS", 5, lambda p: str(len(p.tags))),
        ("DEPLOYS", 7, lambda p: str(len(p.deployments))),
        ("LATEST", 13, lambda p: p.latest_release.tag if p.latest_release else "-"),
        ("PUSHED", 10, lambda p: relative_time(p.pushed_at)),
        ("LICENSE", 8, lambda p: p.license_name or "-"),
        ("TOPICS", 28, lambda p: ",".join(p.topics) or "-"),
    )

    def _projects(self, state: DashboardState, width: int, height: int) -> list[str]:
        lines = [
            f"{BOLD}{TEXT}PROJECT MATRIX{RESET}  {MUTED}h/l horizontal columns · j/k rows · code bytes are GitHub language bytes, not LOC{RESET}",
            "",
        ]
        fixed = 22
        avail = max(20, width - fixed)
        start = self.offsets["project_col"]
        visible = []
        used = 0
        for col in self.PROJECT_COLUMNS[start:]:
            w = col[1] + 1
            if used + w > avail and visible:
                break
            visible.append(col)
            used += w
        header = f"{'PROJECT':20}  " + " ".join(f"{c[0]:<{c[1]}}" for c in visible)
        lines.append(MUTED + header + RESET)
        rows = sorted(state.projects, key=lambda p: p.commit_count, reverse=True)
        off = min(self.offsets["projects"], max(0, len(rows) - 1))
        self.offsets["projects"] = off
        visible_rows = max(1, height - 10)
        for idx, p in enumerate(rows[off : off + visible_rows]):
            marker = BLUE + "›" + RESET if idx == 0 else " "
            row = f"{marker}{TEXT}{p.alias[:19]:19}{RESET}  " + " ".join(
                f"{str(c[2](p))[: c[1]]:<{c[1]}}" for c in visible
            )
            lines.append(row)
        if rows:
            p = rows[off]
            top = p.contributors[0].login if p.contributors else "-"
            mix = ", ".join(
                f"{k} {v / max(1, p.language_bytes) * 100:.0f}%"
                for k, v in sorted(
                    p.languages.items(), key=lambda kv: kv[1], reverse=True
                )[:4]
            )
            lines += [
                "",
                f"{BOLD}{TEXT}{p.full_name or p.alias}{RESET}  {MUTED}{p.description or 'No description'}{RESET}",
                f"{MUTED}languages{RESET} {SUB}{mix or '-'}{RESET}   {MUTED}top contributor{RESET} {SUB}{top}{RESET}   {MUTED}branch{RESET} {SUB}{p.default_branch or '-'}{RESET}",
            ]
        lines.append(
            f"{MUTED}columns {start + 1}-{start + len(visible)} of {len(self.PROJECT_COLUMNS)} · selected row {off + 1} of {len(rows)}{RESET}"
        )
        return lines

    def _constellation(
        self, state: DashboardState, width: int, height: int
    ) -> list[str]:
        projects = sorted(state.projects, key=lambda p: p.alias.lower())
        if not projects:
            return ["No project data"]
        self.const_index = max(0, min(self.const_index, len(projects) - 1))
        p = projects[self.const_index]
        edges = sorted(
            [
                e
                for e in state.analytics.constellation_edges
                if e.source == p.alias or e.target == p.alias
            ],
            key=lambda e: e.similarity,
            reverse=True,
        )
        lines = [
            f"{BOLD}{TEXT}CONSTELLATION EXPLORER{RESET}  {MUTED}j/k select project · relationships are language-mix similarity{RESET}",
            "",
        ]
        if width >= 100:
            leftw = min(42, width // 3)
            rightw = width - leftw - 3
            plist = []
            start = max(0, self.const_index - (height - 9) // 2)
            for i, q in enumerate(projects[start : start + max(5, height - 8)], start):
                plist.append(
                    f"{BLUE if i == self.const_index else SUB}{'›' if i == self.const_index else ' '} {q.alias[: leftw - 5]}{RESET}"
                )
            detail = [
                f"{BOLD}{TEXT}{p.alias}{RESET}  {MUTED}{p.dominant_language}{RESET}",
                f"{SUB}{(p.description or 'No description')[:rightw]}{RESET}",
                f"{MUTED}code bytes{RESET} {TEXT}{human_bytes(p.language_bytes)}{RESET}   {MUTED}repo size{RESET} {TEXT}{human_kb(p.size_kb)}{RESET}   {MUTED}commits{RESET} {TEXT}{compact(p.commit_count)}{RESET}",
                f"{MUTED}stars/forks/issues{RESET} {TEXT}{p.stars}/{p.forks}/{p.open_issues}{RESET}   {MUTED}last push{RESET} {TEXT}{relative_time(p.pushed_at)}{RESET}",
                "",
                f"{BOLD}{TEXT}NEAREST LANGUAGE MIXES{RESET}",
            ]
            for e in edges[: max(3, height - 13)]:
                other = e.target if e.source == p.alias else e.source
                detail.append(
                    f"{other[:24]:24} {bar(e.similarity, 18, full='█', empty='░')} {e.similarity * 100:4.0f}%"
                )
            for i in range(max(len(plist), len(detail))):
                lines.append(
                    f"{_fit(plist[i] if i < len(plist) else '', leftw)} {MUTED}│{RESET} {_fit(detail[i] if i < len(detail) else '', rightw)}"
                )
        else:
            lines += [
                f"{BOLD}{p.alias}{RESET} · {p.dominant_language} · {human_bytes(p.language_bytes)} · {compact(p.commit_count)} commits",
                SUB + (p.description or "") + RESET,
                "",
                BOLD + "NEAREST LANGUAGE MIXES" + RESET,
            ]
            for e in edges[: max(3, height - 8)]:
                other = e.target if e.source == p.alias else e.source
                lines.append(
                    f"{other:20} {bar(e.similarity, max(10, width - 34), full='█', empty='░')} {e.similarity * 100:4.0f}%"
                )
        return lines

    def _activity(self, state: DashboardState, width: int, height: int) -> list[str]:
        rows = state.analytics.commit_wave
        off = min(self.offsets["activity"], max(0, len(rows) - 1))
        self.offsets["activity"] = off
        lines = [
            f"{BOLD}{TEXT}RECENT CHANGE LEDGER{RESET}  {MUTED}j/k scroll · bars show deletions ← center → additions{RESET}",
            "",
        ]
        head = f"{'PROJECT':14} {'DATE':10} {'SHA':7} {'CHANGE':24} {'DEL':>5} {'ADD':>5}  MESSAGE"
        lines.append(MUTED + head + RESET)
        maxv = max([max(r["additions"], r["deletions"]) for r in rows] or [1])
        barhalf = 10
        for r in rows[off : off + max(1, height - 6)]:
            dl = max(0, round(barhalf * r["deletions"] / maxv))
            ad = max(0, round(barhalf * r["additions"] / maxv))
            chg = f"{RED}{'█' * dl:>{barhalf}}{RESET}{SURFACE}│{RESET}{GREEN}{'█' * ad:<{barhalf}}{RESET}"
            msg = str(r["message"])
            lines.append(
                f"{TEXT}{r['project'][:14]:14}{RESET} {SUB}{short_date(r['date']):10} {r['sha']:7}{RESET} {chg} {r['deletions']:5} {r['additions']:5}  {msg}"
            )
        return lines

    def _ecology(self, state: DashboardState, width: int, height: int) -> list[str]:
        langs = state.analytics.languages
        active = "LANGUAGES" if self.ecology_pane == 0 else "PROJECTS"

        lines = [
            (
                f"{BOLD}{TEXT}LANGUAGE ECOLOGY{RESET}  "
                f"{BLUE}{active}{RESET}  "
                f"{MUTED}h/l pane · j/k scroll · GitHub language bytes, not LOC{RESET}"
            ),
            "",
        ]
        rows = max(5, height - 7)

        left_off = max(
            0,
            min(
                self.offsets["ecology_left"],
                max(0, len(langs) - rows),
            ),
        )

        projects = sorted(
            state.projects,
            key=lambda project: project.language_bytes,
            reverse=True,
        )

        right_off = max(
            0,
            min(
                self.offsets["ecology_right"],
                max(0, len(projects) - rows),
            ),
        )

        self.offsets["ecology_left"] = left_off
        self.offsets["ecology_right"] = right_off
        if width >= 100:
            leftw = 30
            rightw = width - leftw - 3

            ledger = [
                (MUTED + f"{'LANGUAGE':10} {'BYTES':>8} {'SHARE':>6} {'R':>3}" + RESET)
            ]

            for language in langs[left_off : left_off + rows]:
                ledger.append(
                    f"{TEXT}{language.language[:10]:10}{RESET} "
                    f"{SUB}{human_bytes(language.bytes):>8} "
                    f"{language.share * 100:5.1f}% "
                    f"{language.projects:3}{RESET}"
                )

            projectw = 18
            project_gap = 3
            cellw = 2
            col_gap = 1
            slot = cellw + col_gap

            matrix_width = max(
                1,
                rightw - projectw - project_gap,
            )

            max_languages = max(
                1,
                matrix_width // slot,
            )

            top = langs[:max_languages]

            labels = [
                language.language[:cellw].upper().center(cellw) for language in top
            ]

            hdr = (
                "PROJECT".ljust(projectw)
                + " " * project_gap
                + (" " * col_gap).join(labels)
            )

            matrix = [MUTED + hdr + RESET]

            for project in projects[right_off : right_off + rows]:
                total = max(
                    1,
                    project.language_bytes,
                )

                cells: list[str] = []

                for language in top:
                    share = (
                        project.languages.get(
                            language.language,
                            0,
                        )
                        / total
                    )

                    if share == 0:
                        cells.append(" " * cellw)
                        continue
                    elif share < 0.08:
                        glyph = "░"
                    elif share < 0.25:
                        glyph = "▒"
                    elif share < 0.55:
                        glyph = "▓"
                    else:
                        glyph = "█"

                    cells.append(
                        _ansi_color(T.language_color(language.language))
                        + glyph * cellw
                        + RESET
                    )

                matrix.append(
                    f"{TEXT}"
                    f"{project.alias[:projectw]:{projectw}}"
                    f"{RESET}" + " " * project_gap + (" " * col_gap).join(cells)
                )

            line_count = max(
                len(ledger),
                len(matrix),
            )

            for i in range(line_count):
                left_line = ledger[i] if i < len(ledger) else ""

                right_line = matrix[i] if i < len(matrix) else ""

                left_text = _fit(
                    left_line,
                    leftw,
                )

                right_text = _fit(
                    right_line,
                    rightw,
                )

                lines.append(f"{left_text} {MUTED}│{RESET} {right_text}")

        else:
            for language in langs[: max(1, height - 5)]:
                share_bar = bar(
                    language.share,
                    max(10, width - 38),
                    full="█",
                    empty="░",
                )
                lines.append(
                    f"{language.language:15} "
                    f"{share_bar} "
                    f"{language.share * 100:5.1f}% "
                    f"{human_bytes(language.bytes):>9}"
                )
        return lines

    def _contributions(
        self, state: DashboardState, width: int, height: int
    ) -> list[str]:
        u = state.user
        days = u.contribution_days
        weeks = [days[i : i + 7] for i in range(0, len(days), 7)]
        visible = max(8, (width - 6) // 2)
        if self.offsets["contrib"] < 0:
            self.offsets["contrib"] = max(0, len(weeks) - visible)
        off = max(0, min(self.offsets["contrib"], max(0, len(weeks) - visible)))
        self.offsets["contrib"] = off
        lines = [
            f"{BOLD}{TEXT}CONTRIBUTIONS{RESET}  {MUTED}h/l scroll weeks · all daily detail currently available from source{RESET}",
            f"{MUTED}calendar total{RESET} {TEXT}{compact(u.calendar_total)}{RESET}   {MUTED}commit contributions{RESET} {TEXT}{compact(u.commits)}{RESET}   {MUTED}PRs{RESET} {TEXT}{compact(u.pull_requests)}{RESET}   {MUTED}daily detail{RESET} {TEXT}{len(days)} days{RESET}",
            "",
        ]
        if weeks:
            shown = weeks[off : off + visible]
            start = shown[0][0].date if shown and shown[0] else ""
            end = shown[-1][-1].date if shown and shown[-1] else ""
            lines.append(
                f"{SUB}{start} → {end}   weeks {off + 1}-{off + len(shown)} of {len(weeks)}{RESET}"
            )
            maxd = max([d.count for d in days] or [1])
            levels = [
                T.SURFACE0,
                _blend_hex(T.SURFACE0, T.GREEN, 0.28),
                _blend_hex(T.SURFACE0, T.GREEN, 0.48),
                _blend_hex(T.SURFACE0, T.GREEN, 0.72),
                T.GREEN,
            ]
            import datetime as _dt

            day_labels = []
            for di in range(7):
                sample = next((wk[di] for wk in shown if di < len(wk)), None)
                try:
                    day_labels.append(
                        _dt.date.fromisoformat(sample.date).strftime("%a")
                        if sample
                        else "---"
                    )
                except ValueError:
                    day_labels.append("---")
            for di in range(7):
                row = f"{MUTED}{day_labels[di]}{RESET} "
                for wk in shown:
                    if di >= len(wk):
                        row += "  "
                        continue
                    d = wk[di]
                    q = d.count / maxd
                    level = (
                        0
                        if d.count == 0
                        else 1
                        if q < 0.2
                        else 2
                        if q < 0.45
                        else 3
                        if q < 0.75
                        else 4
                    )
                    row += T.ansi(levels[level]) + "■" + RESET + " "
                lines.append(row)
        annual = list(u.annual_totals.items())
        if annual and len(lines) < height - 2:
            mx = max(v for _, v in annual) or 1
            lines += ["", BOLD + TEXT + "ANNUAL TOTALS" + RESET]
            parts = [
                f"{y} {bar(v / mx, 8, full='█', empty='░')} {compact(v)}"
                for y, v in annual
            ]
            line = ""
            for part in parts:
                if _len(line) + len(part) + 3 > width:
                    lines.append(line)
                    line = ""
                line += ("   " if line else "") + part
            if line:
                lines.append(line)
        return lines

    def _sources(self, state: DashboardState, width: int, height: int) -> list[str]:
        tabs = ["REGISTRIES", "STATUS", "RELEASES"]
        lines = [
            f"{BOLD}{TEXT}SOURCES{RESET}  "
            + "  ".join(
                f"{BLUE if i == self.source_tab else MUTED}{'[' if i == self.source_tab else ' '}{name}{']' if i == self.source_tab else ' '}{RESET}"
                for i, name in enumerate(tabs)
            )
            + f"  {MUTED}[t] switch tab · j/k scroll{RESET}",
            "",
        ]
        if self.source_tab == 0:
            rows = []
            for a in state.npm:
                rows.append(
                    (
                        "npm",
                        a.name,
                        a.alias,
                        a.version,
                        "-",
                        human_bytes(a.size_bytes),
                        relative_time(a.updated_at),
                    )
                )
            for a in state.crates:
                rows.append(
                    (
                        "crates",
                        a.name,
                        a.alias,
                        a.version,
                        compact(a.downloads) if a.downloads is not None else "-",
                        "-",
                        relative_time(a.updated_at),
                    )
                )
            for a in state.docker:
                rows.append(
                    (
                        "docker",
                        a.alias,
                        a.alias,
                        a.latest_tag,
                        "-",
                        human_bytes(a.latest_size_bytes),
                        relative_time(a.latest_updated_at),
                    )
                )
            off = min(self.offsets["sources"], max(0, len(rows) - 1))
            self.offsets["sources"] = off
            lines.append(
                MUTED
                + f"{'SOURCE':8} {'NAME':20} {'ALIAS':18} {'VERSION/TAG':13} {'DOWNLOADS':>10} {'SIZE':>10} {'UPDATED':>10}"
                + RESET
            )
            for r in rows[off : off + max(1, height - 5)]:
                lines.append(
                    f"{TEXT}{r[0]:8}{RESET} {r[1][:20]:20} {r[2][:18]:18} {r[3][:13]:13} {r[4]:>10} {r[5]:>10} {r[6]:>10}"
                )
        elif self.source_tab == 1:
            lines.append(
                MUTED
                + f"{'CHECK':24} {'STATE':8} {'HTTP':>6} {'LATENCY':>9} {'CHECKED':>10} URL"
                + RESET
            )
            for s in state.statuses:
                lines.append(
                    f"{TEXT}{s.label[:24]:24}{RESET} {GREEN if s.ok else RED}{('UP' if s.ok else s.state.upper()):8}{RESET} {s.status or '-'!s:>6} {(f'{s.latency_ms:.0f}ms' if s.latency_ms is not None else '-'):>9} {relative_time(s.checked_at):>10} {s.url}"
                )
        else:
            rows = sorted(state.projects, key=lambda p: p.alias)
            off = min(self.offsets["sources"], max(0, len(rows) - 1))
            self.offsets["sources"] = off
            lines.append(
                MUTED
                + f"{'PROJECT':20} {'LATEST':14} {'PUBLISHED':10} {'RELS':>5} {'TAGS':>5} {'DEPL':>5} {'PUSHED':>10}"
                + RESET
            )
            for p in rows[off : off + max(1, height - 5)]:
                lines.append(
                    f"{TEXT}{p.alias[:20]:20}{RESET} {(p.latest_release.tag if p.latest_release else '-')[:14]:14} {(short_date(p.latest_release.published_at) if p.latest_release else '-'):10} {len(p.releases):5} {len(p.tags):5} {len(p.deployments):5} {relative_time(p.pushed_at):>10}"
                )
        return lines

    def _inspector(self, state: DashboardState, width: int, height: int) -> list[str]:
        raw = self.engine.raw_store
        keys = sorted(raw)

        idx = max(
            0,
            min(
                self.offsets["inspector_left"],
                max(0, len(keys) - 1),
            ),
        )

        self.offsets["inspector_left"] = idx
        key = keys[idx] if keys else ""

        active = "KEYS" if self.inspector_pane == 0 else "VALUE"

        lines = [
            (
                f"{BOLD}{TEXT}RAW STORE INSPECTOR{RESET}  "
                f"{BLUE}{active}{RESET}  "
                f"{MUTED}h/l pane · j/k scroll · exact cached /v1/store value{RESET}"
            ),
            "",
        ]

        if width >= 100 and keys:
            leftw = min(42, max(32, width // 3))
            rightw = width - leftw - 3

            rows = max(1, height - 4)

            start = max(
                0,
                min(
                    idx - rows // 2,
                    max(0, len(keys) - rows),
                ),
            )

            kl: list[str] = []

            for i, k in enumerate(
                keys[start : start + rows],
                start,
            ):
                kl.append(
                    f"{BLUE if i == idx else SUB}"
                    f"{'›' if i == idx else ' '} "
                    f"{k[: leftw - 4]}"
                    f"{RESET}"
                )

            js = json.dumps(
                raw.get(key),
                indent=2,
                ensure_ascii=False,
            ).splitlines()

            json_height = max(1, rows - 1)

            right_max = max(
                0,
                len(js) - json_height,
            )

            right_off = max(
                0,
                min(
                    self.offsets["inspector_right"],
                    right_max,
                ),
            )

            self.offsets["inspector_right"] = right_off

            shown_json = js[right_off : right_off + json_height]

            detail = [
                BOLD + TEXT + key + RESET,
                *(SUB + line + RESET for line in shown_json),
            ]

            for i in range(rows):
                left_line = kl[i] if i < len(kl) else ""
                right_line = detail[i] if i < len(detail) else ""

                lines.append(
                    f"{_fit(left_line, leftw)} "
                    f"{MUTED}│{RESET} "
                    f"{_fit(right_line, rightw)}"
                )

        elif key:
            lines.append(BLUE + key + RESET)
            lines += json.dumps(
                raw.get(key),
                indent=2,
                ensure_ascii=False,
            ).splitlines()[: height - 5]

        return lines

    def _footer(self, width: int) -> list[str]:
        if self.progress:
            p = self.progress
            if p.progress is None:
                self._indeterminate = (self._indeterminate + 1) % 22
                fill = (
                    "░" * self._indeterminate
                    + "▓▓▓"
                    + "░" * max(0, 22 - self._indeterminate)
                )
                st = f"{PEACH}{fill}{RESET} {p.message}"
            else:
                st = f"{BLUE}{bar(p.progress, 25, full='▓', empty='░')}{RESET} {p.message}"
        else:
            st = self.message or "Ready"
        return [
            _fit(
                SURFACE + "-" * width + RESET,
                width,
            ),
            _fit(
                f"{MUTED}[r] refresh  [c] check  [1-8] views  [q] quit{RESET}"
                f"     {SUB}{st}{RESET}",
                width,
            ),
        ]

    def frame(self) -> str:
        state = self.engine.state
        size = shutil.get_terminal_size((132, 38))
        width = max(68, size.columns)
        height = max(22, size.lines)
        body_height = height - 6
        render = [
            self._pulse,
            self._projects,
            self._constellation,
            self._activity,
            self._ecology,
            self._contributions,
            self._sources,
            self._inspector,
        ]
        lines = self._header(width, state)
        body = render[self.view](state, width, body_height)
        available = height - len(lines) - 2
        body = body[:available] + [""] * max(0, available - len(body))
        lines.extend(_fit(x, width) for x in body)
        lines.extend(self._footer(width))
        return "\x1b[H" + "\n".join(lines)

    def _move(self, delta: int) -> None:
        state = self.engine.state
        if self.view == 1:
            self.offsets["projects"] = max(0, self.offsets["projects"] + delta)
        elif self.view == 2:
            self.const_index = max(
                0, min(len(state.projects) - 1, self.const_index + delta)
            )
        elif self.view == 3:
            self.offsets["activity"] = max(0, self.offsets["activity"] + delta)
        elif self.view == 4:
            key = "ecology_left" if self.ecology_pane == 0 else "ecology_right"

            self.offsets[key] = max(
                0,
                self.offsets[key] + delta,
            )
        elif self.view == 6:
            self.offsets["sources"] = max(0, self.offsets["sources"] + delta)
        elif self.view == 7:
            if self.inspector_pane == 0:
                old = self.offsets["inspector_left"]

                self.offsets["inspector_left"] = max(
                    0,
                    min(
                        len(self.engine.raw_store) - 1,
                        old + delta,
                    ),
                )
                if self.offsets["inspector_left"] != old:
                    self.offsets["inspector_right"] = 0

            else:
                self.offsets["inspector_right"] = max(
                    0,
                    self.offsets["inspector_right"] + delta,
                )

    def _horizontal(self, delta: int) -> None:
        if self.view == 1:
            self.offsets["project_col"] = max(
                0,
                min(len(self.PROJECT_COLUMNS) - 1, self.offsets["project_col"] + delta),
            )
        elif self.view == 4:
            self.ecology_pane = max(
                0,
                min(
                    1,
                    self.ecology_pane + delta,
                ),
            )
        elif self.view == 5:
            self.offsets["contrib"] = max(0, self.offsets["contrib"] + delta * 4)
        elif self.view == 7:
            self.inspector_pane = max(
                0,
                min(
                    1,
                    self.inspector_pane + delta,
                ),
            )

    def run(self) -> None:
        print(
            "\x1b[?1049h\x1b[2J\x1b[?25l",
            end="",
            flush=True,
        )

        try:
            with _raw_terminal():
                last_progress_draw = 0.0

                while self.running:
                    now = time.monotonic()

                    animate = (
                        self.progress is not None and now - last_progress_draw >= 0.08
                    )

                    if self._dirty or animate:
                        sys.stdout.write(self.frame())
                        sys.stdout.flush()

                        self._dirty = False

                        if animate:
                            last_progress_draw = now

                    key = _read_key()

                    if key:
                        low = key.lower()

                        if low == "q":
                            self.running = False

                        elif low == "r":
                            self.refresh()
                            self._redraw()

                        elif low == "c":
                            self.check()
                            self._redraw()

                        elif low == "t" and self.view == 6:
                            self.source_tab = (self.source_tab + 1) % 3

                            self.offsets["sources"] = 0
                            self._redraw()

                        elif low in ("j", "down"):
                            self._move(1)
                            self._redraw()

                        elif low in ("k", "up"):
                            self._move(-1)
                            self._redraw()

                        elif low in ("h", "left"):
                            self._horizontal(-1)
                            self._redraw()

                        elif low in ("l", "right"):
                            self._horizontal(1)
                            self._redraw()

                        elif low.isdigit() and 1 <= int(low) <= len(self.views):
                            self.view = int(low) - 1
                            self._redraw()

                    time.sleep(0.01)

        finally:
            print(
                "\x1b[?25h\x1b[?1049l" + RESET,
                end="",
                flush=True,
            )


def _blend_hex(a: str, b: str, t: float) -> str:
    av = [int(a[i : i + 2], 16) for i in (1, 3, 5)]
    bv = [int(b[i : i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(av, bv))


def run_tui(engine: EchopointEngine) -> None:
    TuiApp(engine).run()
