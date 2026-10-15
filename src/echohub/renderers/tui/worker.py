"""Sync and refresh off the main loop.

The worker thread never touches the screen: it puts events on a queue and
the main loop drains it between frames. Cancelling stops the work at its
next progress step, like the desktop app's task.
"""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass

from ...engine import ProgressCallback, ProgressUpdate

Work = Callable[[ProgressCallback], object]
Explain = Callable[[BaseException], tuple[str, str]]


@dataclass(frozen=True, slots=True)
class Progress:
    update: ProgressUpdate


@dataclass(frozen=True, slots=True)
class Done:
    result: object


@dataclass(frozen=True, slots=True)
class Failed:
    title: str
    detail: str


Event = Progress | Done | Failed


class _Cancelled(BaseException):
    """Unwinds a cancelled task; BaseException so no `except Exception` eats it."""


class Task:
    def __init__(self, work: Work, explain: Explain) -> None:
        self.events: queue.Queue[Event] = queue.Queue()
        self.cancelled = False
        self._work = work
        self._explain = explain
        # Daemon: a request blocked on the network must not keep the process
        # alive after the user quits. The cache is written atomically, so
        # stopping mid-write leaves the old snapshot intact.
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def cancel(self) -> None:
        self.cancelled = True

    @property
    def running(self) -> bool:
        return self._thread.is_alive()

    def join(self, timeout: float | None = None) -> None:
        self._thread.join(timeout)

    def drain(self) -> list[Event]:
        events: list[Event] = []
        while True:
            try:
                events.append(self.events.get_nowait())
            except queue.Empty:
                return events

    def _run(self) -> None:
        try:
            result = self._work(self._progress)
        except _Cancelled:
            return
        except Exception as exc:  # noqa: BLE001 > background task boundary
            if not self.cancelled:
                self.events.put(Failed(*self._explain(exc)))
        else:
            if not self.cancelled:
                self.events.put(Done(result))

    def _progress(self, update: ProgressUpdate) -> None:
        if self.cancelled:
            raise _Cancelled
        self.events.put(Progress(update))
