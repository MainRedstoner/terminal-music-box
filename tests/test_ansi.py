"""Screen cell buffer: wide chars, plain-text snapshots, minimal diff rendering."""
from __future__ import annotations

import re
import unittest

from tmb.ansi import C, CONT, Screen, char_width, text_width

SGR = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")


def visible(ansi: str) -> str:
    return SGR.sub("", ansi)


class Widths(unittest.TestCase):
    def test_char_width(self):
        self.assertEqual(char_width("A"), 1)
        self.assertEqual(char_width(" "), 1)
        self.assertEqual(char_width("中"), 2)
        self.assertEqual(char_width("Ａ"), 2)
        self.assertEqual(char_width(""), 0)

    def test_zero_width_chars(self):
        self.assertEqual(char_width("\u0301"), 0)
        self.assertEqual(char_width("\u200b"), 0)

    def test_text_width(self):
        self.assertEqual(text_width(""), 0)
        self.assertEqual(text_width("abc"), 3)
        self.assertEqual(text_width("A中B"), 4)
        self.assertEqual(text_width("终端音乐盒"), 10)


class Buffer(unittest.TestCase):
    def test_text_marks_continuation_cells(self):
        s = Screen(10, 2)
        end = s.text(0, 0, "中文ab", C.red)
        self.assertEqual(end, 6)
        self.assertEqual([c[0] for c in s.cells[0][:6]], ["中", CONT, "文", CONT, "a", "b"])
        self.assertEqual(s.cells[0][1][1], C.red)

    def test_text_returns_next_free_column(self):
        s = Screen(10, 1)
        self.assertEqual(s.text(2, 0, "ab"), 4)

    def test_text_clips_at_right_edge(self):
        s = Screen(4, 1)
        self.assertEqual(s.text(0, 0, "abcdef"), 4)
        self.assertEqual("".join(c[0] for c in s.cells[0]), "abcd")

    def test_wide_char_at_last_column_does_not_overflow(self):
        s = Screen(3, 1)
        s.text(2, 0, "中")
        self.assertEqual(s.cells[0][2][0], "中")
        self.assertEqual(len(s.cells[0]), 3)

    def test_put_out_of_bounds_is_ignored(self):
        s = Screen(4, 2)
        s.put(-1, 0, "x")
        s.put(4, 0, "x")
        s.put(0, 2, "x")
        s.put(0, -1, "x")
        self.assertEqual(s.plain_text(), "\n")

    def test_zero_width_put_is_ignored(self):
        s = Screen(4, 1)
        s.put(0, 0, "\u0301")
        self.assertEqual(s.cells[0][0][0], " ")

    def test_fill_and_hline(self):
        s = Screen(6, 3)
        s.fill(1, 1, 3, 2, "#", C.blue)
        s.hline(0, 0, 6, "-")
        self.assertEqual(s.plain_text(), "------\n ###\n ###")

    def test_clear_resets_cells(self):
        s = Screen(4, 2)
        s.text(0, 0, "abcd")
        s.clear()
        self.assertEqual(s.plain_text(), "\n")

    def test_plain_text_omits_continuations_and_rstrips(self):
        s = Screen(12, 3)
        s.text(0, 0, "中文ab")
        s.text(0, 2, "  ")
        self.assertEqual(s.plain_text(), "中文ab\n\n")

    def test_in_bounds(self):
        s = Screen(4, 2)
        self.assertTrue(s.in_bounds(3, 1))
        self.assertFalse(s.in_bounds(4, 1))
        self.assertFalse(s.in_bounds(0, -1))


class Render(unittest.TestCase):
    def test_unchanged_frame_renders_nothing(self):
        s = Screen(20, 3)
        s.text(0, 0, "hello", C.green)
        first = s.render()
        self.assertIn("hello", first)
        self.assertEqual(s.render(), "")
        self.assertEqual(s.render(), "")

    def test_only_the_changed_row_is_redrawn(self):
        s = Screen(20, 4)
        for y in range(4):
            s.text(0, y, "row%d" % y)
        s.render()
        s.put(2, 2, "X", C.red)
        out = s.render()
        self.assertEqual(out.count(";1H"), 1)
        self.assertIn("\x1b[3;1H", out)
        self.assertIn("38;5;%d" % C.red, out)

    def test_continuation_cells_are_not_emitted(self):
        s = Screen(4, 1)
        s.text(0, 0, "中")
        out = s.render()
        self.assertEqual(visible(out), "中  ")
        self.assertEqual(visible(out).count("中"), 1)

    def test_resize_forces_full_redraw(self):
        s = Screen(6, 3)
        s.text(0, 0, "abc")
        s.render()
        s.resize(8, 2)
        self.assertEqual((s.w, s.h), (8, 2))
        out = s.render()
        self.assertEqual(out.count(";1H"), 2)
        self.assertEqual(s.plain_text(), "\n")

    def test_bold_and_colors(self):
        s = Screen(6, 1)
        s.text(0, 0, "x", C.gold, C.panel, True)
        out = s.render()
        # Minimal SGR: bold, fg and bg are restated as separate deltas.
        self.assertIn("\x1b[1m", out)
        self.assertIn("\x1b[38;5;%dm" % C.gold, out)
        self.assertIn("\x1b[48;5;%dm" % C.panel, out)

    def test_style_delta_only_restates_changes(self):
        s = Screen(4, 1)
        s.text(0, 0, "a", C.red, None, True)
        s.text(1, 0, "b")  # back to default: bold off + fg default
        out = s.render()
        self.assertIn("38;5;%d" % C.red, out)
        self.assertIn("\x1b[22m", out)
        self.assertIn("\x1b[39m", out)
        # One reset as the frame baseline; styles are never reset per row.
        self.assertEqual(out.count("\x1b[0m"), 1)


if __name__ == "__main__":
    unittest.main()