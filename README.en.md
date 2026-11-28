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
- **Prenatal mode** — gentle auto-played melodies that keep playing while a play
  key is held (and for 2 seconds after the last one is released); otherwise they
  pause. While it is on, the play keys are muted (only the auto-play sounds) and
  the song button appears; when the melody ends, a 5-second rest leaves the play
  keys deaf and then the mode turns itself off.
- **Rhythm Game** — vertically falling notes, a judgment line,
  Perfect / Good / Miss judgment with effects, live score & combo, latency
  calibration, and rebindable keys. The song list is grouped into
  **Built-in Music / External Music** with a live `/` search (Chinese or
  English); external packs (chart + audio bundled
  into one `.tmbp` file) dropped into `external_songs/` show up and play.
- **Audio** — a real-time polyphonic mixer streaming to ALSA (`aplay`) or
  PulseAudio/PipeWire (`pacat`/`paplay`) on Linux, `winmm` on Windows, and WAV/null
  backends for headless testing. Timbres are pre-rendered in a background thread
  at startup and on switch, so the first press never stalls. Dense chords duck
  the mix automatically (peak-hold + slow release) instead of clipping.

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
python main.py --no-kitty          # testing: skip the kitty keyboard protocol
```

Settings (UI mode, timbre, rhythm keys, latency offset, prenatal song,
per-timbre sound settings) persist to
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

- `^X` — open the timbre list and pick (harp, bass, flute, bell, guitar, chime,
  xylophone, iron xylophone, cow bell, didgeridoo, bit, banjo, pling). Inside
  the list, `/` opens a live filter matching Chinese names, English names and
  timbre ids alike; each search row shows the full name in both languages
  with the matched characters highlighted in gold.
- **Key hold**: on Kitty-protocol terminals (or Windows terminals), sustained
  timbres (flute, bit, didgeridoo) hold until key-up. Harp, bell and chime
  decay at the current length setting while held and speed up to their own
  release time constant (0.15–0.25 s) on key-up; other timbres stay
  fixed-length one-shots, and holding never re-triggers a note. WSL (ConPTY)
  stops delivering key releases on the alternate screen, so the app
  automatically skips it there to keep key-up events flowing.
- **Volume / length**: the strip below the keyboard — `↑/↓` switches between
  volume and note length, `←/→` steps the current timbre's value (volume
  0–2.0, length 0.25–4×; ringing timbres can only be shortened, which speeds
  up their decay rather than cutting the tail). Changes apply instantly; bit
  defaults to 0.25× length.
- `^T` — toggle prenatal mode.
- `^A` — choose the prenatal song (only responds while prenatal mode is on);
  `/` inside the list searches by Chinese or English title, with both names
  shown and the matched characters highlighted.
- `^Q`/`^D`/`^C`/`Esc` — back to menu.
- The on-screen keys and buttons are mouse-clickable.

### Prenatal mode
Turning it on — or changing its song — does not start the melody by itself:
press **any** play key to begin. From then on the play keys become a silent
accompaniment: they still light up and keep the music going, but make no sound.
**2 seconds** without a play key held pauses it; the next key press resumes it,
and a key held down counts as ongoing activity even after another key was
pressed and released on top of it. The
**Song button** shows only while prenatal mode is on, and `^A` responds only
then. The choice is limited to the rhythm game's four songs (defaults to
Canon in C). Timbres are locked per song exactly as in the rhythm game — the
didgeridoo for Canon, the electric piano for the other three — so long notes
sound exactly as they do there; `^X` still overrides one temporarily, and the
volume/length strip follows the timbre that is actually sounding. When the song
ends it stops and rests for **5 seconds**: the play keys are deaf for those 5
seconds, then prenatal mode turns itself off instead of looping.
The melody follows the audio output clock, so its
notes land on exact samples regardless of frame rate or a stalled frame.

Canon, Minuet in G, Turkish March and Für Elise sound pitches outside the
free-play keyboard: the first start — and any start after a song or timbre
change — shows a brief "loading" pass that pre-renders them; a melody already
playing resumes where it was, while a not-yet-started one stays silent until a
play key; later starts are immediate.

### Rhythm Game
- The melody auto-plays for the whole run — each note sounds exactly as it
  crosses the judgment line. Your taps are silent judgment only.
- Press `/` in the song list to search: built-in and external packs filter
  live by Chinese title, English title or id; search rows show both titles
  with the matched characters highlighted, and a group header stays
  visible while anything under it matches. `Esc` clears the search; a second
  `Esc` returns to the main menu.
- Canon's timbre is locked to the didgeridoo; Turkish March, Minuet in G, and
  Für Elise use the electric piano, regardless of the free-play timbre selection.
- Turkish March is the complete rondo
  (A-B-A'-C-D-E-C-A-B-A'-transition-coda); its chart taps the **eighth-note
  skeleton** of the right-hand theme — the sixteenth-note runs are still heard
  from the auto-play but are not tapped. Dense passages stay on the four inner
  lanes, a note crosses to the other hand once one hand has carried six fast
  notes, and every other bar's accented downbeat plus the final note adds a
  two-key chord.
- Default keys: `A S D J K L` (6 lanes), rebindable in **Key Config**
  (binding a key already in use swaps the two lanes).
- Canon's chart is authored: dense phrases use the middle four lanes
  (`S D J K`), rotating the fingering every couple of cycles so long streams
  never settle into one loop; isolated notes spread across all six by register,
  and phrase accents are two-key chords.
- All four rhythm charts share one lane-planning toolbox (`tmb/charts.py`):
  pitches are cut into six contiguous bands **by note count** so a pitch always
  falls in the same place; eighth notes and faster stay on the middle four keys
  while the outer two take only isolated long notes; a repair pass removes
  repeated lanes and breaks over-long one-hand blocks; and an accent chord is a
  mirror (`A`↔`L`, `S`↔`K`, `D`↔`J`), the same shape on both hands.
- **Latency Calibration** measures your input offset against a metronome (median
  of 12 taps).
- `Esc` pauses (only `Esc` during play); the pause menu offers quit or resume,
  and resuming runs a **3-second countdown** first.
- Judgment: **Perfect** (±50 ms), **Good** (±120 ms), else **Miss**.
- Live score, combo, max combo, Perfect/Good/Miss counts and accuracy; the result
  screen shows a grade.

## Built-in songs

Four public-domain melodies, all offered by both the rhythm game and prenatal
mode. The rhythm game contains the complete Canon (with falling notes derived
from violin I),
Minuet in G (AABB repeats, right-hand lead banded by note count, mirrored accents),
Turkish March (right-hand theme on its eighth-note skeleton, complete rondo), and
Für Elise (top right-hand voice, dense notes on the middle four lanes, mirrored
double taps on chords and downbeats):

| Song | Chinese |
| --- | --- |
| Canon in C | 卡农 |
| Minuet in G | G 大调小步舞曲 |
| Turkish March | 土耳其进行曲 |
| Für Elise | 致爱丽丝 |

Canon uses the complete three-violin-and-bass score from
[Mutopia-2015/09/02-2047](https://www.mutopiaproject.org/cgibin/piece-info.cgi?id=2047),
typeset by Michael Fischer v. Mollard and licensed under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), transposed from D to C.

Minuet in G, BWV Anh. 114 (Christian Petzold), uses the public-domain two-staff
score from [Mutopia-2017/01/19-75](https://www.mutopiaproject.org/cgibin/piece-info.cgi?id=75),
including both repeated sections and the written grace note.

Turkish March uses the complete written-through score from
[Mutopia-2015/08/13-108](https://www.mutopiaproject.org/cgibin/piece-info.cgi?id=108),
typeset by Rune Zedeler and Chris Sawer (public domain); repeats are not taken.
Auto-play keeps both piano hands and the sixteenth-note runs, while the chart taps
only the eighth-note skeleton of the right-hand melody, with ornaments shorter
than a sixteenth removed.

Für Elise uses the complete WoO 59 piano score from
[Mutopia-2015/08/18-931](https://www.mutopiaproject.org/cgibin/piece-info.cgi?id=931)
(Breitkopf & Härtel, 1888), with both printed repeats expanded. Typesetter Stelios
Samelis dedicated this edition to the public domain. Its chart keeps the top
right-hand voice as the primary tap; micro-timed grace notes remain only in the
auto-played score. Eighth notes and faster stay on the middle four lanes while the
outer two take only isolated long notes, no lane repeats on three consecutive
onsets, and chords are mirrored across the middle; a fast right-hand passage lends
one note to the left hand after six notes, so two fingers never machine-gun a run.

**Dynamics** (强弱): the numeric scores accept a velocity per note (an optional
extra element in `seq`/`timed` tuples), and `apply_dynamics` transcribes the
markings of the source editions. The scores carry exactly what their sources
notate: the Turkish March's Mutopia typeset ships a dedicated dynamics voice
(p/mp/f/ff, crescendos, sforzandi) and auto-play follows it note by note;
Für Elise is pp throughout per its source; the two Baroque pieces carry no
dynamic markings at all, so they keep a uniform level. Both the rhythm game's
auto-played melody and prenatal playback follow the score's dynamics; the
auto-play additionally yields polyphony headroom (`SongPlayer.POLYPHONY_GAIN`)
so soft passages never trigger the mixer's adaptive ducking and the dynamics
pass through untouched — the limiter only steps in on the loudest tuttis
(such as the closing chords), pinning the strongest written level to the
peak ceiling.

## External Song Packs

The rhythm game can load custom charts: a chart and its audio bundled into
**one `.tmbp` file** (a zip holding `manifest.json`, `chart.json` and a
compressed audio track). Drop it into `external_songs/` next to the package
and it appears under the "External Music" group in the song list. That
directory is excluded via `.gitignore` — external audio is usually
copyrighted material and must not enter version control.

- **Playback**: entering the song decodes the pack audio to 44.1 kHz mono PCM
  with ffmpeg (a 4-minute song is about 20 MB of RAM) and streams it through
  the existing mixer as one long voice; pause/resume line up exactly, and on
  slow devices the audio re-aligns once it drifts more than 80 ms from the
  song clock. Packs whose audio is a plain PCM WAV play without ffmpeg.

Charting, aligning and packing all happen in one web page — no command-line
tools are involved.

### Chart Studio: chart / align / pack

Open **`tools/chart_studio.html`** — a zero-dependency, single-file web tool
(Chrome/Edge recommended). Audio plays through WebAudio on the browser's audio
thread, so page jank never affects the transport. The layout is a canvas plus a
song/selection/grid sidebar and a transport dock: the overview strip scrubs,
while the beat grid, waveform, per-lane note counts, BPM and alignment stats
stay in view.

- **Loading** — pick a file in the top bar, or drop audio, a `chart.json` or a
  `.tmbp` onto the window; with no material, *Demo* synthesises 60 seconds of
  music at 120 BPM.
- **Latency calibration** — 16 metronome clicks, median tap offset, compensating
  output latency + reaction time in one number; at reduced speed the reaction
  part scales with the rate. Notes placed while paused sit exactly on the
  playhead instead of being shifted by the reaction delay.
- **Play view** — the same `A S D J K L` six lanes as the game; tap while
  listening, `Space` pauses/resumes, 0.25×–1× speed, metronome and key click.
- **Timeline view** (`Tab`) — piano roll + waveform + grid: click to select,
  drag to move in time and lane, `↑/↓` changes lane, `←/→` ±10 ms (Shift ±50 ms),
  `Del` deletes, `Ctrl+Z` / `Ctrl+Shift+Z` undo/redo, `Ctrl+wheel` zooms. A
  double tap is `L` on a selected note then click the partner — both align to
  one timestamp and edit together (`U` unlinks).
- **Grid / align** — the grid unit is an integer fraction of the BPM beat
  (1, 1/2, 1/4, 1/8); phase slides the whole grid sideways and *Auto phase*
  solves it from the circular mean of the note times; offset fixes a chart that
  sits uniformly early/late, and strength (0–100%) controls how far notes move
  toward the grid. The sidebar shows the current deviation (median/p90), the
  preview movement, how many notes land within 10/20/30 ms, and how many time
  points would merge. Yellow ticks are only a preview — *Quantise all* rewrites
  the times (undoable, same-lane duplicates merged).
- **Packing** — *Pack / Export* writes the `.tmbp` in one click: WebCodecs
  encodes the audio to mono Opus 96 kbps inside Ogg (about 3 MB for 4 minutes);
  without WebCodecs the source file is embedded verbatim, and a synthesized
  demo falls back to 44.1 kHz mono WAV (which the engine plays without ffmpeg).
  A finished pack reopens through *Music pack* in the top bar — the `.tmbp` is
  the project file, so no separate chart-source directory is needed.
- **Drafts** — autosaved in the browser per audio file, including metadata,
  BPM, grid phase and double-tap groups.

Bilibili `.m4s` segments cannot be decoded by browsers — remux first:
`ffmpeg -i in.m4s -c:a copy out.m4a`.

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
  external.py      external song packs (.tmbp): parsing, ffmpeg decode, PCM player
  screens/         main_menu, freeplay, rhythm, rhythm_game, song_select, timbre_select
tools/
  chart_studio.html     chart / align / pack in one standalone web page (zero deps)
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
  `aplay` and `paplay` work. Installing `pulseaudio-utils` alone does not start
  a server -- check `pactl info` first; otherwise TMB falls back to ALSA.

## License

Melodies are public-domain compositions. Synthesized audio is generated at runtime;
no Minecraft assets are bundled or redistributed.