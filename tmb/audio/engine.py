"""Real-time polyphonic mixer. A background thread pulls sample chunks from
active voices, sums them, and streams S16LE frames to the output backend.

Voices are either one-shot (a precomputed buffer) or sustained (attack +
looping steady + release). Rendered timbre buffers are cached per (timbre,
midi) so repeated notes are cheap. No third-party dependencies.
"""
from __future__ import annotations

import math
import os
import threading
import time
from array import array
from typing import Dict, List, Optional, Tuple

from .backends import Backend, open_backend
from .synth import SR, NoteBuffers, Timbre, fade_out, get_timbre, render_note, zeros

Segment = Tuple[array, bool]
# Long natural tails make rendered notes large (~0.1-1.3 MB per key), so
# memory stays bounded. 96 lets the two biggest rhythm scores (56 + 39 keys)
# stay resident together; smaller values make every switch re-render.
CACHE_LIMIT = 96
# Below this many keys a preload finishes faster than spawning/queuing in the
# process pool, so it renders inline instead.
MP_MIN_NOTES = 4
MIX_CEILING = 0.85   # pre-master peak where the adaptive mix starts ducking
MIX_RELEASE = 0.008  # per-chunk recovery (~1.2 s back to full level)


def _limit(s: float) -> float:
    a = abs(s)
    if a <= 0.8:
        return s
    k = 0.8 + 0.2 * math.tanh((a - 0.8) / 0.2)
    return k if s >= 0 else -k


def _mp_enabled() -> bool:
    """True when note rendering may use worker processes (env kill-switch)."""
    return os.environ.get("TMB_NO_MP") is None and (os.cpu_count() or 1) > 1


_mp_pool = None
_mp_pool_lock = threading.Lock()


def _get_pool():
    """Lazily start the shared render pool (one per process, reused)."""
    global _mp_pool
    with _mp_pool_lock:
        if _mp_pool is None:
            import multiprocessing
            # Keep one core for the mixer thread and the UI.
            workers = max(1, min(4, (os.cpu_count() or 2) - 1))
            _mp_pool = multiprocessing.Pool(workers)
        return _mp_pool


class Voice:
    def __init__(self, segments: List[Segment], release: Optional[array] = None,
                 sustain: bool = False, gain: float = 1.0,
                 steady: Optional[array] = None, start: int = 0,
                 decay: float = 1.0, release_tau: Optional[float] = None):
        self._segments = segments
        self._idx = 0
        self._pos = start
        # Frames actually consumed from the segments (mixer thread only);
        # external PCM playback reads this to know where the song is.
        self.consumed = 0
        self._release = release
        self._sustain = sustain
        self._steady = steady
        self._loop_pos = 0
        self.gain = gain
        self.done = False
        self._fade_total = 0
        self._fade_left = 0
        # Extra per-sample gain multiplier (<1) that shortens a ringing
        # note by speeding up its decay instead of slicing its buffer.
        self._decay = decay
        self._decay_g = 1.0
        # Timbre-specific time constant used to speed the decay up on key-up
        # (None = this voice is not a key-held ringing note).
        self._release_tau = release_tau

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
            if self._release_tau is not None:
                # Key-up speeds the held decay up to the timbre's release
                # time constant; the mixer keeps the curve smooth.
                fast = math.exp(-1.0 / (max(0.01, self._release_tau) * SR))
                self._decay = min(self._decay, fast)
            return
        seg = self._steady
        if seg is not None and len(seg):
            # Continue from the current loop phase so the tail is click-free.
            pos = self._loop_pos % len(seg)
            rot = seg[pos:] + seg[:pos]
            rn = len(self._release) if self._release is not None and len(self._release) else int(SR * 0.15)
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
            chunk = buf[self._pos:self._pos + take]
            if chunk.typecode != out.typecode:
                # External PCM arrives as raw int16 frames (±32768); the mixer
                # sums float32 normalized to ±1. Without the scale every
                # sample lands far beyond the limiter knee: one chunk after
                # any silence (the mix gain back at 1.0) plays as a square
                # wave. 512 frames per pull — the conversion is noise.
                chunk = array(out.typecode, [v / 32768.0 for v in chunk])
            out[filled:filled + take] = chunk
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
        self.consumed += filled
        if self._idx >= len(self._segments):
            self.done = True
        if self._decay < 1.0:
            # Shortened ringing note: fade the whole voice exponentially.
            # Cheaper than rewriting the shared buffer and keeps the pitch.
            g = self._decay_g
            d = self._decay
            for i in range(n):
                out[i] *= g
                g *= d
            self._decay_g = g
            if g < 1e-3:  # -60 dB: inaudible, free the voice early
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


