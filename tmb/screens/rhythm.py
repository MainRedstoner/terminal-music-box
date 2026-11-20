"""Rhythm meta screens: song list, latency calibration, key config."""
from __future__ import annotations

from statistics import median

from ..ansi import Screen as Buffer, C
from ..events import KeyEvent, is_exit, UP, DOWN, LEFT, RIGHT
from ..ui import center_text, draw_box, draw_button, draw_menu_row
from .base import Screen, ListScreen
from .. import songs


class RhythmListScreen(ListScreen):
    def enter(self, **kw):
        lang = self.theme.lang
        ids = list(songs.ORDER)
        self.title = self.theme.t("rhythm.list")
        self.back_target = "menu"
        items = [self.theme.t("rhythm.calibration"), self.theme.t("rhythm.keys")]
        actions = [lambda: self.app.navigate("rhythm_calib"),
                   lambda: self.app.navigate("rhythm_keys")]
        items += [songs.SONGS[s].title(lang) for s in ids]
        actions += [(lambda sid=s: self.app.navigate("rhythm_game", song=sid)) for s in ids]
        self.set_items(items, actions)
        self.footer = self.theme.t("freeplay.exit_hint")


class RhythmCalibScreen(Screen):
    BPM = 100
    PERIOD = 60.0 / BPM
    TARGET = 12

    def enter(self, **kw) -> None:
        self.clock = 0.0
        self._beat = 0
        self.offsets = []
        self.last_off = None
        self.done = False
        self.status = ""
        self.status_fg = C.green

    def exit(self) -> None:
        self.audio.stop_all()

    def update(self, dt: float) -> None:
        if self.done:
            return
        self.clock += dt
        while self._beat * self.PERIOD <= self.clock:
            midi = 88 if self._beat % 4 == 0 else 84
            self.audio.play_note("bit", midi, 0.08)
            self._beat += 1

    def handle_key(self, ev: KeyEvent) -> None:
        if not ev.pressed:
            return
        k = ev.key
        if is_exit(k):
            self.app.navigate("rhythm_list")
        elif k == "r":
            self._reset()
        elif not self.done:
            self._tap()

    def _tap(self) -> None:
        nearest = round(self.clock / self.PERIOD) * self.PERIOD
        off = self.clock - nearest
        self.last_off = off
        self.offsets.append(off)
        if len(self.offsets) >= self.TARGET:
            self.done = True
            ms = round(median(self.offsets) * 1000)
            self.config.latency_ms = ms
            self.config.save()
            self.status = self.theme.t("rhythm.calib_done", ms=ms)
            self.status_fg = C.green

    def _reset(self) -> None:
        self.config.latency_ms = 0
        self.config.save()
        self.offsets = []
        self.last_off = None
        self.done = False
        self.clock = 0.0
        self._beat = 0
        self.status = self.theme.t("rhythm.calib_reset")
        self.status_fg = C.yellow

    def draw(self, scr: Buffer) -> None:
        self.hits.clear()
        th = self.theme
        w, h = scr.w, scr.h
        bw = min(w - 4, 64)
        bx = (w - bw) // 2
        top = 2
        bh = h - top - 2
        draw_box(scr, bx, top, bw, bh, th, fg=C.cyan,
                 title=th.t("rhythm.latency"), title_fg=C.yellow)
        by = top + bh - 4
        phase = (self.clock % self.PERIOD) / self.PERIOD if not self.done else 0.0
        on = not self.done and phase < 0.2
        est = round(median(self.offsets) * 1000) if self.offsets else self.config.latency_ms
        y = top + 1

        def row(s, fg, bold=False):
            nonlocal y
            if y < by and s:
                center_text(scr, y, s, fg, None, bold)
            y += 1

        row(th.t("rhythm.latency_hint"), C.cyan)
        row("" if self.done else th.t("rhythm.press_any"), C.dim)
        y += 1
        lamp = ("●" if on else "○") if th.is_unicode else ("*" if on else "o")
        if self.last_off is not None:
            lamp += "  %+d ms" % round(self.last_off * 1000)
        row(lamp, C.yellow if on else C.gray, True)
        if y < by:
            barw = min(bw - 8, 30)
            nfill = int(phase * barw)
            x = bx + (bw - barw) // 2
            fc, ec = ("█", "░") if th.is_unicode else ("#", "-")
            scr.text(x, y, fc * nfill, C.cyan)
            scr.text(x + nfill, y, ec * (barw - nfill), C.dim)
        y += 2
        row(th.t("rhythm.tap_count", n=len(self.offsets), total=self.TARGET), C.white)
        row(th.t("rhythm.offset_ms", ms=est), C.gold)
        y += 1
        row(self.status, self.status_fg)

        rw = 14 if bw >= 34 else max(6, (bw - 6) // 2)
        kw = 12 if bw >= 34 else max(6, bw - 6 - rw)
        x0 = bx + (bw - rw - 2 - kw) // 2
        reset = "R 重置" if th.is_unicode else "R Reset"
        draw_button(scr, x0, by, rw, 3, reset, th,
                    hits=self.hits, action=self._reset)
        draw_button(scr, x0 + rw + 2, by, kw, 3, th.t("common.back"), th,
                    hits=self.hits, action=lambda: self.app.navigate("rhythm_list"))
        center_text(scr, h - 2, th.t("freeplay.exit_hint"), C.dim)


class RhythmKeysScreen(Screen):
    def enter(self, **kw) -> None:
        self.keys = list(self.config.rhythm_keys)
        self.index = 0
        self.status = ""

    def handle_key(self, ev: KeyEvent) -> None:
        if not ev.pressed:
            return
        k = ev.key
        n = len(self.keys)
        if is_exit(k):
            self.app.navigate("rhythm_list")
        elif k in (UP, LEFT):
            self.index = (self.index - 1) % n
        elif k in (DOWN, RIGHT):
            self.index = (self.index + 1) % n
        elif ev.letter and not ev.is_ctrl:
            self._bind(ev.letter.lower())

    def _select(self, i: int) -> None:
        self.index = i

    def _bind(self, letter: str) -> None:
        i = self.index
        swapped = False
        if letter in self.keys:
            j = self.keys.index(letter)
            if j != i:
                self.keys[i], self.keys[j] = self.keys[j], self.keys[i]
                swapped = True
        self.keys[i] = letter
        self.config.rhythm_keys = list(self.keys)
        self.config.save()
        th = self.theme
        self.status = th.t("rhythm.key_saved")
        if swapped:
            self.status += ("（已交换）" if th.is_unicode else " (swapped)")

    def draw(self, scr: Buffer) -> None:
        self.hits.clear()
        th = self.theme
        w, h = scr.w, scr.h
        bw = min(w - 4, 56)
        bx = (w - bw) // 2
        top = 2
        bh = h - top - 2
        draw_box(scr, bx, top, bw, bh, th, fg=C.cyan,
                 title=th.t("rhythm.keys"), title_fg=C.yellow)
        by = top + bh - 4
        b = th.border
        y = top + 1
        if y < by:
            center_text(scr, y, th.t("rhythm.keys_hint"), C.cyan)
        y += 2
        for i, key in enumerate(self.keys):
            if y >= by:
                break
            cap = "%s %s %s" % (b.v, key.upper(), b.v)
            label = "%s   %s" % (th.t("rhythm.key_lane", i=i + 1), cap)
            draw_menu_row(scr, bx + 2, y, bw - 4, label, i == self.index, th,
                          hits=self.hits, action=(lambda idx=i: self._select(idx)))
            y += 1
        y += 1
        if self.status and y < by:
            center_text(scr, y, self.status, C.green)
        btnw = min(12, bw - 4)
        draw_button(scr, bx + (bw - btnw) // 2, by, btnw, 3, th.t("common.back"), th,
                    hits=self.hits, action=lambda: self.app.navigate("rhythm_list"))
        center_text(scr, h - 2, th.t("freeplay.exit_hint"), C.dim)