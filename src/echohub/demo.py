from __future__ import annotations

from datetime import date, timedelta

from .types import JsonObject, JsonValue

RepoSeed = tuple[str, str, int, int, int, int, str]


def demo_store() -> JsonObject:
    repos: list[RepoSeed] = [
        (
            "echopoint",
            "JavaScript",
            1,
            20,
            88,
            3410,
            "Edge telemetry and SVG generation engine",
        ),
        (
            "voxelhalla",
            "C",
            4,
            57,
            224,
            11840,
            "Voxel survivor shooter built with raylib",
        ),
        ("8bitaxe", "C", 3, 31, 161, 8820, "Voxel incremental idle game"),
        ("tinyts", "TypeScript", 6, 15, 73, 1940, "Tiny TypeScript experiments"),
        ("journey", "TypeScript", 9, 28, 129, 5360, "JavaScript engine experiments"),
        (
            "svgmetro",
            "JavaScript",
            2,
            19,
            91,
            2270,
            "SVG transit visualization toolkit",
        ),
        ("rubis", "TypeScript", 5, 22, 108, 3120, "Rubik's cube solver"),
    ]
    store: JsonObject = {
        "_meta:last_updated": "2026-08-23T03:58:00.000Z",
        "_meta:last_run": {"success": 42, "failed": 0, "processed": 42, "total": 384},
    }

    for idx, (alias, language, stars, _recent, commits, size, description) in enumerate(
        repos
    ):
        store[f"github:{alias}:repo"] = {
            "name": alias,
            "full_name": f"ujjwalvivek/{alias}",
            "description": description,
            "html_url": f"https://github.com/ujjwalvivek/{alias}",
            "stargazers_count": stars,
            "forks_count": idx % 3,
            "watchers_count": stars,
            "open_issues_count": idx % 4,
            "size": size,
            "default_branch": "main",
            "created_at": f"2025-{(idx % 9) + 1:02d}-10T10:00:00Z",
            "updated_at": f"2026-08-{22 - idx:02d}T18:00:00Z",
            "pushed_at": f"2026-08-{22 - idx:02d}T18:00:00Z",
            "owner": {"login": "ujjwalvivek"},
            "topics": [language.lower(), "showcase"],
            "license": {"spdx_id": "MIT"},
        }
        second_language = "Python" if idx % 2 else "HTML"
        store[f"github:{alias}:langs"] = {
            language: size * 100,
            second_language: size * 17,
            "CSS": size * 7,
        }
        store[f"github:{alias}:commit_count"] = {"total": commits}
        commit_rows: list[JsonValue] = []
        messages = (
            "feat: tighten the core loop",
            "fix: remove visual artifact",
            "chore: trim build path",
            "perf: reduce draw calls",
            "docs: refresh usage notes",
        )
        for number in range(5):
            commit_rows.append(
                {
                    "sha": f"{idx}{number}" * 8,
                    "message": messages[number],
                    "url": f"https://github.com/ujjwalvivek/{alias}/commit/demo{number}",
                    "author": "Ujjwal Vivek",
                    "date": f"2026-08-{22 - number - idx % 3:02d}T{18 - number:02d}:00:00Z",
                    "additions": 15 + idx * 11 + number * 17,
                    "deletions": 4 + idx * 3 + number * 7,
                }
            )
        store[f"github:{alias}:commits"] = commit_rows
        store[f"github:{alias}:contributors"] = [
            {"login": "ujjwalvivek", "contributions": commits}
        ]
        store[f"github:{alias}:tags"] = [{"name": f"v0.{idx + 1}.0"}]
        store[f"github:{alias}:deployments"] = []
        release: JsonObject = {
            "tag_name": f"v0.{idx + 1}.0",
            "name": f"v0.{idx + 1}.0",
            "published_at": f"2026-08-{15 - idx:02d}T12:00:00Z",
            "html_url": f"https://github.com/ujjwalvivek/{alias}/releases",
        }
        store[f"github:{alias}:release"] = release
        store[f"github:{alias}:releases"] = [release]
        store[f"github:{alias}:user"] = {"login": "ujjwalvivek", "name": "Ujjwal Vivek"}

    packages = [("journey", "1.4.1"), ("tinyts", "0.8.0"), ("svgmetro", "0.5.3")]
    for idx, (alias, version) in enumerate(packages):
        dependencies: JsonObject = {"demo-dep": "^1.0.0"} if idx == 0 else {}
        store[f"npm:{alias}"] = {
            "name": alias,
            "version": version,
            "description": f"{alias} package",
            "license": "MIT",
            "homepage": f"https://example.invalid/{alias}",
            "repository": {"url": f"git+https://github.com/ujjwalvivek/{alias}.git"},
            "dependencies": dependencies,
            "dist": {"unpackedSize": 140_000 + idx * 55_000, "fileCount": 14 + idx * 5},
        }

    store["crates:journey"] = {
        "crate": {
            "name": "journey",
            "newest_version": "0.3.2",
            "downloads": 1830,
            "recent_downloads": 244,
            "description": "Journey crate",
            "license": "MIT",
            "repository": "https://github.com/ujjwalvivek/journey",
            "updated_at": "2026-08-20T10:00:00Z",
        }
    }
    store["docker:echopoint:tags"] = {
        "results": [
            {
                "name": "latest",
                "last_updated": "2026-08-21T10:00:00Z",
                "full_size": 24_800_000,
                "images": [{"architecture": "amd64"}, {"architecture": "arm64"}],
            },
            {"name": "0.1.0"},
        ]
    }
    store["status:site"] = {
        "alias": "site",
        "label": "Portfolio",
        "state": "up",
        "ok": True,
        "status": 200,
        "latency_ms": 84,
        "checked_at": "2026-08-23T03:57:00Z",
        "url": "https://ujjwalvivek.com",
    }
    store["status:api"] = {
        "alias": "api",
        "label": "Echopoint API",
        "state": "up",
        "ok": True,
        "status": 200,
        "latency_ms": 42,
        "checked_at": "2026-08-23T03:57:00Z",
        "url": "https://echopoint.ujjwalvivek.com/v1/health",
    }

    today = date(2026, 8, 23)
    days: list[JsonValue] = []
    calendar_total = 0

    for offset in range(364, -1, -1):
        day = today - timedelta(days=offset)
        count = (day.day * 3 + day.month * 2 + offset) % 8
        if day.weekday() >= 5:
            count //= 2
        calendar_total += count
        days.append(
            {
                "date": day.isoformat(),
                "contributionCount": count,
                "color": "#a6e3a1" if count else "#313244",
            }
        )

    weeks: list[JsonValue] = []

    for index in range(0, len(days), 7):
        week: JsonObject = {
            "contributionDays": days[index : index + 7],
        }
        weeks.append(week)

    user: JsonObject = {
        "name": "Ujjwal Vivek",
        "login": "ujjwalvivek",
        "contributionsCollection": {
            "totalCommitContributions": 724,
            "totalPullRequestContributions": 38,
            "totalRepositoriesWithContributedIssues": 17,
            "restrictedContributionsCount": 0,
            "contributionCalendar": {
                "totalContributions": calendar_total,
                "weeks": weeks,
            },
        },
    }
    annual_totals = {
        2016: 94,
        2017: 176,
        2018: 232,
        2019: 318,
        2020: 401,
        2021: 522,
        2022: 611,
        2023: 702,
        2024: 808,
        2025: 997,
        2026: 684,
    }
    for year, total in annual_totals.items():
        user[f"y{year}"] = {
            "contributionCalendar": {"totalContributions": total},
            "restrictedContributionsCount": 0,
        }
    store["github:ujjwalvivek:summary"] = {"data": {"user": user}}
    return store
