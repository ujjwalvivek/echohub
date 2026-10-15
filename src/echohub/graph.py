"""Repo graph for the Constellation view: model plus a small force layout.

Repos link to the languages they are mostly written in, and each language is
a hub node, the way Obsidian draws tags. A d3-style force simulation (charge,
springs, centring, collision) lets clusters form on their own: single-language
repos ring their hub, mixed repos settle between hubs.

No Qt here, so the layout is deterministic and testable.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field

from .models import Project

MIN_SHARE = 0.08  # a language under 8% of a repo's code gets no link
MAX_LINKS = 3  # per repo


@dataclass(slots=True)
class GraphNode:
    id: str
    label: str
    kind: str  # "repo" or "language"
    language: str  # its own name for hubs, the dominant one for repos
    weight: float  # 0..1, sqrt-scaled code bytes within its kind
    private: bool = False
    code: int = 0  # bytes: the repo's, or the language's total
    x: float = 0.0
    y: float = 0.0
    vx: float = 0.0
    vy: float = 0.0
    # While dragged, the node is pinned here and forces leave it alone.
    pinned: tuple[float, float] | None = None

    @property
    def radius(self) -> float:
        if self.kind == "language":
            return 7.0 + 9.0 * self.weight
        return 3.5 + 7.5 * self.weight


@dataclass(slots=True)
class GraphLink:
    source: str
    target: str
    share: float  # the language's share of the repo's code


@dataclass(slots=True)
class RepoGraph:
    nodes: list[GraphNode] = field(default_factory=list)
    links: list[GraphLink] = field(default_factory=list)

    def node(self, node_id: str) -> GraphNode | None:
        return next((node for node in self.nodes if node.id == node_id), None)

    def neighbours(self, node_id: str) -> set[str]:
        found: set[str] = set()
        for link in self.links:
            if link.source == node_id:
                found.add(link.target)
            elif link.target == node_id:
                found.add(link.source)
        return found


def language_id(language: str) -> str:
    return f"lang:{language}"


def _hash_unit(value: str, salt: str) -> float:
    digest = hashlib.sha256(f"{salt}:{value}".encode()).digest()
    return int.from_bytes(digest[:4], "big") / 2**32


def build_graph(projects: list[Project]) -> RepoGraph:
    graph = RepoGraph()
    totals: dict[str, int] = {}
    links: list[GraphLink] = []
    for project in projects:
        code = project.language_bytes
        if not code:
            continue
        ranked = sorted(project.languages.items(), key=lambda item: -item[1])
        for language, value in ranked[:MAX_LINKS]:
            share = value / code
            if share < MIN_SHARE:
                continue
            links.append(GraphLink(project.alias, language_id(language), share))
            totals[language] = totals.get(language, 0) + value

    max_code = max((project.language_bytes for project in projects), default=0) or 1
    max_total = max(totals.values(), default=0) or 1
    for project in projects:
        graph.nodes.append(
            GraphNode(
                id=project.alias,
                label=project.alias,
                kind="repo",
                language=project.dominant_language,
                weight=math.sqrt(project.language_bytes / max_code),
                private=project.private,
                code=project.language_bytes,
            )
        )
    for language, total in sorted(totals.items(), key=lambda item: -item[1]):
        graph.nodes.append(
            GraphNode(
                id=language_id(language),
                label=language,
                kind="language",
                language=language,
                weight=math.sqrt(total / max_total),
                code=total,
            )
        )
    graph.links = links
    _seed(graph)
    return graph


def _seed(graph: RepoGraph) -> None:
    """Deterministic start: a phyllotaxis spiral, hubs first, order by hash."""
    ordered = sorted(
        graph.nodes,
        key=lambda node: (node.kind != "language", _hash_unit(node.id, "o")),
    )
    golden = math.pi * (3 - math.sqrt(5))
    for index, node in enumerate(ordered):
        radius = 12 * math.sqrt(index + 0.5)
        angle = index * golden
        node.x = radius * math.cos(angle)
        node.y = radius * math.sin(angle)
        node.vx = node.vy = 0.0


class ForceLayout:
    """d3-force in miniature. Call ``step`` until ``settled``; ``reheat`` after
    a drag so the graph flows around the moved node."""

    ALPHA_MIN = 0.002
    ALPHA_DECAY = 1 - ALPHA_MIN ** (1 / 300)  # cools in ~300 ticks
    VELOCITY_DECAY = 0.42
    LINK_DISTANCE = 58.0
    CHARGE_REPO = -120.0
    CHARGE_HUB = -320.0
    CENTRE_PULL = 0.04

    def __init__(self, graph: RepoGraph) -> None:
        self.graph = graph
        self.alpha = 1.0
        self._index = {node.id: node for node in graph.nodes}
        degree: dict[str, int] = dict.fromkeys(self._index, 0)
        for link in graph.links:
            degree[link.source] += 1
            degree[link.target] += 1
        # d3's defaults: a link pulls the lower-degree end harder, so hubs
        # stay put and their repos come to them.
        self._links = [
            (
                self._index[link.source],
                self._index[link.target],
                1 / max(1, min(degree[link.source], degree[link.target])),
                degree[link.source] / max(1, degree[link.source] + degree[link.target]),
                link.share,
            )
            for link in graph.links
            if link.source in self._index and link.target in self._index
        ]

    @property
    def settled(self) -> bool:
        return self.alpha < self.ALPHA_MIN

    def reheat(self, alpha: float = 0.3) -> None:
        self.alpha = max(self.alpha, alpha)

    def run(self, ticks: int) -> None:
        for _ in range(ticks):
            if self.settled:
                return
            self.step()

    def step(self) -> None:
        alpha = self.alpha
        nodes = self.graph.nodes
        self._links_force(alpha)
        self._charge(nodes, alpha)
        self._collide(nodes)
        for node in nodes:
            if node.pinned is not None:
                node.x, node.y = node.pinned
                node.vx = node.vy = 0.0
                continue
            node.vx -= node.x * self.CENTRE_PULL * alpha
            node.vy -= node.y * self.CENTRE_PULL * alpha
            node.vx *= 1 - self.VELOCITY_DECAY
            node.vy *= 1 - self.VELOCITY_DECAY
            node.x += node.vx
            node.y += node.vy
        self.alpha += (0.0 - alpha) * self.ALPHA_DECAY

    def _links_force(self, alpha: float) -> None:
        for source, target, strength, bias, share in self._links:
            dx = target.x + target.vx - source.x - source.vx
            dy = target.y + target.vy - source.y - source.vy
            distance = math.hypot(dx, dy) or 1e-6
            # A repo sits closer to the language it is mostly made of.
            rest = (
                self.LINK_DISTANCE * (1.25 - 0.5 * share)
                + source.radius
                + target.radius
            )
            pull = (distance - rest) / distance * alpha * strength
            dx *= pull
            dy *= pull
            target.vx -= dx * bias
            target.vy -= dy * bias
            source.vx += dx * (1 - bias)
            source.vy += dy * (1 - bias)

    def _charge(self, nodes: list[GraphNode], alpha: float) -> None:
        count = len(nodes)
        for i in range(count):
            a = nodes[i]
            charge_a = self.CHARGE_HUB if a.kind == "language" else self.CHARGE_REPO
            for j in range(i + 1, count):
                b = nodes[j]
                charge_b = self.CHARGE_HUB if b.kind == "language" else self.CHARGE_REPO
                dx = b.x - a.x
                dy = b.y - a.y
                square = dx * dx + dy * dy
                if square < 1:
                    # Coincident: nudge apart along a stable direction.
                    dx = 0.5 + _hash_unit(a.id + b.id, "j") * 0.5
                    dy = 0.5 - _hash_unit(b.id + a.id, "j") * 0.5
                    square = dx * dx + dy * dy
                if square > 360_000:  # beyond 600 units nobody feels it
                    continue
                a.vx += dx * charge_b * alpha / square
                a.vy += dy * charge_b * alpha / square
                b.vx -= dx * charge_a * alpha / square
                b.vy -= dy * charge_a * alpha / square

    def _collide(self, nodes: list[GraphNode]) -> None:
        count = len(nodes)
        for i in range(count):
            a = nodes[i]
            for j in range(i + 1, count):
                b = nodes[j]
                reach = a.radius + b.radius + 10
                dx = b.x + b.vx - a.x - a.vx
                dy = b.y + b.vy - a.y - a.vy
                square = dx * dx + dy * dy
                if square >= reach * reach:
                    continue
                distance = math.sqrt(square) or 1e-6
                push = (reach - distance) / distance * 0.5
                dx *= push
                dy *= push
                b.vx += dx * 0.5
                b.vy += dy * 0.5
                a.vx -= dx * 0.5
                a.vy -= dy * 0.5
