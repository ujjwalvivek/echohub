
from echohub.analytics import build_analytics, constellation_edges, language_slices
from echohub.demo import demo_store
from echohub.models import PackageArtifact, Project
from echohub.normalize import normalize_projects


def project(alias: str, languages: dict[str, int], **fields: object) -> Project:
    item = Project(alias=alias, name=alias, full_name=f"owner/{alias}")
    item.languages = languages
    for name, value in fields.items():
        setattr(item, name, value)
    return item


def package(alias: str, name: str) -> PackageArtifact:
    return PackageArtifact(ecosystem="npm", alias=alias, name=name, version="1.0.0")


def test_language_slices_sum_shares_and_count_projects() -> None:
    rows = language_slices(
        [
            project("a", {"Rust": 300, "C": 100}),
            project("b", {"Rust": 100, "C": 0}),
        ]
    )
    by_language = {row.language: row for row in rows}
    assert [row.language for row in rows] == ["Rust", "C"]
    assert by_language["Rust"].bytes == 400
    assert by_language["Rust"].projects == 2
    assert by_language["C"].projects == 1, "zero-byte entries are not usage"
    assert abs(sum(row.share for row in rows) - 1.0) < 1e-9


def test_private_language_totals_join_the_ledger_without_projects() -> None:
    rows = language_slices(
        [project("a", {"Rust": 100})], {"Rust": 50, "Go": 250, "Odd": -5}
    )
    by_language = {row.language: row for row in rows}
    assert rows[0].language == "Go"
    assert by_language["Go"].projects == 0
    assert by_language["Go"].private_bytes == 250
    assert by_language["Rust"].bytes == 150
    assert by_language["Rust"].private_bytes == 50
    assert by_language["Odd"].bytes == 0


def test_build_analytics_reports_private_bytes_in_totals() -> None:
    projects = [project("a", {"Rust": 100})]
    analytics = build_analytics(projects, [], [], [], {"Go": 40})
    assert analytics.totals["language_bytes"] == 140
    assert analytics.totals["private_language_bytes"] == 40


def test_constellation_edges_link_similar_projects() -> None:
    projects = normalize_projects(demo_store())
    edges = constellation_edges(projects)
    assert edges
    assert edges == constellation_edges(list(reversed(projects))), "order-independent"
    for edge in edges:
        assert edge.source != edge.target
        assert 0.0 <= edge.similarity <= 1.0


def test_pypi_packages_count_and_link_to_projects() -> None:
    projects = [project("echohub", {})]
    pypi = [PackageArtifact(ecosystem="pypi", alias="echohub", name="echohub")]
    analytics = build_analytics(projects, [], [], [], pypi=pypi)
    assert analytics.totals["packages"] == 1
