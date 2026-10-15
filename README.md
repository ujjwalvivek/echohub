# Echohub

**Echohub** is a local-first telemetry deck built around Echopoint data. One Python engine owns fetching, caching, normalization and analytics; two renderers consume the same `DashboardState`:

- **Desktop app** - native Qt (PySide6) app: compact, with its own chrome. The default `echohub` command.
- **TUI** - the same pages in a true-color terminal, keyboard first. Works over SSH.

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

## Desktop app

`echohub` opens the window straight away and checks Echopoint in the background, so a slow or unreachable server never blocks startup. The first run shows a welcome screen until the first snapshot arrives; after that the saved snapshot loads instantly. Failures are explained in plain words (unreachable, rejected token, and so on) while the last snapshot stays on screen.

## TUI

`echohub tui` behaves the same way: it draws the saved snapshot at once, checks in the background, and quits immediately even mid-sync. It has the desktop app's eight pages in the same order and needs at least 80 × 24; from 100 columns it adds the sidebar, and wider terminals show more columns and side panels. Press `?` on any page for its keys.

## Configuration

| Variable                                            | Default                                        | Purpose                                  |
| --------------------------------------------------- | ---------------------------------------------- | ---------------------------------------- |
| `ECHOHUB_SOURCE_URL` / `ECHOPOINT_URL`              | production Echopoint                           | Upstream base URL                        |
| `ECHOHUB_REFRESH_TOKEN` / `ECHOPOINT_REFRESH_TOKEN` | unset                                          | Enables refresh and the private snapshot |
| `ECHOHUB_CACHE_DIR` / `ECHOPOINT_CACHE_DIR`         | `%LOCALAPPDATA%\echohub` or `~/.cache/echohub` | Snapshot location                        |
| `ECHOHUB_TIMEOUT`                                   | `20`                                           | Seconds for health and snapshot requests |
| `ECHOHUB_REFRESH_TIMEOUT`                           | `120`                                          | Seconds for each upstream refresh call   |

## Quick start

```sh
# Requires Python 3.11+

# Sync with the server
python run.py sync

# Run tests
python -m pytest

# Run the desktop app and the TUI
python run.py gui
python run.py tui

# Install the package locally
python -m pip install -e .
echohub

# Offline mode (no network access)
python run.py --offline gui
python run.py --offline tui

# Demo mode (no network access, no data)
python run.py --demo gui
python run.py --demo tui
```

## Controls

| Context               | Controls                                                                      |
| --------------------- | ----------------------------------------------------------------------------- |
| Everywhere            | `R` refresh, `C` check changes, `1`–`8` switch page                           |
| TUI lists             | `J/K` or arrows, `PgDn/PgUp`, `g/G` top and bottom, `/` filter, `S` sort      |
| TUI details           | `Enter` opens, `Esc` goes back, `O` opens on GitHub                           |
| TUI panes             | `Tab` or `H/L` switch pane (Languages, Inspector), `H/L` year (Contributions) |
| TUI help and quit     | `?` lists the page's keys, `Q` quits                                          |
| Desktop tables        | click a header to sort, double-click a row to open it                         |
| Desktop Constellation | wheel zoom, drag a node or the canvas, double-click opens GitHub              |

## License

MIT licensed.
