"""Song / beatmap data model, a pausable song player, and the built-in library.

A Song is a list of timed notes used by prenatal mode (auto playback). A
Beatmap is a list of timed lane notes used by the rhythm game.
`beatmap_from_song` derives a playable chart from a melody. The library below
is extended with more public-domain melodies.
"""
from __future__ import annotations

import math
from bisect import bisect_right
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class Note:
    time: float   # seconds from song start
    midi: int
    dur: float    # seconds
    vel: float = 1.0


@dataclass
class Song:
    id: str
    title_zh: str
    title_en: str
    bpm: float
    notes: List[Note] = field(default_factory=list)
    chart_notes: Optional[List[Note]] = None  # playable lead line, if different
    timbre: Optional[str] = None  # locked rhythm-game sound; None = user's timbre

    @property
    def duration(self) -> float:
        if not self.notes:
            return 0.0
        return max(n.time + n.dur for n in self.notes)

    def title(self, lang: str) -> str:
        return self.title_zh if lang == "zh" else self.title_en


@dataclass
class RNote:
    time: float   # hit time in seconds
    lane: int     # 0..5


@dataclass
class Beatmap:
    song_id: str
    notes: List[RNote] = field(default_factory=list)
    difficulty: str = "Normal"
    lead_in: float = 2.0   # chart times = song times + lead_in

    @property
    def duration(self) -> float:
        if not self.notes:
            return 0.0
        return max(n.time for n in self.notes)


def seq(items, bpm: float, start: float = 0.0, gate: float = 0.9) -> List[Note]:
    """Build notes from (midi, beats) pairs. gate shortens dur slightly."""
    spb = 60.0 / bpm
    t = start
    out: List[Note] = []
    for midi, beats in items:
        if midi > 0:
            out.append(Note(t, midi, beats * spb * gate))
        t += beats * spb
    return out


def timed(items, bpm: float) -> List[Note]:
    """Build notes from (start, midi, duration) triples in 32nd notes."""
    q = 60.0 / (bpm * 8.0)
    return [Note(t * q, midi, dur * q) for t, midi, dur in items]


def beatmap_from_song(song: Song, lead_in: float = 2.0) -> Beatmap:
    melody = song.chart_notes if song.chart_notes is not None else song.notes
    if not melody:
        return Beatmap(song.id, [], lead_in=lead_in)
    pitches = [n.midi for n in melody]
    lo, hi = min(pitches), max(pitches)
    span = max(1, hi - lo)
    notes: List[RNote] = []
    for n in melody:
        lane = int((n.midi - lo) * 6 / (span + 1))
        lane = max(0, min(5, lane))
        notes.append(RNote(n.time + lead_in, lane))
    notes.sort(key=lambda r: r.time)
    return Beatmap(song.id, notes, lead_in=lead_in)


def _turkish_lane_plan(melody: List[Note], bpm: float
                       ) -> Tuple[List[int], List[Tuple[int, int]]]:
    """Return (main lanes, accent companions) for the Turkish March chart.

    Dense 16th-note streams stay on the four inner lanes, and a repeated pitch
    alternates to a neighbouring lane instead of piling up on one key. Every
    other bar's long downbeat (and the final note) adds a companion lane for a
    two-key accent chord.
    """
    n = len(melody)
    times = [note.time for note in melody]
    lo = min(note.midi for note in melody)
    hi = max(note.midi for note in melody)
    span = max(1, hi - lo)
    dense_gap = 0.25 * 60.0 / bpm

    dense: List[bool] = []
    for i in range(n):
        prev_gap = times[i] - times[i - 1] if i else float("inf")
        next_gap = times[i + 1] - times[i] if i + 1 < n else float("inf")
        dense.append(min(prev_gap, next_gap) <= dense_gap)

    # Repeated pitches alternate lanes so runs never pile up on one key. The
    # alternation applies up to one beat apart; longer gaps start fresh.
    spread_gap = 60.0 / bpm
    lanes: List[int] = [0] * n
    last = -1
    last_time = 0.0
    for i, note in enumerate(melody):
        if dense[i]:
            lane = 1 + int((note.midi - lo) * 4 / (span + 1))
            lane = max(1, min(4, lane))
            low, high = 1, 4
        else:
            lane = int((note.midi - lo) * 6 / (span + 1))
            lane = max(0, min(5, lane))
            low, high = 0, 5
        if lane == last and note.time - last_time <= spread_gap:
            options = [alt for alt in (lane - 1, lane + 1)
                       if low <= alt <= high]
            options.sort(key=lambda alt: (alt in (0, 5), abs(alt - lane), alt))
            if options:
                lane = options[0]
        lanes[i] = lane
        last = lane
        last_time = note.time

    # Accent chords: the first beat of every other bar, when the melody holds
    # for at least an eighth, plus the final note. Times are quantised to 32nds
    # so the check does not drift with float accumulation.
    q = bpm * 8.0 / 60.0
    chords: List[Tuple[int, int]] = []
    for i, note in enumerate(melody):
        start = round(note.time * q)
        dur = round(note.dur * q)
        accent = i == n - 1 or ((start - 8) % 32 == 0 and dur >= 4)
        if not accent:
            continue
        forbidden = {lanes[i]}
        if i and times[i] - times[i - 1] <= dense_gap:
            forbidden.add(lanes[i - 1])
        if i + 1 < n and times[i + 1] - times[i] <= dense_gap:
            forbidden.add(lanes[i + 1])
        companions = [lane for lane in range(6) if lane not in forbidden]
        companions.sort(key=lambda lane: (lane in (0, 5), abs(lane - lanes[i])))
        if companions:
            chords.append((i, companions[0]))
    return lanes, chords


def _turkish_beatmap(song: Song, lead_in: float = 2.0) -> Beatmap:
    """Chart the Turkish March with spread-out runs and accent chords."""
    melody = song.chart_notes if song.chart_notes is not None else song.notes
    if not melody:
        return Beatmap(song.id, [], lead_in=lead_in)
    lanes, chords = _turkish_lane_plan(melody, song.bpm)
    notes = [RNote(note.time + lead_in, lanes[i])
             for i, note in enumerate(melody)]
    notes.extend(RNote(melody[i].time + lead_in, lane) for i, lane in chords)
    notes.sort(key=lambda r: (r.time, r.lane))
    return Beatmap(song.id, notes, lead_in=lead_in)


class SongPlayer:
    """Drives auto-playback; call update(dt) each frame. Pause freezes time.

    `vol` and `length` carry the user's per-timbre sound settings: volume
    scales every note's velocity, length rescales each note's duration.
    """

    def __init__(self, engine, song: Song, timbre: str,
                 vol: float = 1.0, length: float = 1.0):
        self.engine = engine
        self.song = song
        self.timbre = timbre
        self.vol = vol
        self.length = length
        self.pos = 0.0
        self.idx = 0
        self.playing = False
        self.finished = False

    def start(self) -> None:
        self.pos = 0.0
        self.idx = 0
        self.playing = True
        self.finished = False

    def pause(self) -> None:
        self.playing = False

    def resume(self) -> None:
        if not self.finished:
            self.playing = True

    def stop(self) -> None:
        self.playing = False
        self.engine.stop_all()

    def set_timbre(self, tid: str) -> None:
        self.timbre = tid

    def update(self, dt: float) -> None:
        if not self.playing or self.finished:
            return
        self.pos += dt
        notes = self.song.notes
        while self.idx < len(notes) and notes[self.idx].time <= self.pos:
            n = notes[self.idx]
            self.engine.play_note(self.timbre, n.midi, n.dur * self.length,
                                  n.vel * self.vol)
            self.idx += 1
        if self.idx >= len(notes) and self.pos >= self.song.duration:
            self.finished = True
            self.playing = False

    @property
    def progress(self) -> float:
        d = self.song.duration
        return min(1.0, self.pos / d) if d > 0 else 0.0


# Library --------------------------------------------------------------------
SONGS: Dict[str, Song] = {}
ORDER: List[str] = []
RHYTHM_ORDER: List[str] = ["canon", "minuet_g", "turkish_march"]


def register(song: Song) -> Song:
    SONGS[song.id] = song
    if song.id not in ORDER:
        ORDER.append(song.id)
    return song


def get_song(sid: Optional[str]) -> Song:
    if sid and sid in SONGS:
        return SONGS[sid]
    return SONGS[ORDER[0]]


def first_song_id() -> str:
    return ORDER[0]


# 小星星 / Twinkle Twinkle Little Star (public domain) — keep first: default prenatal song.
_twinkle = seq([
    (60, 1), (60, 1), (67, 1), (67, 1), (69, 1), (69, 1), (67, 2),
    (65, 1), (65, 1), (64, 1), (64, 1), (62, 1), (62, 1), (60, 2),
    (67, 1), (67, 1), (65, 1), (65, 1), (64, 1), (64, 1), (62, 2),
    (67, 1), (67, 1), (65, 1), (65, 1), (64, 1), (64, 1), (62, 2),
    (60, 1), (60, 1), (67, 1), (67, 1), (69, 1), (69, 1), (67, 2),
    (65, 1), (65, 1), (64, 1), (64, 1), (62, 1), (62, 1), (60, 2),
], bpm=100)
register(Song("twinkle", "小星星", "Twinkle Twinkle", 100, _twinkle))

# 玛丽有只小羊羔 / Mary Had a Little Lamb (traditional, public domain)
register(Song("mary_lamb", "玛丽有只小羊羔", "Mary Had a Little Lamb", 100, seq([
    (64, 1), (62, 1), (60, 1), (62, 1), (64, 1), (64, 1), (64, 2),
    (62, 1), (62, 1), (62, 2), (64, 1), (67, 1), (67, 2),
    (64, 1), (62, 1), (60, 1), (62, 1), (64, 1), (64, 1), (64, 1), (64, 1),
    (62, 1), (62, 1), (64, 1), (62, 1), (60, 4),
], bpm=100)))

# 欢乐颂 / Ode to Joy (Beethoven, public domain) — the complete 4-phrase theme.
register(Song("ode_joy", "欢乐颂", "Ode to Joy", 100, seq([
    # Phrase 1
    (64, 1), (64, 1), (65, 1), (67, 1), (67, 1), (65, 1), (64, 1), (62, 1),
    (60, 1), (60, 1), (62, 1), (64, 1), (64, 1.5), (62, 0.5), (62, 2),
    # Phrase 2
    (64, 1), (64, 1), (65, 1), (67, 1), (67, 1), (65, 1), (64, 1), (62, 1),
    (60, 1), (60, 1), (62, 1), (64, 1), (62, 1.5), (60, 0.5), (60, 2),
    # Phrase 3 ("Deine Zauber binden wieder ...")
    (62, 1), (62, 1), (64, 1), (60, 1),
    (62, 0.5), (64, 0.5), (65, 1), (64, 0.5), (62, 0.5), (60, 1),
    (62, 0.5), (64, 0.5), (65, 1), (64, 0.5), (62, 0.5), (60, 1),
    (62, 0.5), (64, 0.5), (65, 1), (64, 0.5), (62, 0.5), (55, 1.5),
    # Phrase 4 ("Alle Menschen werden Brüder ...")
    (64, 1), (64, 1), (65, 1), (67, 1), (67, 1), (65, 1), (64, 1), (62, 1),
    (60, 1), (60, 1), (62, 1), (64, 1), (62, 1.5), (60, 0.5), (60, 2),
], bpm=100)))

