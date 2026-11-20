"""Audio output backends. All standard-library only.

- AlsaBackend / PulseBackend: stream raw S16LE to aplay / paplay (Raspberry Pi).
- WinmmBackend: waveOut streaming via ctypes (Windows).
- WavBackend: render to a .wav file (tests / offline verification).
- NullBackend: discard samples but keep real-time pacing (headless tests).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
import wave
from collections import deque
from typing import Optional


class Backend:
    blocking = True
    name = "base"

    def open(self, sr: int, ch: int) -> None:
        raise NotImplementedError

    def write(self, pcm: bytes) -> None:
        raise NotImplementedError

    def close(self) -> None:
        pass


class NullBackend(Backend):
    blocking = False
    name = "null"

    def open(self, sr, ch):
        self.sr, self.ch = sr, ch

    def write(self, pcm):
        pass


class WavBackend(Backend):
    blocking = False
    name = "wav"

    def __init__(self, path: str):
        self.path = path
        self._data = bytearray()
        self.sr = 44100
        self.ch = 1

    def open(self, sr, ch):
        self.sr, self.ch = sr, ch
        self._data = bytearray()

    def write(self, pcm):
        self._data += pcm

    def close(self):
        with wave.open(self.path, "wb") as w:
            w.setnchannels(self.ch)
            w.setsampwidth(2)
            w.setframerate(self.sr)
            w.writeframes(bytes(self._data))


class _ProcBackend(Backend):
    blocking = True

    def __init__(self, argv):
        self.argv = argv
        self.proc: Optional[subprocess.Popen] = None

    def open(self, sr, ch):
        self.proc = subprocess.Popen(self.argv, stdin=subprocess.PIPE,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def write(self, pcm):
        if self.proc and self.proc.stdin:
            try:
                self.proc.stdin.write(pcm)
            except (BrokenPipeError, OSError):
                pass

    def close(self):
        if self.proc:
            try:
                if self.proc.stdin:
                    self.proc.stdin.close()
                self.proc.wait(timeout=2)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass
            self.proc = None


class AlsaBackend(_ProcBackend):
    name = "alsa"

    def __init__(self, sr=44100, ch=1):
        super().__init__(["aplay", "-q", "-t", "raw", "-f", "S16_LE",
                          "-r", str(sr), "-c", str(ch), "-"])


class PulseBackend(_ProcBackend):
    name = "pulse"

    def __init__(self, sr=44100, ch=1):
        super().__init__(["paplay", "--raw", "--format=s16le",
                          "--rate=%d" % sr, "--channels=%d" % ch])


class WinmmBackend(Backend):
    blocking = True
    name = "winmm"

    def __init__(self, nbuf=10, chunk=512):
        import ctypes as ct
        from ctypes import wintypes as wt
        self._ct = ct
        self._wt = wt
        self.winmm = ct.windll.winmm
        self.k32 = ct.windll.kernel32
        self.nbuf = nbuf
        self.chunk = chunk
        self._hwo = None
        self._event = None
        self._headers = []
        self._buffers = []
        self._free = deque()
        self._pending = bytearray()
        self._sr = 44100
        self._ch = 1

    def open(self, sr, ch):
        ct = self._ct
        self._sr, self._ch = sr, ch

        class WAVEFORMATEX(ct.Structure):
            _fields_ = [("wFormatTag", ct.c_ushort), ("nChannels", ct.c_ushort),
                        ("nSamplesPerSec", ct.c_uint), ("nAvgBytesPerSec", ct.c_uint),
                        ("nBlockAlign", ct.c_ushort), ("wBitsPerSample", ct.c_ushort),
                        ("cbSize", ct.c_ushort)]

        class WAVEHDR(ct.Structure):
            _fields_ = [("lpData", ct.c_void_p), ("dwBufferLength", ct.c_uint),
                        ("dwBytesRecorded", ct.c_uint), ("dwUser", ct.c_void_p),
                        ("dwFlags", ct.c_uint), ("dwLoops", ct.c_uint),
                        ("lpNext", ct.c_void_p), ("reserved", ct.c_void_p)]

        self._WAVEHDR = WAVEHDR
        fmt = WAVEFORMATEX(1, ch, sr, sr * ch * 2, ch * 2, 16, 0)
        self._event = self.k32.CreateEventW(None, False, False, None)
        hwo = ct.c_void_p()
        CALLBACK_EVENT = 0x20
        rc = self.winmm.waveOutOpen(ct.byref(hwo), ct.c_uint(-1), ct.byref(fmt),
                                    ct.c_void_p(self._event), ct.c_void_p(0), ct.c_uint(CALLBACK_EVENT))
        if rc != 0:
            raise OSError("waveOutOpen failed: %d" % rc)
        self._hwo = hwo
        self._chunk_bytes = self.chunk * ch * 2
        for _ in range(self.nbuf):
            buf = ct.create_string_buffer(self._chunk_bytes)
            hdr = WAVEHDR()
            hdr.lpData = ct.cast(buf, ct.c_void_p)
            hdr.dwBufferLength = self._chunk_bytes
            self._buffers.append(buf)
            self._headers.append(hdr)
            self._free.append(len(self._headers) - 1)

    def _reclaim(self):
        ct = self._ct
        WHDR_DONE = 0x1
        for i, hdr in enumerate(self._headers):
            if (hdr.dwFlags & WHDR_DONE) and i not in self._free:
                self.winmm.waveOutUnprepareHeader(self._hwo, ct.byref(hdr), ct.sizeof(hdr))
                hdr.dwFlags = 0
                self._free.append(i)

    def write(self, pcm):
        ct = self._ct
        if not self._hwo:
            return
        self._pending += pcm
        while len(self._pending) >= self._chunk_bytes:
            while True:
                self._reclaim()
                if self._free:
                    break
                self.k32.WaitForSingleObject(self._event, 200)
            idx = self._free.popleft()
            hdr = self._headers[idx]
            buf = self._buffers[idx]
            ct.memmove(buf, bytes(self._pending[:self._chunk_bytes]), self._chunk_bytes)
            del self._pending[:self._chunk_bytes]
            hdr.dwBufferLength = self._chunk_bytes
            hdr.dwFlags = 0
            rc = self.winmm.waveOutPrepareHeader(self._hwo, ct.byref(hdr), ct.sizeof(hdr))
            if rc == 0:
                rc = self.winmm.waveOutWrite(self._hwo, ct.byref(hdr), ct.sizeof(hdr))
            if rc != 0:
                self.winmm.waveOutUnprepareHeader(self._hwo, ct.byref(hdr), ct.sizeof(hdr))
                hdr.dwFlags = 0
                self._free.append(idx)

    def close(self):
        ct = self._ct
        if self._hwo:
            self.winmm.waveOutReset(self._hwo)
            for hdr in self._headers:
                try:
                    self.winmm.waveOutUnprepareHeader(self._hwo, ct.byref(hdr), ct.sizeof(hdr))
                except Exception:
                    pass
            self.winmm.waveOutClose(self._hwo)
            self._hwo = None
        if self._event:
            self.k32.CloseHandle(self._event)
            self._event = None


def _warn_silent(msg: str) -> None:
    sys.stderr.write("tmb: %s\n" % msg)


def open_backend(prefer: Optional[str] = None, sr: int = 44100, ch: int = 1,
                 wav_path: Optional[str] = None) -> Backend:
    """Pick the best available backend for this platform."""
    if prefer == "null":
        return NullBackend()
    if prefer == "wav" or wav_path:
        return WavBackend(wav_path or "output.wav")
    if prefer == "winmm" and os.name == "nt":
        return WinmmBackend()
    if prefer == "alsa" and shutil.which("aplay"):
        return AlsaBackend(sr, ch)
    if prefer == "pulse" and shutil.which("paplay"):
        return PulseBackend(sr, ch)
    if os.name == "nt":
        try:
            return WinmmBackend()
        except Exception:
            _warn_silent("winmm unavailable; running silent.")
            return NullBackend()
    # WSL2 has no ALSA device; WSLg exposes PulseAudio at /mnt/wslg/PulseServer.
    if os.path.isdir("/mnt/wslg"):
        if not os.environ.get("PULSE_SERVER") and os.path.exists("/mnt/wslg/PulseServer"):
            os.environ["PULSE_SERVER"] = "unix:/mnt/wslg/PulseServer"
        if shutil.which("paplay"):
            return PulseBackend(sr, ch)
        _warn_silent("WSLg detected but paplay is missing; "
                     "install pulseaudio-utils for sound (sudo apt install pulseaudio-utils).")
        return NullBackend()
    if shutil.which("aplay"):
        return AlsaBackend(sr, ch)
    if shutil.which("paplay"):
        return PulseBackend(sr, ch)
    if shutil.which("afplay"):
        # macOS afplay cannot stream; fall back to null (audio disabled)
        _warn_silent("macOS afplay cannot stream; running silent.")
        return NullBackend()
    _warn_silent("no audio backend found; running silent. "
                 "Install alsa-utils (aplay) or pulseaudio-utils (paplay).")
    return NullBackend()