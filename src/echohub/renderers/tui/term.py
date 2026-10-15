"""Terminal I/O: raw keys in, changed lines out.

``KeyDecoder`` turns raw input into key names and has no I/O, so tests feed
it strings. ``Terminal`` owns the real console: cbreak mode on POSIX, VT
output on Windows, the alternate screen, and drawing only the lines that
changed since the last frame.
"""

from __future__ import annotations

import codecs
import os
import shutil
import sys
import time
from collections.abc import Callable
from types import TracebackType
from typing import Self

ESC = "\x1b"

# Final byte of a CSI sequence -> key. ESC [ A, ESC [ 1;5A (modifiers ignored).
_CSI_LETTERS = {
    "A": "up",
    "B": "down",
    "C": "right",
    "D": "left",
    "H": "home",
    "F": "end",
    "Z": "backtab",
}
# ESC [ n ~
_CSI_TILDE = {
    "1": "home",
    "7": "home",
    "4": "end",
    "8": "end",
    "3": "delete",
    "5": "pgup",
    "6": "pgdn",
}
# Windows console: msvcrt returns a 0x00 or 0xE0 prefix, then one of these.
_WINDOWS_KEYS = {
    "H": "up",
    "P": "down",
    "K": "left",
    "M": "right",
    "G": "home",
    "O": "end",
    "I": "pgup",
    "Q": "pgdn",
    "S": "delete",
    "\x0f": "backtab",
}
_CONTROLS = {
    "\r": "enter",
    "\n": "enter",
    "\t": "tab",
    "\x7f": "backspace",
    "\x08": "backspace",
    "\x03": "ctrl-c",
}


class KeyDecoder:
    """Raw terminal input to key names: "j", "G", "up", "pgdn", "enter", "esc"…

    A lone ESC is held back, because it may start a sequence whose rest is
    still in flight; ``flush`` releases it once no more input has come.
    """

    def __init__(self) -> None:
        self._pending = ""

    @property
    def pending(self) -> bool:
        return bool(self._pending)

    def feed(self, data: str) -> list[str]:
        buffer = self._pending + data
        self._pending = ""
        keys: list[str] = []
        index = 0
        while index < len(buffer):
            char = buffer[index]
            if char != ESC:
                if char == "\r" and buffer[index + 1 : index + 2] == "\n":
                    index += 1
                key = _CONTROLS.get(char)
                if key is not None:
                    keys.append(key)
                elif char >= " ":
                    keys.append(char)
                index += 1
                continue
            used, key = _escape(buffer, index)
            if used == 0:
                # Incomplete: keep it until more arrives or flush() gives up.
                self._pending = buffer[index:]
                break
            if key:
                keys.append(key)
            index += used
        return keys

    def flush(self) -> list[str]:
        """No more input came: a held ESC was the Escape key."""
        pending, self._pending = self._pending, ""
        return ["esc"] if pending.startswith(ESC) else []


def _escape(buffer: str, start: int) -> tuple[int, str]:
    """Decode the sequence at ``start`` (an ESC): (chars used, key or "").

    Returns (0, "") when the sequence isn't complete yet.
    """
    rest = buffer[start + 1 :]
    if not rest:
        return 0, ""
    lead = rest[0]
    if lead == "O":  # SS3: ESC O A …
        if len(rest) < 2:
            return 0, ""
        return 3, _CSI_LETTERS.get(rest[1], "")
    if lead != "[":
        # ESC then a plain key (Alt+key, or Escape typed right before it):
        # report Escape and let the key decode on its own.
        return 1, "esc"
    # CSI: parameters, then a final byte in 0x40-0x7E.
    for offset in range(1, len(rest)):
        char = rest[offset]
        if "\x40" <= char <= "\x7e":
            params = rest[1:offset]
            if char == "~":
                return offset + 2, _CSI_TILDE.get(params.split(";")[0], "")
            return offset + 2, _CSI_LETTERS.get(char, "")
    return 0, ""


def windows_key(prefix: str, code: str) -> str:
    """A Windows special key (arrow, PgDn…) from msvcrt's two-part code."""
    del prefix  # 0x00 and 0xE0 mean the same keys here
    return _WINDOWS_KEYS.get(code, "")


