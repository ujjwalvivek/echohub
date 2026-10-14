# Echohub

**Echohub** is a local-first telemetry deck built around Echopoint data. One Python engine owns fetching, caching, normalization and analytics; two renderers consume the same `DashboardState`:

- **GUI** - native Python/Tk desktop app with dense data workspaces and interactive canvases.
- **TUI** - keyboard-first true-color terminal interface.

## Network contract

```text
GET /v1/health
       │
       ├── last_updated unchanged ──> use local store.json
       │
       └── last_updated changed ────> GET /v1/store once
```

With a token configured, the snapshot comes from `GET /v1/private` instead, which includes private repositories. A cached snapshot of the other kind is re-downloaded even if `last_updated` is unchanged.

Manual refresh is explicit:

```text
REFRESH
  └─ POST /v1/refresh, repeated until Echopoint's due queue is empty
       └─ each call is one Worker run with a fixed fetch budget
  └─ verify last_updated
       └─ download the snapshot once only if changed
```

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `ECHOHUB_SOURCE_URL` / `ECHOPOINT_URL` | production Echopoint | Upstream base URL |
| `ECHOHUB_REFRESH_TOKEN` / `ECHOPOINT_REFRESH_TOKEN` | unset | Enables refresh and the private snapshot |
| `ECHOHUB_CACHE_DIR` / `ECHOPOINT_CACHE_DIR` | `%LOCALAPPDATA%\echohub` or `~/.cache/echohub` | Snapshot location |
| `ECHOHUB_TIMEOUT` | `20` | Seconds for health and snapshot requests |
| `ECHOHUB_REFRESH_TIMEOUT` | `120` | Seconds for each upstream refresh call |

## Quick start

```sh
# Requires Python 3.11+

# Sync with the server
python run.py sync

# Run tests
python -m pytest

# Run the GUI and TUI
python run.py gui
python run.py tui

# Install the package locally
python -m pip install -e .
echohub gui

# Offline mode (no network access)
python run.py --offline gui
python run.py --offline tui

# Demo mode (no network access, no data)
python run.py --demo gui
python run.py --demo tui
```

## Controls

| Context               | Controls                                                 |
| --------------------- | -------------------------------------------------------- |
| Global                | `R` refresh, `C` check changes, `1`–`8` switch workspace |
| TUI Projects          | `J/K` rows, `H/L` column window                          |
| TUI Constellation     | `J/K` focused project                                    |
| TUI Activity          | `J/K` commits                                            |
| TUI Contributions     | `H/L` weeks                                              |
| TUI Sources           | `T` tab, `J/K` rows                                      |
| TUI Inspector         | `J/K` keys                                               |
| GUI tables            | wheel rows, Shift+wheel/trackpad columns                 |
| GUI constellation     | wheel zoom, drag pan, click focus                        |

## License

MIT licensed.
