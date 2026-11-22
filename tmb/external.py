"""External song packs: a chart + its audio in one .tmbp file.

A pack is a zip archive holding manifest.json, chart.json and one audio
member. Pack audio is usually copyrighted material, so the directory the
packs live in (external_songs/ next to the package) is gitignored and the
repo never bundles any.

Playback decodes the audio member to a mono int16 PCM array once — about
21 MB per 4-minute song at the engine's 44.1 kHz, which fits a 1 GB
Raspberry Pi — and streams it through the mixer as a single long voice.
Decoding uses ffmpeg when available; a plain 44.1 kHz mono s16 WAV member
also decodes with the standard library alone, so tiny packs need no
external tools at all.
"""
from __future__ import annotations

import array
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import wave
import zipfile
from typing import Dict, List, Optional, Tuple

from . import songs
from .audio.engine import AudioEngine

PACK_EXT = ".tmbp"
FORMAT_VERSION = 1
DEFAULT_LEAD_IN = 2.0
READ_CHUNK = 1 << 16


class PackError(Exception):
    """A pack is unreadable, malformed, or its audio cannot be decoded."""


def external_dir() -> str:
    """Where .tmbp packs are loaded from (gitignored; overridable for tests)."""
    d = os.environ.get("TMB_EXTERNAL_DIR")
    if d:
        return d
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "external_songs")


def _num(v, default: float) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _sanitize_id(v, fallback: str) -> str:
    s = "".join(c if c.isalnum() and c.isascii() else "_"
                for c in str(v or "").lower())[:64]
    s = s.strip("_")
    return s or fallback


class Pack:
    """One parsed .tmbp file. Chart times are seconds from the audio start."""

    def __init__(self, path: str, manifest: dict, notes: List[Tuple[float, int]]):
        self.path = path
        stem = os.path.splitext(os.path.basename(path))[0]
        self.id = _sanitize_id(manifest.get("id"), _sanitize_id(stem, "external"))
        self.title_zh = str(manifest.get("title_zh") or self.id)
        self.title_en = str(manifest.get("title_en") or self.title_zh)
        self.artist = str(manifest.get("artist") or "")
        self.audio_name = str(manifest.get("audio") or "")
        self.duration = max(0.0, _num(manifest.get("duration"), 0.0))
        self.offset = max(0.0, _num(manifest.get("offset"), 0.0))
        self.lead_in = min(10.0, max(0.5, _num(manifest.get("lead_in"),
                                               DEFAULT_LEAD_IN)))
        self.difficulty = str(manifest.get("difficulty") or "Normal")
        self.volume = min(2.0, max(0.1, _num(manifest.get("volume"), 1.0)))
        self.notes = notes
        self._song: Optional[songs.Song] = None

    def title(self, lang: str) -> str:
        return self.title_zh if lang == "zh" else self.title_en

    def song(self) -> songs.Song:
        """A title-only Song: pack audio replaces the synth melody entirely."""
        if self._song is None:
            self._song = songs.Song(self.id, self.title_zh, self.title_en,
                                    bpm=0.0, notes=[])
        return self._song

    def beatmap(self, lead_in: Optional[float] = None) -> songs.Beatmap:
        li = self.lead_in if lead_in is None else lead_in
        notes = [songs.RNote(t + li, lane) for t, lane in self.notes]
        notes.sort(key=lambda r: (r.time, r.lane))
        return songs.Beatmap(self.id, notes, difficulty=self.difficulty,
                             lead_in=li)


def _parse_chart(raw: bytes) -> List[Tuple[float, int]]:
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as e:
        raise PackError("chart.json: %s" % e)
    items = data.get("notes") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise PackError("chart.json: missing notes list")
    notes: List[Tuple[float, int]] = []
    for item in items:
        try:
            t, lane = item
        except (TypeError, ValueError):
            raise PackError("chart.json: note must be [time, lane]")
        t = _num(t, -1.0)
        if t < 0.0:
            raise PackError("chart.json: negative note time %r" % (item,))
        if not isinstance(lane, int) or not 0 <= lane <= 5:
            raise PackError("chart.json: lane must be 0..5 (%r)" % (item,))
        notes.append((t, lane))
    notes.sort()
    # Identical (time, lane) pairs are worthless taps; chords (same time,
    # different lanes) are legitimate and survive.
    out: List[Tuple[float, int]] = []
    for pair in notes:
        if not out or out[-1] != pair:
            out.append(pair)
    return out


