from __future__ import annotations

import re
from collections import Counter, defaultdict

from .models import (
    Commit,
    ContributionDay,
    Contributor,
    DockerArtifact,
    EngineMeta,
    PackageArtifact,
    Project,
    Release,
    StatusCheck,
    UserSummary,
)
from .types import (
    JsonObject,
    JsonValue,
    as_array,
    as_bool,
    as_float,
    as_int,
    as_object,
    as_str,
)


def _release(value: JsonValue | None) -> Release | None:
    data = as_object(value)
    if not data or as_str(data.get("message")) == "Not Found":
        return None
    tag = as_str(data.get("tag_name")) or as_str(data.get("tag"))
    published_at = as_str(data.get("published_at")) or as_str(data.get("created_at"))
    url = as_str(data.get("html_url")) or as_str(data.get("url"))
    return Release(
        tag=tag,
        name=as_str(data.get("name")),
        published_at=published_at,
        url=url,
        prerelease=as_bool(data.get("prerelease")),
        draft=as_bool(data.get("draft")),
    )


def _commits(value: JsonValue | None) -> list[Commit]:
    result: list[Commit] = []
    for item in as_array(value):
        data = as_object(item)
        raw_commit = as_object(data.get("commit"))
        raw_author = as_object(raw_commit.get("author"))
        message = as_str(data.get("message")) or as_str(raw_commit.get("message"))
        if message:
            message = message.splitlines()[0]
        result.append(
            Commit(
                sha=as_str(data.get("sha")),
                message=message,
                url=as_str(data.get("url")) or as_str(data.get("html_url")),
                author=as_str(data.get("author")) or as_str(raw_author.get("name")),
                date=as_str(data.get("date")) or as_str(raw_author.get("date")),
                additions=as_int(data.get("additions")),
                deletions=as_int(data.get("deletions")),
            )
        )
    return result


_DIGITS = re.compile(r"\d+")
# Three commits with the same message shape inside one repo's recent sample
# is a script, not a person.
_AUTOMATED_REPEATS = 3


def _mark_automated(commits: list[Commit]) -> None:
    shapes = Counter(_DIGITS.sub("#", commit.message) for commit in commits)
    for commit in commits:
        commit.automated = commit.author.lower().endswith("[bot]") or (
            shapes[_DIGITS.sub("#", commit.message)] >= _AUTOMATED_REPEATS
        )


def _contributors(value: JsonValue | None) -> list[Contributor]:
    result: list[Contributor] = []
    for item in as_array(value):
        data = as_object(item)
        result.append(
            Contributor(
                login=as_str(data.get("login")),
                contributions=as_int(data.get("contributions")),
                avatar_url=as_str(data.get("avatar_url")),
            )
        )
    return result


def normalize_projects(store: JsonObject) -> list[Project]:
    grouped: dict[str, JsonObject] = defaultdict(dict)
    for key, value in store.items():
        if not key.startswith("github:"):
            continue
        parts = key.split(":", 2)
        if len(parts) != 3 or parts[2] == "summary":
            continue
        grouped[parts[1]][parts[2]] = value

    projects: list[Project] = []
    for alias, values in grouped.items():
        repo = as_object(values.get("repo"))
        if not repo and values.get("langs") is None and values.get("commits") is None:
            continue
        license_data = as_object(repo.get("license"))
        owner = as_object(repo.get("owner"))
        releases = [
            release
            for raw_release in as_array(values.get("releases"))
            if (release := _release(raw_release)) is not None
        ]
        latest_release = _release(values.get("release"))
        if latest_release is None and releases:
            latest_release = releases[0]

        languages: dict[str, int] = {}
        for language, raw_bytes in as_object(values.get("langs")).items():
            byte_count = as_int(raw_bytes)
            if byte_count >= 0:
                languages[language] = byte_count

        topics = [
            item for item in as_array(repo.get("topics")) if isinstance(item, str)
        ]
        commits = _commits(values.get("commits"))
        _mark_automated(commits)
        project = Project(
            alias=alias,
            name=as_str(repo.get("name"), alias),
            full_name=as_str(repo.get("full_name")) or as_str(repo.get("name"), alias),
            description=as_str(repo.get("description")),
            html_url=as_str(repo.get("html_url")),
            homepage=as_str(repo.get("homepage")),
            default_branch=as_str(repo.get("default_branch")),
            created_at=as_str(repo.get("created_at")),
            updated_at=as_str(repo.get("updated_at")),
            pushed_at=as_str(repo.get("pushed_at")),
            archived=as_bool(repo.get("archived")),
            fork=as_bool(repo.get("fork")),
            private=as_bool(repo.get("private")),
            stars=as_int(repo.get("stargazers_count")),
            forks=as_int(repo.get("forks_count")),
            watchers=as_int(repo.get("watchers_count")),
            open_issues=as_int(repo.get("open_issues_count")),
            size_kb=as_int(repo.get("size")),
            commit_count=as_int(as_object(values.get("commit_count")).get("total")),
            topics=topics,
            license_name=as_str(license_data.get("spdx_id"))
            or as_str(license_data.get("name")),
            owner_login=as_str(owner.get("login"))
            or as_str(as_object(values.get("user")).get("login")),
            languages=languages,
            commits=commits,
            latest_release=latest_release,
            releases=releases,
            contributors=_contributors(values.get("contributors")),
            tags=[as_object(item) for item in as_array(values.get("tags"))],
            deployments=[
                as_object(item) for item in as_array(values.get("deployments"))
            ],
        )
        projects.append(project)
    return sorted(projects, key=lambda project: project.alias.lower())


