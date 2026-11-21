"""Song library, beatmap derivation and the pausable SongPlayer."""
from __future__ import annotations

import unittest
from collections import Counter

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

    def test_previously_partial_songs_are_full_versions(self):
        # Ode to Joy: the complete 4-phrase theme; Jingle Bells: verse + chorus.
        self.assertGreater(songs.SONGS["ode_joy"].duration, 30)
        self.assertGreater(songs.SONGS["jingle_bells"].duration, 45)

    def test_turkish_march_is_in_the_rhythm_library(self):
        song = songs.SONGS["turkish_march"]
        self.assertIn("turkish_march", songs.RHYTHM_ORDER)
        self.assertEqual(song.title_zh, "土耳其进行曲")
        self.assertEqual(song.title_en, "Turkish March")
        self.assertEqual(song.bpm, 120)
        self.assertGreater(song.duration, 40)
        self.assertIsNone(song.timbre)

    def test_turkish_march_opens_with_the_turn_and_climbs_to_c_sharp_six(self):
        song = songs.SONGS["turkish_march"]
        self.assertEqual([n.midi for n in song.notes[:4]], [71, 69, 68, 69])
        self.assertEqual(max(n.midi for n in song.notes), 85)  # C#6, A-major episode
        self.assertEqual([n.midi for n in song.notes[-5:]],
                         [77, 74, 72, 71, 69])

    def test_only_canon_locks_a_timbre(self):
        # The rhythm game always plays canon on the didgeridoo; other songs
        # follow the user's timbre.
        self.assertEqual(songs.SONGS["canon"].timbre, "didgeridoo")
        self.assertEqual({sid for sid in songs.ORDER
                          if songs.SONGS[sid].timbre is not None}, {"canon"})

    def test_canon_is_the_complete_four_part_score(self):
        song = songs.SONGS["canon"]
        spb = 60.0 / song.bpm
        self.assertEqual(song.bpm, 55)
        self.assertEqual(len(song.notes), 1956)  # 593 + 577 + 561 + 225
        self.assertEqual(len(song.chart_notes), 593)
        self.assertAlmostEqual(song.duration, 224.9 * spb)
        self.assertEqual([n.midi for n in song.notes[:8]],
                         [48, 43, 45, 40, 41, 36, 41, 43])
        self.assertEqual([n.midi for n in song.chart_notes[:16]],
                         [76, 74, 72, 71, 69, 67, 69, 71,
                          72, 71, 69, 67, 65, 64, 65, 62])
        self.assertAlmostEqual(song.chart_notes[0].time, 8 * spb)
        final = [n.midi for n in song.notes if abs(n.time - 224 * spb) < 1e-9]
        self.assertEqual(sorted(final), [48, 67, 72, 76])
        self.assertEqual(song.title_en, "Canon in C")
        self.assertEqual(song.title_zh, "卡农")

    def test_minuet_is_the_complete_aabb_score(self):
        song = songs.SONGS["minuet_g"]
        spb = 60.0 / song.bpm
        self.assertEqual(song.bpm, 140)
        self.assertEqual(len(song.notes), 408)
        self.assertEqual(len(song.chart_notes), 274)
        self.assertAlmostEqual(song.duration, 191.9 * spb)
        self.assertEqual([n.midi for n in song.chart_notes[:17]],
                         [74, 62, 67, 69, 71, 72, 74, 67, 67,
                          76, 72, 74, 76, 78, 79, 67, 67])
        for beat, pitch in ((0, 74), (48, 74), (96, 83), (144, 83)):
            section = [n for n in song.chart_notes
                       if abs(n.time - beat * spb) < 1e-9]
            self.assertEqual(section[0].midi, pitch)
        grace_time = (20.5 + 37 / 96) * spb
        grace = next(n for n in song.chart_notes
                     if abs(n.time - grace_time) < 1e-9)
        self.assertEqual(grace.midi, 71)
        final = [n.midi for n in song.notes if abs(n.time - 189 * spb) < 1e-9]
        self.assertEqual(sorted(final), [55, 59, 62, 67])
        self.assertEqual(song.title_en, "Minuet in G")
        self.assertEqual(song.title_zh, "G 大调小步舞曲")

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
            if sid == "canon":
                continue  # canon ships an authored chart; see CanonChart
            song = songs.SONGS[sid]
            bm = songs.get_beatmap(sid)
            with self.subTest(song=sid):
                melody = song.chart_notes if song.chart_notes is not None else song.notes
                self.assertEqual(bm.song_id, sid)
                self.assertEqual(len(bm.notes), len(melody))
                times = [n.time for n in bm.notes]
                self.assertEqual(times, sorted(times))
                for rn, sn in zip(bm.notes, sorted(melody, key=lambda n: n.time)):
                    self.assertIn(rn.lane, range(6))
                    self.assertAlmostEqual(rn.time, sn.time + 2.0)
                self.assertAlmostEqual(bm.duration, max(n.time for n in bm.notes))

    def test_canon_beatmap_follows_violin_one_not_the_full_ensemble(self):
        song = songs.SONGS["canon"]
        bm = songs.get_beatmap("canon")
        self.assertEqual(len(bm.notes), 638)
        self.assertLess(len(bm.notes), len(song.notes))
        self.assertAlmostEqual(bm.notes[0].time, 8 * 60.0 / song.bpm + bm.lead_in)

    def test_minuet_beatmap_follows_the_right_hand_not_the_full_score(self):
        song = songs.SONGS["minuet_g"]
        bm = songs.get_beatmap("minuet_g")
        self.assertEqual(len(bm.notes), 274)
        self.assertLess(len(bm.notes), len(song.notes))
        self.assertAlmostEqual(bm.notes[0].time, bm.lead_in)
        self.assertAlmostEqual(bm.notes[-1].time,
                               189 * 60.0 / song.bpm + bm.lead_in)

    def test_minuet_has_twenty_double_taps_on_accents(self):
        song = songs.SONGS["minuet_g"]
        bm = songs.get_beatmap("minuet_g")
        spb = 60.0 / song.bpm
        accents = (
            (0, 74, 62), (12, 72, 69), (24, 74, 62), (36, 72, 69), (45, 67, 62),
            (48, 74, 62), (60, 72, 69), (72, 74, 62), (84, 72, 69), (93, 67, 62),
            (96, 83, 79), (108, 69, 81), (120, 74, 71), (132, 62, 74), (141, 67, 62),
            (144, 83, 79), (156, 69, 81), (168, 74, 71), (180, 62, 74), (189, 67, 62),
        )
        for beat, lead, harmony in accents:
            with self.subTest(beat=beat):
                chart_at = [n for n in song.chart_notes
                            if abs(n.time - beat * spb) < 1e-9]
                self.assertEqual([n.midi for n in chart_at], [lead, harmony])
                bm_at = [n for n in bm.notes
                         if abs(n.time - beat * spb - bm.lead_in) < 1e-9]
                self.assertEqual(len(bm_at), 2)
                self.assertEqual(len({n.lane for n in bm_at}), 2)
        simultaneous = {}
        for note in song.chart_notes:
            simultaneous.setdefault(round(note.time, 7), []).append(note)
        self.assertEqual(sum(len(notes) > 1 for notes in simultaneous.values()), 20)
        self.assertTrue(all(len(notes) <= 2 for notes in simultaneous.values()))

    def test_turkish_march_beatmap_uses_every_lane(self):
        bm = songs.get_beatmap("turkish_march")
        self.assertEqual(len(bm.notes), len(songs.SONGS["turkish_march"].notes))
        self.assertEqual({n.lane for n in bm.notes}, set(range(6)))

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


