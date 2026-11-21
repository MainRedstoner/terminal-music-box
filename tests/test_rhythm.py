"""Rhythm meta screens: song list, latency calibration, key config."""
from __future__ import annotations

import unittest

from tmb import songs
from tmb.config import Config

try:
    from tests.helpers import HeadlessCase
except ImportError:
    from helpers import HeadlessCase


class RhythmMenu(HeadlessCase):
    start_screen = "rhythm_menu"

    def test_shows_a_large_song_box_and_a_small_function_box(self):
        th = self.app.theme
        self.assertEqual(self.screen.focus, 0)
        self.assertEqual(self.screen.song_ids,
                         ["canon", "minuet_g", "turkish_march", "fur_elise"])
        self.assertIn(th.t("rhythm.list"), self.frame)
        self.assertIn(th.t("rhythm.functions"), self.frame)
        self.assertIn(songs.SONGS["canon"].title("zh"), self.frame)
        self.assertIn(songs.SONGS["minuet_g"].title("zh"), self.frame)
        self.assertIn(songs.SONGS["turkish_march"].title("zh"), self.frame)
        self.assertIn(songs.SONGS["fur_elise"].title("zh"), self.frame)
        self.assertIn(th.t("rhythm.calibration"), self.frame)
        self.assertIn(th.t("rhythm.keys"), self.frame)

    def test_enter_starts_the_selected_song(self):
        self.press("enter")
        self.assertEqual(self.app.current_name, "rhythm_game")
        self.assertEqual(self.screen.song_id, "canon")

    def test_down_selects_minuet_and_enter_starts_it(self):
        self.press("down")
        self.assertEqual(self.screen.song_index, 1)
        self.press("enter")
        self.assertEqual(self.app.current_name, "rhythm_game")
        self.assertEqual(self.screen.song_id, "minuet_g")

    def test_mouse_click_on_the_song_starts_it(self):
        self.click_label(songs.SONGS["minuet_g"].title("zh"))
        self.assertEqual(self.app.current_name, "rhythm_game")
        self.assertEqual(self.screen.song_id, "minuet_g")

    def test_down_selects_and_starts_the_turkish_march(self):
        self.press("down")
        self.press("down")
        self.assertEqual(self.screen.song_index, 2)
        self.press("enter")
        self.assertEqual(self.app.current_name, "rhythm_game")
        self.assertEqual(self.screen.song_id, "turkish_march")

    def test_mouse_click_on_the_turkish_march_starts_it(self):
        self.click_label(songs.SONGS["turkish_march"].title("zh"))
        self.assertEqual(self.app.current_name, "rhythm_game")
        self.assertEqual(self.screen.song_id, "turkish_march")

    def test_down_selects_and_starts_fur_elise(self):
        for _ in range(3):
            self.press("down")
        self.assertEqual(self.screen.song_index, 3)
        self.press("enter")
        self.assertEqual(self.app.current_name, "rhythm_game")
        self.assertEqual(self.screen.song_id, "fur_elise")

    def test_mouse_click_on_fur_elise_starts_it(self):
        self.click_label(songs.SONGS["fur_elise"].title("zh"))
        self.assertEqual(self.app.current_name, "rhythm_game")
        self.assertEqual(self.screen.song_id, "fur_elise")

    def test_left_right_and_tab_switch_focus(self):
        self.assertEqual(self.screen.focus, 0)
        self.press("right")
        self.assertEqual(self.screen.focus, 1)
        self.press("left")
        self.assertEqual(self.screen.focus, 0)
        self.press("tab")
        self.assertEqual(self.screen.focus, 1)
        self.press("tab")
        self.assertEqual(self.screen.focus, 0)

    def test_enter_opens_the_first_function_when_focused(self):
        self.press("tab")
        self.press("enter")
        self.assertEqual(self.app.current_name, "rhythm_calib")

    def test_down_selects_and_opens_key_config(self):
        self.press("tab")
        self.press("down")
        self.assertEqual(self.screen.function_index, 1)
        self.press("enter")
        self.assertEqual(self.app.current_name, "rhythm_keys")

    def test_mouse_click_on_calibration(self):
        self.click_label(self.app.theme.t("rhythm.calibration"))
        self.assertEqual(self.app.current_name, "rhythm_calib")

    def test_escape_returns_to_the_main_menu(self):
        self.press("esc")
        self.assertEqual(self.app.current_name, "menu")