def normalize_packages(store: JsonObject, prefix: str) -> list[PackageArtifact]:
    result: list[PackageArtifact] = []
    for key, value in store.items():
        if not key.startswith(prefix + ":"):
            continue
        alias = key.split(":", 1)[1]
        if ":" in alias:
            # Companion records such as npm:<alias>:time, merged below.
            continue
        data = as_object(value)
        if prefix == "npm":
            published = as_object(store.get(f"npm:{alias}:time"))
            monthly = as_object(store.get(f"npm:{alias}:downloads"))
            monthly_value = monthly.get("downloads")
            dist = as_object(data.get("dist"))
            deps = as_object(data.get("dependencies"))
            repository = data.get("repository")
            if isinstance(repository, dict):
                repository_url = as_str(repository.get("url"))
            else:
                repository_url = repository if isinstance(repository, str) else ""
            size = as_int(dist.get("unpackedSize"), 0)
            files = as_int(dist.get("fileCount"), 0)
            result.append(
                PackageArtifact(
                    ecosystem="npm",
                    alias=alias,
                    name=as_str(data.get("name"), alias),
                    version=as_str(data.get("version")),
                    description=as_str(data.get("description")),
                    updated_at=as_str(published.get("published_at"))
                    or as_str(dist.get("timestamp"))
                    or as_str(data.get("date")),
                    recent_downloads=as_int(monthly_value)
                    if monthly_value is not None
                    else None,
                    size_bytes=size or None,
                    file_count=files or None,
                    dependency_count=len(deps),
                    license_name=as_str(data.get("license")),
                    repository_url=repository_url,
                    homepage=as_str(data.get("homepage")),
                    raw=data,
                )
            )
        elif prefix == "pypi":
            # Echopoint already reduces PyPI's JSON to these few fields.
            result.append(
                PackageArtifact(
                    ecosystem="pypi",
                    alias=alias,
                    name=as_str(data.get("name"), alias),
                    version=as_str(data.get("version")),
                    description=as_str(data.get("summary")),
                    license_name=as_str(data.get("license")),
                    homepage=as_str(data.get("home_page")),
                    raw=data,
                )
            )
        else:
            crate_data = as_object(data.get("crate"))
            crate = crate_data if crate_data else data
            downloads_value = crate.get("downloads")
            recent_value = crate.get("recent_downloads")
            result.append(
                PackageArtifact(
                    ecosystem="crates",
                    alias=alias,
                    name=as_str(crate.get("name"), alias),
                    version=as_str(crate.get("newest_version"))
                    or as_str(crate.get("max_version")),
                    description=as_str(crate.get("description")),
                    updated_at=as_str(crate.get("updated_at")),
                    downloads=as_int(downloads_value)
                    if downloads_value is not None
                    else None,
                    recent_downloads=as_int(recent_value)
                    if recent_value is not None
                    else None,
                    dependency_count=0,
                    license_name=as_str(crate.get("license")),
                    repository_url=as_str(crate.get("repository")),
                    homepage=as_str(crate.get("homepage"))
                    or as_str(crate.get("documentation")),
                    raw=data,
                )
            )
    return sorted(result, key=lambda package: package.alias.lower())


