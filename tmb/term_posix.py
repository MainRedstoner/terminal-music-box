"""POSIX terminal backend: termios raw mode + ANSI/SGR input parsing.

Used on Linux (the Raspberry Pi target), macOS and any ANSI terminal. Reads
stdin bytes, decodes UTF-8 incrementally, and turns them into normalized
events. A lone ESC is disambiguated from an escape sequence with a short
timeout. SIGWINCH delivers resize events.
"""
from __future__ import annotations

import codecs
import os
import select
import signal
import sys
import time
from typing import List

from .events import (KeyEvent, MouseEvent, ResizeEvent, Event,
                     UP, DOWN, LEFT, RIGHT, HOME, END, PGUP, PGDN, DELETE,
                     ENTER, ESC, TAB, BACKSPACE, SPACE)

_CSI_FINAL = set(chr(c) for c in range(0x40, 0x7F))
_TILDE_MAP = {
    "1": HOME, "2": "insert", "3": DELETE, "4": END, "5": PGUP, "6": PGDN,
    "7": HOME, "8": END, "11": "f1", "12": "f2", "13": "f3", "14": "f4",
    "15": "f5", "17": "f6", "18": "f7", "19": "f8", "20": "f9", "21": "f10",
    "23": "f11", "24": "f12",
}
_SS3_MAP = {"P": "f1", "Q": "f2", "R": "f3", "S": "f4",
            "A": UP, "B": DOWN, "C": RIGHT, "D": LEFT, "H": HOME, "F": END}


def _norm_printable(ch: str) -> str:
    if ch == " ":
        return SPACE
    if ch.isalpha():
        return ch.lower()
    return ch


class _Parser:
    def __init__(self):
        self._dec = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self._buf = ""
        self._pending = False

    def has_pending(self) -> bool:
        return self._pending

    def feed(self, data: bytes) -> List[Event]:
        s = self._dec.decode(data)
        self._buf += s
        return self._parse()

    def resolve_pending(self) -> List[Event]:
        out: List[Event] = []
        if self._buf.startswith("\x1b"):
            if len(self._buf) == 1:
                out.append(KeyEvent(ESC))
            # incomplete CSI/SS3 that never finished: drop it
        self._buf = ""
        self._pending = False
        return out

    def _parse(self) -> List[Event]:
        out: List[Event] = []
        s = self._buf
        i = 0
        n = len(s)
        while i < n:
            ch = s[i]
            if ch == "\x1b":
                if i + 1 >= n:
                    self._buf = s[i:]
                    self._pending = True
                    return out
                nxt = s[i + 1]
                if nxt == "[":
                    j = i + 2
                    if j < n and s[j] == "<":
                        # SGR mouse params are numeric; only M/m terminates, so a
                        # malformed sequence is dropped whole instead of leaking keys.
                        while j < n and s[j] not in "Mm":
                            j += 1
                    else:
                        while j < n and s[j] not in _CSI_FINAL:
                            j += 1
                    if j >= n:
                        self._buf = s[i:]
                        self._pending = True
                        return out
                    final = s[j]
                    params = s[i + 2:j]
                    ev = self._csi(params, final)
                    if ev is not None:
                        out.append(ev)
                    i = j + 1
                    continue
                elif nxt == "O":
                    if i + 2 >= n:
                        self._buf = s[i:]
                        self._pending = True
                        return out
                    key = _SS3_MAP.get(s[i + 2])
                    if key:
                        out.append(KeyEvent(key))
                    i += 3
                    continue
                else:
                    if nxt.isprintable():
                        out.append(KeyEvent(_norm_printable(nxt)))
                    i += 2
                    continue
            o = ord(ch)
            if o == 0x09:
                out.append(KeyEvent(TAB)); i += 1; continue
            if o in (0x0D, 0x0A):
                out.append(KeyEvent(ENTER)); i += 1; continue
            if o in (0x08, 0x7F):
                out.append(KeyEvent(BACKSPACE)); i += 1; continue
            if 0x01 <= o <= 0x1A:
                out.append(KeyEvent("ctrl+" + chr(o + 96))); i += 1; continue
            if o == 0x00:
                i += 1; continue
            if o < 0x20:
                i += 1; continue
            out.append(KeyEvent(_norm_printable(ch)))
            i += 1
        self._buf = ""
        self._pending = False
        return out

    def _csi(self, params: str, final: str):
        if params.startswith("<") and final in "Mm":
            try:
                b, x, y = (int(v) for v in params[1:].split(";"))
            except ValueError:
                return None
            return self._mouse(b, x - 1, y - 1, final == "M")
        if params.startswith("?"):
            return None
        if final == "A":
            return KeyEvent(UP)
        if final == "B":
            return KeyEvent(DOWN)
        if final == "C":
            return KeyEvent(RIGHT)
        if final == "D":
            return KeyEvent(LEFT)
        if final == "H":
            return KeyEvent(HOME)
        if final == "F":
            return KeyEvent(END)
        if final == "Z":
            return KeyEvent(TAB)
        if final == "~":
            key = _TILDE_MAP.get(params.split(";")[0])
            return KeyEvent(key) if key else None
        return None

    @staticmethod
    def _mouse(b: int, x: int, y: int, press: bool):
        if b & 64:  # wheel
            return MouseEvent(x, y, 3 if (b & 1) == 0 else 4, "wheel")
        btn = b & 3
        if b & 32:
            return MouseEvent(x, y, btn, "drag")
        return MouseEvent(x, y, btn, "press" if press else "release")


