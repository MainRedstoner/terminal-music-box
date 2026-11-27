"""Free play: keyboard voices, timbre cycling, prenatal mode, mouse."""
from __future__ import annotations

import unittest
from unittest import mock

from tmb import songs
from tmb.audio import synth
from tmb.events import KeyEvent
from tmb.screens.freeplay import (ACTIVITY_WINDOW, KEY_MIDI, PRELOAD_MIDIS,
                                  REPEAT_TIMEOUT, WAIT_TIMEOUT)

try:
    from tests.helpers import HeadlessCase, has_cjk
except ImportError:
    from helpers import HeadlessCase, has_cjk


def cycle_timbre(case):
    """Old ^X cycling, one step at a time through the picker.

    The picker opens preselected on the current timbre, so down+enter applies
    the next one in synth.ORDER.
    """
    case.press("ctrl+x")
    case.assertEqual(case.app.current_name, "timbre_select")
    case.press("down")
    case.press("enter")


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

    def test_key_up_accelerates_a_held_ringing_decay(self):
        self.press("a")
        voice = next(iter(self.engine._voices.values()))
        self.assertFalse(voice._sustain)
        self.assertEqual(voice._decay, 1.0)  # harp defaults to natural length
        self.release("a")
        self.assertEqual(self.screen.key_down, {})
        self.assertEqual(self.engine.active(), 1)  # still decaying, not cut
        self.assertLess(voice._decay, 1.0)

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

    def test_holding_two_keys_keeps_the_first_one_sounding(self):
        self.cfg.timbre = "bit"
        self.press("a")
        self.press("s")
        # Auto-repeat follows only the most recently pressed key, so the first
        # key goes silent while it is still held down. That silence must not
        # be mistaken for a lost release.
        rf = self.app.render_frames
        self.app.render_frames = False
        try:
            for _ in range(60):  # 3 s, well past the old 2 s stuck timeout
                self.term.send(KeyEvent("s", pressed=True, repeat=True))
                self.app.step(0.05)
        finally:
            self.app.render_frames = rf
        self.assertTrue(self.screen.key_down.get("a"))
        self.assertTrue(self.screen.key_down.get("s"))
        self.assertEqual(set(self.screen.key_voice), {"a", "s"})
        self.assertEqual(self.engine.active(), 2)

    def test_a_held_key_survives_without_repeat_events(self):
        self.cfg.timbre = "bit"
        self.press("a")
        self.advance(3.0, dt=0.05)
        # With real key-up events, silence is not evidence of a release: only
        # the key-up ends the voice. (Leaving the screen or switching timbre
        # clears a genuinely lost release.)
        self.assertTrue(self.screen.key_down.get("a"))
        self.assertIn("a", self.screen.key_voice)
        self.assertEqual(self.engine.active(), 1)
        self.release("a")
        self.assertEqual(self.screen.key_down, {})
        self.assertEqual(self.screen.key_voice, {})

    def test_repeat_events_never_retrigger_a_note(self):
        self.press("a")
        self.term.send(KeyEvent("a", pressed=True, repeat=True))
        self.step()
        self.advance(0.5)
        self.term.send(KeyEvent("a", pressed=True, repeat=True))
        self.step()
        self.assertEqual(self.engine.active(), 1)
        self.assertTrue(self.screen.key_down.get("a"))

    def test_held_ringing_note_uses_the_selected_length(self):
        self.cfg.set_sound("harp", ln=0.5)
        self.press("a")
        voice = next(iter(self.engine._voices.values()))
        self.assertFalse(voice._sustain)
        self.assertLess(voice._decay, 1.0)  # decays at the 0.5x length
        self.advance(1.0)
        self.assertEqual(self.engine.active(), 1)  # still sounding while held
        self.release("a")
        self.assertNotIn("a", self.screen.key_voice)

    def test_non_hold_ringing_timbres_stay_one_shots(self):
        self.cfg.timbre = "guitar"
        self.press("a")
        voice = next(iter(self.engine._voices.values()))
        self.assertNotIn("a", self.screen.key_voice)  # no key-up release path
        self.assertEqual([loop for _, loop in voice._segments], [False])
        self.release("a")
        self.assertEqual(self.engine.active(), 1)  # plays its natural tail

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

    def test_ctrl_x_opens_the_searchable_timbre_picker(self):
        self.press("ctrl+x")
        self.assertEqual(self.app.current_name, "timbre_select")
        s = self.screen
        self.assertEqual(s.items,
                         [synth.timbre_name(t, "zh") for t in synth.ORDER])
        self.assertEqual(s.index, synth.ORDER.index("harp"))
        # picking applies the timbre, persists it and returns to free play
        self.press("down")
        self.press("enter")
        self.assertEqual(self.cfg.timbre, synth.ORDER[1])
        self.assertEqual(self.read_config()["timbre"], synth.ORDER[1])
        self.assertEqual(self.app.current_name, "freeplay")
        self.assertIn(synth.timbre_name(synth.ORDER[1], "zh"), self.frame)

    def test_ctrl_t_starts_prenatal_with_default_song(self):
        self.press("ctrl+t")
        p = self.screen.player
        self.assertIsNotNone(p)
        self.assertTrue(self.screen.prenatal)
        self.assertEqual(p.song.id, songs.RHYTHM_ORDER[0])
        self.assertIn(p.song.title("zh"), self.frame)
        self.assertIn(self.app.theme.t("freeplay.prenatal_hint"), self.frame)
        # Enabling prenatal must not start the melody on its own: it stays
        # silent until the first play key (the same press that keeps it alive).
        self.step()  # the frame after the toggle applies the silent gate
        self.assertFalse(p.playing)
        self.assertEqual(self.engine.active(), 0)
        self.press("q")
        self.step()
        self.assertTrue(p.playing)

    def test_ctrl_t_uses_the_configured_song(self):
        self.cfg.prenatal_song = "canon"
        self.press("ctrl+t")
        self.assertEqual(self.screen.player.song.id, "canon")

    def test_ctrl_t_with_a_song_outside_the_rhythm_list_falls_back(self):
        self.cfg.prenatal_song = "twinkle"  # a retired id still in old configs
        self.press("ctrl+t")
        self.assertEqual(self.screen.player.song.id, songs.RHYTHM_ORDER[0])

    def test_ctrl_t_toggles_off_and_silences(self):
        self.press("ctrl+t")
        self.press("q")  # the silent-started melody needs a play key first
        self.advance(0.5)
        self.assertGreater(self.engine.active(), 0)
        self.press("ctrl+t")
        self.assertIsNone(self.screen.player)
        self.assertFalse(self.screen.prenatal)
        self.assertEqual(self.engine.active(), 0)

    def test_ctrl_x_updates_the_player_timbre(self):
        self.press("ctrl+t")
        p = self.screen.player
        self.press("ctrl+x")  # the picker keeps the prenatal player alive
        self.assertEqual(self.app.current_name, "timbre_select")
        self.assertIs(self.app._screens["freeplay"].player, p)
        self.press("down")
        self.press("enter")
        self.assertEqual(self.app.current_name, "freeplay")
        self.assertIs(self.screen.player, p)
        self.assertEqual(p.timbre, self.cfg.timbre)

    def test_prenatal_plays_the_song_locked_timbre(self):
        # Same score, same locked timbre as the rhythm game: Canon keeps its
        # didgeridoo even though free play is set to the harp. The header must
        # name the timbre that is actually sounding.
        self.cfg.timbre = "harp"
        self.cfg.prenatal_song = "canon"
        self.press("ctrl+t")
        self.assertEqual(self.screen.player.timbre, "didgeridoo")
        self.assertIn(synth.timbre_name("didgeridoo", "zh"), self.frame)
        self.assertNotIn(synth.timbre_name("harp", "zh"), self.frame)

    def test_prenatal_song_change_follows_the_new_locked_timbre(self):
        self.press("ctrl+t")
        self.assertEqual(self.screen.player.timbre, "didgeridoo")
        self.press("ctrl+a")
        self.press("down")  # canon -> minuet_g
        self.press("enter")
        self.assertEqual(self.screen.player.song.id, "minuet_g")
        self.assertEqual(self.screen.player.timbre, "pling")

    def test_prenatal_pauses_after_the_activity_window(self):
        self.press("ctrl+t")
        p = self.screen.player
        self.press("q")  # the melody starts silent; a play key starts it
        self.step()
        self.assertTrue(p.playing)
        self.advance(ACTIVITY_WINDOW + 0.1, dt=0.05)
        self.assertFalse(p.playing)
        pos = p.pos
        self.advance(1.0, dt=0.05)
        self.assertEqual(p.pos, pos)

    def test_prenatal_resumes_on_a_play_key(self):
        self.press("ctrl+t")
        p = self.screen.player
        self.press("q")  # the melody starts silent; a play key starts it
        self.step()
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
        rf = self.app.render_frames
        self.app.render_frames = False
        try:
            for i in range(int((duration + 3.0) / 0.05)):
                self.step(0.05)
                if i % 10 == 0:
                    self.term.key("q")
                if p.pos < prev - 1.0:
                    wrapped = True
                prev = p.pos
        finally:
            self.app.render_frames = rf
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
        self.assertEqual(self.cfg.prenatal_song, "turkish_march")
        self.assertEqual(self.read_config()["prenatal_song"], "turkish_march")
        self.assertEqual(self.screen.player.song.id, "turkish_march")
        # A song change restarts the player, but silent, like a fresh start.
        self.step()  # the frame after the pick applies the silent gate
        self.assertFalse(self.screen.player.playing)
        self.press("q")
        self.step()
        self.assertTrue(self.screen.player.playing)

    def test_ctrl_a_without_prenatal_is_ignored(self):
        # ^A picks the prenatal song, so with prenatal mode off it must not
        # even open the picker — matching the song button, which only shows
        # while prenatal mode is on.
        self.press("ctrl+a")
        self.assertEqual(self.app.current_name, "freeplay")
        self.assertIsNone(self.cfg.prenatal_song)
        self.assertIsNone(self.screen.player)
        # The default fallback still applies when prenatal starts later.
        self.press("ctrl+t")
        self.assertEqual(self.screen.player.song.id, songs.RHYTHM_ORDER[0])

    def test_song_select_mouse_click_picks_a_song(self):
        self.press("ctrl+t")  # ^A needs prenatal on to reach the picker
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

    def test_mouse_click_on_timbre_button_opens_the_picker(self):
        self.click_label(self.app.theme.t("freeplay.btn_timbre"))
        self.assertEqual(self.app.current_name, "timbre_select")
        self.press("down")
        self.press("enter")
        self.assertEqual(self.cfg.timbre, "bit")
        self.assertEqual(self.read_config()["timbre"], "bit")

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


