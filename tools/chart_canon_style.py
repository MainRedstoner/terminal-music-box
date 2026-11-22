#!/usr/bin/env python3
"""Chart an audio file in the style of the built-in Canon beatmap.

Two ideas drive this tool.  First, *follow the tune, not the drums*: a pop
mix fires the drum machine far more often than the melody, so the notes are
selected from the melody band (250-1200 Hz: voice + piano) and the low band
only marks downbeat accents.  Second, *plan for two hands* with the same
toolbox the built-in charts use (tmb/charts.py): pitch bands cut by note
count, a rotating fingering bank for runs, no repeated key on consecutive
onsets, one-hand blocks broken across the field, and mirrored double taps.

Placement keeps the detected onset times.  The tempo estimate is used only
to scale the spacing rules — this concert recording breathes (rubato), and
a global quantise grid would pull the chart off the performed rhythm.

    python tools/chart_canon_style.py --audio song.m4s \
        --id i_never_forgot --title-zh 我不曾忘记 --title-en "To the Traveler" \
        --out-dir packs/i_never_forgot
"""
from __future__ import annotations

import argparse
import array
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tmb import charts  # noqa: E402  (pitch bands, banks, repairs, accents)

ANALYSIS_SR = 22050
HOP = 0.010           # onset-envelope frame, seconds
BAND_FILTERS = {
    "low": "lowpass=f=250",
    "mid": "highpass=f=250,lowpass=f=1200",
    "high": "highpass=f=1200",
}
# How much of each band's attack counts as "the tune": the melody band leads,
# the top band only adds brightness, the low band is rhythm, not melody.
MELODY_WEIGHTS = {"mid": 1.0, "high": 0.25, "low": 0.0}
LANE_WEIGHTS = {"low": 0.0, "mid": 3.0, "high": 5.0}   # pitch zone scale 0..5
# Canon fingering banks: dense runs cycle the four inner keys (S D J K),
# consecutive shapes alternate the hands so a switch never breaks a run.
ROLLS = ((1, 2, 3, 4), (2, 4, 1, 3), (4, 3, 2, 1), (3, 4, 1, 2))


def decode_bands(src: str) -> dict:
    """Decode three frequency bands to raw mono PCM, one ffmpeg run each.

    One shared `-filter_complex` with three raw outputs looks cheaper but
    silently mis-scales the outputs on fragmented-MP4 inputs (the frame
    count came back ~4.35x long, warping every derived onset time — the
    reason the first version of this tool produced charts that drifted off
    the music). Separate single-output runs are verified sample-accurate.
    """
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise SystemExit("ffmpeg is required for analysis")
    bands = {}
    with tempfile.TemporaryDirectory() as tmp:
        for name, chain in BAND_FILTERS.items():
            path = os.path.join(tmp, name + ".pcm")
            proc = subprocess.run(
                [ffmpeg, "-v", "error", "-i", src, "-vn", "-ac", "1",
                 "-ar", str(ANALYSIS_SR), "-af", chain, "-f", "s16le", path],
                capture_output=True, text=True, timeout=900)
            if proc.returncode != 0:
                raise SystemExit("ffmpeg analysis failed (%s):\n%s"
                                 % (name, proc.stderr.strip()[-800:]))
            with open(path, "rb") as f:
                pcm = array.array("h")
                pcm.frombytes(f.read())
            if sys.byteorder == "big":
                pcm.byteswap()
            bands[name] = pcm
    return bands


def envelopes(bands: dict) -> dict:
    """Frame RMS per band (one value per HOP seconds)."""
    win = max(1, int(ANALYSIS_SR * HOP))
    out = {}
    for name, pcm in bands.items():
        n = len(pcm) // win
        env = [0.0] * n
        for i in range(n):
            frame = pcm[i * win:(i + 1) * win]
            acc = 0
            for v in frame:
                acc += v * v
            env[i] = math.sqrt(acc / win) / 32768.0
        out[name] = env
    return out


def flux(env: list) -> list:
    """Positive energy change per frame, normalised to a mean of ~1."""
    n = len(env)
    f = [0.0] * n
    for i in range(1, n):
        d = env[i] - env[i - 1]
        if d > 0:
            f[i] = d
    mean = sum(f) / max(1, n)
    if mean <= 0:
        return f
    k = 1.0 / mean
    return [v * k for v in f]


