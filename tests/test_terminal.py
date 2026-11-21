"""Terminal facade: screen lifecycle, mouse/alt-screen sequences, backend dispatch."""
from __future__ import annotations

import io
import os
import unittest
from unittest import mock

from tmb.events import KeyEvent
from tmb.terminal import Terminal, make_backend


class FakeBackend:
    name = "fake"

    def __init__(self):
        self.events = []
        self.setup_calls = 0
        self.teardown_calls = 0

    def setup(self):
        self.setup_calls += 1

    def teardown(self):
        self.teardown_calls += 1

    def size(self):
        return 40, 12

    def poll(self, timeout):
        return list(self.events)


class FakeStdout:
    def __init__(self):
        self.buffer = io.BytesIO()

    def write(self, s):
        self.buffer.write(s.encode("utf-8"))

    def flush(self):
        pass


class Facade(unittest.TestCase):
    def setUp(self):
        self.out = FakeStdout()
        patcher = mock.patch("tmb.terminal.sys.stdout", self.out)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.backend = FakeBackend()
        self.term = Terminal(backend=self.backend)

    def text(self):
        return self.out.buffer.getvalue().decode("utf-8")

    def test_setup_allocates_a_screen_and_enables_mouse(self):
        self.term.setup()
        self.assertEqual((self.term.screen.w, self.term.screen.h), (40, 12))
        self.assertEqual(self.backend.setup_calls, 1)
        out = self.text()
        self.assertIn("\x1b[?1049h", out)
        self.assertIn("\x1b[?1000h", out)
        self.assertIn("\x1b[?1006h", out)
        self.assertIn("\x1b[?25l", out)

    def test_render_flushes_the_diff(self):
        self.term.setup()
        self.term.screen.text(0, 0, "hi")
        self.term.render(self.term.screen)
        self.assertIn("hi", self.text())
        self.term.screen.text(0, 0, "hi")
        before = len(self.text())
        self.term.render(self.term.screen)
        self.assertEqual(len(self.text()), before + len("\x1b[?25l"))

    def test_teardown_restores_the_terminal(self):
        self.term.setup()
        self.term.teardown()
        out = self.text()
        self.assertIn("\x1b[?1006l", out)
        self.assertIn("\x1b[?25h", out)
        self.assertIn("\x1b[?1049l", out)
        self.assertEqual(self.backend.teardown_calls, 1)

    def test_context_manager_runs_setup_and_teardown(self):
        with self.term as t:
            self.assertIs(t, self.term)
            self.assertEqual(self.backend.setup_calls, 1)
        self.assertEqual(self.backend.teardown_calls, 1)

    def test_teardown_runs_even_when_the_body_raises(self):
        with self.assertRaises(RuntimeError):
            with self.term:
                raise RuntimeError("boom")
        self.assertEqual(self.backend.teardown_calls, 1)

    def test_poll_delegates_to_the_backend(self):
        self.backend.events = [KeyEvent("a")]
        self.assertEqual(self.term.poll(0.01), [KeyEvent("a")])

    def test_size_delegates_to_the_backend(self):
        self.assertEqual(self.term.size(), (40, 12))

    def test_flush_without_writes_is_a_noop(self):
        self.term.flush()
        self.assertEqual(self.text(), "")

    def test_alt_screen_can_be_opted_out_by_the_backend(self):
        # WSL/ConPTY drops kitty key releases on the alternate screen, so the
        # posix backend opts out there; the facade must honour that.
        self.backend.use_alt_screen = False
        self.term.setup()
        out = self.text()
        self.assertNotIn("\x1b[?1049h", out)
        self.assertIn("\x1b[?25l", out)  # the rest of setup still runs
        self.term.teardown()
        self.assertNotIn("\x1b[?1049l", self.text())


class Dispatch(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "term_win only imports on Windows")
    def test_make_backend_picks_windows_on_nt(self):
        with mock.patch("tmb.terminal.os.name", "nt"):
            with mock.patch("tmb.term_win.WindowsBackend") as cls:
                self.assertIs(make_backend(), cls.return_value)

    def test_make_backend_picks_posix_otherwise(self):
        with mock.patch("tmb.terminal.os.name", "posix"):
            with mock.patch("tmb.term_posix.PosixBackend") as cls:
                self.assertIs(make_backend(), cls.return_value)

    def test_terminal_defaults_to_the_platform_backend(self):
        with mock.patch("tmb.terminal.make_backend") as mk:
            Terminal()
            mk.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()