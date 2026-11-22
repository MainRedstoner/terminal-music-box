#!/usr/bin/env python3
"""Build a .tmbp rhythm-game pack: manifest.json + chart.json + compressed audio.

The audio is re-encoded with ffmpeg to a compact mono track (default Opus
96 kbps, falling back to the always-available native AAC encoder) so packs
stay small on disk and decode into a few dozen MB of PCM on a 1 GB
Raspberry Pi. Output goes to external_songs/ next to the package — that
directory is gitignored because pack audio is usually copyrighted.

Examples:
    python tools/make_pack.py --src packs/my_song --audio song.m4s
    python tools/make_pack.py --audio song.flac --title-zh 我的歌 \
        --title-en My Song --chart chart.json
    python tools/make_pack.py --src packs/tiny --audio tiny.wav --codec wav
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_OUT_DIR = os.path.join(REPO, "external_songs")

CODEC_ARGS = {
    "opus": (["-c:a", "libopus", "-application", "audio"], ".opus"),
    "aac": (["-c:a", "aac"], ".m4a"),
    "mp3": (["-c:a", "libmp3lame"], ".mp3"),
    "wav": (["-c:a", "pcm_s16le"], ".wav"),
}


def probe_duration(path: str) -> float:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return 0.0
    try:
        out = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nk=1:nw=1", path],
            capture_output=True, text=True, timeout=60, check=True)
        return max(0.0, float(out.stdout.strip()))
    except (subprocess.SubprocessError, ValueError, OSError):
        return 0.0


def transcode(src: str, codec: str, bitrate: str, dst: str) -> None:
    flags, _ext = CODEC_ARGS[codec]
    argv = ["ffmpeg", "-y", "-v", "error", "-i", src, "-vn", "-ac", "1"]
    if codec != "opus":
        # libopus only accepts 48k/24k/16k/12k/8k; it always resamples to
        # 48k internally, so the rate flag would just make it fail.
        argv += ["-ar", "44100"]
    argv += flags
    if codec not in ("wav",):
        argv += ["-b:a", bitrate]
    argv += [dst]
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=600)
    if proc.returncode != 0:
        raise SystemExit("ffmpeg %s encode failed:\n%s"
                         % (codec, proc.stderr.strip()[-800:]))


def validate_chart(notes, duration: float) -> None:
    if not isinstance(notes, list) or not notes:
        raise SystemExit("chart has no notes")
    last_t = -1.0
    for item in notes:
        try:
            t, lane = item
        except (TypeError, ValueError):
            raise SystemExit("chart note must be [time, lane]: %r" % (item,))
        if not (0.0 <= float(t)):
            raise SystemExit("negative note time: %r" % (item,))
        if not (isinstance(lane, int) and 0 <= lane <= 5):
            raise SystemExit("lane must be an int 0..5: %r" % (item,))
        if float(t) < last_t:
            raise SystemExit("chart times must be sorted (%r after %r)"
                             % (t, last_t))
        last_t = float(t)
    if duration > 0 and last_t > duration + 2.0:
        # Container metadata can undershoot the decodable length by a frame
        # or two (AAC padding), so a small overshoot is legitimate.
        raise SystemExit("chart ends at %.2fs but audio is %.2fs long"
                         % (last_t, duration))


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--src", metavar="DIR",
                   help="pack source dir with manifest.json + chart.json")
    p.add_argument("--audio", metavar="PATH", help="source audio file")
    p.add_argument("--chart", metavar="PATH", help="chart json (overrides src)")
    p.add_argument("--out", metavar="PATH", help="output .tmbp path")
    p.add_argument("--codec", choices=sorted(CODEC_ARGS), default="opus",
                   help="audio codec (default opus; aac is the fallback)")
    p.add_argument("--bitrate", default="96k", help="audio bitrate (96k)")
    p.add_argument("--id"); p.add_argument("--title-zh", dest="title_zh")
    p.add_argument("--title-en", dest="title_en"); p.add_argument("--artist")
    p.add_argument("--difficulty"); p.add_argument("--offset", type=float)
    p.add_argument("--lead-in", dest="lead_in", type=float)
    p.add_argument("--volume", type=float)
    args = p.parse_args(argv)

    manifest = {"format": 1, "lead_in": 2.0, "offset": 0.0, "volume": 1.0}
    if args.src:
        src_manifest = os.path.join(args.src, "manifest.json")
        try:
            with open(src_manifest, "r", encoding="utf-8") as f:
                manifest.update(json.load(f))
        except (OSError, ValueError) as e:
            raise SystemExit("cannot read %s: %s" % (src_manifest, e))

    overrides = {"id": args.id, "title_zh": args.title_zh,
                 "title_en": args.title_en, "artist": args.artist,
                 "difficulty": args.difficulty, "offset": args.offset,
                 "lead_in": args.lead_in, "volume": args.volume}
    for key, value in overrides.items():
        if value is not None:
            manifest[key] = value

    audio_src = args.audio or manifest.get("audio_src") or ""
    if not audio_src or not os.path.isfile(audio_src):
        raise SystemExit("need --audio PATH (a readable audio file)")
    audio_src = os.path.abspath(audio_src)

    chart_path = args.chart
    if not chart_path and args.src:
        chart_path = os.path.join(args.src, "chart.json")
    if not chart_path:
        raise SystemExit("need --chart PATH or --src DIR with chart.json")
    try:
        with open(chart_path, "r", encoding="utf-8") as f:
            chart = json.load(f)
    except (OSError, ValueError) as e:
        raise SystemExit("cannot read %s: %s" % (chart_path, e))

    song_id = str(manifest.get("id") or "").strip()
    if not song_id:
        song_id = os.path.splitext(os.path.basename(audio_src))[0]
    manifest["id"] = song_id

    duration = probe_duration(audio_src)
    if duration <= 0:
        duration = float(manifest.get("duration") or 0.0)
        if duration <= 0:
            raise SystemExit("cannot determine audio duration (install "
                             "ffprobe, or set duration in manifest.json)")
    manifest["duration"] = round(duration, 3)
    validate_chart(chart.get("notes"), duration)

    # Encode once per codec attempt: opus may be missing from the local
    # ffmpeg build, then the built-in AAC encoder always works.
    attempts = [args.codec] if args.codec != "opus" else ["opus", "aac"]
    with tempfile.TemporaryDirectory() as tmp:
        audio_name = None
        used_codec = args.codec
        for codec in attempts:
            _flags, ext = CODEC_ARGS[codec]
            dst = os.path.join(tmp, "audio" + ext)
            try:
                transcode(audio_src, codec, args.bitrate, dst)
            except SystemExit as e:
                if codec == attempts[-1]:
                    raise
                sys.stderr.write("note: %s; falling back to aac\n" % e)
                continue
            audio_name = "audio" + ext
            used_codec = codec
            break
        assert audio_name is not None
        manifest["audio"] = audio_name
        tmp_audio = os.path.join(tmp, audio_name)

        out = args.out or os.path.join(DEFAULT_OUT_DIR,
                                       "%s.tmbp" % song_id)
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        with zipfile.ZipFile(out, "w") as zf:
            zf.writestr("manifest.json",
                        json.dumps(manifest, ensure_ascii=False, indent=1))
            zf.writestr("chart.json",
                        json.dumps(chart, ensure_ascii=False,
                                   separators=(",", ":")))
            # Opus/AAC are already compressed; storing avoids pointless deflate.
            method = zipfile.ZIP_STORED if used_codec != "wav" else zipfile.ZIP_DEFLATED
            zf.write(tmp_audio, audio_name, compress_type=method)

    src_size = os.path.getsize(audio_src)
    audio_size = _audio_size(out, audio_name)
    pack_size = os.path.getsize(out)
    print("pack   : %s" % out)
    print("audio  : %s, %s, %.1f MB (source %.1f MB, %d%%)"
          % (audio_name, used_codec, audio_size / 1e6, src_size / 1e6,
             round(100 * audio_size / max(1, src_size))))
    print("total  : %.1f MB" % (pack_size / 1e6))
    print("duration %.1fs, %d chart notes" % (duration, len(chart["notes"])))
    return 0


def _audio_size(pack: str, member: str) -> int:
    with zipfile.ZipFile(pack) as zf:
        return zf.getinfo(member).file_size


if __name__ == "__main__":
    sys.exit(main())
