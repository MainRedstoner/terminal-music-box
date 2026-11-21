"""Lane-planning helpers shared by every rhythm chart.

A falling chart is not a transcription of the score: six keys under two hands
punish transcriptions and reward *fingering*.  Every song in the library goes
through the same four ideas, in this order:

1. **Pitch bands** — low pitches fall on the left, high on the right, so the
   chart still reads as the melody.  Bands are cut by note *count*, not by
   pitch range: melody pitches cluster around the tonic, and an even split of
   the range would dump half the notes on two middle lanes.
2. **Pattern banks** — a dense run is handed to a rotating set of lane shapes
   (rolls, bursts) instead of the pitch mapping, because at speed nobody reads
   individual pitches; they read the rhythm and the fingering.
3. **Corrections** — never the same lane twice in a row, and break very long
   one-hand blocks by crossing to the other hand.  A chart that leaves one
   hand idle for half a minute, or asks two fingers to do 6 notes a second,
   stops being playable no matter how faithful it is.
4. **Accents** — phrase peaks become double taps, preferably one per hand.

Songs differ in how they combine these steps, so the module exposes them as
small composable pieces rather than one rigid pipeline.
"""
from __future__ import annotations

from collections import Counter
from typing import (Callable, Dict, Iterable, Iterator, List, Optional,
                    Sequence, Tuple, Union)

LEFT = (0, 1, 2)
RIGHT = (3, 4, 5)
INNER = (1, 2, 3, 4)
OUTER = (0, 5)


def is_left(lane: int) -> bool:
    return lane < 3


def mirror(lane: int) -> int:
    """The other hand's lane at the same distance from the middle."""
    return 5 - lane


def same_hand(a: int, b: int) -> bool:
    return is_left(a) == is_left(b)


# Banding --------------------------------------------------------------------

def pitch_bands(pitches: Iterable[int], bands: int = 6,
                lanes: Optional[Sequence[int]] = None
                ) -> Dict[int, int]:
    """Map every pitch to a contiguous band holding an equal share of notes.

    `lanes` restricts and orders the band destinations, e.g. `(1, 2, 3, 4)`
    keeps a dense run on the inner four keys while still giving the run a
    balanced four-way split.  A pitch keeps one band for the whole song, so
    the same note always falls in the same place.

    The cut points are chosen by dynamic programming to minimise the largest
    band, not by rounding the running share: with a discrete pitch range a
    proportional cut lands mid-group and leaves the top band half empty.
    """
    pitches = list(pitches)
    if not pitches:
        return {}
    counts = Counter(pitches)
    uniq = sorted(counts)
    targets = tuple(lanes) if lanes is not None else tuple(range(bands))
    k = len(targets)
    if len(uniq) == 1:
        return {uniq[0]: targets[0]}

    prefix = [0]
    for pitch in uniq:
        prefix.append(prefix[-1] + counts[pitch])
    n = len(uniq)
    inf = float("inf")
    # best[b][i]: smallest possible largest band for the first i pitches in b
    # bands; cut[b][i] remembers where the last band started.
    best = [[inf] * (n + 1) for _ in range(k + 1)]
    cut = [[0] * (n + 1) for _ in range(k + 1)]
    best[0][0] = 0
    for b in range(1, k + 1):
        for i in range(1, n + 1):
            for j in range(b - 1, i):
                load = max(best[b - 1][j], prefix[i] - prefix[j])
                if load < best[b][i]:
                    best[b][i] = load
                    cut[b][i] = j

    spans: List[Tuple[int, int]] = []
    i = n
    for b in range(k, 0, -1):
        j = cut[b][i]
        spans.append((j, i))
        i = j
    spans.reverse()
    lane_of: Dict[int, int] = {}
    for lane, (start, end) in zip(targets, spans):
        for idx in range(start, end):
            lane_of[uniq[idx]] = lane
    return lane_of


# Patterns -------------------------------------------------------------------

def pattern_stream(patterns: Sequence[Sequence[int]], repeats: int = 2
                   ) -> Iterator[int]:
    """Yield lane shapes from a bank, repeating each shape `repeats` times.

    The bank rotation keeps a long stream from settling into one memorisable
    loop; the repeat count keeps each shape long enough to learn.
    """
    bank = 0
    while True:
        for _ in range(repeats):
            yield from patterns[bank % len(patterns)]
        bank += 1


def dense_flags(times: Sequence[float], spb: float,
                threshold: float = 0.25) -> List[bool]:
    """Mark notes that sit inside a run of `threshold`-beat gaps."""
    out: List[bool] = []
    limit = threshold * spb
    for i in range(len(times)):
        prev = times[i] - times[i - 1] if i else float("inf")
        nxt = times[i + 1] - times[i] if i + 1 < len(times) else float("inf")
        out.append(min(prev, nxt) <= limit + 1e-9)
    return out


