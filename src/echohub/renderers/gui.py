from __future__ import annotations

import json
import math
import sys
import threading
import tkinter as tk
from collections.abc import Callable
from datetime import date, timedelta
from importlib.resources import files
from tkinter import ttk
from typing import ClassVar, final

from .. import theme as T
from ..engine import EchopointEngine, ProgressUpdate
from ..formatting import compact, human_bytes, human_kb, relative_time, short_date
from ..models import (
    ConstellationEdge,
    ConstellationNode,
    ContributionDay,
    DashboardState,
    Project,
)

FONT = ("Consolas", 10)
FONT_SMALL = ("Consolas", 9)
FONT_TINY = ("Consolas", 8)
FONT_BOLD = ("Consolas", 10, "bold")
FONT_TITLE = ("Consolas", 21, "bold")

ScrollWidget = tk.Canvas | tk.Listbox | tk.Text | ttk.Treeview


def _blend(a: str, b: str, t: float) -> str:
    t = max(0.0, min(1.0, t))
    av = [int(a[i : i + 2], 16) for i in (1, 3, 5)]
    bv = [int(b[i : i + 2], 16) for i in (1, 3, 5)]
    vals = [round(x + (y - x) * t) for x, y in zip(av, bv)]
    return "#" + "".join(f"{v:02x}" for v in vals)


def _colorref(hex_color: str) -> int:
    """Convert #RRGGBB to the COLORREF integer used by DWM."""
    value = hex_color.lstrip("#")
    r, g, b = (int(value[i : i + 2], 16) for i in (0, 2, 4))
    return r | (g << 8) | (b << 16)


def _apply_native_window_theme(root: tk.Tk) -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id()) or root.winfo_id()
        enabled = ctypes.c_int(1)
        # 20 is current DWMWA_USE_IMMERSIVE_DARK_MODE; 19 is the older build fallback.
        for attribute in (20, 19):
            try:
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, attribute, ctypes.byref(enabled), ctypes.sizeof(enabled)
                )
                break
            except (AttributeError, OSError):
                continue
        for attribute, color in ((34, T.SURFACE0), (35, T.MANTLE), (36, T.TEXT)):
            try:
                value = ctypes.c_int(_colorref(color))
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value)
                )
            except (AttributeError, OSError):
                continue
    except (AttributeError, OSError, tk.TclError):
        # Native chrome polish should never prevent the app from launching.
        return


