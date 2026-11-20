"""Headless terminal for tests: inject events, capture rendered text frames."""
from __future__ import annotations

from collections import deque
from typing import List

from .ansi import Screen
from .events import KeyEvent, MouseEvent, ResizeEvent


class HeadlessTerminal:
    def __init__(self, w: int = 80, h: int = 24):
        self.screen = Screen(w, h)
        self._queue = deque()
        self.frames: List[str] = []
        self.last = ""

    def setup(self) -> None:
        pass

    def teardown(self) -> None:
        pass

    def size(self):
        return self.screen.w, self.screen.h

    def write(self, s: str) -> None:
        pass

    def flush(self) -> None:
        pass

    def poll(self, timeout: float):
        out = list(self._queue)
        self._queue.clear()
        return out

    def render(self, scr: Screen) -> None:
        self.last = scr.plain_text()
        self.frames.append(self.last)

    def send(self, *events) -> None:
        self._queue.extend(events)

    def key(self, key: str, pressed: bool = True) -> None:
        self._queue.append(KeyEvent(key, pressed))

    def mouse(self, x: int, y: int, button: int = 0, kind: str = "press") -> None:
        self._queue.append(MouseEvent(x, y, button, kind))

    def resize(self, w: int, h: int) -> None:
        self._queue.append(ResizeEvent(w, h))