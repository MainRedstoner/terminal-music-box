"""Windows console backend via ctypes (kernel32).

Reads real console INPUT_RECORDs, so we get key-down AND key-up (used for
sustain), unambiguous ESC, and native mouse events. Output uses VT processing
so the same ANSI renderer works. No third-party dependencies.
"""
from __future__ import annotations

import ctypes as ct
from ctypes import wintypes as wt
from typing import List

from .events import (KeyEvent, MouseEvent, ResizeEvent, Event,
                     UP, DOWN, LEFT, RIGHT, HOME, END, PGUP, PGDN, DELETE,
                     ENTER, ESC, TAB, BACKSPACE, SPACE)

k32 = ct.windll.kernel32

STD_INPUT_HANDLE = -10
STD_OUTPUT_HANDLE = -11
ENABLE_WINDOW_INPUT = 0x0008
ENABLE_MOUSE_INPUT = 0x0010
ENABLE_EXTENDED_FLAGS = 0x0080
ENABLE_PROCESSED_OUTPUT = 0x0001
ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
KEY_EVENT = 0x0001
MOUSE_EVENT = 0x0002
WINDOW_BUFFER_SIZE_EVENT = 0x0004
WAIT_OBJECT_0 = 0
MOUSE_MOVED = 0x0001
MOUSE_WHEELED = 0x0004
CTRL_MASK = 0x0004 | 0x0008  # right | left ctrl pressed


class COORD(ct.Structure):
    _fields_ = [("X", ct.c_short), ("Y", ct.c_short)]


class SMALL_RECT(ct.Structure):
    _fields_ = [("Left", ct.c_short), ("Top", ct.c_short),
                ("Right", ct.c_short), ("Bottom", ct.c_short)]


class KEY_EVENT_RECORD(ct.Structure):
    _fields_ = [("bKeyDown", ct.c_int), ("wRepeatCount", ct.c_ushort),
                ("wVirtualKeyCode", ct.c_ushort), ("wVirtualScanCode", ct.c_ushort),
                ("UnicodeChar", ct.c_wchar), ("dwControlKeyState", ct.c_uint)]


class MOUSE_EVENT_RECORD(ct.Structure):
    _fields_ = [("dwMousePosition", COORD), ("dwButtonState", ct.c_uint),
                ("dwControlKeyState", ct.c_uint), ("dwEventFlags", ct.c_uint)]


class WINDOW_BUFFER_SIZE_RECORD(ct.Structure):
    _fields_ = [("dwSize", COORD)]


class _EventUnion(ct.Union):
    _fields_ = [("KeyEvent", KEY_EVENT_RECORD), ("MouseEvent", MOUSE_EVENT_RECORD),
                ("WindowBufferSizeEvent", WINDOW_BUFFER_SIZE_RECORD)]


class INPUT_RECORD(ct.Structure):
    _fields_ = [("EventType", ct.c_ushort), ("Event", _EventUnion)]


class CONSOLE_SCREEN_BUFFER_INFO(ct.Structure):
    _fields_ = [("dwSize", COORD), ("dwCursorPosition", COORD),
                ("wAttributes", ct.c_ushort), ("srWindow", SMALL_RECT),
                ("dwMaximumWindowSize", COORD)]


_VK_SPECIAL = {
    0x26: UP, 0x28: DOWN, 0x25: LEFT, 0x27: RIGHT,
    0x24: HOME, 0x23: END, 0x21: PGUP, 0x22: PGDN, 0x2E: DELETE,
    0x70: "f1", 0x71: "f2", 0x72: "f3", 0x73: "f4", 0x74: "f5", 0x75: "f6",
    0x76: "f7", 0x77: "f8", 0x78: "f9", 0x79: "f10", 0x7A: "f11", 0x7B: "f12",
}
_BUTTON_BIT = [(0x1, 0), (0x4, 1), (0x2, 2)]


def _norm(ch: str) -> str:
    if ch == " ":
        return SPACE
    if ch.isalpha():
        return ch.lower()
    return ch


