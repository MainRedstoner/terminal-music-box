"""Procedural synthesis of Minecraft 1.20 note-block timbres (no samples).

Contract for every timbre:
    render(midi) -> NoteBuffers
One-shot timbres fill `oneshot`. Sustained timbres fill `attack`, `steady`
(a click-free loopable segment) and `release`. The engine assembles these.

All synthesis uses only the standard library (math / array / random). Helpers
below use a wavetable oscillator and precomputed envelopes so per-note render
cost stays low on a Raspberry Pi. Rendered notes are cached by (timbre, midi).
"""
from __future__ import annotations

import math
import random
from array import array
from dataclasses import dataclass
from typing import Dict, List, Optional

SR = 44100
_rng = random.Random(1234)

# One-cycle sine wavetable for cheap oscillators.
_TABLE_SIZE = 2048
_SINE = array("f", (math.sin(2 * math.pi * i / _TABLE_SIZE) for i in range(_TABLE_SIZE)))


def midi_to_freq(midi: int) -> float:
    return 440.0 * (2.0 ** ((midi - 69) / 12.0))


def pitch_decay(midi: int, low: float, high: float) -> float:
    """Karplus-Strong damping interpolated over the low octave.

    The loop attenuates once per period, so low notes ring far longer than
    high ones for the same `decay`; without compensation their tail is still
    audible when the buffer ends.
    """
    t = max(0.0, min(1.0, (midi - 48) / 12.0))
    return low + (high - low) * t


def zeros(n: int) -> array:
    return array("f", bytes(4 * n))


def wavetable(freq: float, n: int, phase0: float = 0.0) -> array:
    inc = freq * _TABLE_SIZE / SR
    out = array("f", bytes(4 * n))
    ph = phase0 * _TABLE_SIZE
    mask = _TABLE_SIZE - 1
    for i in range(n):
        out[i] = _SINE[int(ph) & mask]
        ph += inc
    return out


def square(freq: float, n: int, duty: float = 0.5) -> array:
    inc = freq / SR
    out = array("f", bytes(4 * n))
    ph = 0.0
    for i in range(n):
        out[i] = 1.0 if (ph % 1.0) < duty else -1.0
        ph += inc
    return out


def decay_env(n: int, tau: float) -> array:
    r = math.exp(-1.0 / (SR * tau))
    out = array("f", bytes(4 * n))
    v = 1.0
    for i in range(n):
        out[i] = v
        v *= r
    return out


def lin_env(n: int, start: float, end: float) -> array:
    out = array("f", bytes(4 * n))
    if n == 1:
        out[0] = start
        return out
    step = (end - start) / (n - 1)
    for i in range(n):
        out[i] = start + step * i
    return out


def adsr(n: int, a: float, d: float, s_level: float, r: float) -> array:
    """Attack/Decay/Sustain/Release envelope over n samples (times in seconds)."""
    na, nd, nr = int(a * SR), int(d * SR), int(r * SR)
    ns = max(0, n - na - nd - nr)
    out = zeros(n)
    i = 0
    for k in range(na):
        out[i] = k / max(1, na); i += 1
    for k in range(nd):
        out[i] = 1.0 + (s_level - 1.0) * (k / max(1, nd)); i += 1
    for k in range(ns):
        out[i] = s_level; i += 1
    for k in range(nr):
        out[i] = s_level * (1.0 - k / max(1, nr)); i += 1
    while i < n:
        out[i] = 0.0; i += 1
    return out


def mix(*bufs: array) -> array:
    n = max((len(b) for b in bufs), default=0)
    out = zeros(n)
    for b in bufs:
        for i in range(len(b)):
            out[i] += b[i]
    return out


def scale(buf: array, gain: float) -> array:
    return array("f", (s * gain for s in buf))


def mul(a: array, b: array) -> array:
    n = min(len(a), len(b))
    return array("f", (a[i] * b[i] for i in range(n)))


def add_partials(acc: array, f: float, parts) -> array:
    """Add decaying sine partials in one pass (no temporary arrays).

    Long natural tails make buffers several seconds long, so render cost
    matters on a Raspberry Pi; this loop is roughly twice as fast as building
    a tone and envelope array per partial.
    """
    n = len(acc)
    mask = _TABLE_SIZE - 1
    for mult, amp, tau in parts:
        inc = f * mult * _TABLE_SIZE / SR
        r = math.exp(-1.0 / (SR * tau))
        # Stop once this partial is 80 dB down; the rest is inaudible and the
        # saving matters for multi-second tails on a Raspberry Pi.
        limit = min(n, int(tau * math.log(max(amp, 1e-9) / 1e-4) * SR) + 1)
        ph = 0.0
        v = 1.0
        for i in range(limit):
            acc[i] += amp * _SINE[int(ph) & mask] * v
            ph += inc
            v *= r
    return acc


