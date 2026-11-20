"""Normalized event contract shared by all backends and screens."""
from __future__ import annotations

import unittest

from tmb.events import (EXIT_KEYS, KeyEvent, MouseEvent, ResizeEvent, ctrl, is_exit)


class ExitKeys(unittest.TestCase):
    def test_the_four_exit_chords(self):
        for key in ("ctrl+q", "ctrl+d", "ctrl+c", "esc"):
            with self.subTest(key=key):
                self.assertTrue(is_exit(key))
                self.assertIn(key, EXIT_KEYS)

    def test_other_keys_are_not_exits(self):
        for key in ("q", "d", "c", "ctrl+x", "ctrl+t", "ctrl+a", "enter", "space", "up"):
            with self.subTest(key=key):
                self.assertFalse(is_exit(key))

    def test_ctrl_helper_lowercases(self):
        self.assertEqual(ctrl("Q"), "ctrl+q")
        self.assertEqual(ctrl("x"), "ctrl+x")


class KeyEvents(unittest.TestCase):
    def test_letter_of_plain_and_ctrl_keys(self):
        self.assertEqual(KeyEvent("a").letter, "a")
        self.assertEqual(KeyEvent("ctrl+x").letter, "x")
        self.assertIsNone(KeyEvent("up").letter)
        self.assertIsNone(KeyEvent("enter").letter)
        self.assertIsNone(KeyEvent("1").letter)
        self.assertIsNone(KeyEvent("ctrl+1").letter)

    def test_is_ctrl(self):
        self.assertTrue(KeyEvent("ctrl+t").is_ctrl)
        self.assertFalse(KeyEvent("t").is_ctrl)

    def test_pressed_defaults_to_true(self):
        self.assertTrue(KeyEvent("a").pressed)
        self.assertFalse(KeyEvent("a", False).pressed)

    def test_events_are_frozen_and_comparable(self):
        self.assertEqual(KeyEvent("a"), KeyEvent("a", True))
        with self.assertRaises(Exception):
            KeyEvent("a").key = "b"


class OtherEvents(unittest.TestCase):
    def test_mouse_event_fields(self):
        m = MouseEvent(3, 4, 0, "press")
        self.assertEqual((m.x, m.y, m.button, m.kind), (3, 4, 0, "press"))
        self.assertEqual(m, MouseEvent(3, 4, 0, "press"))

    def test_resize_event_fields(self):
        r = ResizeEvent(100, 30)
        self.assertEqual((r.w, r.h), (100, 30))


if __name__ == "__main__":
    unittest.main()