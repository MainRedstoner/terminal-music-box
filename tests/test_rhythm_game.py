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

    def test_no_song_argument_defaults_to_canon(self):
        self.app.navigate("rhythm_game")
        self.assertEqual(self.app.current.song_id, "canon")

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
        self.tap(self.lane_key(n0))
        self.at(n1.time + PERFECT_WIN + 0.03)
        self.tap(self.lane_key(n1))
        self.assertEqual((g.perfect, g.good, g.miss), (1, 1, 0))
        self.assertEqual(g.combo, 2)
        self.assertEqual(g.score, 303 + 102)

    def test_combo_multiplier_raises_the_score(self):
        self.start_play()
        g = self.game
        for n in g.notes[:2]:
            self.at(n.time)
            self.tap(self.lane_key(n))
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

    def test_a_second_key_down_while_held_does_not_judge(self):
        # Windows/console backends report auto-repeat as a plain key-down, so a
        # press for a key that is still held must be ignored as well.
        self.start_play()
        g = self.game
        key = self.lane_key(g.notes[0])
        self.at(g.notes[0].time)
        self.press(key)
        with mock.patch.object(g, "_hit_lane") as hit:
            self.term.send(KeyEvent(key, pressed=True))
            self.step()
        hit.assert_not_called()
        self.assertEqual(g.judged, 1)

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
        self.press("esc")
        pos = g.player.pos
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
        self.press("esc")
        t = self.game.song_time
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
        self.assertEqual(self.app.current_name, "rhythm_menu")

    def test_pause_menu_escape_quits_to_the_list(self):
        self.start_play()
        self.press("esc")
        self.press("ctrl+q")
        self.assertEqual(self.app.current_name, "rhythm_menu")

    def test_mouse_click_on_resume_button(self):
        self.start_play()
        self.press("esc")
        self.click_label(self.app.theme.t("rhythm.resume"))
        self.assertEqual(self.game.state, "countdown")

    def test_mouse_click_on_quit_button(self):
        self.start_play()
        self.press("esc")
        self.click_label(self.app.theme.t("rhythm.quit_to_list"))
        self.assertEqual(self.app.current_name, "rhythm_menu")

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
            self.tap(self.lane_key(n))
        self.run_until(lambda: g.state == "result", dt=0.05)
        self.assertEqual(g.miss, 0)
        self.assertEqual(g.perfect, len(g.notes))
        self.assertEqual(g.grade, "S")
        self.assertGreater(g.score, 0)

    def test_result_enter_returns_to_the_list(self):
        self.start_play()
        self.run_until(lambda: self.game.state == "result", dt=0.05)
        self.press("enter")
        self.assertEqual(self.app.current_name, "rhythm_menu")

    def test_result_escape_returns_to_the_list(self):
        self.start_play()
        self.run_until(lambda: self.game.state == "result", dt=0.05)
        self.press("esc")
        self.assertEqual(self.app.current_name, "rhythm_menu")

    def test_result_mouse_back_button(self):
        self.start_play()
        self.run_until(lambda: self.game.state == "result", dt=0.05)
        self.click_label(self.app.theme.t("common.back"))
        self.assertEqual(self.app.current_name, "rhythm_menu")


class Minuet(Game):
    song = "minuet_g"

    def test_the_timbre_is_locked_to_the_electric_piano(self):
        self.assertEqual(self.game.timbre, "pling")
        self.assertEqual(self.game.player.timbre, "pling")

    def test_downbeat_plays_the_full_score_and_accepts_the_double_hit(self):
        self.start_play()
        g = self.game
        with mock.patch.object(self.engine, "play_note",
                               wraps=self.engine.play_note) as pn:
            self.at(g.notes[0].time)
            self.assertEqual(pn.call_count, 4)
            downbeat = [n for n in g.notes if n.time == g.notes[0].time]
            self.assertEqual(len(downbeat), 2)
            for note in downbeat:
                self.press(self.lane_key(note))
            self.assertEqual(g.perfect, 2)
            self.assertEqual(pn.call_count, 4)


class TurkishMarch(Game):
    song = "turkish_march"

    def test_the_chart_is_the_right_hand_melody(self):
        g = self.game
        self.assertEqual(g.beatmap.song_id, "turkish_march")
        # The chart taps the eighth-note skeleton of the written right hand, so
        # every falling note lands on a written note but not every written note
        # becomes a tap.
        self.assertGreater(len(g.notes), 400)
        self.assertLess(len(g.notes), len(g.song.chart_notes))
        self.assertLess(len(g.notes), len(g.song.notes))
        self.assertTrue(
            {round(n.time, 6) for n in g.notes}
            <= {round(n.time + g.beatmap.lead_in, 6)
                for n in g.song.chart_notes}
        )

    def test_an_accent_chord_judges_both_notes(self):
        g = self.game
        by_time = {}
        for note in g.notes:
            by_time.setdefault(round(note.time, 6), []).append(note.lane)
        t, lanes = next((t, ls) for t, ls in sorted(by_time.items())
                        if len(ls) == 2)
        self.start_play()
        self.at(t)
        for lane in lanes:
            self.press(g.lane_keys[lane])
        self.assertEqual(g.perfect, 2)

    def test_the_timbre_is_locked_to_the_electric_piano(self):
        self.assertEqual(self.game.timbre, "pling")
        self.assertEqual(self.game.player.timbre, "pling")

    def test_the_first_note_can_be_hit(self):
        self.start_play()
        n = self.game.notes[0]
        self.at(n.time)
        self.press(self.lane_key(n))
        self.assertEqual(self.game.perfect, 1)
        self.assertEqual(self.game.miss, 0)


