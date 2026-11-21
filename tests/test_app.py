"""App state machine: menu navigation (keys + mouse), mode toggle, exit, resize."""
from __future__ import annotations

import unittest

from tmb.app import App
from tmb.audio.backends import NullBackend
from tmb.audio.engine import AudioEngine
from tmb.config import Config
from tmb.screens import register_all
from tmb.testing import HeadlessTerminal
from tmb.theme import ASCII_THEME, UNICODE_THEME

try:
    from tests.helpers import HeadlessCase, has_cjk, isolated_config
except ImportError:
    from helpers import HeadlessCase, has_cjk, isolated_config


class MenuKeys(HeadlessCase):
    def test_initial_frame_is_the_chinese_menu(self):
        self.assertEqual(self.app.current_name, "menu")
        self.assertIn(UNICODE_THEME.t("app.title"), self.frame)
        self.assertTrue(has_cjk(self.frame))
        for key in ("menu.freeplay", "menu.rhythm", "menu.toggle_mode", "menu.quit"):
            self.assertIn(UNICODE_THEME.t(key), self.frame)

    def test_number_shortcuts(self):
        for key, name in (("1", "freeplay"), ("2", "rhythm_menu")):
            with self.subTest(key=key):
                self.app.navigate("menu")
                self.press(key)
                self.assertEqual(self.app.current_name, name)

    def test_number_three_toggles_mode(self):
        self.press("3")
        self.assertEqual(self.cfg.mode, "ascii")
        self.press("3")
        self.assertEqual(self.cfg.mode, "unicode")

    def test_number_four_quits(self):
        self.press("4")
        self.assertFalse(self.app.running)

    def test_down_enter_opens_rhythm(self):
        self.press("down")
        self.assertEqual(self.screen.index, 1)
        self.press("enter")
        self.assertEqual(self.app.current_name, "rhythm_menu")

    def test_up_wraps_to_last_item(self):
        self.press("up")
        self.assertEqual(self.screen.index, 3)

    def test_down_wraps_to_first_item(self):
        for _ in range(4):
            self.press("down")
        self.assertEqual(self.screen.index, 0)

    def test_space_activates_selection(self):
        self.press("space")
        self.assertEqual(self.app.current_name, "freeplay")

    def test_key_releases_are_ignored(self):
        self.release("1")
        self.assertEqual(self.app.current_name, "menu")

    def test_unhandled_keys_do_nothing(self):
        self.press("z")
        self.assertEqual(self.app.current_name, "menu")
        self.assertEqual(self.screen.index, 0)


class MenuMouse(HeadlessCase):
    def test_click_freeplay_button(self):
        self.click_label(UNICODE_THEME.t("menu.freeplay"))
        self.assertEqual(self.app.current_name, "freeplay")

    def test_click_rhythm_button(self):
        self.click_label(UNICODE_THEME.t("menu.rhythm"))
        self.assertEqual(self.app.current_name, "rhythm_menu")

    def test_click_toggle_button(self):
        self.click_label(UNICODE_THEME.t("menu.toggle_mode"))
        self.assertEqual(self.cfg.mode, "ascii")
        self.assertFalse(has_cjk(self.frame))

    def test_click_quit_button(self):
        self.click_label(UNICODE_THEME.t("menu.quit"))
        self.assertFalse(self.app.running)

    def test_click_outside_buttons_does_nothing(self):
        self.click(0, 0)
        self.assertEqual(self.app.current_name, "menu")

    def test_click_ascii_button(self):
        self.press("3")
        self.click_label(ASCII_THEME.t("menu.freeplay"))
        self.assertEqual(self.app.current_name, "freeplay")


