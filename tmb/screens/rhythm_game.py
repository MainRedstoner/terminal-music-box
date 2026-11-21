"""Rhythm gameplay: 6 falling lanes, tap judgment, auto-played melody."""
from __future__ import annotations

import math
from typing import Dict, List, Optional

from ..ansi import Screen as Buffer, C, text_width
from ..events import KeyEvent, ESC, ENTER, SPACE, UP, DOWN, is_exit
from ..ui import draw_box, draw_button, center_text
from .. import songs
from .base import Screen

LANES = 6
PERFECT_WIN = 0.050
GOOD_WIN = 0.120
REPEAT_TIMEOUT = 0.18  # auto-repeat debounce (POSIX has no key-up events)
APPROACH = 1.6
COUNTDOWN = 3.0
RESULT_TAIL = 1.5
EFFECT_TIME = 0.4
LANE_FLASH = 0.15
PALETTE = [C.cyan, C.green, C.yellow, C.magenta, C.blue, C.pink]


class RhythmGameScreen(Screen):
    def enter(self, song: Optional[str] = None, **kw) -> None:
        self.song_id = song or songs.RHYTHM_ORDER[0]
        self.song = songs.get_song(self.song_id)
        self.beatmap = songs.get_beatmap(self.song_id)
        self.notes = self.beatmap.notes
        keys = list(self.config.rhythm_keys)
        if len(keys) != LANES:
            keys = ["a", "s", "d", "j", "k", "l"]
        self.lane_keys = keys
        self.key_lane: Dict[str, int] = {k: i for i, k in enumerate(keys)}
        self.offset_sec = self.config.latency_ms / 1000.0
        self.scroll_speed = max(0.2, float(self.config.scroll_speed or 1.0))
        self.score = 0
        self.combo = 0
        self.maxcombo = 0
        self.perfect = 0
        self.good = 0
        self.miss = 0
        self.judged = 0
        self.note_state: List[int] = [0] * len(self.notes)  # 0 pending 1 hit 2 miss
        self.key_down: Dict[str, bool] = {}
        self.last_press: Dict[str, float] = {}
        self.clock = 0.0
        self.lane_fx = [0.0] * LANES
        self.fx_time = 0.0
        self.fx_text = ""
        self.fx_color = C.white
        self.song_time = 0.0
        self.countdown = COUNTDOWN
        self.pause_index = 0
        self.grade = "D"
        self.state = "countdown"
        # The melody auto-plays for the whole run; hits are silent judgment
        # only. The player is positioned so each note sounds exactly when its
        # chart note crosses the judgment line (chart = song time + lead_in).
        # A song may lock its timbre (canon always plays the didgeridoo,
        # whatever the free-play keyboard is set to); otherwise the user's
        # choice stands. Preload the score's keys in the background so the
        # auto-play never stalls on a first-use render mid-song.
        self.timbre = self.song.timbre or self.config.timbre
        self.audio.preload(self.timbre,
                           sorted({n.midi for n in self.song.notes}))
        vol, length = self.config.sound_params(self.timbre)
        self.player = songs.SongPlayer(self.audio, self.song, self.timbre,
                                       vol=vol, length=length)
        self.player.start()
        self.player.pos = -self.beatmap.lead_in

    def exit(self) -> None:
        try:
            if self.player is not None:
                self.player.stop()
                self.player = None
        except Exception:
            pass

    def _accuracy(self) -> float:
        return 100.0 * (self.perfect + 0.5 * self.good) / max(1, self.judged)

    def _fx(self, text: str, color: int, lane: int) -> None:
        self.fx_text = text
        self.fx_color = color
        self.fx_time = EFFECT_TIME
        if 0 <= lane < LANES:
            self.lane_fx[lane] = LANE_FLASH

    def _miss(self, lane: int, idx: int) -> None:
        self.note_state[idx] = 2
        self.miss += 1
        self.judged += 1
        self.combo = 0
        self._fx(self.theme.t("rhythm.miss"), C.red, lane)

    def _hit_lane(self, lane: int) -> None:
        ht = self.song_time - self.offset_sec
        best = -1
        bestd = GOOD_WIN + 1.0
        for i, n in enumerate(self.notes):
            if self.note_state[i] != 0 or n.lane != lane:
                continue
            d = abs(n.time - ht)
            if d <= GOOD_WIN and d < bestd:
                bestd = d
                best = i
        if best < 0:
            return
        perfect = bestd <= PERFECT_WIN
        self.note_state[best] = 1
        self.combo += 1
        self.maxcombo = max(self.maxcombo, self.combo)
        mult = 1.0 + min(self.combo, 50) * 0.01
        self.score += int((300 if perfect else 100) * mult)
        if perfect:
            self.perfect += 1
            self._fx(self.theme.t("rhythm.perfect"), C.gold, lane)
        else:
            self.good += 1
            self._fx(self.theme.t("rhythm.good"), C.cyan, lane)
        self.judged += 1

    def _pause(self) -> None:
        self.key_down.clear()
        self.pause_index = 0
        self.state = "pause"

    def _resume(self) -> None:
        self.countdown = COUNTDOWN
        self.state = "countdown"

    def _sync_melody(self) -> None:
        """Position the auto-play so a note sounds as its chart note lands."""
        p = self.player
        if p is None:
            return
        p.pos = self.song_time - self.beatmap.lead_in
        p.update(0.0)

    def _finish(self) -> None:
        a = self._accuracy()
        self.grade = "S" if a >= 95 else "A" if a >= 88 else "B" if a >= 75 else "C" if a >= 60 else "D"
        self.state = "result"
        try:
            if self.player is not None:
                self.player.stop()
                self.player = None
        except Exception:
            pass

    def handle_key(self, ev: KeyEvent) -> None:
        k = ev.key
        if not ev.pressed:
            self.key_down[k] = False
            return
        if self.state == "play":
            if k == ESC:
                self._pause()
            elif is_exit(k):
                return  # only ESC pauses during play; ignore ^Q/^D/^C
            elif k in self.key_lane:
                held = self.key_down.get(k, False)
                self.key_down[k] = True
                self.last_press[k] = self.clock
                # Auto-repeat must not judge twice. Kitty reports it explicitly;
                # Windows/console backends only report a second key-down for a
                # key that is still held, so `held` catches those too.
                if held or ev.repeat:
                    return
                self._hit_lane(self.key_lane[k])
            return
        if self.state == "countdown":
            if k == ESC:
                self._pause()
            return
        if self.state == "pause":
            if is_exit(k):
                self.app.navigate("rhythm_menu")
            elif k == UP:
                self.pause_index = (self.pause_index - 1) % 2
            elif k == DOWN:
                self.pause_index = (self.pause_index + 1) % 2
            elif k in (ENTER, SPACE):
                self._pause_action(self.pause_index)
            return
        if self.state == "result":
            if is_exit(k) or k in (ENTER, SPACE):
                self.app.navigate("rhythm_menu")

    def _pause_action(self, i: int) -> None:
        if i == 0:
            self._resume()
        else:
            self.app.navigate("rhythm_menu")

    def update(self, dt: float) -> None:
        # Sim clock, not wall clock: a slow first-note synth render must not
        # expire the auto-repeat debounce and swallow the next press.
        self.clock += dt
        if self.fx_time > 0:
            self.fx_time = max(0.0, self.fx_time - dt)
        for i in range(LANES):
            if self.lane_fx[i] > 0:
                self.lane_fx[i] = max(0.0, self.lane_fx[i] - dt)
        if not self.app.release_events():
            # Legacy terminals have no key-up: expire the pressed look heuristically.
            for k in list(self.key_down):
                if self.key_down[k] and self.clock - self.last_press.get(k, 0.0) > REPEAT_TIMEOUT:
                    self.key_down[k] = False
        if self.state == "countdown":
            self.countdown -= dt
            if self.countdown <= 0:
                self.state = "play"
            return
        if self.state != "play":
            return
        self.song_time += dt
        self._sync_melody()
        ht = self.song_time - self.offset_sec
        for i, n in enumerate(self.notes):
            if self.note_state[i] == 0 and n.time + GOOD_WIN < ht:
                self._miss(n.lane, i)
        if self.song_time > self.beatmap.duration + RESULT_TAIL:
            self._finish()

    # Drawing -----------------------------------------------------------------

    def draw(self, scr: Buffer) -> None:
        self.hits.clear()
        if self.state == "result":
            self._draw_result(scr)
            return
        self._draw_field(scr)
        if self.state == "countdown":
            self._draw_countdown(scr)
        elif self.state == "pause":
            self._draw_pause(scr)

    def _draw_hud(self, scr: Buffer, w: int) -> None:
        th = self.theme
        scr.text(0, 0, "%s %07d" % (th.t("rhythm.score"), self.score), C.white, None, True)
        acc = "%s %.1f%%" % (th.t("rhythm.accuracy"), self._accuracy())
        scr.text(max(0, w - text_width(acc)), 0, acc, C.cyan)
        combo = str(self.combo)
        scr.text(max(0, (w - text_width(combo)) // 2), 0, combo, C.gold, None, True)
        cl = th.t("rhythm.combo")
        scr.text(max(0, (w - text_width(cl)) // 2), 1, cl, C.dim)
        x = scr.text(0, 1, "P ", C.gold)
        x = scr.text(x, 1, str(self.perfect), C.gold)
        x = scr.text(x, 1, "  G ", C.cyan)
        x = scr.text(x, 1, str(self.good), C.cyan)
        x = scr.text(x, 1, "  M ", C.red)
        scr.text(x, 1, str(self.miss), C.red)
        mx = "%s %d" % (th.t("rhythm.maxcombo"), self.maxcombo)
        scr.text(max(0, w - text_width(mx)), 1, mx, C.gray)

    def _draw_field(self, scr: Buffer) -> None:
        th = self.theme
        w, h = scr.w, scr.h
        uni = th.is_unicode
        field_top = 2
        judge_y = max(field_top + 1, h - 5)
        speed = (judge_y - field_top) / (APPROACH / self.scroll_speed)
        lane_w = max(2, min(8, (w - 2) // LANES))
        field_w = lane_w * LANES
        x0 = max(0, (w - field_w) // 2)
        ht = self.song_time - self.offset_sec
        self._draw_hud(scr, w)
        sep = "│" if uni else "|"
        for i in range(LANES + 1):
            x = x0 + i * lane_w
            for y in range(field_top, judge_y):
                scr.put(x, y, sep, C.dim)
        scr.fill(x0, judge_y, field_w, 1, "═" if uni else "=", C.judge, None, True)
        tap = "█" if uni else "#"
        for i, n in enumerate(self.notes):
            if self.note_state[i] != 0 or n.lane >= LANES:
                continue
            lane = n.lane
            cx = x0 + lane * lane_w + lane_w // 2
            bw = max(1, lane_w - 2)
            bx = cx - bw // 2
            col = PALETTE[lane]
            head_y = int(round(judge_y - (n.time - ht) * speed))
            if field_top <= head_y <= judge_y:
                scr.fill(bx, head_y, bw, 1, tap, col, None, True)
        ky = judge_y + 1
        for lane in range(LANES):
            cx = x0 + lane * lane_w + lane_w // 2
            key = self.lane_keys[lane]
            flash = self.lane_fx[lane] > 0
            down = self.key_down.get(key, False)
            fg = C.gold if flash else (C.white if down else C.cyan)
            bg = C.panel_hi if (flash or down) else None
            scr.put(cx, ky, key.upper(), fg, bg, True)
        if self.fx_time > 0 and self.fx_text:
            center_text(scr, max(field_top, judge_y - 2), self.fx_text, self.fx_color, None, True)
        center_text(scr, h - 2, "Esc " + th.t("rhythm.pause"), C.dim)

    def _draw_countdown(self, scr: Buffer) -> None:
        th = self.theme
        cy = scr.h // 2
        n = max(1, min(3, int(math.ceil(self.countdown))))
        if self.song is not None:
            center_text(scr, cy - 3, self.song.title(th.lang), C.cyan, None, True)
        center_text(scr, cy - 1, str(n), C.gold, None, True)
        center_text(scr, cy + 1, th.t("rhythm.countdown"), C.white)

    def _draw_pause(self, scr: Buffer) -> None:
        th = self.theme
        w, h = scr.w, scr.h
        bw = min(44, max(20, w - 4))
        bh = 9
        bx = max(0, (w - bw) // 2)
        by = max(0, (h - bh) // 2)
        draw_box(scr, bx, by, bw, bh, th, fg=C.cyan, title=th.t("rhythm.pause"), title_fg=C.yellow)
        bxx = bx + 2
        bwi = bw - 4
        draw_button(scr, bxx, by + 2, bwi, 3, th.t("rhythm.resume"), th,
                    selected=self.pause_index == 0, hits=self.hits, action=lambda: self._resume())
        draw_button(scr, bxx, by + 5, bwi, 3, th.t("rhythm.quit_to_list"), th,
                    selected=self.pause_index == 1, hits=self.hits,
                    action=lambda: self.app.navigate("rhythm_menu"))

    def _draw_result(self, scr: Buffer) -> None:
        th = self.theme
        w, h = scr.w, scr.h
        bw = min(52, max(24, w - 4))
        bh = min(h - 2, 15)
        bx = max(0, (w - bw) // 2)
        by = max(0, (h - bh) // 2)
        draw_box(scr, bx, by, bw, bh, th, fg=C.cyan, title=th.t("rhythm.result"), title_fg=C.yellow)
        cx = bx + bw // 2

        def ctext(y: int, s: str, fg: int, bold: bool = False) -> None:
            scr.text(max(bx + 1, cx - text_width(s) // 2), y, s, fg, None, bold)

        if self.song is not None:
            ctext(by + 1, self.song.title(th.lang), C.white, True)
        gc = {"S": C.gold, "A": C.green, "B": C.cyan, "C": C.yellow, "D": C.red}.get(self.grade, C.white)
        ctext(by + 3, th.t("rhythm.grade"), C.dim)
        ctext(by + 4, self.grade, gc, True)
        ctext(by + 6, "%s %07d" % (th.t("rhythm.score"), self.score), C.white)
        ctext(by + 7, "%s %.1f%%" % (th.t("rhythm.accuracy"), self._accuracy()), C.cyan)
        ctext(by + 8, "%s %d" % (th.t("rhythm.maxcombo"), self.maxcombo), C.gray)
        ctext(by + 9, "P %d   G %d   M %d" % (self.perfect, self.good, self.miss), C.gray)
        btnw = min(20, bw - 4)
        draw_button(scr, cx - btnw // 2, by + bh - 4, btnw, 3, th.t("common.back"), th,
                    selected=True, hits=self.hits, action=lambda: self.app.navigate("rhythm_menu"))
        center_text(scr, h - 1, th.t("freeplay.exit_hint"), C.dim)