def _length_decay(samples: int, mult: float) -> float:
    """Per-sample gain decay that brings a ringing note to -60 dB in
    `samples * mult` frames. 1.0 means the natural buffer is left alone."""
    if mult >= 1.0 or samples <= 0:
        return 1.0
    target = max(int(SR * 0.12), int(samples * mult))
    return math.exp(-7.0 / target)


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
        # Keys of the active preload request (None when idle). Eviction must
        # never drop these or the "is the song ready" gate can never open.
        self._pinned: Optional[set] = None
        self._preload_lock = threading.Lock()
        self._preload_gen = 0
        self._preload_tid: Optional[str] = None
        self._preload_total = 0
        self._preload_done = 0
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._samples = 0
        self._t0 = 0.0
        self._mix_gain = 1.0  # adaptive headroom, mixer thread only
        self._hold = 0.0      # decaying peak-hold feeding the mix decision

    def _mix_target(self, peak: float, mix: float) -> float:
        """Adaptive headroom for the current chunk.

        A single note peaks around 0.85 pre-master and never ducks; when many
        voices sum past MIX_CEILING the gain ducks instantly (the chunk is then
        rendered with a smooth ramp, so the drop never clicks) and recovers
        slowly afterwards. This keeps chords clean instead of crushing them
        through the tanh knee.
        """
        if peak <= MIX_CEILING:
            target = 1.0
        else:
            target = MIX_CEILING / peak
        if target < mix:
            return target  # duck immediately; the render ramp smooths it
        return min(target, mix + MIX_RELEASE)

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
        self._mix_gain = 1.0
        self._hold = 0.0
        self._t0 = time.perf_counter()
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
        mix = 1.0  # gain at the end of the previous chunk
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
            peak = max((abs(s) for s in acc), default=0.0)
            # peak-hold with a slow decay: short valleys between beats must not
            # tempt the gain back up before the next loud chunk arrives
            self._hold = max(peak, self._hold * 0.7)
            new_mix = self._mix_target(self._hold, mix)
            # linear gain ramp across the chunk: no clicks when the level ducks
            step = (new_mix - mix) / n
            gain = mix
            vals = []
            ap = vals.append
            for s in acc:
                gain += step
                ap(int(_limit(s * gain * g) * 32767))
            out = array("h", vals)
            mix = new_mix
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
                dt = target - time.perf_counter()
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
            self._store(tid, midi, nb)
        return nb

    def _store(self, tid: str, midi: int, nb: NoteBuffers) -> None:
        key = (tid, midi)
        with self._cache_lock:
            if key not in self._cache:
                self._evict_slot()
                self._cache[key] = nb

    def _evict_slot(self) -> None:
        """Drop one cache entry before an insert, protecting the request.

        Eviction is FIFO (dicts keep insertion order), but a note belonging to
        the active preload request must survive: the rhythm menu waits for the
        whole set to be cached before starting a song, and dropping one of its
        notes can make the set permanently uncachable — the "clicked a song,
        loading finished, never entered" bug. If every entry is pinned the
        cache temporarily outgrows CACHE_LIMIT; _trim_cache restores the bound
        once the request ends.
        """
        if len(self._cache) < CACHE_LIMIT:
            return
        pinned = self._pinned
        for key in self._cache:
            if pinned is None or key not in pinned:
                del self._cache[key]
                return

    def _trim_cache(self) -> None:
        """Restore the CACHE_LIMIT bound after a pinned request finishes.

        Pops oldest-first, so the just-rendered request (the newest entries)
        is what survives.
        """
        while len(self._cache) > CACHE_LIMIT:
            self._cache.pop(next(iter(self._cache)))

    def preload(self, tid: str, midis) -> None:
        """Render (tid, midi) buffers in a background daemon thread.

        First use of a long-tail timbre can take hundreds of ms per key, which
        would stall the UI on the first press; preloading removes that. A newer
        preload request supersedes the running one (rapid timbre cycling).
        """
        with self._preload_lock:
            self._preload_gen += 1
            gen = self._preload_gen
            keys = {(tid, m) for m in midis}
            with self._cache_lock:
                todo = [m for m in midis if (tid, m) not in self._cache]
                # Pin the whole requested set (not just todo): already-cached
                # keys are part of the start gate too.
                self._pinned = keys if todo else None
            self._preload_tid = tid if todo else None
            self._preload_total = len(todo)
            self._preload_done = 0
        if not todo:
            return
        threading.Thread(target=self._preload_work, args=(tid, todo, gen),
                         name="tmb-preload", daemon=True).start()

    def _preload_work(self, tid: str, midis, gen: int) -> None:
        try:
            if len(midis) >= MP_MIN_NOTES and _mp_enabled():
                self._preload_parallel(tid, midis, gen)
            else:
                self._preload_serial(tid, midis, gen)
        except Exception:
            # A broken pool must not wedge the start gate; finish inline.
            # _preload_serial skips already-cached keys, so partial work stays.
            with self._preload_lock:
                live = gen == self._preload_gen
            if live:
                self._preload_serial(tid, midis, gen)
        with self._preload_lock:
            if gen != self._preload_gen:
                return
            self._preload_tid = None
            with self._cache_lock:
                self._pinned = None
                self._trim_cache()

    def _preload_serial(self, tid: str, midis, gen: int) -> None:
        for m in midis:
            with self._preload_lock:
                if gen != self._preload_gen:
                    return  # superseded by a newer preload request
            self._buffers(tid, m)
            with self._preload_lock:
                if gen == self._preload_gen:
                    self._preload_done += 1

    def _preload_parallel(self, tid: str, midis, gen: int) -> None:
        """Render the keys in worker processes, inserting as results land.

        Every insert re-checks the generation, so a superseded request drops
        out after at most one in-flight note and cancels the queued rest.
        """
        pool = _get_pool()
        futures = [(m, pool.apply_async(render_note, ((tid, m),),
                                         error_callback=lambda e: None))
                   for m in midis]
        for i, (m, fut) in enumerate(futures):
            nb = fut.get(timeout=120.0)
            with self._preload_lock:
                if gen != self._preload_gen:
                    for _, f in futures[i:]:
                        f.cancel()  # no-op on finished results
                    return
                self._preload_done += 1
            self._store(tid, m, nb)

    def preload_status(self) -> Tuple[bool, int, int]:
        """Return (active, rendered, total) for the latest preload request.

        active is False once the worker has rendered every requested key
        (or when everything was already cached and no work was started).
        """
        with self._preload_lock:
            return (self._preload_tid is not None,
                    self._preload_done, self._preload_total)

    def is_preloaded(self, tid: str, midis) -> bool:
        """True when every (tid, midi) buffer is already cached."""
        with self._cache_lock:
            return all((tid, m) in self._cache for m in midis)

    def note_on(self, tid: str, midi: int, vel: float = 1.0,
                length: Optional[float] = None) -> int:
        """Start a note that lasts until note_off.

        Sustained timbres loop their steady segment. Ringing timbres play
        their natural buffer, sped up by the per-timbre `length` multiplier
        exactly like play_note; key-up then accelerates the decay further.
        """
        nb = self._buffers(tid, midi)
        t = get_timbre(tid)
        if t.sustain and nb.steady is not None:
            atk = nb.attack if nb.attack is not None else zeros(0)
            v = Voice([(atk, False), (nb.steady, True)], release=nb.release,
                      sustain=True, gain=vel, steady=nb.steady)
        else:
            buf = nb.oneshot if nb.oneshot is not None else assemble_oneshot(nb, 1.0)
            mult = 1.0 if length is None else max(0.12, float(length))
            v = Voice([(buf, False)], gain=vel,
                      decay=_length_decay(len(buf), mult),
                      release_tau=t.release_tau)
        return self._add(v)

    def play_note(self, tid: str, midi: int, dur: float, vel: float = 1.0,
                  length: Optional[float] = None) -> int:
        """Play a fixed-length note.

        `length` is the user's per-timbre note-length multiplier (None/1.0 =
        the natural buffer). Values below 1 make ringing timbres decay faster
        — the shared buffer is played through an extra exponential gain curve,
        so the note keeps its pitch instead of being sliced; sustained timbres
        are assembled at the shorter duration. Values above 1 only extend
        sustained timbres: ringing ones cannot outlast their natural buffer.
        """
        nb = self._buffers(tid, midi)
        t = get_timbre(tid)
        mult = 1.0 if length is None else max(0.12, float(length))
        decay = 1.0
        if t.sustain and nb.steady is not None:
            buf = assemble_oneshot(nb, max(0.12, dur * mult))
        else:
            buf = nb.oneshot if nb.oneshot is not None else assemble_oneshot(nb, dur)
            # Hit -60 dB at len*mult: the note sounds shorter, but its tail
            # glides down instead of being cut mid-ring.
            decay = _length_decay(len(buf), mult)
        return self._add(Voice([(buf, False)], gain=vel, decay=decay))

    def _add(self, v: Voice) -> int:
        with self._lock:
            vid = self._next_id
            self._next_id += 1
            self._voices[vid] = v
        return vid

    def play_pcm(self, pcm, gain: float = 1.0, start: int = 0) -> int:
        """Play a raw mono float/int sample buffer (external song audio).

        The buffer is shared, never copied or mutated; `start` resumes from a
        frame offset. Returns the voice id for stop_voice/voice_consumed.
        """
        return self._add(Voice([(pcm, False)], gain=gain, start=start))

    def stop_voice(self, vid: int, fade_ms: float = 120.0) -> None:
        """Fade one voice out and detach it (external music pause/stop)."""
        with self._lock:
            v = self._voices.pop(vid, None)
            if v is not None and fade_ms > 0:
                v.fade_out(max(1, int(self.sr * fade_ms / 1000)))
                self._fading.append(v)

    def voice_consumed(self, vid: int) -> int:
        """Frames the mixer has pulled from this voice, or -1 if it is gone."""
        with self._lock:
            v = self._voices.get(vid)
        return v.consumed if v is not None else -1

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