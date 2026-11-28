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
import io
import json
import math
import os
import re
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
# Whole-process bound on one ffmpeg run. A stalled ffmpeg (alive, silent)
# must not hold the single decode slot forever — killing it makes the stdout
# read hit EOF and the failure path report normally. Desktops decode a
# 4-minute song in well under a second; a Pi needs a few.
DECODE_TIMEOUT = 300.0


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
    """A finite float from `v`, or `default`.

    json accepts NaN/Infinity literals and float() overflows on huge ints;
    int() over such a value would then crash the caller (start_decode,
    PackPlayer.sync — the whole app dies from one manifest field), so
    non-finite counts as garbage.
    """
    try:
        f = float(v)
    except (TypeError, ValueError, OverflowError):
        return default
    return f if math.isfinite(f) else default


def _sanitize_id(v, fallback: str) -> str:
    s = "".join(c if c.isalnum() and c.isascii() else "_"
                for c in str(v or "").lower())[:64]
    s = s.strip("_")
    return s or fallback


# C0/C1 control bytes: ESC, newline, tab, BEL… A pack-provided string lands
# verbatim in the terminal grid, so a control byte would be written to the
# terminal raw — CSI/OSC injection, cursor misalignment. Strip, don't escape:
# titles are prose, not data.
_TEXT_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def _sanitize_text(s: str) -> str:
    return _TEXT_CONTROL.sub("", s)


class Pack:
    """One parsed .tmbp file. Chart times are seconds from the audio start."""

    # Source-file signature (stat) recorded by read_pack; Library.refresh
    # compares it to detect a same-id pack that was replaced on disk. The
    # inode/volume join catches same-size rewrites that mtime granularity
    # (2 s on FAT32) would miss.
    source_sig = (0, 0, 0, 0)

    def __init__(self, path: str, manifest: dict, notes: List[Tuple[float, int]]):
        self.path = path
        stem = os.path.splitext(os.path.basename(path))[0]
        self.id = _sanitize_id(manifest.get("id"), _sanitize_id(stem, "external"))
        self.title_zh = _sanitize_text(str(manifest.get("title_zh") or self.id)) or self.id
        self.title_en = _sanitize_text(str(manifest.get("title_en") or self.title_zh)) or self.title_zh
        self.artist = _sanitize_text(str(manifest.get("artist") or ""))
        self.audio_name = str(manifest.get("audio") or "")
        self.duration = max(0.0, _num(manifest.get("duration"), 0.0))
        self.offset = max(0.0, _num(manifest.get("offset"), 0.0))
        self.lead_in = min(10.0, max(0.5, _num(manifest.get("lead_in"),
                                               DEFAULT_LEAD_IN)))
        self.difficulty = _sanitize_text(str(manifest.get("difficulty") or "Normal")) or "Normal"
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
        try:
            return _read_members(zf, path)
        except PackError:
            raise
        except Exception as e:
            # A corrupt member (bad CRC -> BadZipFile, an encrypted entry ->
            # RuntimeError, broken deflate -> zlib.error) is still just a
            # broken pack: only PackError is filtered upstream (Library
            # warnings, menu error notices), anything else escaping here
            # crashes the whole app the moment the rhythm menu opens.
            # str(MemoryError()) is "": keep the message non-empty.
            raise PackError("corrupt member: %s"
                            % (str(e) or type(e).__name__)) from e


def _read_members(zf: zipfile.ZipFile, path: str) -> Pack:
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
    pack = Pack(path, manifest, notes)
    try:
        st = os.stat(path)
        pack.source_sig = (st.st_mtime_ns, st.st_size, st.st_ino, st.st_dev)
    except OSError:
        pass
    return pack


