"""Persistent user settings (theme, timbre, rhythm keys, latency offset)."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from typing import List, Optional

DEFAULT_KEYS = ["a", "s", "d", "j", "k", "l"]


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
            cfg = cls()
            for k, v in data.items():
                if hasattr(cfg, k):
                    setattr(cfg, k, v)
            if not isinstance(cfg.rhythm_keys, list) or len(cfg.rhythm_keys) != 6:
                cfg.rhythm_keys = list(DEFAULT_KEYS)
            cfg.rhythm_keys = [str(k).lower()[:1] for k in cfg.rhythm_keys]
            if cfg.mode not in ("unicode", "ascii"):
                cfg.mode = "unicode"
            return cfg
        except (OSError, ValueError, TypeError):
            return cls()