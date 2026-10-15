import json
from pathlib import Path

import pytest

from echohub.__main__ import main, parse_args


def test_parse_args_global_flags_before_command() -> None:
    args = parse_args(["--offline", "--cache-dir", "x", "tui"])
    assert args.offline
    assert args.cache_dir == "x"
    assert args.command == "tui"


def test_no_command_opens_the_desktop_app() -> None:
    assert parse_args([]).command == "gui"
    assert parse_args(["--offline"]).command == "gui"


def test_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    from echohub import __version__

    with pytest.raises(SystemExit) as exit_info:
        _ = parse_args(["--version"])
    assert exit_info.value.code == 0
    assert capsys.readouterr().out.strip() == f"echohub {__version__}"


def test_demo_inspect_prints_dashboard_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--demo", "--cache-dir", str(tmp_path), "inspect"]) == 0
    state = json.loads(capsys.readouterr().out)
    assert state["projects"]
    assert state["analytics"]["totals"]["projects"] == len(state["projects"])


def test_offline_without_snapshot_explains_next_step(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit, match="echohub sync"):
        _ = main(["--offline", "--cache-dir", str(tmp_path), "inspect"])
    assert capsys.readouterr().out == ""


def test_offline_rejects_network_commands(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="network action"):
        _ = main(["--offline", "--cache-dir", str(tmp_path), "sync"])


def test_offline_uses_existing_snapshot(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--demo", "--cache-dir", str(tmp_path), "inspect"]) == 0
    _ = capsys.readouterr()
    assert main(["--offline", "--cache-dir", str(tmp_path), "inspect"]) == 0
    assert json.loads(capsys.readouterr().out)["meta"]["from_cache"] is True


def test_gui_never_blocks_startup_on_the_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from echohub.__main__ import make_engine, parse_args

    calls: list[str] = []
    monkeypatch.setattr(
        "echohub.engine.EchopointEngine.sync",
        lambda *_args, **_kwargs: calls.append("sync"),
    )
    engine = make_engine(parse_args(["--cache-dir", str(tmp_path), "gui"]))
    assert calls == [], "the window checks in the background instead"
    assert not engine.has_data