# 铃儿响叮当 / Jingle Bells (James Pierpont, public domain) — verse + chorus.
register(Song("jingle_bells", "铃儿响叮当", "Jingle Bells", 120, seq([
    # Verse
    (67, 1), (64, 1), (62, 1), (60, 2),                              # Dashing through the snow
    (67, 1), (67, 1), (67, 1), (67, 1), (64, 1), (62, 0.5), (60, 0.5), (69, 2),  # in a one-horse open sleigh
    (69, 1), (65, 1), (64, 1), (62, 1), (71, 2),                     # O'er the fields we go
    (67, 1), (67, 1), (65, 1), (62, 1), (64, 2),                     # laughing all the way
    (67, 1), (64, 1), (62, 1), (60, 2),                              # Bells on bobtail ring
    (67, 1), (67, 1), (64, 1), (62, 1), (60, 1), (69, 2),            # making spirits bright
    (69, 1), (69, 1), (65, 1), (64, 1), (62, 1),                     # What fun it is to ride
    (67, 1), (67, 1), (67, 1), (67, 1),                              # and sing a sleighing
    (69, 1), (67, 1), (65, 1), (62, 1), (60, 4),                     # song tonight
    # Chorus
    (64, 1), (64, 1), (64, 2), (64, 1), (64, 1), (64, 2),
    (64, 1), (67, 1), (60, 1), (62, 1), (64, 4),
    (65, 1), (65, 1), (65, 1), (65, 1), (65, 1), (64, 1), (64, 1),
    (64, 0.5), (64, 0.5), (64, 1), (62, 1), (62, 1), (64, 1), (62, 2), (67, 2),
    (64, 1), (64, 1), (64, 2), (64, 1), (64, 1), (64, 2),
    (64, 1), (67, 1), (60, 1), (62, 1), (64, 4),
    (65, 1), (65, 1), (65, 1), (65, 1), (65, 1), (64, 1), (64, 1),
    (64, 0.5), (64, 0.5), (67, 1), (67, 1), (65, 1), (62, 1), (60, 4),
], bpm=120)))

# 祝你生日快乐 / Happy Birthday (public domain since 2016)
register(Song("happy_birthday", "祝你生日快乐", "Happy Birthday", 120, seq([
    (67, 0.75), (67, 0.25), (69, 1), (67, 1), (72, 1), (71, 2),
    (67, 0.75), (67, 0.25), (69, 1), (67, 1), (74, 1), (72, 2),
    (67, 0.75), (67, 0.25), (79, 1), (76, 1), (72, 1), (71, 1), (69, 2),
    (77, 0.75), (77, 0.25), (76, 1), (72, 1), (74, 1), (72, 2),
], bpm=120)))

# 卡农 / Canon in C — the complete Canon per 3 Violini e Basso, transposed
# from D major. Source: Mutopia-2015/09/02-2047 (IMSLP), typeset by Michael
# Fischer v. Mollard, CC BY 4.0:
# https://www.mutopiaproject.org/cgibin/piece-info.cgi?id=2047
# The 50-bar violin canon enters at beats 8, 16 and 24. The ground bass
# repeats 28 times; all four parts begin their final notes on beat 224.
_CANON_BPM = 55.0

_CANON_COMMON = [
    # Bar 1
    (76, 1), (74, 1), (72, 1), (71, 1),
    # Bar 2
    (69, 1), (67, 1), (69, 1), (71, 1),
    # Bar 3
    (72, 1), (71, 1), (69, 1), (67, 1),
    # Bar 4
    (65, 1), (64, 1), (65, 1), (62, 1),
    # Bar 5
    (60, 0.5), (64, 0.5), (67, 0.5), (65, 0.5), (64, 0.5), (60, 0.5), (64, 0.5), (62, 0.5),
    # Bar 6
    (60, 0.5), (57, 0.5), (60, 0.5), (67, 0.5), (65, 0.5), (69, 0.5), (67, 0.5), (65, 0.5),
    # Bar 7
    (64, 0.5), (60, 0.5), (62, 0.5), (71, 0.5), (72, 0.5), (76, 0.5), (79, 0.5), (67, 0.5),
    # Bar 8
    (69, 0.5), (65, 0.5), (67, 0.5), (64, 0.5), (60, 0.5), (72, 0.5), (72, 0.75), (71, 0.25),
    # Bar 9
    (72, 0.25), (71, 0.25), (72, 0.25), (60, 0.25), (59, 0.25), (67, 0.25), (62, 0.25),
    (64, 0.25), (60, 0.25), (72, 0.25), (71, 0.25), (69, 0.25), (71, 0.25), (76, 0.25),
    (79, 0.25), (81, 0.25),
    # Bar 10
    (77, 0.25), (76, 0.25), (74, 0.25), (77, 0.25), (76, 0.25), (74, 0.25), (72, 0.25),
    (71, 0.25), (69, 0.25), (67, 0.25), (65, 0.25), (64, 0.25), (62, 0.25), (65, 0.25),
    (64, 0.25), (62, 0.25),
    # Bar 11
    (60, 0.25), (62, 0.25), (64, 0.25), (65, 0.25), (67, 0.25), (62, 0.25), (67, 0.25),
    (65, 0.25), (64, 0.25), (69, 0.25), (67, 0.25), (65, 0.25), (67, 0.25), (65, 0.25),
    (64, 0.25), (62, 0.25),
    # Bar 12
    (60, 0.25), (57, 0.25), (69, 0.25), (71, 0.25), (72, 0.25), (71, 0.25), (69, 0.25),
    (67, 0.25), (65, 0.25), (64, 0.25), (62, 0.25), (69, 0.25), (67, 0.25), (69, 0.25),
    (67, 0.25), (65, 0.25),
    # Bar 13
    (64, 0.5), (76, 0.5), (74, 1), (0, 0.5), (72, 0.5), (76, 1),
    # Bar 14
    (81, 1), (79, 1), (81, 1), (83, 1),
    # Bar 15
    (84, 0.5), (72, 0.5), (71, 1), (0, 0.5), (69, 0.5), (72, 1),
    # Bar 16
    (72, 1.5), (72, 0.5), (72, 0.5), (77, 0.5), (74, 0.5), (79, 0.5),
    # Bar 17
    (79, 0.25), (76, 0.125), (77, 0.125), (79, 0.25), (76, 0.125), (77, 0.125), (79, 0.125),
    (67, 0.125), (69, 0.125), (71, 0.125), (72, 0.125), (74, 0.125), (76, 0.125), (77, 0.125),
    (76, 0.25), (72, 0.125), (74, 0.125), (76, 0.25), (64, 0.125), (65, 0.125), (67, 0.125),
    (69, 0.125), (67, 0.125), (65, 0.125), (67, 0.125), (64, 0.125), (65, 0.125), (67, 0.125),
    # Bar 18
    (65, 0.25), (69, 0.125), (67, 0.125), (65, 0.25), (64, 0.125), (62, 0.125), (64, 0.125),
    (62, 0.125), (60, 0.125), (62, 0.125), (64, 0.125), (65, 0.125), (67, 0.125), (69, 0.125),
    (65, 0.25), (69, 0.125), (67, 0.125), (69, 0.25), (71, 0.125), (72, 0.125), (67, 0.125),
    (69, 0.125), (71, 0.125), (72, 0.125), (74, 0.125), (76, 0.125), (77, 0.125), (79, 0.125),
    # Bar 19
    (76, 0.25), (72, 0.125), (74, 0.125), (76, 0.25), (74, 0.125), (72, 0.125), (74, 0.125),
    (71, 0.125), (72, 0.125), (74, 0.125), (76, 0.125), (74, 0.125), (72, 0.125), (71, 0.125),
    (72, 0.25), (69, 0.125), (71, 0.125), (72, 0.25), (60, 0.125), (62, 0.125), (64, 0.125),
    (65, 0.125), (64, 0.125), (62, 0.125), (64, 0.125), (72, 0.125), (71, 0.125), (72, 0.125),
    # Bar 20
    (69, 0.25), (72, 0.125), (71, 0.125), (69, 0.25), (67, 0.125), (65, 0.125), (67, 0.125),
    (65, 0.125), (64, 0.125), (65, 0.125), (67, 0.125), (69, 0.125), (71, 0.125), (72, 0.125),
    (69, 0.25), (72, 0.125), (71, 0.125), (72, 0.25), (71, 0.125), (69, 0.125), (71, 0.125),
    (72, 0.125), (74, 0.125), (72, 0.125), (71, 0.125), (72, 0.125), (69, 0.125), (71, 0.125),
    # Bar 21
    (72, 0.5), (0, 0.5), (71, 0.5), (0, 0.5), (69, 0.5), (0, 0.5), (72, 0.5), (0, 0.5),
    # Bar 22
    (60, 0.5), (0, 0.5), (60, 0.5), (0, 0.5), (60, 0.5), (0, 0.5), (62, 0.5), (0, 1),
    # Bar 23
    (67, 0.5), (0, 0.5), (67, 0.5), (0, 0.5), (64, 0.5), (0, 0.5), (67, 0.5),
    # Bar 24
    (0, 0.5), (65, 0.5), (0, 0.5), (64, 0.5), (0, 0.5), (65, 0.5), (0, 0.5), (74, 0.5),
    # Bar 25
    (76, 0.25), (64, 0.25), (65, 0.25), (64, 0.25), (62, 0.25), (74, 0.25), (76, 0.25),
    (74, 0.25), (72, 0.25), (64, 0.25), (60, 0.25), (69, 0.25), (67, 0.25), (55, 0.25),
    (53, 0.25), (55, 0.25),
    # Bar 26
    (57, 0.25), (69, 0.25), (71, 0.25), (69, 0.25), (67, 0.25), (55, 0.25), (53, 0.25),
    (55, 0.25), (57, 0.25), (69, 0.25), (67, 0.25), (69, 0.25), (71, 0.25), (59, 0.25),
    (57, 0.25), (59, 0.25),
    # Bar 27
    (60, 0.25), (72, 0.25), (74, 0.25), (72, 0.25), (71, 0.25), (59, 0.25), (60, 0.25),
    (59, 0.25), (57, 0.25), (69, 0.25), (67, 0.25), (69, 0.25), (71, 0.25), (59, 0.25),
    (64, 0.25), (62, 0.25),
    # Bar 28
    (60, 0.25), (72, 0.25), (74, 0.25), (77, 0.25), (76, 0.25), (64, 0.25), (67, 0.25),
    (76, 0.25), (72, 0.25), (77, 0.25), (76, 0.25), (77, 0.25), (74, 0.25), (67, 0.25),
    (65, 0.25), (67, 0.25),
    # Bar 29
    (64, 0.25), (67, 0.25), (67, 0.25), (67, 0.25), (67, 0.25), (67, 0.25), (67, 0.25),
    (67, 0.25), (64, 0.25), (64, 0.25), (64, 0.25), (64, 0.25), (64, 0.25), (64, 0.25),
    (67, 0.25), (67, 0.25),
    # Bar 30
    (65, 0.25), (65, 0.25), (65, 0.25), (72, 0.25), (72, 0.25), (72, 0.25), (72, 0.25),
    (72, 0.25), (72, 0.25), (72, 0.25), (69, 0.25), (69, 0.25), (67, 0.25), (67, 0.25),
    (74, 0.25), (71, 0.25),
    # Bar 31
    (67, 0.25), (76, 0.25), (76, 0.25), (76, 0.25), (74, 0.25), (74, 0.25), (74, 0.25),
    (74, 0.25), (72, 0.25), (72, 0.25), (72, 0.25), (72, 0.25), (79, 0.25), (79, 0.25),
    (79, 0.25), (79, 0.25),
    # Bar 32
    (81, 0.25), (81, 0.25), (81, 0.25), (81, 0.25), (79, 0.25), (79, 0.25), (79, 0.25),
    (79, 0.25), (81, 0.25), (81, 0.25), (81, 0.25), (81, 0.25), (83, 0.25), (71, 0.25),
    (71, 0.25), (71, 0.25),
    # Bar 33
    (72, 0.25), (60, 0.125), (62, 0.125), (64, 0.25), (60, 0.25), (59, 0.25), (71, 0.125),
    (72, 0.125), (74, 0.25), (71, 0.25), (69, 0.25), (57, 0.125), (59, 0.125), (60, 0.25),
    (57, 0.25), (59, 0.25), (67, 0.125), (65, 0.125), (64, 0.25), (62, 0.25),
    # Bar 34
    (60, 0.25), (65, 0.125), (64, 0.125), (62, 0.25), (65, 0.25), (64, 0.25), (60, 0.125),
    (62, 0.125), (64, 0.25), (67, 0.25), (65, 0.25), (69, 0.125), (67, 0.125), (65, 0.25),
    (64, 0.25), (62, 0.25), (67, 0.125), (65, 0.125), (64, 0.25), (62, 0.25),
    # Bar 35
    (64, 0.25), (72, 0.125), (71, 0.125), (72, 0.25), (64, 0.25), (67, 0.25), (67, 0.125),
    (69, 0.125), (71, 0.25), (67, 0.25), (64, 0.25), (72, 0.125), (74, 0.125), (76, 0.25),
    (72, 0.25), (76, 0.25), (76, 0.125), (74, 0.125), (72, 0.25), (71, 0.25),
    # Bar 36
    (69, 0.25), (69, 0.125), (67, 0.125), (69, 0.25), (71, 0.25), (72, 0.25), (76, 0.125),
    (74, 0.125), (72, 0.25), (76, 0.25), (77, 0.25), (72, 0.125), (71, 0.125), (69, 0.25),
    (69, 0.25), (67, 0.25), (62, 0.25), (67, 0.25), (67, 0.25),
    # Bar 37
    (67, 1.5), (67, 0.5), (60, 1.5), (67, 0.5),
    # Bar 38
    (65, 1), (67, 1), (65, 0.5), (60, 0.5), (60, 0.75), (59, 0.25),
    # Bar 39
    (60, 0.5), (72, 0.5), (71, 1), (69, 1), (67, 1),
    # Bar 40
    (60, 0.75), (62, 0.25), (64, 1), (69, 1), (62, 0.75), (62, 0.25),
    # Bar 41
    (64, 0.75), (76, 0.25), (76, 0.25), (77, 0.25), (76, 0.25), (74, 0.25), (72, 0.75),
    (72, 0.25), (72, 0.25), (74, 0.25), (72, 0.25), (71, 0.25),
    # Bar 42
    (69, 1), (72, 1), (72, 0.25), (70, 0.25), (69, 0.25), (70, 0.25), (67, 0.75), (67, 0.25),
    # Bar 43
    (67, 0.75), (79, 0.25), (79, 0.25), (81, 0.25), (79, 0.25), (77, 0.25), (76, 0.75),
    (76, 0.25), (76, 0.25), (77, 0.25), (76, 0.25), (74, 0.25),
    # Bar 44
    (72, 0.25), (70, 0.25), (69, 0.25), (70, 0.25), (67, 0.75), (67, 0.25), (65, 0.5),
    (72, 0.5), (71, 0.75), (71, 0.25),
    # Bar 45
    (72, 0.5), (72, 1), (71, 1), (69, 1), (67, 1),
    # Bar 46
    (65, 1), (64, 1.25), (62, 0.25), (62, 1),
    # Bar 47
    (64, 0.5), (76, 1), (74, 0.5), (72, 0.5), (84, 1), (82, 0.5),
    # Bar 48
    (81, 1), (84, 0.5), (79, 0.5), (81, 1), (79, 1),
    # Bar 49
    (79, 1), (67, 0.75), (65, 0.25), (64, 1), (76, 0.75), (74, 0.25),
    # Bar 50
    (72, 1.5), (72, 0.5), (72, 1), (71, 1),
]