def normalize(buf: array, peak: float = 0.9) -> array:
    m = max((abs(s) for s in buf), default=0.0)
    if m < 1e-9:
        return buf
    return scale(buf, peak / m)


_FADE_WINDOWS: Dict[int, array] = {}


def _fade_window(nf: int) -> array:
    """Raised-cosine fade curve for nf samples, cached per length.

    assemble_oneshot / Voice.release fade every played note with the same
    shape; the per-sample math.cos was the dominant render-side cost.
    """
    w = _FADE_WINDOWS.get(nf)
    if w is None:
        w = array("f", (0.5 + 0.5 * math.cos(math.pi * (i + 1) / nf)
                        for i in range(nf)))
        _FADE_WINDOWS[nf] = w
    return w


def fade_out(buf: array, ms: float) -> array:
    """Raised-cosine fade to exact silence (smooth slope at both ends)."""
    nf = min(len(buf), int(ms / 1000 * SR))
    if nf <= 0:
        return buf
    out = array("f", buf)
    w = _fade_window(nf)
    base = len(out) - nf
    for i in range(nf):
        out[base + i] *= w[i]
    return out


def fade_in(buf: array, ms: float) -> array:
    nf = min(len(buf), int(ms / 1000 * SR))
    out = array("f", buf)
    for i in range(nf):
        out[i] *= i / nf
    return out


def periodic(freq: float, seconds: float) -> array:
    """A steady segment containing a whole number of cycles (click-free loop)."""
    cycles = max(1, round(freq * seconds))
    n = int(round(cycles * SR / freq))
    return wavetable(freq, n)


def karplus_strong(freq: float, dur: float, decay: float = 0.996,
                   brightness: float = 0.5) -> array:
    n = int(SR * dur)
    period = max(2, int(SR / freq))
    buf = [_rng.uniform(-1, 1) for _ in range(period)]
    out = array("f", bytes(4 * n))
    idx = 0
    for i in range(n):
        cur = buf[idx]
        nxt = buf[(idx + 1) % period]
        buf[idx] = decay * (brightness * cur + (1 - brightness) * nxt)
        out[i] = cur
        idx = (idx + 1) % period
    return normalize(fade_out(out, 300), 0.9)


@dataclass
class NoteBuffers:
    oneshot: Optional[array] = None
    attack: Optional[array] = None
    steady: Optional[array] = None
    release: Optional[array] = None


class Timbre:
    id = "base"
    name_zh = "基础"
    name_en = "Base"
    sustain = False

    def render(self, midi: int) -> NoteBuffers:
        raise NotImplementedError


class Harp(Timbre):
    id = "harp"
    name_zh = "竖琴（钢琴）"
    name_en = "Harp"
    sustain = False

    def render(self, midi):
        f = midi_to_freq(midi)
        n = int(SR * 7.5)
        parts = [(1, 1.0, 1.6), (2, 0.45, 0.9), (3, 0.3, 0.6),
                 (4, 0.18, 0.4), (5, 0.1, 0.3), (6, 0.06, 0.2)]
        acc = add_partials(zeros(n), f, parts)
        acc = fade_out(fade_in(normalize(acc, 0.85), 3), 800)
        return NoteBuffers(oneshot=acc)


class Bit(Timbre):
    id = "bit"
    name_zh = "比特（方波）"
    name_en = "Bit"
    sustain = True

    def render(self, midi):
        f = midi_to_freq(midi)
        atk = fade_in(scale(periodic_square(f, 0.02), 0.5), 4)
        steady = scale(periodic_square(f, 0.3), 0.5)
        rel = fade_out(scale(square(f, int(SR * 0.2)), 0.5), 200)
        return NoteBuffers(attack=atk, steady=steady, release=rel)


def periodic_square(freq: float, seconds: float) -> array:
    cycles = max(1, round(freq * seconds))
    n = int(round(cycles * SR / freq))
    return square(freq, n)


