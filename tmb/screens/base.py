"""Screen base class + a reusable scrolling list screen."""
from __future__ import annotations

from typing import Any, Callable, List, Optional

from ..ansi import Screen as Buffer, C
from ..events import KeyEvent, MouseEvent, is_exit, UP, DOWN, ENTER, HOME, END, PGUP, PGDN
from ..ui import HitMap, draw_box, draw_menu_row, center_text


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
    """A titled, scrolling, keyboard+mouse list. Actions are callables."""

    def __init__(self, app):
        super().__init__(app)
        self.title = ""
        self.items: List[str] = []
        self.actions: List[Callable] = []
        self.index = 0
        self.scroll = 0
        self.footer = ""
        self.back_target = "menu"

    def set_items(self, items: List[str], actions: List[Callable]) -> None:
        self.items = items
        self.actions = actions
        self.index = min(self.index, max(0, len(items) - 1))

    def handle_key(self, ev: KeyEvent) -> None:
        if not ev.pressed:
            return
        k = ev.key
        if is_exit(k):
            self.app.navigate(self.back_target)
        elif k == UP:
            self.index = max(0, self.index - 1)
        elif k == DOWN:
            self.index = min(len(self.items) - 1, self.index + 1)
        elif k == HOME:
            self.index = 0
        elif k == END:
            self.index = max(0, len(self.items) - 1)
        elif k == PGUP:
            self.index = max(0, self.index - 5)
        elif k == PGDN:
            self.index = min(len(self.items) - 1, self.index + 5)
        elif k == ENTER or k == "space":
            self.on_action(self.actions[self.index])

    def on_action(self, action: Any) -> None:
        if callable(action):
            action()

    def _select(self, i: int) -> None:
        self.index = i
        if 0 <= i < len(self.actions):
            self.on_action(self.actions[i])

    def draw(self, scr: Buffer) -> None:
        self.hits.clear()
        th = self.theme
        w, h = scr.w, scr.h
        bw = min(w - 4, 60)
        bx = (w - bw) // 2
        top = 2
        rows = h - top - 4
        draw_box(scr, bx, top, bw, h - top - 2, th, fg=C.cyan, title=self.title, title_fg=C.yellow)
        if self.index < self.scroll:
            self.scroll = self.index
        if self.index >= self.scroll + rows:
            self.scroll = self.index - rows + 1
        self.scroll = max(0, min(self.scroll, max(0, len(self.items) - rows)))
        for r in range(rows):
            i = self.scroll + r
            if i >= len(self.items):
                break
            y = top + 1 + r
            draw_menu_row(scr, bx + 1, y, bw - 2, self.items[i], i == self.index, th,
                          hits=self.hits, action=(lambda idx=i: self._select(idx)))
        if self.footer:
            center_text(scr, h - 2, self.footer, C.dim)