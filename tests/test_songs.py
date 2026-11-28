"""Song library, beatmap derivation and the pausable SongPlayer."""
from __future__ import annotations

import itertools
import unittest
from collections import Counter

from tmb import songs
from tmb.audio.backends import NullBackend
from tmb.audio.engine import AudioEngine


class Library(unittest.TestCase):
    def test_the_library_is_exactly_the_rhythm_list(self):
        self.assertGreaterEqual(len(songs.SONGS), 4)
        self.assertEqual(songs.ORDER, songs.RHYTHM_ORDER)
        self.assertEqual(len(songs.ORDER), len(songs.SONGS))
        self.assertEqual(set(songs.ORDER), set(songs.SONGS))

    def test_canon_is_first_and_the_default(self):
        self.assertEqual(songs.ORDER[0], "canon")
        self.assertEqual(songs.first_song_id(), "canon")
        self.assertIs(songs.get_song(None), songs.SONGS["canon"])
        self.assertIs(songs.get_song("no_such_song"), songs.SONGS["canon"])

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
        song = songs.SONGS["canon"]
        self.assertEqual(song.title("zh"), song.title_zh)
        self.assertEqual(song.title("en"), song.title_en)

    def test_turkish_march_is_the_complete_rondo(self):
        song = songs.SONGS["turkish_march"]
        self.assertIn("turkish_march", songs.RHYTHM_ORDER)
        self.assertEqual(song.title_zh, "土耳其进行曲")
        self.assertEqual(song.title_en, "Turkish March")
        self.assertEqual(song.bpm, 120)
        self.assertGreater(song.duration, 120)
        self.assertEqual(len(song.notes), 1442)       # both piano hands
        self.assertEqual(len(song.chart_notes), 604)  # right-hand top line
        self.assertEqual(song.timbre, "pling")

    def test_turkish_march_opens_with_the_turn_and_reaches_e6(self):
        song = songs.SONGS["turkish_march"]
        self.assertEqual([n.midi for n in song.chart_notes[:4]],
                         [71, 69, 68, 69])
        self.assertEqual(min(n.midi for n in song.chart_notes), 64)
        self.assertEqual(max(n.midi for n in song.chart_notes), 88)  # E6, coda
        self.assertEqual([n.midi for n in song.chart_notes[-5:]],
                         [81, 88, 81, 81, 81])

    def test_rhythm_songs_lock_their_timbres(self):
        # Canon sounds on the didgeridoo; Turkish March, Minuet in G, and
        # Für Elise on the electric piano. Every other song follows the
        # user's timbre.
        self.assertEqual(songs.SONGS["canon"].timbre, "didgeridoo")
        self.assertEqual(songs.SONGS["turkish_march"].timbre, "pling")
        self.assertEqual(songs.SONGS["minuet_g"].timbre, "pling")
        self.assertEqual(songs.SONGS["fur_elise"].timbre, "pling")
        self.assertEqual({sid for sid in songs.ORDER
                          if songs.SONGS[sid].timbre is not None},
                         {"canon", "minuet_g", "turkish_march",
                          "fur_elise"})

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

    def test_fur_elise_is_the_complete_expanded_piano_score(self):
        song = songs.SONGS["fur_elise"]
        self.assertEqual(song.bpm, 60)
        self.assertEqual(len(song.notes), 1041)  # 605 right-hand + 436 left-hand
        self.assertEqual(len(song.chart_notes), 594)  # 551 onsets + 43 double taps
        self.assertEqual(len(song.chart_lanes), len(song.chart_notes))
        self.assertAlmostEqual(song.duration, 189.5)
        self.assertEqual(min(n.midi for n in song.notes), 33)
        self.assertEqual(max(n.midi for n in song.notes), 100)
        self.assertEqual([n.midi for n in song.chart_notes[:9]],
                         [76, 75, 76, 75, 76, 71, 74, 72, 69])
        lead_pitches = {}
        for note in song.chart_notes:
            lead_pitches[note.time] = max(lead_pitches.get(note.time, 0),
                                          note.midi)
        self.assertEqual(min(lead_pitches.values()), 57)
        self.assertEqual(max(lead_pitches.values()), 100)

        def pitches_at(notes, beat):
            return [n.midi for n in notes if abs(n.time - beat) < 1e-9]

        # Both printed A and B repeats, the F/C episodes, and the final A.
        for beat in (0, 12, 25.5, 46.5, 157.5):
            self.assertEqual(pitches_at(song.chart_notes, beat), [76])
        self.assertEqual(pitches_at(song.chart_notes, 69), [72])
        self.assertEqual(sorted(pitches_at(song.notes, 124.5)),
                         [45, 64, 67, 70, 73])
        self.assertEqual(sorted(pitches_at(song.notes, 189)), [33, 45, 69])
        self.assertEqual(song.title_en, "Für Elise")
        self.assertEqual(song.title_zh, "致爱丽丝")

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

    def test_seq_takes_per_note_velocity(self):
        notes = songs.seq([(60, 1), (62, 1, 0.5), (64, 2)], bpm=120)
        self.assertEqual([n.vel for n in notes], [1.0, 0.5, 1.0])

    def test_timed_takes_per_note_velocity(self):
        notes = songs.timed([(0, 60, 4), (4, 62, 4, 0.5)], bpm=120)
        self.assertEqual([n.vel for n in notes], [1.0, 0.5])

    def test_dynamics_follow_the_source_editions(self):
        # The numeric scores carry exactly the dynamics their source notates:
        # the two Baroque pieces have none, Für Elise is pp throughout, and
        # the Turkish March follows the Mutopia typeset's dynamics voice.
        for sid in ("canon", "minuet_g"):
            song = songs.SONGS[sid]
            with self.subTest(song=sid):
                self.assertTrue(all(n.vel == 1.0 for n in song.notes))
        fur = songs.SONGS["fur_elise"]
        self.assertTrue(all(abs(n.vel - songs.DYNAMIC_LEVELS["pp"]) < 1e-9
                            for n in fur.notes))
        turkish = songs.SONGS["turkish_march"]
        spb = 60.0 / turkish.bpm

        def vel_at(beat):
            return {round(n.vel, 6) for n in turkish.notes
                    if abs(n.time - beat * spb) < 1e-9}

        self.assertEqual(vel_at(0), {songs.DYNAMIC_LEVELS["p"]})
        self.assertEqual(vel_at(16), {songs.DYNAMIC_LEVELS["mp"]})
        self.assertEqual(vel_at(48), {songs.DYNAMIC_LEVELS["f"]})
        self.assertEqual(vel_at(128), {songs.DYNAMIC_LEVELS["p"]})
        # The coda's echo arpeggios soften before the closing chords.
        self.assertEqual(vel_at(218), {songs.DYNAMIC_LEVELS["p"]})
        self.assertEqual(vel_at(232), {songs.DYNAMIC_LEVELS["f"]})
        self.assertEqual(vel_at(254), {songs.DYNAMIC_LEVELS["ff"]})
        # A hairpin interpolates between the levels in force.
        inside = next(iter(vel_at(70)))
        self.assertBetween(inside, songs.DYNAMIC_LEVELS["p"],
                           songs.DYNAMIC_LEVELS["mp"])

    def assertBetween(self, value, low, high):
        self.assertGreater(value, low)
        self.assertLess(value, high)