class CanonChart(unittest.TestCase):
    """The authored chart spreads streams over S D J K and accents with chords."""

    def setUp(self):
        self.song = songs.SONGS["canon"]
        self.bm = songs.get_beatmap("canon")
        self.melody = self.song.chart_notes
        self.spb = 60.0 / self.song.bpm
        self.events = {}
        for n in self.bm.notes:
            self.events.setdefault(n.time, []).append(n.lane)
        self.times = sorted(self.events)

    def gap(self, i):
        before = self.melody[i].time - self.melody[i - 1].time if i > 0 else float("inf")
        after = self.melody[i + 1].time - self.melody[i].time if i < len(self.melody) - 1 else float("inf")
        return min(before, after)

    def dense_times(self):
        return {n.time + self.bm.lead_in for i, n in enumerate(self.melody)
                if self.gap(i) <= 0.25 * self.spb + 1e-9}

    def test_every_melody_note_is_still_a_hit(self):
        self.assertEqual(set(self.times),
                         {n.time + self.bm.lead_in for n in self.melody})

    def test_chords_land_on_phrase_accents(self):
        chords = [t for t in self.times if len(self.events[t]) > 1]
        self.assertGreaterEqual(len(chords), 30)
        self.assertLessEqual(len(chords), 60)
        for t in chords:
            self.assertEqual(len(self.events[t]), 2)
            self.assertEqual(len(set(self.events[t])), 2)

    def test_dense_runs_stay_on_the_middle_four_lanes(self):
        for t in self.dense_times():
            for lane in self.events[t]:
                self.assertIn(lane, (1, 2, 3, 4))

    def test_sparse_notes_reach_the_outer_lanes(self):
        dense = self.dense_times()
        outer = {lane for t in self.times if t not in dense
                 for lane in self.events[t]}
        self.assertEqual(outer & {0, 5}, {0, 5})

    def test_no_lane_repeats_on_consecutive_hits(self):
        for a, b in zip(self.times, self.times[1:]):
            self.assertFalse(set(self.events[a]) & set(self.events[b]))

    def test_no_lane_carries_a_pile_of_a_dense_bar(self):
        for bar in range(50):
            lo = 8 * self.spb + bar * 4 * self.spb + self.bm.lead_in
            hits = [lane for t in self.times if lo <= t < lo + 4 * self.spb
                    for lane in self.events[t]]
            if len(hits) >= 16:
                self.assertLessEqual(max(hits.count(l) for l in set(hits)),
                                     len(hits) // 3)

    def test_middle_lanes_share_the_load_evenly(self):
        counts = [sum(1 for n in self.bm.notes if n.lane == l) for l in range(1, 5)]
        self.assertLess(max(counts) - min(counts), 20)

    def test_long_streams_change_their_fingering(self):
        dense = self.dense_times()
        seq = [self.events[t][0] for t in self.times if t in dense]
        windows = Counter(tuple(seq[i:i + 4]) for i in range(len(seq) - 3))
        self.assertGreater(len(windows), 40)
        self.assertLess(windows.most_common(1)[0][1] / sum(windows.values()), 0.12)

    def test_the_fastest_bursts_alternate_hands(self):
        single = {t: ls[0] for t, ls in self.events.items() if len(ls) == 1}
        idx = [i for i in range(len(self.melody))
               if self.gap(i) <= 0.125 * self.spb + 1e-9]
        pairs = [(self.melody[a].time + self.bm.lead_in,
                  self.melody[b].time + self.bm.lead_in)
                 for a, b in zip(idx, idx[1:]) if b == a + 1]
        pairs = [(a, b) for a, b in pairs if a in single and b in single]
        same = sum(1 for a, b in pairs if (single[a] < 3) == (single[b] < 3))
        self.assertLess(same / len(pairs), 0.1)

    def test_the_score_itself_is_untouched(self):
        self.assertEqual(len(self.song.notes), 1956)
        self.assertEqual(len(self.melody), 593)
        self.assertAlmostEqual(self.song.duration, 245.34545454545457)


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