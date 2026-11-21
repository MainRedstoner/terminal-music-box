"""Application: state machine + main loop tying terminal, audio and screens."""
from __future__ import annotations

import time
from typing import Callable, Dict, Optional

from .config import Config
from .events import KeyEvent, MouseEvent, ResizeEvent
from .theme import theme_for
from .ui import draw_loading_overlay
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
        # perf_counter, not monotonic: on Windows monotonic() is GetTickCount64
        # with a 15.6 ms resolution, which quantises every frame delta.
        self._last = time.perf_counter()

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

    def release_events(self) -> bool:
        """True when the terminal reports key releases (kitty protocol / Windows)."""
        return bool(getattr(self.terminal, "release_events", False))

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

    def step(self, dt: Optional[float] = None) -> None:
        """Poll input, advance the simulation, then handle the input.

        Order matters for timing accuracy: the frame clock is advanced *before*
        events are dispatched, so a key press is judged against the time it
        arrived instead of the previous frame (measured ~25 ms stale on
        Windows). Input is polled first so the frame delta covers the wait; a
        caller (tests, scripts) can still pass an explicit dt.
        """
        if not self.running:
            return
        events = self.terminal.poll(0.016)
        if dt is None:
            now = time.perf_counter()
            dt = min(0.1, now - self._last)
            self._last = now
        if self.current is not None:
            self.current.update(dt)
        for e in events:
            self._dispatch(e)
        if not self.running:
            return
        scr = self.terminal.screen
        scr.clear()
        if self.current is not None:
            self.current.draw(scr)
        self._draw_loading(scr)
        self.terminal.render(scr)

    def _draw_loading(self, scr) -> None:
        # Offline/headless runs have no playback thread to stall, and their
        # frames are consumed by tests or --demo, so no popup is needed.
        if not self.audio.realtime:
            return
        active, done, total = self.audio.preload_status()
        if active:
            draw_loading_overlay(scr, self.theme, done, total)

    def run(self) -> None:
        self.audio.start()
        self._preload_timbre()
        self.navigate("menu")
        self._last = time.perf_counter()
        try:
            while self.running:
                self.step()
        finally:
            self._diag("run loop exited")
            self.audio.stop()
            self._diag("audio stopped")

    def _diag(self, msg: str) -> None:
        """Append to the TMB_LOG_INPUT file when input diagnostics are on."""
        import os
        path = os.environ.get("TMB_LOG_INPUT")
        if path:
            try:
                with open("%s.app" % path, "a", encoding="utf-8") as f:
                    f.write(msg + "\n")
            except OSError:
                pass