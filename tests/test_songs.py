"""Song library, beatmap derivation and the pausable SongPlayer."""
from __future__ import annotations

import unittest

from tmb import songs
from tmb.audio.backends import NullBackend
from tmb.audio.engine import AudioEngine


class Library(unittest.TestCase):
    def test_at_least_six_songs(self):
        self.assertGreaterEqual(len(songs.SONGS), 6)
        self.assertEqual(len(songs.ORDER), len(songs.SONGS))
        self.assertEqual(set(songs.ORDER), set(songs.SONGS))

    def test_twinkle_is_first_and_the_default(self):
        self.assertEqual(songs.ORDER[0], "twinkle")
        self.assertEqual(songs.first_song_id(), "twinkle")
        self.assertIs(songs.get_song(None), songs.SONGS["twinkle"])
        self.assertIs(songs.get_song("no_such_song"), songs.SONGS["twinkle"])
        self.assertIs(songs.get_song("canon"), songs.SONGS["canon"])

    def test_every_song_is_well_formed(self):
        for sid in songs.ORDER:
            song = songs.SONGS[sid]
            with self.subTest(song=sid):
                self.assertEqual(song.id, sid)
                self.assertTrue(song.title_zh and song.title_en)
                self.assertNotEqual(song.title_zh, song.title_en)
                self.assertGreater(song.bpm, 0)
                self.assertGreater(len(song.notes), 4)
                times = [n.time for n in song.notes]
                self.assertEqual(times, sorted(times))
                self.assertGreaterEqual(times[0], 0.0)
                for n in song.notes:
                    self.assertGreater(n.midi, 0)
                    self.assertLess(n.midi, 128)
                    self.assertGreater(n.dur, 0.0)
                    self.assertGreater(n.vel, 0.0)
                self.assertAlmostEqual(song.duration,
                                       max(n.time + n.dur for n in song.notes))

    def test_titles_follow_language(self):
        song = songs.SONGS["twinkle"]
        self.assertEqual(song.title("zh"), song.title_zh)
        self.assertEqual(song.title("en"), song.title_en)

    def test_seq_skips_rests_but_keeps_time(self):
        notes = songs.seq([(60, 1), (0, 1), (-1, 1), (64, 2)], bpm=120)
        self.assertEqual([n.midi for n in notes], [60, 64])
        self.assertAlmostEqual(notes[0].time, 0.0)
        self.assertAlmostEqual(notes[1].time, 1.5)
        self.assertAlmostEqual(notes[0].dur, 0.5 * 0.9)
        self.assertAlmostEqual(notes[1].dur, 1.0 * 0.9)

    def test_seq_start_offset(self):
        notes = songs.seq([(60, 1)], bpm=60, start=2.0)
        self.assertAlmostEqual(notes[0].time, 2.0)


class Beatmaps(unittest.TestCase):
    def test_every_beatmap_matches_its_song(self):
        for sid in songs.ORDER:
            song = songs.SONGS[sid]
            bm = songs.get_beatmap(sid)
            with self.subTest(song=sid):
                self.assertEqual(bm.song_id, sid)
                self.assertEqual(len(bm.notes), len(song.notes))
                times = [n.time for n in bm.notes]
                self.assertEqual(times, sorted(times))
                for rn, sn in zip(bm.notes, sorted(song.notes, key=lambda n: n.time)):
                    self.assertIn(rn.lane, range(6))
                    self.assertAlmostEqual(rn.time, sn.time + 2.0)
                self.assertAlmostEqual(bm.duration, max(n.time for n in bm.notes))

    def test_beatmaps_are_pure_tap_notes(self):
        for sid in songs.ORDER:
            with self.subTest(song=sid):
                for n in songs.get_beatmap(sid).notes:
                    self.assertFalse(hasattr(n, "hold"))

    def test_all_six_lanes_are_used_somewhere(self):
        used = set()
        for sid in songs.ORDER:
            used |= {n.lane for n in songs.get_beatmap(sid).notes}
        self.assertEqual(used, set(range(6)))

    def test_beatmaps_are_cached(self):
        self.assertIs(songs.get_beatmap("twinkle"), songs.get_beatmap("twinkle"))

    def test_unknown_id_falls_back_to_first_song(self):
        bm = songs.get_beatmap("not_a_song")
        self.assertEqual(len(bm.notes), len(songs.SONGS["twinkle"].notes))

    def test_empty_song_gives_empty_beatmap(self):
        bm = songs.beatmap_from_song(songs.Song("empty", "空", "Empty", 100, []))
        self.assertEqual(bm.notes, [])
        self.assertEqual(bm.duration, 0.0)

    def test_single_pitch_song_stays_in_lane_zero(self):
        song = songs.Song("one", "一", "One", 100, songs.seq([(60, 1), (60, 1)], bpm=100))
        bm = songs.beatmap_from_song(song)
        self.assertEqual({n.lane for n in bm.notes}, {0})


