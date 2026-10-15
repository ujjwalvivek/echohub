from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .config import DashboardConfig
from .demo import demo_store
from .engine import EchopointEngine, ProgressUpdate


class CliArgs(argparse.Namespace):
    url: str | None = None
    cache_dir: str | None = None
    demo: bool = False
    offline: bool = False
    command: str | None = None


def _progress(update: ProgressUpdate) -> None:
    pct = "…" if update.progress is None else f"{update.progress * 100:3.0f}%"
    print(f"[{pct:>4}] {update.message}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="echohub",
        description="Echohub · multi-surface telemetry dashboard",
    )
    _ = parser.add_argument(
        "--url",
        help="Upstream telemetry URL (default: ECHOHUB_SOURCE_URL or production Echopoint)",
    )
    _ = parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    _ = parser.add_argument("--cache-dir", help="Override local snapshot directory")
    _ = parser.add_argument(
        "--demo",
        action="store_true",
        help="Install and use bundled demo telemetry instead of the network",
    )
    _ = parser.add_argument(
        "--offline",
        action="store_true",
        help="Use the local snapshot without a health check",
    )
    # With no command, open the desktop app.
    sub = parser.add_subparsers(dest="command", required=False)
    _ = sub.add_parser(
        "sync",
        help="Download the snapshot only if Echopoint changed "
        "(private repos included with a token)",
    )
    _ = sub.add_parser(
        "refresh",
        help="Ask Echopoint to refresh until its queue is empty, then re-sync",
    )
    _ = sub.add_parser("inspect", help="Print normalized dashboard state as JSON")
    _ = sub.add_parser("tui", help="Launch the terminal renderer")
    _ = sub.add_parser("gui", help="Launch the desktop app (default)")
    return parser


def parse_args(argv: list[str] | None = None) -> CliArgs:
    args = build_parser().parse_args(argv, namespace=CliArgs())
    if args.command is None:
        args.command = "gui"
    return args


def make_engine(args: CliArgs) -> EchopointEngine:
    config = DashboardConfig.from_env()
    if args.url:
        config.base_url = args.url.rstrip("/")
    if args.cache_dir:
        config.cache_dir = Path(args.cache_dir)
    engine = EchopointEngine(config)
    if args.demo:
        _ = engine.install_demo(demo_store())
        return engine
    had_cache = engine.load_cache()
    if args.command in {"gui", "tui"}:
        # Both open at once and check in the background, so a slow or
        # unreachable Echopoint never blocks or prevents startup.
        return engine
    if args.command in {"sync", "refresh"}:
        if args.offline:
            raise SystemExit(
                f"`{args.command}` is a network action and cannot be used with --offline."
            )
        return engine
    if not args.offline:
        try:
            _ = engine.sync(progress=_progress if args.command == "inspect" else None)
        except Exception as exc:
            if not had_cache:
                raise
            print(
                f"warning: source check failed; using cached snapshot: {exc}",
                file=sys.stderr,
            )
    elif not had_cache:
        raise SystemExit(
            "No local snapshot exists. Run `echohub sync` once or use --demo."
        )
    return engine


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        engine = make_engine(args)
        if args.command == "sync":
            result = engine.sync(progress=_progress)
            print(result.message)
        elif args.command == "refresh":
            result = engine.refresh(_progress)
            print(result.message)
        elif args.command == "inspect":
            print(json.dumps(engine.state.to_dict(), indent=2, ensure_ascii=False))
        elif args.command == "tui":
            from .renderers.tui import run_tui

            run_tui(engine, auto_check=not args.offline and not args.demo)
        elif args.command == "gui":
            from .renderers.qt.app import run_qt

            run_qt(engine, auto_check=not args.offline and not args.demo)
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception as exc:  # noqa: BLE001 > top-level CLI error boundary
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
