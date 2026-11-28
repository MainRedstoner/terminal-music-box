"""Rhythm meta screens: song list, latency calibration, key config."""
from __future__ import annotations

import unittest
from unittest import mock

from tmb import songs
from tmb.ansi import C
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


class RhythmMenuSearch(HeadlessCase):
    start_screen = "rhythm_menu"

    def test_slash_opens_search_and_a_chinese_query_filters(self):
        s = self.screen
        self.press("/")
        self.assertTrue(s.searching)
        self.assertEqual(s.focus, 0)  # search always targets the song list
        self.press("卡")
        self.press("农")
        self.assertEqual(s.song_ids, ["canon"])
        self.assertIn(songs.SONGS["canon"].title("zh"), self.frame)
        self.assertNotIn(songs.SONGS["minuet_g"].title("zh"), self.frame)
        self.press("enter")
        self.assertEqual(self.app.current_name, "rhythm_game")
        self.assertEqual(self.screen.song_id, "canon")

    def test_search_matches_the_english_title_and_keeps_group_headers(self):
        s = self.screen
        self.press("/")
        for ch in "elise":
            self.press(ch)
        self.assertEqual(s.song_ids, ["fur_elise"])
        # the builtin header stays above the lone match; the empty external
        # group (header + hint) is filtered away entirely
        th = self.app.theme
        self.assertIn(th.t("rhythm.builtin"), self.frame)
        self.assertNotIn(th.t("rhythm.external"), self.frame)
        self.press("esc")
        self.assertFalse(s.searching)
        self.assertEqual(s.song_ids,
                         ["canon", "minuet_g", "turkish_march", "fur_elise"])

    def test_search_finds_an_external_pack_by_its_chinese_title(self):
        try:
            from tests.test_external import build_pack
        except ImportError:
            from test_external import build_pack
        build_pack(self.external_dir, name="star.tmbp", sid="star_light",
                   manifest={"title_zh": "星光", "title_en": "Starlight"})
        self.app.navigate("menu")  # re-enter so the menu rescans the packs
        self.app.navigate("rhythm_menu")
        self.step()
        s = self.screen
        self.assertEqual(s.song_total, 5)
        self.press("/")
        self.press("星")
        self.assertEqual(s.song_ids, ["star_light"])
        self.assertIn(self.app.theme.t("rhythm.external"), self.frame)

    def test_no_match_shows_the_hint_and_enter_starts_nothing(self):
        self.press("/")
        for ch in "zzz":
            self.press(ch)
        self.assertEqual(self.screen.song_rows, [])
        self.assertIn(self.app.theme.t("search.no_match"), self.frame)
        self.press("enter")
        self.assertEqual(self.app.current_name, "rhythm_menu")

    def test_typing_ignores_focus_and_tab_keys(self):
        s = self.screen
        self.press("/")
        self.press("tab")
        self.press("left")
        self.assertEqual(s.focus, 0)
        self.assertTrue(s.searching)

    def test_search_rows_show_both_language_titles(self):
        self.press("/")
        for ch in "elise":
            self.press(ch)
        self.assertIn("致爱丽丝", self.frame)
        self.assertIn("Für Elise", self.frame)

    def test_matched_characters_get_a_gold_chip(self):
        self.press("/")
        for ch in "elise":
            self.press(ch)
        x, y = self.find_label("Für Elise")
        row = self.term.screen.cells[y]
        # exactly the five "elise" characters are chipped; the Chinese title,
        # which the query does not match, is not
        gold = [cell for cell in row if cell[2] == C.gold]
        self.assertEqual(len(gold), 5)


class Calibration(HeadlessCase):
    start_screen = "rhythm_calib"

    def tap_on_beat(self, count, offset=0.0):
        c = self.screen
        for k in range(1, count + 1):
            self.run_until(lambda: c.clock >= k * c.PERIOD + offset, dt=0.005)
            # A real tap is down+up: press() alone models holding the key,
            # which the calibration screen must (and now does) treat as one
            # tap plus auto-repeat, not twelve taps.
            self.tap("j", dt=0.005)

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


class RhythmPreloadGate(HeadlessCase):
    """A song opens only after its audio buffers are ready."""

    start_screen = "rhythm_menu"

    def setUp(self):
        super().setUp()
        self.engine.realtime = True
        self.engine.preload = mock.Mock()
        self.engine.is_preloaded = mock.Mock(return_value=False)

    def test_enter_waits_for_the_song_to_preload(self):
        self.press("enter")
        self.assertEqual(self.app.current_name, "rhythm_menu")
        self.engine.preload.assert_called_once()
        self.assertIsNotNone(self.screen._pending_song)

    def test_enters_automatically_when_the_preload_finishes(self):
        self.press("enter")
        self.assertEqual(self.app.current_name, "rhythm_menu")
        self.engine.is_preloaded.return_value = True
        self.step()
        self.assertEqual(self.app.current_name, "rhythm_game")
        self.assertEqual(self.screen.song_id, "canon")




