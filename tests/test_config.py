"""Config persistence: roundtrip, validation, cross-platform paths."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest import mock

from tmb import config as cfgmod
from tmb.config import DEFAULT_KEYS, Config


class ConfigFile(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "nested", "config.json")
        patcher = mock.patch("tmb.config.config_path", return_value=self.path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write(self, data):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(data, f)

    def test_defaults(self):
        c = Config()
        self.assertEqual(c.mode, "unicode")
        self.assertEqual(c.timbre, "harp")
        self.assertEqual(c.rhythm_keys, DEFAULT_KEYS)
        self.assertEqual(c.latency_ms, 0)
        self.assertIsNone(c.prenatal_song)
        self.assertEqual(c.scroll_speed, 1.0)

    def test_roundtrip_creates_parent_dirs(self):
        c = Config(mode="ascii", timbre="bell", rhythm_keys=list("zxcvbn"),
                   latency_ms=-42, prenatal_song="canon", scroll_speed=2.5)
        c.save()
        self.assertTrue(os.path.isfile(self.path))
        self.assertEqual(Config.load(), c)

    def test_saved_json_is_utf8_and_complete(self):
        Config(prenatal_song="canon").save()
        with open(self.path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(set(data), {"mode", "timbre", "rhythm_keys", "latency_ms",
                                     "prenatal_song", "scroll_speed", "sound"})

    def test_missing_file_gives_defaults(self):
        self.assertEqual(Config.load(), Config())

    def test_corrupt_json_gives_defaults(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("{not json")
        self.assertEqual(Config.load(), Config())

    def test_unknown_fields_are_ignored(self):
        self.write({"timbre": "flute", "bogus": 123})
        c = Config.load()
        self.assertEqual(c.timbre, "flute")
        self.assertFalse(hasattr(c, "bogus"))

    def test_bad_rhythm_keys_length_resets_to_defaults(self):
        for bad in ([], ["a"], list("abcde"), list("abcdefg"), list("abcdefghij")):
            with self.subTest(keys=bad):
                self.write({"rhythm_keys": bad})
                self.assertEqual(Config.load().rhythm_keys, DEFAULT_KEYS)

    def test_non_list_rhythm_keys_resets_to_defaults(self):
        for bad in ("asdfgh", None, 6, {"a": 1}):
            with self.subTest(keys=bad):
                self.write({"rhythm_keys": bad})
                self.assertEqual(Config.load().rhythm_keys, DEFAULT_KEYS)

    def test_keys_are_lowercased_and_single_characters(self):
        self.write({"rhythm_keys": ["A", "BB", "c", "D", "e", "f"]})
        self.assertEqual(Config.load().rhythm_keys, ["a", "b", "c", "d", "e", "f"])

    def test_invalid_mode_resets_to_unicode(self):
        for bad in ("weird", "", None, 3):
            with self.subTest(mode=bad):
                self.write({"mode": bad})
                self.assertEqual(Config.load().mode, "unicode")

    def test_valid_modes_are_kept(self):
        for mode in ("unicode", "ascii"):
            self.write({"mode": mode})
            self.assertEqual(Config.load().mode, mode)

    def test_sound_params_default_to_natural(self):
        c = Config()
        self.assertEqual(c.sound_params("harp"), (1.0, 1.0))
        self.assertEqual(c.sound_params("flute"), (1.0, 1.0))

    def test_bit_defaults_to_a_short_note_length(self):
        c = Config()
        self.assertEqual(c.sound_params("bit"), (1.0, 0.25))
        # a user override always wins over the built-in default
        c.set_sound("bit", ln=1.0)
        self.assertEqual(c.sound_params("bit"), (1.0, 1.0))
        # removing the override restores it
        c.sound.pop("bit")
        self.assertEqual(c.sound_params("bit"), (1.0, 0.25))

    def test_sound_params_clamp_out_of_range_values(self):
        c = Config(sound={"harp": {"vol": 9.0, "len": 0.01},
                          "flute": {"vol": -3.0, "len": 99.0}})
        self.assertEqual(c.sound_params("harp"), (2.0, 0.25))
        self.assertEqual(c.sound_params("flute"), (0.0, 4.0))

    def test_sound_params_ignore_non_numeric_junk(self):
        c = Config(sound={"harp": {"vol": "loud", "len": None}})
        self.assertEqual(c.sound_params("harp"), (1.0, 1.0))

    def test_set_sound_updates_and_persists(self):
        c = Config()
        c.set_sound("harp", vol=1.4, ln=0.5)
        self.assertEqual(c.sound_params("harp"), (1.4, 0.5))
        c.save()
        self.assertEqual(Config.load().sound_params("harp"), (1.4, 0.5))

    def test_set_sound_partial_keeps_the_other_value(self):
        c = Config()
        c.set_sound("bell", vol=0.8, ln=0.75)
        c.set_sound("bell", ln=1.0)
        self.assertEqual(c.sound_params("bell"), (0.8, 1.0))

    def test_load_drops_malformed_sound_entries(self):
        self.write({"sound": {"harp": "loud", "flute": {"vol": 0.5}, 42: {"vol": 1}}})
        c = Config.load()
        self.assertEqual(c.sound_params("harp"), (1.0, 1.0))
        self.assertEqual(c.sound_params("flute"), (0.5, 1.0))

    def test_non_dict_sound_resets_to_empty(self):
        for bad in ("loud", 5, ["harp"]):
            with self.subTest(sound=bad):
                self.write({"sound": bad})
                self.assertEqual(Config.load().sound, {})

    def test_save_is_atomic_enough_to_reload_repeatedly(self):
        c = Config()
        for i in range(5):
            c.latency_ms = i * 10
            c.save()
            self.assertEqual(Config.load().latency_ms, i * 10)

    def test_unwritable_path_does_not_raise(self):
        with mock.patch("tmb.config.config_path", return_value=os.path.join(self.tmp.name, "x", "y", "z.json")):
            with mock.patch("tmb.config.os.makedirs", side_effect=OSError("nope")):
                Config().save()


    def test_non_object_root_gives_defaults(self):
        self.write([])
        self.assertEqual(Config.load().mode, "unicode")

    def test_method_names_cannot_be_overwritten(self):
        self.write({"save": 1, "bogus": 2})
        c = Config.load()
        self.assertFalse(hasattr(c, "bogus"))
        c.save()  # must still be the method, not the injected value

    def test_wrong_typed_numbers_are_normalized(self):
        self.write({"latency_ms": "20", "scroll_speed": "fast",
                    "timbre": ["harp"], "prenatal_song": 7})
        c = Config.load()
        self.assertEqual(c.latency_ms, 20)
        self.assertEqual(c.scroll_speed, 1.0)
        self.assertEqual(c.timbre, "harp")
        self.assertIsNone(c.prenatal_song)

    def test_non_finite_numbers_fall_back_to_defaults(self):
        # json accepts NaN/Infinity literals; int(nan) raises ValueError and
        # int(inf) OverflowError - both used to crash Config.load() itself.
        self.write({"latency_ms": float("nan")})
        self.assertEqual(Config.load().latency_ms, 0)
        self.write({"latency_ms": float("inf")})
        self.assertEqual(Config.load().latency_ms, 0)
        self.write({"scroll_speed": float("nan")})
        self.assertEqual(Config.load().scroll_speed, 1.0)
        self.write({"latency_ms": 10 ** 400})   # overflows float()
        self.assertEqual(Config.load().latency_ms, 0)
        self.write({"scroll_speed": 10 ** 400})
        self.assertEqual(Config.load().scroll_speed, 1.0)

    def test_scroll_speed_is_bounded_on_load(self):
        # Finite-but-huge survives isfinite and then makes `speed` inf in the
        # falling-note draw; the bound keeps the game drawable.
        self.write({"scroll_speed": 1e308})
        self.assertEqual(Config.load().scroll_speed, 8.0)
        self.write({"scroll_speed": 0.01})
        self.assertEqual(Config.load().scroll_speed, 0.2)
        self.write({"scroll_speed": 2.5})
        self.assertEqual(Config.load().scroll_speed, 2.5)


class ConfigPath(unittest.TestCase):
    def test_windows_uses_appdata(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(cfgmod.os, "name", "nt"):
                with mock.patch.dict(os.environ, {"APPDATA": d}):
                    p = cfgmod.config_path()
            self.assertEqual(p, os.path.join(d, "terminal-music-box", "config.json"))

    def test_posix_uses_xdg_config_home(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(cfgmod.os, "name", "posix"):
                with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": d}):
                    p = cfgmod.config_path()
            self.assertEqual(p, os.path.join(d, "terminal-music-box", "config.json"))

    def test_posix_falls_back_to_dot_config(self):
        with mock.patch.object(cfgmod.os, "name", "posix"):
            with mock.patch.dict(os.environ, {}, clear=True):
                with mock.patch.object(cfgmod.os.path, "expanduser", return_value="/home/pi"):
                    p = cfgmod.config_path()
        self.assertEqual(p.replace("\\", "/"),
                         "/home/pi/.config/terminal-music-box/config.json")


if __name__ == "__main__":
    unittest.main()
