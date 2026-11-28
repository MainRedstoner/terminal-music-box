"""Free play: 21-key C-major keyboard, timbre picker, prenatal mode."""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

from ..ansi import Screen as Buffer, C, text_width
from ..config import LEN_RANGE, VOL_RANGE
from ..events import KeyEvent, MouseEvent, is_exit, LEFT, RIGHT, UP, DOWN
from ..ui import center_text, draw_box, draw_button, fit_text
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
# Pre-rendering the 21 keyboard pitches keeps free play from stalling on the
# first press. Prenatal mode is a different animal: it auto-plays a song's
# complete score, which reaches outside C3-B5 (Canon's bass line bottoms out at
# C2, Für Elise climbs to E7), so it preloads the selected song's own pitches
# with the keyboard keys after them, and waits for that whole set before
# playback starts — see _prenatal_keys.
PRELOAD_MIDIS = sorted(set(KEY_MIDI.values()))

REPEAT_TIMEOUT = 0.2   # auto-repeat debounce: legacy terminals have no key-up
ACTIVITY_WINDOW = 2.0
FINISH_REST = 5.0      # after the last note: deaf to play keys, then mode off
WAIT_TIMEOUT = 60.0    # a wedged preload must not silence prenatal mode forever
NOTE_DUR = 1.0
VOL_STEP = 0.1
LEN_STEP = 0.25
BAR_SLOTS = 8
CAP_W = 5
LABEL_W = 6


