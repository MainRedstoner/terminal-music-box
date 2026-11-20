"""Rhythm gameplay: countdown, tap judgment, pause, result, latency offset."""
from __future__ import annotations

import unittest
from unittest import mock

from tmb import songs
from tmb.config import DEFAULT_KEYS
from tmb.events import KeyEvent
from tmb.screens.rhythm_game import (COUNTDOWN, GOOD_WIN, PERFECT_WIN,
                                     REPEAT_TIMEOUT, RESULT_TAIL)

try:
    from tests.helpers import HeadlessCase
except ImportError:
    from helpers import HeadlessCase


class Game(HeadlessCase):
    song = "twinkle"

    def setUp(self):
        super().setUp()
        self.app.navigate("rhythm_game", song=self.song)
        self.game = self.app.current
        self.step()

    def restart(self, **cfg):
        for k, v in cfg.items():
            setattr(self.cfg, k, v)
        self.app.navigate("rhythm_game", song=self.song)
        self.game = self.app.current
        self.step()

    def start_play(self):
        self.run_until(lambda: self.game.state == "play", dt=0.01)

    def at(self, t, dt=0.005):
        self.run_until(lambda: self.game.song_time >= t, dt=dt)

    def lane_key(self, note):
        return self.game.lane_keys[note.lane]


class Setup(Game):
    def test_enter_starts_in_countdown(self):
        g = self.game
        self.assertEqual(g.state, "countdown")
        self.assertLessEqual(g.countdown, COUNTDOWN)
        self.assertGreater(g.countdown, COUNTDOWN - 0.1)
        self.assertEqual(g.song_id, self.song)
        self.assertIs(g.beatmap, songs.get_beatmap(self.song))
        self.assertEqual(g.lane_keys, DEFAULT_KEYS)
        self.assertEqual(g.score, 0)
        self.assertEqual(g.note_state, [0] * len(g.notes))
        self.assertEqual(g.song_time, 0.0)

    def test_countdown_becomes_play_after_three_seconds(self):
        self.advance(3.1, dt=0.01)
        self.assertEqual(self.game.state, "play")
        self.assertLess(self.game.song_time, 0.2)

    def test_lane_keys_do_not_judge_during_countdown(self):
        self.press("a")
        self.assertEqual(self.game.judged, 0)
        self.assertEqual(self.game.state, "countdown")

    def test_countdown_frame_shows_the_song_and_a_number(self):
        self.assertIn(self.game.song.title("zh"), self.frame)
        self.assertIn(self.app.theme.t("rhythm.countdown"), self.frame)

    def test_custom_lane_keys_are_used(self):
        self.restart(rhythm_keys=list("zxcvbn"))
        self.assertEqual(self.game.lane_keys, list("zxcvbn"))
        self.start_play()
        self.at(self.game.notes[0].time)
        self.press("z")
        self.assertEqual(self.game.perfect, 1)

    def test_short_key_list_falls_back_to_defaults(self):
        self.restart(rhythm_keys=["a"])
        self.assertEqual(self.game.lane_keys, DEFAULT_KEYS)

    def test_scroll_speed_is_applied_without_crashing(self):
        self.restart(scroll_speed=2.5)
        self.start_play()
        self.advance(1.0)
        self.assertTrue(self.frame.strip())