class Player(unittest.TestCase):
    def setUp(self):
        self.eng = AudioEngine(backend=NullBackend(), realtime=False)
        self.song = songs.get_song("twinkle")
        self.p = songs.SongPlayer(self.eng, self.song, "harp")

    def test_start_plays_notes_as_time_passes(self):
        self.p.start()
        self.assertTrue(self.p.playing)
        self.p.update(0.5)
        self.assertAlmostEqual(self.p.pos, 0.5)
        expected = sum(1 for n in self.song.notes if n.time <= 0.5)
        self.assertEqual(self.eng.active(), expected)
        self.assertGreater(expected, 0)

    def test_pause_freezes_position_and_notes(self):
        self.p.start()
        self.p.update(0.5)
        pos, voices = self.p.pos, self.eng.active()
        self.p.pause()
        self.assertFalse(self.p.playing)
        self.p.update(2.0)
        self.assertEqual(self.p.pos, pos)
        self.assertEqual(self.eng.active(), voices)

    def test_resume_continues_from_paused_position(self):
        self.p.start()
        self.p.update(0.5)
        self.p.pause()
        self.p.update(1.0)
        self.p.resume()
        self.assertTrue(self.p.playing)
        self.p.update(0.5)
        self.assertAlmostEqual(self.p.pos, 1.0)

    def test_finishes_at_duration(self):
        self.p.start()
        for _ in range(2000):
            if self.p.finished:
                break
            self.p.update(0.05)
        self.assertTrue(self.p.finished)
        self.assertFalse(self.p.playing)
        self.assertGreaterEqual(self.p.pos, self.song.duration)
        self.assertEqual(self.p.idx, len(self.song.notes))
        self.assertEqual(self.p.progress, 1.0)
        self.assertEqual(self.eng.active(), len(self.song.notes))

    def test_resume_after_finish_does_not_restart(self):
        self.p.start()
        self.p.update(self.song.duration + 1.0)
        self.assertTrue(self.p.finished)
        self.p.resume()
        self.assertFalse(self.p.playing)

    def test_start_rewinds(self):
        self.p.start()
        self.p.update(self.song.duration + 1.0)
        self.p.start()
        self.assertEqual(self.p.pos, 0.0)
        self.assertEqual(self.p.idx, 0)
        self.assertFalse(self.p.finished)
        self.assertTrue(self.p.playing)

    def test_stop_silences_engine(self):
        self.p.start()
        self.p.update(1.0)
        self.assertGreater(self.eng.active(), 0)
        self.p.stop()
        self.assertFalse(self.p.playing)
        self.assertEqual(self.eng.active(), 0)

    def test_progress_before_start_is_zero(self):
        self.assertEqual(self.p.progress, 0.0)
        self.p.start()
        self.p.update(self.song.duration / 2)
        self.assertAlmostEqual(self.p.progress, 0.5, places=2)

    def test_set_timbre(self):
        self.p.set_timbre("bell")
        self.assertEqual(self.p.timbre, "bell")

    def test_empty_song_finishes_immediately_without_crashing(self):
        p = songs.SongPlayer(self.eng, songs.Song("e", "空", "Empty", 100, []), "harp")
        p.start()
        p.update(0.1)
        self.assertTrue(p.finished)
        self.assertEqual(p.progress, 0.0)
        self.assertEqual(self.eng.active(), 0)


if __name__ == "__main__":
    unittest.main()