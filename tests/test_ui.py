"""ui.py primitives: the search field's draw pass and label fitting."""
from __future__ import annotations

import time
import unittest

from tmb.ansi import Screen
from tmb.theme import theme_for
from tmb.ui import draw_button, draw_menu_row, draw_search_field

TH = theme_for("unicode")


class SearchField(unittest.TestCase):
    def test_a_short_query_is_kept_whole(self):
        scr = Screen(80, 24)
        w = draw_search_field(scr, 0, 0, 58, "harp", TH)
        self.assertEqual(w, 1 + 4 + 1)
        self.assertIn("/harp", scr.plain_text())

    def test_an_overlong_query_drops_its_head_keeps_its_tail(self):
        scr = Screen(80, 24)
        query = "abcde" * 4000              # 20000 chars, far past the field
        draw_search_field(scr, 0, 0, 58, query, TH)
        text = scr.plain_text()
        self.assertTrue(text.startswith("/"))
        self.assertIn(query[-20:], text)    # the caret end stays visible

    def test_a_wide_query_is_a_single_pass(self):
        # Regression: dropping one character per full re-measure made the
        # draw an O(n^2) loop - 16k characters froze the frame for ~15 s.
        # The bound is generous so slow machines do not flake; the old code
        # needs minutes at this size, the single pass needs milliseconds.
        scr = Screen(80, 24)
        t0 = time.perf_counter()
        draw_search_field(scr, 0, 0, 58, "a" * 40000, TH)
        self.assertLess(time.perf_counter() - t0, 2.0)

    def test_a_one_char_query_is_never_dropped(self):
        scr = Screen(10, 3)
        draw_search_field(scr, 0, 0, 3, "很宽的字符", TH)
        self.assertIn("/", scr.plain_text())  # something is always drawn


class LabelFitting(unittest.TestCase):
    """U5: rows and buttons clip their labels to their own width."""

    def test_a_long_row_label_never_crosses_the_row(self):
        scr = Screen(80, 24)
        draw_menu_row(scr, 2, 4, 20, "一" * 40, False, TH)   # 80 columns wide
        for x in range(22, 40):             # nothing spills past the row
            self.assertEqual(scr.cells[4][x][0], " ")
            self.assertIsNone(scr.cells[4][x][2])

    def test_a_selected_row_keeps_the_marker_inside(self):
        scr = Screen(80, 24)
        draw_menu_row(scr, 2, 4, 20, "一" * 40, True, TH)
        self.assertEqual(scr.cells[4][21][0], " ")  # right edge clean

    def test_a_long_button_label_never_crosses_the_button(self):
        scr = Screen(40, 8)
        draw_button(scr, 3, 3, 18, 3, "切换 Unicode / ASCII", TH)
        # The button spans columns 3..20; the old draw wrote 'SCII' past it.
        self.assertEqual(scr.cells[4][20][0], "│")  # right border intact
        self.assertEqual(scr.cells[4][21][0], " ")


try:
    from tests.helpers import HeadlessCase
except ImportError:
    from helpers import HeadlessCase


class QueryCap(HeadlessCase):
    """The query cap bounds paste bursts: an unbounded query made every
    keystroke quadratic over the whole query (matches, casefold, draw)."""

    start_screen = "menu"

    def test_a_paste_is_capped(self):
        from tmb.ui import QUERY_MAX
        self.app.navigate("timbre_select")
        self.press("/")
        for _ in range(300):
            self.press("a")
        self.assertEqual(len(self.screen.query), QUERY_MAX)
        self.assertEqual(self.screen.query, "a" * QUERY_MAX)


if __name__ == "__main__":
    unittest.main()