def _decode_wav(src, sr: int) -> Optional[array.array]:
    """Mono s16 WAV at the exact engine rate decodes without any subprocess.

    `src` is a binary file object (a zip member or BytesIO); frames are read
    in chunks so the PCM array is the only full-size buffer — the member
    itself streams through instead of sitting in memory beside the result.
    """
    try:
        with wave.open(src) as w:
            if (w.getnchannels() != 1 or w.getsampwidth() != 2
                    or w.getframerate() != sr):
                return None
            pcm = array.array("h")
            while True:
                frames = w.readframes(READ_CHUNK // 2)
                if not frames:
                    break
                pcm.frombytes(frames)
    except Exception:
        return None
    if sys.byteorder == "big":
        pcm.byteswap()
    return pcm


def _reap_later(proc: subprocess.Popen, seconds: float) -> None:
    """Kill `proc` unless it exits within `seconds` (watchdog thread body)."""
    try:
        proc.wait(timeout=seconds)
    except subprocess.TimeoutExpired:
        proc.kill()


def _decode_ffmpeg_file(path: str, sr: int, progress=None) -> array.array:
    """Run ffmpeg over `path` and collect mono s16 PCM at `sr`.

    stderr is drained concurrently: a pipe nobody reads fills up (64 KiB on
    Linux, 4 KiB measured on Windows) and a chatty ffmpeg — corrupt audio
    prints one error per frame — blocks on writing it, never finishing
    stdout. Parent and child then wait on each other forever: the decode
    thread hangs for good, the loading overlay stays at 0% and the pack can
    never be retried. Only the exit status decides failure; the drained
    stderr is kept for the error message.
    """
    argv = ["ffmpeg", "-v", "error", "-i", path, "-vn", "-f", "s16le",
            "-ac", "1", "-ar", str(sr), "pipe:1"]
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    try:
        err: List[bytes] = []

        def _drain() -> None:
            try:
                while True:
                    chunk = proc.stderr.read(READ_CHUNK)
                    if not chunk:
                        return
                    err.append(chunk)
            except Exception:
                pass

        t = threading.Thread(target=_drain, name="tmb-ffmpeg-stderr",
                             daemon=True)
        t.start()
        # A watchdog bounds the whole run. The stderr drain fixed the pipe
        # deadlock, but an ffmpeg that stalls mid-input (alive, silent) would
        # still block stdout.read() forever — and with the one-decode gate
        # that wedged every pack until restart. Killing it makes the read hit
        # EOF and the failure path report normally.
        watchdog = threading.Thread(
            target=_reap_later, args=(proc, DECODE_TIMEOUT),
            name="tmb-ffmpeg-watchdog", daemon=True)
        watchdog.start()
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
            proc.wait(timeout=10)
            t.join(timeout=10)
            _stderr = b"".join(err).decode("utf-8", "replace")
            if proc.returncode != 0:
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
        if proc.poll() is None:
            proc.kill()


def decode_audio(data, sr: int, name: str, progress=None) -> array.array:
    """Decode pack audio to mono int16 at `sr`.

    `data` is the audio member's bytes, or an open binary file object for it
    (zip members stream through one, so a 4-minute song never needs the whole
    blob — and its decompressed copy — resident at once). WAV members
    matching the engine rate use the stdlib path; everything else streams
    through ffmpeg (stdin-free: a temp file, because MP4 containers are not
    seekable when piped). `progress(decoded_frames)` is called as the PCM
    grows.
    """
    if name.lower().endswith(".wav"):
        fast = _decode_wav(data if hasattr(data, "read")
                           else io.BytesIO(data), sr)
        if fast is not None:
            if progress:
                progress(len(fast))
            return fast
    if hasattr(data, "read") and hasattr(data, "seek"):
        # The failed fast path consumed part of the stream (header probed,
        # rate mismatch): rewind so ffmpeg sees the member from its start.
        try:
            data.seek(0)
        except OSError:
            pass
    if not shutil.which("ffmpeg"):
        raise PackError("ffmpeg not found; install it to play this pack "
                        "(sudo apt install ffmpeg)")
    fd, tmp = tempfile.mkstemp(suffix=os.path.splitext(name)[1] or ".bin")
    try:
        if hasattr(data, "read"):
            with os.fdopen(fd, "wb") as out:
                shutil.copyfileobj(data, out, READ_CHUNK)
        else:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
        return _decode_ffmpeg_file(tmp, sr, progress)
    finally:
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
        # refresh() cache: path -> (stat signature, Pack). Re-parsing every
        # .tmbp (zip + two JSON members + a full note list) ran synchronously
        # in the UI thread on every entry into the rhythm menu.
        self._pack_cache: Dict[str, tuple] = {}
        # id -> stat signature of the pack each cached PCM/error came from;
        # a replaced or deleted file must invalidate its old audio.
        self._pack_meta: Dict[str, tuple] = {}

    def refresh(self) -> None:
        packs: List[Pack] = []
        warnings: List[str] = []
        seen: Dict[str, Pack] = {}
        visited: set = set()
        cache = self._pack_cache
        if os.path.isdir(self.dir):
            for name in sorted(os.listdir(self.dir)):
                if not name.lower().endswith(PACK_EXT):
                    continue
                path = os.path.join(self.dir, name)
                visited.add(path)
                try:
                    st = os.stat(path)
                    # mtime+size alone miss a same-size rewrite within the
                    # filesystem's timestamp granularity (2 s on FAT32);
                    # the inode/volume join closes that window.
                    sig = (st.st_mtime_ns, st.st_size, st.st_ino, st.st_dev)
                except OSError:
                    sig = None
                pack = None
                if sig is not None:
                    hit = cache.get(path)
                    if hit is not None and hit[0] == sig:
                        pack = hit[1]
                if pack is None:
                    try:
                        pack = read_pack(path)
                    except PackError as e:
                        warnings.append("%s: %s" % (name, e))
                        cache.pop(path, None)
                        continue
                    cache[path] = (sig, pack)
                if pack.id in seen:
                    warnings.append("%s: duplicate id %r (skipped)"
                                    % (name, pack.id))
                    continue
                seen[pack.id] = pack
                packs.append(pack)
        # A deleted or renamed file is never visited again; its parsed Pack
        # would sit in the cache forever.
        self._pack_cache = {p: v for p, v in cache.items() if p in visited}
        packs.sort(key=lambda p: p.title_zh)
        self.packs = packs
        self.warnings = warnings
        # Cache PCM/errors are keyed by pack id, but a pack is its *file*:
        # replacing a same-id .tmbp (or deleting it) must drop the old audio,
        # or the menu keeps seeing "ready" and the game plays stale PCM
        # against the new chart for the whole session.
        live = {p.id: p.source_sig for p in packs}
        stale = [sid for sid, meta in self._pack_meta.items()
                 if live.get(sid) != meta]
        if stale:
            with self._lock:
                for sid in stale:
                    self._pcm.pop(sid, None)
                    self._errors.pop(sid, None)
        self._pack_meta = live

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
            if self._decoding is not None:
                # One decode at a time: a running decode cannot be cancelled
                # (it would read its whole member and run ffmpeg to the end
                # only to throw the result away), so rapid pack switches used
                # to stack N concurrent ffmpeg jobs + N members + N PCM sets
                # in RAM with only the last one kept — real OOM pressure on a
                # 1 GB Pi. The menu's healing path retries when it finishes.
                return False
            self._gen += 1
            gen = self._gen
            self._decoding = sid
            self._errors.pop(sid, None)
            self._done = 0
            self._total = int(pack.duration * self.sr) if pack.duration else 0
        threading.Thread(target=self._decode_work, args=(pack, gen),
                         name="tmb-pack-decode", daemon=True).start()
        return True

    def _decode_work(self, pack: Pack, gen: int) -> None:
        try:
            with zipfile.ZipFile(pack.path) as zf:
                def progress(frames: int) -> None:
                    with self._lock:
                        if gen != self._gen:
                            return
                        self._done = frames
                        # A duration shorter than the real audio must not
                        # push the loading popup past 100%: grow the total
                        # with the frames actually decoded instead.
                        if frames > self._total:
                            self._total = frames

                name = pack.audio_name
                try:
                    src = zf.open(name)
                except KeyError as e:
                    raise PackError("audio member %r missing" % name) from e
                # The member streams through as a file object: the PCM array
                # is the only full-size copy (about 21 MB per 4-minute song),
                # not member + readframes copy + array peaking at 3-4x that.
                with src:
                    pcm = decode_audio(src, self.sr, name, progress)
            if not pcm:
                raise PackError("audio decoded to silence")
            with self._lock:
                if gen != self._gen:
                    return
                # The pack file may have been replaced (or deleted) while the
                # decode ran: refresh() has already re-recorded the new
                # signature for this id. Storing PCM decoded from the old
                # bytes would poison the cache — the menu would see "ready"
                # and play old audio against the new chart until restart.
                try:
                    st = os.stat(pack.path)
                    fresh = (st.st_mtime_ns, st.st_size, st.st_ino,
                             st.st_dev) == pack.source_sig
                except OSError:
                    fresh = False
                if not fresh:
                    return
                self._pcm[pack.id] = pcm
                # One decoded song in RAM is enough for a 1 GB Pi — but only
                # release the others once the new one is playable: trimming on
                # request left nothing playable when the new pack failed.
                self._pcm = {k: v for k, v in self._pcm.items() if k == pack.id}
        except Exception as e:  # surfaced in the song list, never fatal
            with self._lock:
                if gen != self._gen:
                    return
                # str(MemoryError()) == "": an empty message reads as "no
                # error" (error() uses "" for none) and the menu retried the
                # decode every frame forever. Fall back to the type name.
                self._errors[pack.id] = str(e) or type(e).__name__
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
