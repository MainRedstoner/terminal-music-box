"""Generic song picker: localization, selection, callback, back target, scrolling."""
from __future__ import annotations

import unittest

from tmb import songs

try:
    from tests.helpers import HeadlessCase
except ImportError:
    from helpers import HeadlessCase


class SongSelect(HeadlessCase):
    def open(self, **kw):
        self.app.navigate("song_select", **kw)
        self.app.step(0.016)
        return self.app.current

    def test_items_are_the_rhythm_songs_in_order(self):
        s = self.open()
        self.assertEqual(s.items, [songs.SONGS[sid].title("zh")
                                   for sid in songs.RHYTHM_ORDER])
        self.assertEqual(len(s.actions), len(songs.RHYTHM_ORDER))
        self.assertEqual(s.title, self.app.theme.t("song.select"))

    def test_index_defaults_to_the_configured_song(self):
        self.cfg.prenatal_song = "fur_elise"
        s = self.open()
        self.assertEqual(s.index, songs.RHYTHM_ORDER.index("fur_elise"))

    def test_selected_kwarg_overrides_the_config(self):
        self.cfg.prenatal_song = "canon"
        s = self.open(selected="turkish_march")
        self.assertEqual(s.index, songs.RHYTHM_ORDER.index("turkish_march"))

    def test_unknown_selection_keeps_index_zero(self):
        s = self.open(selected="nope")
        self.assertEqual(s.index, 0)

    def test_song_outside_the_rhythm_list_keeps_index_zero(self):
        self.cfg.prenatal_song = "twinkle"
        s = self.open()
        self.assertEqual(s.index, 0)

    def test_picking_saves_the_config_and_calls_back(self):
        seen = []
        self.open(on_select=seen.append, back="menu")
        self.press("down")
        self.press("enter")
        sid = songs.RHYTHM_ORDER[1]
        self.assertEqual(seen, [sid])
        self.assertEqual(self.cfg.prenatal_song, sid)
        self.assertEqual(self.read_config()["prenatal_song"], sid)
        self.assertEqual(self.app.current_name, "menu")

    def test_default_back_target_is_freeplay(self):
        self.open()
        self.press("enter")
        self.assertEqual(self.app.current_name, "freeplay")
        self.assertEqual(self.cfg.prenatal_song, songs.RHYTHM_ORDER[0])

    def test_escape_leaves_the_choice_untouched(self):
        seen = []
        self.cfg.prenatal_song = "canon"
        self.open(on_select=seen.append, back="menu")
        self.press("down")
        self.press("esc")
        self.assertEqual(self.app.current_name, "menu")
        self.assertEqual(seen, [])
        self.assertEqual(self.cfg.prenatal_song, "canon")

    def test_mouse_click_picks_the_clicked_row(self):
        seen = []
        self.open(on_select=seen.append, back="menu")
        self.click_label(songs.SONGS["fur_elise"].title("zh"))
        self.assertEqual(seen, ["fur_elise"])
        self.assertEqual(self.app.current_name, "menu")

    def test_home_end_and_page_keys(self):
        s = self.open()
        self.press("end")
        self.assertEqual(s.index, len(songs.RHYTHM_ORDER) - 1)
        self.press("home")
        self.assertEqual(s.index, 0)
        self.press("pgdn")
        self.assertEqual(s.index, min(5, len(songs.RHYTHM_ORDER) - 1))
        self.press("pgup")
        self.assertEqual(s.index, 0)

    def test_custom_title_is_drawn(self):
        self.open(title="自定义标题")
        self.assertIn("自定义标题", self.frame)

    def test_footer_shows_the_exit_hint(self):
        self.open()
        self.assertIn(self.app.theme.t("freeplay.exit_hint"), self.frame)


class SongSelectAscii(HeadlessCase):
    mode = "ascii"

    def test_english_titles(self):
        self.app.navigate("song_select")
        self.step()
        self.assertEqual(self.screen.items,
                         [songs.SONGS[sid].title("en") for sid in songs.RHYTHM_ORDER])
        self.assertIn("Canon in C", self.frame)


class SongSelectShort(HeadlessCase):
    height = 9

    def test_scrolls_to_keep_the_selection_visible(self):
        self.app.navigate("song_select", back="menu")
        s = self.screen
        for _ in range(len(songs.RHYTHM_ORDER) - 1):
            self.press("down")
        self.assertEqual(s.index, len(songs.RHYTHM_ORDER) - 1)
        self.assertGreater(s.scroll, 0)
        self.assertIn(s.items[s.index], self.frame)
        self.press("enter")
        self.assertEqual(self.cfg.prenatal_song, songs.RHYTHM_ORDER[-1])
        self.assertEqual(self.app.current_name, "menu")


if __name__ == "__main__":
    unittest.main()