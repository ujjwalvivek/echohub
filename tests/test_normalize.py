from echohub.analytics import build_analytics
from echohub.demo import demo_store
from echohub.normalize import (
    normalize_docker,
    normalize_packages,
    normalize_private_languages,
    normalize_projects,
    normalize_statuses,
    normalize_user,
)
from echohub.types import JsonObject


def test_demo_normalizes_all_families():
    store = demo_store()
    projects = normalize_projects(store)
    npm = normalize_packages(store, "npm")
    crates = normalize_packages(store, "crates")
    docker = normalize_docker(store)
    statuses = normalize_statuses(store)
    user = normalize_user(store)

    assert len(projects) == 7
    assert {p.alias for p in projects} >= {"echopoint", "voxelhalla", "journey"}
    assert len(npm) == 3
    assert npm[0].size_bytes is not None
    assert len(crates) == 1
    assert crates[0].recent_downloads == 244
    assert len(docker) == 1
    assert docker[0].latest_size_bytes == 24_800_000
    assert len(statuses) == 2
    assert user.login == "ujjwalvivek"
    assert 2026 in user.annual_totals
    assert len(user.contribution_days) >= 350


def test_project_commit_enrichment_survives_normalization():
    project = next(
        p for p in normalize_projects(demo_store()) if p.alias == "echopoint"
    )
    assert project.commits
    assert project.commits[0].additions > 0
    assert project.commits[0].deletions > 0
    assert project.commit_count == 88
    assert project.dominant_language == "JavaScript"


def test_analytics_are_shared_visual_projections():
    store = demo_store()
    projects = normalize_projects(store)
    npm = normalize_packages(store, "npm")
    crates = normalize_packages(store, "crates")
    docker = normalize_docker(store)
    analytics = build_analytics(projects, npm, crates, docker)
    assert analytics.totals["projects"] == 7
    assert analytics.totals["commits"] > 0
    assert analytics.languages[0].bytes > 0
    assert len(analytics.constellation_nodes) == len(projects)
    assert analytics.commit_wave
    assert analytics.ecosystem_links


def test_private_language_aggregate_is_not_a_project():
    store = demo_store()
    store["github:private:ujjwalvivek:langs"] = {
        "languages": {"Rust": 1200, "Go": 300, "Bad": "x"},
        "repositories": 7,
        "complete": True,
    }
    aliases = {p.alias for p in normalize_projects(store)}
    assert "private" not in aliases
    assert normalize_private_languages(store) == {"Rust": 1200, "Go": 300}


def test_private_language_aggregate_missing_or_malformed():
    assert normalize_private_languages({}) == {}
    assert normalize_private_languages({"github:private:x:langs": [1, 2]}) == {}


def test_projects_tolerate_partial_and_malformed_records():
    store: JsonObject = {
        "github:only-langs:langs": {"Rust": 10, "Neg": -1},
        "github:junk:repo": "not an object",
        "github:empty:tags": [],
        "github:ujjwalvivek:summary": {"user": {}},
    }
    projects = {p.alias: p for p in normalize_projects(store)}
    assert set(projects) == {"only-langs"}, "records with no usable data are skipped"
    assert projects["only-langs"].languages == {"Rust": 10}


def test_pypi_packages_normalize_from_echopoint_shape():
    store: JsonObject = {
        "pypi:echohub": {
            "name": "echohub",
            "version": "2.0.1",
            "summary": "Local-first telemetry deck.",
            "requires_python": ">=3.11",
            "license": "MIT",
            "home_page": None,
        },
        "npm:other": {"name": "other", "version": "1.0.0"},
    }
    (package,) = normalize_packages(store, "pypi")
    assert package.ecosystem == "pypi"
    assert package.name == "echohub"
    assert package.version == "2.0.1"
    assert package.description == "Local-first telemetry deck."
    assert package.homepage == ""
    assert package.raw["requires_python"] == ">=3.11"