_CANON_END_I = [
    # Bar 1
    (72, 0.5), (60, 0.5), (59, 0.5), (71, 0.5), (69, 0.5), (57, 0.5), (55, 0.5), (67, 0.5),
    # Bar 2
    (65, 0.5), (77, 0.5), (76, 0.5), (64, 0.5), (62, 0.5), (69, 0.5), (62, 0.5), (74, 0.5),
    # Bar 3
    (76, 0.5), (64, 0.5), (62, 0.5), (74, 0.5), (72, 0.5), (60, 0.5), (59, 0.5), (71, 0.5),
    # Bar 4
    (69, 0.5), (81, 0.5), (79, 0.5), (67, 0.5), (65, 0.75), (74, 0.25), (67, 0.5), (67, 0.5),
    # Bar 5
    (67, 1),
]

_CANON_END_II = [
    # Bar 1
    (72, 0.5), (60, 0.5), (59, 0.5), (71, 0.5), (69, 0.5), (57, 0.5), (55, 0.5), (67, 0.5),
    # Bar 2
    (65, 0.5), (77, 0.5), (76, 0.5), (64, 0.5), (62, 0.5), (69, 0.5), (62, 0.5), (74, 0.5),
    # Bar 3
    (76, 1),
]

_CANON_END_III = [
    # Bar 1
    (72, 1),
]

_CANON_BASS = [(48, 1), (43, 1), (45, 1), (40, 1), (41, 1), (36, 1), (41, 1), (43, 1)]
def _canon_violin(entry_beats: float, ending) -> List[Note]:
    return seq(_CANON_COMMON + ending, bpm=_CANON_BPM,
               start=entry_beats * 60.0 / _CANON_BPM)


_canon_violin_one = _canon_violin(8, _CANON_END_I)
_canon_violin_two = _canon_violin(16, _CANON_END_II)
_canon_violin_three = _canon_violin(24, _CANON_END_III)
_canon_bass = seq(_CANON_BASS * 28 + [_CANON_BASS[0]], bpm=_CANON_BPM)
_canon_notes = sorted(
    _canon_violin_one + _canon_violin_two + _canon_violin_three + _canon_bass,
    key=lambda n: n.time,
)
# Only violin I becomes falling notes; the complete four-part score auto-plays.
# Canon is the rhythm game's song, and its timbre is locked to the didgeridoo.
register(Song("canon", "卡农", "Canon in C", _CANON_BPM, _canon_notes,
              chart_notes=_canon_violin_one, timbre="didgeridoo"))

# Canon's chart is authored rather than pitch-derived: whole bars repeat one
# pitch, so a pitch mapping stacks 20+ taps on a single lane. Dense runs cycle
# the middle four lanes (S D J K); isolated notes spread across all six.
_CANON_LANE_BOUNDS = (62, 66, 70, 74, 79)
# Each bank rotates every couple of cycles so a long stream never settles into
# one memorisable loop. Consecutive shapes are ordered so the hand alternation
# and the lane changes survive the switch.
_CANON_ROLLS = ((1, 2, 3, 4), (2, 4, 1, 3), (4, 3, 2, 1), (3, 4, 1, 2))
_CANON_BURSTS = ((1, 3, 2, 4), (2, 4, 1, 3), (1, 4, 2, 3), (2, 3, 1, 4))
_CANON_REPEATS = 2
_CANON_ENTRY_BEATS = 8


def _canon_stream(patterns):
    bank = 0
    while True:
        for _ in range(_CANON_REPEATS):
            yield from patterns[bank % len(patterns)]
        bank += 1


def _canon_beatmap(song: Song, lead_in: float = 2.0) -> Beatmap:
    melody = song.chart_notes if song.chart_notes is not None else song.notes
    spb = 60.0 / song.bpm
    count = len(melody)

    def gap(i: int) -> float:
        before = melody[i].time - melody[i - 1].time if i > 0 else math.inf
        after = melody[i + 1].time - melody[i].time if i < count - 1 else math.inf
        return min(before, after)

    lanes: List[int] = []
    roll = _canon_stream(_CANON_ROLLS)
    burst = _canon_stream(_CANON_BURSTS)
    for i, n in enumerate(melody):
        g = gap(i)
        dense = g <= 0.25 * spb + 1e-9
        if g <= 0.125 * spb + 1e-9:
            lane = next(burst)
        elif dense:
            lane = next(roll)
        else:
            lane = bisect_right(_CANON_LANE_BOUNDS, n.midi)
        if lanes and lane == lanes[-1]:
            lane = 1 + lane % 4 if dense else (lane + 1 if lane < 5 else lane - 1)
        lanes.append(lane)

    entry = _CANON_ENTRY_BEATS * spb
    bar = 4 * spb
    bar_count = int((melody[-1].time - entry) / bar) + 1
    bars: List[List[int]] = [[] for _ in range(bar_count)]
    for i, n in enumerate(melody):
        bars[int((n.time - entry) / bar + 1e-9)].append(i)

    accents = {count - 1}
    for b, idx in enumerate(bars):
        if not idx:
            continue
        downbeat = abs(melody[idx[0]].time - (entry + b * bar)) < 1e-6
        if downbeat and (b % 4 == 0 or len(idx) <= 8):
            accents.add(idx[0])
    for b in range(0, bar_count, 4):
        idx = [i for k in range(b, min(b + 4, bar_count)) for i in bars[k]]
        if idx:
            peak = max(idx, key=lambda i: melody[i].midi)
            if gap(peak) > 0.125 * spb + 1e-9:
                accents.add(peak)

    events: Dict[float, List[int]] = {}
    for i, lane in enumerate(lanes):
        events.setdefault(melody[i].time, []).append(lane)
    times = sorted(events)
    slot = {t: k for k, t in enumerate(times)}
    for i in sorted(accents):
        t = melody[i].time
        k = slot[t]
        lane = lanes[i]
        # Mirroring across the field pairs opposite hands; neighbouring lanes
        # are excluded so the chord never forces the same key twice in a row.
        taken = {lane}
        if k > 0:
            taken |= set(events[times[k - 1]])
        if k + 1 < len(times):
            taken |= set(events[times[k + 1]])
        partners = (5 - lane, 1, 2, 3, 4)
        if gap(i) > 0.25 * spb + 1e-9:
            partners += (0, 5)
        for partner in partners:
            if partner not in taken:
                events[t].append(partner)
                break

    notes = [RNote(t + lead_in, lane) for t in times for lane in sorted(events[t])]
    return Beatmap(song.id, notes, lead_in=lead_in)

# Minuet in G, BWV Anh. 114 (Christian Petzold): complete AABB score.
_MINUET_BPM = 140.0
_MINUET_MELODY_A = [
    # Bar 1
    (74, 1), (67, 0.5), (69, 0.5), (71, 0.5), (72, 0.5),
    # Bar 2
    (74, 1), (67, 1), (67, 1),
    # Bar 3
    (76, 1), (72, 0.5), (74, 0.5), (76, 0.5), (78, 0.5),
    # Bar 4
    (79, 1), (67, 1), (67, 1),
    # Bar 5
    (72, 1), (74, 0.5), (72, 0.5), (71, 0.5), (69, 0.5),
    # Bar 6
    (71, 1), (72, 0.5), (71, 0.5), (69, 0.5), (67, 0.5),
    # Bar 7, including the written grace note before bar 8
    (66, 1), (67, 0.5), (69, 0.5), (71, 0.5),
    (67, 37 / 96), (71, 11 / 96),
    # Bar 8
    (69, 3),
    # Bar 9
    (74, 1), (67, 0.5), (69, 0.5), (71, 0.5), (72, 0.5),
    # Bar 10
    (74, 1), (67, 1), (67, 1),
    # Bar 11
    (76, 1), (72, 0.5), (74, 0.5), (76, 0.5), (78, 0.5),
    # Bar 12
    (79, 1), (67, 1), (67, 1),
    # Bar 13
    (72, 1), (74, 0.5), (72, 0.5), (71, 0.5), (69, 0.5),
    # Bar 14
    (71, 1), (72, 0.5), (71, 0.5), (69, 0.5), (67, 0.5),
    # Bar 15
    (69, 1), (71, 0.5), (69, 0.5), (67, 0.5), (66, 0.5),
    # Bar 16
    (67, 3),
]