class Judgment(Game):
    def test_perfect_hit_on_the_note_time(self):
        self.start_play()
        n = self.game.notes[0]
        self.at(n.time)
        self.press(self.lane_key(n))
        g = self.game
        self.assertEqual((g.perfect, g.good, g.miss), (1, 0, 0))
        self.assertEqual(g.combo, 1)
        self.assertEqual(g.maxcombo, 1)
        self.assertEqual(g.score, 303)
        self.assertEqual(g.judged, 1)
        self.assertEqual(g.note_state[0], 1)
        self.assertGreaterEqual(self.engine.active(), 1)

    def test_slightly_early_hit_is_still_perfect(self):
        self.start_play()
        n = self.game.notes[0]
        self.at(n.time - PERFECT_WIN + 0.01)
        self.press(self.lane_key(n))
        self.assertEqual(self.game.perfect, 1)

    def test_late_hit_inside_the_good_window(self):
        self.start_play()
        g = self.game
        n0, n1 = g.notes[0], g.notes[1]
        self.at(n0.time)
        self.press(self.lane_key(n0))
        self.at(n1.time + PERFECT_WIN + 0.03)
        self.press(self.lane_key(n1))
        self.assertEqual((g.perfect, g.good, g.miss), (1, 1, 0))
        self.assertEqual(g.combo, 2)
        self.assertEqual(g.score, 303 + 102)

    def test_combo_multiplier_raises_the_score(self):
        self.start_play()
        g = self.game
        for n in g.notes[:2]:
            self.at(n.time)
            self.press(self.lane_key(n))
        self.assertEqual(g.combo, 2)
        self.assertEqual(g.score, 303 + 306)

    def test_unhit_note_becomes_a_miss_and_breaks_the_combo(self):
        self.start_play()
        g = self.game
        n = g.notes[0]
        self.at(n.time)
        self.press(self.lane_key(n))
        self.at(g.notes[1].time + GOOD_WIN + 0.05)
        self.assertEqual(g.miss, 1)
        self.assertEqual(g.combo, 0)
        self.assertEqual(g.maxcombo, 1)
        self.assertEqual(g.note_state[1], 2)
        self.assertEqual(g.judged, 2)

    def test_pressing_far_too_early_judges_nothing(self):
        self.start_play()
        self.at(0.5)
        self.press(self.lane_key(self.game.notes[0]))
        self.assertEqual(self.game.judged, 0)
        self.assertEqual(self.game.score, 0)

    def test_pressing_the_wrong_lane_judges_nothing(self):
        self.start_play()
        n = self.game.notes[0]
        self.at(n.time)
        self.press(self.game.lane_keys[(n.lane + 1) % 6])
        self.assertEqual(self.game.judged, 0)

    def test_a_note_cannot_be_hit_twice(self):
        self.start_play()
        n = self.game.notes[0]
        self.at(n.time)
        self.press(self.lane_key(n))
        self.press(self.lane_key(n))
        self.assertEqual(self.game.judged, 1)
        self.assertEqual(self.game.perfect, 1)

    def test_repeat_events_never_judge_a_note(self):
        self.start_play()
        g = self.game
        key = self.lane_key(g.notes[0])
        self.at(g.notes[0].time)
        self.press(key)
        with mock.patch.object(g, "_hit_lane") as hit:
            self.term.send(KeyEvent(key, pressed=True, repeat=True))
            self.step()
        hit.assert_not_called()
        self.assertEqual(g.judged, 1)
        self.assertTrue(g.key_down.get(key))

    def test_legacy_terminal_expires_the_pressed_key_look(self):
        self.term.release_events = False
        self.start_play()
        g = self.game
        key = self.lane_key(g.notes[0])
        self.at(g.notes[0].time)
        self.press(key)
        self.advance(REPEAT_TIMEOUT + 0.1, dt=0.05)
        self.assertFalse(g.key_down.get(key))

    def test_judgment_feedback_is_drawn(self):
        self.start_play()
        n = self.game.notes[0]
        self.at(n.time)
        self.press(self.lane_key(n))
        self.assertIn(self.app.theme.t("rhythm.perfect"), self.frame)
        self.assertIn("0000303", self.frame)


class Melody(Game):
    def test_melody_autoplays_and_the_hit_is_silent(self):
        self.start_play()
        g = self.game
        with mock.patch.object(self.engine, "play_note",
                               wraps=self.engine.play_note) as pn:
            self.at(g.beatmap.lead_in - 0.05)
            self.assertEqual(pn.call_count, 0)      # silence during the lead-in
            self.press(self.lane_key(g.notes[0]))   # the hit itself makes no sound
            self.assertEqual(pn.call_count, 0)
            self.advance(0.3)
            self.assertEqual(pn.call_count, 1)      # the melody sounded on its own
            self.assertEqual(pn.call_args.args[1], g.song.notes[0].midi)

    def test_melody_note_lands_exactly_on_its_chart_time(self):
        self.start_play()
        g = self.game
        with mock.patch.object(self.engine, "play_note",
                               wraps=self.engine.play_note) as pn:
            self.at(g.notes[0].time + PERFECT_WIN)
            self.assertEqual(pn.call_count, 1)      # fires as the note crosses the line

    def test_melody_pauses_with_the_game_and_resumes_after_the_countdown(self):
        self.start_play()
        g = self.game
        self.advance(2.5)
        self.assertGreaterEqual(self.engine.active(), 1)
        pos = g.player.pos
        self.press("esc")
        self.advance(0.5)
        self.assertEqual(g.player.pos, pos)
        self.press("enter")
        self.advance(COUNTDOWN + 0.2, dt=0.01)
        self.assertEqual(g.state, "play")
        self.assertGreater(g.player.pos, pos)

    def test_finishing_stops_the_melody(self):
        self.start_play()
        g = self.game
        self.run_until(lambda: g.state == "result", dt=0.05)
        self.assertIsNone(g.player)
        self.assertEqual(self.engine.active(), 0)


