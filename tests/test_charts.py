"""Lane-planning helpers: bands, fingering streams and the correction passes."""
from __future__ import annotations

import unittest
from collections import Counter

from tmb import charts


class Bands(unittest.TestCase):
    def test_empty_input_maps_nothing(self):
        self.assertEqual(charts.pitch_bands([], 6), {})

    def test_a_single_pitch_takes_the_first_lane(self):
        self.assertEqual(charts.pitch_bands([60, 60], 6), {60: 0})

    def test_bands_are_monotonic_and_balanced(self):
        # Three pitches per band, six bands, one pitch per band: flat by design.
        pitches = [60] * 10 + [62] * 10 + [64] * 10 + [65] * 10 + [67] * 10 + [69] * 10
        band = charts.pitch_bands(pitches, 6)
        ordered = [band[pitch] for pitch in sorted(band)]
        self.assertEqual(ordered, sorted(ordered))
        self.assertEqual(set(ordered), set(range(6)))
        loads = Counter(band[pitch] for pitch in pitches)
        self.assertEqual(len(set(loads.values())), 1)

    def test_a_dense_pitch_does_not_swallow_a_band(self):
        # The top band must still receive notes when the top pitch is rare.
        pitches = [60] * 40 + [61] * 40 + [62] * 10 + [90] * 1
        band = charts.pitch_bands(pitches, 3)
        self.assertEqual(band[90], 2)
        self.assertEqual(band[60], 0)

    def test_lanes_argument_restricts_the_destinations(self):
        band = charts.pitch_bands([60, 62, 64, 65, 67, 69], lanes=charts.INNER)
        self.assertTrue(set(band.values()) <= set(charts.INNER))
        self.assertEqual(sorted(set(band.values())), list(charts.INNER))

    def test_every_pitch_is_mapped(self):
        band = charts.pitch_bands([60, 64, 67], 6)
        self.assertEqual(set(band), {60, 64, 67})


class Patterns(unittest.TestCase):
    def test_a_bank_repeats_each_shape_then_rotates(self):
        stream = charts.pattern_stream(((1, 2), (3, 4)), repeats=2)
        self.assertEqual([next(stream) for _ in range(8)],
                         [1, 2, 1, 2, 3, 4, 3, 4])

    def test_a_single_repeat_still_cycles(self):
        stream = charts.pattern_stream(((0,), (5,)), repeats=1)
        self.assertEqual([next(stream) for _ in range(4)], [0, 5, 0, 5])


class Density(unittest.TestCase):
    def test_flags_both_neighbours_of_a_close_pair(self):
        times = [0.0, 0.1, 0.2, 1.0]
        self.assertEqual(charts.dense_flags(times, spb=1.0, threshold=0.25),
                         [True, True, True, False])

    def test_a_lone_note_is_sparse(self):
        self.assertEqual(charts.dense_flags([0.0, 5.0], spb=1.0), [False, False])


