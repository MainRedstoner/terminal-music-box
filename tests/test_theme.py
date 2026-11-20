"""Themes: every user-visible string must exist in BOTH languages."""
from __future__ import annotations

import os
import re
import unittest

from tmb import theme

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
USED = re.compile(r"""\.t\(\s*["']([a-zA-Z0-9_.]+)["']""")


class ThemeBasics(unittest.TestCase):
    def test_theme_for_mode(self):
        self.assertIs(theme.theme_for("unicode"), theme.UNICODE_THEME)
        self.assertIs(theme.theme_for("ascii"), theme.ASCII_THEME)
        self.assertIs(theme.theme_for("anything"), theme.UNICODE_THEME)

    def test_unicode_theme_is_chinese_and_rounded(self):
        th = theme.UNICODE_THEME
        self.assertEqual(th.lang, "zh")
        self.assertTrue(th.is_unicode)
        self.assertEqual(th.border, theme.ROUNDED)

    def test_ascii_theme_is_english_and_plain(self):
        th = theme.ASCII_THEME
        self.assertEqual(th.lang, "en")
        self.assertFalse(th.is_unicode)
        self.assertEqual(th.border, theme.PLAIN)
        self.assertEqual(th.border.tl, "+")

    def test_every_key_resolves_in_both_languages(self):
        for th in (theme.UNICODE_THEME, theme.ASCII_THEME):
            for key in th.strings:
                with self.subTest(lang=th.lang, key=key):
                    self.assertNotEqual(th.t(key), key)
                    self.assertTrue(th.t(key).strip())

    def test_chinese_strings_are_actually_chinese(self):
        for key, value in theme.ZH.items():
            if key in ("app.subtitle",):
                continue
            with self.subTest(key=key):
                self.assertTrue(any("\u4e00" <= c <= "\u9fff" for c in value), value)

    def test_format_kwargs(self):
        self.assertEqual(theme.ASCII_THEME.t("rhythm.tap_count", n=3, total=12),
                         "Samples 3/12")
        self.assertIn("3", theme.UNICODE_THEME.t("rhythm.tap_count", n=3, total=12))

    def test_missing_kwargs_do_not_raise(self):
        self.assertEqual(theme.ASCII_THEME.t("rhythm.tap_count"), "Samples {n}/{total}")

    def test_unknown_key_returns_the_key(self):
        self.assertEqual(theme.ASCII_THEME.t("no.such.key"), "no.such.key")


class TranslationCoverage(unittest.TestCase):
    def test_no_chinese_key_is_missing_from_english(self):
        self.assertEqual(set(theme.ZH) - set(theme.EN), set())

    def test_every_key_used_in_source_exists_in_both_tables(self):
        used = set()
        for dirpath, _dirs, files in os.walk(os.path.join(ROOT, "tmb")):
            for name in files:
                if name.endswith(".py"):
                    with open(os.path.join(dirpath, name), "r", encoding="utf-8") as f:
                        used |= set(USED.findall(f.read()))
        self.assertGreater(len(used), 50)
        self.assertEqual(used - set(theme.ZH), set())
        self.assertEqual(used - set(theme.EN), set())

    def test_placeholder_names_match_between_languages(self):
        fields = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")
        for key in set(theme.ZH) & set(theme.EN):
            with self.subTest(key=key):
                self.assertEqual(set(fields.findall(theme.ZH[key])),
                                 set(fields.findall(theme.EN[key])))


if __name__ == "__main__":
    unittest.main()