_MINUET_MELODY_B = [
    # Bar 17
    (83, 1), (79, 0.5), (81, 0.5), (83, 0.5), (79, 0.5),
    # Bar 18
    (81, 1), (74, 0.5), (76, 0.5), (78, 0.5), (74, 0.5),
    # Bar 19
    (79, 1), (76, 0.5), (78, 0.5), (79, 0.5), (74, 0.5),
    # Bar 20
    (73, 1), (71, 0.5), (73, 0.5), (69, 1),
    # Bar 21
    (69, 0.5), (71, 0.5), (73, 0.5), (74, 0.5), (76, 0.5), (78, 0.5),
    # Bar 22
    (79, 1), (78, 1), (76, 1),
    # Bar 23
    (78, 1), (69, 1), (73, 1),
    # Bar 24
    (74, 3),
    # Bar 25
    (74, 1), (67, 0.5), (66, 0.5), (67, 1),
    # Bar 26
    (76, 1), (67, 0.5), (66, 0.5), (67, 1),
    # Bar 27
    (74, 1), (72, 1), (71, 1),
    # Bar 28
    (69, 0.5), (67, 0.5), (66, 0.5), (67, 0.5), (69, 1),
    # Bar 29
    (62, 0.5), (64, 0.5), (66, 0.5), (67, 0.5), (69, 0.5), (71, 0.5),
    # Bar 30
    (72, 1), (71, 1), (69, 1),
    # Bar 31
    (71, 0.5), (74, 0.5), (67, 1), (66, 1),
    # Bar 32
    (67, 3),
]

_MINUET_BASS_A = [
    # Bar 1; B3 and D4 are added as harmony below
    (55, 2), (57, 1),
    # Bar 2
    (59, 3),
    # Bar 3
    (60, 3),
    # Bar 4
    (59, 3),
    # Bar 5
    (57, 3),
    # Bar 6
    (55, 3),
    # Bar 7
    (62, 1), (59, 1), (55, 1),
    # Bar 8
    (62, 1), (50, 0.5), (60, 0.5), (59, 0.5), (57, 0.5),
    # Bar 9
    (59, 2), (57, 1),
    # Bar 10
    (55, 1), (59, 1), (55, 1),
    # Bar 11
    (60, 3),
    # Bar 12
    (59, 1), (60, 0.5), (59, 0.5), (57, 0.5), (55, 0.5),
    # Bar 13
    (57, 2), (54, 1),
    # Bar 14
    (55, 2), (59, 1),
    # Bar 15
    (60, 1), (62, 1), (50, 1),
    # Bar 16
    (55, 2), (43, 1),
]

_MINUET_BASS_B = [
    # Bar 17
    (55, 3),
    # Bar 18
    (54, 3),
    # Bar 19
    (52, 1), (55, 1), (52, 1),
    # Bar 20
    (57, 2), (45, 1),
    # Bar 21
    (57, 3),
    # Bar 22
    (59, 1), (62, 1), (61, 1),
    # Bar 23
    (62, 1), (54, 1), (57, 1),
    # Bar 24
    (62, 1), (50, 1), (60, 1),
    # Bar 25
    (59, 2), (59, 1),
    # Bar 26
    (60, 2), (60, 1),
    # Bar 27
    (59, 1), (57, 1), (55, 1),
    # Bar 28
    (62, 2), (0, 1),
    # Bar 29
    (50, 3),
    # Bar 30
    (52, 1), (55, 1), (54, 1),
    # Bar 31
    (55, 1), (47, 1), (50, 1),
    # Bar 32
    (55, 1), (50, 1), (43, 1),
]

_MINUET_ACCENTS_A = ((0, 62), (12, 69), (24, 62), (36, 69), (45, 62))
_MINUET_ACCENTS_B = ((0, 79), (12, 81), (24, 71), (36, 74), (45, 62))

_minuet_melody = seq(_MINUET_MELODY_A * 2 + _MINUET_MELODY_B * 2,
                     bpm=_MINUET_BPM)
_minuet_bass = seq(_MINUET_BASS_A * 2 + _MINUET_BASS_B * 2,
                   bpm=_MINUET_BPM)
_minuet_spb = 60.0 / _MINUET_BPM
_minuet_harmony = []
for _start in (0.0, 48.0):
    for _midi in (59, 62):
        _minuet_harmony.append(Note(_start * _minuet_spb, _midi,
                                    2 * _minuet_spb * 0.9))
for _start in (96.0, 144.0):
    for _offset, _midi, _beats in ((25, 62, 2), (28, 64, 2), (38, 54, 1),
                                   (45, 59, 3), (45, 62, 3)):
        _minuet_harmony.append(Note((_start + _offset) * _minuet_spb, _midi,
                                    _beats * _minuet_spb * 0.9))
_minuet_notes = sorted(_minuet_melody + _minuet_bass + _minuet_harmony,
                       key=lambda n: n.time)
# Chart-only harmony accents leave the original two-staff audio unchanged.
_minuet_chart = list(_minuet_melody)
_minuet_lead_times = {round(n.time / _minuet_spb, 9): n.time
                      for n in _minuet_melody}
for _start, _accents in ((0.0, _MINUET_ACCENTS_A), (48.0, _MINUET_ACCENTS_A),
                         (96.0, _MINUET_ACCENTS_B), (144.0, _MINUET_ACCENTS_B)):
    for _offset, _midi in _accents:
        _time = _minuet_lead_times[round(_start + _offset, 9)]
        _minuet_chart.append(Note(_time, _midi, _minuet_spb * 0.9))
_minuet_chart.sort(key=lambda n: n.time)
register(Song("minuet_g", "G 大调小步舞曲", "Minuet in G", _MINUET_BPM,
              _minuet_notes, chart_notes=_minuet_chart))


# 土耳其进行曲 / Turkish March — the complete Rondo alla Turca from Mozart's
# Piano Sonata No. 11 in A major, K. 331 (third movement), public domain.
# Source: Mutopia-2015/08/13-108, typeset by Rune Zedeler and Chris Sawer,
# public domain, via the Mutopia MIDI: the complete written-through score for
# both hands, all sections and coda, repeats not taken.
# https://www.mutopiaproject.org/cgibin/piece-info.cgi?id=108
# Tuples are (start, midi, duration) in 32nd notes. `_TURKISH_SCORE` keeps the
# complete piano texture for auto-play; `_TURKISH_CHART` is the right-hand top
# line with ornamental notes shorter than a 16th removed, so every falling
# note is playable. The rhythm game locks this piece to the electric piano.
_TURKISH_BPM = 120.0