class PrenatalPreload(HeadlessCase):
    """Prenatal playback waits for the selected song's own pitch set.

    The free-play preload covers 21 keyboard keys only, while prenatal mode
    auto-plays a song's complete score — which reaches outside that range
    (Canon's bass line, Für Elise's top octave). A cold (timbre, midi) render
    runs inline in the UI thread, so starting early freezes a frame and fires
    the note late; the screen must wait for the background preload instead.
    """

    start_screen = "freeplay"

    def setUp(self):
        super().setUp()
        # The gate is armed only when a real playback thread exists; headless
        # runs keep starting immediately (see test_headless_runs_skip_the_gate).
        self.engine.realtime = True
        self.engine.preload = mock.Mock()
        self.engine.is_preloaded = mock.Mock(return_value=False)
        self.engine.preload_status = mock.Mock(return_value=(True, 0, 8))

    def requested(self):
        tid, midis = self.engine.preload.call_args[0]
        return tid, list(midis)

    def test_starting_prenatal_waits_for_the_configured_song(self):
        self.cfg.prenatal_song = "fur_elise"
        self.press("ctrl+t")
        p = self.screen.player
        self.assertEqual(p.song.id, "fur_elise")
        self.assertTrue(self.screen._waiting)
        self.assertFalse(p.playing)
        tid, midis = self.requested()
        # Prenatal auto-play carries the song's locked timbre, exactly like
        # the rhythm game, so the same score sounds the same on both screens.
        self.assertEqual(tid, songs.SONGS["fur_elise"].timbre)
        self.assertLessEqual(set(songs.SONGS["fur_elise"].pitches), set(midis))

    def test_playback_starts_at_the_top_once_the_buffers_land(self):
        self.cfg.prenatal_song = "fur_elise"
        self.press("ctrl+t")
        p = self.screen.player
        self.press("q")  # a key press must not force a cold start
        self.assertFalse(p.playing)
        self.engine.is_preloaded.return_value = True
        self.engine.preload_status.return_value = (False, 8, 8)
        self.step()
        self.assertTrue(p.playing)
        self.assertFalse(self.screen._waiting)
        self.assertLess(p.pos, 0.05)

    def test_every_prenatal_song_is_preloaded_whole(self):
        for sid in songs.RHYTHM_ORDER:
            with self.subTest(song=sid):
                self.engine.preload.reset_mock()
                self.app.navigate("freeplay")
                self.cfg.prenatal_song = sid
                self.press("ctrl+t")
                tid, midis = self.requested()
                self.assertEqual(tid, songs.SONGS[sid].timbre)
                self.assertEqual(self.screen.player.song.id, sid)
                # The song's complete score, not just the 21 keyboard keys.
                self.assertLessEqual(set(songs.SONGS[sid].pitches), set(midis))
                # ...and the keyboard stays warm from the same request.
                self.assertLessEqual(set(PRELOAD_MIDIS), set(midis))

    def test_the_gate_covers_the_whole_request_not_just_the_song(self):
        self.cfg.prenatal_song = "canon"
        self.press("ctrl+t")
        tid, midis = self.requested()
        # Prenatal locks the song's timbre, like the rhythm game does.
        self.assertEqual(tid, songs.SONGS["canon"].timbre or self.cfg.timbre)
        # The request holds the whole score and the keyboard keys after it.
        self.assertLessEqual(set(songs.SONGS["canon"].pitches), set(midis))
        self.assertLessEqual(set(PRELOAD_MIDIS), set(midis))
        # ...and the gate inspects that same set, not only the song's pitches
        # (Canon never plays D3 or E3, so it cannot warm those keys itself).
        checked = set()
        for call in self.engine.is_preloaded.call_args_list:
            checked.update(call[0][1])
        self.assertLessEqual(set(PRELOAD_MIDIS), checked)

    def test_a_stale_selection_preloads_the_fallback_song(self):
        self.cfg.prenatal_song = "twinkle"  # a retired id still in old configs
        self.press("ctrl+t")
        p = self.screen.player
        self.assertEqual(p.song.id, songs.RHYTHM_ORDER[0])
        tid, midis = self.requested()
        self.assertEqual(tid, songs.SONGS[songs.RHYTHM_ORDER[0]].timbre)
        self.assertLessEqual(set(p.song.pitches), set(midis))

    def test_switching_timbre_mid_song_reloads_and_resumes_in_place(self):
        self.engine.is_preloaded.return_value = True
        self.engine.preload_status.return_value = (False, 8, 8)
        self.press("ctrl+t")
        p = self.screen.player
        self.press("q")  # the melody starts silent; a play key starts it
        self.step()
        self.assertTrue(p.playing)
        self.advance(0.5)
        pos = p.pos
        self.assertGreater(pos, 0.4)
        self.engine.preload.reset_mock()
        self.engine.is_preloaded.return_value = False
        self.engine.preload_status.return_value = (True, 0, 8)
        cycle_timbre(self)
        self.assertEqual(p.timbre, self.cfg.timbre)
        self.assertEqual(p.timbre, "bit")
        self.assertTrue(self.screen._waiting)
        self.assertFalse(p.playing)
        self.assertGreaterEqual(p.pos, pos)  # parked mid-phrase, not rewound
        self.assertEqual(self.engine.preload.call_args[0][0], "bit")
        self.engine.is_preloaded.return_value = True
        self.step()
        self.assertTrue(p.playing)
        self.assertGreater(p.pos, pos)

    def test_picking_a_new_song_waits_for_its_buffers(self):
        self.engine.is_preloaded.return_value = True
        self.press("ctrl+t")
        self.press("q")  # the melody starts silent; a play key starts it
        self.step()
        self.assertTrue(self.screen.player.playing)
        self.engine.preload.reset_mock()
        self.engine.is_preloaded.return_value = False
        self.press("ctrl+a")
        self.assertEqual(self.app.current_name, "song_select")
        self.press("enter")
        self.assertEqual(self.app.current_name, "freeplay")
        p = self.screen.player
        self.assertEqual(p.song.id, songs.RHYTHM_ORDER[0])
        self.assertTrue(self.screen._waiting)
        self.assertFalse(p.playing)
        tid, midis = self.requested()
        self.assertEqual(tid, songs.SONGS[songs.RHYTHM_ORDER[0]].timbre)
        self.assertLessEqual(set(p.song.pitches), set(midis))

    def test_song_loop_regates_a_cold_cache(self):
        self.engine.is_preloaded.return_value = True
        self.cfg.prenatal_song = "minuet_g"
        self.press("ctrl+t")
        p = self.screen.player
        duration = p.song.duration
        flipped = False
        for _ in range(int((duration + 2.0) / 0.05)):
            if not flipped and p.pos > duration - 0.3:
                # Something (the rhythm game, a timbre switch) evicted the
                # buffers while the song was playing: the loop must not start
                # cold again.
                self.engine.preload.reset_mock()
                self.engine.is_preloaded.return_value = False
                self.engine.preload_status.return_value = (True, 0, 4)
                flipped = True
            self.step(0.05)
            self.term.key("q")  # keep the 2 s activity window open
            if self.screen._waiting:
                break
        self.assertTrue(flipped)
        self.assertTrue(self.screen._waiting)
        self.assertFalse(p.playing)
        self.assertEqual(p.pos, 0.0)
        self.engine.preload.assert_called()

    def test_a_superseded_request_is_reissued(self):
        self.cfg.prenatal_song = "fur_elise"
        self.press("ctrl+t")
        self.assertTrue(self.screen._waiting)
        self.assertEqual(self.engine.preload.call_count, 1)
        # Another screen's preload superseded ours and finished without the
        # song: the gate must re-ask instead of waiting forever.
        self.engine.preload_status.return_value = (False, 5, 5)
        self.step()
        self.assertEqual(self.engine.preload.call_count, 2)
        self.assertTrue(self.screen._waiting)

    def test_a_wedged_preload_falls_back_to_playing(self):
        self.cfg.prenatal_song = "fur_elise"
        self.press("ctrl+t")
        p = self.screen.player
        self.assertFalse(p.playing)
        self.advance(WAIT_TIMEOUT + 1.0)
        # The wait gives up instead of wedging forever, but playback still
        # starts only on a play key.
        self.assertFalse(self.screen._waiting)
        self.assertFalse(p.playing)
        self.press("q")
        self.step()
        self.assertTrue(p.playing)

    def test_the_wait_survives_the_song_picker(self):
        self.press("ctrl+t")
        fp = self.screen
        player = fp.player
        self.assertTrue(fp._waiting)
        self.press("ctrl+a")
        self.press("esc")
        self.assertEqual(self.app.current_name, "freeplay")
        self.assertIs(self.screen.player, player)  # the picker keeps the player
        self.assertTrue(self.screen._waiting)
        self.engine.is_preloaded.return_value = True
        self.step()
        self.assertFalse(self.screen._waiting)
        # Buffers landed, but no play key yet: still silent.
        self.assertFalse(player.playing)
        self.press("q")
        self.step()
        self.assertTrue(player.playing)

    def test_toggling_off_while_waiting_stops_cleanly(self):
        self.cfg.prenatal_song = "fur_elise"
        self.press("ctrl+t")
        self.assertTrue(self.screen._waiting)
        self.press("ctrl+t")
        self.assertIsNone(self.screen.player)
        self.assertFalse(self.screen._waiting)
        self.assertFalse(self.screen.prenatal)
        self.assertEqual(self.engine.active(), 0)

    def test_headless_runs_skip_the_gate(self):
        self.engine.realtime = False
        self.cfg.prenatal_song = "fur_elise"
        self.press("ctrl+t")
        self.assertFalse(self.screen._waiting)
        self.engine.preload.assert_not_called()
        # The silent start applies to headless runs too.
        self.step()
        self.assertFalse(self.screen.player.playing)
        self.press("q")
        self.step()
        self.assertTrue(self.screen.player.playing)


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
        cycle_timbre(self)  # harp -> bit -> flute (sustained), via the picker
        cycle_timbre(self)
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
        cycle_timbre(self)  # -> bit, with its 0.25x default
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
        self.assertEqual(self.app.current_name, "timbre_select")
        self.press("down")
        self.press("enter")
        self.assertEqual(self.cfg.timbre, "bit")
        self.assertIn("Bit", self.frame)


