"""POSIX terminal backend: termios raw mode + ANSI/SGR input parsing.

Used on Linux (the Raspberry Pi target), macOS and any ANSI terminal. Reads
stdin bytes, decodes UTF-8 incrementally, and turns them into normalized
events. A lone ESC is disambiguated from an escape sequence with a short
timeout. SIGWINCH delivers resize events.
"""
from __future__ import annotations

import codecs
import os
import re
import select
import signal
import sys
import time
from typing import List, Optional

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
# Kitty keyboard protocol functional key code points (CSI-u encoding).
_KITTY_KEYS = {
    9: TAB, 13: ENTER, 27: ESC, 32: SPACE, 127: BACKSPACE,
}
_KITTY_MOD_CTRL = 4  # shift=1 alt=2 ctrl=4 in the modifier bitfield


def _norm_printable(ch: str) -> str:
    if ch == " ":
        return SPACE
    if ch.isalpha():
        return ch.lower()
    return ch


def _event_type(params: str) -> int:
    """Event type from CSI params: 1 press, 2 repeat, 3 release.

    Kitty encodes it as the second colon sub-field of the second parameter,
    e.g. "1;1:3" (arrow release) or "97;5:3" (ctrl+a release).
    """
    parts = params.split(";")
    if len(parts) >= 2 and ":" in parts[1]:
        tail = parts[1].split(":")
        if len(tail) >= 2 and tail[1].isdigit():
            return int(tail[1])
    return 1


def under_wsl() -> bool:
    """True when running under the Windows Subsystem for Linux.

    ConPTY (the terminal layer behind WSL) stops delivering kitty key
    release events once an application switches to the alternate screen,
    so there we trade the screen-restore nicety for working key-up events.
    """
    try:
        with open("/proc/version", "r", encoding="utf-8", errors="replace") as f:
            return "microsoft" in f.read().lower()
    except OSError:
        return False


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
            return None  # mode / capability replies (DA1, kitty flag query)
        if final == "u":
            return self._csi_u(params)
        et = _event_type(params)
        if final == "A":
            return KeyEvent(UP, et != 3, et == 2)
        if final == "B":
            return KeyEvent(DOWN, et != 3, et == 2)
        if final == "C":
            return KeyEvent(RIGHT, et != 3, et == 2)
        if final == "D":
            return KeyEvent(LEFT, et != 3, et == 2)
        if final == "H":
            return KeyEvent(HOME, et != 3, et == 2)
        if final == "F":
            return KeyEvent(END, et != 3, et == 2)
        if final == "Z":
            return KeyEvent(TAB)
        if final == "~":
            key = _TILDE_MAP.get(params.split(";")[0])
            return KeyEvent(key, et != 3, et == 2) if key else None
        return None

    def _csi_u(self, params: str):
        """Kitty protocol: CSI unicode-key[:alts] ; modifiers:event-type ; text u."""
        try:
            fields = params.split(";")
            key_num = int(fields[0].split(":")[0])
            mods = 0
            et = 1
            if len(fields) >= 2 and fields[1]:
                sub = fields[1].split(":")
                if sub[0].isdigit():
                    mods = max(0, int(sub[0]) - 1)
                if len(sub) >= 2 and sub[1].isdigit():
                    et = int(sub[1])
        except (ValueError, IndexError):
            return None
        if key_num in _KITTY_KEYS:
            key = _KITTY_KEYS[key_num]
        elif 33 <= key_num < 127:
            key = _norm_printable(chr(key_num))
        else:
            return None
        if mods & _KITTY_MOD_CTRL and len(key) == 1 and key.isalpha():
            key = "ctrl+" + key
        return KeyEvent(key, et != 3, et == 2)

    @staticmethod
    def _mouse(b: int, x: int, y: int, press: bool):
        if b & 64:  # wheel
            return MouseEvent(x, y, 3 if (b & 1) == 0 else 4, "wheel")
        btn = b & 3
        if b & 32:
            return MouseEvent(x, y, btn, "drag")
        return MouseEvent(x, y, btn, "press" if press else "release")


def _parse_flags_reply(buf: bytes) -> Optional[int]:
    """First kitty flags-reply (``CSI ? flags u``) in *buf*, else None."""
    m = re.search(rb"\x1b\[\?([\d;]+)u", buf)
    if m:
        try:
            return int(m.group(1).split(b";")[0])
        except ValueError:
            return None
    return None


