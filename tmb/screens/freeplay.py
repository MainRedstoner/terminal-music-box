"""Free play: 21-key C-major keyboard, timbre cycling, prenatal mode."""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from ..ansi import Screen as Buffer, C, char_width, text_width
from ..events import KeyEvent, MouseEvent, is_exit
from ..ui import center_text, draw_box, draw_button
from .. import songs
from ..audio import synth
from .base import Screen

ROWS: Tuple[Tuple[str, str, Tuple[int, ...]], ...] = (
    ("freeplay.high", "qwertyu", (72, 74, 76, 77, 79, 81, 83)),
    ("freeplay.mid", "asdfghj", (60, 62, 64, 65, 67, 69, 71)),
    ("freeplay.low", "zxcvbnm", (48, 50, 52, 53, 55, 57, 59)),
)
KEY_MIDI: Dict[str, int] = {k: m for _, keys, midis in ROWS for k, m in zip(keys, midis)}
PLAY_KEYS = frozenset(KEY_MIDI)
NOTE_NAMES = {0: "C", 2: "D", 4: "E", 5: "F", 7: "G", 9: "A", 11: "B"}
# Every built-in melody pitch lies inside the free-play range, so pre-rendering
# these 21 keys covers free play, prenatal mode and the rhythm game alike.
PRELOAD_MIDIS = sorted(set(KEY_MIDI.values()))

REPEAT_TIMEOUT = 0.2   # auto-repeat debounce: legacy terminals have no key-up
MAX_HOLD = 8.0         # safety cap on a held voice if a release event is lost
ACTIVITY_WINDOW = 2.0
NOTE_DUR = 1.0
CAP_W = 5
LABEL_W = 6


