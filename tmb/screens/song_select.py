"""Generic song picker used by prenatal mode (^A) and reusable elsewhere."""
from __future__ import annotations

from typing import Callable, Optional

from .. import songs
from .base import ListScreen


class SongSelectScreen(ListScreen):
    def enter(self, on_select: Optional[Callable] = None, back: str = "freeplay",
              title: Optional[str] = None, selected: Optional[str] = None):
        self._on_select = on_select
        self.back_target = back
        self.title = title or self.theme.t("song.select")
        lang = self.theme.lang
        other = "en" if lang == "zh" else "zh"
        ids = list(songs.RHYTHM_ORDER)
        items = [songs.SONGS[s].title(lang) for s in ids]
        # Search rows show the full name in both languages, matches highlighted.
        sublabels = [songs.SONGS[s].title(other) for s in ids]
        # Searchable in both languages whatever the UI language: every song
        # carries its Chinese and English title plus its id.
        keywords = []
        for s in ids:
            song = songs.SONGS[s]
            keywords.append([song.title_zh, song.title_en, s])
        actions = [(lambda sid=s: self._pick(sid)) for s in ids]
        self.set_items(items, actions, keywords, sublabels)
        cur = selected if selected is not None else self.config.prenatal_song
        if cur in ids:
            self.index = ids.index(cur)
        self.footer = self.theme.t("list.hint")

    def _pick(self, sid: str) -> None:
        self.config.prenatal_song = sid
        self.config.save()
        if self._on_select:
            self._on_select(sid)
        self.app.navigate(self.back_target)