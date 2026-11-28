"""Rhythm meta screens: song list, latency calibration, key config."""
from __future__ import annotations

from statistics import median

from ..ansi import Screen as Buffer, C, text_width
from ..events import (KeyEvent, ENTER, SPACE, TAB, BACKSPACE, is_exit,
                      UP, DOWN, LEFT, RIGHT)
from ..ui import (center_text, draw_box, draw_button, draw_menu_row,
                  draw_search_field, draw_search_result_row, matches,
                  QUERY_MAX)

# Auto-repeat debounce for the calibration screen on legacy terminals (no
# key-up events). Above the common OS repeat delay (~0.25 s on Windows) so a
# physical hold registers once; still well under the 0.6 s beat period, so
# genuine on-beat taps are never swallowed.
REPEAT_TIMEOUT = 0.3
from .base import Screen
from .. import songs


class RhythmMenuScreen(Screen):
    """Two panes: a wide song selector and a compact settings column.

    The song list is grouped under 内置音乐 / 外部音乐 headers; the external
    packs below are .tmbp files (chart + audio) from external_songs/ and are
    gated on their audio being decoded, like built-in songs gate on buffer
    pre-rendering. '/' opens a live search over both groups; a group's header
    stays visible as long as any song under it matches.
    """

    def enter(self, **kw):
        self.focus = 0  # 0 = songs, 1 = functions
        self.song_index = 0
        self.function_index = 0
        self.function_ids = ["rhythm_calib", "rhythm_keys"]
        self._pending_song = None
        self._pending_pack = None
        self.notice = ""
        self.searching = False
        self.query = ""
        self.app.external.refresh()
        self._rebuild()

    def _rebuild(self) -> None:
        ext = self.app.external
        self.all_rows: list = [("header", "rhythm.builtin")]
        self.all_rows += [("song", sid, None) for sid in songs.RHYTHM_ORDER]
        self.all_rows.append(("header", "rhythm.external"))
        if ext.packs:
            self.all_rows += [("song", pack.id, pack) for pack in ext.packs]
        else:
            self.all_rows.append(("hint", "rhythm.external_empty"))
        self._apply_query()

    def _song_aliases(self, row) -> list:
        sid, pack = row[1], row[2]
        if pack is not None:
            return [pack.title_zh, pack.title_en, pack.artist, pack.id]
        song = songs.SONGS[sid]
        return [song.title_zh, song.title_en, sid]

    def _apply_query(self) -> None:
        """Recompute the visible rows from the query, keeping group headers.

        While filtering, a group's header only appears when at least one song
        under it matches, and the empty-external hint is dropped.
        """
        q = self.query.casefold()
        rows: list = []
        if q:
            header = None
            header_shown = False
            for r in self.all_rows:
                if r[0] == "header":
                    header, header_shown = r, False
                elif r[0] == "song" and matches(q, self._song_aliases(r)):
                    if header is not None and not header_shown:
                        rows.append(header)
                        header_shown = True
                    rows.append(r)
        else:
            rows = self.all_rows
        self.rows = rows
        self.song_rows = [i for i, r in enumerate(rows) if r[0] == "song"]
        self.song_ids = [rows[i][1] for i in self.song_rows]
        self.row_of_song = {row: idx for idx, row in enumerate(self.song_rows)}
        self.song_total = sum(1 for r in self.all_rows if r[0] == "song")
        self.song_index = min(self.song_index, max(0, len(self.song_rows) - 1))
        self.row_scroll = 0

    def _move(self, step: int) -> None:
        if self.focus == 0:
            n = len(self.song_rows)
            if n:
                self.song_index = (self.song_index + step) % n
        else:
            self.function_index = ((self.function_index + step)
                                   % len(self.function_ids))

    def _start_song(self, index: int) -> None:
        self.focus = 0
        self.song_index = index
        if not self.song_rows:
            return
        sid, pack = self.rows[self.song_rows[index]][1:]
        if pack is None:
            if self._song_ready(sid):
                self._pending_song = None
                self._pending_pack = None
                self.app.navigate("rhythm_game", song=sid)
                return
            # A pack left pending from an earlier Enter must not win once the
            # user has picked a built-in song: update() branches on
            # _pending_pack first and would start that pack when it decoded.
            self._pending_song = sid
            self._pending_pack = None
            timbre, midis = self._song_audio(sid)
            self.audio.preload(timbre, midis)
            return
        ext = self.app.external
        if not ext.can_decode(pack):
            self.notice = self.theme.t("rhythm.need_ffmpeg")
            return
        self.notice = ""
        if ext.is_ready(pack.id):
            self._pending_song = None
            self._pending_pack = None
            self.app.navigate("rhythm_game", song=pack.id, pack=pack)
            return
        self._pending_song = pack.id
        self._pending_pack = pack
        if not ext.start_decode(pack.id):
            # Another pack's decode holds the single slot; ours starts when
            # it finishes (update's healing path fires it). Say so, or the
            # silent wait is indistinguishable from a hang — and the loading
            # overlay shows the OTHER pack's progress meanwhile.
            self.notice = self.theme.t("rhythm.decode_queued")

    def _song_audio(self, sid: str):
        song = songs.SONGS[sid]
        timbre = song.timbre or self.config.timbre
        midis = sorted({n.midi for n in song.notes})
        return timbre, midis

    def _song_ready(self, sid: str) -> bool:
        # Headless/offline runs have no playback thread to stall, so they can
        # start immediately; the gate is for real audio.
        if not self.audio.realtime:
            return True
        timbre, midis = self._song_audio(sid)
        return self.audio.is_preloaded(timbre, midis)

    def update(self, dt: float) -> None:
        sid = self._pending_song
        if sid is None:
            return
        pack = self._pending_pack
        if pack is None:
            if self._song_ready(sid):
                self._pending_song = None
                self.app.navigate("rhythm_game", song=sid)
                return
            # Healing: if the last request ran to completion but the gate is
            # still shut, kick preload again instead of waiting forever.
            active, done, total = self.audio.preload_status()
            if not active and total > 0 and done >= total:
                timbre, midis = self._song_audio(sid)
                self.audio.preload(timbre, midis)
            return
        ext = self.app.external
        if ext.is_ready(pack.id):
            self._pending_song = None
            self._pending_pack = None
            self.app.navigate("rhythm_game", song=pack.id, pack=pack)
            return
        err = ext.error(pack.id)
        if err:
            self._pending_song = None
            self._pending_pack = None
            self.notice = self.theme.t("rhythm.external_error", msg=err)
            return
        # Healing: a decode request that neither finished nor errored is dead.
        active, _done, _total = ext.status()
        if not active and ext.start_decode(pack.id):
            self.notice = ""  # the queued decode is finally running

    def exit(self) -> None:
        self._pending_song = None
        self._pending_pack = None

    def _start_function(self, index: int) -> None:
        self.focus = 1
        self.function_index = index
        self._pending_song = None
        self._pending_pack = None
        self.app.navigate(self.function_ids[index])

    def _activate(self) -> None:
        if self.focus == 0:
            if self.song_rows:
                self._start_song(self.song_index)
        else:
            self._start_function(self.function_index)

    def handle_key(self, ev: KeyEvent) -> None:
        if not ev.pressed:
            return
        k = ev.key
        if self.searching:
            if is_exit(k):
                # Esc cancels the search itself; a second Esc leaves the menu.
                self.searching = False
                self.query = ""
                self._apply_query()
                return
            if k == BACKSPACE:
                self.query = self.query[:-1]
                self._apply_query()
                return
            if k == SPACE:
                self.query = (self.query + " ")[-QUERY_MAX:]
                self._apply_query()
                return
            if len(k) == 1:
                self.query = (self.query + k)[-QUERY_MAX:]
                self._apply_query()
                return
            if k == UP:
                self._move(-1)
            elif k == DOWN:
                self._move(1)
            elif k == ENTER:
                self._activate()
            return
        if k == "/":
            self.focus = 0  # search always targets the song list
            self.searching = True
        elif is_exit(k):
            self.app.navigate("menu")
        elif k in (LEFT, RIGHT, TAB):
            self.focus = 1 - self.focus
        elif k == UP:
            self._move(-1)
        elif k == DOWN:
            self._move(1)
        elif k in (ENTER, SPACE):
            self._activate()

    # Drawing -----------------------------------------------------------------

    def _draw_header(self, scr: Buffer, x: int, y: int, w: int,
                     key: str, th) -> None:
        h = th.border.h
        line = "%s %s " % (h * 2, th.t(key))
        rest = max(0, w - text_width(line))
        scr.text(x, y, line + h * rest, C.yellow, None, True)

    def draw(self, scr: Buffer) -> None:
        self.hits.clear()
        th = self.theme
        w, h = scr.w, scr.h
        if w < 16 or h < 7:
            if w and h:
                center_text(scr, min(h - 1, h // 2), th.t("rhythm.title"),
                            C.yellow, None, True)
            return

        total_w = min(w - 4, 100)
        gap = 2
        usable = total_w - gap
        song_w = (usable * 2) // 3
        function_w = usable - song_w
        x = (w - total_w) // 2
        top = 2
        box_h = h - top - 2
        rows = max(0, box_h - 2)
        song_active = self.focus == 0

        draw_box(scr, x, top, song_w, box_h, th,
                 fg=C.cyan if song_active else C.dim,
                 title=th.t("rhythm.list"),
                 title_fg=C.yellow if song_active else C.gray)
        fx = x + song_w + gap
        draw_box(scr, fx, top, function_w, box_h, th,
                 fg=C.cyan if not song_active else C.dim,
                 title=th.t("rhythm.functions"),
                 title_fg=C.yellow if not song_active else C.gray)

        lang = th.lang
        list_rows = rows
        list_y = top + 1
        if self.searching:
            fw = draw_search_field(scr, x + 1, list_y, song_w - 2, self.query, th)
            if len(self.song_rows) != self.song_total and fw + 7 <= song_w - 2:
                scr.text(x + 1 + fw + 1, list_y,
                         "%d/%d" % (len(self.song_rows), self.song_total), C.dim)
            list_y += 1
            list_rows = max(0, rows - 1)
        sel_row = self.song_rows[self.song_index] if self.song_rows else 0
        if sel_row < self.row_scroll:
            self.row_scroll = sel_row
        if list_rows and sel_row >= self.row_scroll + list_rows:
            self.row_scroll = sel_row - list_rows + 1
        for r in range(list_rows):
            i = self.row_scroll + r
            if i >= len(self.rows):
                break
            y = list_y + r
            row = self.rows[i]
            if row[0] == "header":
                self._draw_header(scr, x + 1, y, song_w - 2, row[1], th)
            elif row[0] == "hint":
                scr.text(x + 3, y, "  " + th.t(row[1]), C.dim)
            else:
                idx = self.row_of_song[i]
                item = row[2] or songs.SONGS[row[1]]
                if self.searching:
                    # Full name in both languages, matches highlighted.
                    draw_search_result_row(
                        scr, x + 1, y, song_w - 2, item.title(lang),
                        item.title("en" if lang == "zh" else "zh"),
                        self.query, song_active and idx == self.song_index, th,
                        hits=self.hits,
                        action=(lambda k=idx: self._start_song(k)),
                    )
                else:
                    draw_menu_row(
                        scr, x + 1, y, song_w - 2, item.title(lang),
                        song_active and idx == self.song_index, th,
                        fg=C.white if song_active else C.gray, hits=self.hits,
                        action=(lambda k=idx: self._start_song(k)),
                    )
        if self.searching and not self.song_rows:
            scr.text(x + 3, list_y, th.t("search.no_match"), C.dim)

        labels = [th.t("rhythm.calibration"), th.t("rhythm.keys")]
        for i, label in enumerate(labels[:rows]):
            draw_menu_row(
                scr, fx + 1, top + 1 + i, function_w - 2, label,
                not song_active and i == self.function_index, th,
                fg=C.white if not song_active else C.gray, hits=self.hits,
                action=(lambda idx=i: self._start_function(idx)),
            )

        if self.notice:
            center_text(scr, h - 2, self.notice, C.red)
        else:
            center_text(scr, h - 2, th.t("rhythm.menu_hint"), C.dim)


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
        self._held: set = set()
        self._last_tap: dict = {}

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
            self._held.discard(ev.key)
            return
        k = ev.key
        if is_exit(k):
            self.app.navigate("rhythm_menu")
        elif k == "r":
            self._reset()
        elif not self.done:
            if ev.repeat:
                return
            if self.app.release_events():
                if k in self._held:
                    return  # still held: auto-repeat without a repeat flag
                self._held.add(k)
            else:
                # No key-up events: a hold is only visible as the burst of
                # repeats it produces, so time-debounce each key like the
                # game screen does. One physical hold must not fill the
                # whole sample set with garbage offsets.
                if self.clock - self._last_tap.get(k, -1e9) < REPEAT_TIMEOUT:
                    return
            self._last_tap[k] = self.clock
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
        self._held = set()
        self._last_tap = {}
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
                    hits=self.hits, action=lambda: self.app.navigate("rhythm_menu"))
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
            self.app.navigate("rhythm_menu")
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
                    hits=self.hits, action=lambda: self.app.navigate("rhythm_menu"))
        center_text(scr, h - 2, th.t("freeplay.exit_hint"), C.dim)