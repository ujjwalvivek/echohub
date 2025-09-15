from echohub.analytics import build_analytics
from echohub.demo import demo_store
from echohub.normalize import (
    normalize_docker,
    normalize_packages,
    normalize_projects,
    normalize_statuses,
    normalize_user,
)


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
