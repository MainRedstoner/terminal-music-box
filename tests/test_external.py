"""External packs: parsing, decoding, playback, and the grouped song list."""
from __future__ import annotations

import array
import io
import json
import math
import os
import shutil
import subprocess
import tempfile
import time
import unittest
import wave
import zipfile
from unittest import mock

import tmb.external as external
from tmb.audio.backends import NullBackend, WavBackend
from tmb.audio.engine import AudioEngine

try:
    from tests.helpers import HeadlessCase
except ImportError:
    from helpers import HeadlessCase

HAS_FFMPEG = shutil.which("ffmpeg") is not None


class ThreadedCase(HeadlessCase):
    """HeadlessCase plus a waiter that yields CPU to real decode threads.

    run_until spins app.step() at full speed, which starves the decode
    thread under the GIL for whole seconds; production runs block on input
    polling, so this is only a test-loop artifact. step_until sleeps a
    little between frames.
    """

    def step_until(self, pred, timeout=10.0, dt=0.005):
        deadline = time.time() + timeout
        rf = self.app.render_frames
        self.app.render_frames = False
        try:
            while time.time() < deadline:
                self.app.step(dt)
                time.sleep(0.002)
                if pred():
                    self._refresh_frame()
                    return
        finally:
            self.app.render_frames = rf
        self.fail("step_until: condition never became true")

NOTES = [[0.2, 0], [0.5, 1], [0.8, 2], [1.2, 3], [1.6, 4], [2.0, 5], [2.4, 2]]
DURATION = 3.0


