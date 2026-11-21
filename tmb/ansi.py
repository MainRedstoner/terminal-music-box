"""ANSI screen buffer + diff renderer. No third-party dependencies.

A Screen is a grid of cells (char, fg, bg, bold). Wide (CJK) characters occupy
two columns; the trailing column is marked as a continuation cell and skipped
when rendering. Rendering only redraws rows that changed since the last frame,
which keeps SSH / serial output on a Raspberry Pi cheap.
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


def _sgr(fg: Optional[int], bg: Optional[int], bold: bool) -> str:
    codes = []
    if bold:
        codes.append("1")
    if fg is not None:
        codes.append("38;5;%d" % fg)
    if bg is not None:
        codes.append("48;5;%d" % bg)
    if not codes:
        return "\x1b[0m"
    return "\x1b[0m\x1b[" + ";".join(codes) + "m"


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
        self.cells = [[DEFAULT_CELL for _ in range(self.w)] for _ in range(self.h)]

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
        """Return the ANSI escape string that updates the terminal."""
        out = ["\x1b[?25l"]  # hide cursor while drawing
        prev = self._prev
        force = self._force or len(prev) != self.h
        for y in range(self.h):
            row = self.cells[y]
            if not force and y < len(prev) and prev[y] == row:
                continue
            out.append("\x1b[%d;1H" % (y + 1))
            style = (None, None, False)
            buf = []
            x = 0
            while x < self.w:
                ch, fg, bg, bold = row[x]
                if ch == CONT:
                    x += 1
                    continue
                st = (fg, bg, bold)
                if st != style:
                    if buf:
                        out.append("".join(buf))
                        buf = []
                    out.append(_sgr(fg, bg, bold))
                    style = st
                buf.append(ch if ch else " ")
                x += 1
            if buf:
                out.append("".join(buf))
            out.append("\x1b[0m")
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