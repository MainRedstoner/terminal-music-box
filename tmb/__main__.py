"""CLI entry point: python -m tmb"""
from __future__ import annotations

import argparse
import sys

from .app import App
from .audio.backends import open_backend
from .audio.engine import AudioEngine
from .config import Config
from .screens import register_all


def make_app(terminal, audio_backend=None, wav=None, config=None):
    backend = open_backend(prefer=audio_backend, wav_path=wav)
    audio = AudioEngine(backend=backend)
    cfg = config if config is not None else Config.load()
    app = App(terminal, audio, cfg)
    register_all(app)
    return app


def demo() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    from .testing import HeadlessTerminal
    from .audio.backends import NullBackend
    t = HeadlessTerminal(80, 24)
    audio = AudioEngine(backend=NullBackend(), realtime=False)
    app = App(t, audio, Config())
    register_all(app)
    app.navigate("menu")

    def frame(label):
        app.step(0.016)
        print("=== %s ===" % label)
        print(t.last)
        print()

    def advance(seconds):
        for _ in range(int(seconds / 0.016)):
            app.step(0.016)

    frame("menu / unicode")
    t.key("3")  # toggle mode; "4" is the quit shortcut
    frame("menu / ascii")
    t.key("1")
    frame("freeplay / ascii")
    t.key("a")
    t.key("s")
    t.key("d")
    frame("freeplay / notes")
    t.key("ctrl+x")
    frame("freeplay / timbre picker")
    t.key("/")
    t.key("b")
    frame("freeplay / timbre search")
    t.key("enter")
    frame("freeplay / timbre picked")
    t.key("ctrl+t")
    frame("freeplay / prenatal on")
    advance(1.0)
    t.key("q")
    frame("freeplay / prenatal kept alive")
    advance(2.5)
    frame("freeplay / prenatal paused (no key for 2s)")
    t.key("esc")
    frame("back to menu")
    t.key("3")  # toggle back to Unicode
    frame("menu / unicode again")
    t.key("1")
    frame("freeplay / unicode")
    t.key("esc")
    frame("back to menu")
    t.key("2")
    frame("rhythm menu / songs focused")
    t.key("tab")
    frame("rhythm menu / functions focused")
    t.key("left")
    t.key("enter")
    frame("rhythm game / countdown")
    advance(3.2)
    frame("rhythm game / play")
    t.key("esc")
    frame("rhythm game / paused")
    t.key("enter")
    frame("rhythm game / resume countdown")
    advance(3.2)
    t.key("esc")
    t.key("down")
    t.key("enter")
    frame("back to rhythm menu")
    t.key("esc")
    frame("back to menu")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="tmb", description="Terminal Music Box")
    p.add_argument("--mode", choices=["unicode", "ascii"], help="UI mode")
    p.add_argument("--audio", choices=["auto", "alsa", "pulse", "winmm", "null", "wav"],
                   default="auto", help="audio backend")
    p.add_argument("--wav", metavar="PATH", help="render audio to a WAV file")
    p.add_argument("--demo", action="store_true", help="run a headless scripted demo")
    p.add_argument("--no-kitty", action="store_true",
                   help="skip kitty keyboard protocol negotiation (testing)")
    args = p.parse_args(argv)

    if args.demo:
        demo()
        return 0

    cfg = Config.load()
    if args.mode:
        cfg.mode = args.mode
    prefer = None if args.audio == "auto" else args.audio
    from .terminal import Terminal
    term = Terminal(no_kitty=args.no_kitty)
    app = make_app(term, prefer, args.wav, cfg)
    if not sys.stdout.isatty():
        sys.stderr.write("tmb needs an interactive terminal (try --demo for headless).\n")
        return 1
    with term:
        try:
            app.run()
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())