class Flute(Timbre):
    id = "flute"
    name_zh = "长笛"
    name_en = "Flute"
    sustain = True

    def render(self, midi):
        f = midi_to_freq(midi)
        atk_n = int(round(max(1, round(f * 0.06)) * SR / f))
        atk = fade_in(mix(scale(wavetable(f, atk_n), 0.7),
                          scale(wavetable(f * 2, atk_n), 0.15)), 50)
        steady_n = int(round(max(1, round(f * 0.3)) * SR / f))
        base = mix(scale(wavetable(f, steady_n), 0.7),
                   scale(wavetable(f * 2, steady_n), 0.18),
                   scale(wavetable(f * 3, steady_n), 0.06))
        breath = array("f", (_rng.uniform(-1, 1) * 0.03 for _ in range(steady_n)))
        steady = normalize(mix(base, breath), 0.7)
        rel = fade_out(scale(wavetable(f, int(SR * 0.2)), 0.7), 200)
        return NoteBuffers(attack=atk, steady=steady, release=rel)


class Bass(Timbre):
    id = "bass"
    name_zh = "贝斯"
    name_en = "Bass"
    sustain = False

    def render(self, midi):
        f = midi_to_freq(midi)
        return NoteBuffers(oneshot=karplus_strong(f, 6.0, decay=pitch_decay(midi, 0.996, 0.998), brightness=0.35))


class Bell(Timbre):
    id = "bell"
    name_zh = "钟声"
    name_en = "Bell"
    sustain = False

    def render(self, midi):
        f = midi_to_freq(midi)
        n = int(SR * 5.0)
        parts = [(1.0, 1.0, 1.1), (2.0, 0.6, 0.8), (2.98, 0.4, 0.55),
                 (4.2, 0.25, 0.35), (5.4, 0.15, 0.25)]
        acc = add_partials(zeros(n), f, parts)
        acc = fade_out(fade_in(normalize(acc, 0.85), 2), 600)
        return NoteBuffers(oneshot=acc)


class Guitar(Timbre):
    id = "guitar"
    name_zh = "吉他"
    name_en = "Guitar"
    sustain = False

    def render(self, midi):
        f = midi_to_freq(midi)
        return NoteBuffers(oneshot=karplus_strong(f, 3.6, decay=pitch_decay(midi, 0.992, 0.994), brightness=0.5))


class Chime(Timbre):
    id = "chime"
    name_zh = "风铃"
    name_en = "Chime"
    sustain = False

    def render(self, midi):
        f = midi_to_freq(midi)
        n = int(SR * 6.0)
        parts = [(1.0, 0.7, 1.6), (2.76, 0.5, 1.1), (5.4, 0.35, 0.7),
                 (8.9, 0.2, 0.45)]
        acc = add_partials(zeros(n), f, parts)
        acc = fade_out(fade_in(normalize(acc, 0.85), 2), 700)
        return NoteBuffers(oneshot=acc)


class Xylophone(Timbre):
    id = "xylophone"
    name_zh = "木琴"
    name_en = "Xylophone"
    sustain = False

    def render(self, midi):
        f = midi_to_freq(midi)
        n = int(SR * 0.7)
        tone = mix(scale(wavetable(f, n), 1.0), scale(wavetable(f * 4, n), 0.12))
        body = mul(tone, decay_env(n, 0.08))
        cn = int(SR * 0.005)
        click = scale(mul(array("f", (_rng.uniform(-1, 1) for _ in range(cn))),
                          decay_env(cn, 0.0015)), 0.3)
        acc = normalize(mix(body, click), 0.85)
        return NoteBuffers(oneshot=fade_out(acc, 100))


class IronXylophone(Timbre):
    id = "iron_xylophone"
    name_zh = "铁木琴"
    name_en = "Iron Xylophone"
    sustain = False

    def render(self, midi):
        f = midi_to_freq(midi)
        n = int(SR * 1.1)
        parts = [(1.0, 1.0, 0.18), (3.0, 0.5, 0.12), (5.1, 0.3, 0.08)]
        acc = add_partials(zeros(n), f, parts)
        acc = fade_out(fade_in(normalize(acc, 0.85), 1), 150)
        return NoteBuffers(oneshot=acc)