class Calibration(HeadlessCase):
    start_screen = "rhythm_calib"

    def tap_on_beat(self, count, offset=0.0):
        c = self.screen
        for k in range(1, count + 1):
            self.run_until(lambda: c.clock >= k * c.PERIOD + offset, dt=0.005)
            self.press("j", dt=0.005)

    def test_metronome_keeps_playing(self):
        self.advance(1.3)
        self.assertGreaterEqual(self.engine.active(), 3)
        self.assertGreater(self.screen.clock, 1.2)

    def test_twelve_taps_on_the_beat_calibrate_near_zero(self):
        self.tap_on_beat(12)
        c = self.screen
        self.assertTrue(c.done)
        self.assertEqual(len(c.offsets), 12)
        self.assertLessEqual(abs(self.cfg.latency_ms), 10)
        self.assertEqual(self.read_config()["latency_ms"], self.cfg.latency_ms)
        self.assertEqual(c.status, self.app.theme.t("rhythm.calib_done", ms=self.cfg.latency_ms))

    def test_late_taps_measure_a_positive_offset(self):
        self.tap_on_beat(12, offset=0.1)
        self.assertTrue(self.screen.done)
        self.assertGreaterEqual(self.cfg.latency_ms, 90)
        self.assertLessEqual(self.cfg.latency_ms, 110)

    def test_partial_taps_do_not_change_the_config(self):
        self.cfg.latency_ms = 7
        self.tap_on_beat(5)
        self.assertFalse(self.screen.done)
        self.assertEqual(self.cfg.latency_ms, 7)
        self.assertEqual(len(self.screen.offsets), 5)

    def test_taps_after_completion_are_ignored(self):
        self.tap_on_beat(12)
        latency = self.cfg.latency_ms
        self.press("j")
        self.press("j")
        self.assertEqual(len(self.screen.offsets), 12)
        self.assertEqual(self.cfg.latency_ms, latency)

    def test_r_resets_the_calibration(self):
        self.tap_on_beat(12)
        self.press("r")
        c = self.screen
        self.assertEqual(self.cfg.latency_ms, 0)
        self.assertEqual(self.read_config()["latency_ms"], 0)
        self.assertEqual(c.offsets, [])
        self.assertFalse(c.done)
        self.assertLess(c.clock, c.PERIOD)
        self.assertEqual(c.status, self.app.theme.t("rhythm.calib_reset"))

    def test_mouse_reset_button(self):
        self.tap_on_beat(12)
        x, y, w, h, _action = self.screen.hits.regions[0]
        self.click(x + w // 2, y + h // 2)
        self.assertEqual(self.cfg.latency_ms, 0)
        self.assertFalse(self.screen.done)

    def test_mouse_back_button(self):
        x, y, w, h, _action = self.screen.hits.regions[1]
        self.click(x + w // 2, y + h // 2)
        self.assertEqual(self.app.current_name, "rhythm_menu")

    def test_escape_returns_to_the_rhythm_menu(self):
        self.press("esc")
        self.assertEqual(self.app.current_name, "rhythm_menu")

    def test_calibration_shows_the_sample_counter(self):
        self.tap_on_beat(3)
        self.assertIn(self.app.theme.t("rhythm.tap_count", n=3, total=12), self.frame)


class KeyConfig(HeadlessCase):
    start_screen = "rhythm_keys"

    def test_starts_from_the_saved_keys(self):
        self.assertEqual(self.screen.keys, self.cfg.rhythm_keys)
        self.assertEqual(self.screen.index, 0)
        self.assertIn(self.app.theme.t("rhythm.keys"), self.frame)

    def test_binding_a_new_letter_saves_it(self):
        self.press("z")
        self.assertEqual(self.screen.keys[0], "z")
        self.assertEqual(self.cfg.rhythm_keys[0], "z")
        self.assertEqual(self.read_config()["rhythm_keys"], self.cfg.rhythm_keys)
        self.assertEqual(Config.load().rhythm_keys, self.cfg.rhythm_keys)
        self.assertTrue(self.screen.status.startswith(self.app.theme.t("rhythm.key_saved")))

    def test_binding_an_existing_letter_swaps_lanes(self):
        self.press("j")
        self.assertEqual(self.screen.keys, ["j", "s", "d", "a", "k", "l"])
        self.assertEqual(self.cfg.rhythm_keys, ["j", "s", "d", "a", "k", "l"])
        self.assertEqual(len(set(self.screen.keys)), 6)

    def test_swapping_back_restores_the_original(self):
        self.press("j")
        self.press("down")
        self.press("down")
        self.press("down")
        self.press("j")
        self.assertEqual(self.screen.keys, ["a", "s", "d", "j", "k", "l"])

    def test_navigation_wraps_both_ways(self):
        self.press("up")
        self.assertEqual(self.screen.index, 5)
        self.press("down")
        self.assertEqual(self.screen.index, 0)
        self.press("right")
        self.assertEqual(self.screen.index, 1)
        self.press("left")
        self.assertEqual(self.screen.index, 0)

    def test_binding_a_second_lane(self):
        self.press("down")
        self.press("q")
        self.assertEqual(self.screen.keys, ["a", "q", "d", "j", "k", "l"])

    def test_ctrl_chords_and_digits_do_not_bind(self):
        before = list(self.screen.keys)
        self.press("ctrl+z")
        self.press("1")
        self.press("enter")
        self.assertEqual(self.screen.keys, before)

    def test_mouse_click_selects_a_lane(self):
        x, y, w, h, _action = self.screen.hits.regions[2]
        self.click(x + w // 2, y)
        self.assertEqual(self.screen.index, 2)
        self.press("q")
        self.assertEqual(self.screen.keys[2], "q")

    def test_escape_returns_to_the_rhythm_menu(self):
        self.press("esc")
        self.assertEqual(self.app.current_name, "rhythm_menu")

    def test_rebinding_survives_a_new_game(self):
        self.press("z")
        self.press("esc")
        self.press("enter")
        self.assertEqual(self.app.current_name, "rhythm_game")
        self.assertEqual(self.screen.lane_keys[0], "z")


if __name__ == "__main__":
    unittest.main()