def wav_bytes(seconds=DURATION, sr=44100, freq=440.0) -> bytes:
    n = int(sr * seconds)
    pcm = array.array("h", (int(12000 * math.sin(2 * math.pi * freq * i / sr))
                            for i in range(n)))
    bio = io.BytesIO()
    with wave.open(bio, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    return bio.getvalue()


def build_pack(directory, name="test.tmbp", sid="test_song", audio="audio.wav",
               data=None, manifest=None, chart=None, duration=DURATION) -> str:
    os.makedirs(directory, exist_ok=True)
    if data is None:
        data = wav_bytes(duration)
    m = {"format": 1, "id": sid, "title_zh": "测试曲", "title_en": "Test Song",
         "audio": audio, "duration": duration, "lead_in": 0.5}
    if manifest:
        m.update(manifest)
    c = {"version": 1, "notes": chart if chart is not None else NOTES}
    path = os.path.join(directory, name)
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("manifest.json", json.dumps(m, ensure_ascii=False))
        zf.writestr("chart.json", json.dumps(c))
        zf.writestr(audio, data)
    return path


class PackParsing(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_reads_manifest_and_chart(self):
        path = build_pack(self.tmp.name)
        pack = external.read_pack(path)
        self.assertEqual(pack.id, "test_song")
        self.assertEqual(pack.title_zh, "测试曲")
        self.assertEqual(pack.title_en, "Test Song")
        self.assertEqual(pack.audio_name, "audio.wav")
        self.assertEqual(pack.duration, DURATION)
        self.assertEqual(pack.lead_in, 0.5)
        self.assertEqual([(round(t, 3), lane) for t, lane in pack.notes],
                         [tuple(n) for n in NOTES])
        bm = pack.beatmap()
        self.assertEqual(bm.notes[0].time, 0.2 + 0.5)
        self.assertEqual(bm.notes[0].lane, 0)
        self.assertEqual(bm.duration, max(t for t, _ in NOTES) + 0.5)

    def test_titles_fall_back_to_the_id(self):
        path = build_pack(self.tmp.name, sid="fallback",
                          manifest={"title_zh": None})
        self.assertEqual(external.read_pack(path).title_zh, "fallback")

    def test_chords_survive_but_duplicate_taps_do_not(self):
        chart = [[1.0, 2], [1.0, 4], [1.0, 2]]
        path = build_pack(self.tmp.name, chart=chart)
        pack = external.read_pack(path)
        self.assertEqual(pack.notes, [(1.0, 2), (1.0, 4)])

    def test_rejects_missing_chart(self):
        path = os.path.join(self.tmp.name, "bad.tmbp")
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("manifest.json", json.dumps(
                {"format": 1, "id": "x", "audio": "audio.wav"}))
        with self.assertRaises(external.PackError):
            external.read_pack(path)

    def test_rejects_missing_audio_member(self):
        path = os.path.join(self.tmp.name, "bad.tmbp")
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("manifest.json", json.dumps(
                {"format": 1, "id": "x", "audio": "gone.wav"}))
            zf.writestr("chart.json", json.dumps({"notes": NOTES}))
        with self.assertRaises(external.PackError):
            external.read_pack(path)

    def test_rejects_bad_lane(self):
        path = build_pack(self.tmp.name, chart=[[1.0, 9]])
        with self.assertRaises(external.PackError):
            external.read_pack(path)

    def test_rejects_unknown_format(self):
        path = build_pack(self.tmp.name, manifest={"format": 99})
        with self.assertRaises(external.PackError):
            external.read_pack(path)

    def test_rejects_a_corrupt_zip(self):
        path = os.path.join(self.tmp.name, "bad.tmbp")
        with open(path, "wb") as f:
            f.write(b"not a zip at all")
        with self.assertRaises(external.PackError):
            external.read_pack(path)


class WavDecode(unittest.TestCase):
    def test_stdlib_fast_path(self):
        pcm = external.decode_audio(wav_bytes(0.5), 44100, "audio.wav")
        self.assertEqual(pcm.typecode, "h")
        self.assertEqual(len(pcm), 22050)
        self.assertNotEqual(max(abs(v) for v in pcm[:441]), 0)

    def test_rate_mismatch_needs_ffmpeg(self):
        with mock.patch.object(external.shutil, "which", return_value=None):
            with self.assertRaises(external.PackError):
                external.decode_audio(wav_bytes(0.1, sr=22050), 44100,
                                      "audio.wav")


@unittest.skipUnless(HAS_FFMPEG, "ffmpeg required")
class FfmpegDecode(unittest.TestCase):
    def _compressed(self, codec: str, ext: str) -> bytes:
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "in.wav")
            dst = os.path.join(tmp, "out.m4a" if ext == ".m4s" else "out" + ext)
            with open(src, "wb") as f:
                f.write(wav_bytes(0.5))
            flags = {"opus": ["-c:a", "libopus"], "aac": ["-c:a", "aac"],
                     "m4s-like": ["-c:a", "aac"]}[codec]
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", src, "-ac", "1"]
                           + flags + [dst], check=True, timeout=60)
            with open(dst, "rb") as f:
                return f.read()

    def test_decodes_opus(self):
        pcm = external.decode_audio(self._compressed("opus", ".opus"), 44100,
                                    "audio.opus")
        self.assertAlmostEqual(len(pcm), 22050, delta=4410)

    def test_decodes_an_aac_m4s_stream(self):
        pcm = external.decode_audio(self._compressed("m4s-like", ".m4s"),
                                    44100, "audio.m4s")
        self.assertAlmostEqual(len(pcm), 22050, delta=4410)


class FakeEngine:
    """Scripted engine: consumed advances only when the mixer 'pulls'."""

    def __init__(self, sr=100):
        self.sr = sr
        self.voices = {}
        self.stopped = []
        self.next_id = 1

    def play_pcm(self, pcm, gain=1.0, start=0):
        vid = self.next_id
        self.next_id += 1
        self.voices[vid] = {"consumed": 0, "start": start, "gain": gain}
        return vid

    def voice_consumed(self, vid):
        v = self.voices.get(vid)
        return -1 if v is None else v["consumed"]

    def stop_voice(self, vid, fade_ms=120.0):
        self.stopped.append((vid, fade_ms))
        self.voices.pop(vid, None)

    def advance(self, frames):
        for v in self.voices.values():
            v["consumed"] += frames


