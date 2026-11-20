"""Per-timbre sound settings: volume and note length, live preview."""
from __future__ import annotations

from typing import List

from ..ansi import Screen as Buffer, C, text_width
from ..config import LEN_RANGE, VOL_RANGE
from ..audio import synth
from ..events import KeyEvent, MouseEvent, is_exit, UP, DOWN, LEFT, RIGHT
from ..ui import center_text, draw_box, draw_menu_row
from .base import Screen

PREVIEW_MIDI = 64  # E4
VOL_STEP = 0.1
LEN_STEP = 0.25
BAR_SLOTS = 8
NAME_W = 12


class SoundSettingsScreen(Screen):
    def enter(self, **kw) -> None:
        self.order: List[str] = list(synth.ORDER)
        self.index = min(getattr(self, "index", 0), len(self.order) - 1)
        self.scroll = 0
        self.status = ""

    def exit(self) -> None:
        self.audio.stop_all()

    # Adjustments -------------------------------------------------------------

    def _max_len(self, tid: str) -> float:
        # Ringing timbres cannot be extended past their natural buffer;
        # sustained ones can be assembled up to 4x.
        return LEN_RANGE[1] if synth.get_timbre(tid).sustain else 1.0

    def _step_vol(self, delta: float) -> None:
        tid = self.order[self.index]
        vol, ln = self.config.sound_params(tid)
        self.config.set_sound(tid, vol=vol + delta, ln=ln)
        self.config.save()
        self.status = ""

    def _step_len(self, delta: float) -> None:
        tid = self.order[self.index]
        vol, ln = self.config.sound_params(tid)
        ln = min(self._max_len(tid), max(LEN_RANGE[0], ln + delta))
        self.config.set_sound(tid, vol=vol, ln=ln)
        self.config.save()
        self.status = ""

    def _reset(self) -> None:
        tid = self.order[self.index]
        self.config.sound.pop(tid, None)
        self.config.save()
        self.status = self.theme.t("sound.reset_done")

    def _preview(self) -> None:
        tid = self.order[self.index]
        vol, ln = self.config.sound_params(tid)
        self.audio.stop_all()
        self.audio.play_note(tid, PREVIEW_MIDI, 1.0, vol, length=ln)

    # Input -------------------------------------------------------------------

    def handle_key(self, ev: KeyEvent) -> None:
        if not ev.pressed:
            return
        k = ev.key
        n = len(self.order)
        if is_exit(k):
            self.app.navigate("menu")
        elif k == UP:
            self.index = (self.index - 1) % n
        elif k == DOWN:
            self.index = (self.index + 1) % n
        elif k == LEFT:
            self._step_vol(-VOL_STEP)
        elif k == RIGHT:
            self._step_vol(VOL_STEP)
        elif k == "a":
            self._step_len(-LEN_STEP)
        elif k == "d":
            self._step_len(LEN_STEP)
        elif k in ("enter", "space"):
            self._preview()
        elif k == "r":
            self._reset()

    def handle_mouse(self, ev: MouseEvent) -> None:
        if ev.kind != "press":
            return
        action = self.hits.hit(ev.x, ev.y)
        if action is not None:
            action()

    def _select(self, i: int) -> None:
        self.index = i

    # Drawing -----------------------------------------------------------------

    def _pad(self, s: str, width: int) -> str:
        gap = width - text_width(s)
        return s + " " * max(0, gap)

    def _bar(self, value: float, lo: float, hi: float, uni: bool) -> str:
        frac = (value - lo) / max(1e-9, hi - lo)
        full = max(0, min(BAR_SLOTS, int(round(frac * BAR_SLOTS))))
        on, off = ("█", "░") if uni else ("#", "-")
        return on * full + off * (BAR_SLOTS - full)

    def _row_label(self, tid: str, th) -> str:
        vol, ln = self.config.sound_params(tid)
        name = synth.timbre_name(tid, th.lang)
        return "%s  %s %.1f   %s %.2f×" % (
            self._pad(name, NAME_W),
            self._bar(vol, *VOL_RANGE, th.is_unicode), vol,
            self._bar(ln, LEN_RANGE[0], self._max_len(tid), th.is_unicode), ln)

    def draw(self, scr: Buffer) -> None:
        self.hits.clear()
        th = self.theme
        w, h = scr.w, scr.h
        bw = min(w - 4, 62)
        bx = (w - bw) // 2
        top = 2
        bh = h - top - 2
        if bh < 5:
            return
        draw_box(scr, bx, top, bw, bh, th, fg=C.cyan,
                 title=th.t("sound.title"), title_fg=C.yellow)
        hint_y = top + bh - 2
        status_y = hint_y - 1
        rows = max(1, status_y - (top + 2))
        self.scroll = max(0, min(self.scroll, self.index - rows + 1))
        self.scroll = min(self.scroll, max(0, len(self.order) - rows))
        y = top + 2
        for i in range(self.scroll, len(self.order)):
            if y > status_y - 1 or y >= h:
                break
            tid = self.order[i]
            draw_menu_row(scr, bx + 1, y, bw - 2, self._row_label(tid, th),
                          i == self.index, th, hits=self.hits,
                          action=(lambda idx=i: self._select(idx)))
            y += 1
        if self.status:
            center_text(scr, status_y, self.status, C.green)
        center_text(scr, hint_y, th.t("sound.hint"), C.dim)
