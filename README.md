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

Manual refresh is explicit:

```text
REFRESH
  └─ request upstream refresh once
       └─ wait while Echopoint works
  └─ verify last_updated
       └─ download /v1/store once only if changed
```

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
| GUI/Web tables        | wheel rows, Shift+wheel/trackpad columns                 |
| GUI/Web constellation | wheel zoom, drag pan, click focus                        |

## License

MIT licensed.
