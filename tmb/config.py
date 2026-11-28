"""Persistent user settings (theme, timbre, rhythm keys, latency offset)."""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field, asdict, fields
from typing import Dict, List, Optional, Tuple

DEFAULT_KEYS = ["a", "s", "d", "j", "k", "l"]
VOL_RANGE = (0.0, 2.0)     # per-timbre volume multiplier
LEN_RANGE = (0.25, 4.0)    # per-timbre note-length multiplier (1.0 = natural)
# Timbres whose natural default differs from 1.0x / full volume.
DEFAULT_SOUND = {"bit": {"vol": 1.0, "len": 0.25}}


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _num(v, default: float) -> float:
    """A finite float from `v`, or `default`.

    json happily parses NaN/Infinity literals; float(huge int) overflows.
    Converting the result afterwards (int(nan), int(inf)) would crash the
    load itself, so non-finite values count as garbage here.
    """
    try:
        f = float(v)
    except (TypeError, ValueError, OverflowError):
        return default
    return f if math.isfinite(f) else default


def config_path() -> str:
    if os.name == "nt":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        d = os.path.join(base, "terminal-music-box")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
        d = os.path.join(base, "terminal-music-box")
    return os.path.join(d, "config.json")


@dataclass
class Config:
    mode: str = "unicode"            # "unicode" | "ascii"
    timbre: str = "harp"
    rhythm_keys: List[str] = field(default_factory=lambda: list(DEFAULT_KEYS))
    latency_ms: int = 0              # input latency offset applied to judgments
    prenatal_song: Optional[str] = None
    scroll_speed: float = 1.0        # note fall speed multiplier
    # per-timbre sound settings: {tid: {"vol": float, "len": float}}; a missing
    # entry means the natural defaults (vol 1.0, natural length).
    sound: Dict[str, Dict[str, float]] = field(default_factory=dict)

    def sound_params(self, tid: str) -> Tuple[float, float]:
        d = self.sound.get(tid)
        if d is None:
            d = DEFAULT_SOUND.get(tid, {})
        vol = _clamp(_num(d.get("vol"), 1.0), *VOL_RANGE)
        ln = _clamp(_num(d.get("len"), 1.0), *LEN_RANGE)
        return vol, ln

    def set_sound(self, tid: str, vol: Optional[float] = None,
                  ln: Optional[float] = None) -> None:
        cur_vol, cur_ln = self.sound_params(tid)
        if vol is not None:
            cur_vol = _clamp(vol, *VOL_RANGE)
        if ln is not None:
            cur_ln = _clamp(ln, *LEN_RANGE)
        self.sound[tid] = {"vol": round(cur_vol, 2), "len": round(cur_ln, 2)}

    def save(self) -> None:
        try:
            p = config_path()
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                json.dump(asdict(self), f, ensure_ascii=False, indent=2)
        except OSError:
            pass

    @classmethod
    def load(cls) -> "Config":
        try:
            with open(config_path(), "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError, TypeError):
            return cls()
        if not isinstance(data, dict):
            # A hand-edited file with a non-object root used to crash the app
            # on startup ('list' object has no attribute 'items').
            return cls()
        cfg = cls()
        # Whitelist real fields only: hasattr() also matched method names, so
        # {"save": 1} could replace the save() method and blow up later.
        known = {f.name for f in fields(cls)}
        for k, v in data.items():
            if k in known:
                setattr(cfg, k, v)
        if not isinstance(cfg.rhythm_keys, list) or len(cfg.rhythm_keys) != 6:
            cfg.rhythm_keys = list(DEFAULT_KEYS)
        cfg.rhythm_keys = [str(k).lower()[:1] for k in cfg.rhythm_keys]
        if cfg.mode not in ("unicode", "ascii"):
            cfg.mode = "unicode"
        if not isinstance(cfg.timbre, str) or not cfg.timbre:
            cfg.timbre = "harp"
        if cfg.prenatal_song is not None and not isinstance(cfg.prenatal_song, str):
            cfg.prenatal_song = None
        # A wrong-typed number used to survive the load and crash later —
        # latency_ms/1000.0 with a string, float() on scroll_speed — inside
        # the rhythm game's enter().
        cfg.latency_ms = int(_num(cfg.latency_ms, 0))
        cfg.scroll_speed = _num(cfg.scroll_speed, 1.0)
        if not isinstance(cfg.sound, dict):
            cfg.sound = {}
        cfg.sound = {str(k): dict(v) for k, v in cfg.sound.items()
                     if isinstance(v, dict)}
        return cfg