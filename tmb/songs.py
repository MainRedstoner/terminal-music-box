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
from typing import Dict, List, Optional


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
RHYTHM_ORDER: List[str] = ["canon"]


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
    BEATMAPS[_sid] = beatmap_from_song(SONGS[_sid])
BEATMAPS["canon"] = _canon_beatmap(SONGS["canon"])


def get_beatmap(sid: str) -> Beatmap:
    if sid not in BEATMAPS:
        BEATMAPS[sid] = beatmap_from_song(get_song(sid))
    return BEATMAPS[sid]