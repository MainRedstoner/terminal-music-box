"""Screen registration."""
from __future__ import annotations


def register_all(app) -> None:
    from .main_menu import MainMenu
    from .freeplay import FreePlayScreen
    from .song_select import SongSelectScreen
    from .rhythm import (RhythmListScreen, RhythmCalibScreen, RhythmKeysScreen)
    from .rhythm_game import RhythmGameScreen
    app.register("menu", MainMenu)
    app.register("freeplay", FreePlayScreen)
    app.register("song_select", SongSelectScreen)
    app.register("rhythm_list", RhythmListScreen)
    app.register("rhythm_game", RhythmGameScreen)
    app.register("rhythm_calib", RhythmCalibScreen)
    app.register("rhythm_keys", RhythmKeysScreen)