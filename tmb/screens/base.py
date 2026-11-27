"""Screen base class + a reusable scrolling, searchable list screen."""
from __future__ import annotations

from typing import Any, Callable, List, Optional

from ..ansi import Screen as Buffer, C
from ..events import (KeyEvent, MouseEvent, is_exit, UP, DOWN, ENTER, SPACE,
                      BACKSPACE, HOME, END, PGUP, PGDN)
from ..ui import (HitMap, draw_box, draw_menu_row, center_text,
                  draw_search_field, draw_search_result_row, matches)

NAV_KEYS = (UP, DOWN, HOME, END, PGUP, PGDN, ENTER)


class Screen:
    """Base screen. Subclasses override handle_key/update/draw/on_action."""

    def __init__(self, app):
        self.app = app
        self.hits = HitMap()

    @property
    def theme(self):
        return self.app.theme

    @property
    def config(self):
        return self.app.config

    @property
    def audio(self):
        return self.app.audio

    def enter(self, **kw) -> None:
        pass

    def exit(self) -> None:
        pass

    def handle_key(self, ev: KeyEvent) -> None:
        pass

    def handle_mouse(self, ev: MouseEvent) -> None:
        if ev.kind == "press":
            action = self.hits.hit(ev.x, ev.y)
            if action is not None:
                self.on_action(action)

    def on_action(self, action: Any) -> None:
        if callable(action):
            action()

    def update(self, dt: float) -> None:
        pass

    def draw(self, scr: Buffer) -> None:
        self.hits.clear()


class ListScreen(Screen):
    """A titled, scrolling, keyboard+mouse list with live '/' search.

    Each item can carry extra search aliases beyond its label (both language
    names, ids…), so a query finds entries in either language regardless of
    the active UI. While the field is open, printable keys type into the
    query and the list shows only matches; self.index points into the
    *visible* list, and actions stay attached to their original items.
    """

    def __init__(self, app):
        super().__init__(app)
        self.title = ""
        self.items: List[str] = []
        self.actions: List[Callable] = []
        self.keywords: List[List[str]] = []
        self.visible: List[int] = []
        self.sublabels: Optional[List[str]] = None  # other-language name per item
        self.index = 0
        self.scroll = 0
        self.footer = ""
        self.back_target = "menu"
        self.searching = False
        self.query = ""

    def set_items(self, items: List[str], actions: List[Callable],
                  keywords: Optional[List[List[str]]] = None,
                  sublabels: Optional[List[str]] = None) -> None:
        self.items = list(items)
        self.actions = list(actions)
        if keywords is not None:
            self.keywords = [list(aliases) for aliases in keywords]
        else:
            self.keywords = [[label] for label in self.items]
        self.sublabels = (list(sublabels)
                          if sublabels is not None and len(sublabels) == len(items)
                          else None)
        # A picker re-entered from scratch starts with a clean field.
        self.searching = False
        self.query = ""
        self.refresh()

    def refresh(self) -> None:
        """Recompute the visible (filtered) rows from the current query."""
        q = self.query.casefold()
        if q:
            self.visible = [i for i, aliases in enumerate(self.keywords)
                            if matches(q, aliases)]
        else:
            self.visible = list(range(len(self.items)))
        self.index = min(self.index, max(0, len(self.visible) - 1))

    def handle_key(self, ev: KeyEvent) -> None:
        if not ev.pressed:
            return
        k = ev.key
        if self.searching:
            if is_exit(k):
                # Esc cancels the search itself; a second Esc leaves.
                self.searching = False
                self.query = ""
                self.refresh()
                return
            if k == BACKSPACE:
                self.query = self.query[:-1]
                self.refresh()
                return
            if k == SPACE:
                self.query += " "  # typing, not activating
                self.refresh()
                self.index = 0
                return
            elif len(k) == 1:
                self.query += k
                self.refresh()
                self.index = 0  # each typed char restarts at the first match
                return
            elif k not in NAV_KEYS:
                return  # arrows/chords that are not navigation are ignored
        elif k == "/":
            self.searching = True
            return
        elif is_exit(k):
            self.app.navigate(self.back_target)
            return
        n = len(self.visible)
        if k == UP:
            self.index = max(0, self.index - 1)
        elif k == DOWN:
            self.index = min(n - 1, self.index + 1)
        elif k == HOME:
            self.index = 0
        elif k == END:
            self.index = max(0, n - 1)
        elif k == PGUP:
            self.index = max(0, self.index - 5)
        elif k == PGDN:
            self.index = min(n - 1, self.index + 5)
        elif k == ENTER or k == SPACE:
            self._activate()

    def _activate(self) -> None:
        if 0 <= self.index < len(self.visible):
            self.on_action(self.actions[self.visible[self.index]])

    def on_action(self, action: Any) -> None:
        if callable(action):
            action()

    def _select(self, vi: int) -> None:
        self.index = vi
        self._activate()

    def draw(self, scr: Buffer) -> None:
        self.hits.clear()
        th = self.theme
        w, h = scr.w, scr.h
        bw = min(w - 4, 60)
        bx = (w - bw) // 2
        top = 2
        field = 1 if self.searching else 0
        rows = h - top - 4 - field
        draw_box(scr, bx, top, bw, h - top - 2, th, fg=C.cyan, title=self.title, title_fg=C.yellow)
        y = top + 1
        if self.searching:
            fw = draw_search_field(scr, bx + 1, y, bw - 2, self.query, th)
            if len(self.visible) != len(self.items) and fw + 7 <= bw - 2:
                scr.text(bx + 1 + fw + 1, y, "%d/%d" % (len(self.visible),
                                                        len(self.items)), C.dim)
            y += 1
        n = len(self.visible)
        if self.index < self.scroll:
            self.scroll = self.index
        if self.index >= self.scroll + rows:
            self.scroll = self.index - rows + 1
        self.scroll = max(0, min(self.scroll, max(0, n - rows)))
        for r in range(rows):
            vi = self.scroll + r
            if vi >= n:
                if self.searching and r == 0:
                    scr.text(bx + 1, y + r, th.t("search.no_match"), C.dim)
                break
            item = self.visible[vi]
            if self.searching:
                draw_search_result_row(
                    scr, bx + 1, y + r, bw - 2, self.items[item],
                    self.sublabels[item] if self.sublabels else None,
                    self.query, vi == self.index, th,
                    hits=self.hits, action=(lambda idx=vi: self._select(idx)))
            else:
                draw_menu_row(scr, bx + 1, y + r, bw - 2, self.items[item],
                              vi == self.index, th,
                              hits=self.hits, action=(lambda idx=vi: self._select(idx)))
        if self.footer:
            center_text(scr, h - 2, self.footer, C.dim)