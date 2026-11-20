"""Shared fixtures: isolated config file, deterministic headless app, frame search."""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

from tmb.ansi import CONT
from tmb.app import App
from tmb.audio.backends import NullBackend
from tmb.audio.engine import AudioEngine
from tmb.config import Config
from tmb.screens import register_all
from tmb.testing import HeadlessTerminal


def isolated_config(case) -> str:
    tmp = tempfile.TemporaryDirectory()
    case.addCleanup(tmp.cleanup)
    path = os.path.join(tmp.name, "config.json")
    patcher = mock.patch("tmb.config.config_path", return_value=path)
    patcher.start()
    case.addCleanup(patcher.stop)
    return path


def has_cjk(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


class HeadlessCase(unittest.TestCase):
    """App driven by app.step(dt); audio is never started so voices accumulate."""

    width = 80
    height = 24
    mode = "unicode"
    timbre = "harp"
    start_screen = "menu"

    def setUp(self):
        self.config_file = isolated_config(self)
        self.cfg = Config(mode=self.mode, timbre=self.timbre)
        self.term = HeadlessTerminal(self.width, self.height)
        self.engine = AudioEngine(backend=NullBackend(), realtime=False)
        self.app = App(self.term, self.engine, self.cfg)
        register_all(self.app)
        self.app.navigate(self.start_screen)
        self.app.step(0.016)

    @property
    def screen(self):
        return self.app.current

    @property
    def frame(self) -> str:
        return self.term.last

    def step(self, dt=0.016):
        self.app.step(dt)

    def steps(self, n, dt=0.016):
        for _ in range(n):
            self.app.step(dt)

    def advance(self, seconds, dt=0.01):
        self.steps(max(1, int(round(seconds / dt))), dt)

    def press(self, key, dt=0.016):
        self.term.key(key)
        self.app.step(dt)

    def release(self, key, dt=0.016):
        self.term.key(key, pressed=False)
        self.app.step(dt)

    def click(self, x, y, dt=0.016, kind="press"):
        self.term.mouse(x, y, 0, kind)
        self.app.step(dt)

    def run_until(self, pred, dt=0.005, max_steps=200000):
        for _ in range(max_steps):
            if pred():
                return
            self.app.step(dt)
        self.fail("run_until: condition never became true")

    def find_label(self, label):
        for y, row in enumerate(self.term.screen.cells):
            vis = [(x, c[0]) for x, c in enumerate(row) if c[0] and c[0] != CONT]
            for i in range(len(vis) - len(label) + 1):
                if all(vis[i + j][1] == label[j] for j in range(len(label))):
                    return vis[i][0], y
        self.fail("label %r not found in frame:\n%s" % (label, self.frame))

    def click_label(self, label, dt=0.016):
        x, y = self.find_label(label)
        self.click(x, y, dt)

    def read_config(self):
        import json
        with open(self.config_file, "r", encoding="utf-8") as f:
            return json.load(f)