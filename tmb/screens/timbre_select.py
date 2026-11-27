"""Timbre picker opened from free play (^X): a searchable list, not a cycle."""
from __future__ import annotations

from typing import Callable, Optional

from ..audio import synth
from .base import ListScreen


class TimbreSelectScreen(ListScreen):
    def enter(self, on_select: Optional[Callable] = None, back: str = "freeplay",
              selected: Optional[str] = None):
        self._on_select = on_select
        self.back_target = back
        self.title = self.theme.t("timbre.select")
        lang = self.theme.lang
        other = "en" if lang == "zh" else "zh"
        ids = list(synth.ORDER)
        items = [synth.timbre_name(t, lang) for t in ids]
        # Search rows show the full name in both languages, matches highlighted.
        sublabels = [synth.timbre_name(t, other) for t in ids]
        # Searchable in both languages whatever the UI language: every timbre
        # carries its Chinese and English name plus its id.
        keywords = [[tim.name_zh, tim.name_en, tim.id]
                    for tim in (synth.get_timbre(t) for t in ids)]
        actions = [(lambda tid=t: self._pick(tid)) for t in ids]
        self.set_items(items, actions, keywords, sublabels)
        cur = selected if selected is not None else self.config.timbre
        if cur in ids:
            self.index = ids.index(cur)
        self.footer = self.theme.t("list.hint")

    def _pick(self, tid: str) -> None:
        self.config.timbre = tid
        self.config.save()
        if self._on_select:
            self._on_select(tid)
        self.app.navigate(self.back_target)
