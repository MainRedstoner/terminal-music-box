"""Screen registration."""
from __future__ import annotations


def register_all(app) -> None:
    from .main_menu import MainMenu
    from .freeplay import FreePlayScreen
    from .song_select import SongSelectScreen
    from .timbre_select import TimbreSelectScreen
    from .rhythm import RhythmMenuScreen, RhythmCalibScreen, RhythmKeysScreen
    from .rhythm_game import RhythmGameScreen
    app.register("menu", MainMenu)
    app.register("freeplay", FreePlayScreen)
    app.register("song_select", SongSelectScreen)
    app.register("timbre_select", TimbreSelectScreen)
    app.register("rhythm_menu", RhythmMenuScreen)
    app.register("rhythm_game", RhythmGameScreen)
    app.register("rhythm_calib", RhythmCalibScreen)
    app.register("rhythm_keys", RhythmKeysScreen)