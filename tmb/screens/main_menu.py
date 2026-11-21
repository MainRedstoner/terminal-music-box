"""Main menu: Free Play, Rhythm Game, Unicode/ASCII toggle, Quit."""
from __future__ import annotations

from ..ansi import C
from ..events import KeyEvent, is_exit, UP, DOWN, ENTER
from ..ui import draw_button, center_text
from .base import Screen


class MainMenu(Screen):
    def enter(self, **kw) -> None:
        self.index = 0

    def _items(self):
        th = self.theme
        return [
            (th.t("menu.freeplay"), lambda: self.app.navigate("freeplay")),
            (th.t("menu.rhythm"), lambda: self.app.navigate("rhythm_list")),
            (th.t("menu.toggle_mode"), self.app.toggle_mode),
            (th.t("menu.quit"), self.app.quit),
        ]

    def handle_key(self, ev: KeyEvent) -> None:
        if not ev.pressed:
            return
        k = ev.key
        items = self._items()
        if is_exit(k):
            self.app.quit()
        elif k == UP:
            self.index = (self.index - 1) % len(items)
        elif k == DOWN:
            self.index = (self.index + 1) % len(items)
        elif k == ENTER or k == "space":
            items[self.index][1]()
        elif k in ("1", "2", "3", "4"):
            i = int(k) - 1
            if i < len(items):
                self.index = i
                items[i][1]()

    def on_action(self, action) -> None:
        if callable(action):
            action()

    def draw(self, scr) -> None:
        self.hits.clear()
        th = self.theme
        w, h = scr.w, scr.h
        center_text(scr, 2, th.t("app.title"), C.yellow, None, True)
        center_text(scr, 3, "♪ ♫ ♪", C.cyan)
        mode = th.t("mode.unicode") if th.is_unicode else th.t("mode.ascii")
        center_text(scr, 4, mode, C.dim)
        items = self._items()
        bw = min(40, w - 6)
        bh = 3 if h >= 14 else 1
        gap = 1
        total = len(items) * bh + (len(items) - 1) * gap
        y0 = max(6, (h - total) // 2)
        x0 = (w - bw) // 2
        for i, (label, action) in enumerate(items):
            y = y0 + i * (bh + gap)
            draw_button(scr, x0, y, bw, bh, label, th, selected=(i == self.index),
                        hits=self.hits, action=action)
        center_text(scr, h - 2, th.t("menu.hint"), C.dim)