"""Immediate-mode UI primitives + mouse hit-testing.

Screens draw with these helpers onto a Screen and register clickable regions
in a HitMap. On a mouse press the screen looks up the region and runs its
action. Buttons use the active theme's border (rounded in Unicode mode).
"""
from __future__ import annotations

from typing import Any, List, Optional, Tuple

from .ansi import Screen, char_width, text_width, C
from .theme import Theme

Region = Tuple[int, int, int, int, Any]

# A search query longer than this is useless and dangerous: a pasted blob
# used to make every keystroke O(len) over the whole query (matches(),
# casefold, the draw pass) - quadratic across a paste burst.
QUERY_MAX = 256


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
    fg = fg if fg is not None else C.white
    # Selection recolors the border only; the interior keeps no highlight fill.
    draw_box(screen, x, y, w, h, theme, fg=C.cyan if selected else fg, bg=bg)
    # fill interior
    screen.fill(x + 1, y + 1, w - 2, h - 2, " ", fg, bg)
    label = fit_text(label, max(1, w - 2))
    tw = text_width(label)
    tx = x + max(1, (w - tw) // 2)
    ty = y + h // 2
    screen.text(tx, ty, label, fg, bg, selected)
    if hits is not None and action is not None:
        hits.add(x, y, w, h, action)


def draw_menu_row(screen: Screen, x: int, y: int, w: int, label: str, selected: bool,
                  theme: Theme, fg=None, hits: Optional[HitMap] = None, action: Any = None,
                  marker="> ") -> None:
    # fit_text keeps a long label (an external pack's unbounded title, a
    # narrow terminal's fixed labels) from overwriting the row's border and
    # the neighbouring pane; draw_search_result_row already did this.
    if selected:
        screen.fill(x, y, w, 1, " ", C.black, C.cyan)
        label = fit_text(label, max(1, w - 1 - text_width(marker)))
        screen.text(x + 1, y, marker + label, C.black, C.cyan, True)
    else:
        screen.fill(x, y, w, 1, " ", fg, None)
        label = fit_text(label, max(1, w - 3))
        screen.text(x + 1, y, "  " + label, fg if fg is not None else C.white, None)
    if hits is not None and action is not None:
        hits.add(x, y, w, 1, action)


def matches(query: str, aliases) -> bool:
    """Case-insensitive substring match over one entry's alias strings.

    Searchable lists pass every name an entry is findable by (both languages,
    ids…), so a query finds items regardless of the active UI language.
    """
    q = query.casefold()
    return any(q in str(a).casefold() for a in aliases if a)


def draw_search_field(screen: Screen, x: int, y: int, w: int, query: str,
                      theme: Theme) -> int:
    """The '/query▌' input line of a searchable list; returns its width.

    Overlong queries drop characters from the left so the caret stays
    visible. The kept suffix is found in one right-to-left pass: the old loop
    re-measured the whole remaining string per dropped character, which made
    a pasted query an O(n²) frame (seconds of freeze at 8k characters).
    """
    cursor = "▌" if theme.is_unicode else "_"
    limit = max(1, w) - text_width(cursor) - 1
    used = 0
    start = len(query)
    while start > 0 and used + char_width(query[start - 1]) <= limit:
        used += char_width(query[start - 1])
        start -= 1
    if start == len(query) and query:
        # Even one character overflows: show the last one (the old loop also
        # never dropped the final character).
        start = len(query) - 1
    query = query[start:]
    line = "/" + query + cursor
    screen.text(x, y, line, C.white, None, True)
    return text_width(line)


def fit_text(s: str, width: int) -> str:
    """Truncate s to at most `width` display columns (CJK-aware)."""
    if text_width(s) <= width:
        return s
    out: List[str] = []
    used = 0
    for ch in s:
        cw = char_width(ch)
        if used + cw > width:
            break
        out.append(ch)
        used += cw
    return "".join(out)


def match_spans(text: str, query: str) -> List[Tuple[int, int]]:
    """Character-index spans where the casefolded query occurs in text."""
    q = query.casefold()
    if not q:
        return []
    folded = text.casefold()
    if len(folded) != len(text):  # casefold rescaled a char: try plain lower()
        folded = text.lower()
        if len(folded) != len(text):
            return []
    spans: List[Tuple[int, int]] = []
    i = folded.find(q)
    while i != -1:
        spans.append((i, i + len(q)))
        i = folded.find(q, i + 1)
    return spans


def draw_text_highlighted(screen: Screen, x: int, y: int, text: str, query: str,
                          fg=None, bg=None, bold=False) -> int:
    """Draw text with every query match chipped in gold; returns the next column.

    Expects pre-truncated text (see fit_text) — matching runs on what is drawn
    so spans always line up.
    """
    cx = x
    pos = 0
    for s, e in match_spans(text, query):
        if s > pos:
            cx = screen.text(cx, y, text[pos:s], fg, bg, bold)
        cx = screen.text(cx, y, text[s:e], C.black, C.gold, bold)
        pos = e
    if pos < len(text):
        cx = screen.text(cx, y, text[pos:], fg, bg, bold)
    return cx


def draw_search_result_row(screen: Screen, x: int, y: int, w: int, primary: str,
                           secondary: Optional[str], query: str, selected: bool,
                           theme: Theme, hits: Optional[HitMap] = None,
                           action: Any = None) -> None:
    """A list row while searching: the entry's full names in both languages.

    The primary name is the active UI language's, the secondary the other
    language's (dim on unselected rows); matched characters get a gold chip
    in either. Mirrors draw_menu_row's selection styling and hit registration.
    """
    if selected:
        screen.fill(x, y, w, 1, " ", C.black, C.cyan)
        screen.text(x + 1, y, "> ", C.black, C.cyan, True)
    else:
        screen.fill(x, y, w, 1, " ", None, None)
    end = x + w
    cx = x + 3
    base_bg = C.cyan if selected else None
    room = end - cx
    if room > 0:
        cx = draw_text_highlighted(screen, cx, y, fit_text(primary, room), query,
                                   C.black if selected else C.white, base_bg,
                                   selected)
    if secondary:
        sx = cx + 2
        room = end - sx
        if room > 0:
            draw_text_highlighted(screen, sx, y, fit_text(secondary, room), query,
                                  C.black if selected else C.dim, base_bg, False)
    if hits is not None and action is not None:
        hits.add(x, y, w, 1, action)


def center_text(screen: Screen, y: int, text: str, fg=None, bg=None, bold=False) -> None:
    tw = text_width(text)
    x = max(0, (screen.w - tw) // 2)
    screen.text(x, y, text, fg, bg, bold)


def draw_loading_overlay(screen: Screen, theme: Theme, done: int,
                         total: int) -> None:
    """Draw a centered progress popup while audio buffers are rendering."""
    w, h = screen.w, screen.h
    if w < 14 or h < 7:
        return
    bw = min(w - 4, 36)
    bh = 5
    x = (w - bw) // 2
    y = (h - bh) // 2
    draw_box(screen, x, y, bw, bh, theme, fg=C.cyan,
             title=theme.t("loading.title"), title_fg=C.yellow)
    ratio = done / total if total else 1.0
    center_text(screen, y + 1, "%d%%" % round(ratio * 100), C.white, None, True)
    barw = max(4, bw - 6)
    nfill = int(barw * ratio)
    fill, empty = ("█", "░") if theme.is_unicode else ("#", "-")
    bx = x + (bw - barw) // 2
    screen.text(bx, y + 3, fill * nfill, C.cyan)
    screen.text(bx + nfill, y + 3, empty * (barw - nfill), C.dim)


def clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))