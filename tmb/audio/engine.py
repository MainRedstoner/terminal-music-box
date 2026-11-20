"""Real-time polyphonic mixer. A background thread pulls sample chunks from
active voices, sums them, and streams S16LE frames to the output backend.

Voices are either one-shot (a precomputed buffer) or sustained (attack +
looping steady + release). Rendered timbre buffers are cached per (timbre,
midi) so repeated notes are cheap. No third-party dependencies.
"""
from __future__ import annotations

import math
import threading
import time
from array import array
from typing import Dict, List, Optional, Tuple

from .backends import Backend, open_backend
from .synth import SR, NoteBuffers, Timbre, fade_out, get_timbre, zeros

Segment = Tuple[array, bool]
CACHE_LIMIT = 64  # long natural tails make rendered notes large; bound memory


def _limit(s: float) -> float:
    a = abs(s)
    if a <= 0.8:
        return s
    k = 0.8 + 0.2 * math.tanh((a - 0.8) / 0.2)
    return k if s >= 0 else -k


class Voice:
    def __init__(self, segments: List[Segment], release: Optional[array] = None,
                 sustain: bool = False, gain: float = 1.0,
                 steady: Optional[array] = None):
        self._segments = segments
        self._idx = 0
        self._pos = 0
        self._release = release
        self._sustain = sustain
        self._steady = steady
        self._loop_pos = 0
        self.gain = gain
        self.done = False
        self._fade_total = 0
        self._fade_left = 0

    def fade_out(self, samples: int) -> None:
        """Mark the voice to ramp to silence over `samples` frames."""
        if self._fade_left > 0:
            return
        self._fade_total = max(1, samples)
        self._fade_left = self._fade_total

    def is_fading(self) -> bool:
        return self._fade_left > 0

    def release(self) -> None:
        if not self._sustain:
            return
        seg = self._steady
        if seg is not None and len(seg):
            # Continue from the current loop phase so the tail is click-free.
            pos = self._loop_pos % len(seg)
            rot = seg[pos:] + seg[:pos]
            rn = len(self._release) if self._release is not None and len(self._release) else int(SR * 0.08)
            tail = zeros(rn)
            i = 0
            while i < rn:
                take = min(len(rot), rn - i)
                tail[i:i + take] = rot[:take]
                i += take
            self._segments = [(fade_out(tail, 1000.0 * rn / SR), False)]
            self._idx = 0
            self._pos = 0
        elif self._release is not None and len(self._release):
            self._segments = [(self._release, False)]
            self._idx = 0
            self._pos = 0
        else:
            self._segments = []
            self.done = True

    def pull(self, n: int) -> array:
        out = zeros(n)
        filled = 0
        while filled < n and self._idx < len(self._segments):
            buf, loop = self._segments[self._idx]
            if len(buf) == 0:
                self._idx += 1
                self._pos = 0
                continue
            avail = len(buf) - self._pos
            take = min(n - filled, avail)
            out[filled:filled + take] = buf[self._pos:self._pos + take]
            self._pos += take
            filled += take
            if loop:
                self._loop_pos = self._pos % len(buf)
            if self._pos >= len(buf):
                if loop:
                    self._pos = 0
                else:
                    self._idx += 1
                    self._pos = 0
        if self._idx >= len(self._segments):
            self.done = True
        if self._fade_left > 0:
            played = self._fade_total - self._fade_left
            take = min(n, self._fade_left)
            for i in range(take):
                out[i] *= 0.5 + 0.5 * math.cos(math.pi * (played + i + 1) / self._fade_total)
            self._fade_left -= take
            if self._fade_left <= 0:
                self.done = True
        return out


def assemble_oneshot(nb: NoteBuffers, dur: float) -> array:
    atk = nb.attack if nb.attack is not None else zeros(0)
    steady = nb.steady
    rel = nb.release if nb.release is not None else zeros(0)
    target = int(dur * SR)
    body = max(0, target - len(atk) - len(rel))
    out = array("f", atk)
    if steady is not None and len(steady) > 0 and body > 0:
        need = len(atk) + body
        while len(out) < need:
            out += steady
        out = out[:need]
        # Release continues the body's end phase so the seam is click-free.
        pos = body % len(steady)
        rot = steady[pos:] + steady[:pos]
        rn = max(len(rel), int(SR * 0.08))
        tail = zeros(rn)
        i = 0
        while i < rn:
            take = min(len(rot), rn - i)
            tail[i:i + take] = rot[:take]
            i += take
        out += fade_out(tail, 1000.0 * rn / SR)
    else:
        out += rel
    return out


