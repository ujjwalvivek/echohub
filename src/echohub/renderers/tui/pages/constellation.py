"""Constellation: repos linked to the languages they're written in.

The same graph and force layout as the desktop view (``graph.py``), settled
once and drawn on the character grid: hubs as rings in their language
colour, repos as dots, links as dotted lines. Selecting a node lights its
links and dims everything outside it and its neighbours.

Three levels, Enter to go down and Esc to come back: the graph's nodes, a
language's repos, then a repo's details.
"""

from __future__ import annotations

from dataclasses import dataclass

from .... import palette as P
from ....formatting import human_bytes
from ....graph import ForceLayout, GraphLink, GraphNode, RepoGraph, build_graph
from ....models import DashboardState, Project
from ..style import RESET, fg, fit, hjoin, paint, spread, surface
from ..widgets import page_title, private_mark, section
from .base import Context, Page, list_moves
from .detail import project_detail

SIDE = 34
SIDE_FROM = 100
SETTLE_TICKS = 400
# Terminal cells are about twice as tall as wide.
CELL_ASPECT = 2.0
MARGIN_X = 10
MARGIN_Y = 1


@dataclass(slots=True)
class _Cell:
    char: str = " "
    colour: str = P.BASE
    bold: bool = False


class ConstellationPage(Page):
    name = "Constellation"
    keys = (
        ("j k", "select the next or previous node (languages first)"),
        ("Enter / l", "a language: step into its repos; a repo: its details"),
        ("Esc / h", "back up one level"),
        ("o", "open the selected repo on GitHub"),
    )

    def __init__(self, ctx: Context) -> None:
        super().__init__(ctx)
        self.projects: dict[str, Project] = {}
        self.graph: RepoGraph | None = None
        self._source: list[Project] = []
        self.order: list[GraphNode] = []
        self.index = 0
        # Inside a language: its repos are listed and ``child`` picks one.
        self.inside = False
        self.child = 0
        self.detail_open = False

    def set_state(self, state: DashboardState) -> None:
        self._source = state.projects
        self.projects = {project.alias: project for project in state.projects}
        self.graph = None  # laid out on first view, not at startup

    def _ensure_graph(self) -> RepoGraph:
        if self.graph is None:
            graph = build_graph(self._source)
            ForceLayout(graph).run(SETTLE_TICKS)
            hubs = sorted(
                (n for n in graph.nodes if n.kind == "language"), key=lambda n: -n.code
            )
            repos = sorted(
                (n for n in graph.nodes if n.kind == "repo"),
                key=lambda n: n.label.lower(),
            )
            selected = self.order[self.index].id if self.order else ""
            self.order = hubs + repos
            ids = [node.id for node in self.order]
            self.index = ids.index(selected) if selected in ids else 0
            self.graph = graph
        return self.graph

    @property
    def selected(self) -> GraphNode | None:
        return self.order[self.index] if self.order else None

    def hub_links(self, node: GraphNode | None) -> list[GraphLink]:
        """A language's repos, the ones it makes up most of first."""
        if self.graph is None or node is None or node.kind != "language":
            return []
        links = [link for link in self.graph.links if link.target == node.id]
        return sorted(links, key=lambda link: (-link.share, link.source.lower()))

    @property
    def repo(self) -> GraphNode | None:
        """The repo Enter, o and the details act on: the repo picked inside a
        language, or the selected node when it is a repo."""
        node = self.selected
        if self.inside and self.graph is not None:
            links = self.hub_links(node)
            if not links:
                return None
            return self.graph.node(links[min(self.child, len(links) - 1)].source)
        return node if node is not None and node.kind == "repo" else None

    def render(self, cells: int, rows: int) -> list[str]:
        graph = self._ensure_graph()
        repo = self.repo
        if self.detail_open and repo is not None:
            where = (
                self.selected.label
                if self.inside and self.selected
                else "Constellation"
            )
            back = paint("Esc", P.ACCENT) + paint(f" back to {where}", P.MUTED)
            return [back, ""] + project_detail(
                self.projects.get(repo.id), min(cells, 100)
            )[: rows - 2]
        repos = sum(1 for n in graph.nodes if n.kind == "repo")
        hubs = len(graph.nodes) - repos
        lines = [
            page_title(
                "Constellation", f"{repos} repos linked to {hubs} languages", cells
            ),
            "",
        ]
        body = rows - len(lines)
        if cells >= SIDE_FROM:
            plot = cells - SIDE - 3
            side = self._side(SIDE, body)
            return lines + hjoin(
                (self._plot(graph, plot, body), plot), (side, SIDE), gap=3
            )
        if self.inside:
            # No room beside the graph: the repo list takes the page.
            return lines + self._side(cells, body)
        info = self._side(cells, 4)[:3]
        return lines + self._plot(graph, cells, body - len(info)) + info

    def _side(self, cells: int, rows: int) -> list[str]:
        graph = self.graph
        node = self.selected
        if graph is None or node is None:
            return [paint("No repos with code yet", P.MUTED)]
        colour = P.series_color(node.language)
        links = [link for link in graph.links if node.id in (link.source, link.target)]
        if node.kind == "language":
            hint = (
                paint("Enter", P.ACCENT)
                + paint(" details · ", P.MUTED)
                + paint("Esc", P.ACCENT)
                + paint(" back", P.MUTED)
                if self.inside
                else paint("Enter", P.ACCENT) + paint(" step into its repos", P.MUTED)
            )
            lines = [
                paint("◉ ", colour) + paint(node.label, colour, bold=True),
                paint(
                    f"{human_bytes(node.code)} of code · {len(links)} repos", P.MUTED
                ),
                hint,
                section("Repos", str(len(links)), cells),
            ]
            hub_links = self.hub_links(node)
            self.child = max(0, min(self.child, len(hub_links) - 1))
            room = max(1, rows - len(lines) - 2)
            start = max(0, min(self.child - room // 2, len(hub_links) - room))
            for index, link in enumerate(hub_links[start : start + room], start):
                repo = graph.node(link.source)
                private = repo.private if repo is not None else False
                chosen = self.inside and index == self.child
                row = spread(
                    private_mark(private)
                    + paint(link.source, P.TEXT if chosen else P.SUBTLE),
                    paint(f"{link.share:.0%}", P.SUBTLE),
                    cells - 2,
                )
                if chosen:
                    lines.append(
                        surface(paint("▌", P.ACCENT) + " " + row, cells, P.SELECTED)
                    )
                else:
                    lines.append("  " + row)
        else:
            lines = [
                private_mark(node.private) + paint(node.label, P.TEXT, bold=True),
                paint(f"{node.language} · {human_bytes(node.code)}", P.MUTED),
                paint("Enter", P.ACCENT)
                + paint(" details · ", P.MUTED)
                + paint("o", P.ACCENT)
                + paint(" GitHub", P.MUTED),
                section("Languages", str(len(links)), cells),
            ]
            for link in sorted(links, key=lambda link: -link.share):
                hub = graph.node(link.target)
                name = hub.label if hub is not None else link.target
                lines.append(
                    spread(
                        paint("■ ", P.series_color(name)) + paint(name, P.SUBTLE),
                        paint(f"{link.share:.0%}", P.SUBTLE),
                        cells,
                    )
                )
        if self.inside:
            count = len(self.hub_links(node))
            position = paint(
                f"{self.child + 1} of {count} repos · j k to move", P.MUTED
            )
        else:
            position = paint(
                f"{self.index + 1} of {len(self.order)} · j k to move", P.MUTED
            )
        lines = lines[: max(1, rows - 2)]
        return [fit(line, cells) for line in lines] + ["", position]

    def _plot(self, graph: RepoGraph, cells: int, rows: int) -> list[str]:
        if rows < 3 or not graph.nodes:
            return []
        grid = [[_Cell() for _ in range(cells)] for _ in range(rows)]
        xs = [n.x for n in graph.nodes]
        ys = [n.y for n in graph.nodes]
        span_x = (max(xs) - min(xs)) or 1.0
        span_y = (max(ys) - min(ys)) or 1.0
        # One scale for both axes, so clusters keep their shape on tall
        # cells; margins leave room for labels at the edges.
        room_x = max(1, cells - 2 * MARGIN_X)
        room_y = max(1, rows - 1 - 2 * MARGIN_Y)
        scale = min(room_x / span_x, room_y * CELL_ASPECT / span_y)
        left = (cells - span_x * scale) / 2
        top = (rows - 1 - span_y * scale / CELL_ASPECT) / 2

        def place(node: GraphNode) -> tuple[int, int]:
            col = round(left + (node.x - min(xs)) * scale)
            row = round(top + (node.y - min(ys)) * scale / CELL_ASPECT)
            return max(0, min(cells - 1, col)), max(0, min(rows - 1, row))

        spots = {node.id: place(node) for node in graph.nodes}
        focus = self.selected
        picked = self.repo.id if self.inside and self.repo is not None else ""
        near = {focus.id} | graph.neighbours(focus.id) if focus is not None else set()

        for link in graph.links:
            lit = focus is not None and focus.id in (link.source, link.target)
            colour = P.ACCENT if lit else P.BORDER_STRONG
            for col, row in _line(spots[link.source], spots[link.target])[1:-1]:
                cell = grid[row][col]
                if cell.char == " " or lit:
                    grid[row][col] = _Cell("·", colour)

        # Hubs over repos, the focus last so nothing hides it.
        def rank(node: GraphNode) -> tuple[bool, bool]:
            return (node.id == (focus.id if focus else ""), node.kind == "language")

        for node in sorted(graph.nodes, key=rank):
            col, row = spots[node.id]
            colour = P.series_color(node.language)
            if node.id not in near:
                colour = P.blend(P.BASE, colour, 0.55)
            char = "◉" if node.kind == "language" else "●"
            if focus is not None and node.id == focus.id:
                char = "◉" if node.kind == "language" else "◆"
            if node.id == picked:
                char = "◆"
            grid[row][col] = _Cell(char, colour, bold=node.kind == "language")

        # Labels in priority order (focus, hubs, neighbours, bigger repos);
        # one that would cover another node or label is skipped.
        def priority(node: GraphNode) -> tuple[bool, bool, bool, bool, float]:
            return (
                node.id != picked,
                node.id != (focus.id if focus else ""),
                node.kind != "language",
                node.id not in near,
                -node.weight,
            )

        for node in sorted(graph.nodes, key=priority):
            col, row = spots[node.id]
            hub = node.kind == "language"
            colour = P.series_color(node.language) if hub else P.SUBTLE
            if node.id not in near:
                colour = P.blend(P.BASE, colour, 0.55 if hub else 0.45)
            if (focus is not None and node.id == focus.id) or node.id == picked:
                colour = P.TEXT
            _label(grid, col, row, node.label, colour, hub)

        return [_row(cells_row) for cells_row in grid]

    def key(self, key: str) -> bool:
        _ = self._ensure_graph()  # keys may arrive before the first draw
        back = key in ("esc", "backspace", "h", "left")
        down = key in ("enter", "l", "right")
        if self.detail_open:
            if back:
                self.detail_open = False
                return True
            return key == "o" and self._open()
        if self.inside:
            if back:
                self.inside = False
                return True
            move = list_moves(key, 10)
            if move is not None:
                count = len(self.hub_links(self.selected))
                self.child = max(0, min(count - 1, self.child + move))
                return True
            if down and self.repo is not None:
                self.detail_open = True
                return True
            return key == "o" and self._open()
        node = self.selected
        move = list_moves(key, 10)
        if move is not None and self.order:
            self.index = max(0, min(len(self.order) - 1, self.index + move))
            return True
        if down and node is not None:
            if node.kind == "language":
                if self.hub_links(node):
                    self.inside = True
                    self.child = 0
            else:
                self.detail_open = True
            return True
        if key == "o":
            return self._open()
        return False

    def _open(self) -> bool:
        node = self.repo
        project = self.projects.get(node.id) if node is not None else None
        if project is not None and project.html_url:
            self.ctx.open_url(project.html_url)
        return True


def _line(a: tuple[int, int], b: tuple[int, int]) -> list[tuple[int, int]]:
    """Cells from a to b (Bresenham), both ends included."""
    (x0, y0), (x1, y1) = a, b
    dx, dy = abs(x1 - x0), -abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    error = dx + dy
    points: list[tuple[int, int]] = []
    while True:
        points.append((x0, y0))
        if (x0, y0) == (x1, y1):
            return points
        double = 2 * error
        if double >= dy:
            error += dy
            x0 += sx
        if double <= dx:
            error += dx
            y0 += sy


def _label(
    grid: list[list[_Cell]], col: int, row: int, text: str, colour: str, bold: bool
) -> None:
    """Write a label right of its node, else left; skip it if it would cover
    another node or label."""
    width = len(grid[0])
    text = text[:24]
    for start in (col + 2, col - 1 - len(text)):
        end = start + len(text)
        if start < 0 or end > width:
            continue
        span = grid[row][max(0, start - 1) : min(width, end + 1)]
        if all(cell.char in (" ", "·") for cell in span):
            for offset, char in enumerate(text):
                grid[row][start + offset] = _Cell(char, colour, bold)
            return


def _row(cells: list[_Cell]) -> str:
    out: list[str] = []
    current: tuple[str, bool] | None = None
    for cell in cells:
        style = (cell.colour, cell.bold)
        if cell.char == " ":
            if current is not None:
                out.append(RESET)
                current = None
            out.append(" ")
            continue
        if style != current:
            out.append(RESET + ("\x1b[1m" if cell.bold else "") + fg(cell.colour))
            current = style
        out.append(cell.char)
    if current is not None:
        out.append(RESET)
    return "".join(out)
