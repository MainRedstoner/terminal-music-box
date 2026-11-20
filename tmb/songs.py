"""Song / beatmap data model, a pausable song player, and the built-in library.

A Song is a list of timed notes used by prenatal mode (auto playback). A
Beatmap is a list of timed lane notes (tap / hold) used by the rhythm game.
`beatmap_from_song` derives a playable chart from a melody. The library below
is extended with more public-domain melodies.
"""
from __future__ import annotations

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
    hold: float = 0.0  # >0 == hold note (seconds)


@dataclass
class Beatmap:
    song_id: str
    notes: List[RNote] = field(default_factory=list)
    difficulty: str = "Normal"

    @property
    def duration(self) -> float:
        if not self.notes:
            return 0.0
        return max(n.time + n.hold for n in self.notes)


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


def beatmap_from_song(song: Song, lead_in: float = 2.0, hold_threshold: float = 0.8) -> Beatmap:
    if not song.notes:
        return Beatmap(song.id, [])
    pitches = [n.midi for n in song.notes]
    lo, hi = min(pitches), max(pitches)
    span = max(1, hi - lo)
    notes: List[RNote] = []
    for n in song.notes:
        lane = int((n.midi - lo) * 6 / (span + 1))
        lane = max(0, min(5, lane))
        hold = n.dur if n.dur >= hold_threshold else 0.0
        notes.append(RNote(n.time + lead_in, lane, hold))
    notes.sort(key=lambda r: r.time)
    return Beatmap(song.id, notes)


class SongPlayer:
    """Drives auto-playback; call update(dt) each frame. Pause freezes time."""

    def __init__(self, engine, song: Song, timbre: str):
        self.engine = engine
        self.song = song
        self.timbre = timbre
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
            self.engine.play_note(self.timbre, n.midi, n.dur, n.vel)
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

# 欢乐颂 / Ode to Joy (Beethoven, public domain)
register(Song("ode_joy", "欢乐颂", "Ode to Joy", 100, seq([
    (64, 1), (64, 1), (65, 1), (67, 1), (67, 1), (65, 1), (64, 1), (62, 1),
    (60, 1), (60, 1), (62, 1), (64, 1), (64, 1.5), (62, 0.5), (62, 2),
    (64, 1), (64, 1), (65, 1), (67, 1), (67, 1), (65, 1), (64, 1), (62, 1),
    (60, 1), (60, 1), (62, 1), (64, 1), (62, 1.5), (60, 0.5), (60, 2),
], bpm=100)))

# 铃儿响叮当 / Jingle Bells (chorus, James Pierpont, public domain)
register(Song("jingle_bells", "铃儿响叮当", "Jingle Bells", 120, seq([
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

# 卡农（片段） / Canon in C (fragment, Pachelbel, public domain)
register(Song("canon", "卡农（片段）", "Canon in C (fragment)", 80, seq([
    (76, 2), (74, 2), (72, 2), (71, 2), (69, 2), (67, 2), (69, 2), (71, 2),
    (72, 2), (71, 2), (69, 2), (67, 2), (65, 2), (64, 2), (65, 2), (67, 2),
], bpm=80)))

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


def get_beatmap(sid: str) -> Beatmap:
    if sid not in BEATMAPS:
        BEATMAPS[sid] = beatmap_from_song(get_song(sid))
    return BEATMAPS[sid]