def pick_onsets(band_flux: dict, fps: float) -> list:
    """Melody-led onset picking.

    Candidates are peaks of any band's flux; each peak is scored by how much
    of the attack belongs to the melody band.  A local relative threshold
    keeps quiet passages (solo piano, a cappella lines) chartable while the
    absolute floor stays small.
    """
    n = len(next(iter(band_flux.values())))
    peaks = []
    for i in range(1, n - 1):
        if combined_peak(band_flux, i):
            t = i / fps
            strength = sum(band_flux[k][i] * w
                           for k, w in MELODY_WEIGHTS.items())
            total = sum(band_flux[k][i] for k in band_flux) + 1e-9
            shares = {k: band_flux[k][i] / total for k in band_flux}
            peaks.append([t, strength, shares])
    # Local adaptive threshold on the melody score, referenced to the local
    # 85th percentile rather than the mean: a uniform, busy passage (chorus
    # strumming) must survive — a mean-based bar is 1.8× its own typical
    # peak there and would erase the whole section.
    kept = []
    win = int(1.0 / HOP)
    for idx, item in enumerate(peaks):
        lo = max(0, idx - win)
        hi = min(len(peaks), idx + win)
        local = sorted(p[1] for p in peaks[lo:hi])
        ref = local[int(0.85 * (len(local) - 1))] if local else 0.0
        thr = max(0.35 * ref, 0.05)
        if item[1] >= thr:
            kept.append(item)
    return kept


def combined_peak(band_flux: dict, i: int) -> bool:
    """True when any band's flux peaks at frame i."""
    for f in band_flux.values():
        if f[i] >= f[i - 1] and f[i] > f[i + 1] and f[i] > 0:
            return True
    return False


def merge_close(onsets: list, gap: float) -> list:
    """Drop peaks that crowd inside `gap` seconds, keeping the strongest."""
    out = []
    for item in sorted(onsets, key=lambda x: x[0]):
        if out and item[0] - out[-1][0] < gap:
            if item[1] > out[-1][1]:
                out[-1] = item
            continue
        out.append(item)
    return out


def estimate_tempo(band_flux: dict, fps: float) -> float:
    """Autocorrelate the melody-band envelope; the beat only scales the
    spacing rules, so a rough estimate is enough."""
    data = band_flux["mid"]
    n = len(data)
    best = None
    for lag in range(int(fps * 0.30), int(fps * 1.05)):
        acc = 0.0
        for i in range(0, n - lag, 3):
            acc += data[i] * data[i + lag]
        score = acc / (n - lag)
        if best is None or score > best[1]:
            best = (lag, score)
    bpm = 60.0 * fps / best[0]
    while bpm > 170.0:
        bpm /= 2
    while bpm < 55.0:
        bpm *= 2
    return bpm