class WindowsBackend:
    name = "windows"

    def __init__(self):
        self._hin = k32.GetStdHandle(STD_INPUT_HANDLE)
        self._hout = k32.GetStdHandle(STD_OUTPUT_HANDLE)
        self._old_in = wt.DWORD()
        self._old_out = wt.DWORD()
        self._last_buttons = 0
        self._last_size = None
        self._buf = (INPUT_RECORD * 256)()

    def setup(self) -> None:
        k32.GetConsoleMode(self._hin, ct.byref(self._old_in))
        k32.GetConsoleMode(self._hout, ct.byref(self._old_out))
        k32.SetConsoleMode(self._hin, ENABLE_WINDOW_INPUT | ENABLE_MOUSE_INPUT | ENABLE_EXTENDED_FLAGS)
        k32.SetConsoleMode(self._hout, ENABLE_PROCESSED_OUTPUT | ENABLE_VIRTUAL_TERMINAL_PROCESSING)
        self._last_size = self.size()

    def teardown(self) -> None:
        k32.SetConsoleMode(self._hin, self._old_in.value)
        k32.SetConsoleMode(self._hout, self._old_out.value)

    def size(self):
        info = CONSOLE_SCREEN_BUFFER_INFO()
        if k32.GetConsoleScreenBufferInfo(self._hout, ct.byref(info)):
            w = info.srWindow.Right - info.srWindow.Left + 1
            h = info.srWindow.Bottom - info.srWindow.Top + 1
            if w > 0 and h > 0:
                return w, h
        return 80, 24

    def poll(self, timeout: float) -> List[Event]:
        events: List[Event] = []
        ms = max(0, int(timeout * 1000))
        rc = k32.WaitForSingleObject(self._hin, ms)
        if rc == WAIT_OBJECT_0:
            count = wt.DWORD()
            k32.GetNumberOfConsoleInputEvents(self._hin, ct.byref(count))
            n = min(count.value, 256)
            if n:
                read = wt.DWORD()
                k32.ReadConsoleInputW(self._hin, self._buf, n, ct.byref(read))
                for i in range(read.value):
                    rec = self._buf[i]
                    if rec.EventType == KEY_EVENT:
                        ev = self._key(rec.Event.KeyEvent)
                        if ev:
                            events.append(ev)
                    elif rec.EventType == MOUSE_EVENT:
                        events += self._mouse(rec.Event.MouseEvent)
        cur = self.size()
        if self._last_size is not None and cur != self._last_size:
            events.append(ResizeEvent(*cur))
        self._last_size = cur
        return events

    def _key(self, k):
        vk = k.wVirtualKeyCode
        down = bool(k.bKeyDown)
        ch = k.UnicodeChar or ""
        if vk in _VK_SPECIAL:
            key = _VK_SPECIAL[vk]
        elif vk == 0x1B:
            key = ESC
        elif vk == 0x0D:
            key = ENTER
        elif vk == 0x09:
            key = TAB
        elif vk == 0x08:
            key = BACKSPACE
        elif vk == 0x20:
            key = SPACE
        else:
            o = ord(ch) if ch else 0
            if 0x01 <= o <= 0x1A:
                key = "ctrl+" + chr(o + 96)
            elif o == 0x1B:
                key = ESC
            elif o == 0x08:
                key = BACKSPACE
            elif ch and ch.isprintable():
                key = _norm(ch)
            else:
                return None
        if len(key) == 1 and key.isalpha() and (k.dwControlKeyState & CTRL_MASK):
            key = "ctrl+" + key
        return KeyEvent(key, pressed=down)

    def _mouse(self, m) -> List[Event]:
        x, y = m.dwMousePosition.X, m.dwMousePosition.Y
        state = m.dwButtonState
        flags = m.dwEventFlags
        out: List[Event] = []
        if flags & MOUSE_WHEELED:
            up = not (state & 0x80000000)
            out.append(MouseEvent(x, y, 3 if up else 4, "wheel"))
            self._last_buttons = state
            return out
        pressed = state & ~self._last_buttons
        released = self._last_buttons & ~state
        for bit, btn in _BUTTON_BIT:
            if pressed & bit:
                out.append(MouseEvent(x, y, btn, "press"))
            if released & bit:
                out.append(MouseEvent(x, y, btn, "release"))
        if (flags & MOUSE_MOVED) and state and not out:
            btn = next((b for bit, b in _BUTTON_BIT if state & bit), 0)
            out.append(MouseEvent(x, y, btn, "drag"))
        self._last_buttons = state
        return out