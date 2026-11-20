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
            backends._ProcBackend(["player"]).open(44100, 1)
        self.assertEqual(popen.call_args.kwargs.get("bufsize"), 0)

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


if __name__ == "__main__":
    unittest.main()