class Terminal:
    """The real console. Use as a context manager around the main loop."""

    ENTER = "\x1b[?1049h\x1b[?25l\x1b[?7l\x1b[2J"
    LEAVE = "\x1b[0m\x1b[?7h\x1b[?25h\x1b[?1049l"

    def __init__(self) -> None:
        self.decoder = KeyDecoder()
        self._restore: Callable[[], None] | None = None
        self._utf8 = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self._last: list[str] = []
        self._size: tuple[int, int] = (0, 0)

    def __enter__(self) -> Self:
        if os.name == "nt":
            _enable_windows_vt()
        elif sys.stdin.isatty():
            import termios
            import tty

            fd = sys.stdin.fileno()
            saved = termios.tcgetattr(fd)
            tty.setcbreak(fd)
            self._restore = lambda: termios.tcsetattr(fd, termios.TCSADRAIN, saved)
        if (sys.stdout.encoding or "").lower().replace("-", "") != "utf8":
            # A pipe or legacy code page can't take the box and block glyphs.
            sys.stdout.reconfigure(encoding="utf-8")  # pyright: ignore[reportAttributeAccessIssue]
        self.write(self.ENTER)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.write(self.LEAVE)
        if self._restore is not None:
            self._restore()

    def size(self) -> tuple[int, int]:
        size = shutil.get_terminal_size((80, 24))
        return size.columns, size.lines

    def write(self, data: str) -> None:
        _ = sys.stdout.write(data)
        sys.stdout.flush()

    def draw(self, lines: list[str], size: tuple[int, int]) -> None:
        """Write the lines that changed since the last frame."""
        out: list[str] = []
        if size != self._size:
            # Resized: start clean so nothing from the old layout survives.
            out.append("\x1b[2J")
            self._last = []
            self._size = size
        for row, line in enumerate(lines):
            if row < len(self._last) and self._last[row] == line:
                continue
            out.append(f"\x1b[{row + 1};1H{line}")
        self._last = list(lines)
        if out:
            self.write("".join(out))

    def redraw_all(self) -> None:
        self._last = []
        self._size = (0, 0)

    def read_keys(self, timeout: float) -> list[str]:
        """Keys pressed within ``timeout`` seconds (empty if none)."""
        if os.name == "nt":
            return self._read_windows(timeout)
        return self._read_posix(timeout)

    def _read_posix(self, timeout: float) -> list[str]:
        import select

        if not sys.stdin.isatty():
            time.sleep(timeout)
            return []
        fd = sys.stdin.fileno()
        ready, _, _ = select.select([fd], [], [], timeout)
        if not ready:
            return self.decoder.flush() if self.decoder.pending else []
        keys = self.decoder.feed(self._utf8.decode(os.read(fd, 4096)))
        while self.decoder.pending:
            # The rest of an escape sequence arrives within a few ms.
            ready, _, _ = select.select([fd], [], [], 0.03)
            if not ready:
                keys += self.decoder.flush()
                break
            keys += self.decoder.feed(self._utf8.decode(os.read(fd, 4096)))
        return keys

    def _read_windows(self, timeout: float) -> list[str]:
        import msvcrt

        deadline = time.monotonic() + timeout
        while not msvcrt.kbhit():
            if time.monotonic() >= deadline:
                return []
            time.sleep(0.01)
        keys: list[str] = []
        while msvcrt.kbhit():
            char = msvcrt.getwch()
            if char in ("\x00", "\xe0"):
                key = windows_key(char, msvcrt.getwch())
                if key:
                    keys.append(key)
                continue
            keys += self.decoder.feed(char)
        # The Windows console sends Escape as a lone ESC, never a sequence.
        return keys + self.decoder.flush()


def _enable_windows_vt() -> None:
    """Let the Windows console interpret ANSI sequences on stdout."""
    import ctypes

    kernel32 = ctypes.windll.kernel32
    handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
    mode = ctypes.c_uint32()
    if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
        # ENABLE_PROCESSED_OUTPUT | ENABLE_VIRTUAL_TERMINAL_PROCESSING
        _ = kernel32.SetConsoleMode(handle, mode.value | 0x0001 | 0x0004)
