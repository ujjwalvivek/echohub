import math

from echohub.graph import ForceLayout, build_graph, language_id
from echohub.models import Project


def _projects() -> list[Project]:
    return [
        Project(alias="engine", languages={"Rust": 900, "C": 60, "Shell": 40}),
        Project(alias="site", languages={"TypeScript": 500, "CSS": 500}),
        Project(alias="tool", languages={"Rust": 300}),
        Project(alias="notes"),  # no code: a node, but no links
    ]


def test_repos_link_to_their_main_languages() -> None:
    graph = build_graph(_projects())
    links = {(link.source, link.target) for link in graph.links}
    assert ("engine", language_id("Rust")) in links
    assert ("engine", language_id("Shell")) not in links, "under 8% gets no link"
    assert ("site", language_id("CSS")) in links
    hubs = {node.id for node in graph.nodes if node.kind == "language"}
    assert hubs == {language_id(name) for name in ("Rust", "TypeScript", "CSS")}
    assert graph.neighbours(language_id("Rust")) == {"engine", "tool"}
    assert graph.node("notes") is not None
    assert not graph.neighbours("notes")


def test_layout_is_deterministic_and_settles_apart() -> None:
    first, second = build_graph(_projects()), build_graph(_projects())
    for graph in (first, second):
        layout = ForceLayout(graph)
        layout.run(1000)
        assert layout.settled
    assert [(n.x, n.y) for n in first.nodes] == [(n.x, n.y) for n in second.nodes]
    nodes = first.nodes
    for i, a in enumerate(nodes):
        for b in nodes[i + 1 :]:
            assert math.hypot(a.x - b.x, a.y - b.y) > a.radius + b.radius, (a.id, b.id)


def test_pinned_node_stays_under_the_cursor() -> None:
    graph = build_graph(_projects())
    layout = ForceLayout(graph)
    node = graph.node("tool")
    assert node is not None
    node.pinned = (123.0, -45.0)
    layout.reheat(0.5)
    layout.run(20)
    assert (node.x, node.y) == (123.0, -45.0)
