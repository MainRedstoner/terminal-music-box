"""Terminal facade: screen lifecycle, mouse/alt-screen sequences, backend dispatch."""
from __future__ import annotations

import io
import os
import unittest
from unittest import mock

from tmb.events import KeyEvent
from tmb.terminal import Terminal, make_backend
from tmb.term_posix import PosixBackend


class FakeBackend:
    name = "fake"

    def __init__(self):
        self.events = []
        self.setup_calls = 0
        self.teardown_calls = 0
        self.enter_alt_calls = 0
        self.leave_alt_calls = 0
        self.on_enter = None
        self.on_leave = None

    def setup(self):
        self.setup_calls += 1

    def teardown(self):
        self.teardown_calls += 1

    def enter_alt_screen(self):
        self.enter_alt_calls += 1
        if self.on_enter:
            self.on_enter()

    def leave_alt_screen(self):
        self.leave_alt_calls += 1
        if self.on_leave:
            self.on_leave()

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
        # Nothing changed: the renderer returns an empty diff and nothing is
        # flushed (the old per-frame cursor-hide made every frame cost bytes).
        self.term.screen.text(0, 0, "hi")
        before = len(self.text())
        self.term.render(self.term.screen)
        self.assertEqual(len(self.text()), before)

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
        self.assertEqual(self.backend.enter_alt_calls, 0)
        self.assertEqual(self.backend.leave_alt_calls, 0)

    def test_keyboard_flags_are_pushed_after_the_alt_screen_switch(self):
        # kitty keeps separate keyboard-mode stacks per screen: the flags
        # pushed during setup belong to the main screen, so the alt screen
        # needs its own push or releases are never reported.
        self.backend.on_enter = lambda: self.out.buffer.write(b"<ENTER>")
        self.term.setup()
        out = self.out.buffer.getvalue()
        self.assertEqual(self.backend.enter_alt_calls, 1)
        self.assertLess(out.index(b"\x1b[?1049h"), out.index(b"<ENTER>"))

    def test_alt_flags_are_popped_before_leaving_the_alt_screen(self):
        self.term.setup()
        self.backend.on_leave = lambda: self.out.buffer.write(b"<LEAVE>")
        self.term.teardown()
        out = self.out.buffer.getvalue()
        self.assertEqual(self.backend.leave_alt_calls, 1)
        self.assertLess(out.index(b"<LEAVE>"), out.index(b"\x1b[?1049l"))


class KittyAltScreen(unittest.TestCase):
    @staticmethod
    def backend(kitty):
        b = object.__new__(PosixBackend)
        b._kitty = kitty
        b._diag_log = None
        return b

    def test_enter_pushes_flags_on_the_current_screen(self):
        out = FakeStdout()
        with mock.patch("tmb.term_posix.sys.stdout", out):
            self.backend(True).enter_alt_screen()
        self.assertEqual(out.buffer.getvalue(), b"\x1b[>3u")

    def test_leave_pops_flags_on_the_current_screen(self):
        out = FakeStdout()
        with mock.patch("tmb.term_posix.sys.stdout", out):
            self.backend(True).leave_alt_screen()
        self.assertEqual(out.buffer.getvalue(), b"\x1b[<u")

    def test_without_kitty_nothing_is_sent(self):
        out = FakeStdout()
        with mock.patch("tmb.term_posix.sys.stdout", out):
            self.backend(False).enter_alt_screen()
            self.backend(False).leave_alt_screen()
        self.assertEqual(out.buffer.getvalue(), b"")


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

    def test_make_backend_passes_no_kitty_to_posix(self):
        with mock.patch("tmb.terminal.os.name", "posix"):
            with mock.patch("tmb.term_posix.PosixBackend") as cls:
                make_backend(no_kitty=True)
                cls.assert_called_once_with(no_kitty=True)

    def test_terminal_defaults_to_the_platform_backend(self):
        with mock.patch("tmb.terminal.make_backend") as mk:
            Terminal()
            mk.assert_called_once_with(False)


if __name__ == "__main__":
    unittest.main()