"""Mixer: deterministic voice bookkeeping (no thread) + real WAV renders (thread)."""
from __future__ import annotations

import array
import os
import tempfile
import time
import unittest
import wave

from tmb.audio import synth
from tmb.audio.backends import NullBackend, WavBackend
from tmb.audio.engine import AudioEngine, CACHE_LIMIT, Voice, assemble_oneshot


def peak(buf) -> float:
    return max((abs(s) for s in buf), default=0.0)


def pcm_peak(pcm: bytes) -> int:
    a = array.array("h")
    a.frombytes(pcm[:len(pcm) // 2 * 2])
    return max((abs(s) for s in a), default=0)


class VoiceBookkeeping(unittest.TestCase):
    def setUp(self):
        self.eng = AudioEngine(backend=NullBackend(), realtime=False)

    def test_note_on_allocates_ids_and_counts_voices(self):
        self.assertEqual(self.eng.active(), 0)
        a = self.eng.note_on("bit", 60)
        b = self.eng.note_on("flute", 64)
        c = self.eng.play_note("harp", 60, 0.5)
        self.assertEqual(len({a, b, c}), 3)
        self.assertEqual(self.eng.active(), 3)
        self.assertEqual(set(self.eng._voices), {a, b, c})

    def test_stop_all_clears_voices(self):
        for i in range(4):
            self.eng.play_note("harp", 60 + i, 0.4)
        self.assertEqual(self.eng.active(), 4)
        self.eng.stop_all()
        self.assertEqual(self.eng.active(), 0)
        self.assertEqual(self.eng._voices, {})

    def test_one_shot_voice_is_a_single_non_looping_segment(self):
        vid = self.eng.play_note("harp", 60, 0.5)
        v = self.eng._voices[vid]
        self.assertFalse(v._sustain)
        self.assertEqual([loop for _, loop in v._segments], [False])
        self.assertGreater(peak(v.pull(512)), 0.05)

    def test_sustain_voice_loops_until_note_off(self):
        vid = self.eng.note_on("didgeridoo", 60)
        v = self.eng._voices[vid]
        self.assertTrue(v._sustain)
        self.assertEqual([loop for _, loop in v._segments], [False, True])
        rel_len = len(v._release)
        peaks = [peak(v.pull(256)) for _ in range(80)]
        self.assertTrue(all(p > 0.01 for p in peaks), peaks[:5])
        self.assertFalse(v.done)
        self.eng.note_off(vid)
        self.assertEqual([loop for _, loop in v._segments], [False])
        chunks = 0
        while not v.done and chunks < 500:
            v.pull(256)
            chunks += 1
        self.assertTrue(v.done)
        self.assertLessEqual(chunks * 256, rel_len + 256)

    def test_note_off_on_one_shot_is_a_noop(self):
        vid = self.eng.play_note("harp", 60, 0.5)
        v = self.eng._voices[vid]
        before = list(v._segments)
        self.eng.note_off(vid)
        self.assertEqual(v._segments, before)
        self.assertFalse(v.done)

    def test_note_off_unknown_id_is_safe(self):
        self.eng.note_off(9999)
        self.assertEqual(self.eng.active(), 0)

    def test_velocity_becomes_gain(self):
        vid = self.eng.note_on("bit", 60, 0.4)
        self.assertAlmostEqual(self.eng._voices[vid].gain, 0.4)

    def test_buffers_are_cached_per_timbre_and_pitch(self):
        first = self.eng._buffers("harp", 60)
        self.assertIs(self.eng._buffers("harp", 60), first)
        self.assertIsNot(self.eng._buffers("harp", 62), first)

    def test_buffer_cache_is_bounded(self):
        self.assertGreater(CACHE_LIMIT, 0)
        for midi in range(60, 60 + CACHE_LIMIT + 1):
            self.eng._buffers("xylophone", midi)
        self.assertEqual(len(self.eng._cache), CACHE_LIMIT)
        self.assertNotIn(("xylophone", 60), self.eng._cache)

    def test_assemble_oneshot_matches_requested_duration(self):
        nb = synth.get_timbre("flute").render(60)
        for dur in (0.3, 0.5, 1.0, 2.0):
            with self.subTest(dur=dur):
                buf = assemble_oneshot(nb, dur)
                self.assertEqual(len(buf), int(dur * synth.SR))
                self.assertGreater(peak(buf), 0.1)

    def test_assemble_oneshot_never_shorter_than_attack_plus_release(self):
        nb = synth.get_timbre("bit").render(60)
        minimum = len(nb.attack) + len(nb.release)
        buf = assemble_oneshot(nb, 0.01)
        self.assertEqual(len(buf), minimum)
        self.assertGreater(peak(buf), 0.1)

    def test_assemble_oneshot_of_empty_buffers(self):
        self.assertEqual(len(assemble_oneshot(synth.NoteBuffers(), 0.5)), 0)

    def test_assemble_oneshot_fades_to_exact_silence(self):
        for tid in ("bit", "flute", "didgeridoo"):
            for dur in (0.22, 0.5, 1.0):
                with self.subTest(timbre=tid, dur=dur):
                    buf = assemble_oneshot(synth.get_timbre(tid).render(60), dur)
                    self.assertEqual(buf[-1], 0.0)
                    self.assertLess(max(abs(s) for s in buf[-int(synth.SR * 0.02):]), 0.02)

    def test_voice_fade_ramps_monotonically_to_zero(self):
        v = Voice([(array.array("f", [1.0] * 1000), False)])
        v.fade_out(100)
        first = v.pull(50)
        second = v.pull(50)
        self.assertGreater(first[0], 0.9)
        for i in range(1, len(first)):
            self.assertLessEqual(first[i], first[i - 1] + 1e-6)
        self.assertLess(abs(second[-1]), 1e-6)
        self.assertTrue(v.done)

    def test_stop_all_moves_voices_to_a_fading_tail(self):
        eng = AudioEngine(backend=NullBackend(), realtime=False)
        vid = eng.play_note("harp", 60, 1.0)
        v = eng._voices[vid]
        eng.stop_all()
        self.assertEqual(eng.active(), 0)
        self.assertEqual(eng._voices, {})
        self.assertEqual(eng._fading, [v])
        self.assertTrue(v.is_fading())
        for _ in range(200):
            if v.done:
                break
            v.pull(512)
        self.assertTrue(v.done)

    def test_stop_all_immediate_clears_fading_tails(self):
        eng = AudioEngine(backend=NullBackend(), realtime=False)
        eng.play_note("harp", 60, 1.0)
        eng.stop_all()
        eng.stop_all(0)
        self.assertEqual(eng._fading, [])
        self.assertEqual(eng._voices, {})


class Preload(unittest.TestCase):
    """Background pre-rendering keeps the first press of a timbre stall-free."""

    def setUp(self):
        self.eng = AudioEngine(backend=NullBackend(), realtime=False)

    def _wait_cache(self, key, timeout=10.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if key in self.eng._cache:
                return True
            time.sleep(0.01)
        return False

    def test_preload_fills_the_cache_in_a_background_thread(self):
        self.assertEqual(self.eng._cache, {})
        self.eng.preload("bit", (60, 62, 64))
        self.assertTrue(self._wait_cache(("bit", 64)))
        self.assertEqual(len(self.eng._cache), 3)
        self.eng.play_note("bit", 64, 0.3)  # already rendered: instant
        self.assertEqual(self.eng.active(), 1)

    def test_preload_returns_immediately_even_for_a_slow_timbre(self):
        t0 = time.perf_counter()
        self.eng.preload("harp", (60, 62, 64))
        self.assertLess(time.perf_counter() - t0, 0.5)
        self.assertTrue(self._wait_cache(("harp", 64)))
        self.assertEqual(len(self.eng._cache), 3)

    def test_preload_skips_entries_already_cached(self):
        self.eng._buffers("bit", 60)
        self.eng.preload("bit", (60, 62))
        self.assertTrue(self._wait_cache(("bit", 62)))
        self.assertEqual(set(self.eng._cache), {("bit", 60), ("bit", 62)})

    def test_a_newer_preload_supersedes_the_running_one(self):
        self.eng.preload("harp", (48, 50, 52, 53, 55, 57, 59))  # slow renders
        self.eng.preload("bit", (60,))
        self.assertTrue(self._wait_cache(("bit", 60)))
        time.sleep(0.6)  # grace: at most one in-flight harp render may land
        harp = sum(1 for tid, _ in self.eng._cache if tid == "harp")
        self.assertLess(harp, 4)


class WavMixer(unittest.TestCase):
    """Start the real mixer thread and verify the rendered WAV is audible."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "mix.wav")
        self.eng = AudioEngine(backend=WavBackend(self.path), realtime=True)
        self.addCleanup(self.eng.stop)

    def read_wav(self):
        with wave.open(self.path, "rb") as w:
            self.assertEqual(w.getnchannels(), 1)
            self.assertEqual(w.getsampwidth(), 2)
            self.assertEqual(w.getframerate(), synth.SR)
            return w.readframes(w.getnframes())

    def test_play_note_renders_non_silent_wav(self):
        self.eng.start()
        self.eng.play_note("harp", 60, 0.3)
        time.sleep(0.6)
        self.eng.stop()
        pcm = self.read_wav()
        self.assertGreater(len(pcm), 2 * 4000)
        self.assertGreater(pcm_peak(pcm), 3000)

    def test_sustain_note_on_then_note_off_renders_and_ends(self):
        self.eng.start()
        vid = self.eng.note_on("flute", 60)
        time.sleep(0.25)
        self.assertEqual(self.eng.active(), 1)
        self.eng.note_off(vid)
        time.sleep(0.35)
        self.assertEqual(self.eng.active(), 0)
        self.eng.stop()
        pcm = self.read_wav()
        self.assertGreater(pcm_peak(pcm), 3000)
        self.assertLess(pcm_peak(pcm[-2000:]), 1000)

    def test_stop_all_silences_the_running_mixer(self):
        self.eng.start()
        self.eng.note_on("bit", 60)
        time.sleep(0.25)
        self.eng.stop_all()
        self.assertEqual(self.eng.active(), 0)
        time.sleep(0.25)
        self.eng.stop()
        pcm = self.read_wav()
        self.assertGreater(pcm_peak(pcm[:synth.SR // 5]), 3000)
        self.assertLess(pcm_peak(pcm[-2000:]), 500)

    def test_polyphony_sums_two_voices(self):
        self.eng.start()
        self.eng.play_note("bit", 60, 0.4)
        self.eng.play_note("bit", 67, 0.4)
        self.assertEqual(self.eng.active(), 2)
        time.sleep(0.4)
        self.eng.stop()
        self.assertGreater(pcm_peak(self.read_wav()), 3000)


if __name__ == "__main__":
    unittest.main()