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
        ids = list(songs.RHYTHM_ORDER)
        items = [songs.SONGS[s].title(lang) for s in ids]
        actions = [(lambda sid=s: self._pick(sid)) for s in ids]
        self.set_items(items, actions)
        cur = selected if selected is not None else self.config.prenatal_song
        if cur in ids:
            self.index = ids.index(cur)
        self.footer = self.theme.t("freeplay.exit_hint")

    def _pick(self, sid: str) -> None:
        self.config.prenatal_song = sid
        self.config.save()
        if self._on_select:
            self._on_select(sid)
        self.app.navigate(self.back_target)