class ModeToggle(HeadlessCase):
    def test_toggle_switches_language_and_border(self):
        self.assertTrue(has_cjk(self.frame))
        self.assertIn("╭", self.frame)
        self.press("3")
        self.assertFalse(has_cjk(self.frame))
        self.assertIn("Free Play", self.frame)
        self.assertIn("+", self.frame)
        self.assertNotIn("╭", self.frame)
        self.press("3")
        self.assertTrue(has_cjk(self.frame))

    def test_toggle_is_persisted(self):
        self.press("3")
        self.assertEqual(self.read_config()["mode"], "ascii")
        self.assertEqual(Config.load().mode, "ascii")

    def test_theme_object_follows_mode(self):
        self.assertIs(self.app.theme, UNICODE_THEME)
        self.press("3")
        self.assertIs(self.app.theme, ASCII_THEME)


class AsciiStart(HeadlessCase):
    mode = "ascii"

    def test_ascii_mode_starts_english(self):
        self.assertFalse(has_cjk(self.frame))
        self.assertIn("Terminal Music Box", self.frame)
        self.assertIs(self.app.theme, ASCII_THEME)


class ExitChords(HeadlessCase):
    def test_every_exit_chord_quits_from_the_menu(self):
        for key in ("ctrl+q", "ctrl+d", "ctrl+c", "esc"):
            with self.subTest(key=key):
                self.app.running = True
                self.app.navigate("menu")
                self.press(key)
                self.assertFalse(self.app.running)

    def test_no_frame_is_drawn_after_quit(self):
        self.press("ctrl+q")
        count = len(self.term.frames)
        self.steps(3)
        self.assertEqual(len(self.term.frames), count)


class Navigation(HeadlessCase):
    def test_screens_are_cached(self):
        self.app.navigate("freeplay")
        first = self.app.current
        self.app.navigate("menu")
        self.app.navigate("freeplay")
        self.assertIs(self.app.current, first)

    def test_unknown_screen_raises(self):
        with self.assertRaises(KeyError):
            self.app.navigate("nope")

    def test_exit_calls_previous_screen_exit(self):
        self.app.navigate("freeplay")
        self.press("a")
        self.assertGreater(self.engine.active(), 0)
        self.app.navigate("menu")
        self.assertEqual(self.engine.active(), 0)

    def test_resize_event_resizes_buffer_and_frame(self):
        self.assertEqual(self.term.screen.w, 80)
        self.term.resize(100, 30)
        self.step()
        self.assertEqual((self.term.screen.w, self.term.screen.h), (100, 30))
        self.assertEqual(len(self.frame.split("\n")), 30)
        self.assertEqual(self.term.size(), (100, 30))

    def test_resize_to_tiny_does_not_crash(self):
        self.term.resize(10, 4)
        self.step()
        self.assertEqual((self.term.screen.w, self.term.screen.h), (10, 4))


class AllScreensAtManySizes(unittest.TestCase):
    SIZES = [(80, 24), (120, 40), (46, 14), (40, 12), (30, 10), (20, 8), (12, 6), (6, 5), (5, 4)]
    SCREENS = [("menu", {}), ("freeplay", {}), ("song_select", {}),
               ("rhythm_menu", {}),
               ("rhythm_calib", {}), ("rhythm_keys", {}), ("rhythm_game", {"song": "canon"})]

    def setUp(self):
        self.config_file = isolated_config(self)

    def test_every_screen_draws_and_updates_at_every_size(self):
        for w, h in self.SIZES:
            for name, kw in self.SCREENS:
                with self.subTest(size=(w, h), screen=name):
                    term = HeadlessTerminal(w, h)
                    cfg = Config(timbre="bit")
                    app = App(term, AudioEngine(backend=NullBackend(), realtime=False), cfg)
                    register_all(app)
                    app.navigate(name, **kw)
                    for _ in range(3):
                        app.step(0.016)
                    if name == "freeplay":
                        term.key("ctrl+t")
                        app.step(0.016)
                        for _ in range(40):
                            app.step(0.05)
                    if name == "rhythm_game":
                        for _ in range(70):
                            app.step(0.05)
                        term.key("esc")
                        app.step(0.016)
                    self.assertEqual(len(term.last.split("\n")), h)


if __name__ == "__main__":
    unittest.main()