def read_pack(path: str) -> Pack:
    """Parse one .tmbp; raises PackError with a user-readable reason."""
    try:
        zf = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as e:
        raise PackError("cannot open: %s" % e)
    with zf:
        names = zf.namelist()
        try:
            manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        except KeyError:
            raise PackError("manifest.json missing")
        except (UnicodeDecodeError, ValueError) as e:
            raise PackError("manifest.json: %s" % e)
        if not isinstance(manifest, dict):
            raise PackError("manifest.json: expected an object")
        version = _num(manifest.get("format"), 0)
        if version != FORMAT_VERSION:
            raise PackError("unsupported pack format %r" % version)
        try:
            chart_raw = zf.read("chart.json")
        except KeyError:
            raise PackError("chart.json missing")
        notes = _parse_chart(chart_raw)
        audio = str(manifest.get("audio") or "")
        if not audio or audio not in names:
            raise PackError("audio member %r missing" % audio)
        return Pack(path, manifest, notes)


def _decode_wav(data: bytes, sr: int) -> Optional[array.array]:
    """Mono s16 WAV at the exact engine rate decodes without any subprocess."""
    try:
        import io
        with wave.open(io.BytesIO(data)) as w:
            if (w.getnchannels() != 1 or w.getsampwidth() != 2
                    or w.getframerate() != sr):
                return None
            pcm = array.array("h")
            pcm.frombytes(w.readframes(w.getnframes()))
    except Exception:
        return None
    if sys.byteorder == "big":
        pcm.byteswap()
    return pcm


