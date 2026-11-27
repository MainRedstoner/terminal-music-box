"""Static contract checks for the single-file chart/align/pack studio page.

The studio is plain HTML + one inline script, so there is no import graph to
check. A missing element used to abort the whole script at load time (the
canvas never drew), so these tests pin the DOM/script contract: every element
the script looks up by id, every label target and every dialog close button
must exist, ids must be unique, the page must stay dependency-free, and the
chart -> align -> pack pipeline must live entirely in that one file.
"""
from __future__ import annotations

import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
STUDIO = ROOT / "tools" / "chart_studio.html"


def read_html() -> str:
    return STUDIO.read_text(encoding="utf-8")


class ChartStudioPageTest(unittest.TestCase):
    def setUp(self) -> None:
        self.html = read_html()
        self.ids = re.findall(r'\bid="([^"]+)"', self.html)
        self.id_set = set(self.ids)

    def test_ids_are_unique(self) -> None:
        duplicates = sorted({i for i in self.ids if self.ids.count(i) > 1})
        self.assertEqual(duplicates, [])

    def test_script_id_lookups_resolve(self) -> None:
        refs = set(re.findall(r'\$\("([^"]+)"\)', self.html))
        refs |= set(re.findall(r'getElementById\("([^"]+)"\)', self.html))
        self.assertGreater(len(refs), 40)
        missing = sorted(refs - self.id_set)
        self.assertEqual(missing, [], "script looks up missing element ids")

    def test_label_targets_resolve(self) -> None:
        targets = set(re.findall(r'\bfor="([^"]+)"', self.html))
        self.assertFalse(targets - self.id_set)

    def test_dialog_close_targets_resolve(self) -> None:
        targets = set(re.findall(r'data-close="([^"]+)"', self.html))
        self.assertTrue(targets)
        self.assertFalse(targets - self.id_set)

    def test_required_shell_elements_exist(self) -> None:
        for element_id in (
            "view", "overview", "audioFile", "importFile", "audioMeta",
            "metaDlg", "metaId", "metaSummary", "helpDlg", "calibDlg",
            "btnExportChart", "btnExportManifest", "btnPlay", "toast",
            # alignment
            "snapSelect", "phaseMs", "phaseRange", "btnAutoPhase",
            "btnPhaseZero", "btnQuantize", "offsetMs", "offsetRange",
            "strength", "strengthVal", "btnShift", "statCurrent",
            "statPreview", "statBands", "statMerge", "quantHint",
            "gridHint", "dirtyChip",
            # packing
            "btnBuildPack", "btnOpenPack", "packFile", "packAudioPlan",
            "packOutName", "packProgress", "packProgressBar",
        ):
            self.assertIn(f'id="{element_id}"', self.html)

    def test_alignment_pipeline_exists(self) -> None:
        for name in ("gridSnap", "targetFor", "autoPhase", "applyQuantize",
                     "applyShift", "updateAlignStats"):
            self.assertIn(name, self.html)

    def test_pack_pipeline_exists(self) -> None:
        # The browser is the whole toolchain now: zip writer, Opus/Ogg muxer,
        # WAV fallback and the .tmbp reader all live in this file.
        for name in ("zipStore", "oggMux", "encodeOpusOgg", "encodeWav",
                     "buildPackBytes", "packManifest", "readZip",
                     "loadPackFile", "inflateRaw"):
            self.assertIn(name, self.html)

    def test_no_command_line_toolchain_left(self) -> None:
        # make_pack.py / chart_canon_style.py / align_studio.html were removed
        # when the page absorbed them; stale references would mislead readers.
        for gone in ("make_pack.py", "chart_canon_style", "align_studio"):
            self.assertNotIn(gone, self.html)

    def test_stays_zero_dependency(self) -> None:
        self.assertEqual(self.html.count("<script>"), 1)
        self.assertNotRegex(self.html, r"<script[^>]+src=")
        self.assertNotRegex(self.html, r"<link[^>]+stylesheet")
        self.assertNotRegex(self.html, r"https?://[^\s\"']+\.(?:js|css)")

    def test_not_a_broken_stub(self) -> None:
        # Guards against an accidental truncation of the file.
        self.assertGreater(len(self.html), 60_000)
        self.assertIn("WebAudio", self.html)
        self.assertIn("chartText", self.html)
        self.assertIn("manifestText", self.html)


if __name__ == "__main__":
    unittest.main()