class PackPlayerLogic(unittest.TestCase):
    def _player(self, seconds=3.0):
        eng = FakeEngine(sr=100)
        pcm = array.array("h", range(int(100 * seconds)))
        return external.PackPlayer(eng, pcm, offset=0.0, volume=1.0), eng

    def test_audio_starts_at_the_lead_in(self):
        p, eng = self._player()
        p.sync(1.0, lead_in=2.0)
        self.assertFalse(p.started)
        p.sync(2.0, lead_in=2.0)
        self.assertTrue(p.started)
        self.assertEqual(len(eng.voices), 1)

    def test_pause_keeps_the_position_and_resume_continues(self):
        p, eng = self._player()
        p.sync(2.0, lead_in=2.0)
        vid = next(iter(eng.voices))
        eng.advance(150)
        p.sync(3.5, lead_in=2.0)  # clock matches the mixer, no resync
        self.assertAlmostEqual(p.position, 1.5, delta=0.001)
        p.pause()
        self.assertEqual(eng.stopped, [(vid, mock.ANY)])
        self.assertAlmostEqual(p.position, 1.5, delta=0.001)
        p.resume()
        self.assertEqual(eng.voices[next(iter(eng.voices))]["start"], 150)

    def test_a_ended_voice_marks_the_player_finished(self):
        p, eng = self._player(1.0)
        p.sync(2.0, lead_in=2.0)
        vid = next(iter(eng.voices))
        eng.voices.pop(vid)
        p.sync(2.5, lead_in=2.0)
        self.assertTrue(p.finished)
        self.assertFalse(p.playing)

    def test_sync_resyncs_when_the_mixer_lags(self):
        p, eng = self._player(4.0)
        p.sync(2.0, lead_in=2.0)
        vid = next(iter(eng.voices))
        eng.advance(50)  # mixer only consumed 0.5 s
        # One drifted frame is tolerated (a GC pause must not punch a seam);
        # sustained drift restarts the voice at the expected frame.
        for song_time in (5.0, 5.1, 5.2):
            p.sync(song_time, lead_in=2.0)
        self.assertEqual(eng.stopped[0][0], vid)
        self.assertNotIn(vid, eng.voices)
        restarted = [v for v in eng.voices.values()]
        self.assertEqual(restarted[0]["start"], 320)

    def test_a_single_drifted_frame_does_not_resync(self):
        p, eng = self._player(4.0)
        p.sync(2.0, lead_in=2.0)
        vid = next(iter(eng.voices))
        eng.advance(50)
        p.sync(5.0, lead_in=2.0)  # drifted, but only once
        self.assertEqual(eng.stopped, [])
        self.assertIn(vid, eng.voices)

    def test_sync_finishes_once_the_song_clock_passes_the_audio(self):
        p, eng = self._player(1.0)
        p.sync(2.0, lead_in=2.0)
        p.sync(3.5, lead_in=2.0)
        self.assertTrue(p.finished)
        self.assertEqual(eng.stopped, [(1, mock.ANY)])

    def test_stop_is_safe_without_a_voice(self):
        p, eng = self._player()
        p.stop()
        self.assertEqual(eng.stopped, [])

    def test_volume_goes_to_the_voice(self):
        eng = FakeEngine()
        p = external.PackPlayer(eng, array.array("h", range(10)), volume=0.5)
        p.sync(0.0, lead_in=0.0)
        self.assertEqual(eng.voices[1]["gain"], 0.5)


