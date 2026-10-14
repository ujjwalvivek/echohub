from __future__ import annotations

import hashlib
import math
from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime

from .models import (
    CommitWaveRow,
    ConstellationEdge,
    ConstellationNode,
    DashboardAnalytics,
    DockerArtifact,
    EcosystemArtifactRow,
    EcosystemLinkRow,
    LanguageSlice,
    PackageArtifact,
    Project,
)


def _parse_date(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _days_since(value: str) -> float:
    parsed = _parse_date(value)
    if parsed is None:
        return 9999.0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return max(0.0, (datetime.now(UTC) - parsed).total_seconds() / 86400.0)


def score_projects(projects: list[Project]) -> None:
    """Internal ranking only."""
    for project in projects:
        churn = sum(commit.churn for commit in project.commits)
        recent_commit_count = len(project.commits)
        pushed_bonus = max(0.0, 20.0 - min(20.0, _days_since(project.pushed_at) / 3.0))
        release_date = (
            project.latest_release.published_at if project.latest_release else ""
        )
        release_bonus = max(0.0, 15.0 - min(15.0, _days_since(release_date) / 10.0))
        project.activity_score = round(
            recent_commit_count * 5
            + math.log1p(churn) * 4
            + math.log1p(project.stars) * 2
            + pushed_bonus
            + release_bonus,
            2,
        )


def language_slices(
    projects: Iterable[Project],
    private_languages: dict[str, int] | None = None,
) -> list[LanguageSlice]:
    totals: dict[str, int] = defaultdict(int)
    counts: dict[str, int] = defaultdict(int)
    private = private_languages or {}
    for project in projects:
        for language, value in project.languages.items():
            totals[language] += max(0, value)
            if value > 0:
                counts[language] += 1
    for language, value in private.items():
        totals[language] += max(0, value)
    grand = sum(totals.values()) or 1
    rows = [
        LanguageSlice(
            language=language,
            bytes=value,
            share=value / grand,
            projects=counts[language],
            private_bytes=max(0, private.get(language, 0)),
        )
        for language, value in totals.items()
    ]
    return sorted(rows, key=lambda row: row.bytes, reverse=True)


def _lang_vector(project: Project) -> dict[str, float]:
    total = project.language_bytes or 1
    return {
        language: value / total
        for language, value in project.languages.items()
        if value > 0
    }


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    keys = set(a) | set(b)
    dot = sum(a.get(key, 0.0) * b.get(key, 0.0) for key in keys)
    norm_a = math.sqrt(sum(value * value for value in a.values()))
    norm_b = math.sqrt(sum(value * value for value in b.values()))
    return dot / (norm_a * norm_b) if norm_a and norm_b else 0.0


def _hash_fraction(value: str, offset: int = 0) -> float:
    digest = hashlib.sha256(value.encode()).digest()
    start = offset % (len(digest) - 4)
    return int.from_bytes(digest[start : start + 4], "big") / 2**32


def constellation(
    projects: list[Project],
) -> tuple[list[ConstellationNode], list[ConstellationEdge]]:
    """Stable language-clustered layout plus sparse nearest-similarity edges."""
    if not projects:
        return [], []

    vectors = {project.alias: _lang_vector(project) for project in projects}
    edge_pairs: dict[tuple[str, str], float] = {}
    for project in projects:
        scored: list[tuple[float, Project]] = []
        for candidate in projects:
            if project is candidate:
                continue
            similarity = _cosine(vectors[project.alias], vectors[candidate.alias])
            if similarity >= 0.25:
                scored.append((similarity, candidate))
        for similarity, candidate in sorted(
            scored, key=lambda item: item[0], reverse=True
        )[:3]:
            left, right = sorted((project.alias, candidate.alias))
            key: tuple[str, str] = (left, right)
            edge_pairs[key] = max(edge_pairs.get(key, 0.0), similarity)
    edges = [
        ConstellationEdge(source, target, round(similarity, 3))
        for (source, target), similarity in sorted(edge_pairs.items())
    ]

    groups: dict[str, list[Project]] = defaultdict(list)
    for project in projects:
        groups[project.dominant_language].append(project)
    languages = sorted(
        groups,
        key=lambda language: (
            -sum(project.language_bytes for project in groups[language]),
            language.lower(),
        ),
    )

    centers: dict[str, tuple[float, float]] = {}
    group_count = max(1, len(languages))
    for index, language in enumerate(languages):
        angle = -math.pi / 2 + (2 * math.pi * index / group_count)
        centers[language] = (
            0.5 + 0.34 * math.cos(angle),
            0.5 + 0.34 * math.sin(angle),
        )

    max_code = max((project.language_bytes for project in projects), default=1) or 1
    max_activity = (
        max((project.activity_score for project in projects), default=1.0) or 1.0
    )
    nodes: list[ConstellationNode] = []
    for language in languages:
        members = sorted(
            groups[language],
            key=lambda project: (-project.language_bytes, project.alias.lower()),
        )
        center_x, center_y = centers[language]
        count = len(members)
        for index, project in enumerate(members):
            if count == 1:
                x, y = center_x, center_y
            else:
                ring = 0.026 + 0.015 * math.sqrt(count)
                angle = (
                    2 * math.pi * index / count + _hash_fraction(project.alias, 3) * 0.4
                )
                radius = ring * (0.72 + _hash_fraction(project.alias, 7) * 0.45)
                x = center_x + radius * math.cos(angle)
                y = center_y + radius * math.sin(angle)
            x = min(0.94, max(0.06, x))
            y = min(0.92, max(0.08, y))
            nodes.append(
                ConstellationNode(
                    alias=project.alias,
                    x=round(x, 4),
                    y=round(y, 4),
                    size=round(
                        0.30
                        + 0.70 * math.sqrt(max(0, project.language_bytes) / max_code),
                        3,
                    ),
                    activity=round(project.activity_score / max_activity, 3),
                    language=project.dominant_language,
                    stars=project.stars,
                    commits=project.commit_count,
                )
            )
    return nodes, edges


def commit_wave(projects: Iterable[Project]) -> list[CommitWaveRow]:
    rows: list[CommitWaveRow] = []
    for project in projects:
        for commit in project.commits:
            rows.append(
                {
                    "project": project.alias,
                    "sha": commit.sha[:7],
                    "message": commit.message,
                    "date": commit.date,
                    "additions": commit.additions,
                    "deletions": commit.deletions,
                    "churn": commit.churn,
                }
            )
    rows.sort(key=lambda row: row["date"], reverse=True)
    return rows[:120]


def _artifact_project(
    alias: str, name: str, projects: list[Project]
) -> tuple[str | None, str]:
    candidates = {project.alias.lower(): project.alias for project in projects}
    for value in (alias, name):
        low = value.lower()
        if low in candidates:
            return candidates[low], "exact"
    prefix_matches = [
        project.alias
        for project in projects
        if len(project.alias) >= 4
        and (
            alias.lower().startswith(project.alias.lower() + "-")
            or name.lower().startswith(project.alias.lower() + "-")
        )
    ]
    if len(prefix_matches) == 1:
        return prefix_matches[0], "prefix"
    return None, "unlinked"


def _artifact_row(kind: str, version: str, name: str) -> EcosystemArtifactRow:
    return {"type": kind, "version": version, "name": name}


def ecosystem_links(
    projects: list[Project],
    npm: list[PackageArtifact],
    crates: list[PackageArtifact],
    docker: list[DockerArtifact],
    pypi: list[PackageArtifact] | None = None,
) -> list[EcosystemLinkRow]:
    links: list[EcosystemLinkRow] = []
    for item in npm:
        project, link_kind = _artifact_project(item.alias, item.name, projects)
        links.append(
            {
                "alias": item.alias,
                "project": project,
                "link_kind": link_kind,
                "artifacts": [_artifact_row("npm", item.version, item.name)],
            }
        )
    for item in crates:
        project, link_kind = _artifact_project(item.alias, item.name, projects)
        links.append(
            {
                "alias": item.alias,
                "project": project,
                "link_kind": link_kind,
                "artifacts": [_artifact_row("crates", item.version, item.name)],
            }
        )
    for item in pypi or []:
        project, link_kind = _artifact_project(item.alias, item.name, projects)
        links.append(
            {
                "alias": item.alias,
                "project": project,
                "link_kind": link_kind,
                "artifacts": [_artifact_row("pypi", item.version, item.name)],
            }
        )
    for item in docker:
        project, link_kind = _artifact_project(item.alias, item.alias, projects)
        links.append(
            {
                "alias": item.alias,
                "project": project,
                "link_kind": link_kind,
                "artifacts": [_artifact_row("docker", item.latest_tag, item.alias)],
            }
        )
    return sorted(links, key=lambda row: (row["project"] or "~", row["alias"]))


def build_analytics(
    projects: list[Project],
    npm: list[PackageArtifact],
    crates: list[PackageArtifact],
    docker: list[DockerArtifact],
    private_languages: dict[str, int] | None = None,
    *,
    pypi: list[PackageArtifact] | None = None,
) -> DashboardAnalytics:
    pypi = pypi or []
    score_projects(projects)
    private_bytes = sum(max(0, value) for value in (private_languages or {}).values())
    nodes, edges = constellation(projects)
    commits = [commit for project in projects for commit in project.commits]
    totals: dict[str, int | float] = {
        "projects": len(projects),
        "stars": sum(project.stars for project in projects),
        "forks": sum(project.forks for project in projects),
        "open_issues": sum(project.open_issues for project in projects),
        "commits": sum(project.commit_count for project in projects),
        "recent_commits": len(commits),
        "recent_additions": sum(commit.additions for commit in commits),
        "recent_deletions": sum(commit.deletions for commit in commits),
        "recent_churn": sum(commit.churn for commit in commits),
        "language_bytes": sum(project.language_bytes for project in projects)
        + private_bytes,
        "private_language_bytes": private_bytes,
        "repo_size_kb": sum(project.size_kb for project in projects),
        "releases": sum(len(project.releases) for project in projects),
        "packages": len(npm) + len(crates) + len(pypi) + len(docker),
    }
    return DashboardAnalytics(
        totals=totals,
        languages=language_slices(projects, private_languages),
        constellation_nodes=nodes,
        constellation_edges=edges,
        commit_wave=commit_wave(projects),
        ecosystem_links=ecosystem_links(projects, npm, crates, docker, pypi),
    )