def normalize_docker(store: JsonObject) -> list[DockerArtifact]:
    result: list[DockerArtifact] = []
    for key, value in store.items():
        if not key.startswith("docker:"):
            continue
        parts = key.split(":")
        alias = parts[1] if len(parts) > 1 else key
        data = as_object(value)
        tags = as_array(data.get("results")) if data else as_array(value)
        result.append(
            DockerArtifact(alias=alias, tags=[as_object(item) for item in tags])
        )
    return sorted(result, key=lambda artifact: artifact.alias.lower())


def normalize_statuses(store: JsonObject) -> list[StatusCheck]:
    result: list[StatusCheck] = []
    for key, value in store.items():
        if not key.startswith("status:"):
            continue
        alias = key.split(":", 1)[1]
        data = as_object(value)
        latency_value = data.get("latency_ms")
        if latency_value is None:
            latency_value = data.get("latency")
        ok = as_bool(data.get("ok"))
        state = as_str(data.get("state")) or ("up" if ok else "unknown")
        status_value = as_int(data.get("status"), 0)
        result.append(
            StatusCheck(
                alias=alias,
                label=as_str(data.get("label"), alias),
                state=state,
                ok=ok,
                status=status_value or None,
                latency_ms=as_float(latency_value),
                checked_at=as_str(data.get("checked_at")),
                url=as_str(data.get("url")),
                error=as_str(data.get("error")),
            )
        )
    return sorted(result, key=lambda status: status.alias.lower())


def normalize_user(store: JsonObject) -> UserSummary:
    summary_key = next(
        (
            key
            for key in store
            if key.startswith("github:") and key.endswith(":summary")
        ),
        None,
    )
    if summary_key is None:
        return UserSummary()

    payload = as_object(store.get(summary_key))
    data_root = as_object(payload.get("data"))
    root = data_root if data_root else payload
    user_object = as_object(root.get("user"))
    user = user_object if user_object else root
    cc = as_object(user.get("contributionsCollection"))
    calendar = as_object(cc.get("contributionCalendar"))

    days: list[ContributionDay] = []
    for week_value in as_array(calendar.get("weeks")):
        week = as_object(week_value)
        for day_value in as_array(week.get("contributionDays")):
            day = as_object(day_value)
            days.append(
                ContributionDay(
                    date=as_str(day.get("date")),
                    count=as_int(day.get("contributionCount")),
                    color=as_str(day.get("color")),
                )
            )

    annual: dict[int, int] = {}
    for key, value in user.items():
        if len(key) == 5 and key.startswith("y") and key[1:].isdigit():
            year = int(key[1:])
            data = as_object(value)
            total = as_int(
                as_object(data.get("contributionCalendar")).get("totalContributions")
            )
            total += as_int(data.get("restrictedContributionsCount"))
            annual[year] = total

    return UserSummary(
        name=as_str(user.get("name")),
        login=as_str(user.get("login"), summary_key.split(":")[1]),
        commits=as_int(cc.get("totalCommitContributions")),
        pull_requests=as_int(cc.get("totalPullRequestContributions")),
        repositories_with_issues=as_int(
            cc.get("totalRepositoriesWithContributedIssues")
        ),
        restricted=as_int(cc.get("restrictedContributionsCount")),
        calendar_total=as_int(calendar.get("totalContributions")),
        contribution_days=days,
        annual_totals=dict(sorted(annual.items())),
    )


def normalize_private_languages(store: JsonObject) -> dict[str, int]:
    """Read Echopoint's sanitized ``github:private:<owner>:langs`` aggregate."""
    totals: dict[str, int] = defaultdict(int)
    for key, value in store.items():
        if not (key.startswith("github:private:") and key.endswith(":langs")):
            continue
        for language, raw_bytes in as_object(as_object(value).get("languages")).items():
            byte_count = as_int(raw_bytes)
            if byte_count > 0:
                totals[language] += byte_count
    return dict(totals)


def normalize_meta(
    store: JsonObject,
    *,
    fetched_at: str,
    from_cache: bool,
    remote_sources: int | None = None,
) -> EngineMeta:
    return EngineMeta(
        last_updated=as_str(store.get("_meta:last_updated")),
        last_run=as_object(store.get("_meta:last_run")),
        fetched_at=fetched_at,
        from_cache=from_cache,
        remote_sources=remote_sources,
    )
