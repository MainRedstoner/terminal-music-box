"""Output backends: pipe writing, PulseAudio latency choices, pacing contract."""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

from tmb.audio import backends


class _ChunkedPipe:
    def __init__(self, limit):
        self.limit = limit
        self.data = b""

    def write(self, view):
        take = min(len(view), self.limit)
        self.data += bytes(view[:take])
        return take


def proc_with(stdin):
    b = backends._ProcBackend(["player"])
    b.proc = SimpleNamespace(stdin=stdin)
    return b


class ProcPipe(unittest.TestCase):
    def test_open_pipe_is_unbuffered(self):
        with mock.patch("tmb.audio.backends.subprocess.Popen") as popen:
            popen.return_value.poll.return_value = None
            backends._ProcBackend(["player"]).open(44100, 1)
        self.assertEqual(popen.call_args.kwargs.get("bufsize"), 0)

    def test_immediate_player_exit_raises(self):
        with mock.patch("tmb.audio.backends.subprocess.Popen") as popen:
            popen.return_value.poll.return_value = 1
            with self.assertRaises(OSError):
                backends._ProcBackend(["player"]).open(44100, 1)

    def test_short_writes_are_retried_until_done(self):
        pipe = _ChunkedPipe(3)
        proc_with(pipe).write(b"abcdefgh")
        self.assertEqual(pipe.data, b"abcdefgh")

    def test_broken_pipe_is_ignored(self):
        class Broken:
            def write(self, view):
                raise BrokenPipeError()
        proc_with(Broken()).write(b"abc")

    def test_proc_backends_let_the_mixer_pace_itself(self):
        self.assertFalse(backends._ProcBackend.blocking)
        self.assertFalse(backends.AlsaBackend().blocking)
        self.assertFalse(backends.PulseBackend().blocking)

    def test_write_without_a_process_is_a_noop(self):
        backends._ProcBackend(["player"]).write(b"abc")


class PulseArgv(unittest.TestCase):
    def test_pacat_is_preferred_with_a_short_server_buffer(self):
        def which(name):
            return "/usr/bin/pacat" if name == "pacat" else None
        with mock.patch("tmb.audio.backends.shutil.which", side_effect=which):
            pb = backends.PulseBackend(48000, 2)
        self.assertEqual(pb.argv[0], "/usr/bin/pacat")
        self.assertIn("--rate=48000", pb.argv)
        self.assertIn("--channels=2", pb.argv)
        self.assertIn("--latency-msec=30", pb.argv)

    def test_paplay_is_the_fallback(self):
        with mock.patch("tmb.audio.backends.shutil.which", return_value=None):
            pb = backends.PulseBackend()
        self.assertEqual(pb.argv[0], "paplay")
        self.assertFalse(any("latency" in a for a in pb.argv))


class BackendSelection(unittest.TestCase):
    def _pick(self, tools, pulse_up, prefer=None):
        with mock.patch("tmb.audio.backends.shutil.which",
                        side_effect=lambda n: ("/usr/bin/" + n) if n in tools else None), \
             mock.patch("tmb.audio.backends._pulse_available", return_value=pulse_up):
            return backends.open_backend(prefer=prefer)

    def test_live_pulse_server_wins_over_raw_alsa(self):
        self.assertEqual(self._pick({"aplay", "paplay", "pactl"}, True).name, "pulse")

    def test_dead_pulse_server_falls_back_to_alsa(self):
        self.assertEqual(self._pick({"aplay", "paplay", "pactl"}, False).name, "alsa")

    def test_dead_pulse_without_aplay_warns_instead_of_faking_sound(self):
        with mock.patch("tmb.audio.backends.shutil.which",
                        side_effect=lambda n: "/usr/bin/paplay" if n == "paplay" else None), \
             mock.patch("tmb.audio.backends._pulse_available", return_value=False), \
             mock.patch("tmb.audio.backends._warn_silent") as warn:
            b = backends.open_backend()
        self.assertEqual(b.name, "null")
        self.assertIn("not reachable", warn.call_args[0][0])

    def test_explicit_pulse_still_honours_the_request(self):
        with mock.patch("tmb.audio.backends.shutil.which",
                        side_effect=lambda n: "/usr/bin/paplay" if n == "paplay" else None), \
             mock.patch("tmb.audio.backends._pulse_available", return_value=False), \
             mock.patch("tmb.audio.backends._warn_silent") as warn:
            b = backends.open_backend(prefer="pulse")
        self.assertEqual(b.name, "pulse")
        self.assertIn("not reachable", warn.call_args[0][0])

    def test_pulse_probe_asks_the_server(self):
        with mock.patch("tmb.audio.backends.shutil.which",
                        side_effect=lambda n: "/usr/bin/pactl" if n == "pactl" else None), \
             mock.patch("tmb.audio.backends.subprocess.run") as run:
            run.return_value = SimpleNamespace(returncode=0)
            self.assertTrue(backends._pulse_available())
        self.assertEqual(run.call_args[0][0], ["/usr/bin/pactl", "info"])

    def test_pulse_probe_is_false_without_pactl(self):
        with mock.patch("tmb.audio.backends.shutil.which", return_value=None):
            self.assertFalse(backends._pulse_available())


if __name__ == "__main__":
    unittest.main()