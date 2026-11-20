"""Windows console input mapping: key-down AND key-up, ctrl state, mouse buttons.

Skipped on POSIX (the module binds ct.windll at import time).
"""
from __future__ import annotations

import importlib
import os
import unittest

from tmb.events import KeyEvent, MouseEvent


@unittest.skipUnless(os.name == "nt", "Windows console backend only exists on Windows")
class WindowsInput(unittest.TestCase):
    def setUp(self):
        self.mod = importlib.import_module("tmb.term_win")
        self.b = self.mod.WindowsBackend.__new__(self.mod.WindowsBackend)
        self.b._last_buttons = 0

    def key(self, ch="", vk=0, down=True, ctrl=0):
        r = self.mod.KEY_EVENT_RECORD()
        r.bKeyDown = 1 if down else 0
        r.wVirtualKeyCode = vk
        r.UnicodeChar = ch or "\x00"
        r.dwControlKeyState = ctrl
        return self.b._key(r)

    def mouse(self, x, y, state=0, flags=0):
        r = self.mod.MOUSE_EVENT_RECORD()
        r.dwMousePosition.X = x
        r.dwMousePosition.Y = y
        r.dwButtonState = state
        r.dwEventFlags = flags
        return self.b._mouse(r)

    def test_letters_are_lowercased(self):
        self.assertEqual(self.key("A", vk=0x41), KeyEvent("a", True))
        self.assertEqual(self.key("z", vk=0x5A), KeyEvent("z", True))

    def test_key_up_is_reported(self):
        self.assertEqual(self.key("a", vk=0x41, down=False), KeyEvent("a", False))

    def test_ctrl_state_makes_a_chord(self):
        self.assertEqual(self.key("x", vk=0x58, ctrl=self.mod.CTRL_MASK), KeyEvent("ctrl+x"))
        self.assertEqual(self.key("\x01", vk=0x41), KeyEvent("ctrl+a"))
        self.assertEqual(self.key("\x11", vk=0x51), KeyEvent("ctrl+q"))
        self.assertEqual(self.key("\x14", vk=0x54), KeyEvent("ctrl+t"))

    def test_special_virtual_keys(self):
        for vk, name in ((0x26, "up"), (0x28, "down"), (0x25, "left"), (0x27, "right"),
                         (0x24, "home"), (0x23, "end"), (0x21, "pgup"), (0x22, "pgdn"),
                         (0x2E, "delete"), (0x1B, "esc"), (0x0D, "enter"),
                         (0x09, "tab"), (0x08, "backspace"), (0x20, "space")):
            with self.subTest(vk=vk):
                self.assertEqual(self.key("", vk=vk), KeyEvent(name, True))
                self.assertEqual(self.key("", vk=vk, down=False), KeyEvent(name, False))

    def test_space_character_normalizes(self):
        self.assertEqual(self.key(" ", vk=0x20), KeyEvent("space"))

    def test_modifier_only_records_are_dropped(self):
        self.assertIsNone(self.key("", vk=0x10))
        self.assertIsNone(self.key("", vk=0x12))

    def test_mouse_press_then_release(self):
        self.assertEqual(self.mouse(3, 4, state=0x1), [MouseEvent(3, 4, 0, "press")])
        self.assertEqual(self.mouse(3, 4, state=0x0), [MouseEvent(3, 4, 0, "release")])

    def test_right_and_middle_buttons(self):
        self.assertEqual(self.mouse(1, 2, state=0x2), [MouseEvent(1, 2, 2, "press")])
        self.assertEqual(self.mouse(1, 2, state=0x0), [MouseEvent(1, 2, 2, "release")])
        self.assertEqual(self.mouse(1, 2, state=0x4), [MouseEvent(1, 2, 1, "press")])

    def test_wheel_direction(self):
        self.assertEqual(self.mouse(5, 6, state=0x00780000, flags=self.mod.MOUSE_WHEELED),
                         [MouseEvent(5, 6, 3, "wheel")])
        self.assertEqual(self.mouse(5, 6, state=0xFF880000, flags=self.mod.MOUSE_WHEELED),
                         [MouseEvent(5, 6, 4, "wheel")])

    def test_drag_while_a_button_is_held(self):
        self.mouse(0, 0, state=0x1)
        self.assertEqual(self.mouse(2, 3, state=0x1, flags=self.mod.MOUSE_MOVED),
                         [MouseEvent(2, 3, 0, "drag")])

    def test_mouse_coordinates_are_zero_based(self):
        self.assertEqual(self.mouse(0, 0, state=0x1), [MouseEvent(0, 0, 0, "press")])


if __name__ == "__main__":
    unittest.main()