class Dynamics(unittest.TestCase):
    """apply_dynamics transcribes a source edition's markings."""

    def song(self, beats):
        items = [(60 + k, b) for k, b in enumerate(beats)]
        return songs.seq(items, bpm=60)  # 1 beat per second

    def test_steps_hold_from_their_beat_on(self):
        notes = self.song([1, 1, 1, 1])
        songs.apply_dynamics(notes, 60, [(2.0, "p")])
        self.assertEqual([n.vel for n in notes],
                         [1.0, 1.0, songs.DYNAMIC_LEVELS["p"],
                          songs.DYNAMIC_LEVELS["p"]])

    def test_ramps_interpolate_between_levels(self):
        notes = self.song([1, 1, 1, 1, 1])
        songs.apply_dynamics(notes, 60, [(1.0, "f", 3.0), (3.0, "p")])
        self.assertAlmostEqual(notes[0].vel, 1.0)
        self.assertAlmostEqual(notes[1].vel, 1.0)
        self.assertAlmostEqual(notes[2].vel,
                               (1.0 + songs.DYNAMIC_LEVELS["f"]) / 2)
        # The step that ends a hairpin wins at the shared beat.
        self.assertAlmostEqual(notes[3].vel, songs.DYNAMIC_LEVELS["p"])
        self.assertAlmostEqual(notes[4].vel, songs.DYNAMIC_LEVELS["p"])

    def test_notes_before_the_first_marking_play_at_base(self):
        notes = self.song([1, 1, 1])
        songs.apply_dynamics(notes, 60, [(2.0, "pp")])
        self.assertEqual(notes[0].vel, 1.0)
        self.assertEqual(notes[1].vel, 1.0)
        self.assertEqual(notes[2].vel, songs.DYNAMIC_LEVELS["pp"])

    def test_marks_do_not_move_times_or_pitches(self):
        notes = self.song([1, 1, 1])
        times = [n.time for n in notes]
        songs.apply_dynamics(notes, 60, [(0.0, "f"), (2.0, "pp")])
        self.assertEqual([n.time for n in notes], times)
        self.assertEqual([n.midi for n in notes], [60, 61, 62])


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
                if sid == "turkish_march":
                    # The chart taps the eighth-note skeleton of the right hand,
                    # so it is a subset of the written line, not a copy of it.
                    self.assertGreater(len(bm.notes), 400)
                    self.assertLess(len(bm.notes), len(melody))
                else:
                    self.assertEqual(len(bm.notes), len(melody))
                # Accent chords repeat a melody time; no chart note may drift.
                chart_times = {round(n.time, 9) for n in bm.notes}
                melody_times = {round(n.time + 2.0, 9) for n in melody}
                self.assertTrue(chart_times <= melody_times)
                times = [n.time for n in bm.notes]
                self.assertEqual(times, sorted(times))
                for rn in bm.notes:
                    self.assertIn(rn.lane, range(6))
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
        song = songs.SONGS["turkish_march"]
        bm = songs.get_beatmap("turkish_march")
        self.assertGreater(len(bm.notes), 400)
        self.assertLess(len(bm.notes), len(song.chart_notes))
        self.assertEqual({n.lane for n in bm.notes}, set(range(6)))

    def test_turkish_march_chart_taps_the_eighth_note_skeleton(self):
        song = songs.SONGS["turkish_march"]
        bm = songs.get_beatmap("turkish_march")
        eighth = 30.0 / song.bpm
        for rn in bm.notes:
            grid = (rn.time - bm.lead_in) / eighth
            with self.subTest(time=rn.time):
                self.assertAlmostEqual(grid, round(grid), places=6)
        written = {round(n.time + bm.lead_in, 6) for n in song.chart_notes}
        chart = {round(n.time, 6) for n in bm.notes}
        self.assertTrue(chart <= written)

    def test_turkish_march_adds_accent_chords(self):
        song = songs.SONGS["turkish_march"]
        lanes, chords = songs._turkish_lane_plan(song.chart_notes, song.bpm)
        self.assertGreaterEqual(len(chords), 20)
        for i, companion in chords:
            self.assertIn(companion, range(6))
            self.assertNotEqual(companion, lanes[i])

    def test_turkish_march_dense_notes_stay_off_the_outer_lanes(self):
        song = songs.SONGS["turkish_march"]
        bm = songs.get_beatmap("turkish_march")
        times = [n.time for n in song.chart_notes]
        dense_gap = 0.25 * 60.0 / song.bpm
        dense_times = set()
        for i in range(len(times)):
            prev = times[i] - times[i - 1] if i else float("inf")
            nxt = (times[i + 1] - times[i]
                   if i + 1 < len(times) else float("inf"))
            if min(prev, nxt) <= dense_gap:
                dense_times.add(round(times[i] + bm.lead_in, 6))
        self.assertGreater(len(dense_times), 300)
        for rn in bm.notes:
            if round(rn.time, 6) in dense_times:
                self.assertIn(rn.lane, (1, 2, 3, 4))

    def test_turkish_march_repeated_notes_change_lanes(self):
        song = songs.SONGS["turkish_march"]
        lanes, _chords = songs._turkish_lane_plan(song.chart_notes, song.bpm)
        longest = max(len(list(g)) for _, g in itertools.groupby(lanes))
        self.assertLessEqual(longest, 2)

    def test_turkish_march_dense_runs_change_lanes(self):
        song = songs.SONGS["turkish_march"]
        lanes, _chords = songs._turkish_lane_plan(song.chart_notes, song.bpm)
        notes = song.chart_notes
        times = [n.time for n in notes]
        dense_gap = 0.25 * 60.0 / song.bpm
        dense = []
        for i in range(len(notes)):
            prev = times[i] - times[i - 1] if i else float("inf")
            nxt = (times[i + 1] - times[i]
                   if i + 1 < len(times) else float("inf"))
            dense.append(min(prev, nxt) <= dense_gap)
        runs = []
        i = 0
        while i < len(notes):
            if not dense[i]:
                i += 1
                continue
            j = i + 1
            while j < len(notes) and dense[j]:
                j += 1
            runs.append(lanes[i:j])
            i = j
        long_runs = [run for run in runs if len(run) >= 4]
        self.assertGreater(len(long_runs), 0)
        for run in long_runs:
            self.assertGreaterEqual(len(set(run)), 2)
            longest = max(len(list(g)) for _, g in itertools.groupby(run))
            self.assertLessEqual(longest, 2)

    def test_fur_elise_beatmap_is_balanced_and_uses_double_taps(self):
        song = songs.SONGS["fur_elise"]
        bm = songs.get_beatmap("fur_elise")
        self.assertEqual(len(bm.notes), 594)
        self.assertLess(len(bm.notes), len(song.notes))
        self.assertEqual({n.lane for n in bm.notes}, set(range(6)))
        self.assertAlmostEqual(bm.notes[0].time, 2.0)
        self.assertAlmostEqual(bm.notes[-1].time, 191.0)
        self.assertAlmostEqual(song.chart_notes[-1].time, 189.0)
        self.assertGreater(song.duration, song.chart_notes[-1].time)

        by_time = {}
        for note in bm.notes:
            by_time.setdefault(note.time, set()).add(note.lane)
        self.assertEqual(len(by_time), 551)
        doubles = [lanes for lanes in by_time.values() if len(lanes) > 1]
        self.assertEqual(len(doubles), 43)
        for lanes in doubles:
            self.assertEqual(len(lanes), 2)

        loads = [sum(1 for n in bm.notes if n.lane == lane) for lane in range(6)]
        # Eighth notes and faster stay on the middle four keys, so those carry
        # the chart and must stay even; the outer two take only isolated long
        # notes, which keeps a hand from stretching for A or L mid-run.
        inner = loads[1:5]
        self.assertLessEqual(max(inner) - min(inner), 30)
        self.assertGreaterEqual(min(inner), 110)
        outer = loads[0] + loads[5]
        self.assertGreater(outer, 0)
        self.assertLessEqual(outer / len(bm.notes), 0.15)

        # No lane may appear on three consecutive onsets.
        timeline = [by_time[t] for t in sorted(by_time)]
        for earlier, middle, later in zip(timeline, timeline[1:], timeline[2:]):
            self.assertFalse(earlier & middle & later)

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
        self.assertIs(songs.get_beatmap("canon"), songs.get_beatmap("canon"))

    def test_unknown_id_falls_back_to_first_song(self):
        bm = songs.get_beatmap("not_a_song")
        self.assertEqual(bm.song_id, songs.first_song_id())

    def test_empty_song_gives_empty_beatmap(self):
        bm = songs.beatmap_from_song(songs.Song("empty", "空", "Empty", 100, []))
        self.assertEqual(bm.notes, [])
        self.assertEqual(bm.duration, 0.0)

    def test_single_pitch_song_stays_in_lane_zero(self):
        song = songs.Song("one", "一", "One", 100, songs.seq([(60, 1), (60, 1)], bpm=100))
        bm = songs.beatmap_from_song(song)
        self.assertEqual({n.lane for n in bm.notes}, {0})


