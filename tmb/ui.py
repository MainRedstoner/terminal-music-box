"""Immediate-mode UI primitives + mouse hit-testing.

Screens draw with these helpers onto a Screen and register clickable regions
in a HitMap. On a mouse press the screen looks up the region and runs its
action. Buttons use the active theme's border (rounded in Unicode mode).
"""
from __future__ import annotations

from typing import Any, List, Optional, Tuple

from .ansi import Screen, text_width, C
from .theme import Theme

Region = Tuple[int, int, int, int, Any]


class HitMap:
    def __init__(self):
        self.regions: List[Region] = []

    def clear(self) -> None:
        self.regions.clear()

    def add(self, x: int, y: int, w: int, h: int, action: Any) -> None:
        if w > 0 and h > 0:
            self.regions.append((x, y, w, h, action))

    def hit(self, x: int, y: int) -> Optional[Any]:
        for rx, ry, rw, rh, action in reversed(self.regions):
            if rx <= x < rx + rw and ry <= y < ry + rh:
                return action
        return None


def draw_box(screen: Screen, x: int, y: int, w: int, h: int, theme: Theme,
             fg=C.gray, bg=None, title: Optional[str] = None, title_fg=None) -> None:
    b = theme.border
    if w < 2 or h < 2:
        return
    screen.put(x, y, b.tl, fg, bg)
    screen.put(x + w - 1, y, b.tr, fg, bg)
    screen.put(x, y + h - 1, b.bl, fg, bg)
    screen.put(x + w - 1, y + h - 1, b.br, fg, bg)
    screen.hline(x + 1, y, w - 2, b.h, fg, bg)
    screen.hline(x + 1, y + h - 1, w - 2, b.h, fg, bg)
    for yy in range(y + 1, y + h - 1):
        screen.put(x, yy, b.v, fg, bg)
        screen.put(x + w - 1, yy, b.v, fg, bg)
        screen.hline(x + 1, yy, w - 2, " ", None, bg)
    if title:
        tx = x + 2
        screen.put(tx, y, " ", fg, bg)
        end = screen.text(tx + 1, y, title, title_fg or fg, bg, True)
        screen.put(end, y, " ", fg, bg)


def draw_button(screen: Screen, x: int, y: int, w: int, h: int, label: str,
                theme: Theme, selected=False, fg=None, bg=None, hits: Optional[HitMap] = None,
                action: Any = None) -> None:
    if selected:
        fg = fg if fg is not None else C.black
        bg = bg if bg is not None else C.cyan
    else:
        fg = fg if fg is not None else C.white
        bg = bg
    draw_box(screen, x, y, w, h, theme, fg=fg if not selected else C.cyan, bg=bg)
    # fill interior
    screen.fill(x + 1, y + 1, w - 2, h - 2, " ", fg, bg)
    tw = text_width(label)
    tx = x + max(1, (w - tw) // 2)
    ty = y + h // 2
    screen.text(tx, ty, label, fg, bg, selected)
    if hits is not None and action is not None:
        hits.add(x, y, w, h, action)


def draw_menu_row(screen: Screen, x: int, y: int, w: int, label: str, selected: bool,
                  theme: Theme, fg=None, hits: Optional[HitMap] = None, action: Any = None,
                  marker="> ") -> None:
    if selected:
        screen.fill(x, y, w, 1, " ", C.black, C.cyan)
        screen.text(x + 1, y, marker + label, C.black, C.cyan, True)
    else:
        screen.fill(x, y, w, 1, " ", fg, None)
        screen.text(x + 1, y, "  " + label, fg if fg is not None else C.white, None)
    if hits is not None and action is not None:
        hits.add(x, y, w, 1, action)


def center_text(screen: Screen, y: int, text: str, fg=None, bg=None, bold=False) -> None:
    tw = text_width(text)
    x = max(0, (screen.w - tw) // 2)
    screen.text(x, y, text, fg, bg, bold)


def clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))