class PosixBackend:
    name = "posix"
    release_events = False  # set True when the kitty protocol is negotiated

    def __init__(self, no_kitty=False):
        import termios
        import tty
        self._termios = termios
        self._tty = tty
        self._fd = sys.stdin.fileno()
        self._old = None
        self._parser = _Parser()
        self._resized = False
        self._old_handler = None
        self._no_kitty = no_kitty  # --no-kitty: test the legacy-key paths
        self._kitty = False
        self._diag_log = None
        path = os.environ.get("TMB_LOG_INPUT")
        if path:
            try:
                self._diag_log = open("%s.%d" % (path, os.getpid()), "a",
                                      encoding="utf-8", buffering=1)
            except OSError:
                self._diag_log = None

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
        self._kitty = not self._no_kitty and self._negotiate_kitty()
        self.release_events = self._kitty
        # WSL/ConPTY drops kitty releases while on the alternate screen; there
        # we skip it so key-up events (needed for sustained timbres) keep
        # flowing. Native terminals deliver releases fine either way.
        self.use_alt_screen = not (self._kitty and under_wsl())
        self._diag("setup: kitty=%r release_events=%r use_alt_screen=%r"
                   % (self._kitty, self.release_events, self.use_alt_screen))
        try:
            self._old_handler = signal.getsignal(signal.SIGWINCH)
            signal.signal(signal.SIGWINCH, self._on_winch)
        except (ValueError, OSError, AttributeError):
            pass

    def _negotiate_kitty(self) -> bool:
        """Enable the kitty keyboard protocol for press/repeat/release events.

        Push flags (disambiguate | report event types), then query the current
        flags and DA1. A ``CSI ? <flags> u`` reply proves support; a DA1-only
        reply (or silence) means unsupported and we pop the flags again.
        """
        try:
            out = sys.stdout.buffer
            out.write(b"\x1b[>3u\x1b[?u\x1b[c")
            out.flush()
        except Exception:
            return False
        data = b""
        end = time.monotonic() + 0.2
        kitty = False
        while time.monotonic() < end:
            r, _, _ = select.select([self._fd], [], [], max(0.0, end - time.monotonic()))
            if not r:
                break
            data += os.read(self._fd, 4096)
            if re.search(rb"\x1b\[\?[\d;]+u", data):
                kitty = True
                break
        if not kitty:
            # The push may still have taken effect even though the reply was
            # missed (slow terminal); clear it and check whether the terminal
            # is kitty-capable after all.
            try:
                out.write(b"\x1b[<u\x1b[=0;1u")
                out.flush()
            except Exception:
                pass
            if self._kitty_flags(0.2) not in (0, None):
                self._kitty_shutdown()
        return kitty

    def _kitty_flags(self, timeout: float) -> Optional[int]:
        """Query the terminal's active kitty flags; None when it stays silent."""
        try:
            sys.stdout.buffer.write(b"\x1b[?u")
            sys.stdout.buffer.flush()
        except Exception:
            return None
        buf = b""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            r, _, _ = select.select([self._fd], [], [], max(0.0, end - time.monotonic()))
            if r:
                buf += os.read(self._fd, 65536)
                flags = _parse_flags_reply(buf)
                if flags is not None:
                    self._diag("kitty_flags -> %d (%r)" % (flags, buf))
                    return flags
        self._diag("kitty_flags -> None (no reply)")
        return None

    def _drain_stdin(self, seconds: float) -> None:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            r, _, _ = select.select([self._fd], [], [], max(0.0, end - time.monotonic()))
            if not r:
                return
            os.read(self._fd, 65536)

    def _kitty_shutdown(self) -> None:
        """Pop the pushed kitty flags and verify they actually cleared.

        ConPTY behind WSL parses client output asynchronously and drops the
        tail of a heavy stream when the process exits — the pop then never
        takes effect and the shell inherits kitty-encoded keys. The flags
        query forces a round trip; if the replies stay inconclusive, hold the
        process briefly so ConPTY can still consume the pending escapes.
        """
        try:
            self._diag("kitty_shutdown: begin")
            for attempt in range(3):
                self._drain_stdin(0.1)  # stale replies first
                sys.stdout.buffer.write(b"\x1b[<u\x1b[=0;1u")
                sys.stdout.buffer.flush()
                if self._kitty_flags(0.25) in (0, None):
                    self._diag("kitty_shutdown: cleared on attempt %d" % (attempt + 1))
                    return
            time.sleep(0.3)  # inconclusive: let the async parser drain
            self._diag("kitty_shutdown: inconclusive after retries")
        except Exception:
            pass

    def teardown(self) -> None:
        self._diag("teardown: begin (kitty=%r)" % self._kitty)
        if self._kitty:
            self._kitty = False
            self.release_events = False
            self._kitty_shutdown()
        if self._old is not None:
            self._termios.tcsetattr(self._fd, self._termios.TCSANOW, self._old)
            self._old = None
        self._diag("teardown: end")
        try:
            if self._old_handler is not None:
                signal.signal(signal.SIGWINCH, self._old_handler)
        except (ValueError, OSError, AttributeError):
            pass

    def _on_winch(self, *_):
        self._resized = True

    def _diag(self, msg: str) -> None:
        """Append to the TMB_LOG_INPUT file when input diagnostics are on."""
        if self._diag_log is not None:
            try:
                self._diag_log.write(msg + "\n")
                self._diag_log.flush()
            except Exception:
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
                n = len(events)
                events += self._parser.feed(data)
                self._diag("in=%r -> %r" % (data, events[n:]))
            while True:
                r, _, _ = select.select([fd], [], [], 0)
                if not r:
                    break
                data = os.read(fd, 65536)
                if not data:
                    break
                n = len(events)
                events += self._parser.feed(data)
                self._diag("in=%r -> %r" % (data, events[n:]))
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