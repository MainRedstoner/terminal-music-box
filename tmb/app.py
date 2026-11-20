"""Application: state machine + main loop tying terminal, audio and screens."""
from __future__ import annotations

import time
from typing import Callable, Dict, Optional

from .config import Config
from .events import KeyEvent, MouseEvent, ResizeEvent
from .theme import theme_for
from .audio.engine import AudioEngine


class App:
    def __init__(self, terminal, audio: AudioEngine, config: Optional[Config] = None):
        self.terminal = terminal
        self.audio = audio
        self.config = config if config is not None else Config.load()
        self.theme = theme_for(self.config.mode)
        self._factories: Dict[str, Callable] = {}
        self._screens: Dict[str, object] = {}
        self.current = None
        self.current_name = ""
        self.running = True
        self._last = time.monotonic()

    def register(self, name: str, factory: Callable) -> None:
        self._factories[name] = factory

    def navigate(self, name: str, **kw) -> None:
        if self.current is not None:
            self.current.exit()
        scr = self._screens.get(name)
        if scr is None:
            factory = self._factories.get(name)
            if factory is None:
                raise KeyError("unknown screen: %s" % name)
            scr = factory(self)
            self._screens[name] = scr
        self.current = scr
        self.current_name = name
        scr.enter(**kw)

    def toggle_mode(self) -> None:
        self.config.mode = "ascii" if self.config.mode == "unicode" else "unicode"
        self.theme = theme_for(self.config.mode)
        self.config.save()

    def quit(self) -> None:
        self.running = False

    def _preload_timbre(self) -> None:
        # Local import: keeps app import-light and avoids screen-module cycles.
        from .screens.freeplay import PRELOAD_MIDIS
        self.audio.preload(self.config.timbre, PRELOAD_MIDIS)

    def _dispatch(self, e) -> None:
        if isinstance(e, ResizeEvent):
            self.terminal.screen.resize(e.w, e.h)
        elif isinstance(e, KeyEvent):
            if self.current is not None:
                self.current.handle_key(e)
        elif isinstance(e, MouseEvent):
            if self.current is not None:
                self.current.handle_mouse(e)

    def step(self, dt: float) -> None:
        for e in self.terminal.poll(0.016):
            self._dispatch(e)
        if not self.running:
            return
        if self.current is not None:
            self.current.update(dt)
        scr = self.terminal.screen
        scr.clear()
        if self.current is not None:
            self.current.draw(scr)
        self.terminal.render(scr)

    def run(self) -> None:
        self.audio.start()
        self._preload_timbre()
        self.navigate("menu")
        self._last = time.monotonic()
        try:
            while self.running:
                now = time.monotonic()
                dt = min(0.1, now - self._last)
                self._last = now
                self.step(dt)
        finally:
            self.audio.stop()