def note_name(midi: int) -> str:
    return "%s%d" % (NOTE_NAMES.get(midi % 12, "?"), midi // 12 - 1)


class FreePlayScreen(Screen):
    def __init__(self, app):
        super().__init__(app)
        self.player: Optional[songs.SongPlayer] = None
        self._picking = False
        self._resuming = False
        self._reset()

    def _reset(self) -> None:
        self.clock = 0.0
        self.last_activity = 0.0
        self.prenatal = False
        self.key_down: Dict[str, bool] = {}
        self.last_event: Dict[str, float] = {}
        self.key_voice: Dict[str, int] = {}
        self.focus = 0  # 0 = volume, 1 = note length (sound strip)
        self._mouse_key: Optional[str] = None
        # Prenatal playback is paused until the song's pitches are rendered
        # (see _begin_playback); _wait_started bounds that wait.
        self._waiting = False
        self._wait_started = 0.0
        # A freshly created player — prenatal just enabled, or its song just
        # changed — stays silent until the user presses a play key; only that
        # same key press that keeps prenatal playback alive may start it.
        self._silent = False
        # When the melody reached its end: prenatal mode is resting (deaf to
        # play keys) for FINISH_REST seconds, then turns itself off instead
        # of looping the song.
        self._finished_at: Optional[float] = None

    def enter(self, **kw) -> None:
        # Coming back from the song/timbre picker keeps the session exactly
        # as it was — player, prenatal flag, sound-strip focus (a player-less
        # re-entry must not fall through into a full _reset).
        if self.player is not None or self._resuming:
            self._resuming = False
            self.last_activity = self.clock
            return
        self._reset()
        # Another screen's preloads (or a rhythm score) may have evicted these
        # 21 keys since startup; re-arm them so a press never renders inline.
        self.audio.preload(self.config.timbre, PRELOAD_MIDIS)

    def exit(self) -> None:
        picking = self._picking
        self._picking = False
        self._clear_keys()
        if picking:
            self._resuming = True
            if self.player is not None:
                # Freeze the melody while the picker is up. The player follows
                # the audio clock even offscreen (update() is not called, so
                # nothing schedules the notes it crosses — silence with the
                # clock still running), and returning used to fire every note
                # it had crossed in one zero-delay burst.
                self.player.pause()
            return
        self._resuming = False
        if self.player is not None:
            self.player.stop()
            self.player = None
        self.prenatal = False
        self._waiting = False
        self._silent = False
        self._finished_at = None
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
            self._open_timbre()
        elif k == "ctrl+t":
            self._toggle_prenatal()
        elif k == "ctrl+a" and self.player is not None:
            self._pick_song()  # song picking only makes sense with prenatal on
        elif k in (UP, DOWN):
            self.focus = 1 - self.focus  # toggle volume / length focus
        elif k in (LEFT, RIGHT):
            self._adjust(-1 if k == LEFT else 1)
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
        if self._finished_at is not None:
            return  # the rest after the last note is deaf (see _press)
        self._mouse_key = key
        self._press(key)

    def _back(self) -> None:
        self.app.navigate("menu")

    def _press(self, key: str) -> None:
        if self._finished_at is not None:
            # The song is over and its rest deafens every play key, so a
            # stray key (or a click on a cap) cannot restart the melody.
            return
        self.last_activity = self.clock
        self.last_event[key] = self.clock
        if self.player is not None:
            # Prenatal mode: keys only keep the auto-play alive, no sound. A
            # press also wakes a player that is still silent after being
            # created (prenatal just enabled, or its song just changed);
            # repeats of an already-held key count too, so this runs before
            # the key_down check below.
            self._silent = False
            if self.key_down.get(key, False):
                return
            self.key_down[key] = True
            return
        if self.key_down.get(key, False):
            return
        self.key_down[key] = True
        midi = KEY_MIDI[key]
        tid = self.config.timbre
        vol, length = self.config.sound_params(tid)
        if self.audio.realtime and not self.audio.is_preloaded(tid, (midi,)):
            # A cold note would render inline in this (UI) thread: hundreds of
            # ms of frozen frame and a late note. Render it in the background
            # and drop this press; the loading popup shows the work. Ask for
            # the whole keyboard, not just this key: a single-key request
            # supersedes enter()'s 21-key batch, and nothing would queue the
            # other keys again (their first press would be dropped for good).
            # While a request is already running, drop the press without a
            # new one — it would cancel and restart the same renders.
            if not self.audio.preload_status()[0]:
                self.audio.preload(tid, PRELOAD_MIDIS)
            return
        t = synth.get_timbre(tid)
        if self.app.release_events() and (t.sustain or t.release_tau is not None):
            # Real key-up events: a sustained timbre holds until release; a
            # holdable ringing timbre decays at the selected rate while held
            # and speeds up to its release time constant on key-up.
            self.key_voice[key] = self.audio.note_on(tid, midi, vol,
                                                     length=length)
        else:
            self.audio.play_note(tid, midi, NOTE_DUR, vol, length=length)

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

    def _open_timbre(self) -> None:
        self._picking = True
        self.app.navigate("timbre_select", on_select=self._apply_timbre,
                          back="freeplay", selected=self._active_timbre())

    def _apply_timbre(self, tid: str) -> None:
        self.config.timbre = tid
        self.config.save()
        self._clear_keys()
        if self.player is not None:
            # The melody is about to continue on a timbre whose buffers do not
            # exist yet: re-render the whole song before letting it resume.
            # A finished one has nothing left to play, so skip that pass.
            self.player.set_timbre(tid)
            if not self.player.finished:
                self._begin_playback()
        else:
            self.audio.preload(tid, PRELOAD_MIDIS)  # no stall on the first press

    # Sound strip -------------------------------------------------------------

    def _max_len(self, tid: str) -> float:
        # Ringing timbres cannot be extended past their natural buffer;
        # sustained ones can be assembled up to 4x.
        return LEN_RANGE[1] if synth.get_timbre(tid).sustain else 1.0

    def _active_timbre(self) -> str:
        """The timbre free play is set to — the one the melody plays as well.

        The player is built from config.timbre (see _start_player) and ^X
        updates both, so prenatal mode never carries a timbre of its own.
        """
        return self.config.timbre

    def _adjust(self, sign: int) -> None:
        """Step the focused sound value of the current timbre."""
        tid = self._active_timbre()
        vol, ln = self.config.sound_params(tid)
        if self.focus == 0:
            self.config.set_sound(tid, vol=vol + sign * VOL_STEP, ln=ln)
        else:
            ln = min(self._max_len(tid), max(LEN_RANGE[0], ln + sign * LEN_STEP))
            self.config.set_sound(tid, vol=vol, ln=ln)
        self.config.save()
        if self.player is not None:  # keep the prenatal melody in sync
            self.player.vol, self.player.length = self.config.sound_params(tid)

    def _toggle_prenatal(self) -> None:
        if self.player is None:
            self._start_player(self.config.prenatal_song)
            self.prenatal = True
        else:
            self._stop_prenatal()

    def _stop_prenatal(self) -> None:
        """Turn prenatal mode off: the ^T toggle, or the rest after the end."""
        if self.player is not None:
            self.player.stop()
            self.player = None
        self.prenatal = False
        self._waiting = False
        self._silent = False
        self._finished_at = None

    def _start_player(self, sid: Optional[str]) -> None:
        # Prenatal mode only offers the rhythm game's songs; an unset or stale
        # config value falls back to the first of them.
        if sid not in songs.RHYTHM_ORDER:
            sid = songs.RHYTHM_ORDER[0]
        song = songs.get_song(sid)
        # The melody sounds on whatever timbre free play is set to. Locking it
        # to the rhythm game's per-song timbre made entering and leaving
        # prenatal mode switch the user's timbre (header and sound strip
        # included); the toggle must leave that selection alone. The rhythm
        # screen keeps its own lock — see rhythm_game.py.
        tid = self.config.timbre
        vol, length = self.config.sound_params(tid)
        self.player = songs.SongPlayer(self.audio, song, tid,
                                       vol=vol, length=length)
        # Enabling prenatal (or changing its song) must not start the melody
        # on its own: stay silent until the user presses a play key. _silent
        # outranks the fresh activity timestamp _begin_playback sets below.
        self._silent = True
        self._begin_playback(restart=True)

    def _pick_song(self) -> None:
        self._picking = True
        self.app.navigate("song_select", on_select=self._on_song, back="freeplay")

    def _on_song(self, sid: str) -> None:
        if self.player is not None:
            self.player.stop()
            self._start_player(sid)

    # Prenatal preload gate ---------------------------------------------------

    def _begin_playback(self, restart: bool = False) -> None:
        """Start (or resume) the melody, but only once its buffers are cached.

        A cold (timbre, midi) render runs inline in whichever thread asks for
        it — here the UI thread, mid-frame — so starting a song (or switching
        timbre mid-song) before its own pitches are rendered freezes the frame
        and fires the note late for every pitch the keyboard preload misses.
        The background preload already reports progress through the app's
        loading overlay, so the wait is visible to the user.
        """
        p = self.player
        if p is None:
            return
        if restart:
            p.start()
            self.last_activity = self.clock
            self._finished_at = None
        if self._ensure_buffers(force=True):
            self._waiting = False
            return
        self._waiting = True
        self._wait_started = self.clock
        p.pause()

    def _prenatal_keys(self) -> List[int]:
        """Pitches the prenatal session needs: the song first, keyboard after.

        The gate and the request must agree: waiting only for the song's own
        pitches started playback while the tail of the same request (the
        missing keyboard keys) was still rendering, competing with the mixer
        on a single-core Pi.
        """
        p = self.player
        if p is None:
            return []
        keys = list(p.song.pitches)
        have = set(keys)
        return keys + [m for m in PRELOAD_MIDIS if m not in have]

    def _ensure_buffers(self, force: bool = False) -> bool:
        """True when every key of the prenatal request is cached for its timbre.

        Missing keys are requested in the background. `force` (a fresh
        start) always asks, so a request superseded by another screen or by a
        newer timbre cannot leave the gate shut for good; otherwise it only
        re-asks when nothing is in flight, which rescues a request that ended
        without covering the song.
        """
        p = self.player
        if p is None:
            return True
        if not self.audio.realtime:
            return True  # offline/headless runs have no playback thread to stall
        midis = self._prenatal_keys()
        if self.audio.is_preloaded(p.timbre, midis):
            return True
        if force or not self.audio.preload_status()[0]:
            self._request_buffers()
        return False

    def _request_buffers(self) -> None:
        """Pre-render the song's pitches first, then the keyboard keys."""
        p = self.player
        if p is None:
            return
        self.audio.preload(p.timbre, self._prenatal_keys())

    # Simulation --------------------------------------------------------------

    def update(self, dt: float) -> None:
        self.clock += dt
        if not self.app.release_events():
            # Legacy terminals never report key-up, so a key counts as released
            # once its auto-repeat stops. Terminals with real key-up must not
            # use this heuristic: auto-repeat only follows the most recently
            # pressed key, so a key held underneath a newer one goes silent
            # while it is still down. Expiring it would cut the note short
            # when two keys are held together.
            for key in list(self.key_down):
                if self.clock - self.last_event.get(key, 0.0) > REPEAT_TIMEOUT:
                    self._release(key)
        p = self.player
        if p is not None:
            if self._waiting:
                if self._ensure_buffers():
                    self._waiting = False
                    # The gate's wait ate into the activity window: opening
                    # it must not instantly trip the idle pause below — once
                    # paused, nothing re-arms the melody on its own.
                    self.last_activity = self.clock
                elif self.clock - self._wait_started > WAIT_TIMEOUT:
                    # A wedged render must not wedge the screen for good:
                    # stop waiting and take the stalls as they come. Playback
                    # itself still waits for the user's play key below.
                    self._waiting = False
            if not self._waiting:
                if p.finished:
                    # The song is over: rest for FINISH_REST with the play
                    # keys deaf (see _press), then leave prenatal mode rather
                    # than looping the melody forever. The screen clock, not
                    # the audio clock, times the rest, so it does not run
                    # while another screen (the pickers) is up.
                    if self._finished_at is None:
                        self._finished_at = self.clock
                    elif self.clock - self._finished_at >= FINISH_REST:
                        self._stop_prenatal()
                else:
                    if self.key_down:
                        # A key still down is ongoing activity. Auto-repeat
                        # only follows the most recently pressed key, so a
                        # key held underneath a newer one stops reporting
                        # while it is still down (the same trap held notes
                        # hit — see _release). Without this the idle pause
                        # started 2 s after the newer key was released, even
                        # though a finger was still on the keyboard.
                        self.last_activity = self.clock
                    if self._silent or self.clock - self.last_activity > ACTIVITY_WINDOW:
                        p.pause()
                    else:
                        p.resume()
                    p.update(dt)
                    if p.finished:
                        self._finished_at = self.clock

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
        # The stacked sound strip takes two rows; prenatal progress one more.
        reserve = 2 if (self.player is not None and ctrl_y - y >= 12) else 1
        end = self._draw_keyboard(scr, y, ctrl_y - reserve - 1)
        if self.player is not None and ctrl_y - 3 >= max(y, end):
            self._draw_progress(scr, ctrl_y - 3)
        self._draw_sound_strip(scr, ctrl_y - 2)
        self._draw_controls(scr, ctrl_y, btn_h)
        center_text(scr, h - 2, th.t("freeplay.exit_hint"), C.dim)

    def _header_lines(self) -> List[Tuple[str, int, bool]]:
        th = self.theme
        tid = self._active_timbre()
        lines = [
            (th.t("freeplay.title"), C.yellow, True),
            (th.t("freeplay.timbre_line", name=synth.timbre_name(tid, th.lang)), C.cyan, False),
        ]
        if self.player is not None:
            lines.append((th.t("freeplay.prenatal_song",
                               title=self.player.song.title(th.lang)), C.green, False))
            hint = ("freeplay.prenatal_finished_hint"
                    if self._finished_at is not None else "freeplay.prenatal_hint")
            lines.append((th.t(hint), C.dim, False))
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
            (th.t("freeplay.btn_timbre"), self._open_timbre, False),
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
            draw_button(scr, x, y, bw, bh, fit_text(lab, max(1, bw - 2)), th,
                        selected=sel, hits=self.hits, action=action)
            x += bw + gap

    def _draw_sound_strip(self, scr: Buffer, y: int) -> None:
        """Stacked per-timbre volume / length editors for the current timbre."""
        th = self.theme
        w, h = scr.w, scr.h
        if not (0 <= y < h) or w < 30:
            return
        tid = self._active_timbre()
        vol, ln = self.config.sound_params(tid)
        uni = th.is_unicode
        on, off = ("█", "░") if uni else ("#", "-")

        def bar(value: float, lo: float, hi: float) -> str:
            frac = (value - lo) / max(1e-9, hi - lo)
            full = max(0, min(BAR_SLOTS, int(round(frac * BAR_SLOTS))))
            return on * full + off * (BAR_SLOTS - full)

        segs = [
            (th.t("freeplay.vol"), bar(vol, *VOL_RANGE), "%.1f" % vol),
            (th.t("freeplay.len"), bar(ln, LEN_RANGE[0], self._max_len(tid)),
             "%.2f×" % ln),
        ]
        seg_w = 24
        x = max(0, (w - seg_w) // 2)
        for i, (label, bar_text, val) in enumerate(segs):
            row = y + i
            if row >= h:
                break
            sel = self.focus == i
            fg = C.cyan if sel else C.gray
            line = "%s %s %s" % (label, bar_text, val)
            scr.text(x, row, line, fg, None, sel)
            self.hits.add(x, row, seg_w, 1, (lambda idx=i: setattr(self, "focus", idx)))

    def _draw_progress(self, scr: Buffer, y: int) -> None:
        p = self.player
        if p is None or not (0 <= y < scr.h):
            return
        th = self.theme
        if self._finished_at is not None:
            # The rest after the last note: count it down so the deaf play
            # keys do not look like a frozen screen.
            left = int(math.ceil(FINISH_REST - (self.clock - self._finished_at)))
            center_text(scr, y, th.t("freeplay.prenatal_finished", sec=max(1, left)),
                        C.yellow)
            return
        barw = max(6, min(24, scr.w - 18))
        fill = max(0, min(barw, int(round(p.progress * barw))))
        fc, ec = ("█", "░") if th.is_unicode else ("#", "-")
        state = th.t("freeplay.playing") if p.playing else th.t("freeplay.paused")
        line = "%s %s%s %3d%%" % (state, fc * fill, ec * (barw - fill),
                                  int(p.progress * 100))
        center_text(scr, y, line, C.green if p.playing else C.gray)