# Complete two-hand score.
_TURKISH_SCORE = [
    (0, 71, 2), (2, 69, 2), (4, 68, 2), (6, 69, 2), (8, 57, 4), (8, 72, 4),
    (12, 60, 4), (12, 64, 4), (16, 60, 4), (16, 64, 4), (16, 74, 2), (18, 72, 2),
    (20, 60, 4), (20, 64, 4), (20, 71, 2), (22, 72, 2), (24, 57, 4), (24, 76, 4),
    (28, 60, 4), (28, 64, 4), (32, 60, 4), (32, 64, 4), (32, 77, 2), (34, 76, 2),
    (36, 60, 4), (36, 64, 4), (36, 75, 2), (38, 76, 2), (40, 57, 4), (40, 83, 2),
    (42, 81, 2), (44, 60, 4), (44, 64, 4), (44, 80, 2), (46, 81, 2), (48, 57, 4),
    (48, 83, 2), (50, 81, 2), (52, 60, 4), (52, 64, 4), (52, 80, 2), (54, 81, 2),
    (56, 57, 4), (56, 84, 8), (60, 60, 4), (60, 64, 4), (64, 60, 4), (64, 64, 4),
    (64, 81, 4), (68, 60, 4), (68, 64, 4), (68, 84, 4), (72, 52, 4), (72, 83, 4),
    (76, 59, 4), (76, 64, 4), (76, 78, 4), (76, 81, 4), (80, 59, 4), (80, 64, 4),
    (80, 76, 4), (80, 79, 4), (84, 59, 4), (84, 64, 4), (84, 78, 4), (84, 81, 4),
    (88, 52, 4), (88, 83, 4), (92, 59, 4), (92, 64, 4), (92, 78, 4), (92, 81, 4),
    (96, 59, 4), (96, 64, 4), (96, 76, 4), (96, 79, 4), (100, 59, 4), (100, 64, 4),
    (100, 78, 4), (100, 81, 4), (104, 52, 4), (104, 83, 4), (108, 59, 4), (108, 64, 4),
    (108, 78, 4), (108, 81, 4), (112, 47, 4), (112, 76, 4), (112, 79, 4), (116, 59, 4),
    (116, 75, 4), (116, 78, 4), (120, 52, 8), (120, 76, 8), (128, 72, 4), (128, 76, 4),
    (132, 74, 4), (132, 77, 4), (136, 48, 4), (136, 76, 4), (136, 79, 4), (140, 60, 4),
    (140, 76, 4), (140, 79, 4), (144, 52, 4), (144, 81, 2), (146, 79, 2), (148, 64, 4),
    (148, 77, 2), (150, 76, 2), (152, 55, 8), (152, 71, 4), (152, 74, 8), (156, 67, 4),
    (160, 72, 4), (160, 76, 4), (164, 74, 4), (164, 77, 4), (168, 48, 4), (168, 76, 4),
    (168, 79, 4), (172, 60, 4), (172, 76, 4), (172, 79, 4), (176, 52, 4), (176, 81, 2),
    (178, 79, 2), (180, 64, 4), (180, 77, 2), (182, 76, 2), (184, 55, 8), (184, 71, 8),
    (184, 74, 8), (192, 69, 4), (192, 72, 4), (196, 71, 4), (196, 74, 4), (200, 45, 4),
    (200, 72, 4), (200, 76, 4), (204, 57, 4), (204, 72, 4), (204, 76, 4), (208, 48, 4),
    (208, 77, 2), (210, 76, 2), (212, 60, 4), (212, 74, 2), (214, 72, 2), (216, 52, 8),
    (216, 68, 4), (216, 71, 8), (220, 64, 4), (224, 69, 4), (224, 72, 4), (228, 71, 4),
    (228, 74, 4), (232, 45, 4), (232, 72, 4), (232, 76, 4), (236, 57, 4), (236, 72, 4),
    (236, 76, 4), (240, 48, 4), (240, 77, 2), (242, 76, 2), (244, 60, 4), (244, 74, 2),
    (246, 72, 2), (248, 52, 8), (248, 68, 8), (248, 71, 8), (256, 71, 2), (258, 69, 2),
    (260, 68, 2), (262, 69, 2), (264, 57, 4), (264, 72, 4), (268, 60, 4), (268, 64, 4),
    (272, 60, 4), (272, 64, 4), (272, 74, 2), (274, 72, 2), (276, 60, 4), (276, 64, 4),
    (276, 71, 2), (278, 72, 2), (280, 57, 4), (280, 76, 4), (284, 60, 4), (284, 64, 4),
    (288, 60, 4), (288, 64, 4), (288, 77, 2), (290, 76, 2), (292, 60, 4), (292, 64, 4),
    (292, 75, 2), (294, 76, 2), (296, 57, 4), (296, 83, 2), (298, 81, 2), (300, 60, 4),
    (300, 64, 4), (300, 80, 2), (302, 81, 2), (304, 57, 4), (304, 83, 2), (306, 81, 2),
    (308, 60, 4), (308, 64, 4), (308, 80, 2), (310, 81, 2), (312, 53, 4), (312, 84, 4),
    (316, 57, 4), (316, 63, 4), (320, 57, 4), (320, 63, 4), (320, 81, 4), (324, 57, 4),
    (324, 63, 4), (324, 83, 4), (328, 52, 4), (328, 84, 4), (332, 57, 4), (332, 64, 4),
    (332, 83, 4), (336, 50, 4), (336, 81, 4), (340, 53, 4), (340, 59, 4), (340, 80, 4),
    (344, 48, 4), (344, 81, 4), (348, 52, 4), (348, 57, 4), (348, 76, 4), (352, 50, 4),
    (352, 77, 4), (356, 53, 4), (356, 59, 4), (356, 74, 4), (360, 52, 4), (360, 57, 4),
    (360, 72, 8), (364, 52, 4), (364, 57, 4), (368, 52, 4), (368, 56, 4), (368, 71, 6),
    (372, 52, 4), (372, 56, 4), (374, 69, 1), (375, 71, 1), (376, 45, 7), (376, 57, 7),
    (376, 69, 8), (384, 69, 4), (384, 81, 4), (388, 71, 4), (388, 83, 4), (392, 57, 4),
    (392, 73, 8), (392, 85, 8), (396, 57, 4), (400, 57, 4), (400, 69, 4), (400, 81, 4),
    (404, 57, 3), (404, 71, 4), (404, 83, 4), (408, 57, 4), (408, 73, 4), (408, 85, 4),
    (412, 57, 4), (412, 71, 4), (412, 83, 4), (416, 57, 4), (416, 69, 4), (416, 81, 4),
    (420, 57, 3), (420, 68, 4), (420, 80, 4), (424, 50, 4), (424, 66, 4), (424, 78, 4),
    (428, 50, 3), (428, 68, 4), (428, 80, 4), (432, 51, 4), (432, 69, 4), (432, 81, 4),
    (436, 51, 3), (436, 71, 4), (436, 83, 4), (440, 52, 4), (440, 68, 4), (440, 80, 4),
    (444, 52, 4), (444, 64, 4), (444, 76, 4), (448, 52, 4), (448, 69, 4), (448, 81, 4),
    (452, 52, 3), (452, 71, 4), (452, 83, 4), (456, 57, 4), (456, 73, 8), (456, 85, 8),
    (460, 57, 4), (464, 57, 4), (464, 69, 4), (464, 81, 4), (468, 57, 3), (468, 71, 4),
    (468, 83, 4), (472, 57, 4), (472, 73, 4), (472, 85, 4), (476, 57, 4), (476, 71, 4),
    (476, 83, 4), (480, 57, 4), (480, 69, 4), (480, 81, 4), (484, 57, 3), (484, 68, 4),
    (484, 80, 4), (488, 50, 4), (488, 66, 4), (488, 78, 4), (492, 50, 3), (492, 71, 4),
    (492, 83, 4), (496, 52, 4), (496, 68, 4), (496, 80, 4), (500, 52, 4), (500, 64, 4),
    (500, 76, 4), (504, 45, 8), (504, 69, 8), (504, 81, 8), (512, 85, 2), (514, 86, 2),
    (516, 85, 2), (518, 83, 2), (520, 54, 4), (520, 81, 2), (522, 83, 2), (524, 57, 4),
    (524, 61, 4), (524, 81, 2), (526, 80, 2), (528, 57, 4), (528, 61, 4), (528, 78, 2),
    (530, 81, 2), (532, 57, 4), (532, 61, 4), (532, 80, 2), (534, 78, 2), (536, 56, 4),
    (536, 77, 2), (538, 78, 2), (540, 59, 4), (540, 61, 4), (540, 80, 2), (542, 77, 2),
    (544, 59, 4), (544, 61, 4), (544, 73, 2), (546, 75, 2), (548, 59, 4), (548, 61, 4),
    (548, 77, 2), (550, 73, 2), (552, 54, 4), (552, 78, 2), (554, 77, 2), (556, 57, 4),
    (556, 61, 4), (556, 78, 2), (558, 80, 2), (560, 57, 4), (560, 61, 4), (560, 81, 2),
    (562, 80, 2), (564, 57, 4), (564, 61, 4), (564, 81, 2), (566, 83, 2), (568, 53, 4),
    (568, 85, 2), (570, 84, 2), (572, 56, 4), (572, 61, 4), (572, 85, 2), (574, 84, 2),
    (576, 56, 4), (576, 61, 4), (576, 85, 2), (578, 86, 2), (580, 56, 4), (580, 61, 4),
    (580, 85, 2), (582, 83, 2), (584, 54, 4), (584, 81, 2), (586, 83, 2), (588, 57, 4),
    (588, 61, 4), (588, 81, 2), (590, 80, 2), (592, 57, 4), (592, 61, 4), (592, 78, 2),
    (594, 81, 2), (596, 57, 4), (596, 61, 4), (596, 80, 2), (598, 78, 2), (600, 56, 4),
    (600, 76, 2), (602, 78, 2), (604, 61, 4), (604, 64, 4), (604, 80, 2), (606, 76, 2),
    (608, 61, 4), (608, 64, 4), (608, 73, 2), (610, 75, 2), (612, 61, 4), (612, 64, 4),
    (612, 76, 2), (614, 73, 2), (616, 56, 4), (616, 75, 2), (618, 76, 2), (620, 63, 4),
    (620, 66, 4), (620, 78, 2), (622, 75, 2), (624, 63, 4), (624, 66, 4), (624, 72, 2),
    (626, 73, 2), (628, 63, 4), (628, 66, 4), (628, 75, 2), (630, 72, 2), (632, 61, 8),
    (632, 64, 8), (632, 73, 8), (640, 76, 2), (642, 74, 2), (644, 73, 2), (646, 71, 2),
    (648, 57, 4), (648, 69, 2), (650, 71, 2), (652, 61, 4), (652, 64, 4), (652, 73, 2),
    (654, 74, 2), (656, 61, 4), (656, 64, 4), (656, 76, 2), (658, 78, 2), (660, 61, 4),
    (660, 64, 4), (660, 80, 2), (662, 81, 2), (664, 59, 4), (664, 81, 2), (666, 80, 2),
    (668, 62, 4), (668, 64, 4), (668, 78, 2), (670, 76, 2), (672, 56, 4), (672, 76, 2),
    (674, 74, 2), (676, 62, 4), (676, 64, 4), (676, 73, 2), (678, 71, 2), (680, 57, 4),
    (680, 69, 2), (682, 71, 2), (684, 61, 4), (684, 64, 4), (684, 73, 2), (686, 74, 2),
    (688, 61, 4), (688, 64, 4), (688, 76, 2), (690, 78, 2), (692, 61, 4), (692, 64, 4),
    (692, 80, 2), (694, 81, 2), (696, 52, 4), (696, 82, 4), (700, 56, 4), (700, 62, 4),
    (700, 83, 4), (704, 56, 4), (704, 62, 4), (704, 76, 2), (706, 74, 2), (708, 56, 4),
    (708, 62, 4), (708, 73, 2), (710, 71, 2), (712, 57, 4), (712, 69, 2), (714, 71, 2),
    (716, 61, 4), (716, 64, 4), (716, 73, 2), (718, 74, 2), (720, 61, 4), (720, 64, 4),
    (720, 76, 2), (722, 78, 2), (724, 61, 4), (724, 64, 4), (724, 80, 2), (726, 81, 2),
    (728, 59, 4), (728, 81, 2), (730, 80, 2), (732, 62, 4), (732, 64, 4), (732, 78, 2),
    (734, 76, 2), (736, 56, 4), (736, 76, 2), (738, 74, 2), (740, 62, 4), (740, 64, 4),
    (740, 73, 2), (742, 71, 2), (744, 57, 4), (744, 73, 2), (746, 76, 2), (748, 54, 4),
    (748, 69, 2), (750, 73, 2), (752, 50, 4), (752, 71, 2), (754, 74, 2), (756, 52, 4),
    (756, 68, 2), (758, 71, 2), (760, 45, 4), (760, 69, 8), (764, 57, 4), (768, 85, 2),
    (770, 86, 2), (772, 85, 2), (774, 83, 2), (776, 54, 4), (776, 81, 2), (778, 83, 2),
    (780, 57, 4), (780, 61, 4), (780, 81, 2), (782, 80, 2), (784, 57, 4), (784, 61, 4),
    (784, 78, 2), (786, 81, 2), (788, 57, 4), (788, 61, 4), (788, 80, 2), (790, 78, 2),
    (792, 56, 4), (792, 77, 2), (794, 78, 2), (796, 59, 4), (796, 61, 4), (796, 80, 2),
    (798, 77, 2), (800, 59, 4), (800, 61, 4), (800, 73, 2), (802, 75, 2), (804, 59, 4),
    (804, 61, 4), (804, 77, 2), (806, 73, 2), (808, 54, 4), (808, 78, 2), (810, 77, 2),
    (812, 57, 4), (812, 61, 4), (812, 78, 2), (814, 80, 2), (816, 57, 4), (816, 61, 4),
    (816, 81, 2), (818, 80, 2), (820, 57, 4), (820, 61, 4), (820, 81, 2), (822, 83, 2),
    (824, 49, 4), (824, 85, 2), (826, 84, 2), (828, 56, 4), (828, 61, 4), (828, 85, 2),
    (830, 84, 2), (832, 55, 4), (832, 61, 4), (832, 85, 2), (834, 84, 2), (836, 54, 4),
    (836, 61, 4), (836, 85, 2), (838, 82, 2), (840, 47, 4), (840, 86, 2), (842, 85, 2),
    (844, 54, 4), (844, 59, 4), (844, 86, 2), (846, 85, 2), (848, 54, 4), (848, 59, 4),
    (848, 86, 2), (850, 85, 2), (852, 54, 4), (852, 59, 4), (852, 86, 2), (854, 85, 2),
    (856, 47, 4), (856, 86, 2), (858, 85, 2), (860, 56, 4), (860, 59, 4), (860, 83, 2),
    (862, 81, 2), (864, 56, 4), (864, 59, 4), (864, 80, 2), (866, 81, 2), (868, 56, 4),
    (868, 59, 4), (868, 83, 2), (870, 80, 2), (872, 49, 4), (872, 81, 2), (874, 83, 2),
    (876, 54, 4), (876, 57, 4), (876, 85, 2), (878, 78, 2), (880, 49, 4), (880, 77, 2),
    (882, 78, 2), (884, 56, 4), (884, 59, 4), (884, 80, 2), (886, 77, 2), (888, 54, 7),
    (888, 57, 7), (888, 78, 8), (896, 69, 4), (896, 81, 4), (900, 71, 4), (900, 83, 4),
    (904, 57, 4), (904, 73, 8), (904, 85, 8), (908, 57, 4), (912, 57, 4), (912, 69, 4),
    (912, 81, 4), (916, 57, 3), (916, 71, 4), (916, 83, 4), (920, 57, 4), (920, 73, 4),
    (920, 85, 4), (924, 57, 4), (924, 71, 4), (924, 83, 4), (928, 57, 4), (928, 69, 4),
    (928, 81, 4), (932, 57, 3), (932, 68, 4), (932, 80, 4), (936, 50, 4), (936, 66, 4),
    (936, 78, 4), (940, 50, 3), (940, 68, 4), (940, 80, 4), (944, 51, 4), (944, 69, 4),
    (944, 81, 4), (948, 51, 3), (948, 71, 4), (948, 83, 4), (952, 52, 4), (952, 68, 4),
    (952, 80, 4), (956, 52, 4), (956, 64, 4), (956, 76, 4), (960, 52, 4), (960, 69, 4),
    (960, 81, 4), (964, 52, 3), (964, 71, 4), (964, 83, 4), (968, 57, 4), (968, 73, 8),
    (968, 85, 8), (972, 57, 4), (976, 57, 4), (976, 69, 4), (976, 81, 4), (980, 57, 3),
    (980, 71, 4), (980, 83, 4), (984, 57, 4), (984, 73, 4), (984, 85, 4), (988, 57, 4),
    (988, 71, 4), (988, 83, 4), (992, 57, 4), (992, 69, 4), (992, 81, 4), (996, 57, 3),
    (996, 68, 4), (996, 80, 4), (1000, 50, 4), (1000, 66, 4), (1000, 78, 4), (1004, 50, 3),
    (1004, 71, 4), (1004, 83, 4), (1008, 52, 4), (1008, 68, 4), (1008, 80, 4), (1012, 52, 4),
    (1012, 64, 4), (1012, 76, 4), (1016, 45, 8), (1016, 69, 8), (1016, 81, 8), (1024, 71, 2),
    (1026, 69, 2), (1028, 68, 2), (1030, 69, 2), (1032, 57, 4), (1032, 72, 4), (1036, 60, 4),
    (1036, 64, 4), (1040, 60, 4), (1040, 64, 4), (1040, 74, 2), (1042, 72, 2), (1044, 60, 4),
    (1044, 64, 4), (1044, 71, 2), (1046, 72, 2), (1048, 57, 4), (1048, 76, 4), (1052, 60, 4),
    (1052, 64, 4), (1056, 60, 4), (1056, 64, 4), (1056, 77, 2), (1058, 76, 2), (1060, 60, 4),
    (1060, 64, 4), (1060, 75, 2), (1062, 76, 2), (1064, 57, 4), (1064, 83, 2), (1066, 81, 2),
    (1068, 60, 4), (1068, 64, 4), (1068, 80, 2), (1070, 81, 2), (1072, 57, 4), (1072, 83, 2),
    (1074, 81, 2), (1076, 60, 4), (1076, 64, 4), (1076, 80, 2), (1078, 81, 2), (1080, 57, 4),
    (1080, 84, 8), (1084, 60, 4), (1084, 64, 4), (1088, 60, 4), (1088, 64, 4), (1088, 81, 4),
    (1092, 60, 4), (1092, 64, 4), (1092, 84, 4), (1096, 52, 4), (1096, 83, 4), (1100, 59, 4),
    (1100, 64, 4), (1100, 78, 4), (1100, 81, 4), (1104, 59, 4), (1104, 64, 4), (1104, 76, 4),
    (1104, 79, 4), (1108, 59, 4), (1108, 64, 4), (1108, 78, 4), (1108, 81, 4), (1112, 52, 4),
    (1112, 83, 4), (1116, 59, 4), (1116, 64, 4), (1116, 78, 4), (1116, 81, 4), (1120, 59, 4),
    (1120, 64, 4), (1120, 76, 4), (1120, 79, 4), (1124, 59, 4), (1124, 64, 4), (1124, 78, 4),
    (1124, 81, 4), (1128, 52, 4), (1128, 83, 4), (1132, 59, 4), (1132, 64, 4), (1132, 78, 4),
    (1132, 81, 4), (1136, 47, 4), (1136, 76, 4), (1136, 79, 4), (1140, 59, 4), (1140, 75, 4),
    (1140, 78, 4), (1144, 52, 8), (1144, 76, 8), (1152, 72, 4), (1152, 76, 4), (1156, 74, 4),
    (1156, 77, 4), (1160, 48, 4), (1160, 76, 4), (1160, 79, 4), (1164, 60, 4), (1164, 76, 4),
    (1164, 79, 4), (1168, 52, 4), (1168, 81, 2), (1170, 79, 2), (1172, 64, 4), (1172, 77, 2),
    (1174, 76, 2), (1176, 55, 8), (1176, 71, 4), (1176, 74, 8), (1180, 67, 4), (1184, 72, 4),
    (1184, 76, 4), (1188, 74, 4), (1188, 77, 4), (1192, 48, 4), (1192, 76, 4), (1192, 79, 4),
    (1196, 60, 4), (1196, 76, 4), (1196, 79, 4), (1200, 52, 4), (1200, 81, 2), (1202, 79, 2),
    (1204, 64, 4), (1204, 77, 2), (1206, 76, 2), (1208, 55, 8), (1208, 71, 8), (1208, 74, 8),
    (1216, 69, 4), (1216, 72, 4), (1220, 71, 4), (1220, 74, 4), (1224, 45, 4), (1224, 72, 4),
    (1224, 76, 4), (1228, 57, 4), (1228, 72, 4), (1228, 76, 4), (1232, 48, 4), (1232, 77, 2),
    (1234, 76, 2), (1236, 60, 4), (1236, 74, 2), (1238, 72, 2), (1240, 52, 8), (1240, 68, 4),
    (1240, 71, 8), (1244, 64, 4), (1248, 69, 4), (1248, 72, 4), (1252, 71, 4), (1252, 74, 4),
    (1256, 45, 4), (1256, 72, 4), (1256, 76, 4), (1260, 57, 4), (1260, 72, 4), (1260, 76, 4),
    (1264, 48, 4), (1264, 77, 2), (1266, 76, 2), (1268, 60, 4), (1268, 74, 2), (1270, 72, 2),
    (1272, 52, 8), (1272, 68, 8), (1272, 71, 8), (1280, 71, 2), (1282, 69, 2), (1284, 68, 2),
    (1286, 69, 2), (1288, 57, 4), (1288, 72, 4), (1292, 60, 4), (1292, 64, 4), (1296, 60, 4),
    (1296, 64, 4), (1296, 74, 2), (1298, 72, 2), (1300, 60, 4), (1300, 64, 4), (1300, 71, 2),
    (1302, 72, 2), (1304, 57, 4), (1304, 76, 4), (1308, 60, 4), (1308, 64, 4), (1312, 60, 4),
    (1312, 64, 4), (1312, 77, 2), (1314, 76, 2), (1316, 60, 4), (1316, 64, 4), (1316, 75, 2),
    (1318, 76, 2), (1320, 57, 4), (1320, 83, 2), (1322, 81, 2), (1324, 60, 4), (1324, 64, 4),
    (1324, 80, 2), (1326, 81, 2), (1328, 57, 4), (1328, 83, 2), (1330, 81, 2), (1332, 60, 4),
    (1332, 64, 4), (1332, 80, 2), (1334, 81, 2), (1336, 53, 4), (1336, 84, 4), (1340, 57, 4),
    (1340, 63, 4), (1344, 57, 4), (1344, 63, 4), (1344, 81, 4), (1348, 57, 4), (1348, 63, 4),
    (1348, 83, 4), (1352, 52, 4), (1352, 84, 4), (1356, 57, 4), (1356, 64, 4), (1356, 83, 4),
    (1360, 50, 4), (1360, 81, 4), (1364, 53, 4), (1364, 59, 4), (1364, 80, 4), (1368, 48, 4),
    (1368, 81, 4), (1372, 52, 4), (1372, 57, 4), (1372, 76, 4), (1376, 50, 4), (1376, 77, 4),
    (1380, 53, 4), (1380, 59, 4), (1380, 74, 4), (1384, 52, 4), (1384, 57, 4), (1384, 72, 8),
    (1388, 52, 4), (1388, 57, 4), (1392, 52, 4), (1392, 56, 4), (1392, 71, 6), (1396, 52, 4),
    (1396, 56, 4), (1398, 69, 1), (1399, 71, 1), (1400, 45, 7), (1400, 57, 7), (1400, 69, 8),
    (1408, 69, 2), (1410, 81, 2), (1412, 71, 2), (1414, 83, 2), (1416, 57, 4), (1416, 73, 2),
    (1418, 85, 2), (1420, 57, 4), (1424, 57, 4), (1424, 69, 2), (1426, 81, 2), (1428, 57, 3),
    (1428, 71, 2), (1430, 83, 2), (1432, 57, 4), (1432, 73, 2), (1434, 85, 2), (1436, 57, 4),
    (1436, 71, 2), (1438, 83, 2), (1440, 57, 4), (1440, 69, 2), (1442, 81, 2), (1444, 57, 3),
    (1444, 68, 2), (1446, 80, 2), (1448, 50, 4), (1448, 66, 2), (1450, 78, 2), (1452, 50, 3),
    (1452, 68, 2), (1454, 80, 2), (1456, 51, 4), (1456, 69, 2), (1458, 81, 2), (1460, 51, 3),
    (1460, 71, 2), (1462, 83, 2), (1464, 52, 4), (1464, 68, 2), (1466, 80, 2), (1468, 52, 4),
    (1468, 64, 2), (1470, 76, 2), (1472, 52, 4), (1472, 69, 2), (1474, 81, 2), (1476, 52, 3),
    (1476, 71, 2), (1478, 83, 2), (1480, 57, 4), (1480, 73, 2), (1482, 85, 2), (1484, 57, 4),
    (1488, 57, 4), (1488, 69, 2), (1490, 81, 2), (1492, 57, 3), (1492, 71, 2), (1494, 83, 2),
    (1496, 57, 4), (1496, 73, 2), (1498, 85, 2), (1500, 57, 4), (1500, 71, 2), (1502, 83, 2),
    (1504, 57, 4), (1504, 69, 2), (1506, 81, 2), (1508, 57, 3), (1508, 68, 2), (1510, 80, 2),
    (1512, 50, 4), (1512, 66, 2), (1514, 78, 2), (1516, 50, 3), (1516, 71, 2), (1518, 83, 2),
    (1520, 52, 4), (1520, 68, 2), (1522, 80, 2), (1524, 52, 4), (1524, 64, 2), (1526, 76, 2),
    (1528, 45, 7), (1528, 69, 7), (1528, 81, 7), (1536, 57, 4), (1536, 69, 8), (1536, 81, 8),
    (1540, 57, 4), (1544, 57, 4), (1544, 73, 8), (1544, 85, 6), (1548, 57, 3), (1550, 85, 2),
    (1552, 57, 4), (1552, 73, 8), (1552, 76, 8), (1552, 81, 8), (1552, 85, 16), (1556, 57, 4),
    (1560, 57, 4), (1564, 57, 3), (1568, 57, 4), (1568, 73, 8), (1568, 76, 8), (1568, 81, 8),
    (1568, 85, 16), (1572, 57, 4), (1576, 57, 4), (1580, 57, 3), (1584, 57, 4), (1584, 86, 2),
    (1586, 85, 2), (1588, 57, 4), (1588, 83, 2), (1590, 85, 2), (1592, 57, 4), (1592, 86, 2),
    (1594, 85, 2), (1596, 57, 3), (1596, 83, 2), (1598, 85, 2), (1600, 50, 4), (1600, 78, 15),
    (1600, 81, 15), (1600, 86, 15), (1604, 50, 4), (1608, 50, 4), (1612, 50, 3), (1615, 86, 1),
    (1616, 57, 4), (1616, 76, 3), (1616, 81, 3), (1616, 85, 3), (1619, 86, 1), (1620, 57, 4),
    (1620, 76, 3), (1620, 81, 3), (1620, 85, 3), (1623, 86, 1), (1624, 57, 4), (1624, 76, 3),
    (1624, 81, 3), (1624, 85, 3), (1627, 86, 1), (1628, 57, 3), (1628, 76, 4), (1628, 81, 4),
    (1628, 85, 4), (1632, 52, 4), (1632, 76, 16), (1632, 80, 16), (1632, 83, 12), (1636, 52, 4),
    (1640, 52, 4), (1644, 52, 3), (1644, 88, 4), (1648, 57, 4), (1648, 73, 8), (1648, 76, 8),
    (1648, 81, 8), (1648, 85, 16), (1652, 57, 4), (1656, 57, 4), (1660, 57, 3), (1664, 57, 4),
    (1664, 73, 8), (1664, 76, 8), (1664, 81, 8), (1664, 85, 16), (1668, 57, 4), (1672, 57, 4),
    (1676, 57, 3), (1680, 57, 4), (1680, 86, 2), (1682, 85, 2), (1684, 57, 4), (1684, 83, 2),
    (1686, 85, 2), (1688, 57, 4), (1688, 86, 2), (1690, 85, 2), (1692, 57, 3), (1692, 83, 2),
    (1694, 85, 2), (1696, 50, 4), (1696, 78, 15), (1696, 81, 15), (1696, 86, 15), (1700, 50, 4),
    (1704, 50, 4), (1708, 50, 3), (1711, 86, 1), (1712, 57, 4), (1712, 76, 15), (1712, 81, 15),
    (1712, 85, 15), (1716, 57, 4), (1720, 57, 4), (1724, 57, 3), (1727, 85, 1), (1728, 52, 4),
    (1728, 76, 3), (1728, 80, 3), (1728, 83, 3), (1731, 85, 1), (1732, 52, 4), (1732, 76, 3),
    (1732, 80, 3), (1732, 83, 3), (1735, 85, 1), (1736, 52, 4), (1736, 76, 3), (1736, 80, 3),
    (1736, 83, 3), (1739, 85, 1), (1740, 52, 4), (1740, 76, 4), (1740, 80, 4), (1740, 83, 4),
    (1744, 57, 2), (1744, 81, 8), (1746, 64, 2), (1748, 61, 2), (1750, 64, 2), (1752, 57, 2),
    (1752, 85, 6), (1754, 64, 2), (1756, 61, 2), (1758, 64, 2), (1758, 85, 2), (1760, 57, 2),
    (1760, 85, 16), (1762, 64, 2), (1764, 61, 2), (1766, 64, 2), (1768, 57, 2), (1770, 64, 2),
    (1772, 61, 2), (1774, 64, 2), (1776, 57, 2), (1776, 85, 16), (1778, 64, 2), (1780, 61, 2),
    (1782, 64, 2), (1784, 57, 2), (1786, 64, 2), (1788, 61, 2), (1790, 64, 2), (1792, 57, 2),
    (1792, 86, 2), (1794, 64, 2), (1794, 85, 2), (1796, 61, 2), (1796, 83, 2), (1798, 64, 2),
    (1798, 85, 2), (1800, 57, 2), (1800, 86, 2), (1802, 64, 2), (1802, 85, 2), (1804, 61, 2),
    (1804, 83, 2), (1806, 64, 2), (1806, 85, 2), (1808, 57, 2), (1808, 86, 15), (1810, 66, 2),
    (1812, 62, 2), (1814, 66, 2), (1816, 57, 2), (1818, 66, 2), (1820, 62, 2), (1822, 66, 2),
    (1823, 86, 1), (1824, 57, 2), (1824, 85, 3), (1826, 64, 2), (1827, 86, 1), (1828, 61, 2),
    (1828, 85, 3), (1830, 64, 2), (1831, 86, 1), (1832, 57, 2), (1832, 85, 3), (1834, 64, 2),
    (1835, 86, 1), (1836, 61, 2), (1836, 85, 4), (1838, 64, 2), (1840, 52, 2), (1840, 83, 12),
    (1842, 64, 2), (1844, 56, 2), (1846, 64, 2), (1848, 52, 2), (1850, 64, 2), (1852, 56, 2),
    (1852, 88, 4), (1854, 64, 1), (1856, 57, 4), (1856, 73, 8), (1856, 76, 8), (1856, 81, 8),
    (1856, 85, 16), (1860, 57, 4), (1864, 57, 4), (1868, 57, 3), (1872, 57, 4), (1872, 73, 8),
    (1872, 76, 8), (1872, 81, 8), (1872, 85, 16), (1876, 57, 4), (1880, 57, 4), (1884, 57, 3),
    (1888, 57, 4), (1888, 86, 2), (1890, 85, 2), (1892, 57, 4), (1892, 83, 2), (1894, 85, 2),
    (1896, 57, 4), (1896, 86, 2), (1898, 85, 2), (1900, 57, 3), (1900, 83, 2), (1902, 85, 2),
    (1904, 50, 4), (1904, 78, 15), (1904, 81, 15), (1904, 86, 15), (1908, 50, 4), (1912, 50, 4),
    (1916, 50, 3), (1919, 86, 1), (1920, 57, 4), (1920, 76, 15), (1920, 81, 15), (1920, 85, 15),
    (1924, 57, 4), (1928, 57, 4), (1932, 57, 3), (1935, 85, 1), (1936, 52, 4), (1936, 76, 3),
    (1936, 80, 3), (1936, 83, 3), (1939, 85, 1), (1940, 52, 4), (1940, 76, 3), (1940, 80, 3),
    (1940, 83, 3), (1943, 85, 1), (1944, 52, 4), (1944, 76, 3), (1944, 80, 3), (1944, 83, 3),
    (1947, 85, 1), (1948, 52, 3), (1948, 76, 4), (1948, 80, 4), (1948, 83, 4), (1952, 57, 4),
    (1952, 69, 12), (1952, 73, 12), (1952, 76, 12), (1952, 81, 12), (1956, 57, 4), (1960, 57, 4),
    (1964, 57, 3), (1964, 73, 4), (1964, 85, 4), (1968, 57, 4), (1968, 69, 12), (1968, 81, 12),
    (1972, 57, 4), (1976, 57, 4), (1980, 57, 3), (1980, 76, 4), (1980, 88, 4), (1984, 57, 4),
    (1984, 69, 12), (1984, 81, 12), (1988, 57, 4), (1992, 57, 4), (1996, 57, 3), (1996, 73, 4),
    (1996, 85, 4), (2000, 57, 4), (2000, 69, 4), (2000, 81, 4), (2004, 57, 3), (2004, 73, 4),
    (2004, 85, 4), (2008, 57, 4), (2008, 69, 4), (2008, 81, 4), (2012, 57, 4), (2012, 76, 4),
    (2012, 88, 4), (2016, 45, 8), (2016, 69, 8), (2016, 81, 8), (2024, 45, 8), (2024, 49, 8),
    (2024, 52, 8), (2024, 57, 8), (2024, 69, 8), (2024, 73, 8), (2024, 76, 8), (2024, 81, 8),
    (2032, 45, 8), (2032, 49, 8), (2032, 52, 8), (2032, 57, 8), (2032, 69, 8), (2032, 73, 8),
    (2032, 76, 8), (2032, 81, 8),
]