class PackPlayerEngine(unittest.TestCase):
    """White-box: int16 PCM must arrive normalized in the float mixer."""

    def setUp(self):
        self.engine = AudioEngine(backend=NullBackend(), realtime=False)

    def test_pcm_pull_values_and_consumed(self):
        pcm = array.array("h", [1000, -1000] * 16)
        vid = self.engine.play_pcm(pcm)
        voice = self.engine._voices[vid]
        out = voice.pull(4)
        for got, want in zip(out, (1000, -1000, 1000, -1000)):
            self.assertAlmostEqual(got, want / 32768.0, places=6)
        self.assertEqual(voice.consumed, 4)

    def test_start_offset_resumes_mid_buffer(self):
        pcm = array.array("h", [1000, -1000] * 16)
        vid = self.engine.play_pcm(pcm, start=6)
        out = self.engine._voices[vid].pull(2)
        self.assertAlmostEqual(out[0], 1000 / 32768.0, places=6)
        self.assertAlmostEqual(out[1], -1000 / 32768.0, places=6)

    def test_full_scale_pcm_stays_below_the_limiter_knee(self):
        # Regression: unscaled int16 sent every sample through the tanh
        # limiter (raw 32767 * gain ≫ 0.8), so one chunk after any silence
        # — the mix gain back at 1.0 — played as a square wave.
        pcm = array.array("h", [32767, -32767] * 128)
        vid = self.engine.play_pcm(pcm)
        out = self.engine._voices[vid].pull(16)
        self.assertTrue(all(abs(v) <= 1.0 for v in out))

    def test_recorded_playback_keeps_the_sine_crest(self):
        # The full "recording" path: real mixer pacing into a WAV. A loud
        # sine must stay a sine (crest ≈ 0.707); the scaling bug collapsed
        # it toward a square wave (crest ≈ 1.0) after every silence.
        import tempfile
        import wave as wave_module
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "out.wav")
        engine = AudioEngine(backend=WavBackend(path), realtime=True)
        sr = engine.sr
        pcm = array.array("h", (int(32767 * math.sin(2 * math.pi * 220 * i / sr))
                                for i in range(sr // 2)))
        engine.start()
        try:
            engine.play_pcm(pcm)
            time.sleep(0.6)
        finally:
            engine.stop()
        with wave_module.open(path) as w:
            data = array.array("h")
            data.frombytes(w.readframes(w.getnframes()))
        body = data[int(sr * 0.05):int(sr * 0.45)]
        peak = max(abs(v) for v in body)
        rms = (sum(v * v for v in body[::2]) / max(1, len(body) // 2)) ** 0.5
        self.assertGreater(peak, 1000)  # actually audible
        self.assertLess(peak, 32767 * 0.9)
        self.assertLess(rms / peak, 0.85)

    def test_stop_voice_removes_and_fades(self):
        pcm = array.array("h", [1, -1] * 64)
        vid = self.engine.play_pcm(pcm)
        self.engine.stop_voice(vid, fade_ms=10)
        self.assertEqual(self.engine.active(), 0)
        self.assertEqual(self.engine.voice_consumed(vid), -1)


class GroupedList(ThreadedCase):
    """The rhythm song list with 内置/外部 sections."""

    start_screen = "menu"

    def setUp(self):
        super().setUp()
        build_pack(self.external_dir)
        self.app.external.refresh()
        self.app.navigate("rhythm_menu")
        self.app.step(0.016)

    def test_two_section_headers_with_external_below_builtin(self):
        th = self.app.theme
        rows = self.screen.rows
        kinds = [r[0] for r in rows]
        self.assertEqual(kinds.count("header"), 2)
        self.assertIn(("header", "rhythm.builtin"), rows)
        self.assertIn(("header", "rhythm.external"), rows)
        self.assertLess(rows.index(("header", "rhythm.builtin")),
                        rows.index(("header", "rhythm.external")))
        self.assertIn(th.t("rhythm.builtin"), self.frame)
        self.assertIn(th.t("rhythm.external"), self.frame)
        self.assertIn("测试曲", self.frame)

    def test_flat_song_ids_put_the_pack_last(self):
        self.assertEqual(self.screen.song_ids,
                         ["canon", "minuet_g", "turkish_march", "fur_elise",
                          "test_song"])

    def test_down_moves_from_the_last_builtin_to_the_pack(self):
        for _ in range(4):
            self.press("down")
        self.assertEqual(self.screen.song_index, 4)
        self.press("enter")
        # step_until, not run_until: the pack decodes on a worker thread and a
        # full-speed app.step() loop starves it under the GIL (see ThreadedCase).
        self.step_until(lambda: self.app.current_name == "rhythm_game")
        self.assertEqual(self.screen.pack.id, "test_song")

    def test_entering_the_pack_decodes_then_plays(self):
        for _ in range(4):
            self.press("down")
        self.press("enter")
        self.step_until(lambda: self.app.current_name == "rhythm_game")
        game = self.screen
        self.assertEqual(game.beatmap.notes[0].time, 0.2 + 0.5)
        self.advance(3.1)  # countdown
        self.assertEqual(game.state, "play")
        self.advance(0.6)  # song_time reaches the 0.5 s lead-in
        self.assertGreaterEqual(self.engine.active(), 1)
        self.assertTrue(game.player.started)

    def test_pause_stops_pack_audio_and_resume_restarts_it(self):
        for _ in range(4):
            self.press("down")
        self.press("enter")
        self.step_until(lambda: self.app.current_name == "rhythm_game")
        self.advance(3.1 + 0.6)
        self.assertGreaterEqual(self.engine.active(), 1)
        self.press("esc")
        self.assertEqual(self.screen.state, "pause")
        self.assertEqual(self.engine.active(), 0)
        self.assertFalse(self.screen.player.playing)
        self.press("enter")  # 继续
        self.advance(3.1)    # countdown
        self.assertGreaterEqual(self.engine.active(), 1)
        self.assertTrue(self.screen.player.playing)

    def test_finishing_a_pack_shows_the_result(self):
        for _ in range(4):
            self.press("down")
        self.press("enter")
        self.step_until(lambda: self.app.current_name == "rhythm_game")
        self.advance(3.1 + 0.5 + max(t for t, _ in NOTES) + 1.6)
        self.assertEqual(self.screen.state, "result")
        self.assertIn("测试曲", self.frame)


class EmptyExternalSection(HeadlessCase):
    start_screen = "rhythm_menu"

    def test_shows_a_hint_when_no_packs_exist(self):
        th = self.app.theme
        self.assertIn(th.t("rhythm.external_empty"), self.frame)
        self.assertEqual([r for r in self.screen.rows if r[0] == "song"],
                         [("song", sid, None) for sid in
                          ["canon", "minuet_g", "turkish_march", "fur_elise"]])


class PackErrors(ThreadedCase):
    start_screen = "menu"

    def setUp(self):
        super().setUp()
        build_pack(self.external_dir, name="broken.tmbp", sid="broken",
                   audio="audio.opus", data=b"\x00" * 64)
        self.app.external.refresh()
        self.app.navigate("rhythm_menu")
        self.app.step(0.016)

    def _select_broken(self):
        for _ in range(4):
            self.press("down")
        self.press("enter")

    def test_a_broken_pack_reports_an_error_instead_of_entering(self):
        self._select_broken()
        self.step_until(lambda: self.screen.notice != "")
        self.assertEqual(self.app.current_name, "rhythm_menu")
        self.assertIn(self.app.theme.t("rhythm.external_error",
                                       msg=self.app.external.error("broken")),
                      self.screen.notice)

    def test_without_ffmpeg_the_pack_is_refused_upfront(self):
        with mock.patch.object(external.shutil, "which", return_value=None):
            self._select_broken()
            self.step()
            self.assertIn(self.app.theme.t("rhythm.need_ffmpeg"),
                          self.screen.notice)
            self.assertEqual(self.app.current_name, "rhythm_menu")


class LibraryBehaviour(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.lib = external.Library(engine_sr=44100,
                                    directory=self.tmp.name)

    def _wait_ready(self, sid):
        self.lib.start_decode(sid)
        for _ in range(2000):
            if self.lib.is_ready(sid):
                return
            time.sleep(0.005)
        self.fail("decode never finished: %s" % self.lib.error(sid))

    def test_refresh_skips_invalid_packs_with_a_warning(self):
        build_pack(self.tmp.name, sid="good")
        with zipfile.ZipFile(os.path.join(self.tmp.name, "bad.tmbp"), "w") as zf:
            zf.writestr("manifest.json", "{oops")
        self.lib.refresh()
        self.assertEqual([p.id for p in self.lib.packs], ["good"])
        self.assertTrue(self.lib.warnings)

    def test_duplicate_ids_are_skipped(self):
        build_pack(self.tmp.name, name="a.tmbp", sid="same")
        build_pack(self.tmp.name, name="b.tmbp", sid="same")
        self.lib.refresh()
        self.assertEqual(len(self.lib.packs), 1)

    def test_starting_a_new_pack_releases_the_previous_pcm(self):
        build_pack(self.tmp.name, name="a.tmbp", sid="a")
        build_pack(self.tmp.name, name="b.tmbp", sid="b")
        self.lib.refresh()
        self._wait_ready("a")
        self.assertIsNotNone(self.lib.get_pcm("a"))
        self.lib.start_decode("b")
        self._wait_ready("b")
        self.assertIsNone(self.lib.get_pcm("a"))
        self.assertIsNotNone(self.lib.get_pcm("b"))

    def test_release_all(self):
        build_pack(self.tmp.name, sid="a")
        self.lib.refresh()
        self._wait_ready("a")
        self.lib.release_all()
        self.assertIsNone(self.lib.get_pcm("a"))


if __name__ == "__main__":
    unittest.main()