def plan_lanes(notes: list, beat: float) -> list:
    """Two-hand lane planning (the Canon chart's rules, via tmb/charts.py).

    notes: [(t, strength, shares)] -> [(t, lane)]
    """
    n = len(notes)
    if not n:
        return []
    run_gap = 0.5 * beat + 1e-9
    dense = []
    for i, (t, _s, _sh) in enumerate(notes):
        prev = t - notes[i - 1][0] if i else math.inf
        nxt = notes[i + 1][0] - t if i + 1 < n else math.inf
        dense.append(min(prev, nxt) <= run_gap)

    # Pitch zones cut by note count, kept on the inner four keys: the melody
    # reads left-to-right with low notes falling left, and the outer keys
    # stay nearly free (the reference charts keep them at a few percent).
    pseudo = [int(round(sum(LANE_WEIGHTS[k] * sh[k] for k in LANE_WEIGHTS)) * 12)
              for _t, _s, sh in notes]
    lane_of_pitch = charts.pitch_bands(pseudo, lanes=(1, 2, 3, 4))
    lanes = []
    bank = charts.pattern_stream(ROLLS, repeats=2)
    for i in range(n):
        if dense[i]:
            lane = next(bank)
        else:
            lane = lane_of_pitch.get(pseudo[i], 1 + (i % 4))
        lanes.append(lane)

    # Repairs: never the same key twice in a row, and no one-hand block long
    # enough to tire two fingers. Slow singing lines may stay on one hand.
    times = [t for t, _s, _sh in notes]
    lanes = charts.no_repeat(lanes, times, gap=0.9 * beat)
    # A singing line here moves at ~one note per beat — the default fast
    # threshold (half a beat) would call it legato and let one hand own
    # twenty-second stretches. Count anything within a beat as fast.
    lanes = charts.break_hand_blocks(lanes, times, max_run=8,
                                     beat_gap=0.9 * beat)

    # Accent chords: the strongest melody note of every four-bar span, plus
    # the final note. Mirrored pairs read as one gesture (A-L, S-K, D-J).
    loads = [0] * 6
    for lane in lanes:
        loads[lane] += 1
    events = {}
    for i, lane in enumerate(lanes):
        events.setdefault(times[i], []).append(lane)
    ordered = sorted(events)
    slot = {t: k for k, t in enumerate(ordered)}
    span = 16 * beat
    accents = set()
    if n:
        accents.add(n - 1)
    window_start = times[0]
    best_i = None
    best_key = (-1.0, -1.0)
    for i, (t, s, _sh) in enumerate(notes):
        if t >= window_start + span:
            if best_i is not None:
                accents.add(best_i)
            window_start = t
            best_i, best_key = None, (-1.0, -1.0)
        if _local_gap(times, i) > run_gap:
            # Prefer strong notes whose mirror key is free once the
            # neighbours' lanes are counted in: a mirrored pair reads as
            # one gesture (the reference charts sit at 90-95% mirrored).
            taken = neighbour_lanes(events, ordered, slot, t) | {lanes[i]}
            mirror_free = charts.mirror(lanes[i]) not in taken
            key = (1.0 if mirror_free else 0.0, s)
            if key > best_key:
                best_i, best_key = i, key
    if best_i is not None:
        accents.add(best_i)
    for i in sorted(accents):
        t = times[i]
        lane = lanes[i]
        taken = set(events[t])
        k = slot[t]
        if k > 0:
            taken |= set(events[ordered[k - 1]])
        if k + 1 < len(ordered):
            taken |= set(events[ordered[k + 1]])
        partner = charts.mirror_partner(lane, taken)
        if partner is not None:
            events[t].append(partner)
    return [(t, lane) for t in ordered for lane in sorted(events[t])]


def neighbour_lanes(events: dict, ordered: list, slot: dict, t: float) -> set:
    """The lanes of the events right before and after time `t`."""
    taken: set = set()
    k = slot[t]
    if k > 0:
        taken |= set(events[ordered[k - 1]])
    if k + 1 < len(ordered):
        taken |= set(events[ordered[k + 1]])
    return taken


def _local_gap(times: list, i: int) -> float:
    prev = times[i] - times[i - 1] if i else math.inf
    nxt = times[i + 1] - times[i] if i + 1 < len(times) else math.inf
    return min(prev, nxt)


