"""Free play: keyboard voices, timbre cycling, prenatal mode, mouse."""
from __future__ import annotations

import unittest

from tmb import songs
from tmb.audio import synth
from tmb.events import KeyEvent
from tmb.screens.freeplay import (ACTIVITY_WINDOW, KEY_MIDI, STUCK_TIMEOUT,
                                  REPEAT_TIMEOUT)

try:
    from tests.helpers import HeadlessCase, has_cjk
except ImportError:
    from helpers import HeadlessCase, has_cjk


class FreePlay(HeadlessCase):
    start_screen = "freeplay"

    def test_frame_shows_the_three_row_keyboard(self):
        th = self.app.theme
        self.assertIn(th.t("freeplay.title"), self.frame)
        self.assertIn(th.t("freeplay.exit_hint"), self.frame)
        for cap in ("[Q]", "[A]", "[Z]", "[M]"):
            self.assertIn(cap, self.frame)
        for name in ("C5", "C4", "C3"):
            self.assertIn(name, self.frame)

    def test_play_key_creates_a_voice(self):
        self.press("a")
        self.assertEqual(self.engine.active(), 1)
        self.assertTrue(self.screen.key_down.get("a"))
        self.press("s")
        self.assertEqual(self.engine.active(), 2)

    def test_every_key_of_the_21_key_keyboard_plays(self):
        self.assertEqual(len(KEY_MIDI), 21)
        for i, key in enumerate(KEY_MIDI):
            self.press(key, dt=0.001)
            self.assertEqual(self.engine.active(), i + 1)
        self.assertEqual(len(self.screen.key_down), 21)
        for key in KEY_MIDI:
            self.release(key, dt=0.001)
        self.assertEqual(self.screen.key_down, {})
        self.assertEqual(self.engine.active(), 21)  # one-shots ring out

    def test_legacy_terminal_expires_held_keys_after_the_timeout(self):
        self.term.release_events = False
        for key in KEY_MIDI:
            self.press(key, dt=0.001)
        self.assertEqual(len(self.screen.key_down), 21)
        self.advance(REPEAT_TIMEOUT + 0.1, dt=0.05)
        self.assertEqual(self.screen.key_down, {})
        self.assertEqual(self.engine.active(), 21)

    def test_key_up_does_not_stop_a_playing_note(self):
        self.press("a")
        self.release("a")
        self.assertEqual(self.screen.key_down, {})
        self.assertEqual(self.engine.active(), 1)

    def test_sustained_timbre_holds_a_voice_until_key_release(self):
        self.cfg.timbre = "bit"
        self.press("a")
        voice = next(iter(self.engine._voices.values()))
        self.assertTrue(voice._sustain)
        self.advance(1.0)
        self.assertEqual(self.engine.active(), 1)  # still sounding while held
        self.assertTrue(self.screen.key_down.get("a"))
        self.release("a")
        self.assertEqual(self.screen.key_down, {})
        self.assertEqual([loop for _, loop in voice._segments], [False])  # tail rings
        self.assertEqual(self.engine.active(), 1)

    def test_a_lost_release_frees_the_key_after_the_stuck_timeout(self):
        self.cfg.timbre = "bit"
        self.press("a")
        self.advance(STUCK_TIMEOUT + 0.3, dt=0.1)
        self.assertEqual(self.screen.key_down, {})
        self.assertEqual(self.screen.key_voice, {})
        voice = next(iter(self.engine._voices.values()))
        self.assertEqual([loop for _, loop in voice._segments], [False])  # capped off

    def test_repeat_events_never_retrigger_a_note(self):
        self.press("a")
        self.term.send(KeyEvent("a", pressed=True, repeat=True))
        self.step()
        self.advance(0.5)
        self.term.send(KeyEvent("a", pressed=True, repeat=True))
        self.step()
        self.assertEqual(self.engine.active(), 1)
        self.assertTrue(self.screen.key_down.get("a"))

    def test_legacy_sustained_timbre_plays_a_fixed_length_one_shot(self):
        self.term.release_events = False
        self.cfg.timbre = "bit"
        self.press("a")
        voice = next(iter(self.engine._voices.values()))
        self.assertFalse(voice._sustain)
        self.assertEqual([loop for _, loop in voice._segments], [False])
        self.release("a")
        self.assertEqual(self.engine.active(), 1)
        self.assertEqual(self.screen.key_down, {})

    def test_auto_repeat_does_not_retrigger(self):
        self.press("a")
        self.advance(0.15, dt=0.05)
        self.press("a")
        self.advance(0.15, dt=0.05)
        self.assertEqual(self.engine.active(), 1)

    def test_key_up_of_non_play_keys_is_safe(self):
        self.release("enter")
        self.release("ctrl+x")
        self.assertEqual(self.engine.active(), 0)

    def test_ctrl_x_cycles_timbre_and_persists(self):
        self.assertEqual(self.cfg.timbre, "harp")
        self.press("ctrl+x")
        self.assertEqual(self.cfg.timbre, "bit")
        self.press("ctrl+x")
        self.assertEqual(self.cfg.timbre, "flute")
        self.assertEqual(self.read_config()["timbre"], "flute")
        self.assertIn(synth.timbre_name("flute", "zh"), self.frame)
        for _ in range(11):
            self.press("ctrl+x")
        self.assertEqual(self.cfg.timbre, "harp")

    def test_ctrl_t_starts_prenatal_with_default_song(self):
        self.press("ctrl+t")
        p = self.screen.player
        self.assertIsNotNone(p)
        self.assertTrue(p.playing)
        self.assertTrue(self.screen.prenatal)
        self.assertEqual(p.song.id, songs.first_song_id())
        self.assertIn(p.song.title("zh"), self.frame)
        self.assertIn(self.app.theme.t("freeplay.prenatal_hint"), self.frame)

    def test_ctrl_t_uses_the_configured_song(self):
        self.cfg.prenatal_song = "canon"
        self.press("ctrl+t")
        self.assertEqual(self.screen.player.song.id, "canon")

    def test_ctrl_t_toggles_off_and_silences(self):
        self.press("ctrl+t")
        self.advance(0.5)
        self.assertGreater(self.engine.active(), 0)
        self.press("ctrl+t")
        self.assertIsNone(self.screen.player)
        self.assertFalse(self.screen.prenatal)
        self.assertEqual(self.engine.active(), 0)

    def test_ctrl_x_updates_the_player_timbre(self):
        self.press("ctrl+t")
        self.press("ctrl+x")
        self.assertEqual(self.screen.player.timbre, self.cfg.timbre)

    def test_prenatal_pauses_after_the_activity_window(self):
        self.press("ctrl+t")
        p = self.screen.player
        self.advance(ACTIVITY_WINDOW + 0.1, dt=0.05)
        self.assertFalse(p.playing)
        pos = p.pos
        self.advance(1.0, dt=0.05)
        self.assertEqual(p.pos, pos)

    def test_prenatal_resumes_on_a_play_key(self):
        self.press("ctrl+t")
        p = self.screen.player
        self.advance(ACTIVITY_WINDOW + 0.1, dt=0.05)
        self.assertFalse(p.playing)
        self.press("q")
        # The frame clock advances before input is dispatched, so the resume
        # takes effect on the following frame's update.
        self.step()
        self.assertTrue(p.playing)
        pos = p.pos
        self.advance(0.5)
        self.assertGreater(p.pos, pos)

    def test_prenatal_keeps_playing_while_keys_are_pressed(self):
        self.press("ctrl+t")
        p = self.screen.player
        for _ in range(30):
            self.advance(0.1)
            self.press("q")
        self.assertTrue(p.playing)
        self.assertGreater(p.pos, 2.5)

    def test_prenatal_mode_mutes_user_played_notes(self):
        self.press("ctrl+t")
        p = self.screen.player
        self.press("a")
        self.press("s")
        self.assertTrue(self.screen.key_down.get("a"))
        self.assertTrue(self.screen.key_down.get("s"))
        self.assertTrue(p.playing)
        # only the auto-played song note exists; neither key press made a sound
        self.assertEqual(self.engine.active(), 1)

    def test_prenatal_song_loops_after_it_finishes(self):
        self.press("ctrl+t")
        p = self.screen.player
        duration = p.song.duration
        prev = 0.0
        wrapped = False
        for i in range(int((duration + 3.0) / 0.05)):
            self.step(0.05)
            if i % 10 == 0:
                self.term.key("q")
            if p.pos < prev - 1.0:
                wrapped = True
            prev = p.pos
        self.assertTrue(wrapped)
        self.assertTrue(p.playing)
        self.assertLess(p.pos, duration)

    def test_ctrl_a_opens_song_select_and_keeps_the_player(self):
        self.press("ctrl+t")
        fp = self.screen
        player = fp.player
        self.press("ctrl+a")
        self.assertEqual(self.app.current_name, "song_select")
        self.assertIs(fp.player, player)
        self.press("down")
        self.press("down")
        self.press("enter")
        self.assertEqual(self.app.current_name, "freeplay")
        self.assertEqual(self.cfg.prenatal_song, "ode_joy")
        self.assertEqual(self.read_config()["prenatal_song"], "ode_joy")
        self.assertEqual(self.screen.player.song.id, "ode_joy")
        self.assertTrue(self.screen.player.playing)

    def test_ctrl_a_without_a_player_only_stores_the_choice(self):
        self.press("ctrl+a")
        self.assertEqual(self.app.current_name, "song_select")
        self.press("down")
        self.press("enter")
        self.assertEqual(self.app.current_name, "freeplay")
        self.assertEqual(self.cfg.prenatal_song, "mary_lamb")
        self.assertIsNone(self.screen.player)
        self.press("ctrl+t")
        self.assertEqual(self.screen.player.song.id, "mary_lamb")

    def test_song_select_mouse_click_picks_a_song(self):
        self.press("ctrl+a")
        self.click_label(songs.SONGS["canon"].title("zh"))
        self.assertEqual(self.app.current_name, "freeplay")
        self.assertEqual(self.cfg.prenatal_song, "canon")

    def test_song_select_escape_keeps_the_previous_choice(self):
        self.press("ctrl+t")
        self.press("ctrl+a")
        self.press("esc")
        self.assertEqual(self.app.current_name, "freeplay")
        self.assertIsNone(self.cfg.prenatal_song)
        self.assertIsNotNone(self.screen.player)

    def test_exit_chords_return_to_the_menu_and_clean_up(self):
        for key in ("ctrl+q", "ctrl+d", "ctrl+c", "esc"):
            with self.subTest(key=key):
                self.app.navigate("freeplay")
                fp = self.screen
                self.press("ctrl+t")
                self.press("a")
                self.press(key)
                self.assertEqual(self.app.current_name, "menu")
                self.assertIsNone(fp.player)
                self.assertFalse(fp.prenatal)
                self.assertEqual(self.engine.active(), 0)

    def test_reentering_after_exit_starts_fresh(self):
        self.press("ctrl+t")
        self.press("esc")
        self.press("1")
        self.assertEqual(self.app.current_name, "freeplay")
        self.assertIsNone(self.screen.player)
        self.assertFalse(self.screen.prenatal)
        self.assertEqual(self.screen.key_down, {})

    def test_mouse_click_on_a_key_cap_plays_a_note(self):
        x, y = self.find_label("[A]")
        self.click(x + 1, y)
        self.assertEqual(self.engine.active(), 1)
        self.assertTrue(self.screen.key_down.get("a"))
        self.click(x + 1, y, kind="release")
        self.assertEqual(self.screen.key_down, {})

    def test_mouse_click_and_release_of_a_sustained_timbre_cap(self):
        self.cfg.timbre = "bit"
        x, y = self.find_label("[S]")
        self.click(x + 1, y)
        voice = next(iter(self.engine._voices.values()))
        self.assertTrue(voice._sustain)
        self.click(x + 1, y, kind="release")
        self.assertEqual(self.screen.key_down, {})
        self.assertEqual(self.screen.key_voice, {})
        self.assertEqual([loop for _, loop in voice._segments], [False])
        self.assertEqual(self.engine.active(), 1)

    def test_mouse_click_on_timbre_button(self):
        self.click_label(self.app.theme.t("freeplay.btn_timbre"))
        self.assertEqual(self.cfg.timbre, "bit")

    def test_mouse_click_on_prenatal_button_toggles(self):
        th = self.app.theme
        self.click_label(th.t("freeplay.btn_prenatal", state=th.t("common.off")))
        self.assertIsNotNone(self.screen.player)
        self.click_label(th.t("freeplay.btn_prenatal", state=th.t("common.on")))
        self.assertIsNone(self.screen.player)

    def test_song_button_appears_only_with_prenatal_on(self):
        th = self.app.theme
        self.assertNotIn(th.t("freeplay.btn_song"), self.frame)
        self.press("ctrl+t")
        self.assertIn(th.t("freeplay.btn_song"), self.frame)
        self.click_label(th.t("freeplay.btn_song"))
        self.assertEqual(self.app.current_name, "song_select")

    def test_mouse_click_on_back_button(self):
        self.click_label(self.app.theme.t("common.back"))
        self.assertEqual(self.app.current_name, "menu")