# Right-hand melody used for the falling notes.
_TURKISH_CHART = [
    (0, 71, 2), (2, 69, 2), (4, 68, 2), (6, 69, 2), (8, 72, 4), (16, 74, 2),
    (18, 72, 2), (20, 71, 2), (22, 72, 2), (24, 76, 4), (32, 77, 2), (34, 76, 2),
    (36, 75, 2), (38, 76, 2), (40, 83, 2), (42, 81, 2), (44, 80, 2), (46, 81, 2),
    (48, 83, 2), (50, 81, 2), (52, 80, 2), (54, 81, 2), (56, 84, 8), (64, 81, 4),
    (68, 84, 4), (72, 83, 4), (76, 81, 4), (80, 79, 4), (84, 81, 4), (88, 83, 4),
    (92, 81, 4), (96, 79, 4), (100, 81, 4), (104, 83, 4), (108, 81, 4), (112, 79, 4),
    (116, 78, 4), (120, 76, 8), (128, 76, 4), (132, 77, 4), (136, 79, 4), (140, 79, 4),
    (144, 81, 2), (146, 79, 2), (148, 77, 2), (150, 76, 2), (152, 74, 8), (156, 67, 4),
    (160, 76, 4), (164, 77, 4), (168, 79, 4), (172, 79, 4), (176, 81, 2), (178, 79, 2),
    (180, 77, 2), (182, 76, 2), (184, 74, 8), (192, 72, 4), (196, 74, 4), (200, 76, 4),
    (204, 76, 4), (208, 77, 2), (210, 76, 2), (212, 74, 2), (214, 72, 2), (216, 71, 8),
    (220, 64, 4), (224, 72, 4), (228, 74, 4), (232, 76, 4), (236, 76, 4), (240, 77, 2),
    (242, 76, 2), (244, 74, 2), (246, 72, 2), (248, 71, 8), (256, 71, 2), (258, 69, 2),
    (260, 68, 2), (262, 69, 2), (264, 72, 4), (272, 74, 2), (274, 72, 2), (276, 71, 2),
    (278, 72, 2), (280, 76, 4), (288, 77, 2), (290, 76, 2), (292, 75, 2), (294, 76, 2),
    (296, 83, 2), (298, 81, 2), (300, 80, 2), (302, 81, 2), (304, 83, 2), (306, 81, 2),
    (308, 80, 2), (310, 81, 2), (312, 84, 4), (320, 81, 4), (324, 83, 4), (328, 84, 4),
    (332, 83, 4), (336, 81, 4), (340, 80, 4), (344, 81, 4), (348, 76, 4), (352, 77, 4),
    (356, 74, 4), (360, 72, 8), (368, 71, 6), (376, 69, 8), (384, 81, 4), (388, 83, 4),
    (392, 85, 8), (400, 81, 4), (404, 83, 4), (408, 85, 4), (412, 83, 4), (416, 81, 4),
    (420, 80, 4), (424, 78, 4), (428, 80, 4), (432, 81, 4), (436, 83, 4), (440, 80, 4),
    (444, 76, 4), (448, 81, 4), (452, 83, 4), (456, 85, 8), (464, 81, 4), (468, 83, 4),
    (472, 85, 4), (476, 83, 4), (480, 81, 4), (484, 80, 4), (488, 78, 4), (492, 83, 4),
    (496, 80, 4), (500, 76, 4), (504, 81, 8), (512, 85, 2), (514, 86, 2), (516, 85, 2),
    (518, 83, 2), (520, 81, 2), (522, 83, 2), (524, 81, 2), (526, 80, 2), (528, 78, 2),
    (530, 81, 2), (532, 80, 2), (534, 78, 2), (536, 77, 2), (538, 78, 2), (540, 80, 2),
    (542, 77, 2), (544, 73, 2), (546, 75, 2), (548, 77, 2), (550, 73, 2), (552, 78, 2),
    (554, 77, 2), (556, 78, 2), (558, 80, 2), (560, 81, 2), (562, 80, 2), (564, 81, 2),
    (566, 83, 2), (568, 85, 2), (570, 84, 2), (572, 85, 2), (574, 84, 2), (576, 85, 2),
    (578, 86, 2), (580, 85, 2), (582, 83, 2), (584, 81, 2), (586, 83, 2), (588, 81, 2),
    (590, 80, 2), (592, 78, 2), (594, 81, 2), (596, 80, 2), (598, 78, 2), (600, 76, 2),
    (602, 78, 2), (604, 80, 2), (606, 76, 2), (608, 73, 2), (610, 75, 2), (612, 76, 2),
    (614, 73, 2), (616, 75, 2), (618, 76, 2), (620, 78, 2), (622, 75, 2), (624, 72, 2),
    (626, 73, 2), (628, 75, 2), (630, 72, 2), (632, 73, 8), (640, 76, 2), (642, 74, 2),
    (644, 73, 2), (646, 71, 2), (648, 69, 2), (650, 71, 2), (652, 73, 2), (654, 74, 2),
    (656, 76, 2), (658, 78, 2), (660, 80, 2), (662, 81, 2), (664, 81, 2), (666, 80, 2),
    (668, 78, 2), (670, 76, 2), (672, 76, 2), (674, 74, 2), (676, 73, 2), (678, 71, 2),
    (680, 69, 2), (682, 71, 2), (684, 73, 2), (686, 74, 2), (688, 76, 2), (690, 78, 2),
    (692, 80, 2), (694, 81, 2), (696, 82, 4), (700, 83, 4), (704, 76, 2), (706, 74, 2),
    (708, 73, 2), (710, 71, 2), (712, 69, 2), (714, 71, 2), (716, 73, 2), (718, 74, 2),
    (720, 76, 2), (722, 78, 2), (724, 80, 2), (726, 81, 2), (728, 81, 2), (730, 80, 2),
    (732, 78, 2), (734, 76, 2), (736, 76, 2), (738, 74, 2), (740, 73, 2), (742, 71, 2),
    (744, 73, 2), (746, 76, 2), (748, 69, 2), (750, 73, 2), (752, 71, 2), (754, 74, 2),
    (756, 68, 2), (758, 71, 2), (760, 69, 8), (768, 85, 2), (770, 86, 2), (772, 85, 2),
    (774, 83, 2), (776, 81, 2), (778, 83, 2), (780, 81, 2), (782, 80, 2), (784, 78, 2),
    (786, 81, 2), (788, 80, 2), (790, 78, 2), (792, 77, 2), (794, 78, 2), (796, 80, 2),
    (798, 77, 2), (800, 73, 2), (802, 75, 2), (804, 77, 2), (806, 73, 2), (808, 78, 2),
    (810, 77, 2), (812, 78, 2), (814, 80, 2), (816, 81, 2), (818, 80, 2), (820, 81, 2),
    (822, 83, 2), (824, 85, 2), (826, 84, 2), (828, 85, 2), (830, 84, 2), (832, 85, 2),
    (834, 84, 2), (836, 85, 2), (838, 82, 2), (840, 86, 2), (842, 85, 2), (844, 86, 2),
    (846, 85, 2), (848, 86, 2), (850, 85, 2), (852, 86, 2), (854, 85, 2), (856, 86, 2),
    (858, 85, 2), (860, 83, 2), (862, 81, 2), (864, 80, 2), (866, 81, 2), (868, 83, 2),
    (870, 80, 2), (872, 81, 2), (874, 83, 2), (876, 85, 2), (878, 78, 2), (880, 77, 2),
    (882, 78, 2), (884, 80, 2), (886, 77, 2), (888, 78, 8), (896, 81, 4), (900, 83, 4),
    (904, 85, 8), (912, 81, 4), (916, 83, 4), (920, 85, 4), (924, 83, 4), (928, 81, 4),
    (932, 80, 4), (936, 78, 4), (940, 80, 4), (944, 81, 4), (948, 83, 4), (952, 80, 4),
    (956, 76, 4), (960, 81, 4), (964, 83, 4), (968, 85, 8), (976, 81, 4), (980, 83, 4),
    (984, 85, 4), (988, 83, 4), (992, 81, 4), (996, 80, 4), (1000, 78, 4), (1004, 83, 4),
    (1008, 80, 4), (1012, 76, 4), (1016, 81, 8), (1024, 71, 2), (1026, 69, 2), (1028, 68, 2),
    (1030, 69, 2), (1032, 72, 4), (1040, 74, 2), (1042, 72, 2), (1044, 71, 2), (1046, 72, 2),
    (1048, 76, 4), (1056, 77, 2), (1058, 76, 2), (1060, 75, 2), (1062, 76, 2), (1064, 83, 2),
    (1066, 81, 2), (1068, 80, 2), (1070, 81, 2), (1072, 83, 2), (1074, 81, 2), (1076, 80, 2),
    (1078, 81, 2), (1080, 84, 8), (1088, 81, 4), (1092, 84, 4), (1096, 83, 4), (1100, 81, 4),
    (1104, 79, 4), (1108, 81, 4), (1112, 83, 4), (1116, 81, 4), (1120, 79, 4), (1124, 81, 4),
    (1128, 83, 4), (1132, 81, 4), (1136, 79, 4), (1140, 78, 4), (1144, 76, 8), (1152, 76, 4),
    (1156, 77, 4), (1160, 79, 4), (1164, 79, 4), (1168, 81, 2), (1170, 79, 2), (1172, 77, 2),
    (1174, 76, 2), (1176, 74, 8), (1180, 67, 4), (1184, 76, 4), (1188, 77, 4), (1192, 79, 4),
    (1196, 79, 4), (1200, 81, 2), (1202, 79, 2), (1204, 77, 2), (1206, 76, 2), (1208, 74, 8),
    (1216, 72, 4), (1220, 74, 4), (1224, 76, 4), (1228, 76, 4), (1232, 77, 2), (1234, 76, 2),
    (1236, 74, 2), (1238, 72, 2), (1240, 71, 8), (1244, 64, 4), (1248, 72, 4), (1252, 74, 4),
    (1256, 76, 4), (1260, 76, 4), (1264, 77, 2), (1266, 76, 2), (1268, 74, 2), (1270, 72, 2),
    (1272, 71, 8), (1280, 71, 2), (1282, 69, 2), (1284, 68, 2), (1286, 69, 2), (1288, 72, 4),
    (1296, 74, 2), (1298, 72, 2), (1300, 71, 2), (1302, 72, 2), (1304, 76, 4), (1312, 77, 2),
    (1314, 76, 2), (1316, 75, 2), (1318, 76, 2), (1320, 83, 2), (1322, 81, 2), (1324, 80, 2),
    (1326, 81, 2), (1328, 83, 2), (1330, 81, 2), (1332, 80, 2), (1334, 81, 2), (1336, 84, 4),
    (1344, 81, 4), (1348, 83, 4), (1352, 84, 4), (1356, 83, 4), (1360, 81, 4), (1364, 80, 4),
    (1368, 81, 4), (1372, 76, 4), (1376, 77, 4), (1380, 74, 4), (1384, 72, 8), (1392, 71, 6),
    (1400, 69, 8), (1408, 69, 2), (1410, 81, 2), (1412, 71, 2), (1414, 83, 2), (1416, 73, 2),
    (1418, 85, 2), (1424, 69, 2), (1426, 81, 2), (1428, 71, 2), (1430, 83, 2), (1432, 73, 2),
    (1434, 85, 2), (1436, 71, 2), (1438, 83, 2), (1440, 69, 2), (1442, 81, 2), (1444, 68, 2),
    (1446, 80, 2), (1448, 66, 2), (1450, 78, 2), (1452, 68, 2), (1454, 80, 2), (1456, 69, 2),
    (1458, 81, 2), (1460, 71, 2), (1462, 83, 2), (1464, 68, 2), (1466, 80, 2), (1468, 64, 2),
    (1470, 76, 2), (1472, 69, 2), (1474, 81, 2), (1476, 71, 2), (1478, 83, 2), (1480, 73, 2),
    (1482, 85, 2), (1488, 69, 2), (1490, 81, 2), (1492, 71, 2), (1494, 83, 2), (1496, 73, 2),
    (1498, 85, 2), (1500, 71, 2), (1502, 83, 2), (1504, 69, 2), (1506, 81, 2), (1508, 68, 2),
    (1510, 80, 2), (1512, 66, 2), (1514, 78, 2), (1516, 71, 2), (1518, 83, 2), (1520, 68, 2),
    (1522, 80, 2), (1524, 64, 2), (1526, 76, 2), (1528, 81, 7), (1536, 81, 8), (1544, 85, 6),
    (1550, 85, 2), (1552, 85, 16), (1568, 85, 16), (1584, 86, 2), (1586, 85, 2), (1588, 83, 2),
    (1590, 85, 2), (1592, 86, 2), (1594, 85, 2), (1596, 83, 2), (1598, 85, 2), (1600, 86, 15),
    (1616, 85, 3), (1620, 85, 3), (1624, 85, 3), (1628, 85, 4), (1632, 83, 12), (1644, 88, 4),
    (1648, 85, 16), (1664, 85, 16), (1680, 86, 2), (1682, 85, 2), (1684, 83, 2), (1686, 85, 2),
    (1688, 86, 2), (1690, 85, 2), (1692, 83, 2), (1694, 85, 2), (1696, 86, 15), (1712, 85, 15),
    (1728, 83, 3), (1732, 83, 3), (1736, 83, 3), (1740, 83, 4), (1744, 81, 8), (1752, 85, 6),
    (1760, 85, 16), (1776, 85, 16), (1792, 86, 2), (1794, 85, 2), (1796, 83, 2), (1798, 85, 2),
    (1800, 86, 2), (1802, 85, 2), (1804, 83, 2), (1806, 85, 2), (1808, 86, 15), (1824, 85, 3),
    (1828, 85, 3), (1832, 85, 3), (1836, 85, 4), (1840, 83, 12), (1852, 88, 4), (1856, 85, 16),
    (1872, 85, 16), (1888, 86, 2), (1890, 85, 2), (1892, 83, 2), (1894, 85, 2), (1896, 86, 2),
    (1898, 85, 2), (1900, 83, 2), (1902, 85, 2), (1904, 86, 15), (1920, 85, 15), (1936, 83, 3),
    (1940, 83, 3), (1944, 83, 3), (1948, 83, 4), (1952, 81, 12), (1964, 85, 4), (1968, 81, 12),
    (1980, 88, 4), (1984, 81, 12), (1996, 85, 4), (2000, 81, 4), (2004, 85, 4), (2008, 81, 4),
    (2012, 88, 4), (2016, 81, 8), (2024, 81, 8), (2032, 81, 8),
]