def decode_audio(data: bytes, sr: int, name: str,
                 progress=None) -> array.array:
    """Decode pack audio bytes to mono int16 at `sr`.

    WAV members matching the engine rate use the stdlib path; everything
    else streams through ffmpeg (stdin-free: a temp file, because MP4
    containers are not seekable when piped). `progress(decoded_frames)` is
    called as the PCM grows.
    """
    fast = None
    if name.lower().endswith(".wav"):
        fast = _decode_wav(data, sr)
        if fast is not None:
            if progress:
                progress(len(fast))
            return fast
    if not shutil.which("ffmpeg"):
        raise PackError("ffmpeg not found; install it to play this pack "
                        "(sudo apt install ffmpeg)")
    fd, tmp = tempfile.mkstemp(suffix=os.path.splitext(name)[1] or ".bin")
    proc = None
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        argv = ["ffmpeg", "-v", "error", "-i", tmp, "-vn", "-f", "s16le",
                "-ac", "1", "-ar", str(sr), "pipe:1"]
        proc = subprocess.Popen(argv, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
        try:
            pcm = array.array("h")
            pending = b""
            assert proc.stdout is not None
            while True:
                chunk = proc.stdout.read(READ_CHUNK)
                if not chunk:
                    break
                pending += chunk
                use = len(pending) & ~1  # whole frames only
                if use:
                    piece = array.array("h")
                    piece.frombytes(pending[:use])
                    if sys.byteorder == "big":
                        piece.byteswap()
                    pcm.extend(piece)
                    pending = pending[use:]
                    if progress:
                        progress(len(pcm))
            _stderr = proc.stderr.read().decode("utf-8", "replace") if proc.stderr else ""
            if proc.wait(timeout=10) != 0:
                raise PackError("ffmpeg failed: %s" % _stderr.strip()[-200:])
            return pcm
        finally:
            # The pipes must be closed even when reads raise (leaked fds).
            for stream in (proc.stdout, proc.stderr):
                if stream is not None:
                    try:
                        stream.close()
                    except OSError:
                        pass
    finally:
        if proc is not None and proc.poll() is None:
            proc.kill()
        try:
            os.unlink(tmp)
        except OSError:
            pass


class PackPlayer:
    """Plays one decoded pack through the engine as a single long voice.

    The rhythm screen drives it with the same calls it makes on
    songs.SongPlayer: sync(song_time, lead_in) each play frame, pause(),
    resume(), stop(). The audio launches when the song clock reaches the
    chart lead-in, exactly when the first falling note leaves the top. The
    mixer's real consumption is the position of record; when it stays
    drifted from the song clock (slow device, blocked output pipe) the
    voice restarts at the expected frame — falling-note judgment follows
    the clock — but only after the drift persists across several frames,
    so one hiccup never becomes an audible seam.
    """

    DRIFT_RESYNC = 0.08   # seconds of game-vs-audio gap worth a restart
    RESYNC_FRAMES = 3     # consecutive drifted frames before restarting

    def __init__(self, engine: AudioEngine, pcm: Optional[array.array],
                 offset: float = 0.0, volume: float = 1.0):
        self.engine = engine
        self.pcm = pcm
        self.sr = engine.sr
        self.offset = max(0.0, offset)
        self.gain = min(2.0, max(0.0, volume))
        self._vid: Optional[int] = None
        self._base = 0        # frames played before the current voice
        self._live = 0        # frames consumed by the current voice
        self.playing = False
        self.started = False
        self.finished = False
        self._drifted = 0

    @property
    def position(self) -> float:
        return (self._base + self._live) / self.sr

    def _start_voice(self, frames: int) -> None:
        frames = max(0, min(frames, len(self.pcm)))
        if frames >= len(self.pcm):
            self.finished = True
            return
        self._base = frames
        self._live = 0
        self._vid = self.engine.play_pcm(self.pcm, gain=self.gain,
                                         start=frames)
        self.playing = True

    def _expected_frames(self, song_time: float, lead_in: float) -> int:
        return int(max(0.0, song_time - lead_in + self.offset) * self.sr)

    def start(self) -> None:
        """Start at the manifest offset; the rhythm game uses sync() instead."""
        if not self.started:
            self.started = True
            if self.pcm:
                self._start_voice(int(self.offset * self.sr))

    def sync(self, song_time: float, lead_in: float = 0.0) -> None:
        if not self.started:
            if song_time < lead_in - 1e-6:
                return
            self.started = True
        if not self.pcm:
            self.finished = True
            return
        expected = self._expected_frames(song_time, lead_in)
        if expected >= len(self.pcm):
            # The song clock ran past the audio (or the chart outlives it).
            if self._vid is not None:
                self.engine.stop_voice(self._vid, fade_ms=60.0)
                self._vid = None
            self.playing = False
            self.finished = True
            return
        if not self.playing or self._vid is None:
            self._start_voice(expected)
            return
        c = self.engine.voice_consumed(self._vid)
        if c < 0:
            # The mixer consumed the whole buffer: the music ended cleanly.
            self._live = 0
            self.playing = False
            self.finished = True
            return
        self._live = c
        # Audio lagging the clock (device stall, starved mixer) skips
        # forward to `expected` after a few drifted frames — falling-note
        # judgment follows the clock. Audio *ahead* of the clock never
        # rewinds: a backward restart would replay the music, and a
        # systematically slow sim clock is not a real playback state.
        lag = self._base + self._live - expected
        if lag < -self.sr * self.DRIFT_RESYNC:
            # Resynchronize only on sustained drift: a single late frame
            # (GC pause, slow render) must not punch an audible seam into
            # the music. A restart crossfades: the old voice ramps out
            # while the new one takes over.
            self._drifted += 1
            if self._drifted >= self.RESYNC_FRAMES:
                self._drifted = 0
                self.engine.stop_voice(self._vid, fade_ms=40.0)
                self._vid = None
                self.playing = False
                self._start_voice(expected)
        else:
            self._drifted = 0

    def pause(self) -> None:
        if self._vid is not None and self.playing:
            c = self.engine.voice_consumed(self._vid)
            self.engine.stop_voice(self._vid, fade_ms=60.0)
            self._base += max(0, c)
            self._live = 0
            self._vid = None
        self.playing = False

    def resume(self) -> None:
        if self.started and not self.finished and not self.playing and self.pcm:
            self._start_voice(self._base)

    def stop(self) -> None:
        if self._vid is not None:
            self.engine.stop_voice(self._vid, fade_ms=120.0)
            self._vid = None
        self.playing = False


class Library:
    """Scans the pack directory and decodes audio in a background thread.

    At most one song stays decoded (about 20 MB of PCM) — starting another
    pack releases the previous one, which matters on a 1 GB Raspberry Pi.
    """

    def __init__(self, engine_sr: int = 44100, directory: Optional[str] = None):
        self.dir = directory or external_dir()
        self.sr = engine_sr
        self.packs: List[Pack] = []
        self.warnings: List[str] = []
        self._lock = threading.Lock()
        self._pcm: Dict[str, array.array] = {}
        self._errors: Dict[str, str] = {}
        self._decoding: Optional[str] = None
        self._gen = 0
        self._done = 0
        self._total = 0

    def refresh(self) -> None:
        packs: List[Pack] = []
        warnings: List[str] = []
        seen: Dict[str, Pack] = {}
        if os.path.isdir(self.dir):
            for name in sorted(os.listdir(self.dir)):
                if not name.lower().endswith(PACK_EXT):
                    continue
                path = os.path.join(self.dir, name)
                try:
                    pack = read_pack(path)
                except PackError as e:
                    warnings.append("%s: %s" % (name, e))
                    continue
                if pack.id in seen:
                    warnings.append("%s: duplicate id %r (skipped)"
                                    % (name, pack.id))
                    continue
                seen[pack.id] = pack
                packs.append(pack)
        packs.sort(key=lambda p: p.title_zh)
        self.packs = packs
        self.warnings = warnings

    def get(self, sid: str) -> Optional[Pack]:
        for p in self.packs:
            if p.id == sid:
                return p
        return None

    def get_pcm(self, sid: str) -> Optional[array.array]:
        with self._lock:
            return self._pcm.get(sid)

    def player_for(self, pack: Pack, engine: AudioEngine) -> PackPlayer:
        """A PackPlayer over the decoded audio (menu gated the decode)."""
        return PackPlayer(engine, self.get_pcm(pack.id),
                          offset=pack.offset, volume=pack.volume)

    def is_ready(self, sid: str) -> bool:
        with self._lock:
            return sid in self._pcm

    def error(self, sid: str) -> str:
        with self._lock:
            return self._errors.get(sid, "")

    def can_decode(self, pack: Pack) -> bool:
        if shutil.which("ffmpeg"):
            return True
        # Without ffmpeg only the stdlib WAV fast path can play.
        return pack.audio_name.lower().endswith(".wav")

    def status(self) -> Tuple[bool, int, int]:
        with self._lock:
            return (self._decoding is not None, self._done, self._total)

    def start_decode(self, sid: str) -> bool:
        pack = self.get(sid)
        if pack is None or self.is_ready(sid):
            return False
        with self._lock:
            if self._decoding == sid:
                return True
            self._gen += 1
            gen = self._gen
            self._decoding = sid
            self._errors.pop(sid, None)
            self._done = 0
            self._total = int(pack.duration * self.sr) if pack.duration else 0
            # One decoded song in RAM is enough for a 1 GB Pi.
            self._pcm = {k: v for k, v in self._pcm.items() if k == sid}
        threading.Thread(target=self._decode_work, args=(pack, gen),
                         name="tmb-pack-decode", daemon=True).start()
        return True

    def _decode_work(self, pack: Pack, gen: int) -> None:
        try:
            with zipfile.ZipFile(pack.path) as zf:
                data = zf.read(pack.audio_name)
            total_hint = int(pack.duration * self.sr) if pack.duration else 0

            def progress(frames: int) -> None:
                with self._lock:
                    if gen != self._gen:
                        return
                    self._done = frames
                    if not self._total:
                        self._total = max(total_hint, frames)

            pcm = decode_audio(data, self.sr, pack.audio_name, progress)
            if not pcm:
                raise PackError("audio decoded to silence")
            with self._lock:
                if gen != self._gen:
                    return
                self._pcm[pack.id] = pcm
        except Exception as e:  # surfaced in the song list, never fatal
            with self._lock:
                if gen != self._gen:
                    return
                self._errors[pack.id] = str(e)
        finally:
            with self._lock:
                if gen == self._gen:
                    self._decoding = None
                    self._done = 0
                    self._total = 0

    def release(self, sid: str) -> None:
        with self._lock:
            self._pcm.pop(sid, None)

    def release_all(self) -> None:
        with self._lock:
            self._pcm.clear()