class Corrections(unittest.TestCase):
    def test_a_repeated_lane_moves_to_a_neighbour(self):
        out = charts.no_repeat([2, 2, 3], [0.0, 0.1, 0.2], gap=1.0)
        self.assertEqual(out[0], 2)
        self.assertNotEqual(out[1], 2)
        self.assertEqual(out[2], 3)

    def test_a_repeat_beyond_the_gap_is_left_alone(self):
        out = charts.no_repeat([2, 2], [0.0, 5.0], gap=1.0)
        self.assertEqual(out, [2, 2])

    def test_an_allowed_set_is_respected(self):
        out = charts.no_repeat([1, 1], [0.0, 0.1], gap=1.0,
                               allowed=charts.INNER)
        self.assertIn(out[1], charts.INNER)

    def test_hand_runs_split_by_hand(self):
        self.assertEqual(charts.hand_runs([0, 1, 4, 5]), [(0, 2, True), (2, 4, False)])
        self.assertEqual(charts.hand_runs([]), [])

    def test_a_long_one_hand_block_is_crossed(self):
        lanes = [1] * 10
        times = [i * 0.1 for i in range(10)]
        out = charts.break_hand_blocks(lanes, times, max_run=3)
        self.assertTrue(any(lane >= 3 for lane in out))

    def test_a_short_block_is_untouched(self):
        lanes = [1, 1, 1]
        out = charts.break_hand_blocks(lanes, [0.0, 0.1, 0.2], max_run=6)
        self.assertEqual(out, lanes)

    def test_a_slow_block_is_untouched(self):
        lanes = [1] * 10
        times = [i * 2.0 for i in range(10)]
        out = charts.break_hand_blocks(lanes, times, max_run=3,
                                       beat_gap=0.5)
        self.assertEqual(out, lanes)

    def test_crossing_never_repeats_the_previous_lane(self):
        lanes = [2] * 10
        times = [i * 0.1 for i in range(10)]
        out = charts.break_hand_blocks(lanes, times, max_run=3,
                                       crossing=lambda lane: 3)
        self.assertEqual(out[3], 3)
        self.assertNotEqual(out[3], out[2])

    def test_an_explicit_crossing_target_is_used(self):
        # A left-hand block borrows `when_left`, a right-hand block `when_right`.
        lanes = [1] * 8
        times = [i * 0.1 for i in range(8)]
        out = charts.break_hand_blocks(lanes, times, max_run=3,
                                       crossing=(3, 2))
        self.assertIn(3, out)


class Partners(unittest.TestCase):
    def test_a_partner_crosses_hands_by_default(self):
        partner = charts.pick_partner(1, {1}, [0] * 6)
        self.assertIsNotNone(partner)
        self.assertGreaterEqual(partner, 3)

    def test_the_less_loaded_hand_wins(self):
        loads = [50, 50, 50, 0, 0, 0]
        partner = charts.pick_partner(1, {1}, loads)
        self.assertIn(partner, (3, 4, 5))

    def test_taken_lanes_are_excluded(self):
        partner = charts.pick_partner(1, {1, 3, 4}, [0] * 6)
        self.assertNotIn(partner, (1, 3, 4))

    def test_no_candidate_returns_none(self):
        self.assertIsNone(charts.pick_partner(1, set(range(6)), [0] * 6))

    def test_crossing_can_be_switched_off(self):
        # Without the cross-hand preference the lighter lane wins across the
        # middle, so a left-hand primary may stay on the left.
        loads = [0, 0, 0, 99, 99, 99]
        partner = charts.pick_partner(1, {1}, loads, cross_hand=False)
        self.assertLess(partner, 3)


class MirroredPartners(unittest.TestCase):
    def test_the_mirror_is_the_default(self):
        for lane in range(6):
            with self.subTest(lane=lane):
                self.assertEqual(charts.mirror_partner(lane, {lane}), 5 - lane)

    def test_a_taken_mirror_falls_back_nearby(self):
        partner = charts.mirror_partner(1, {1, 4})
        self.assertNotIn(partner, (1, 4))
        self.assertNotEqual(partner, 1)

    def test_the_allowed_set_is_respected(self):
        self.assertIn(charts.mirror_partner(1, {1}, charts.INNER), charts.INNER)

    def test_no_candidate_returns_none(self):
        self.assertIsNone(charts.mirror_partner(1, set(range(6))))


class Helpers(unittest.TestCase):
    def test_lane_hands(self):
        self.assertTrue(charts.is_left(0))
        self.assertFalse(charts.is_left(3))
        self.assertTrue(charts.same_hand(1, 2))
        self.assertFalse(charts.same_hand(2, 3))

    def test_mirror_swaps_the_hands(self):
        for lane in range(6):
            self.assertEqual(charts.mirror(charts.mirror(lane)), lane)
            self.assertNotEqual(charts.is_left(charts.mirror(lane)),
                                charts.is_left(lane))


if __name__ == "__main__":
    unittest.main()