_turkish_score = timed(_TURKISH_SCORE, _TURKISH_BPM)
_turkish_chart = timed(_TURKISH_CHART, _TURKISH_BPM)
register(Song("turkish_march", "土耳其进行曲", "Turkish March", _TURKISH_BPM,
              _turkish_score, chart_notes=_turkish_chart, timbre="pling"))

# 摇篮曲 / Brahms' Lullaby (Wiegenlied Op.49 No.4, public domain).
# Melody verified note-by-note against the tuneonmusic beginner MIDI (C-major
# transposition of the Eb original); rhythm taken from that MIDI.
register(Song("brahms_lullaby", "摇篮曲", "Brahms' Lullaby", 90, seq([
    (64, 0.5), (64, 0.5), (67, 2), (64, 0.5), (64, 0.5), (67, 2),
    (64, 0.5), (67, 0.5), (72, 1), (71, 1.5), (69, 0.5), (69, 1), (67, 1),
    (62, 0.5), (64, 0.5), (65, 1), (62, 1),
    (62, 0.5), (64, 0.5), (65, 2), (62, 0.5), (65, 0.5), (71, 0.5), (69, 0.5), (67, 1),
    (71, 1), (72, 2),
    (60, 0.5), (60, 0.5), (72, 2), (69, 0.5), (65, 0.5), (67, 2),
    (64, 0.5), (60, 0.5), (65, 1), (67, 1), (69, 1), (67, 2),
    (60, 0.5), (60, 0.5), (72, 2), (69, 0.5), (65, 0.5), (67, 2),
    (64, 0.5), (60, 0.5), (65, 1), (64, 1), (62, 1), (60, 2),
], bpm=90)))