class SoundStrip(HeadlessCase):
    start_screen = "freeplay"
    """Inline volume / length editors beside the keyboard."""

    def setUp(self):
        super().setUp()
        th = self.app.theme
        self.vol_label = th.t("freeplay.vol")
        self.len_label = th.t("freeplay.len")

    def test_strip_shows_both_values(self):
        self.assertIn(self.vol_label, self.frame)
        self.assertIn(self.len_label, self.frame)
        self.assertIn("1.0", self.frame)
        self.assertIn("1.00×", self.frame)

    def test_up_down_toggle_the_focus(self):
        self.press("down")
        self.assertEqual(self.screen.focus, 1)
        self.press("up")
        self.assertEqual(self.screen.focus, 0)
        self.press("up")
        self.assertEqual(self.screen.focus, 1)

    def test_left_right_adjust_the_focused_volume(self):
        self.press("right")
        self.assertEqual(self.cfg.sound_params("harp"), (1.1, 1.0))
        self.press("left")
        self.press("left")
        self.assertEqual(self.cfg.sound_params("harp"), (0.9, 1.0))
        self.assertEqual(self.read_config()["sound"]["harp"]["vol"], 0.9)

    def test_left_right_adjust_length_when_focused(self):
        self.press("down")  # focus the length row
        self.press("left")  # harp (ringing) can only be trimmed
        self.assertEqual(self.cfg.sound_params("harp"), (1.0, 0.75))
        self.assertEqual(self.read_config()["sound"]["harp"]["len"], 0.75)
        self.press("ctrl+x")
        self.press("ctrl+x")  # harp -> bit -> flute (sustained)
        self.press("right")
        self.assertEqual(self.cfg.sound_params("flute"), (1.0, 1.25))

    def test_ringing_timbre_length_is_capped_at_natural(self):
        self.press("down")
        for _ in range(6):
            self.press("right")
        self.assertEqual(self.cfg.sound_params("harp")[1], 1.0)

    def test_sustained_timbre_length_grows_to_four(self):
        self.cfg.timbre = "flute"
        self.press("down")
        for _ in range(20):
            self.press("right")
        self.assertEqual(self.cfg.sound_params("flute")[1], 4.0)

    def test_bit_defaults_to_quarter_length(self):
        self.cfg.timbre = "bit"
        self.step()
        self.assertIn("0.25×", self.frame)
        self.assertEqual(self.cfg.sound_params("bit"), (1.0, 0.25))

    def test_adjusted_settings_follow_a_timbre_switch(self):
        self.press("right")
        self.assertEqual(self.cfg.sound_params("harp"), (1.1, 1.0))
        self.press("ctrl+x")  # -> bit, with its 0.25x default
        self.assertEqual(self.cfg.sound_params("bit"), (1.0, 0.25))
        self.assertIn("0.25×", self.frame)

    def test_prenatal_melody_picks_up_live_adjustments(self):
        self.press("ctrl+t")
        self.assertEqual(self.screen.player.vol, 1.0)
        self.press("right")
        self.assertEqual(self.screen.player.vol, 1.1)
        self.assertEqual(self.screen.player.length, 1.0)

    def test_mouse_click_focuses_a_row(self):
        self.click_label(self.len_label)
        self.assertEqual(self.screen.focus, 1)
        self.press("left")
        self.assertEqual(self.cfg.sound_params("harp")[1], 0.75)


class FreePlayAscii(HeadlessCase):
    start_screen = "freeplay"
    mode = "ascii"

    def test_ascii_frame_is_english_and_complete(self):
        self.assertFalse(has_cjk(self.frame))
        self.assertIn("Free Play", self.frame)
        self.assertIn("[A]", self.frame)
        self.assertIn("C4", self.frame)
        self.assertIn("^Q/^D/^C/Esc back", self.frame)

    def test_ascii_timbre_button_click(self):
        self.click_label(self.app.theme.t("freeplay.btn_timbre"))
        self.assertEqual(self.cfg.timbre, "bit")
        self.assertIn("Bit", self.frame)


if __name__ == "__main__":
    unittest.main()