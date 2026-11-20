"""Normalized input events shared by every screen and every platform backend."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


# Special key names (lowercase). Printable keys are represented by their
# character; letters are always normalized to lowercase so bindings are
# case-insensitive. Ctrl combinations are "ctrl+<letter>".
ENTER = "enter"
ESC = "esc"
TAB = "tab"
SPACE = "space"
BACKSPACE = "backspace"
DELETE = "delete"
UP = "up"
DOWN = "down"
LEFT = "left"
RIGHT = "right"
HOME = "home"
END = "end"
PGUP = "pgup"
PGDN = "pgdn"


@dataclass(frozen=True)
class KeyEvent:
    key: str
    pressed: bool = True  # False == key release (Windows backend, kitty protocol)
    repeat: bool = False  # keyboard auto-repeat (kitty protocol event type 2)

    @property
    def is_ctrl(self) -> bool:
        return self.key.startswith("ctrl+")

    @property
    def letter(self) -> Optional[str]:
        """The bare letter for a plain or ctrl key, else None."""
        if self.is_ctrl:
            tail = self.key[5:]
            return tail if len(tail) == 1 and tail.isalpha() else None
        return self.key if len(self.key) == 1 and self.key.isalpha() else None


@dataclass(frozen=True)
class MouseEvent:
    x: int  # 0-based column
    y: int  # 0-based row
    button: int  # 0 left, 1 middle, 2 right, 3 wheel-up, 4 wheel-down
    kind: str  # "press" | "release" | "drag" | "wheel"


@dataclass(frozen=True)
class ResizeEvent:
    w: int
    h: int


Event = object  # KeyEvent | MouseEvent | ResizeEvent


def ctrl(letter: str) -> str:
    return "ctrl+" + letter.lower()


# The three exit chords requested by the issue: ^Q ^D ^C ^[
EXIT_KEYS = frozenset({ctrl("q"), ctrl("d"), ctrl("c"), ESC})


def is_exit(key: str) -> bool:
    return key in EXIT_KEYS