def probe_duration(path: str) -> float:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return 0.0
    try:
        out = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nk=1:nw=1", path],
            capture_output=True, text=True, timeout=60, check=True)
        return max(0.0, float(out.stdout.strip()))
    except (subprocess.SubprocessError, ValueError):
        return 0.0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--audio", required=True)
    p.add_argument("--out-dir", default=None,
                   help="directory for chart.json/manifest.json")
    p.add_argument("--id", default=None)
    p.add_argument("--title-zh", dest="title_zh", default=None)
    p.add_argument("--title-en", dest="title_en", default=None)
    p.add_argument("--artist", default="")
    p.add_argument("--difficulty", default="Normal")
    p.add_argument("--lead-in", dest="lead_in", type=float, default=2.0)
    p.add_argument("--min-gap", dest="min_gap", type=float, default=None,
                   help="minimum tap spacing in seconds (default: half a beat)")
    p.add_argument("--density", type=float, default=1.0,
                   help="note-count multiplier (0.7 easier, 1.3 denser)")
    p.add_argument("--stats", action="store_true",
                   help="print statistics only, write nothing")
    args = p.parse_args(argv)

    if not os.path.isfile(args.audio):
        raise SystemExit("no such file: %s" % args.audio)

    bands = decode_bands(args.audio)
    fps = 1.0 / HOP
    envs = envelopes(bands)
    band_flux = {name: flux(e) for name, e in envs.items()}
    # Filter chains can emit a frame or two more or less per band; align them.
    m = min(len(f) for f in band_flux.values())
    band_flux = {name: f[:m] for name, f in band_flux.items()}

    bpm = estimate_tempo(band_flux, fps)
    beat = 60.0 / bpm
    # The spacing ladder: an eighth-note skeleton with occasional sixteenth
    # pairs on emphatic syllables — the density bar the built-in charts use.
    min_gap = args.min_gap or (0.45 * beat)
    min_gap = max(0.12, min_gap / max(0.5, min(args.density, 1.6)))

    onsets = pick_onsets(band_flux, fps)
    onsets = merge_close(onsets, min_gap)
    strengths = sorted(s for _t, s, _sh in onsets)
    strong = strengths[int(0.88 * len(strengths))] if strengths else 0.0

    notes = []
    last_t = -math.inf
    run = 0
    for t, s, shares in onsets:
        gap = t - last_t
        if gap >= min_gap:
            notes.append((t, s, shares))
            last_t = t
            run = 0
            continue
        # Sixteenth pairs survive only on emphatic attacks and never as
        # walls: the skeleton stays playable, the fill keeps the groove.
        if s >= strong and run < 2 and gap >= 0.5 * min_gap:
            notes.append((t, s, shares))
            last_t = t
            run += 1
    pairs = plan_lanes(notes, beat)

    duration = probe_duration(args.audio) or (notes[-1][0] if notes else 0.0)
    print("duration %.1fs, tempo ~%.1f BPM, %d onsets -> %d taps"
          % (duration, bpm, len(onsets), len(pairs)))

    # Report the same quality metrics the built-in charts are measured on.
    uniq = sorted(set(t for t, _l in pairs))
    per_t = {}
    for t, lane in pairs:
        per_t.setdefault(t, []).append(lane)
    doubles = [lanes for lanes in per_t.values() if len(lanes) > 1]
    mirrored = sum(1 for lanes in doubles
                   if len(lanes) == 2 and lanes[1] == charts.mirror(lanes[0]))
    lanes_only = [l for lanes in per_t.values() for l in lanes]
    outer = sum(1 for l in lanes_only if l in charts.OUTER)
    hand_runs = charts.hand_runs([l for _t, l in pairs])
    longest_hand = max((end - start for start, end, _h in hand_runs), default=0)
    repeats = sum(1 for i in range(1, len(pairs))
                  if pairs[i][1] == pairs[i - 1][1]
                  and pairs[i][0] - pairs[i - 1][0] < 0.5 * beat)
    gaps = [b - a for a, b in zip(uniq, uniq[1:])]
    print("nps %.2f | doubles %d (%d%% mirrored) | outer %d%% | "
          "longest one-hand run %d | fast repeats %d"
          % (len(pairs) / max(1.0, duration), len(doubles),
             round(100 * mirrored / max(1, len(doubles))),
             round(100 * outer / max(1, len(lanes_only))),
             longest_hand, repeats))
    block = 15.0
    k = 0
    while k * block < duration:
        cnt = sum(1 for t, _l in pairs if k * block <= t < (k + 1) * block)
        print("  %5.1f-%5.1fs : %2d taps (%.1f nps)"
              % (k * block, (k + 1) * block, cnt, cnt / block))
        k += 1
    if args.stats:
        return 0

    out_dir = args.out_dir or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "packs", os.path.splitext(os.path.basename(args.audio))[0])
    os.makedirs(out_dir, exist_ok=True)
    chart = {"version": 1,
             "notes": [[round(t, 3), lane] for t, lane in pairs]}
    song_id = args.id or os.path.splitext(os.path.basename(args.audio))[0]
    manifest = {
        "format": 1,
        "id": song_id,
        "title_zh": args.title_zh or song_id,
        "title_en": args.title_en or args.title_zh or song_id,
        "artist": args.artist,
        "audio": "audio.bin",   # make_pack.py fills the real member name
        "duration": round(duration, 3),
        "offset": 0.0,
        "lead_in": args.lead_in,
        "difficulty": args.difficulty,
    }
    with open(os.path.join(out_dir, "chart.json"), "w", encoding="utf-8") as f:
        json.dump(chart, f, ensure_ascii=False, separators=(",", ":"))
    with open(os.path.join(out_dir, "manifest.json"), "w",
              encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    print("wrote %s" % out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