class FurElise(Game):
    song = "fur_elise"

    def test_loads_the_full_song_with_the_locked_timbre(self):
        g = self.game
        self.assertEqual(g.song_id, "fur_elise")
        self.assertIs(g.beatmap, songs.get_beatmap("fur_elise"))
        self.assertEqual(len(g.notes), 594)
        self.assertEqual((g.timbre, g.player.timbre), ("pling", "pling"))
        self.assertIn("致爱丽丝", self.frame)

    def test_first_note_sounds_exactly_at_the_judgment_line(self):
        self.start_play()
        g = self.game
        with mock.patch.object(self.engine, "play_note",
                               wraps=self.engine.play_note) as pn:
            self.at(g.beatmap.lead_in - 0.05)
            self.assertEqual(pn.call_count, 0)
            self.at(g.notes[0].time + PERFECT_WIN)
            self.assertEqual(pn.call_count, 1)
            self.assertEqual(pn.call_args.args[1], 76)

    def test_full_song_schedules_every_part_and_reaches_results(self):
        g = self.game
        with mock.patch.object(self.engine, "play_note",
                               wraps=self.engine.play_note) as pn:
            self.start_play()
            self.run_until(lambda: g.state == "result", dt=0.1)
        self.assertEqual(pn.call_count, 1041)
        self.assertEqual(g.judged, 594)
        self.assertEqual(g.miss, 594)
        self.assertIsNone(g.player)
        self.assertIn("致爱丽丝", self.frame)


class TimbreLock(Game):
    song = "canon"

    def test_canon_locks_the_timbre_to_the_didgeridoo(self):
        g = self.game
        self.assertEqual(g.timbre, "didgeridoo")
        self.assertEqual(g.player.timbre, "didgeridoo")

    def test_songs_without_a_lock_follow_the_user_timbre(self):
        self.assertEqual(self.cfg.timbre, "harp")  # setup default
        self.app.navigate("rhythm_game", song="twinkle")
        self.assertEqual(self.app.current.timbre, "harp")

    def test_the_locked_timbre_uses_its_own_sound_settings(self):
        self.cfg.set_sound("didgeridoo", vol=0.5, ln=2.0)
        self.restart()
        self.assertEqual((self.game.player.vol, self.game.player.length),
                         (0.5, 2.0))

    def test_the_autoplayed_melody_sounds_the_didgeridoo(self):
        self.start_play()
        g = self.game
        with mock.patch.object(self.engine, "play_note",
                               wraps=self.engine.play_note) as pn:
            self.at(g.beatmap.lead_in + 0.05)
            self.assertGreater(pn.call_count, 0)
            self.assertEqual(pn.call_args.args[0], "didgeridoo")


class CanonChartPlay(Game):
    song = "canon"

    def test_both_keys_of_a_chord_score(self):
        self.start_play()
        g = self.game
        i = next(i for i, n in enumerate(g.notes)
                 if i + 1 < len(g.notes) and g.notes[i + 1].time == n.time)
        a, b = g.notes[i], g.notes[i + 1]
        self.assertNotEqual(a.lane, b.lane)
        self.at(a.time)
        self.tap(self.lane_key(a))
        self.tap(self.lane_key(b))
        self.assertEqual(g.perfect, 2)
        self.assertEqual(g.combo, 2)

    def test_a_perfect_run_clears_the_whole_authored_chart(self):
        self.start_play()
        g = self.game
        for n in g.notes:
            self.at(n.time)
            self.tap(self.lane_key(n))
        self.run_until(lambda: g.state == "result", dt=0.05)
        self.assertEqual(g.miss, 0)
        self.assertEqual(g.perfect, len(g.notes))
        self.assertEqual(g.grade, "S")


class LatencyOffset(Game):
    def test_positive_latency_shifts_the_hit_window(self):
        self.restart(latency_ms=100)
        self.assertEqual(self.game.offset_sec, 0.1)
        self.start_play()
        n = self.game.notes[0]
        self.at(n.time + 0.09)
        self.press(self.lane_key(n))
        self.assertEqual(self.game.perfect, 1)

    def test_without_the_offset_the_same_press_is_only_good(self):
        self.start_play()
        n = self.game.notes[0]
        self.at(n.time + 0.09)
        self.press(self.lane_key(n))
        self.assertEqual(self.game.perfect, 0)
        self.assertEqual(self.game.good, 1)


if __name__ == "__main__":
    unittest.main()