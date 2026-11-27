"""Terminal facade: picks the platform backend and owns screen lifecycle."""
from __future__ import annotations

import os
import sys
from typing import List, Optional

from .ansi import Screen
from .events import Event


def _diag(msg: str) -> None:
    """Append to the TMB_LOG_INPUT file when input diagnostics are on."""
    path = os.environ.get("TMB_LOG_INPUT")
    if path:
        try:
            with open(path + ".term", "a", encoding="utf-8") as f:
                f.write(msg + "\n")
        except OSError:
            pass

_MOUSE_ON = "\x1b[?1000h\x1b[?1002h\x1b[?1006h"
_MOUSE_OFF = "\x1b[?1006l\x1b[?1002l\x1b[?1000l"


def make_backend(no_kitty=False):
    if os.name == "nt":
        from .term_win import WindowsBackend
        return WindowsBackend()  # win32 console API: no kitty protocol involved
    from .term_posix import PosixBackend
    return PosixBackend(no_kitty=no_kitty)


class Terminal:
    def __init__(self, backend=None, no_kitty=False):
        self.backend = backend if backend is not None else make_backend(no_kitty)
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
            # Flush the switch first: the keyboard flags must be pushed on the
            # alternate screen's stack, not the main one (see term_posix).
            self.flush()
            enter = getattr(self.backend, "enter_alt_screen", None)
            if enter is not None:
                enter()
        self.write("\x1b[?25l")     # hide cursor
        self.write(_MOUSE_ON)
        self.write("\x1b[2J\x1b[H")
        self.flush()

    def teardown(self) -> None:
        _diag("term.teardown: begin")
        try:
            self.write(_MOUSE_OFF)
            self.write("\x1b[?25h")   # show cursor
            self.write("\x1b[0m")
            self.flush()
            if self._alt:
                # Pop the alternate screen's keyboard flags before leaving it;
                # the main screen's flags are popped by backend.teardown().
                leave = getattr(self.backend, "leave_alt_screen", None)
                if leave is not None:
                    leave()
                self.write("\x1b[?1049l")  # leave alternate screen
                self.flush()
            _diag("term.teardown: sequences flushed")
        finally:
            _diag("term.teardown: calling backend")
            self.backend.teardown()
            _diag("term.teardown: backend done")

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
        # An empty diff means nothing changed; writing/flushing it anyway
        # would wake the console for zero bytes every idle frame.
        data = screen.render()
        if data:
            self.write(data)
            self.flush()

    def poll(self, timeout: float) -> List[Event]:
        return self.backend.poll(timeout)

    @property
    def release_events(self) -> bool:
        """True when the backend reports key releases (kitty protocol / Windows)."""
        return bool(getattr(self.backend, "release_events", False))

    def size(self):
        return self.backend.size()