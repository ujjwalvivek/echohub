from __future__ import annotations

"""
Echohub development task runner.

Run from the project root:

    uv run python scripts/dev.py lint
    uv run dev lint
        Run Ruff without modifying files.

    uv run python scripts/dev.py format
    uv run dev format
        Format Python and apply Ruff's safe automatic fixes.

    uv run python scripts/dev.py typecheck
    uv run dev typecheck
        Run BasedPyright.

    uv run python scripts/dev.py test
    uv run dev test
        Run the complete pytest suite.

    uv run python scripts/dev.py icons
    uv run dev icons
        Generate PNG and ICO assets from assets/echohub.svg.

    uv run python scripts/dev.py validate
    uv run dev validate
        Verify Python compilation.

    uv run python scripts/dev.py check
    uv run dev check
        Run lint + typecheck + tests.

    uv run python scripts/dev.py all
    uv run dev all
        Format/fix + typecheck + tests + validation.

Launch code:

    uv run echohub gui
    uv run echohub tui

    uv run echohub --demo gui
    uv run echohub --demo tui
"""

import argparse
import compileall
import platform
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

APP_ASSETS = ROOT / "src" / "echohub" / "assets"
ASSET_SOURCE = APP_ASSETS / "echohub.svg"

PYTHON_PATHS = (
    ROOT / "src",
    ROOT / "tests",
)


class CliArgs(argparse.Namespace):
    command: str = ""


def run(*command: str, cwd: Path | None = None) -> None:

    print(f"\n> {' '.join(command)}\n")

    _ = subprocess.run(
        command,
        cwd=cwd or ROOT,
        check=True,
    )


def cmd_lint() -> None:

    run("ruff", "check", ".")


def cmd_format() -> None:

    run("ruff", "format", ".")
    run("ruff", "check", ".", "--fix")


def cmd_typecheck() -> None:

    run("basedpyright")


def cmd_test() -> None:

    run("pytest")


def validate_python() -> None:

    print("\nValidating Python sources...")

    for path in PYTHON_PATHS:
        if not compileall.compile_dir(path, quiet=1):
            raise RuntimeError(f"Python compilation failed: {path.relative_to(ROOT)}")

    print("Python compilation OK")


def cmd_validate() -> None:

    validate_python()

    print("\nValidation passed.")


def cmd_check() -> None:

    cmd_lint()
    cmd_typecheck()
    cmd_test()


def cmd_all() -> None:

    cmd_format()
    cmd_typecheck()
    cmd_test()
    cmd_icons()
    cmd_validate()

    print("\nEchohub is clean and ready.")


def cmd_icons() -> None:

    magick = shutil.which("magick")

    if magick is None:
        raise RuntimeError(
            "ImageMagick was not found. "
            "Install ImageMagick and ensure 'magick' is available on PATH."
        )

    if not ASSET_SOURCE.is_file():
        raise RuntimeError(
            f"Canonical icon not found: {ASSET_SOURCE.relative_to(ROOT)}"
        )

    APP_ASSETS.mkdir(parents=True, exist_ok=True)

    print("\nGenerating Echohub icons...")

    run(
        magick,
        "-background",
        "none",
        str(ASSET_SOURCE),
        "-resize",
        "512x512",
        f"PNG32:{APP_ASSETS / 'echohub.png'}",
    )

    run(
        magick,
        "-background",
        "none",
        str(ASSET_SOURCE),
        "-define",
        "icon:auto-resize=256,128,64,48,32,16",
        str(APP_ASSETS / "echohub.ico"),
    )

    print("Generated:")
    print("  src/echohub/assets/echohub.png")
    print("  src/echohub/assets/echohub.ico")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Echohub development tasks",
    )

    _ = parser.add_argument(
        "command",
        choices=(
            "lint",
            "format",
            "typecheck",
            "test",
            "icons",
            "validate",
            "check",
            "all",
        ),
        help="Development task to run",
    )

    return parser


def main() -> int:
    args = build_parser().parse_args(namespace=CliArgs())

    commands: dict[str, Callable[[], None]] = {
        "lint": cmd_lint,
        "format": cmd_format,
        "typecheck": cmd_typecheck,
        "test": cmd_test,
        "icons": cmd_icons,
        "validate": cmd_validate,
        "check": cmd_check,
        "all": cmd_all,
    }

    print(
        f"Echohub dev tools · {platform.system()} · Python {platform.python_version()}"
    )

    command = commands.get(args.command)

    if command is None:
        raise ValueError(f"Unknown development command: {args.command}")

    command()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
