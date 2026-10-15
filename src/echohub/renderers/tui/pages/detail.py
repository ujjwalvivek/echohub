"""One project in full; shared by Projects (side pane or full page) and
Constellation. Mirrors the desktop detail panel, top to bottom."""

from __future__ import annotations

from .... import palette as P
from ....formatting import compact, human_bytes, human_kb, relative_time, short_date
from ....models import Project
from ..style import fit, paint, spread, width
from ..widgets import Stat, hbar, pill, private_mark, section, stat_strip

_MAX_LANGUAGES = 6
_MAX_COMMITS = 6
_MAX_RELEASES = 5
_MAX_PEOPLE = 4


def _wrap(text: str, cells: int, limit: int = 4) -> list[str]:
    words = text.split()
    lines: list[str] = []
    line = ""
    for word in words:
        if line and len(line) + 1 + len(word) > cells:
            lines.append(line)
            line = word
        else:
            line = f"{line} {word}" if line else word
    if line:
        lines.append(line)
    if len(lines) > limit:
        lines = lines[:limit]
        lines[-1] = fit(lines[-1] + " …", cells)
    return lines


def project_detail(project: Project | None, cells: int) -> list[str]:
    if project is None:
        return [paint("Select a project to see its details", P.MUTED)]
    lines = [private_mark(project.private) + paint(project.alias, P.TEXT, bold=True)]
    if project.full_name and project.full_name != project.alias:
        lines.append(paint(project.full_name, P.MUTED))
    if project.description:
        lines += [paint(line, P.SUBTLE) for line in _wrap(project.description, cells)]
    if project.html_url:
        lines.append(paint("o", P.ACCENT) + paint(" open on GitHub", P.MUTED))
    lines.append("")
    lines += stat_strip(
        [
            Stat("Code", human_bytes(project.language_bytes)),
            Stat("Commits", compact(project.commit_count)),
            Stat(
                "Last push",
                relative_time(project.pushed_at) if project.pushed_at else "-",
            ),
        ],
        cells,
    )

    lines += ["", section("Details", "", cells)]
    facts = [
        (
            "Language",
            paint("■ ", P.series_color(project.dominant_language))
            + paint(project.dominant_language, P.TEXT),
        ),
        ("Repo size", paint(human_kb(project.size_kb), P.TEXT)),
        ("Created", paint(short_date(project.created_at), P.TEXT)),
        ("License", paint(project.license_name or "-", P.TEXT)),
        ("Branch", paint(project.default_branch or "-", P.TEXT)),
    ]
    if project.homepage:
        facts.append(("Homepage", paint(project.homepage, P.SUBTLE)))
    if project.stars or project.forks or project.open_issues:
        facts.append(
            (
                "Stars · forks · issues",
                paint(
                    f"{project.stars} · {project.forks} · {project.open_issues}", P.TEXT
                ),
            )
        )
    for caption, value in facts:
        lines.append(spread(paint(caption, P.MUTED), value, cells))

    if project.languages:
        ranked = sorted(project.languages.items(), key=lambda item: -item[1])
        lines += ["", section("Languages", str(len(ranked)), cells)]
        total = project.language_bytes or 1
        track = max(4, cells - 2 - 14 - 1 - 5)
        for name, value in ranked[:_MAX_LANGUAGES]:
            share = value / total
            colour = P.series_color(name)
            lines.append(
                paint("■ ", colour)
                + fit(paint(name, P.SUBTLE), 14)
                + " "
                + hbar(share, track, colour)
                + fit(paint(f"{share:.0%}", P.SUBTLE), 5, "right")
            )
        if len(ranked) > _MAX_LANGUAGES:
            lines.append(paint(f"+{len(ranked) - _MAX_LANGUAGES} more", P.MUTED))

    if project.commits:
        lines += ["", section("Recent commits", str(len(project.commits)), cells)]
        for commit in project.commits[:_MAX_COMMITS]:
            when = paint(relative_time(commit.date), P.SUBTLE)
            tone = P.MUTED if commit.automated else P.SUBTLE
            lines.append(
                fit(paint(commit.message, tone), cells - width(when) - 1) + " " + when
            )

    releases = project.releases or (
        [project.latest_release] if project.latest_release else []
    )
    if releases:
        lines += ["", section("Releases", str(len(releases)), cells)]
        for release in releases[:_MAX_RELEASES]:
            lines.append(
                spread(
                    pill(release.tag),
                    paint(relative_time(release.published_at), P.SUBTLE),
                    cells,
                )
            )

    if project.contributors:
        lines += ["", section("Contributors", str(len(project.contributors)), cells)]
        for person in project.contributors[:_MAX_PEOPLE]:
            lines.append(
                spread(
                    paint(person.login, P.SUBTLE),
                    paint(compact(person.contributions), P.SUBTLE),
                    cells,
                )
            )

    if project.topics:
        lines += ["", section("Topics", str(len(project.topics)), cells)]
        line = ""
        for topic in project.topics:
            chip = pill(topic)
            if line and width(line) + 1 + width(chip) > cells:
                lines.append(line)
                line = chip
            else:
                line = f"{line} {chip}" if line else chip
        if line:
            lines.append(line)
    return [fit(line, cells) for line in lines]