class AudioEngine:
    def __init__(self, backend: Optional[Backend] = None, sr: int = SR, ch: int = 1,
                 chunk: int = 512, realtime: bool = True, master_gain: float = 0.8):
        self.sr = sr
        self.ch = ch
        self.chunk = chunk
        self.realtime = realtime
        self.master_gain = master_gain
        self.backend = backend if backend is not None else open_backend(sr=sr, ch=ch)
        self._voices: Dict[int, Voice] = {}
        self._fading: List[Voice] = []
        self._lock = threading.Lock()
        self._next_id = 1
        self._cache: Dict[Tuple[str, int], NoteBuffers] = {}
        self._cache_lock = threading.Lock()
        self._preload_lock = threading.Lock()
        self._preload_gen = 0
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._samples = 0
        self._t0 = 0.0

    def start(self) -> None:
        if self._running:
            return
        try:
            self.backend.open(self.sr, self.ch)
        except Exception:
            from .backends import NullBackend, _warn_silent
            _warn_silent("audio device open failed (%s); running silent." % self.backend.name)
            self.backend = NullBackend()
            self.backend.open(self.sr, self.ch)
        self._running = True
        self._samples = 0
        self._t0 = time.monotonic()
        self._thread = threading.Thread(target=self._loop, name="tmb-audio", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None
        self.stop_all(0)
        try:
            self.backend.close()
        except Exception:
            pass

    def _loop(self) -> None:
        n = self.chunk
        g = self.master_gain
        while self._running:
            with self._lock:
                voices = list(self._voices.items())
                fading = list(self._fading)
            acc = [0.0] * n
            done = []
            for vid, v in voices:
                chunk = v.pull(n)
                vg = v.gain
                acc = [a + b * vg for a, b in zip(acc, chunk)]
                if v.done:
                    done.append(vid)
            for v in fading:
                chunk = v.pull(n)
                vg = v.gain
                acc = [a + b * vg for a, b in zip(acc, chunk)]
            out = array("h", (int(_limit(s * g) * 32767) for s in acc))
            try:
                self.backend.write(out.tobytes())
            except Exception:
                pass
            self._samples += n
            if done or fading:
                with self._lock:
                    for vid in done:
                        self._voices.pop(vid, None)
                    if fading:
                        self._fading = [v for v in self._fading if not v.done]
            if not self.backend.blocking and self.realtime:
                target = self._t0 + self._samples / self.sr
                dt = target - time.monotonic()
                if dt > 0:
                    time.sleep(dt)

    def _buffers(self, tid: str, midi: int) -> NoteBuffers:
        key = (tid, midi)
        with self._cache_lock:
            nb = self._cache.get(key)
        if nb is None:
            # Render outside the lock: it can take hundreds of ms and must not
            # block the mixer thread or concurrent preloads.
            nb = get_timbre(tid).render(midi)
            with self._cache_lock:
                if key not in self._cache:
                    if len(self._cache) >= CACHE_LIMIT:
                        self._cache.pop(next(iter(self._cache)))
                    self._cache[key] = nb
        return nb

    def preload(self, tid: str, midis) -> None:
        """Render (tid, midi) buffers in a background daemon thread.

        First use of a long-tail timbre can take hundreds of ms per key, which
        would stall the UI on the first press; preloading removes that. A newer
        preload request supersedes the running one (rapid timbre cycling).
        """
        with self._preload_lock:
            self._preload_gen += 1
            gen = self._preload_gen
            todo = [m for m in midis if (tid, m) not in self._cache]
        if not todo:
            return
        threading.Thread(target=self._preload_work, args=(tid, todo, gen),
                         name="tmb-preload", daemon=True).start()

    def _preload_work(self, tid: str, midis, gen: int) -> None:
        for m in midis:
            with self._preload_lock:
                if gen != self._preload_gen:
                    return  # superseded by a newer preload request
            self._buffers(tid, m)

    def note_on(self, tid: str, midi: int, vel: float = 1.0) -> int:
        nb = self._buffers(tid, midi)
        t = get_timbre(tid)
        if t.sustain and nb.steady is not None:
            atk = nb.attack if nb.attack is not None else zeros(0)
            v = Voice([(atk, False), (nb.steady, True)], release=nb.release,
                      sustain=True, gain=vel, steady=nb.steady)
        else:
            buf = nb.oneshot if nb.oneshot is not None else assemble_oneshot(nb, 1.0)
            v = Voice([(buf, False)], gain=vel)
        return self._add(v)

    def play_note(self, tid: str, midi: int, dur: float, vel: float = 1.0,
                  length: Optional[float] = None) -> int:
        """Play a fixed-length note.

        `length` is the user's per-timbre note-length multiplier (None/1.0 =
        the natural buffer from commit 4426253). Values below 1 trim the
        buffer with a fade; values above 1 only extend timbres that can be
        assembled (sustained ones) — ringing timbres simply end naturally.
        """
        nb = self._buffers(tid, midi)
        t = get_timbre(tid)
        mult = 1.0 if length is None else max(0.12, float(length))
        if t.sustain and nb.steady is not None:
            buf = assemble_oneshot(nb, max(0.12, dur * mult))
        else:
            buf = nb.oneshot if nb.oneshot is not None else assemble_oneshot(nb, dur)
            if mult < 1.0:
                want = max(int(SR * 0.12), int(len(buf) * mult))
                buf = fade_out(buf[:want], 60)
        return self._add(Voice([(buf, False)], gain=vel))

    def _add(self, v: Voice) -> int:
        with self._lock:
            vid = self._next_id
            self._next_id += 1
            self._voices[vid] = v
        return vid

    def note_off(self, vid: int) -> None:
        with self._lock:
            v = self._voices.get(vid)
        if v:
            v.release()

    def stop_all(self, fade_ms: float = 120.0) -> None:
        """Silence every voice; fading voices finish their ramp in the mixer."""
        with self._lock:
            if fade_ms > 0:
                n = max(1, int(self.sr * fade_ms / 1000))
                for v in self._voices.values():
                    v.fade_out(n)
                self._fading.extend(self._voices.values())
            else:
                self._fading.clear()
            self._voices.clear()

    def time(self) -> float:
        return self._samples / self.sr

    def active(self) -> int:
        with self._lock:
            return len(self._voices)