# 伦敦桥 / London Bridge Is Falling Down (traditional, public domain).
# Melody verified note-by-note against the tuneonmusic beginner MIDI and two
# independent letter-note transcriptions; rhythm taken from that MIDI.
register(Song("london_bridge", "伦敦桥", "London Bridge", 100, seq([
    (67, 1.5), (69, 0.5), (67, 1), (65, 1), (64, 1), (65, 1), (67, 2),
    (62, 1), (64, 1), (65, 2), (64, 1), (65, 1), (67, 2),
    (67, 1.5), (69, 0.5), (67, 1), (65, 1), (64, 1), (65, 1), (67, 2),
    (62, 2), (67, 2), (64, 1), (60, 3),
], bpm=100)))

# Build beatmaps only after every song is registered.
BEATMAPS: Dict[str, Beatmap] = {}
for _sid in ORDER:
    if _sid == "turkish_march":
        BEATMAPS[_sid] = _turkish_beatmap(SONGS[_sid])
    else:
        BEATMAPS[_sid] = beatmap_from_song(SONGS[_sid])
BEATMAPS["canon"] = _canon_beatmap(SONGS["canon"])


def get_beatmap(sid: str) -> Beatmap:
    if sid not in BEATMAPS:
        BEATMAPS[sid] = beatmap_from_song(get_song(sid))
    return BEATMAPS[sid]