from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable

from .models import (
    CommitWaveRow,
    ConstellationEdge,
    DashboardAnalytics,
    DockerArtifact,
    LanguageSlice,
    PackageArtifact,
    Project,
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


def constellation_edges(projects: list[Project]) -> list[ConstellationEdge]:
    """Each repo linked to up to three repos with the most similar language mix."""
    if not projects:
        return []

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
    return edges


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
                    "automated": commit.automated,
                }
            )
    rows.sort(key=lambda row: row["date"], reverse=True)
    return rows[:120]


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
    private_bytes = sum(max(0, value) for value in (private_languages or {}).values())
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
        constellation_edges=constellation_edges(projects),
        commit_wave=commit_wave(projects),
    )