class PauseAndResult(Game):
    def test_escape_pauses_and_freezes_song_time(self):
        self.start_play()
        self.advance(1.0)
        self.press("esc")
        self.assertEqual(self.game.state, "pause")
        t = self.game.song_time
        self.advance(0.5)
        self.assertEqual(self.game.song_time, t)
        self.assertIn(self.app.theme.t("rhythm.pause"), self.frame)

    def test_exit_chords_do_not_pause_during_play(self):
        self.start_play()
        for key in ("ctrl+q", "ctrl+d", "ctrl+c"):
            with self.subTest(key=key):
                self.press(key)
                self.assertEqual(self.game.state, "play")
                self.assertEqual(self.app.current_name, "rhythm_game")

    def test_escape_during_countdown_pauses(self):
        self.press("esc")
        self.assertEqual(self.game.state, "pause")

    def test_resume_runs_the_countdown_again_and_keeps_progress(self):
        self.start_play()
        self.advance(1.0)
        t = self.game.song_time
        self.press("esc")
        self.press("enter")
        self.assertEqual(self.game.state, "countdown")
        self.assertAlmostEqual(self.game.countdown, COUNTDOWN, places=1)
        self.assertEqual(self.game.song_time, t)
        self.advance(3.1, dt=0.01)
        self.assertEqual(self.game.state, "play")
        self.assertGreater(self.game.song_time, t)

    def test_pause_menu_second_item_quits_to_the_list(self):
        self.start_play()
        self.press("esc")
        self.press("down")
        self.press("enter")
        self.assertEqual(self.app.current_name, "rhythm_list")

    def test_pause_menu_escape_quits_to_the_list(self):
        self.start_play()
        self.press("esc")
        self.press("ctrl+q")
        self.assertEqual(self.app.current_name, "rhythm_list")

    def test_mouse_click_on_resume_button(self):
        self.start_play()
        self.press("esc")
        self.click_label(self.app.theme.t("rhythm.resume"))
        self.assertEqual(self.game.state, "countdown")

    def test_mouse_click_on_quit_button(self):
        self.start_play()
        self.press("esc")
        self.click_label(self.app.theme.t("rhythm.quit_to_list"))
        self.assertEqual(self.app.current_name, "rhythm_list")

    def test_result_after_the_full_duration(self):
        self.start_play()
        self.run_until(lambda: self.game.state == "result", dt=0.05)
        g = self.game
        self.assertGreater(g.song_time, g.beatmap.duration + RESULT_TAIL - 0.1)
        self.assertEqual(g.judged, len(g.notes))
        self.assertEqual(g.miss, len(g.notes))
        self.assertEqual(g.score, 0)
        self.assertEqual(g.grade, "D")
        self.assertIn(self.app.theme.t("rhythm.result"), self.frame)
        self.assertIn(g.song.title("zh"), self.frame)

    def test_result_grade_is_s_for_a_perfect_run(self):
        self.start_play()
        g = self.game
        for n in g.notes:
            self.at(n.time)
            self.press(self.lane_key(n))
        self.run_until(lambda: g.state == "result", dt=0.05)
        self.assertEqual(g.miss, 0)
        self.assertEqual(g.perfect, len(g.notes))
        self.assertEqual(g.grade, "S")
        self.assertGreater(g.score, 0)

    def test_result_enter_returns_to_the_list(self):
        self.start_play()
        self.run_until(lambda: self.game.state == "result", dt=0.05)
        self.press("enter")
        self.assertEqual(self.app.current_name, "rhythm_list")

    def test_result_escape_returns_to_the_list(self):
        self.start_play()
        self.run_until(lambda: self.game.state == "result", dt=0.05)
        self.press("esc")
        self.assertEqual(self.app.current_name, "rhythm_list")

    def test_result_mouse_back_button(self):
        self.start_play()
        self.run_until(lambda: self.game.state == "result", dt=0.05)
        self.click_label(self.app.theme.t("common.back"))
        self.assertEqual(self.app.current_name, "rhythm_list")


class LatencyOffset(Game):
    def test_positive_latency_shifts_the_hit_window(self):
        self.restart(latency_ms=100)
        self.assertEqual(self.game.offset_sec, 0.1)
        self.start_play()
        n = self.game.notes[0]
        self.at(n.time + 0.1)
        self.press(self.lane_key(n))
        self.assertEqual(self.game.perfect, 1)

    def test_without_the_offset_the_same_press_is_only_good(self):
        self.start_play()
        n = self.game.notes[0]
        self.at(n.time + 0.1)
        self.press(self.lane_key(n))
        self.assertEqual(self.game.perfect, 0)
        self.assertEqual(self.game.good, 1)


if __name__ == "__main__":
    unittest.main()