"""Timbre picker: listing, preselection, both-language search, cancel."""
from __future__ import annotations

import unittest

from tmb.audio import synth

try:
    from tests.helpers import HeadlessCase
except ImportError:
    from helpers import HeadlessCase


class TimbreSelect(HeadlessCase):
    start_screen = "freeplay"

    def open_picker(self):
        self.press("ctrl+x")
        self.assertEqual(self.app.current_name, "timbre_select")
        return self.screen

    def test_lists_all_timbres_and_preselects_the_current(self):
        s = self.open_picker()
        self.assertEqual(s.items,
                         [synth.timbre_name(t, self.app.theme.lang)
                          for t in synth.ORDER])
        self.assertEqual(s.visible, list(range(len(synth.ORDER))))
        self.assertEqual(s.index, synth.ORDER.index("harp"))
        self.assertEqual(s.title, self.app.theme.t("timbre.select"))
        self.assertEqual(s.back_target, "freeplay")

    def test_search_finds_by_the_english_alias_in_chinese_mode(self):
        s = self.open_picker()
        self.press("/")
        self.assertTrue(s.searching)
        self.press("h")
        self.press("a")
        self.press("r")
        self.press("p")
        self.assertEqual(s.visible, [0])
        self.assertIn("/harp", self.frame)
        self.assertIn("1/%d" % len(synth.ORDER), self.frame)

    def test_search_finds_by_the_id(self):
        s = self.open_picker()
        self.press("/")
        for ch in "iron_x":
            self.press(ch)
        self.assertEqual(s.visible, [synth.ORDER.index("iron_xylophone")])

    def test_esc_cancels_the_search_then_a_second_esc_leaves(self):
        s = self.open_picker()
        self.press("/")
        for ch in "harp":
            self.press(ch)
        self.assertEqual(s.visible, [0])
        self.press("esc")
        self.assertFalse(s.searching)
        self.assertEqual(s.query, "")
        self.assertEqual(s.visible, list(range(len(synth.ORDER))))
        self.assertEqual(self.app.current_name, "timbre_select")
        self.press("esc")
        self.assertEqual(self.app.current_name, "freeplay")

    def test_backspace_edits_the_query(self):
        s = self.open_picker()
        self.press("/")
        for ch in "bitx":
            self.press(ch)
        self.assertEqual(s.visible, [])
        self.assertIn(self.app.theme.t("search.no_match"), self.frame)
        self.press("backspace")
        self.assertEqual(s.visible, [synth.ORDER.index("bit")])

    def test_no_match_keeps_enter_harmless(self):
        s = self.open_picker()
        self.press("/")
        self.press("z")
        self.press("z")
        self.assertEqual(s.visible, [])
        self.press("enter")
        self.assertEqual(self.app.current_name, "timbre_select")
        self.assertEqual(self.cfg.timbre, "harp")  # nothing was applied


class TimbreSelectAscii(TimbreSelect):
    mode = "ascii"

    def test_search_finds_by_the_chinese_alias_in_english_mode(self):
        s = self.open_picker()
        self.press("/")
        self.press("长")
        self.press("笛")
        self.assertEqual(s.visible, [synth.ORDER.index("flute")])
        self.assertEqual(s.items[s.visible[0]], "Flute")  # en label, zh match

    def test_pick_applies_and_returns_in_english_mode(self):
        self.open_picker()
        self.press("/")
        for ch in "banjo":
            self.press(ch)
        self.press("enter")
        self.assertEqual(self.cfg.timbre, "banjo")
        self.assertEqual(self.read_config()["timbre"], "banjo")
        self.assertEqual(self.app.current_name, "freeplay")


if __name__ == "__main__":
    unittest.main()
