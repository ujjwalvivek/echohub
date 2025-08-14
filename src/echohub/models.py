from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import TypedDict, cast

from .types import JsonObject, JsonValue, as_int


@dataclass(slots=True)
class Commit:
    sha: str = ""
    message: str = ""
    url: str = ""
    author: str = ""
    date: str = ""
    additions: int = 0
    deletions: int = 0

    @property
    def churn(self) -> int:
        return self.additions + self.deletions


@dataclass(slots=True)
class Release:
    tag: str = ""
    name: str = ""
    published_at: str = ""
    url: str = ""
    prerelease: bool = False
    draft: bool = False


@dataclass(slots=True)
class Contributor:
    login: str = ""
    contributions: int = 0
    avatar_url: str = ""


@dataclass(slots=True)
class Project:
    alias: str
    name: str = ""
    full_name: str = ""
    description: str = ""
    html_url: str = ""
    homepage: str = ""
    default_branch: str = ""
    created_at: str = ""
    updated_at: str = ""
    pushed_at: str = ""
    archived: bool = False
    fork: bool = False
    private: bool = False
    stars: int = 0
    forks: int = 0
    watchers: int = 0
    open_issues: int = 0
    size_kb: int = 0
    commit_count: int = 0
    topics: list[str] = field(default_factory=list)
    license_name: str = ""
    owner_login: str = ""
    languages: dict[str, int] = field(default_factory=dict)
    commits: list[Commit] = field(default_factory=list)
    latest_release: Release | None = None
    releases: list[Release] = field(default_factory=list)
    contributors: list[Contributor] = field(default_factory=list)
    tags: list[JsonObject] = field(default_factory=list)
    deployments: list[JsonObject] = field(default_factory=list)
    activity_score: float = 0.0

    @property
    def dominant_language(self) -> str:
        if not self.languages:
            return "Unknown"
        return max(self.languages.items(), key=lambda kv: kv[1])[0]

    @property
    def language_bytes(self) -> int:
        return sum(max(0, value) for value in self.languages.values())


@dataclass(slots=True)
class PackageArtifact:
    ecosystem: str
    alias: str
    name: str = ""
    version: str = ""
    description: str = ""
    updated_at: str = ""
    downloads: int | None = None
    recent_downloads: int | None = None
    size_bytes: int | None = None
    file_count: int | None = None
    dependency_count: int = 0
    license_name: str = ""
    repository_url: str = ""
    homepage: str = ""
    raw: JsonObject = field(default_factory=dict)


@dataclass(slots=True)
class DockerArtifact:
    alias: str
    tags: list[JsonObject] = field(default_factory=list)

    @property
    def latest_tag(self) -> str:
        if not self.tags:
            return ""
        value = self.tags[0].get("name")
        return value if isinstance(value, str) else ""

    @property
    def latest_updated_at(self) -> str:
        if not self.tags:
            return ""
        value = self.tags[0].get("last_updated")
        return value if isinstance(value, str) else ""

    @property
    def latest_size_bytes(self) -> int | None:
        if not self.tags:
            return None
        value = self.tags[0].get("full_size")
        if value is None:
            return None
        parsed = as_int(value, -1)
        return parsed if parsed >= 0 else None


@dataclass(slots=True)
class StatusCheck:
    alias: str
    label: str = ""
    state: str = "unknown"
    ok: bool = False
    status: int | None = None
    latency_ms: float | None = None
    checked_at: str = ""
    url: str = ""
    error: str = ""


@dataclass(slots=True)
class ContributionDay:
    date: str
    count: int
    color: str = ""


@dataclass(slots=True)
class UserSummary:
    name: str = ""
    login: str = ""
    commits: int = 0
    pull_requests: int = 0
    repositories_with_issues: int = 0
    restricted: int = 0
    calendar_total: int = 0
    contribution_days: list[ContributionDay] = field(default_factory=list)
    annual_totals: dict[int, int] = field(default_factory=dict)


@dataclass(slots=True)
class EngineMeta:
    last_updated: str = ""
    last_run: JsonObject = field(default_factory=dict)
    fetched_at: str = ""
    from_cache: bool = False
    remote_sources: int | None = None


@dataclass(slots=True)
class ConstellationNode:
    alias: str
    x: float
    y: float
    size: float
    activity: float
    language: str
    stars: int
    commits: int


@dataclass(slots=True)
class ConstellationEdge:
    source: str
    target: str
    similarity: float


@dataclass(slots=True)
class LanguageSlice:
    language: str
    bytes: int
    share: float
    projects: int


class CommitWaveRow(TypedDict):
    project: str
    sha: str
    message: str
    date: str
    additions: int
    deletions: int
    churn: int


class EcosystemArtifactRow(TypedDict):
    type: str
    version: str
    name: str


class EcosystemLinkRow(TypedDict):
    alias: str
    project: str | None
    link_kind: str
    artifacts: list[EcosystemArtifactRow]


@dataclass(slots=True)
class DashboardAnalytics:
    totals: dict[str, int | float] = field(default_factory=dict)
    languages: list[LanguageSlice] = field(default_factory=list)
    constellation_nodes: list[ConstellationNode] = field(default_factory=list)
    constellation_edges: list[ConstellationEdge] = field(default_factory=list)
    commit_wave: list[CommitWaveRow] = field(default_factory=list)
    ecosystem_links: list[EcosystemLinkRow] = field(default_factory=list)


@dataclass(slots=True)
class DashboardState:
    meta: EngineMeta
    projects: list[Project]
    npm: list[PackageArtifact]
    crates: list[PackageArtifact]
    docker: list[DockerArtifact]
    statuses: list[StatusCheck]
    user: UserSummary
    analytics: DashboardAnalytics
    raw_key_count: int = 0

    def to_dict(self) -> JsonObject:
        # asdict() is typed as dict[str, Any] by typeshed even though every field
        # in this dataclass tree is JSON-compatible. Collapse that stdlib typing
        # hole at this single boundary and keep the public contract concrete.
        raw_data: object = asdict(self)  # pyright: ignore[reportAny]
        data = cast(JsonObject, raw_data)
        projects_value: JsonValue | None = data.get("projects")
        if isinstance(projects_value, list):
            for raw, project in zip(projects_value, self.projects):
                if not isinstance(raw, dict):
                    continue
                raw["dominant_language"] = project.dominant_language
                raw["language_bytes"] = project.language_bytes
                raw["recent_churn"] = sum(
                    max(0, commit.additions) + max(0, commit.deletions)
                    for commit in project.commits
                )
        return data
