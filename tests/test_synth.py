"""Synth registry: the 13 melodic note-block timbres, no percussion, loopable sustains."""
from __future__ import annotations

import unittest
from array import array

from tmb.audio import synth

EXPECTED = {
    "harp", "bit", "flute", "bass", "bell", "guitar", "chime",
    "xylophone", "iron_xylophone", "cow_bell", "didgeridoo", "banjo", "pling",
}
SUSTAINING = {"bit", "flute", "didgeridoo"}
PERCUSSION = {"basedrum", "base_drum", "bassdrum", "snare", "snare_drum",
              "hat", "hihat", "click", "percussion", "drum"}


def peak(buf) -> float:
    return max((abs(s) for s in buf), default=0.0)


_RENDERED = {}


def rendered(tid, midi=60):
    key = (tid, midi)
    if key not in _RENDERED:
        _RENDERED[key] = synth.get_timbre(tid).render(midi)
    return _RENDERED[key]


class Registry(unittest.TestCase):
    def test_exactly_the_13_expected_timbres(self):
        self.assertEqual(set(synth.TIMBRES), EXPECTED)
        self.assertEqual(len(synth.TIMBRES), 13)
        self.assertEqual(len(synth.ORDER), 13)
        self.assertEqual(set(synth.ORDER), EXPECTED)

    def test_no_percussion_timbres(self):
        self.assertEqual(set(synth.TIMBRES) & PERCUSSION, set())
        for tid in synth.TIMBRES:
            self.assertNotIn("drum", tid)
            self.assertNotIn("snare", tid)
            self.assertNotIn("hat", tid)

    def test_ids_match_classes(self):
        for tid, t in synth.TIMBRES.items():
            self.assertEqual(t.id, tid)

    def test_unknown_timbre_falls_back_to_harp(self):
        self.assertIs(synth.get_timbre("does_not_exist"), synth.TIMBRES["harp"])

    def test_names_are_localized(self):
        for tid in synth.ORDER:
            zh = synth.timbre_name(tid, "zh")
            en = synth.timbre_name(tid, "en")
            self.assertTrue(zh and en)
            self.assertNotEqual(zh, en)

    def test_next_timbre_cycles_all_13_and_wraps(self):
        seen = []
        tid = synth.ORDER[0]
        for _ in range(13):
            tid = synth.next_timbre(tid)
            seen.append(tid)
        self.assertEqual(set(seen), EXPECTED)
        self.assertEqual(len(seen), 13)
        self.assertEqual(tid, synth.ORDER[0])

    def test_next_timbre_unknown_starts_at_first(self):
        self.assertEqual(synth.next_timbre("nope"), synth.ORDER[0])

    def test_midi_to_freq(self):
        self.assertAlmostEqual(synth.midi_to_freq(69), 440.0)
        self.assertAlmostEqual(synth.midi_to_freq(60), 261.6255653, places=4)
        self.assertAlmostEqual(synth.midi_to_freq(81), 880.0)


class Render(unittest.TestCase):
    def test_every_timbre_renders_non_silent_audio(self):
        for tid in synth.ORDER:
            with self.subTest(timbre=tid):
                nb = rendered(tid)
                if nb.oneshot is not None:
                    self.assertGreater(peak(nb.oneshot), 0.2)
                    self.assertGreater(len(nb.oneshot), synth.SR * 0.1)
                else:
                    self.assertGreater(peak(nb.attack), 0.01)
                    self.assertGreater(peak(nb.steady), 0.2)
                    self.assertGreater(peak(nb.release), 0.05)

    def test_sustain_flags_only_for_flute_bit_didgeridoo(self):
        self.assertEqual({t.id for t in synth.TIMBRES.values() if t.sustain}, SUSTAINING)

    def test_sustaining_timbres_have_all_three_segments(self):
        for tid in SUSTAINING:
            nb = rendered(tid)
            self.assertIsNone(nb.oneshot)
            for seg in (nb.attack, nb.steady, nb.release):
                self.assertIsInstance(seg, array)
                self.assertGreater(len(seg), 0)
            self.assertGreater(len(nb.steady), synth.SR * 0.2)

    def test_oneshot_timbres_have_no_sustain_segments(self):
        for tid in EXPECTED - SUSTAINING:
            nb = rendered(tid)
            self.assertIsNotNone(nb.oneshot)
            self.assertIsNone(nb.steady)

    def test_keyboard_extremes_are_non_silent(self):
        for tid in ("harp", "bit", "flute", "pling"):
            for midi in (48, 83):
                with self.subTest(timbre=tid, midi=midi):
                    nb = rendered(tid, midi)
                    buf = nb.oneshot if nb.oneshot is not None else nb.steady
                    self.assertGreater(peak(buf), 0.1)

    def test_steady_segment_loops_click_free(self):
        for tid in SUSTAINING:
            with self.subTest(timbre=tid):
                st = rendered(tid).steady
                boundary = abs(st[0] - st[-1])
                inner = max(abs(st[i + 1] - st[i]) for i in range(len(st) - 1))
                # A square wave legitimately jumps by its full amplitude every
                # half cycle, so the loop seam must be no worse than that.
                self.assertLessEqual(boundary, inner * 1.02 + 1e-6)
                if tid != "bit":
                    self.assertLess(boundary, 0.1)

    def test_steady_segment_spans_whole_cycles(self):
        f = synth.midi_to_freq(60)
        for tid in SUSTAINING:
            with self.subTest(timbre=tid):
                st = rendered(tid).steady
                cycles = len(st) * f / synth.SR
                self.assertLess(abs(cycles - round(cycles)), 0.02)
                self.assertGreaterEqual(round(cycles), 1)

    def test_buffers_are_float_arrays(self):
        for tid in synth.ORDER:
            nb = rendered(tid)
            for seg in (nb.oneshot, nb.attack, nb.steady, nb.release):
                if seg is not None:
                    self.assertIsInstance(seg, array)
                    self.assertEqual(seg.typecode, "f")


if __name__ == "__main__":
    unittest.main()