@final
class DashboardGui:
    views: ClassVar[tuple[str, ...]] = (
        "Pulse",
        "Projects",
        "Constellation",
        "Activity",
        "Ecology",
        "Contributions",
        "Sources",
        "Inspector",
    )

    def __init__(self, engine: EchopointEngine):
        self.engine = engine
        self.root = tk.Tk()
        self.root.title("Echohub")
        self.root.geometry("1500x900")
        self.root.minsize(1080, 680)
        self.root.configure(bg=T.BASE)
        self._app_icon = None
        self._apply_identity()
        self.view = 0
        self.progress: ProgressUpdate | None = None
        self.worker: threading.Thread | None = None
        self.nav_buttons: list[tk.Button] = []
        self.content_cleanup: Callable[[], None] | None = None
        self._const_scale = 1.0
        self._const_ox = 0.0
        self._const_oy = 0.0
        self._const_drag: tuple[int, int] | None = None
        self._const_hover: str | None = None
        self._const_selected: str | None = None
        self._project_sort: tuple[str, bool] = ("pushed", True)
        self._phase = 0.0
        self.const_canvas: tk.Canvas | None = None
        self.const_detail: tk.Frame | None = None
        self._const_nodes: dict[str, ConstellationNode] = {}
        self._const_projects: dict[str, Project] = {}
        self._const_edges: list[ConstellationEdge] = []
        self._const_drag_start: tuple[int, int] | None = None
        self._contrib_cells: list[tuple[int, ContributionDay]] = []
        self._style()
        self._build_shell()
        self.root.bind("<Key>", self._key)
        self.root.after(40, self._tick)
        self.root.after(80, lambda: _apply_native_window_theme(self.root))

    def _apply_identity(self) -> None:
        try:
            asset_root = files("echohub").joinpath("assets")
            png = asset_root.joinpath("echohub-64.png")
            self._app_icon = tk.PhotoImage(file=str(png))
            self.root.iconphoto(True, self._app_icon)
            if sys.platform == "win32":
                try:
                    self.root.iconbitmap(
                        default=str(asset_root.joinpath("echohub.ico"))
                    )
                except tk.TclError:
                    pass
        except (OSError, tk.TclError):
            self._app_icon = None

    def _style(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            "Mocha.Treeview",
            background=T.MANTLE,
            fieldbackground=T.MANTLE,
            foreground=T.SUBTEXT1,
            rowheight=29,
            borderwidth=0,
            relief="flat",
            font=FONT_SMALL,
        )
        style.layout(
            "Mocha.Treeview",
            [
                (
                    "Treeview.treearea",
                    {
                        "sticky": "nswe",
                    },
                ),
            ],
        )
        style.map(
            "Mocha.Treeview",
            background=[("selected", T.SURFACE1)],
            foreground=[("selected", T.TEXT)],
        )
        style.configure(
            "Mocha.Treeview.Heading",
            background=T.SURFACE0,
            foreground=T.SUBTEXT1,
            borderwidth=0,
            relief="flat",
            font=("Consolas", 9, "bold"),
            padding=(8, 7),
        )
        style.map("Mocha.Treeview.Heading", background=[("active", T.SURFACE1)])
        style.configure(
            "Mocha.Horizontal.TProgressbar",
            troughcolor=T.SURFACE0,
            background=T.BLUE,
            borderwidth=0,
            lightcolor=T.BLUE,
            darkcolor=T.BLUE,
        )

    def _build_shell(self) -> None:
        rail = tk.Frame(
            self.root,
            bg=T.MANTLE,
            width=214,
            highlightthickness=1,
            highlightbackground=T.SURFACE0,
        )
        rail.pack(side="left", fill="y")
        rail.pack_propagate(False)
        brand = tk.Frame(rail, bg=T.MANTLE)
        brand.pack(fill="x", padx=17, pady=(19, 17))
        if self._app_icon is not None:
            mark = tk.Label(
                brand, image=self._app_icon, bg=T.MANTLE, bd=0, highlightthickness=0
            )
        else:
            mark = tk.Label(
                brand,
                text="EH",
                bg=T.BASE,
                fg=T.BLUE,
                width=3,
                height=1,
                font=("Consolas", 11, "bold"),
                highlightthickness=1,
                highlightbackground=T.BLUE,
            )
        mark.pack(side="left", padx=(0, 10))
        brand_text = tk.Frame(brand, bg=T.MANTLE)
        brand_text.pack(side="left")
        tk.Label(
            brand_text,
            text="ECHOHUB",
            bg=T.MANTLE,
            fg=T.TEXT,
            font=("Consolas", 16, "bold"),
            anchor="w",
        ).pack(fill="x")
        tk.Label(
            brand_text,
            text="TELEMETRY DECK",
            bg=T.MANTLE,
            fg=T.OVERLAY1,
            font=("Consolas", 8),
            anchor="w",
        ).pack(fill="x")
        tk.Frame(rail, bg=T.SURFACE0, height=1).pack(fill="x")
        nav_icons = ("◉", "▤", "✦", "↯", "◫", "▦", "⬢", "{}")
        for idx, label in enumerate(self.views):
            b = tk.Button(
                rail,
                text=f"{nav_icons[idx]:2}  {label.upper()}",
                command=lambda i=idx: self._set_view(i),
                bg=T.MANTLE,
                fg=T.SUBTEXT0,
                activebackground=T.SURFACE0,
                activeforeground=T.TEXT,
                relief="flat",
                bd=0,
                highlightthickness=0,
                anchor="w",
                padx=17,
                pady=10,
                font=("Consolas", 9, "bold"),
                cursor="hand2",
            )
            b.pack(fill="x", pady=1)
            self.nav_buttons.append(b)
        tk.Frame(rail, bg=T.MANTLE).pack(fill="both", expand=True)
        hints = tk.Frame(rail, bg=T.MANTLE)
        hints.pack(fill="x", padx=17, pady=15)
        for key, label in (
            ("R", "refresh"),
            ("C", "check changes"),
            ("1–8", "switch view"),
        ):
            row = tk.Frame(hints, bg=T.MANTLE)
            row.pack(fill="x", pady=2)
            tk.Label(
                row,
                text=key,
                bg=T.SURFACE0,
                fg=T.SUBTEXT1,
                font=FONT_TINY,
                padx=5,
                pady=2,
            ).pack(side="left")
            tk.Label(row, text=label, bg=T.MANTLE, fg=T.OVERLAY1, font=FONT_TINY).pack(
                side="left", padx=7
            )

        main = tk.Frame(self.root, bg=T.BASE)
        main.pack(side="left", fill="both", expand=True)
        header = tk.Frame(
            main,
            bg=T.BASE,
            height=74,
            highlightthickness=1,
            highlightbackground=T.SURFACE0,
        )
        header.pack(fill="x")
        header.pack_propagate(False)
        left = tk.Frame(header, bg=T.BASE)
        left.pack(side="left", padx=24, fill="y")
        self.title_var = tk.StringVar(value="PULSE")
        tk.Label(
            left, textvariable=self.title_var, bg=T.BASE, fg=T.TEXT, font=FONT_TITLE
        ).pack(side="left", pady=22)
        self.meta_var = tk.StringVar(value="")
        tk.Label(
            left, textvariable=self.meta_var, bg=T.BASE, fg=T.OVERLAY1, font=FONT_TINY
        ).pack(side="left", padx=18, pady=26)
        self.refresh_btn = self._button(header, "REFRESH", self._refresh, primary=True)
        self.refresh_btn.pack(side="right", padx=(7, 24), pady=18)
        self.check_btn = self._button(header, "CHECK", self._check)
        self.check_btn.pack(side="right", padx=0, pady=18)

        self.content = tk.Frame(main, bg=T.BASE)
        self.content.pack(fill="both", expand=True, padx=20, pady=16)
        statusbar = tk.Frame(
            main,
            bg=T.MANTLE,
            height=34,
            highlightthickness=1,
            highlightbackground=T.SURFACE0,
        )
        statusbar.pack(fill="x", side="bottom")
        statusbar.pack_propagate(False)
        self.status_var = tk.StringVar(value="READY")
        tk.Label(
            statusbar,
            textvariable=self.status_var,
            bg=T.MANTLE,
            fg=T.OVERLAY1,
            font=FONT_TINY,
            anchor="w",
        ).pack(side="left", padx=15)
        self.progressbar = ttk.Progressbar(
            statusbar,
            length=170,
            mode="determinate",
            style="Mocha.Horizontal.TProgressbar",
        )
        self._progressbar_visible = False
        self._set_view(0)

    def _button(
        self,
        parent: tk.Misc,
        text: str,
        command: Callable[[], object],
        *,
        primary: bool = False,
    ) -> tk.Button:
        return tk.Button(
            parent,
            text=text,
            command=command,
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=T.BLUE if primary else T.SURFACE0,
            cursor="hand2",
            bg=T.BLUE if primary else T.MANTLE,
            fg=T.CRUST if primary else T.SUBTEXT1,
            activebackground=T.SAPPHIRE if primary else T.SURFACE0,
            activeforeground=T.CRUST if primary else T.TEXT,
            font=("Consolas", 9, "bold"),
            padx=13,
            pady=7,
        )

    def _entry(
        self, parent: tk.Misc, var: tk.StringVar | None = None, width: int = 30
    ) -> tk.Entry:
        if var is None:
            return tk.Entry(
                parent,
                width=width,
                bg=T.MANTLE,
                fg=T.TEXT,
                insertbackground=T.TEXT,
                selectbackground=T.SURFACE2,
                selectforeground=T.TEXT,
                relief="flat",
                highlightthickness=1,
                highlightbackground=T.SURFACE0,
                highlightcolor=T.BLUE,
                font=FONT_SMALL,
            )
        return tk.Entry(
            parent,
            textvariable=var,
            width=width,
            bg=T.MANTLE,
            fg=T.TEXT,
            insertbackground=T.TEXT,
            selectbackground=T.SURFACE2,
            selectforeground=T.TEXT,
            relief="flat",
            highlightthickness=1,
            highlightbackground=T.SURFACE0,
            highlightcolor=T.BLUE,
            font=FONT_SMALL,
        )

    def _card(self, parent: tk.Misc, *, padx: int = 14, pady: int = 12) -> tk.Frame:
        return tk.Frame(
            parent,
            bg=T.MANTLE,
            highlightthickness=1,
            highlightbackground=T.SURFACE0,
            padx=padx,
            pady=pady,
        )

    def _section_title(self, parent: tk.Misc, title: str, note: str = "") -> None:
        tk.Label(
            parent,
            text=title,
            bg=parent.cget("bg"),
            fg=T.SUBTEXT1,
            font=("Consolas", 10, "bold"),
            anchor="w",
        ).pack(fill="x")
        if note:
            tk.Label(
                parent,
                text=note,
                bg=parent.cget("bg"),
                fg=T.OVERLAY1,
                font=FONT_TINY,
                anchor="w",
            ).pack(fill="x", pady=(3, 8))

    def _metric_card(
        self, parent: tk.Misc, col: int, label: str, value: str, note: str
    ) -> None:
        card = self._card(parent, padx=13, pady=11)
        card.grid(
            row=0,
            column=col,
            sticky="nsew",
            padx=(0 if col == 0 else 5, 5 if col < 5 else 0),
        )
        tk.Label(
            card,
            text=label.upper(),
            bg=T.MANTLE,
            fg=T.OVERLAY1,
            font=("Consolas", 8, "bold"),
            anchor="w",
        ).pack(fill="x")
        tk.Label(
            card,
            text=value,
            bg=T.MANTLE,
            fg=T.TEXT,
            font=("Consolas", 20, "bold"),
            anchor="w",
        ).pack(fill="x", pady=(5, 2))
        tk.Label(
            card,
            text=note,
            bg=T.MANTLE,
            fg=T.OVERLAY1,
            font=("Consolas", 7),
            anchor="w",
        ).pack(fill="x")

    @staticmethod
    def _wheel_units(event) -> int:
        num = getattr(event, "num", None)
        if num == 4:
            return -3
        if num == 5:
            return 3
        delta = getattr(event, "delta", 0) or 0
        if delta == 0:
            return 0
        if abs(delta) >= 120:
            return max(-8, min(8, int(-delta / 120)))
        return -1 if delta > 0 else 1

    def _bind_scroll(
        self,
        widget: ScrollWidget,
        *,
        vertical: bool = True,
        horizontal: bool = True,
        wheel_horizontal: bool = False,
        speed: int = 1,
    ) -> None:

        def scroll(event):
            units = self._wheel_units(event) * speed
            if not units:
                return None
            shifted = bool(getattr(event, "state", 0) & 0x0001)
            use_x = (
                wheel_horizontal
                or (shifted and horizontal)
                or (not vertical and horizontal)
            )
            try:
                if use_x:
                    widget.xview_scroll(units * speed, "units")
                elif vertical:
                    widget.yview_scroll(units, "units")
                elif horizontal:
                    widget.xview_scroll(units * speed, "units")
            except tk.TclError:
                return None
            return "break"

        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            widget.bind(sequence, scroll, add="+")
        if horizontal:
            for sequence in (
                "<Shift-MouseWheel>",
                "<Shift-Button-4>",
                "<Shift-Button-5>",
            ):
                widget.bind(sequence, scroll, add="+")

    def _tree(
        self,
        parent: tk.Misc,
        columns: list[tuple[str, str, int]],
        *,
        height: int = 12,
    ) -> tuple[ttk.Treeview, None, None]:
        frame = tk.Frame(parent, bg=T.MANTLE)
        frame.pack(fill="both", expand=True)

        tree = ttk.Treeview(
            frame,
            columns=[c[0] for c in columns],
            show="headings",
            height=height,
            style="Mocha.Treeview",
        )

        base_widths = {key: width for key, _, width in columns}
        total_width = sum(base_widths.values())

        for key, label, width in columns:
            tree.heading(key, text=label)
            tree.column(
                key,
                width=width,
                minwidth=max(55, min(width, 90)),
                stretch=False,
                anchor="w",
            )

        def resize_columns(event: tk.Event[tk.Misc]) -> None:
            available = max(1, event.width)

            # Wide tables keep their intended widths and remain horizontally scrollable.
            if available <= total_width:
                for key, _, width in columns:
                    tree.column(key, width=width)
                return

            extra = available - total_width

            for key, _, width in columns:
                share = round(extra * width / total_width)
                tree.column(key, width=width + share)

        tree.bind("<Configure>", resize_columns, add="+")
        tree.pack(fill="both", expand=True)

        self._bind_scroll(
            tree,
            vertical=True,
            horizontal=True,
            speed=4,
        )

        return tree, None, None

    def _key(self, event) -> None:
        if isinstance(event.widget, (tk.Entry, tk.Text, tk.Listbox)):
            return
        ch = (event.char or "").lower()
        if ch == "r":
            self._refresh()
        elif ch == "c":
            self._check()
        elif ch.isdigit() and 1 <= int(ch) <= len(self.views):
            self._set_view(int(ch) - 1)

    def _background(self, fn: Callable[[], object]) -> None:
        if self.worker and self.worker.is_alive():
            return
        self.refresh_btn.configure(state="disabled")
        self.check_btn.configure(state="disabled")

        def run():
            try:
                fn()
            except Exception as exc:  # noqa: BLE001 > background UI task boundary
                self.root.after(0, lambda e=exc: self.status_var.set(f"ERROR · {e}"))
            finally:
                self.root.after(0, self._worker_done)

        self.worker = threading.Thread(target=run, daemon=True)
        self.worker.start()

    def _worker_done(self) -> None:
        self.refresh_btn.configure(state="normal")
        self.check_btn.configure(state="normal")
        self.progress = None
        self.progressbar.stop()
        self.progressbar.configure(mode="determinate", value=0)
        if self._progressbar_visible:
            self.progressbar.pack_forget()
            self._progressbar_visible = False
        self.status_var.set("READY")
        self._set_view(self.view, preserve=True)

    def _set_progress(self, update: ProgressUpdate) -> None:
        self.progress = update

        def apply():
            self.status_var.set(update.message.upper())
            if not self._progressbar_visible:
                self.progressbar.pack(side="right", padx=16, pady=14)
                self._progressbar_visible = True
            if update.progress is None:
                self.progressbar.configure(mode="indeterminate")
                self.progressbar.start(15)
            else:
                self.progressbar.stop()
                self.progressbar.configure(
                    mode="determinate", value=max(0, min(100, update.progress * 100))
                )

        self.root.after(0, apply)

    def _refresh(self) -> None:
        self._background(lambda: self.engine.refresh(self._set_progress))

    def _check(self) -> None:
        self._background(lambda: self.engine.sync(progress=self._set_progress))

    def _tick(self) -> None:
        self._phase += 0.06
        canvas = self.const_canvas
        if self.view == 2 and canvas is not None and canvas.winfo_exists():
            self._draw_constellation_canvas()
        self.root.after(40, self._tick)

    def _clear_content(self) -> None:
        if self.content_cleanup:
            try:
                self.content_cleanup()
            except Exception as exc:  # noqa: BLE001 > cleanup must not break navigation
                self.status_var.set(f"CLEANUP ERROR · {exc}")
            self.content_cleanup = None
        for child in self.content.winfo_children():
            child.destroy()

    def _set_view(self, idx: int, *, preserve: bool = False) -> None:
        self.view = idx
        self.title_var.set(self.views[idx].upper())
        for i, b in enumerate(self.nav_buttons):
            b.configure(
                bg=T.SURFACE0 if i == idx else T.MANTLE,
                fg=T.TEXT if i == idx else T.SUBTEXT0,
            )
        try:
            state = self.engine.state
        except RuntimeError:
            return
        self.meta_var.set(
            f"SNAPSHOT {relative_time(state.meta.last_updated).upper()}  ·  {state.raw_key_count} KEYS"
        )
        self._clear_content()
        [
            self._build_pulse,
            self._build_projects,
            self._build_constellation,
            self._build_activity,
            self._build_ecology,
            self._build_contributions,
            self._build_sources,
            self._build_inspector,
        ][idx](state)

    def _build_pulse(self, state: DashboardState) -> None:
        t = state.analytics.totals
        metrics = tk.Frame(self.content, bg=T.BASE)
        metrics.pack(fill="x", pady=(0, 12))
        for i in range(6):
            metrics.grid_columnconfigure(i, weight=1)
        vals = [
            ("Projects", compact(t.get("projects", 0)), "tracked repositories"),
            ("Total commits", compact(t.get("commits", 0)), "repository commit counts"),
            (
                "Code bytes",
                human_bytes(t.get("language_bytes", 0)),
                "GitHub language bytes",
            ),
            ("Recent churn", compact(t.get("recent_churn", 0)), "cached commit sample"),
            ("Artifacts", compact(t.get("packages", 0)), "npm · crates · docker"),
            (
                "Status",
                f"{sum(s.ok for s in state.statuses)}/{len(state.statuses)}",
                "checks currently up",
            ),
        ]
        for i, (a, b, c) in enumerate(vals):
            self._metric_card(metrics, i, a, b, c)
        body = tk.Frame(self.content, bg=T.BASE)
        body.pack(fill="both", expand=True)
        body.grid_columnconfigure(0, weight=3)
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)
        left = self._card(body)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 7))
        right = self._card(body)
        right.grid(row=0, column=1, sticky="nsew", padx=(7, 0))
        self._section_title(
            left,
            "RECENTLY ACTIVE PROJECTS",
            "Exact snapshot values. No synthetic height or hidden score.",
        )
        cols = [
            ("project", "PROJECT", 180),
            ("push", "LAST PUSH", 90),
            ("cached", "CACHED COMMITS", 105),
            ("churn", "RECENT CHURN", 100),
            ("release", "LATEST RELEASE", 120),
        ]
        tree, *_ = self._tree(left, cols, height=15)
        for p in sorted(state.projects, key=lambda x: x.pushed_at or "", reverse=True):
            churn = sum(c.churn for c in p.commits)
            tree.insert(
                "",
                "end",
                values=(
                    p.alias,
                    relative_time(p.pushed_at),
                    len(p.commits),
                    compact(churn),
                    p.latest_release.tag if p.latest_release else "-",
                ),
            )
        self._section_title(
            right,
            "TELEMETRY HEALTH",
            "Current status checks and collector batch metadata.",
        )
        for s in state.statuses:
            row = tk.Frame(right, bg=T.MANTLE)
            row.pack(fill="x", pady=5)
            tk.Label(
                row,
                text="●",
                bg=T.MANTLE,
                fg=T.GREEN if s.ok else T.RED,
                font=FONT_BOLD,
            ).pack(side="left")
            tk.Label(row, text=s.label, bg=T.MANTLE, fg=T.TEXT, font=FONT_SMALL).pack(
                side="left", padx=7
            )
            tk.Label(
                row,
                text=(f"{s.latency_ms:.0f} ms" if s.latency_ms is not None else "-"),
                bg=T.MANTLE,
                fg=T.SUBTEXT0,
                font=FONT_SMALL,
            ).pack(side="right")
        tk.Frame(right, bg=T.SURFACE0, height=1).pack(fill="x", pady=8)
        run = state.meta.last_run or {}
        for label, value in (
            (
                "Collector processed",
                f"{run.get('processed', run.get('success', '-'))}{' / ' + str(run.get('total')) if run.get('total') is not None else ''}",
            ),
            ("Collector failed", str(run.get("failed", "-"))),
            ("Snapshot marker", relative_time(state.meta.last_updated)),
            ("Recent commits cached", str(len(state.analytics.commit_wave))),
        ):
            row = tk.Frame(right, bg=T.MANTLE)
            row.pack(fill="x", pady=4)
            tk.Label(row, text=label, bg=T.MANTLE, fg=T.OVERLAY1, font=FONT_TINY).pack(
                side="left"
            )
            tk.Label(row, text=value, bg=T.MANTLE, fg=T.TEXT, font=FONT_TINY).pack(
                side="right"
            )

    def _build_projects(self, state: DashboardState) -> None:
        toolbar = tk.Frame(self.content, bg=T.BASE)
        toolbar.pack(fill="x", pady=(0, 9))
        query = tk.StringVar()
        entry = self._entry(toolbar, query, 36)
        entry.pack(side="left", ipady=5)
        entry.insert(0, "")
        tk.Label(
            toolbar,
            text="Filter project, language, topic…",
            bg=T.BASE,
            fg=T.OVERLAY1,
            font=FONT_TINY,
        ).pack(side="left", padx=9)
        tk.Label(
            toolbar,
            text="CODE BYTES = GitHub language bytes · not LOC · table scrolls both directions",
            bg=T.BASE,
            fg=T.OVERLAY1,
            font=FONT_TINY,
        ).pack(side="right")
        table_card = self._card(self.content, padx=0, pady=0)
        table_card.pack(fill="both", expand=True)
        cols = [
            ("project", "PROJECT", 190),
            ("language", "LANGUAGE", 105),
            ("code", "CODE BYTES", 105),
            ("size", "REPO SIZE", 95),
            ("commits", "COMMITS", 80),
            ("stars", "STARS", 65),
            ("forks", "FORKS", 65),
            ("issues", "ISSUES", 65),
            ("watchers", "WATCHERS", 80),
            ("contributors", "TOP CONTRIBUTORS", 115),
            ("churn", "RECENT CHURN", 105),
            ("releases", "CACHED RELEASES", 115),
            ("tags", "CACHED TAGS", 95),
            ("deploys", "CACHED DEPLOYS", 105),
            ("release", "LATEST RELEASE", 115),
            ("pushed", "LAST PUSH", 90),
            ("license", "LICENSE", 80),
            ("topics", "TOPICS", 260),
        ]
        tree, *_ = self._tree(table_card, cols, height=17)
        detail = tk.Frame(
            self.content,
            bg=T.MANTLE,
            highlightthickness=1,
            highlightbackground=T.SURFACE0,
            height=120,
        )
        detail.pack(fill="x", pady=(9, 0))
        detail.pack_propagate(False)
        detail_var = tk.StringVar(
            value="Select a project for description, language mix, contributor and repository metadata."
        )
        tk.Label(
            detail,
            textvariable=detail_var,
            wraplength=1200,
            justify="left",
            anchor="nw",
            bg=T.MANTLE,
            fg=T.SUBTEXT0,
            font=FONT_SMALL,
        ).pack(fill="both", expand=True, padx=13, pady=10)

        def row_values(p: Project):
            churn = sum(c.churn for c in p.commits)
            return (
                p.alias,
                p.dominant_language,
                human_bytes(p.language_bytes),
                human_kb(p.size_kb),
                compact(p.commit_count),
                p.stars,
                p.forks,
                p.open_issues,
                p.watchers,
                len(p.contributors),
                compact(churn),
                len(p.releases),
                len(p.tags),
                len(p.deployments),
                p.latest_release.tag if p.latest_release else "-",
                relative_time(p.pushed_at),
                p.license_name or "-",
                ", ".join(p.topics) or "-",
            )

        pmap = {p.alias: p for p in state.projects}
        sorters = {
            "project": lambda p: p.alias.lower(),
            "language": lambda p: p.dominant_language.lower(),
            "code": lambda p: p.language_bytes,
            "size": lambda p: p.size_kb,
            "commits": lambda p: p.commit_count,
            "stars": lambda p: p.stars,
            "forks": lambda p: p.forks,
            "issues": lambda p: p.open_issues,
            "watchers": lambda p: p.watchers,
            "contributors": lambda p: len(p.contributors),
            "churn": lambda p: sum(c.churn for c in p.commits),
            "releases": lambda p: len(p.releases),
            "tags": lambda p: len(p.tags),
            "deploys": lambda p: len(p.deployments),
            "release": lambda p: p.latest_release.tag if p.latest_release else "",
            "pushed": lambda p: p.pushed_at or "",
            "license": lambda p: p.license_name,
            "topics": lambda p: ",".join(p.topics),
        }

        def refill(*_):
            q = query.get().strip().lower()
            key, desc = self._project_sort
            rows = [
                p
                for p in state.projects
                if not q
                or q
                in " ".join(
                    [p.alias, p.name, p.dominant_language, p.description, *p.topics]
                ).lower()
            ]
            rows.sort(key=sorters[key], reverse=desc)
            tree.delete(*tree.get_children())
            for p in rows:
                tree.insert("", "end", iid=p.alias, values=row_values(p))

        def sort_by(key):
            old, desc = self._project_sort
            self._project_sort = (key, not desc if old == key else True)
            refill()
            for k, label, _ in cols:
                tree.heading(
                    k,
                    text=label
                    + (
                        (" ↓" if self._project_sort[1] else " ↑")
                        if self._project_sort[0] == k
                        else ""
                    ),
                    command=lambda x=k: sort_by(x),
                )

        for k, label, _ in cols:
            tree.heading(k, text=label, command=lambda x=k: sort_by(x))

        def select(_=None):
            ids = tree.selection()
            if not ids:
                return
            p = pmap.get(ids[0])
            if not p:
                return
            top = (
                p.contributors[0].login + f" ({p.contributors[0].contributions})"
                if p.contributors
                else "-"
            )
            langs = (
                ", ".join(
                    f"{k} {v / max(1, p.language_bytes) * 100:.0f}%"
                    for k, v in sorted(
                        p.languages.items(), key=lambda kv: kv[1], reverse=True
                    )[:5]
                )
                or "-"
            )
            detail_var.set(
                f"{p.full_name}  ·  {p.description or 'No description'}\nLanguages: {langs}   ·   Top contributor: {top}   ·   Branch: {p.default_branch or '-'}   ·   Owner: {p.owner_login or '-'}   ·   Created: {short_date(p.created_at)}   ·   Updated: {relative_time(p.updated_at)}"
            )

        query.trace_add("write", refill)
        tree.bind("<<TreeviewSelect>>", select)
        refill()

    def _build_constellation(self, state: DashboardState) -> None:
        toolbar = tk.Frame(self.content, bg=T.BASE)
        toolbar.pack(fill="x", pady=(0, 9))
        self._button(toolbar, "RESET VIEW", self._reset_constellation).pack(side="left")
        search_var = tk.StringVar()
        search = self._entry(toolbar, search_var, 28)
        search.pack(side="left", padx=8, ipady=5)
        tk.Label(
            toolbar,
            text="wheel = zoom · drag = pan · click = inspect · focused node shows its similarity links",
            bg=T.BASE,
            fg=T.OVERLAY1,
            font=FONT_TINY,
        ).pack(side="right")
        area = tk.Frame(self.content, bg=T.BASE)
        area.pack(fill="both", expand=True)
        area.grid_columnconfigure(0, weight=1)
        area.grid_columnconfigure(1, weight=0)
        area.grid_rowconfigure(0, weight=1)
        canvas_wrap = tk.Frame(
            area, bg=T.MANTLE, highlightthickness=1, highlightbackground=T.SURFACE0
        )
        canvas_wrap.grid(row=0, column=0, sticky="nsew", padx=(0, 7))
        self.const_canvas = tk.Canvas(
            canvas_wrap, bg=T.MANTLE, highlightthickness=0, cursor="hand2"
        )
        self.const_canvas.pack(fill="both", expand=True)
        self.const_detail = self._card(area, padx=14, pady=14)
        self.const_detail.grid(row=0, column=1, sticky="ns", padx=(7, 0))
        self.const_detail.configure(width=320)
        self.const_detail.grid_propagate(False)
        self._const_nodes = {n.alias: n for n in state.analytics.constellation_nodes}
        self._const_projects = {p.alias: p for p in state.projects}
        self._const_edges = state.analytics.constellation_edges
        if self._const_selected not in self._const_nodes:
            self._const_selected = next(iter(self._const_nodes), None)
        self.const_canvas.bind(
            "<Configure>", lambda e: self._draw_constellation_canvas()
        )
        self.const_canvas.bind("<MouseWheel>", self._const_wheel)
        self.const_canvas.bind(
            "<Button-4>", lambda e: self._const_zoom_at(e.x, e.y, 1.12)
        )
        self.const_canvas.bind(
            "<Button-5>", lambda e: self._const_zoom_at(e.x, e.y, 0.89)
        )
        self.const_canvas.bind("<ButtonPress-1>", self._const_press)
        self.const_canvas.bind("<B1-Motion>", self._const_drag_motion)
        self.const_canvas.bind("<ButtonRelease-1>", self._const_release)
        self.const_canvas.bind("<Motion>", self._const_motion)

        def find(_=None):
            q = search_var.get().strip().lower()
            p = next((p for p in state.projects if p.alias.lower() == q), None) or next(
                (p for p in state.projects if q and q in p.alias.lower()), None
            )
            if p:
                self._const_selected = p.alias
                self._update_const_detail()
                self._draw_constellation_canvas()

        search.bind("<Return>", find)
        self._update_const_detail()
        self._draw_constellation_canvas()

    def _reset_constellation(self) -> None:
        self._const_scale = 1.0
        self._const_ox = 0.0
        self._const_oy = 0.0
        self._draw_constellation_canvas()

    def _const_screen(self, node: ConstellationNode) -> tuple[float, float]:
        canvas = self.const_canvas
        if canvas is None:
            return 0.0, 0.0
        width = max(1, canvas.winfo_width())
        height = max(1, canvas.winfo_height())
        return (
            (30 + node.x * (width - 60)) * self._const_scale + self._const_ox,
            (35 + node.y * (height - 70)) * self._const_scale + self._const_oy,
        )

    def _const_hit(self, x: int, y: int) -> ConstellationNode | None:
        best: ConstellationNode | None = None
        distance = 1e9
        for node in self._const_nodes.values():
            node_x, node_y = self._const_screen(node)
            radius = 6 + node.size * 10
            candidate = math.hypot(x - node_x, y - node_y)
            if candidate < radius + 7 and candidate < distance:
                best = node
                distance = candidate
        return best

    def _const_zoom_at(self, x: int, y: int, factor: float) -> None:
        old = self._const_scale
        self._const_scale = max(0.45, min(4.0, self._const_scale * factor))
        ratio = self._const_scale / old
        self._const_ox = x - (x - self._const_ox) * ratio
        self._const_oy = y - (y - self._const_oy) * ratio
        self._draw_constellation_canvas()

    def _const_wheel(self, event: tk.Event[tk.Misc]) -> None:
        self._const_zoom_at(event.x, event.y, 1.12 if event.delta > 0 else 0.89)

    def _const_press(self, event: tk.Event[tk.Misc]) -> None:
        self._const_drag = (event.x, event.y)
        self._const_drag_start = (event.x, event.y)

    def _const_drag_motion(self, event: tk.Event[tk.Misc]) -> None:
        if self._const_drag is None:
            return
        x, y = self._const_drag
        self._const_ox += event.x - x
        self._const_oy += event.y - y
        self._const_drag = (event.x, event.y)
        self._draw_constellation_canvas()

    def _const_release(self, event: tk.Event[tk.Misc]) -> None:
        start = self._const_drag_start or (event.x, event.y)
        moved = math.hypot(event.x - start[0], event.y - start[1])
        self._const_drag = None
        self._const_drag_start = None
        if moved < 5:
            node = self._const_hit(event.x, event.y)
            if node is not None:
                self._const_selected = node.alias
                self._update_const_detail()
                self._draw_constellation_canvas()

    def _const_motion(self, event: tk.Event[tk.Misc]) -> None:
        if self._const_drag is not None:
            return
        node = self._const_hit(event.x, event.y)
        alias = node.alias if node else None
        if alias != self._const_hover:
            self._const_hover = alias
            self._draw_constellation_canvas()

    def _const_connections(self, alias: str) -> list[ConstellationEdge]:
        return sorted(
            [
                edge
                for edge in self._const_edges
                if edge.source == alias or edge.target == alias
            ],
            key=lambda edge: edge.similarity,
            reverse=True,
        )

    def _draw_constellation_canvas(self) -> None:
        canvas = self.const_canvas
        if canvas is None or not canvas.winfo_exists():
            return
        canvas.delete("all")
        width = max(1, canvas.winfo_width())
        height = max(1, canvas.winfo_height())
        step = max(24, int(40 * self._const_scale))
        offset_x = int(self._const_ox) % step
        offset_y = int(self._const_oy) % step
        for x in range(offset_x, width, step):
            canvas.create_line(x, 0, x, height, fill=T.SURFACE0)
        for y in range(offset_y, height, step):
            canvas.create_line(0, y, width, y, fill=T.SURFACE0)

        groups: dict[str, list[tuple[float, float]]] = {}
        for node in self._const_nodes.values():
            x, y = self._const_screen(node)
            groups.setdefault(node.language, []).append((x, y))
        for language, points in groups.items():
            group_x = sum(x for x, _ in points) / len(points)
            group_y = sum(y for _, y in points) / len(points)
            canvas.create_text(
                group_x,
                group_y - 24,
                text=language.upper(),
                fill=_blend(T.MANTLE, T.language_color(language), 0.28),
                font=("Consolas", 8, "bold"),
            )

        selected = self._const_selected
        if selected and selected in self._const_nodes:
            for edge in self._const_connections(selected):
                source = self._const_nodes.get(edge.source)
                target = self._const_nodes.get(edge.target)
                if source is None or target is None:
                    continue
                source_x, source_y = self._const_screen(source)
                target_x, target_y = self._const_screen(target)
                color = T.language_color(self._const_nodes[selected].language)
                canvas.create_line(
                    source_x,
                    source_y,
                    target_x,
                    target_y,
                    fill=_blend(T.MANTLE, color, 0.25 + 0.45 * edge.similarity),
                    width=max(1, 1 + int(edge.similarity * 2)),
                )

        for node in self._const_nodes.values():
            x, y = self._const_screen(node)
            radius = 5 + node.size * 10
            color = T.language_color(node.language)
            focused = node.alias in (selected, self._const_hover)
            if focused:
                canvas.create_oval(
                    x - radius - 5,
                    y - radius - 5,
                    x + radius + 5,
                    y + radius + 5,
                    outline=_blend(T.MANTLE, color, 0.45),
                    width=1,
                )
            canvas.create_oval(
                x - radius,
                y - radius,
                x + radius,
                y + radius,
                fill=T.BASE,
                outline=color,
                width=2 if focused else 1,
            )
            if focused:
                canvas.create_text(
                    x + radius + 8,
                    y - 5,
                    text=node.alias,
                    fill=T.TEXT,
                    font=("Consolas", 9, "bold"),
                    anchor="w",
                )
                project = self._const_projects.get(node.alias)
                code_bytes = project.language_bytes if project else 0
                canvas.create_text(
                    x + radius + 8,
                    y + 9,
                    text=f"{node.language} · {human_bytes(code_bytes)}",
                    fill=T.OVERLAY1,
                    font=FONT_TINY,
                    anchor="w",
                )
        canvas.create_text(
            12,
            height - 12,
            text="Node size = code bytes · cluster = dominant language · focus reveals language-similarity links",
            fill=T.OVERLAY1,
            font=FONT_TINY,
            anchor="sw",
        )

    def _update_const_detail(self) -> None:
        detail = self.const_detail
        if detail is None:
            return
        for child in detail.winfo_children():
            child.destroy()
        alias = self._const_selected
        project = self._const_projects.get(alias) if alias else None
        if project is None:
            return
        tk.Label(
            detail,
            text=project.alias,
            bg=T.MANTLE,
            fg=T.TEXT,
            font=("Consolas", 15, "bold"),
            anchor="w",
        ).pack(fill="x")
        tk.Label(
            detail,
            text=project.full_name,
            bg=T.MANTLE,
            fg=T.OVERLAY1,
            font=FONT_TINY,
            anchor="w",
        ).pack(fill="x")
        tk.Label(
            detail,
            text=project.description or "No description in snapshot.",
            wraplength=285,
            justify="left",
            bg=T.MANTLE,
            fg=T.SUBTEXT0,
            font=FONT_SMALL,
            anchor="w",
        ).pack(fill="x", pady=(10, 12))
        stats = (
            ("Dominant language", project.dominant_language),
            ("Code bytes", human_bytes(project.language_bytes)),
            ("Repository size", human_kb(project.size_kb)),
            ("Commits", compact(project.commit_count)),
            (
                "Stars / forks / issues",
                f"{project.stars} / {project.forks} / {project.open_issues}",
            ),
            ("Last push", relative_time(project.pushed_at)),
        )
        for key, value in stats:
            row = tk.Frame(detail, bg=T.MANTLE)
            row.pack(fill="x", pady=3)
            tk.Label(row, text=key, bg=T.MANTLE, fg=T.OVERLAY1, font=FONT_TINY).pack(
                side="left"
            )
            tk.Label(row, text=value, bg=T.MANTLE, fg=T.TEXT, font=FONT_TINY).pack(
                side="right"
            )
        tk.Label(
            detail,
            text="LANGUAGE MIX",
            bg=T.MANTLE,
            fg=T.SUBTEXT1,
            font=("Consolas", 8, "bold"),
            anchor="w",
        ).pack(fill="x", pady=(13, 5))
        total = max(1, project.language_bytes)
        for language, value in sorted(
            project.languages.items(), key=lambda item: item[1], reverse=True
        )[:7]:
            row = tk.Frame(detail, bg=T.MANTLE)
            row.pack(fill="x", pady=2)
            tk.Label(
                row,
                text=language[:12],
                width=12,
                anchor="w",
                bg=T.MANTLE,
                fg=T.SUBTEXT0,
                font=FONT_TINY,
            ).pack(side="left")
            bar_canvas = tk.Canvas(
                row, width=100, height=6, bg=T.SURFACE0, highlightthickness=0
            )
            bar_canvas.pack(side="left", padx=5)
            bar_canvas.create_rectangle(
                0,
                0,
                100 * value / total,
                6,
                fill=T.language_color(language),
                outline="",
            )
            tk.Label(
                row,
                text=f"{value / total * 100:.0f}%",
                bg=T.MANTLE,
                fg=T.OVERLAY1,
                font=FONT_TINY,
            ).pack(side="right")
        tk.Label(
            detail,
            text="NEAREST LANGUAGE MIXES",
            bg=T.MANTLE,
            fg=T.SUBTEXT1,
            font=("Consolas", 8, "bold"),
            anchor="w",
        ).pack(fill="x", pady=(13, 4))
        for edge in self._const_connections(project.alias)[:7]:
            other = edge.target if edge.source == project.alias else edge.source
            row = tk.Frame(detail, bg=T.MANTLE)
            row.pack(fill="x", pady=2)
            tk.Label(row, text=other, bg=T.MANTLE, fg=T.SUBTEXT0, font=FONT_TINY).pack(
                side="left"
            )
            tk.Label(
                row,
                text=f"{edge.similarity * 100:.0f}%",
                bg=T.MANTLE,
                fg=T.TEXT,
                font=FONT_TINY,
            ).pack(side="right")

    def _build_activity(self, state: DashboardState) -> None:
        rows = state.analytics.commit_wave
        t = state.analytics.totals
        metrics = tk.Frame(self.content, bg=T.BASE)
        metrics.pack(fill="x", pady=(0, 12))
        for i in range(4):
            metrics.grid_columnconfigure(i, weight=1)
        counts: dict[str, int] = {}
        for row in rows:
            project = row["project"]
            counts[project] = counts.get(project, 0) + 1
        busiest = max(counts.items(), key=lambda item: item[1])[0] if counts else "-"
        vals = [
            ("Cached commits", str(len(rows)), "recent sample across repos"),
            ("Additions", compact(t.get("recent_additions", 0)), "cached sample"),
            ("Deletions", compact(t.get("recent_deletions", 0)), "cached sample"),
            (
                "Busiest sample",
                busiest,
                f"{counts.get(busiest, 0)} cached commits" if counts else "",
            ),
        ]
        for i, v in enumerate(vals):
            card = self._card(metrics, padx=13, pady=10)
            card.grid(
                row=0,
                column=i,
                sticky="nsew",
                padx=(0 if i == 0 else 5, 5 if i < 3 else 0),
            )
            tk.Label(
                card,
                text=v[0].upper(),
                bg=T.MANTLE,
                fg=T.OVERLAY1,
                font=("Consolas", 8, "bold"),
                anchor="w",
            ).pack(fill="x")
            tk.Label(
                card,
                text=v[1],
                bg=T.MANTLE,
                fg=T.TEXT,
                font=("Consolas", 18, "bold"),
                anchor="w",
            ).pack(fill="x", pady=(4, 1))
            tk.Label(
                card,
                text=v[2],
                bg=T.MANTLE,
                fg=T.OVERLAY1,
                font=("Consolas", 7),
                anchor="w",
            ).pack(fill="x")
        card = self._card(self.content, padx=0, pady=0)
        card.pack(fill="both", expand=True)
        top = tk.Frame(card, bg=T.MANTLE)
        top.pack(fill="x", padx=12, pady=(10, 5))
        tk.Label(
            top,
            text="RECENT CHANGE LEDGER",
            bg=T.MANTLE,
            fg=T.SUBTEXT1,
            font=("Consolas", 10, "bold"),
        ).pack(side="left")
        tk.Label(
            top,
            text="deletions ← center → additions · exact values at right",
            bg=T.MANTLE,
            fg=T.OVERLAY1,
            font=FONT_TINY,
        ).pack(side="right")
        wrap = tk.Frame(card, bg=T.MANTLE)
        wrap.pack(fill="both", expand=True)
        canvas = tk.Canvas(wrap, bg=T.MANTLE, highlightthickness=0)
        canvas.pack(fill="both", expand=True)
        self._bind_scroll(canvas, vertical=True, horizontal=False)
        maxv = max([max(r["additions"], r["deletions"]) for r in rows] or [1])

        def draw(_=None):
            canvas.delete("all")
            w = max(850, canvas.winfo_width())
            rowh = 36
            right_pad = 22
            delta_width = 92
            bar_half = 95

            delta_x = w - right_pad
            bar_cx = delta_x - delta_width - bar_half
            canvas.configure(scrollregion=(0, 0, w, rowh * (len(rows) + 1)))
            headers = [
                (12, "PROJECT"),
                (115, "DATE"),
                (205, "SHA"),
                (275, "MESSAGE"),
                (bar_cx - bar_half, "CHANGE"),
            ]
            canvas.create_text(
                delta_x,
                15,
                text="Δ",
                fill=T.OVERLAY1,
                font=("Consolas", 8, "bold"),
                anchor="e",
            )
            for x, txt in headers:
                canvas.create_text(
                    x,
                    15,
                    text=txt,
                    fill=T.OVERLAY1,
                    font=("Consolas", 8, "bold"),
                    anchor="w",
                )
            for i, r in enumerate(rows):
                y = 35 + i * rowh
                if i % 2:
                    canvas.create_rectangle(
                        0,
                        y - 5,
                        w,
                        y + rowh - 5,
                        fill=_blend(T.MANTLE, T.BASE, 0.35),
                        outline="",
                    )
                canvas.create_text(
                    12,
                    y + 8,
                    text=r["project"][:15],
                    fill=T.TEXT,
                    font=FONT_SMALL,
                    anchor="w",
                )
                canvas.create_text(
                    115,
                    y + 8,
                    text=short_date(r["date"]),
                    fill=T.SUBTEXT0,
                    font=FONT_TINY,
                    anchor="w",
                )
                canvas.create_text(
                    205,
                    y + 8,
                    text=r["sha"],
                    fill=T.SUBTEXT0,
                    font=FONT_TINY,
                    anchor="w",
                )
                msg = str(r["message"])
                canvas.create_text(
                    275,
                    y + 8,
                    text=msg[:58] + ("…" if len(msg) > 58 else ""),
                    fill=T.SUBTEXT1,
                    font=FONT_TINY,
                    anchor="w",
                )
                cx = bar_cx
                half = bar_half
                canvas.create_line(
                    cx, y + 8, cx - half, y + 8, fill=T.SURFACE0, width=5
                )
                canvas.create_line(
                    cx, y + 8, cx + half, y + 8, fill=T.SURFACE0, width=5
                )
                dw = half * r["deletions"] / maxv
                aw = half * r["additions"] / maxv
                canvas.create_line(cx, y + 8, cx - dw, y + 8, fill=T.RED, width=6)
                canvas.create_line(cx, y + 8, cx + aw, y + 8, fill=T.GREEN, width=6)
                canvas.create_line(cx, y - 3, cx, y + 19, fill=T.SURFACE2)
                canvas.create_text(
                    delta_x,
                    y + 8,
                    text=f"−{r['deletions']}  +{r['additions']}",
                    fill=T.SUBTEXT0,
                    font=FONT_TINY,
                    anchor="e",
                )
                canvas.create_line(0, y + rowh - 5, w, y + rowh - 5, fill=T.SURFACE0)

        canvas.bind("<Configure>", draw)
        draw()

    def _build_ecology(self, state: DashboardState) -> None:
        top = self._card(self.content, padx=14, pady=10)
        top.pack(fill="x", pady=(0, 10))
        self._section_title(
            top,
            "PORTFOLIO LANGUAGE COMPOSITION",
            "Measured in GitHub language bytes. This is not lines of code.",
        )
        comp = tk.Canvas(top, height=20, bg=T.SURFACE0, highlightthickness=0)
        comp.pack(fill="x")

        def compdraw(_=None):
            comp.delete("all")
            w = max(10, comp.winfo_width())
            x = 0
            for l in state.analytics.languages[:16]:
                ww = w * l.share
                comp.create_rectangle(
                    x, 0, x + ww, 20, fill=T.language_color(l.language), outline=""
                )
                x += ww

        comp.bind("<Configure>", compdraw)
        body = tk.PanedWindow(
            self.content,
            orient="horizontal",
            bg=T.BASE,
            sashwidth=6,
            showhandle=False,
            bd=0,
        )
        body.pack(fill="both", expand=True)
        left = self._card(body, padx=10, pady=10)
        right = self._card(body, padx=8, pady=8)
        body.add(left, minsize=390)
        body.add(right, minsize=520)
        self._section_title(
            left, "LANGUAGE LEDGER", "Bytes, portfolio share and repository breadth."
        )
        cols = [
            ("lang", "LANGUAGE", 120),
            ("bytes", "BYTES", 100),
            ("share", "SHARE", 70),
            ("repos", "REPOS", 60),
        ]
        tree, *_ = self._tree(left, cols, height=16)
        for l in state.analytics.languages:
            tree.insert(
                "",
                "end",
                values=(
                    l.language,
                    human_bytes(l.bytes),
                    f"{l.share * 100:.1f}%",
                    l.projects,
                ),
            )
        self._section_title(
            right,
            "PROJECT FINGERPRINT MATRIX",
            "Cell intensity = that language's share inside the repository. Scroll both ways.",
        )
        f = tk.Frame(right, bg=T.MANTLE)
        f.pack(fill="both", expand=True)
        cv = tk.Canvas(f, bg=T.MANTLE, highlightthickness=0)
        cv.pack(fill="both", expand=True)
        self._bind_scroll(cv, vertical=True, horizontal=True)
        langs = state.analytics.languages[:14]
        projects = sorted(state.projects, key=lambda p: p.language_bytes, reverse=True)
        cell = 27
        leftw = 170
        topy = 32
        totalw = leftw + len(langs) * cell + 20
        totalh = topy + len(projects) * 25 + 20
        cv.configure(scrollregion=(0, 0, totalw, totalh))
        for j, l in enumerate(langs):
            cv.create_text(
                leftw + j * cell + cell / 2,
                15,
                text=l.language[:3].upper(),
                fill=T.OVERLAY1,
                font=FONT_TINY,
                angle=0,
            )
        for i, p in enumerate(projects):
            y = topy + i * 25
            cv.create_text(
                8,
                y + 10,
                text=p.alias[:22],
                fill=T.SUBTEXT1,
                font=FONT_TINY,
                anchor="w",
            )
            tot = max(1, p.language_bytes)
            for j, l in enumerate(langs):
                share = p.languages.get(l.language, 0) / tot
                level = (
                    0
                    if share == 0
                    else 1
                    if share < 0.08
                    else 2
                    if share < 0.25
                    else 3
                    if share < 0.55
                    else 4
                )
                col = (
                    T.SURFACE0
                    if level == 0
                    else _blend(
                        T.SURFACE0,
                        T.language_color(l.language),
                        [0, 0.28, 0.48, 0.70, 1][level],
                    )
                )
                x = leftw + j * cell
                cv.create_rectangle(x, y, x + 21, y + 19, fill=col, outline=T.BASE)
        compdraw()

    def _build_contributions(self, state: DashboardState) -> None:
        u = state.user
        metrics = tk.Frame(self.content, bg=T.BASE)
        metrics.pack(fill="x", pady=(0, 10))
        for i in range(4):
            metrics.grid_columnconfigure(i, weight=1)
        vals = [
            ("Calendar total", compact(u.calendar_total), "detailed window"),
            ("Commit contributions", compact(u.commits), "current collection"),
            ("Pull requests", compact(u.pull_requests), "current collection"),
            (
                "Daily detail",
                f"{len(u.contribution_days)} days",
                "rolling one-year window",
            ),
        ]
        for i, (a, b, c) in enumerate(vals):
            card = self._card(metrics, padx=13, pady=9)
            card.grid(
                row=0,
                column=i,
                sticky="nsew",
                padx=(0 if i == 0 else 5, 5 if i < 3 else 0),
            )
            tk.Label(
                card,
                text=a.upper(),
                bg=T.MANTLE,
                fg=T.OVERLAY1,
                font=("Consolas", 8, "bold"),
                anchor="w",
            ).pack(fill="x")
            tk.Label(
                card,
                text=b,
                bg=T.MANTLE,
                fg=T.TEXT,
                font=("Consolas", 18, "bold"),
                anchor="w",
            ).pack(fill="x", pady=(4, 1))
            tk.Label(
                card,
                text=c,
                bg=T.MANTLE,
                fg=T.OVERLAY1,
                font=("Consolas", 7),
                anchor="w",
            ).pack(fill="x")
        annual = self._card(self.content, padx=12, pady=9)
        annual.pack(fill="x", pady=(0, 10))
        self._section_title(annual, "ANNUAL TOTALS")
        ac = tk.Canvas(annual, height=92, bg=T.MANTLE, highlightthickness=0)
        ac.pack(fill="x")
        years = list(u.annual_totals.items())
        mx = max([v for _, v in years] or [1])

        def adraw(_=None):
            ac.delete("all")
            w = max(1, ac.winfo_width())
            gap = max(48, w / max(1, len(years)))
            base = 70
            for i, (year, val) in enumerate(years):
                x = 20 + i * gap
                bh = 52 * val / mx
                ac.create_rectangle(x, base - bh, x + 24, base, fill=T.BLUE, outline="")
                ac.create_text(
                    x + 12, base + 13, text=str(year), fill=T.OVERLAY1, font=FONT_TINY
                )
                ac.create_text(
                    x + 12,
                    base - bh - 8,
                    text=compact(val),
                    fill=T.SUBTEXT0,
                    font=FONT_TINY,
                )

        ac.bind("<Configure>", adraw)
        adraw()
        heat = self._card(self.content, padx=12, pady=9)
        heat.pack(fill="both", expand=True)

        self._section_title(
            heat,
            "CONTRIBUTION HEATMAP",
            "Exact daily contributions from the rolling one-year Echopoint window.",
        )

        frame = tk.Frame(heat, bg=T.MANTLE)
        frame.pack(fill="both", expand=True)

        cv = tk.Canvas(
            frame,
            bg=T.MANTLE,
            highlightthickness=0,
        )
        cv.pack(fill="both", expand=True)

        dated: dict[date, ContributionDay] = {}

        for contribution in u.contribution_days:
            try:
                day_date = date.fromisoformat(contribution.date[:10])
            except ValueError:
                continue

            dated[day_date] = contribution

        if not dated:
            return

        first_day = min(dated)
        last_day = max(dated)

        # Pad the exact source window to complete Sunday → Saturday weeks.
        start_day = first_day - timedelta(days=(first_day.weekday() + 1) % 7)

        end_day = last_day + timedelta(days=(5 - last_day.weekday()) % 7)

        timeline: list[date] = []

        current = start_day
        while current <= end_day:
            timeline.append(current)
            current += timedelta(days=1)

        weeks = [timeline[index : index + 7] for index in range(0, len(timeline), 7)]

        def contribution_fill(count: int) -> str:
            if count <= 0:
                return T.SURFACE0
            if count == 1:
                return _blend(T.SURFACE0, T.GREEN, 0.28)
            if count <= 4:
                return _blend(T.SURFACE0, T.GREEN, 0.48)
            if count <= 9:
                return _blend(T.SURFACE0, T.GREEN, 0.72)

            return T.GREEN

        def draw_heatmap(_event=None) -> None:
            cv.delete("all")
            self._contrib_cells = []

            width = max(1, cv.winfo_width())

            left = 12.0
            right = 12.0
            top = 42.0
            gap = 3.0

            week_count = max(1, len(weeks))
            step = (width - left - right) / week_count
            cell = max(5.0, step - gap)

            last_month: tuple[int, int] | None = None
            last_year: int | None = None

            for week_index, week in enumerate(weeks):
                x = left + week_index * step
                label_date = week[0]

                if label_date.year != last_year:
                    cv.create_text(
                        x,
                        10,
                        text=str(label_date.year),
                        fill=T.SUBTEXT0,
                        font=("Consolas", 8, "bold"),
                        anchor="w",
                    )
                    last_year = label_date.year

                month_key = (
                    label_date.year,
                    label_date.month,
                )

                if month_key != last_month:
                    cv.create_text(
                        x,
                        27,
                        text=label_date.strftime("%b").upper(),
                        fill=T.OVERLAY1,
                        font=FONT_TINY,
                        anchor="w",
                    )
                    last_month = month_key

                for day_index, day_date in enumerate(week):
                    y = top + day_index * (cell + gap)

                    contribution = dated.get(day_date)

                    if day_date < first_day or day_date > last_day:
                        fill = T.MANTLE
                        outline = T.MANTLE
                    elif contribution is None:
                        fill = T.SURFACE0
                        outline = T.BASE
                    else:
                        fill = contribution_fill(contribution.count)
                        outline = T.BASE

                    item = cv.create_rectangle(
                        x,
                        y,
                        x + cell,
                        y + cell,
                        fill=fill,
                        outline=outline,
                    )

                    if contribution is not None:
                        self._contrib_cells.append((item, contribution))

        def motion(event: tk.Event[tk.Misc]) -> None:
            items = cv.find_overlapping(
                event.x,
                event.y,
                event.x,
                event.y,
            )

            contribution = next(
                (day for item, day in self._contrib_cells if item in items),
                None,
            )

            if contribution is not None:
                self.status_var.set(
                    f"{contribution.date} · {contribution.count} CONTRIBUTIONS"
                )

        cv.bind("<Configure>", draw_heatmap)
        cv.bind("<Motion>", motion)

        draw_heatmap()

    def _build_sources(self, state: DashboardState) -> None:
        tabbar = tk.Frame(self.content, bg=T.BASE)
        tabbar.pack(fill="x", pady=(0, 8))

        body = tk.Frame(self.content, bg=T.BASE)
        body.pack(fill="both", expand=True)

        tab_buttons: list[tk.Button] = []
        current_tab = tk.IntVar(value=0)

        tabs = (
            "REGISTRIES",
            "STATUS",
            "RELEASE COVERAGE",
        )

        for i in range(len(tabs)):
            tabbar.grid_columnconfigure(i, weight=1, uniform="source-tabs")

        def show_tab(index: int) -> None:
            current_tab.set(index)

            for child in body.winfo_children():
                child.destroy()

            for i, button in enumerate(tab_buttons):
                selected = i == index
                button.configure(
                    bg=T.SURFACE0 if selected else T.MANTLE,
                    fg=T.TEXT if selected else T.SUBTEXT0,
                )

            if index == 0:
                build_registries(body)
            elif index == 1:
                build_status(body)
            else:
                build_releases(body)

        for i, label in enumerate(tabs):
            button = tk.Button(
                tabbar,
                text=label,
                command=lambda index=i: show_tab(index),
                bg=T.MANTLE,
                fg=T.SUBTEXT0,
                activebackground=T.SURFACE0,
                activeforeground=T.TEXT,
                relief="flat",
                bd=0,
                highlightthickness=0,
                font=("Consolas", 9, "bold"),
                pady=9,
                cursor="hand2",
            )

            button.grid(
                row=0,
                column=i,
                sticky="ew",
                padx=(0 if i == 0 else 2, 0),
            )

            tab_buttons.append(button)

        def build_registries(parent: tk.Misc) -> None:
            rc = self._card(parent, padx=10, pady=10)
            rc.pack(fill="both", expand=True)
            cols = [
                ("eco", "SOURCE", 80),
                ("name", "NAME", 180),
                ("alias", "ALIAS", 160),
                ("version", "VERSION/TAG", 110),
                ("downloads", "DOWNLOADS", 95),
                ("recent", "RECENT DL", 90),
                ("size", "SIZE", 95),
                ("files", "FILES/DEPS", 90),
                ("updated", "UPDATED", 100),
                ("license", "LICENSE", 85),
            ]
            tree, *_ = self._tree(rc, cols, height=20)
            for a in state.npm:
                tree.insert(
                    "",
                    "end",
                    values=(
                        "npm",
                        a.name,
                        a.alias,
                        a.version,
                        "-",
                        "-",
                        human_bytes(a.size_bytes),
                        f"{a.file_count if a.file_count is not None else '-'} / {a.dependency_count}",
                        relative_time(a.updated_at),
                        a.license_name or "-",
                    ),
                )
            for a in state.crates:
                tree.insert(
                    "",
                    "end",
                    values=(
                        "crates",
                        a.name,
                        a.alias,
                        a.version,
                        compact(a.downloads) if a.downloads is not None else "-",
                        compact(a.recent_downloads)
                        if a.recent_downloads is not None
                        else "-",
                        "-",
                        "-",
                        relative_time(a.updated_at),
                        a.license_name or "-",
                    ),
                )
            for a in state.docker:
                tree.insert(
                    "",
                    "end",
                    values=(
                        "docker",
                        a.alias,
                        a.alias,
                        a.latest_tag,
                        "-",
                        "-",
                        human_bytes(a.latest_size_bytes),
                        f"{len(a.tags)} tags",
                        relative_time(a.latest_updated_at),
                        "-",
                    ),
                )

        def build_status(parent: tk.Misc) -> None:
            sc = self._card(parent, padx=10, pady=10)
            sc.pack(fill="both", expand=True)
            cols2 = [
                ("label", "CHECK", 220),
                ("state", "STATE", 90),
                ("http", "HTTP", 75),
                ("latency", "LATENCY", 90),
                ("checked", "CHECKED", 100),
                ("url", "URL", 450),
                ("error", "ERROR", 300),
            ]
            st, *_ = self._tree(sc, cols2, height=20)
            for s in state.statuses:
                st.insert(
                    "",
                    "end",
                    values=(
                        s.label,
                        "UP" if s.ok else s.state.upper(),
                        s.status or "-",
                        f"{s.latency_ms:.0f} ms" if s.latency_ms is not None else "-",
                        relative_time(s.checked_at),
                        s.url or "-",
                        s.error or "-",
                    ),
                )

        def build_releases(parent: tk.Misc) -> None:
            relc = self._card(parent, padx=10, pady=10)
            relc.pack(fill="both", expand=True)
            cols3 = [
                ("project", "PROJECT", 190),
                ("latest", "LATEST RELEASE", 120),
                ("published", "PUBLISHED", 100),
                ("releases", "CACHED RELEASES", 115),
                ("tags", "CACHED TAGS", 100),
                ("deploys", "CACHED DEPLOYS", 110),
                ("push", "LAST PUSH", 100),
            ]
            rt, *_ = self._tree(relc, cols3, height=20)
            for p in sorted(state.projects, key=lambda p: p.alias):
                rt.insert(
                    "",
                    "end",
                    values=(
                        p.alias,
                        p.latest_release.tag if p.latest_release else "-",
                        short_date(p.latest_release.published_at)
                        if p.latest_release
                        else "-",
                        len(p.releases),
                        len(p.tags),
                        len(p.deployments),
                        relative_time(p.pushed_at),
                    ),
                )

        show_tab(0)

    def _build_inspector(self, state: DashboardState) -> None:
        raw = self.engine.raw_store
        area = tk.PanedWindow(
            self.content, orient="horizontal", bg=T.BASE, sashwidth=6, bd=0
        )
        area.pack(fill="both", expand=True)
        left = self._card(area, padx=9, pady=9)
        right = self._card(area, padx=9, pady=9)
        area.add(left, minsize=350)
        area.add(right, minsize=650)
        q = tk.StringVar()
        entry = self._entry(left, q, 32)
        entry.pack(fill="x", ipady=5, pady=(0, 8))
        keys = tk.Listbox(
            left,
            bg=T.MANTLE,
            fg=T.SUBTEXT0,
            selectbackground=T.SURFACE1,
            selectforeground=T.TEXT,
            activestyle="none",
            relief="flat",
            highlightthickness=1,
            highlightbackground=T.SURFACE0,
            font=FONT_TINY,
        )
        keys.pack(fill="both", expand=True)
        self._bind_scroll(keys, vertical=True, horizontal=False)
        viewer_header = tk.Frame(right, bg=T.MANTLE)
        viewer_header.pack(fill="x", pady=(0, 7))

        selected_key = tk.StringVar()

        tk.Label(
            viewer_header,
            textvariable=selected_key,
            bg=T.MANTLE,
            fg=T.SUBTEXT1,
            font=("Consolas", 9, "bold"),
            anchor="w",
        ).pack(side="left", fill="x", expand=True)

        viewer = tk.Frame(right, bg=T.MANTLE)
        viewer.pack(fill="both", expand=True)

        line_numbers = tk.Text(
            viewer,
            width=5,
            bg=T.BASE,
            fg=T.OVERLAY1,
            relief="flat",
            bd=0,
            highlightthickness=0,
            wrap="none",
            font=FONT_SMALL,
            padx=5,
            pady=8,
            state="disabled",
            takefocus=False,
        )

        line_numbers.pack(side="left", fill="y")

        text = tk.Text(
            viewer,
            bg=T.MANTLE,
            fg=T.SUBTEXT1,
            insertbackground=T.TEXT,
            selectbackground=T.SURFACE2,
            selectforeground=T.TEXT,
            relief="flat",
            bd=0,
            highlightthickness=0,
            wrap="none",
            font=FONT_SMALL,
            padx=8,
            pady=8,
        )

        text.pack(side="left", fill="both", expand=True)
        self._bind_scroll(text, vertical=True, horizontal=True)
        allkeys = sorted(raw)

        def sync_scroll(first: str, _last: str) -> None:
            line_numbers.yview_moveto(float(first))

        text.configure(
            yscrollcommand=self.root.register(sync_scroll),
        )

        def copy_value() -> None:
            value = text.get("1.0", "end-1c")

            if not value:
                return

            self.root.clipboard_clear()
            self.root.clipboard_append(value)
            self.status_var.set("COPIED RAW VALUE")

        self._button(
            viewer_header,
            "COPY",
            copy_value,
        ).pack(side="right")

        def refill(*_):
            f = q.get().lower()
            keys.delete(0, "end")
            for k in allkeys:
                if not f or f in k.lower():
                    keys.insert("end", k)

        def select(_=None):
            sel = keys.curselection()
            if not sel:
                return
            k = keys.get(sel[0])
            payload = json.dumps(
                raw.get(k),
                indent=2,
                ensure_ascii=False,
            )

            selected_key.set(k)

            text.configure(state="normal")
            text.delete("1.0", "end")
            text.insert("1.0", payload)
            text.configure(state="disabled")

            lines = payload.count("\n") + 1

            line_numbers.configure(state="normal")
            line_numbers.delete("1.0", "end")
            line_numbers.insert(
                "1.0",
                "\n".join(str(i) for i in range(1, lines + 1)),
            )
            line_numbers.configure(state="disabled")

        q.trace_add("write", refill)
        keys.bind("<<ListboxSelect>>", select)

        refill()

        if keys.size() > 0:
            keys.selection_set(0)
            keys.activate(0)
            keys.see(0)
            select()

    def run(self) -> None:
        self.root.mainloop()


def run_gui(engine: EchopointEngine) -> None:
    DashboardGui(engine).run()
