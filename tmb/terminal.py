"""Terminal facade: picks the platform backend and owns screen lifecycle."""
from __future__ import annotations

import os
import sys
from typing import List, Optional

from .ansi import Screen
from .events import Event

_MOUSE_ON = "\x1b[?1000h\x1b[?1002h\x1b[?1006h"
_MOUSE_OFF = "\x1b[?1006l\x1b[?1002l\x1b[?1000l"


def make_backend():
    if os.name == "nt":
        from .term_win import WindowsBackend
        return WindowsBackend()
    from .term_posix import PosixBackend
    return PosixBackend()


class Terminal:
    def __init__(self, backend=None):
        self.backend = backend if backend is not None else make_backend()
        self.screen: Optional[Screen] = None
        self._buf: List[str] = []
        self._alt = False

    def __enter__(self):
        self.setup()
        return self

    def __exit__(self, *exc):
        self.teardown()
        return False

    def setup(self) -> None:
        self.backend.setup()
        w, h = self.backend.size()
        self.screen = Screen(w, h)
        # The alternate screen restores the shell on exit, but ConPTY behind
        # WSL stops delivering kitty key releases there, so the backend can
        # opt out (see PosixBackend.use_alt_screen).
        self._alt = bool(getattr(self.backend, "use_alt_screen", True))
        if self._alt:
            self.write("\x1b[?1049h")   # alternate screen buffer
        self.write("\x1b[?25l")     # hide cursor
        self.write(_MOUSE_ON)
        self.write("\x1b[2J\x1b[H")
        self.flush()

    def teardown(self) -> None:
        try:
            self.write(_MOUSE_OFF)
            self.write("\x1b[?25h")   # show cursor
            if self._alt:
                self.write("\x1b[?1049l")  # leave alternate screen
            self.write("\x1b[0m")
            self.flush()
        finally:
            self.backend.teardown()

    def write(self, s: str) -> None:
        self._buf.append(s)

    def flush(self) -> None:
        if not self._buf:
            return
        data = "".join(self._buf).encode("utf-8")
        self._buf = []
        stream = getattr(sys.stdout, "buffer", None)
        if stream is not None:
            stream.write(data)
            stream.flush()
        else:
            sys.stdout.write(data.decode("utf-8", "replace"))
            sys.stdout.flush()

    def render(self, screen: Screen) -> None:
        self.write(screen.render())
        self.flush()

    def poll(self, timeout: float) -> List[Event]:
        return self.backend.poll(timeout)

    @property
    def release_events(self) -> bool:
        """True when the backend reports key releases (kitty protocol / Windows)."""
        return bool(getattr(self.backend, "release_events", False))

    def size(self):
        return self.backend.size()