# Corrections ----------------------------------------------------------------

def _neighbours(lane: int, allowed: Sequence[int]) -> List[int]:
    cands = [alt for alt in (lane - 1, lane + 1, lane - 2, lane + 2)
             if alt in allowed]
    cands.sort(key=lambda alt: (alt in OUTER, abs(alt - lane), alt))
    return cands


def no_repeat(lanes: List[int], times: Sequence[float],
              *, gap: float = float("inf"),
              allowed: Sequence[int] = tuple(range(6))) -> List[int]:
    """Move a lane that repeats the previous hit within `gap` seconds.

    Repeated pitches are the usual source of stacked taps; alternating to a
    neighbouring key keeps the run playable without moving the note in time.
    """
    out = list(lanes)
    for i in range(1, len(out)):
        if out[i] != out[i - 1]:
            continue
        if times[i] - times[i - 1] > gap + 1e-9:
            continue
        cands = [alt for alt in _neighbours(out[i], allowed)
                 if alt != out[i - 1]]
        if cands:
            out[i] = cands[0]
    return out


def hand_runs(lanes: Sequence[int]) -> List[Tuple[int, int, bool]]:
    """Split a lane sequence into (start, end, is_left) one-hand runs."""
    runs: List[Tuple[int, int, bool]] = []
    if not lanes:
        return runs
    start = 0
    hand = is_left(lanes[0])
    for i in range(1, len(lanes) + 1):
        if i == len(lanes) or is_left(lanes[i]) != hand:
            runs.append((start, i, hand))
            if i < len(lanes):
                start, hand = i, is_left(lanes[i])
    return runs


def break_hand_blocks(lanes: List[int], times: Sequence[float],
                      *, max_run: int = 6, beat_gap: float = 0.5,
                      crossing: Optional[Union[Tuple[int, int],
                                               Callable[[int], int]]] = None,
                      allowed: Sequence[int] = tuple(range(6))) -> List[int]:
    """Cross to the other hand when one hand owns too many fast notes.

    Every `max_run` notes of a one-hand block, one note is handed to the other
    hand, so the stream swings left and right instead of hammering two
    fingers.  Only fast stretches count: a slow singing line may legitimately
    stay on one hand.

    `crossing` selects the borrowed lane: a `(when_left, when_right)` pair
    pins the target for a left-hand block and a right-hand block respectively,
    a callable maps the note's own lane, and `None` mirrors the lane across the
    middle of the field.
    """
    out = list(lanes)
    if not out:
        return out
    times = list(times)
    for start, end, hand in hand_runs(out):
        if end - start <= max_run:
            continue
        count = 0
        for i in range(start, end):
            fast = i == start or times[i] - times[i - 1] <= beat_gap + 1e-9
            count = count + 1 if fast else 1
            if count <= max_run:
                continue
            if callable(crossing):
                target = crossing(out[i])
            elif crossing is not None:
                target = crossing[0] if hand else crossing[1]
            else:
                target = mirror(out[i])
            if (target in allowed and target != out[i]
                    and (i == 0 or target != out[i - 1])):
                out[i] = target
                count = 0
    return out


# Accents --------------------------------------------------------------------

def pick_partner(lane: int, taken: Iterable[int], loads: Sequence[int],
                 *, cross_hand: bool = True,
                 allowed: Sequence[int] = tuple(range(6))) -> Optional[int]:
    """Choose the second key of a double tap.

    Cross-hand pairs are the default: two fingers on one hand making a chord
    is a stretch, while one key per hand is free.  Among the candidates the
    less-loaded hand wins, so a chart cannot quietly pile every chord onto the
    right thumb.
    """
    taken = set(taken)
    options = [cand for cand in allowed if cand not in taken]
    if not options:
        return None

    def rank(cand: int):
        return (same_hand(cand, lane) if cross_hand else False,
                loads[cand], cand in OUTER, abs(cand - lane), cand)

    return min(options, key=rank)


def mirror_partner(lane: int, taken: Iterable[int],
                   allowed: Sequence[int] = tuple(range(6))) -> Optional[int]:
    """The mirrored key for a double tap: 0<->5, 1<->4, 2<->3.

    A mirrored chord is the easiest two-key shape on a six-key field: the two
    hands make the same shape at the same distance from the middle, so the pair
    reads as one gesture.  Nearby keys are used only when the mirror is taken.
    """
    taken = set(taken)
    target = mirror(lane)
    options = [target]
    for step in (1, 2):
        options.append(target - step)
        options.append(target + step)
    for cand in options:
        if cand in allowed and cand not in taken and cand != lane:
            return cand
    return None
