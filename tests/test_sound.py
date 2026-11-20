"""Sound settings screen: volume/length editing, preview, reset, mouse."""
from __future__ import annotations

import unittest

from tmb.audio import synth

try:
    from tests.helpers import HeadlessCase
except ImportError:
    from helpers import HeadlessCase


class SoundSettings(HeadlessCase):
    def setUp(self):
        super().setUp()
        self.app.navigate("sound_settings")
        self.scr = self.app.current
        self.step()

    def test_frame_lists_every_timbre_with_bars(self):
        for tid in synth.ORDER:
            self.assertIn(synth.timbre_name(tid, "zh"), self.frame)
        self.assertIn(self.app.theme.t("sound.hint"), self.frame)

    def test_left_right_adjust_volume_and_persist(self):
        self.press("right")
        self.assertEqual(self.cfg.sound_params("harp"), (1.1, 1.0))
        self.press("left")
        self.press("left")
        self.assertEqual(self.cfg.sound_params("harp"), (0.9, 1.0))
        self.assertEqual(self.read_config()["sound"]["harp"]["vol"], 0.9)

    def test_a_d_adjust_length_and_persist(self):
        self.press("a")
        self.assertEqual(self.cfg.sound_params("harp"), (1.0, 0.75))
        self.assertEqual(self.read_config()["sound"]["harp"]["len"], 0.75)
        # sustained timbres can go beyond the natural length
        self.press("down")
        self.press("down")
        self.press("d")
        self.press("d")
        self.assertEqual(self.cfg.sound_params("flute"), (1.0, 1.5))
        self.assertEqual(self.read_config()["sound"]["flute"]["len"], 1.5)

    def test_ringing_timbre_length_is_capped_at_natural(self):
        for _ in range(10):
            self.press("d")
        self.assertEqual(self.cfg.sound_params("harp")[1], 1.0)

    def test_sustained_timbre_length_grows_to_four(self):
        self.press("down")   # bit
        self.press("down")   # flute
        for _ in range(20):
            self.press("d")
        self.assertEqual(self.cfg.sound_params("flute")[1], 4.0)

    def test_enter_previews_a_voice(self):
        self.press("enter")
        self.assertEqual(self.engine.active(), 1)

    def test_preview_stops_previous_voices(self):
        self.press("down")
        self.press("enter")
        self.press("enter")
        self.assertEqual(self.engine.active(), 1)

    def test_r_resets_the_selected_timbre(self):
        self.press("right")
        self.press("r")
        self.assertEqual(self.cfg.sound_params("harp"), (1.0, 1.0))
        self.assertNotIn("harp", self.cfg.sound)
        self.assertIn(self.app.theme.t("sound.reset_done"), self.frame)

    def test_exit_chords_return_to_the_menu(self):
        for key in ("ctrl+q", "ctrl+d", "ctrl+c", "esc"):
            with self.subTest(key=key):
                self.app.navigate("sound_settings")
                self.press(key)
                self.assertEqual(self.app.current_name, "menu")

    def test_up_down_moves_the_selection(self):
        self.press("down")
        self.assertEqual(self.scr.index, 1)
        self.press("up")
        self.press("up")
        self.assertEqual(self.scr.index, len(synth.ORDER) - 1)

    def test_mouse_click_selects_a_timbre(self):
        x, y = self.find_label(synth.timbre_name("bit", "zh"))
        self.click(x + 1, y)
        self.assertEqual(self.scr.index, 1)


if __name__ == "__main__":
    unittest.main()