class CowBell(Timbre):
    id = "cow_bell"
    name_zh = "牛铃"
    name_en = "Cow Bell"
    sustain = False

    def render(self, midi):
        f = midi_to_freq(midi)
        n = int(SR * 1.2)
        tone = mix(scale(square(f, n), 0.6), scale(square(f * 1.5, n), 0.4))
        acc = fade_in(normalize(mul(tone, decay_env(n, 0.16)), 0.8), 1)
        return NoteBuffers(oneshot=fade_out(acc, 200))


class Didgeridoo(Timbre):
    id = "didgeridoo"
    name_zh = "迪吉里杜管"
    name_en = "Didgeridoo"
    sustain = True

    def render(self, midi):
        f = midi_to_freq(midi)
        atk_n = int(round(max(1, round(f * 0.08)) * SR / f))
        atk = fade_in(normalize(mix(scale(wavetable(f, atk_n), 0.75),
                                    scale(wavetable(f * 2, atk_n), 0.5),
                                    scale(wavetable(f * 3, atk_n), 0.4)), 0.7), 60)
        # All harmonics share the fundamental's whole-cycle length so the loop is seamless.
        steady_n = int(round(max(1, round(f * 0.3)) * SR / f))
        base = mix(scale(wavetable(f, steady_n), 0.75),
                   scale(wavetable(f * 2, steady_n), 0.5),
                   scale(wavetable(f * 3, steady_n), 0.4),
                   scale(wavetable(f * 4, steady_n), 0.18),
                   scale(wavetable(f * 5, steady_n), 0.1),
                   scale(wavetable(f * 6, steady_n), 0.06))
        drone = array("f", (_rng.uniform(-1, 1) * 0.02 for _ in range(steady_n)))
        steady = normalize(mix(base, drone), 0.7)
        rel = fade_out(scale(wavetable(f, int(SR * 0.2)), 0.75), 200)
        return NoteBuffers(attack=atk, steady=steady, release=rel)


class Banjo(Timbre):
    id = "banjo"
    name_zh = "班卓琴"
    name_en = "Banjo"
    sustain = False

    def render(self, midi):
        f = midi_to_freq(midi)
        return NoteBuffers(oneshot=karplus_strong(f, 3.4, decay=pitch_decay(midi, 0.992, 0.994), brightness=0.7))


class Pling(Timbre):
    id = "pling"
    name_zh = "电钢琴"
    name_en = "Pling"
    sustain = False

    def render(self, midi):
        f = midi_to_freq(midi)
        n = int(SR * 3.2)
        out = zeros(n)
        ienv = decay_env(n, 0.18)
        inc = f * _TABLE_SIZE / SR
        mask = _TABLE_SIZE - 1
        # 1:1 FM via table-index modulation (no per-sample math.sin); index decays bright->mellow.
        ig = 3.5 * _TABLE_SIZE / (2 * math.pi)
        ph = 0.0
        for i in range(n):
            m = _SINE[int(ph) & mask]
            out[i] = _SINE[int(ph + ig * (0.08 + 0.92 * ienv[i]) * m) & mask]
            ph += inc
        acc = fade_out(fade_in(normalize(mul(out, decay_env(n, 0.4)), 0.85), 3), 500)
        return NoteBuffers(oneshot=acc)


# Registry -------------------------------------------------------------------
TIMBRES: Dict[str, Timbre] = {}
ORDER: List[str] = []


def register(t: Timbre) -> Timbre:
    TIMBRES[t.id] = t
    if t.id not in ORDER:
        ORDER.append(t.id)
    return t


for _t in (Harp(), Bit(), Flute(), Bass(), Bell(), Guitar(), Chime(),
           Xylophone(), IronXylophone(), CowBell(), Didgeridoo(), Banjo(), Pling()):
    register(_t)


def get_timbre(tid: str) -> Timbre:
    return TIMBRES.get(tid, TIMBRES["harp"])


def render_note(args) -> NoteBuffers:
    """Render one (timbre, midi) pair — the AudioEngine's process-pool worker.

    Must stay module-level so multiprocessing can pickle it by reference, and
    this module is all the worker needs to import (pure math, no backends).
    """
    tid, midi = args
    return get_timbre(tid).render(midi)


def timbre_name(tid: str, lang: str) -> str:
    t = get_timbre(tid)
    return t.name_zh if lang == "zh" else t.name_en


def next_timbre(tid: str) -> str:
    if tid not in ORDER:
        return ORDER[0]
    return ORDER[(ORDER.index(tid) + 1) % len(ORDER)]