def note_name(midi: int) -> str:
    return "%s%d" % (NOTE_NAMES.get(midi % 12, "?"), midi // 12 - 1)


def _fit(s: str, width: int) -> str:
    if text_width(s) <= width:
        return s
    out: List[str] = []
    used = 0
    for ch in s:
        cw = char_width(ch)
        if used + cw > width:
            break
        out.append(ch)
        used += cw
    return "".join(out)


class FreePlayScreen(Screen):
    def __init__(self, app):
        super().__init__(app)
        self.player: Optional[songs.SongPlayer] = None
        self._picking = False
        self._reset()

    def _reset(self) -> None:
        self.clock = 0.0
        self.last_activity = 0.0
        self.prenatal = False
        self.key_down: Dict[str, bool] = {}
        self.last_event: Dict[str, float] = {}
        self.key_voice: Dict[str, int] = {}
        self._mouse_key: Optional[str] = None

    def enter(self, **kw) -> None:
        if self.player is not None:
            self.last_activity = self.clock
            return
        self._reset()

    def exit(self) -> None:
        picking = self._picking
        self._picking = False
        self._clear_keys()
        if picking:
            return
        if self.player is not None:
            self.player.stop()
            self.player = None
        self.prenatal = False
        self.audio.stop_all()

    # Input -------------------------------------------------------------------

    def handle_key(self, ev: KeyEvent) -> None:
        k = ev.key
        if not ev.pressed:
            self._key_up(k)
            return
        if is_exit(k):
            self._back()
        elif k == "ctrl+x":
            self._cycle_timbre()
        elif k == "ctrl+t":
            self._toggle_prenatal()
        elif k == "ctrl+a":
            self._pick_song()
        elif k in KEY_MIDI:
            self._press(k)

    def handle_mouse(self, ev: MouseEvent) -> None:
        if ev.kind == "press":
            action = self.hits.hit(ev.x, ev.y)
            if action is not None:
                self.on_action(action)
        elif ev.kind == "release" and self._mouse_key is not None:
            self._key_up(self._mouse_key)
            self._mouse_key = None

    def _mouse_press(self, key: str) -> None:
        self._mouse_key = key
        self._press(key)

    def _back(self) -> None:
        self.app.navigate("menu")

    def _press(self, key: str) -> None:
        self.last_activity = self.clock
        self.last_event[key] = self.clock
        if self.key_down.get(key, False):
            return
        self.key_down[key] = True
        if self.player is not None:
            return  # prenatal mode: keys only keep the auto-play alive, no sound
        midi = KEY_MIDI[key]
        if self.app.release_events() and synth.get_timbre(self.config.timbre).sustain:
            # Real key-up events: hold the voice until the key is released.
            self.key_voice[key] = self.audio.note_on(self.config.timbre, midi, 1.0)
        else:
            self.audio.play_note(self.config.timbre, midi, NOTE_DUR, 1.0)

    def _key_up(self, key: str) -> None:
        if key in KEY_MIDI:
            self._release(key)

    def _release(self, key: str) -> None:
        self.key_down.pop(key, None)
        self.last_event.pop(key, None)
        vid = self.key_voice.pop(key, None)
        if vid is not None:
            self.audio.note_off(vid)

    def _clear_keys(self) -> None:
        self.key_down.clear()
        self.last_event.clear()
        self._mouse_key = None
        for vid in self.key_voice.values():
            self.audio.note_off(vid)
        self.key_voice.clear()

    # Actions -----------------------------------------------------------------

    def _cycle_timbre(self) -> None:
        tid = synth.next_timbre(self.config.timbre)
        self.config.timbre = tid
        self.config.save()
        self._clear_keys()
        if self.player is not None:
            self.player.set_timbre(tid)
        self.audio.preload(tid, PRELOAD_MIDIS)  # no stall on the first press

    def _toggle_prenatal(self) -> None:
        if self.player is None:
            self._start_player(self.config.prenatal_song)
            self.prenatal = True
        else:
            self.player.stop()
            self.player = None
            self.prenatal = False

    def _start_player(self, sid: Optional[str]) -> None:
        self.player = songs.SongPlayer(self.audio, songs.get_song(sid), self.config.timbre)
        self.player.start()
        self.last_activity = self.clock

    def _pick_song(self) -> None:
        self._picking = True
        self.app.navigate("song_select", on_select=self._on_song, back="freeplay")

    def _on_song(self, sid: str) -> None:
        if self.player is not None:
            self.player.stop()
            self._start_player(sid)

    # Simulation --------------------------------------------------------------

    def update(self, dt: float) -> None:
        self.clock += dt
        if self.app.release_events():
            # Releases arrive as events; only a lost release needs the cap.
            for key, t0 in list(self.last_event.items()):
                if self.clock - t0 > MAX_HOLD:
                    self._release(key)
        else:
            for key in list(self.key_down):
                if self.clock - self.last_event.get(key, 0.0) > REPEAT_TIMEOUT:
                    self._release(key)
        p = self.player
        if p is not None:
            if self.clock - self.last_activity > ACTIVITY_WINDOW:
                p.pause()
            else:
                p.resume()
            p.update(dt)
            if p.finished:
                p.start()

    # Drawing -----------------------------------------------------------------

    def draw(self, scr: Buffer) -> None:
        self.hits.clear()
        th = self.theme
        w, h = scr.w, scr.h
        if w < 6 or h < 5:
            return
        btn_h = 3 if h >= 14 else 1
        ctrl_y = max(0, h - 3 - btn_h)
        y = 0
        head = self._header_lines()[:max(1, ctrl_y - 3)]
        for text, fg, bold in head:
            if y >= ctrl_y:
                break
            center_text(scr, y, text, fg, None, bold)
            y += 1
        reserve = 2 if (self.player is not None and ctrl_y - y >= 12) else 0
        end = self._draw_keyboard(scr, y, ctrl_y - reserve)
        if self.player is not None and ctrl_y - 2 >= max(y, end):
            self._draw_progress(scr, ctrl_y - 2)
        self._draw_controls(scr, ctrl_y, btn_h)
        center_text(scr, h - 2, th.t("freeplay.exit_hint"), C.dim)

    def _header_lines(self) -> List[Tuple[str, int, bool]]:
        th = self.theme
        tid = self.config.timbre
        lines = [
            (th.t("freeplay.title"), C.yellow, True),
            (th.t("freeplay.timbre_line", name=synth.timbre_name(tid, th.lang)), C.cyan, False),
        ]
        if self.player is not None:
            lines.append((th.t("freeplay.prenatal_song",
                               title=self.player.song.title(th.lang)), C.green, False))
            lines.append((th.t("freeplay.prenatal_hint"), C.dim, False))
        else:
            lines.append((th.t("freeplay.prenatal_off"), C.gray, False))
        return lines

    def _geometry(self, w: int) -> Tuple[int, int, int, int, int]:
        label_w = LABEL_W if w >= 46 else 0
        gap = 1 if w >= 36 else 0
        cap_w = max(3, min(CAP_W, (w - 2 - label_w - 6 * gap) // 7))
        kb_w = label_w + 7 * cap_w + 6 * gap
        if kb_w > w - 1:
            cap_w = max(1, (w - 1 - label_w - 6 * gap) // 7)
            kb_w = label_w + 7 * cap_w + 6 * gap
        return max(0, (w - kb_w) // 2), label_w, cap_w, gap, kb_w

    def _draw_keyboard(self, scr: Buffer, top: int, limit: int) -> int:
        th = self.theme
        w, h = scr.w, scr.h
        x0, label_w, cap_w, gap, kb_w = self._geometry(w)
        avail = limit - top
        if avail < 1 or cap_w < 1:
            return top
        names = avail >= 6 and cap_w >= 2
        gaps = avail >= 8
        row_h = 2 if names else 1
        step = row_h + (1 if gaps else 0)
        block_h = 3 * row_h + (2 if gaps else 0)
        boxed = names and gaps and avail >= block_h + 2 and w >= kb_w + 4
        total = block_h + (2 if boxed else 0)
        y = top + max(0, (avail - total) // 2)
        end = y
        if boxed:
            draw_box(scr, x0 - 2, y, kb_w + 4, block_h + 2, th, fg=C.dim,
                     title=th.t("freeplay.keyboard"), title_fg=C.gray)
            end = y + block_h + 2
            y += 1
        for label_key, keys, midis in ROWS:
            if y >= limit or y >= h:
                break
            if label_w:
                scr.text(x0, y, th.t(label_key), C.gray)
            kx = x0 + label_w
            for i, key in enumerate(keys):
                self._draw_cap(scr, kx + i * (cap_w + gap), y, cap_w, key, midis[i],
                               names and y + 1 < limit and y + 1 < h)
            end = max(end, y + row_h)
            y += step
        return end

    def _draw_cap(self, scr: Buffer, x: int, y: int, cap_w: int, key: str,
                  midi: int, names: bool) -> None:
        down = self.key_down.get(key, False)
        fg = C.black if down else C.white
        bg = C.cyan if down else C.panel
        scr.fill(x, y, cap_w, 1, " ", fg, bg)
        label = "[%s]" % key.upper() if cap_w >= 3 else key.upper()
        scr.text(x + max(0, (cap_w - text_width(label)) // 2), y, label, fg, bg, down)
        if 0 <= y < scr.h:
            self.hits.add(x, y, cap_w, 2 if names else 1,
                          (lambda k=key: self._mouse_press(k)))
        if names:
            nm = note_name(midi)
            scr.text(x + max(0, (cap_w - text_width(nm)) // 2), y + 1, nm,
                     C.gold if down else C.dim)

    def _draw_controls(self, scr: Buffer, y: int, bh: int) -> None:
        th = self.theme
        w, h = scr.w, scr.h
        if not (0 <= y < h) or bh < 1:
            return
        on = self.player is not None
        state = th.t("common.on") if on else th.t("common.off")
        btns = [
            (th.t("freeplay.btn_timbre"), self._cycle_timbre, False),
            (th.t("freeplay.btn_prenatal", state=state), self._toggle_prenatal, on),
        ]
        if on:  # song picking only makes sense while prenatal mode is running
            btns.append((th.t("freeplay.btn_song"), self._pick_song, False))
        btns.append((th.t("common.back"), self._back, False))
        gaps = len(btns) - 1
        gap = 2
        widths = [text_width(lab) + 4 for lab, _, _ in btns]
        if sum(widths) + gap * gaps > w - 2:
            gap = 1
            widths = [text_width(lab) + 2 for lab, _, _ in btns]
        if sum(widths) + gap * gaps > w - 2:
            scale = max(0.0, (w - 2 - gap * gaps)) / max(1, sum(widths))
            widths = [max(4, int(wd * scale)) for wd in widths]
        total = sum(widths) + gap * gaps
        x = max(0, (w - total) // 2)
        for (lab, action, sel), bw in zip(btns, widths):
            if x >= w:
                break
            bw = min(bw, w - x)
            draw_button(scr, x, y, bw, bh, _fit(lab, max(1, bw - 2)), th,
                        selected=sel, hits=self.hits, action=action)
            x += bw + gap

    def _draw_progress(self, scr: Buffer, y: int) -> None:
        p = self.player
        if p is None or not (0 <= y < scr.h):
            return
        th = self.theme
        barw = max(6, min(24, scr.w - 18))
        fill = max(0, min(barw, int(round(p.progress * barw))))
        fc, ec = ("█", "░") if th.is_unicode else ("#", "-")
        state = th.t("freeplay.playing") if p.playing else th.t("freeplay.paused")
        line = "%s %s%s %3d%%" % (state, fc * fill, ec * (barw - fill),
                                  int(p.progress * 100))
        center_text(scr, y, line, C.green if p.playing else C.gray)