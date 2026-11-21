"""ANSI screen buffer + diff renderer. No third-party dependencies.

A Screen is a grid of cells (char, fg, bg, bold). Wide (CJK) characters occupy
two columns; the trailing column is marked as a continuation cell and skipped
when rendering. Rendering only redraws rows that changed since the last frame,
which keeps SSH / serial output on a Raspberry Pi cheap, and restates only the
style attributes that actually changed (minimal SGR) — a full reset + complete
restyle per transition roughly doubles the stream, and ConPTY parses every
byte of every frame.
"""
from __future__ import annotations

import unicodedata
from functools import lru_cache
from typing import List, Optional, Tuple

# 256-color palette indices (widely supported: Linux console, SSH, Windows Terminal)
class C:
    default: Optional[int] = None
    black = 16
    red = 196
    green = 46
    yellow = 226
    blue = 39
    magenta = 201
    cyan = 51
    white = 231
    gray = 244
    dim = 238
    orange = 208
    pink = 213
    lime = 118
    gold = 220
    panel = 236
    panel_hi = 240
    judge = 226


Cell = Tuple[str, Optional[int], Optional[int], bool]
CONT = ""  # continuation marker for the 2nd column of a wide char
DEFAULT_CELL: Cell = (" ", None, None, False)


@lru_cache(maxsize=4096)
def char_width(ch: str) -> int:
    if not ch:
        return 0
    if unicodedata.combining(ch):
        return 0
    cat = unicodedata.category(ch)
    if cat in ("Mn", "Me", "Cf"):
        return 0
    if unicodedata.east_asian_width(ch) in ("W", "F"):
        return 2
    return 1


def text_width(s: str) -> int:
    return sum(char_width(c) for c in s)


@lru_cache(maxsize=64)
def _fg_seq(fg: Optional[int]) -> str:
    return "\x1b[39m" if fg is None else "\x1b[38;5;%dm" % fg


@lru_cache(maxsize=64)
def _bg_seq(bg: Optional[int]) -> str:
    return "\x1b[49m" if bg is None else "\x1b[48;5;%dm" % bg


def _sgr_delta(pfg: Optional[int], pbg: Optional[int], pbold: bool,
               fg: Optional[int], bg: Optional[int], bold: bool) -> str:
    """Minimal SGR: restate only the attributes that actually changed.

    Cached sequence strings: the same handful of styles repeat hundreds of
    times per frame across the grid.
    """
    seq = []
    if bold != pbold:
        seq.append("\x1b[1m" if bold else "\x1b[22m")
    if fg != pfg:
        seq.append(_fg_seq(fg))
    if bg != pbg:
        seq.append(_bg_seq(bg))
    return "".join(seq)


class Screen:
    def __init__(self, w: int, h: int):
        self.w = w
        self.h = h
        self.cells: List[List[Cell]] = []
        self._prev: List[List[Cell]] = []
        self.clear()
        self._prev = [row[:] for row in self.cells]
        self._force = True

    def resize(self, w: int, h: int) -> None:
        self.w, self.h = w, h
        self.clear()
        self._prev = []
        self._force = True

    def clear(self) -> None:
        # Reset the existing row lists in place via slice assignment. The old
        # scheme rebuilt every row list per frame, churning w*h slots of
        # garbage that showed up as periodic GC hitches (dropped frames) in
        # the rhythm game.
        blank = [DEFAULT_CELL] * self.w
        rows = self.cells
        if len(rows) != self.h:
            self.cells = [blank[:] for _ in range(self.h)]
        else:
            for row in rows:
                row[:] = blank

    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.w and 0 <= y < self.h

    def put(self, x: int, y: int, ch: str, fg=None, bg=None, bold=False) -> None:
        if not self.in_bounds(x, y):
            return
        w = char_width(ch)
        if w == 0:
            return
        self.cells[y][x] = (ch, fg, bg, bold)
        if w == 2 and x + 1 < self.w:
            self.cells[y][x + 1] = (CONT, fg, bg, bold)

    def text(self, x: int, y: int, s: str, fg=None, bg=None, bold=False) -> int:
        """Draw a string starting at (x,y). Returns the next free column."""
        cx = x
        for ch in s:
            w = char_width(ch)
            if w == 0:
                continue
            if cx >= self.w:
                break
            self.put(cx, y, ch, fg, bg, bold)
            cx += w
        return cx

    def fill(self, x: int, y: int, w: int, h: int, ch=" ", fg=None, bg=None, bold=False) -> None:
        for yy in range(y, y + h):
            for xx in range(x, x + w):
                self.put(xx, yy, ch, fg, bg, bold)

    def hline(self, x: int, y: int, w: int, ch: str, fg=None, bg=None) -> None:
        for xx in range(x, x + w):
            self.put(xx, y, ch, fg, bg)

    def render(self) -> str:
        """Return the ANSI escape string that updates the terminal.

        Only rows that changed are emitted, and each style transition restates
        only the attributes that differ from what the terminal is currently
        showing. An empty string means nothing changed at all — the caller
        should not flush anything.
        """
        out = []
        prev = self._prev
        force = self._force or len(prev) != self.h
        emitted = False
        # Terminal attribute state; the leading reset makes it a known
        # baseline for every frame, so no per-row trailing reset is needed.
        pfg = pbg = None
        pbold = False
        for y in range(self.h):
            row = self.cells[y]
            if not force and y < len(prev) and prev[y] == row:
                continue
            if not emitted:
                out.append("\x1b[0m")
                emitted = True
            out.append("\x1b[%d;1H" % (y + 1))
            buf = []
            x = 0
            while x < self.w:
                ch, fg, bg, bold = row[x]
                if ch == CONT:
                    x += 1
                    continue
                if fg != pfg or bg != pbg or bold != pbold:
                    if buf:
                        out.append("".join(buf))
                        buf = []
                    out.append(_sgr_delta(pfg, pbg, pbold, fg, bg, bold))
                    pfg, pbg, pbold = fg, bg, bold
                buf.append(ch if ch else " ")
                x += 1
            if buf:
                out.append("".join(buf))
        if not emitted:
            return ""
        # Snapshot for the next diff, reusing the previous row lists.
        if len(prev) == self.h:
            for p, row in zip(prev, self.cells):
                p[:] = row
        else:
            self._prev = [row[:] for row in self.cells]
        self._force = False
        return "".join(out)

    def plain_text(self) -> str:
        """ANSI-stripped snapshot of the grid (for tests / headless mode).

        Continuation columns of wide chars are omitted so CJK reads naturally.
        """
        lines = []
        for row in self.cells:
            # List comp (not genexpr): join() over a list is measurably faster,
            # and this runs once per rendered frame.
            lines.append("".join([c[0] for c in row if c[0] and c[0] != CONT]).rstrip())
        return "\n".join(lines)