try:
    from tests.test_external import ThreadedCase, build_pack
except ImportError:
    from test_external import ThreadedCase, build_pack


class CalibrationHolds(HeadlessCase):
    """R1: one physical hold is one tap plus auto-repeat, not a bucket of
    samples; the garbage median must never reach config.latency_ms."""

    start_screen = "rhythm_calib"

    def _hold(self, presses=14, dt=0.033):
        for _ in range(presses):
            self.term.key("j")          # key-down only, no release
            self.app.step(dt)

    def test_a_held_key_registers_one_tap_when_releases_exist(self):
        self.run_until(lambda: self.screen.clock >= 0.3, dt=0.005)
        self._hold()
        self.assertEqual(len(self.screen.offsets), 1)
        self.assertFalse(self.screen.done)

    def test_legacy_terminals_debounce_a_hold(self):
        self.run_until(lambda: self.screen.clock >= 0.3, dt=0.005)
        with mock.patch.object(self.app, "release_events", return_value=False):
            self._hold()
        # No key-up events: every repeat lands inside the debounce window of
        # the last registered tap, so one hold yields a couple of samples at
        # most - not twelve, and the config is not overwritten.
        self.assertLessEqual(len(self.screen.offsets), 3)
        self.assertFalse(self.screen.done)
        self.assertEqual(self.cfg.latency_ms, 0)

    def test_a_realistic_long_hold_registers_one_tap(self):
        # Windows-style auto-repeat: no events during the OS repeat delay
        # (~0.25 s), then one repeat every 40 ms. The debounce window must
        # cover that initial delay, or phantom taps survive it and pollute
        # the persisted latency.
        self.run_until(lambda: self.screen.clock >= 0.3, dt=0.005)
        self.term.key("j")                  # the press
        self.app.step(0.005)
        self.app.step(0.25)                 # repeat delay: silence
        for _ in range(24):
            self.term.key("j")              # repeats every 40 ms
            self.app.step(0.04)
        self.assertEqual(len(self.screen.offsets), 1)
        self.assertFalse(self.screen.done)
        self.assertEqual(self.cfg.latency_ms, 0)


class PendingPackRace(ThreadedCase):
    """R2: a pack decoding from an earlier Enter must not win after the user
    picks a built-in song."""

    start_screen = "menu"

    def setUp(self):
        super().setUp()
        build_pack(self.external_dir, name="slow.tmbp", sid="slow")
        self.app.external.refresh()
        self.engine.realtime = True
        self.engine.is_preloaded = mock.Mock(return_value=False)
        self.engine.preload = mock.Mock()
        self.app.navigate("rhythm_menu")
        self.app.step(0.016)

    def test_a_builtin_choice_cancels_the_pending_pack(self):
        for _ in range(4):
            self.press("down")
        self.press("enter")             # pack pending, its decode starts
        self.assertEqual(self.screen._pending_pack.id, "slow")
        self.press("up")
        self.press("enter")             # fur_elise: cold built-in song
        self.assertIsNone(self.screen._pending_pack)
        self.assertEqual(self.screen._pending_song, "fur_elise")
        self.step_until(lambda: not self.app.external.status()[0], timeout=10)
        self.steps(10)
        # The decode finished, but the pack is no longer the user's choice:
        # the menu must not navigate into it.
        self.assertEqual(self.app.current_name, "rhythm_menu")
        self.assertEqual(self.screen._pending_song, "fur_elise")


class QueuedNotice(HeadlessCase):
    """The queued-decode notice belongs to the pack choice: picking a
    built-in song must clear it instead of leaving a stale red hint."""

    start_screen = "rhythm_menu"

    def setUp(self):
        super().setUp()
        self.engine.realtime = True
        self.engine.is_preloaded = mock.Mock(return_value=False)
        self.engine.preload = mock.Mock()

    def test_a_builtin_pick_clears_the_queued_notice(self):
        self.screen.notice = self.app.theme.t("rhythm.decode_queued")
        self.screen.notice_fg = C.cyan
        self.press("enter")             # first built-in song: cold, starts a preload
        self.step()
        self.assertEqual(self.screen.notice, "")
        self.assertEqual(self.screen._pending_song, "canon")
        self.assertIsNone(self.screen._pending_pack)


if __name__ == "__main__":
    unittest.main()