class PosixBackend:
    name = "posix"

    def __init__(self):
        import termios
        import tty
        self._termios = termios
        self._tty = tty
        self._fd = sys.stdin.fileno()
        self._old = None
        self._parser = _Parser()
        self._resized = False
        self._old_handler = None

    def setup(self) -> None:
        termios = self._termios
        self._old = termios.tcgetattr(self._fd)
        attrs = termios.tcgetattr(self._fd)
        iflag, oflag, cflag, lflag, ispeed, ospeed, cc = attrs
        lflag &= ~(termios.ECHO | termios.ICANON | termios.IEXTEN | termios.ISIG)
        iflag &= ~(termios.IXON | termios.ICRNL | termios.BRKINT | termios.INPCK | termios.ISTRIP)
        oflag &= ~termios.OPOST
        cflag |= termios.CS8
        cc[termios.VMIN] = 0
        cc[termios.VTIME] = 0
        termios.tcsetattr(self._fd, termios.TCSANOW, [iflag, oflag, cflag, lflag, ispeed, ospeed, cc])
        try:
            self._old_handler = signal.getsignal(signal.SIGWINCH)
            signal.signal(signal.SIGWINCH, self._on_winch)
        except (ValueError, OSError, AttributeError):
            pass

    def _on_winch(self, *_):
        self._resized = True

    def teardown(self) -> None:
        if self._old is not None:
            self._termios.tcsetattr(self._fd, self._termios.TCSANOW, self._old)
            self._old = None
        try:
            if self._old_handler is not None:
                signal.signal(signal.SIGWINCH, self._old_handler)
        except (ValueError, OSError, AttributeError):
            pass

    def size(self):
        import fcntl
        import struct
        import termios
        try:
            data = fcntl.ioctl(self._fd, termios.TIOCGWINSZ, b"\x00" * 8)
            rows, cols = struct.unpack("HHHH", data)[:2]
            if cols > 0 and rows > 0:
                return cols, rows
        except Exception:
            pass
        try:
            sz = os.get_terminal_size()
            return sz.columns, sz.lines
        except OSError:
            return 80, 24

    def poll(self, timeout: float) -> List[Event]:
        events: List[Event] = []
        fd = self._fd
        r, _, _ = select.select([fd], [], [], timeout)
        if r:
            data = os.read(fd, 65536)
            if data:
                events += self._parser.feed(data)
            while True:
                r, _, _ = select.select([fd], [], [], 0)
                if not r:
                    break
                data = os.read(fd, 65536)
                if not data:
                    break
                events += self._parser.feed(data)
        if self._parser.has_pending():
            r, _, _ = select.select([fd], [], [], 0.03)
            if r:
                data = os.read(fd, 65536)
                if data:
                    events += self._parser.feed(data)
            if self._parser.has_pending():
                events += self._parser.resolve_pending()
        if self._resized:
            self._resized = False
            w, h = self.size()
            events.append(ResizeEvent(w, h))
        return events