class FreePlayColdKey(HeadlessCase):
    """A cold key must not render inline in the UI thread."""

    start_screen = "freeplay"

    def setUp(self):
        super().setUp()
        self.engine.realtime = True
        self.engine.is_preloaded = mock.Mock(return_value=False)
        self.engine.preload = mock.Mock()
        self.engine.preload_status = mock.Mock(return_value=(False, 0, 0))
        self.engine.play_note = mock.Mock()
        self.engine.note_on = mock.Mock()

    def voiced(self) -> int:
        return self.engine.play_note.call_count + self.engine.note_on.call_count

    def test_a_cold_key_requests_its_buffer_and_skips_the_note(self):
        self.press("q")
        self.assertEqual(self.voiced(), 0)
        tid, midis = self.engine.preload.call_args[0]
        self.assertEqual(tid, self.cfg.timbre)
        self.assertIn(KEY_MIDI["q"], list(midis))

    def test_a_cold_key_rearms_the_whole_keyboard(self):
        # A single-key request would supersede enter()'s 21-key batch and the
        # other keys would stay cold for the rest of the session.
        self.press("q")
        self.assertEqual(self.voiced(), 0)
        self.engine.preload.assert_called_once_with(self.cfg.timbre,
                                                    PRELOAD_MIDIS)

    def test_a_cold_key_does_not_supersede_a_running_request(self):
        self.engine.preload_status.return_value = (True, 0, 21)
        self.press("q")
        self.engine.preload.assert_not_called()
        self.assertEqual(self.voiced(), 0)

    def test_a_warm_key_plays(self):
        self.engine.is_preloaded.return_value = True
        self.press("q")
        # Harp is a holdable ringing timbre, so a warm press starts a voice
        # through note_on; play_note is the fixed-length path. Either is fine,
        # exactly one must fire (the point is that the press is not dropped).
        self.assertEqual(self.voiced(), 1)

    def test_entering_freeplay_rearms_the_keyboard_preload(self):
        self.engine.preload.reset_mock()
        self.app.navigate("freeplay")
        self.engine.preload.assert_called_once_with(self.cfg.timbre, PRELOAD_MIDIS)


if __name__ == "__main__":
    unittest.main()