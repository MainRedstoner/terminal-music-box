# Terminal Music Box

[中文](README.md) | **English**

A zero-dependency, cross-platform terminal instrument and rhythm game written in
pure Python 3 (standard library only). Runs in any ANSI terminal, supports full
keyboard **and** mouse control, and is designed primarily for the **Raspberry Pi**.

Implements [issue #1 — software development plan](https://github.com/MainRedstoner/terminal-music-box/issues/1).

## Features

- **Two UI modes**, switchable from the main menu:
  - **Unicode** — Chinese text, rounded buttons (`╭─╮ │ ╰─╯`).
  - **ASCII** — English only, plain buttons (`+-|`), maximum compatibility.
- **Free Play** — a three-octave keyboard played with the letter keys, with all
  13 melodic Minecraft 1.20 note-block timbres (percussion excluded), synthesized
  procedurally at runtime (no sample files).
- **Prenatal mode** — gentle auto-played melodies that keep playing only while you
  press a play key within a 2-second window; otherwise they pause. While it is on,
  the play keys are muted (only the auto-play sounds) and the song button appears.
- **Rhythm Game** — vertically falling notes, a judgment line,
  Perfect / Good / Miss judgment with effects, live score & combo, latency
  calibration, and rebindable keys.
- **Audio** — a real-time polyphonic mixer streaming to ALSA (`aplay`) or
  PulseAudio/PipeWire (`pacat`/`paplay`) on Linux, `winmm` on Windows, and WAV/null
  backends for headless testing. Timbres are pre-rendered in a background thread
  at startup and on switch, so the first press never stalls.

## Requirements

- Python **3.10+** (standard library only — no `pip install` needed).
- Linux/Raspberry Pi: `aplay` (alsa-utils) or `paplay` (pulseaudio-utils) for sound.
- Windows: sound via the built-in `winmm` API (no extra software).
- A terminal with ANSI + 256-color support (Linux console, SSH, Windows Terminal,
  most modern terminals). Mouse support uses SGR extended mouse tracking.

## Run

```bash
python main.py            # or: python -m tmb
python main.py --mode ascii        # start in ASCII mode
python main.py --audio alsa        # force a backend: alsa|pulse|winmm|null|wav
python main.py --wav out.wav       # render audio to a file instead of a device
python main.py --demo              # headless scripted demo (no terminal needed)
```

Settings (UI mode, timbre, rhythm keys, latency offset, prenatal song) persist to
`~/.config/terminal-music-box/config.json` (Linux) or
`%APPDATA%/terminal-music-box/config.json` (Windows).

## Controls

### Main menu
`↑/↓` select · `Enter` confirm · mouse click · `1–4` shortcuts.
`^Q`/`^D`/`^C`/`Esc` quit.

### Free Play
Three diatonic C-major octaves (7 natural notes per row):

```
Q W E R T Y U   — high  (C5..B5)
A S D F G H J   — mid   (C4..B4)
Z X C V B N M   — low   (C3..B3)
```

- `^X` — cycle timbre (harp, bass, flute, bell, guitar, chime, xylophone,
  iron xylophone, cow bell, didgeridoo, bit, banjo, pling).
- **Key hold**: on Kitty-protocol terminals (or Windows terminals), sustained
  timbres (flute, bit, didgeridoo) sound for as long as the key is held; other
  terminals keep fixed-length notes, and holding never re-triggers a note.
- `^T` — toggle prenatal mode.
- `^A` — choose the prenatal song.
- `^Q`/`^D`/`^C`/`Esc` — back to menu.
- The on-screen keys and buttons are mouse-clickable.

### Prenatal mode
When on, a lullaby plays automatically and the play keys become a silent
accompaniment: they still light up and keep the music going, but make no sound.
Press **any** play key within **2 seconds** to keep it playing; otherwise it
pauses, and the next key press resumes it. The **Song button** shows only while
prenatal mode is on; `^A` picks the song at any time (defaults to the first:
Twinkle Twinkle). Songs loop.

### Rhythm Game
- The melody auto-plays for the whole run — each note sounds exactly as it
  crosses the judgment line. Your taps are silent judgment only.
- Default keys: `A S D J K L` (6 lanes), rebindable in **Key Config**
  (binding a key already in use swaps the two lanes).
- **Latency Calibration** measures your input offset against a metronome (median
  of 12 taps).
- `Esc` pauses (only `Esc` during play); the pause menu offers quit or resume,
  and resuming runs a **3-second countdown** first.
- Judgment: **Perfect** (±50 ms), **Good** (±120 ms), else **Miss**.
- Live score, combo, max combo, Perfect/Good/Miss counts and accuracy; the result
  screen shows a grade.

## Built-in songs

Eight public-domain melodies, shared by prenatal mode and the rhythm game
(beatmaps are derived from the melodies automatically):

| Song | Chinese |
| --- | --- |
| Twinkle Twinkle | 小星星 |
| Mary Had a Little Lamb | 玛丽有只小羊羔 |
| Ode to Joy | 欢乐颂 |
| Jingle Bells | 铃儿响叮当 |
| Happy Birthday | 祝你生日快乐 |
| Canon in C (fragment) | 卡农(片段) |
| Brahms' Lullaby | 摇篮曲 |
| London Bridge | 伦敦桥 |

## Architecture

```
tmb/
  events.py        normalized key/mouse/resize events
  ansi.py          screen buffer + diff renderer (wide-char aware)
  terminal.py      platform facade (alternate screen, mouse, lifecycle)
  term_posix.py    termios raw mode + ANSI/SGR input parser (Linux/macOS)
  term_win.py      Windows console INPUT_RECORD backend (key-up + mouse)
  ui.py            immediate-mode widgets + mouse hit-testing
  theme.py         Unicode/ASCII themes + zh/en string tables
  config.py        persistent settings
  app.py           state machine + main loop
  testing.py       headless terminal for tests
  audio/
    backends.py    alsa / pulse / winmm / wav / null outputs
    engine.py      polyphonic mixer thread + voices
    synth.py       procedural Minecraft note-block timbres
  songs.py         melodies, beatmaps, pausable song player
  screens/         main_menu, freeplay, rhythm, rhythm_game, song_select
```

### Cross-platform input
- **POSIX**: raw `termios`, incremental UTF-8 decode, escape-sequence parser;
  lone `Esc` disambiguated by a short timeout; `SIGWINCH` for resize.
- **Windows**: `ReadConsoleInputW` gives key-down **and** key-up plus native mouse
  events; output uses VT processing so the same ANSI renderer works.
- Key-release is unavailable on POSIX, so auto-repeat events are debounced with a
  short timeout instead of being treated as new presses.

## Tests

```bash
python -m unittest discover -s tests -v
```

The suite drives the app headlessly (injected events, captured text frames) and
verifies the mixer/synth by rendering to WAV — no interactive terminal or sound
card required.

## Raspberry Pi notes

- Install: `sudo apt install python3 alsa-utils` (or `pulseaudio-utils`).
- Run `python3 main.py` directly; works over SSH too (mouse needs SGR support in
  your terminal).
- No sound? Check `aplay -l` for an output device; on PipeWire desktops both
  `aplay` and `paplay` work.

## License

Melodies are public-domain compositions. Synthesized audio is generated at runtime;
no Minecraft assets are bundled or redistributed.