class ChartErgonomics(unittest.TestCase):
    """The rhythm charts are written for two hands on six keys."""

    # Longest run of onsets owned by one hand. Canon's 15 arrive at a slow
    # 1.5 notes/s and are harmless; anything beyond these limits means a hand
    # is being asked to hammer a fast stream alone.
    HAND_RUN_LIMITS = {"canon": 16, "minuet_g": 6,
                       "turkish_march": 14, "fur_elise": 10}

    def _onsets(self, sid):
        events = {}
        for note in songs.get_beatmap(sid).notes:
            events.setdefault(round(note.time, 6), []).append(note.lane)
        times = sorted(events)
        return times, [sorted(events[t]) for t in times]

    def test_no_chart_leaves_one_hand_on_a_long_run(self):
        for sid, limit in self.HAND_RUN_LIMITS.items():
            with self.subTest(song=sid):
                _times, lanes = self._onsets(sid)
                run = best = 0
                previous = None
                for onset in lanes:
                    if len(onset) > 1:
                        # A two-hand chord neither extends nor breaks a run.
                        continue
                    hand = onset[0] < 3
                    run = run + 1 if hand == previous else 1
                    previous = hand
                    best = max(best, run)
                self.assertLessEqual(best, limit)

    def test_minuet_chart_is_planned_for_two_hands(self):
        bm = songs.get_beatmap("minuet_g")
        loads = Counter(n.lane for n in bm.notes)
        left = sum(loads[lane] for lane in (0, 1, 2)) / len(bm.notes)
        self.assertAlmostEqual(left, 0.5, delta=0.08)
        # The outer keys still take part (the chart reads low-left, high-right)
        # but never more than roughly a fifth of the notes.
        outer = (loads[0] + loads[5]) / len(bm.notes)
        self.assertGreater(outer, 0.02)
        self.assertLessEqual(outer, 0.12)

    def test_minuet_chart_does_not_stack_repeated_keys(self):
        times, lanes = self._onsets("minuet_g")
        repeats = sum(1 for a, b in zip(lanes, lanes[1:]) if set(a) & set(b))
        self.assertLessEqual(repeats / len(times), 0.02)

    def test_dense_notes_stay_on_the_middle_four_lanes(self):
        # Canon keeps its own, stricter check in CanonChart; these three use the
        # half-beat threshold every chart was retuned to.
        for sid in ("minuet_g", "turkish_march", "fur_elise"):
            with self.subTest(song=sid):
                bm = songs.get_beatmap(sid)
                spb = 60.0 / songs.SONGS[sid].bpm
                times = sorted({round(n.time, 6) for n in bm.notes})
                dense = set()
                for i, t in enumerate(times):
                    gaps = []
                    if i:
                        gaps.append(t - times[i - 1])
                    if i + 1 < len(times):
                        gaps.append(times[i + 1] - t)
                    if gaps and min(gaps) <= spb * 0.5 + 1e-9:
                        dense.add(t)
                self.assertGreater(len(dense), len(times) // 4)
                for note in bm.notes:
                    if round(note.time, 6) in dense:
                        self.assertIn(note.lane, (1, 2, 3, 4))

    def test_accent_chords_are_mirrored_when_the_key_is_free(self):
        for sid in ("minuet_g", "turkish_march", "fur_elise"):
            with self.subTest(song=sid):
                _times, lanes = self._onsets(sid)
                doubles = [l for l in lanes if len(l) > 1]
                self.assertGreater(len(doubles), 0)
                mirrored = sum(1 for l in doubles if l[0] + l[1] == 5)
                self.assertGreaterEqual(mirrored, len(doubles) * 0.8)


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
        self.song = songs.get_song("minuet_g")
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


class ClockEngine:
    """Realtime-shaped engine: the audio clock only moves when the test says so."""

    realtime = True
    running = True
    sr = 44100

    def __init__(self):
        self.now = 0.0
        self.played = []  # (midi, delay, vel)

    def time(self):
        return self.now

    def play_note(self, tid, midi, dur, vel=1.0, length=None, delay=0):
        self.played.append((midi, delay, vel))

    def stop_all(self):
        self.played.clear()


class PlayerAudioClock(unittest.TestCase):
    """A realtime melody follows the mixer clock; frames only schedule ahead."""

    def setUp(self):
        self.eng = ClockEngine()
        self.song = songs.Song("clock", "钟", "Clock", 120, [
            songs.Note(0.0, 60, 0.2),
            songs.Note(0.5, 62, 0.2),
            songs.Note(1.0, 64, 0.2),
        ])
        self.p = songs.SongPlayer(self.eng, self.song, "harp")

    def test_position_follows_the_audio_clock_not_the_frame_deltas(self):
        self.p.start()
        self.eng.now = 0.3
        self.p.update(0.016)
        self.assertAlmostEqual(self.p.pos, 0.3)
        self.p.update(0.5)  # a slow frame (or app.step's dt clamp) moves nothing
        self.assertAlmostEqual(self.p.pos, 0.3)

    def test_a_note_inside_the_lookahead_is_placed_on_its_exact_sample(self):
        self.p.start()
        self.eng.now = 0.47  # 30 ms before the 0.5 s note
        self.p.update(0.016)
        self.assertEqual([m for m, _, _ in self.eng.played], [60, 62])
        self.assertEqual(self.eng.played[0][1], 0)
        self.assertLessEqual(abs(self.eng.played[1][1] - 0.03 * self.eng.sr), 1)

    def test_a_stalled_clock_fires_the_overdue_notes_at_once(self):
        self.p.start()
        self.eng.now = 2.0
        self.p.update(0.016)
        self.assertEqual([m for m, _, _ in self.eng.played], [60, 62, 64])
        self.assertEqual([d for _, d, _ in self.eng.played], [0, 0, 0])

    def test_the_score_velocity_reaches_the_engine(self):
        # 强弱: the player hands each note's vel times the user's volume
        # (times the polyphony headroom) to the mixer, so the rhythm game and
        # prenatal auto-play both follow the score's dynamics.
        song = songs.Song("dyn", "强弱", "Dynamics", 120, [
            songs.Note(0.0, 60, 0.2, vel=0.5),
            songs.Note(0.5, 62, 0.2, vel=1.0),
        ])
        p = songs.SongPlayer(self.eng, song, "harp", vol=0.8)
        p.start()
        self.eng.now = 1.0
        p.update(0.016)
        expected = [(0.5 * 0.8) * songs.SongPlayer.POLYPHONY_GAIN,
                    (1.0 * 0.8) * songs.SongPlayer.POLYPHONY_GAIN]
        self.assertEqual([v for _, _, v in self.eng.played], expected)

    def test_pause_freezes_and_resume_continues_from_the_frozen_position(self):
        self.p.start()
        self.eng.now = 0.3
        self.p.update(0.016)
        self.p.pause()
        self.eng.now = 5.0
        self.p.update(0.016)
        self.assertAlmostEqual(self.p.pos, 0.3)
        self.p.resume()
        self.eng.now = 5.1
        self.p.update(0.016)
        self.assertAlmostEqual(self.p.pos, 0.4)

    def test_resume_while_playing_does_not_re_anchor(self):
        self.p.start()
        self.eng.now = 0.3
        self.p.resume()  # freeplay calls this on every active frame
        self.p.update(0.016)
        self.assertAlmostEqual(self.p.pos, 0.3)

    def test_a_direct_position_write_re_anchors(self):
        self.p.start()
        self.eng.now = 4.0
        self.p.pos = -2.0  # the rhythm screen positions the melody after start()
        self.eng.now = 6.0
        self.p.update(0.0)
        self.assertAlmostEqual(self.p.pos, 0.0)

    def test_sync_maps_the_chart_clock_onto_the_melody(self):
        self.p.start()
        self.eng.now = 9.0
        self.p.sync(1.0, lead_in=2.0)
        self.assertAlmostEqual(self.p.pos, -1.0)
        self.eng.now = 9.25
        self.p.update(0.0)
        self.assertAlmostEqual(self.p.pos, -0.75)


if __name__ == "__main__":
    unittest.main()