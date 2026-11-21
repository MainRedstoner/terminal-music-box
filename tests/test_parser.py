"""POSIX ANSI/SGR input parser (importable and testable on Windows too)."""
from __future__ import annotations

import unittest

from unittest import mock

from tmb.events import KeyEvent, MouseEvent
from tmb.term_posix import _Parser, _parse_flags_reply, under_wsl


def keys(events):
    return [e.key for e in events if isinstance(e, KeyEvent)]


class ParserKeys(unittest.TestCase):
    def setUp(self):
        self.p = _Parser()

    def test_letters_are_lowercased(self):
        ev = self.p.feed(b"AbCzZ")
        self.assertEqual(keys(ev), ["a", "b", "c", "z", "z"])
        self.assertTrue(all(e.pressed for e in ev))

    def test_digits_and_punctuation_pass_through(self):
        self.assertEqual(keys(self.p.feed(b"123!-")), ["1", "2", "3", "!", "-"])

    def test_ctrl_chords(self):
        for code, letter in ((0x01, "a"), (0x11, "q"), (0x04, "d"),
                             (0x03, "c"), (0x18, "x"), (0x14, "t")):
            with self.subTest(code=code):
                self.assertEqual(keys(self.p.feed(bytes([code]))), ["ctrl+" + letter])

    def test_ctrl_chords_in_one_stream(self):
        self.assertEqual(keys(self.p.feed(bytes([1, 17, 4, 3, 24, 20]))),
                         ["ctrl+a", "ctrl+q", "ctrl+d", "ctrl+c", "ctrl+x", "ctrl+t"])

    def test_control_aliases(self):
        self.assertEqual(keys(self.p.feed(b"\t")), ["tab"])
        self.assertEqual(keys(self.p.feed(b"\r")), ["enter"])
        self.assertEqual(keys(self.p.feed(b"\n")), ["enter"])
        self.assertEqual(keys(self.p.feed(b"\x7f")), ["backspace"])
        self.assertEqual(keys(self.p.feed(b"\x08")), ["backspace"])
        self.assertEqual(keys(self.p.feed(b" ")), ["space"])

    def test_nul_and_other_c0_are_dropped(self):
        self.assertEqual(self.p.feed(b"\x00\x1c\x1d\x1e\x1f"), [])
        self.assertEqual(self.p.feed(b"\x0b"), [KeyEvent("ctrl+k")])

    def test_csi_arrows(self):
        for seq, name in ((b"\x1b[A", "up"), (b"\x1b[B", "down"),
                          (b"\x1b[C", "right"), (b"\x1b[D", "left"),
                          (b"\x1b[H", "home"), (b"\x1b[F", "end")):
            with self.subTest(seq=seq):
                self.assertEqual(keys(self.p.feed(seq)), [name])

    def test_ss3_arrows_and_fkeys(self):
        self.assertEqual(keys(self.p.feed(b"\x1bOA\x1bOB\x1bOC\x1bOD")),
                         ["up", "down", "right", "left"])
        self.assertEqual(keys(self.p.feed(b"\x1bOP")), ["f1"])

    def test_tilde_keys(self):
        self.assertEqual(keys(self.p.feed(b"\x1b[3~\x1b[5~\x1b[6~")),
                         ["delete", "pgup", "pgdn"])
        self.assertEqual(keys(self.p.feed(b"\x1b[200~")), [])

    def test_shift_tab(self):
        self.assertEqual(keys(self.p.feed(b"\x1b[Z")), ["tab"])

    def test_modified_arrow_params(self):
        self.assertEqual(keys(self.p.feed(b"\x1b[1;5A")), ["up"])

    def test_alt_letter_is_normalized(self):
        self.assertEqual(keys(self.p.feed(b"\x1ba")), ["a"])

    def test_legacy_sequences_never_emit_releases(self):
        ev = self.p.feed(b"a\x1b[A\r\x1b[<0;1;1M")
        self.assertTrue(all(e.pressed for e in ev if isinstance(e, KeyEvent)))


class KittyProtocol(unittest.TestCase):
    """CSI-u encoding: press / repeat / release events (kitty keyboard protocol)."""

    def setUp(self):
        self.p = _Parser()

    def test_plain_letter_press_and_release(self):
        self.assertEqual(self.p.feed(b"\x1b[97u"), [KeyEvent("a")])
        self.assertEqual(self.p.feed(b"\x1b[97;1:3u"), [KeyEvent("a", pressed=False)])

    def test_ctrl_letter_arrives_as_csi_u(self):
        for code, letter in ((97, "a"), (113, "q"), (100, "d"), (99, "c"),
                             (120, "x"), (116, "t")):
            with self.subTest(code=code):
                self.assertEqual(keys(self.p.feed(b"\x1b[%d;5u" % code)),
                                 ["ctrl+" + letter])
                self.assertEqual(keys(self.p.feed(b"\x1b[%d;5:3u" % code)),
                                 ["ctrl+" + letter])
                self.assertFalse(self.p.feed(b"\x1b[%d;5:3u" % code)[0].pressed)

    def test_repeat_event_type(self):
        self.assertEqual(self.p.feed(b"\x1b[97;1:2u"),
                         [KeyEvent("a", pressed=True, repeat=True)])

    def test_functional_keys(self):
        self.assertEqual(keys(self.p.feed(b"\x1b[13u")), ["enter"])
        self.assertEqual(keys(self.p.feed(b"\x1b[27u")), ["esc"])
        self.assertEqual(keys(self.p.feed(b"\x1b[9u")), ["tab"])
        self.assertEqual(keys(self.p.feed(b"\x1b[127u")), ["backspace"])
        self.assertEqual(keys(self.p.feed(b"\x1b[32u")), ["space"])

    def test_digits_and_punctuation_pass_through(self):
        self.assertEqual(keys(self.p.feed(b"\x1b[49u\x1b[33u\x1b[45u")),
                         ["1", "!", "-"])

    def test_arrow_and_tilde_releases(self):
        self.assertEqual(self.p.feed(b"\x1b[1;1:3A"), [KeyEvent("up", pressed=False)])
        self.assertEqual(self.p.feed(b"\x1b[1;1:2B"),
                         [KeyEvent("down", pressed=True, repeat=True)])
        self.assertEqual(self.p.feed(b"\x1b[1;1:3D"), [KeyEvent("left", pressed=False)])
        self.assertEqual(self.p.feed(b"\x1b[3;1:3~"),
                         [KeyEvent("delete", pressed=False)])

    def test_alternate_key_and_text_subfields_are_ignored(self):
        self.assertEqual(keys(self.p.feed(b"\x1b[97:65;1;;97u")), ["a"])

    def test_malformed_csi_u_is_dropped(self):
        self.assertEqual(self.p.feed(b"\x1b[u"), [])
        self.assertEqual(self.p.feed(b"\x1b[;;u"), [])
        self.assertEqual(self.p.feed(b"\x1b[999999999999u"), [])

    def test_capability_replies_are_ignored(self):
        self.assertEqual(self.p.feed(b"\x1b[?3u\x1b[?62;1;6c"), [])


class UnderWsl(unittest.TestCase):
    def test_wsl_versions_are_detected(self):
        for version in ("Linux version 5.15.167.4-microsoft-standard-WSL2",
                        "Linux version 4.4.0-19001-Microsoft"):
            with mock.patch("builtins.open", mock.mock_open(
                    read_data=version), create=True):
                self.assertTrue(under_wsl())

    def test_native_linux_and_missing_proc_are_not_wsl(self):
        with mock.patch("builtins.open", mock.mock_open(
                read_data="Linux version 6.6.62-rpi7 (pi)"), create=True):
            self.assertFalse(under_wsl())
        with mock.patch("builtins.open", side_effect=OSError):
            self.assertFalse(under_wsl())


class FlagsReply(unittest.TestCase):
    def test_flags_replies_are_parsed(self):
        self.assertEqual(_parse_flags_reply(b"\x1b[?3u"), 3)
        self.assertEqual(_parse_flags_reply(b"\x1b[?0u"), 0)
        self.assertEqual(_parse_flags_reply(b"\x1b[?61;4;6c\x1b[?23;1u"), 23)

    def test_non_replies_give_none(self):
        self.assertIsNone(_parse_flags_reply(b"\x1b[?62;1;6c"))
        self.assertIsNone(_parse_flags_reply(b"plain bytes"))
        self.assertIsNone(_parse_flags_reply(b"\x1b[?u"))


class ParserPending(unittest.TestCase):
    def setUp(self):
        self.p = _Parser()

    def test_lone_esc_is_pending_then_resolves(self):
        self.assertEqual(self.p.feed(b"\x1b"), [])
        self.assertTrue(self.p.has_pending())
        self.assertEqual(self.p.resolve_pending(), [KeyEvent("esc")])
        self.assertFalse(self.p.has_pending())

    def test_complete_sequence_is_not_pending(self):
        self.assertEqual(keys(self.p.feed(b"\x1b[A")), ["up"])
        self.assertFalse(self.p.has_pending())
        self.assertEqual(self.p.resolve_pending(), [])

    def test_incomplete_csi_is_dropped_on_resolve(self):
        self.assertEqual(self.p.feed(b"\x1b[<0;10"), [])
        self.assertTrue(self.p.has_pending())
        self.assertEqual(self.p.resolve_pending(), [])
        self.assertFalse(self.p.has_pending())

    def test_incomplete_ss3_is_dropped_on_resolve(self):
        self.assertEqual(self.p.feed(b"\x1bO"), [])
        self.assertTrue(self.p.has_pending())
        self.assertEqual(self.p.resolve_pending(), [])

    def test_escape_split_across_feeds(self):
        self.assertEqual(self.p.feed(b"\x1b"), [])
        self.assertEqual(keys(self.p.feed(b"[A")), ["up"])

    def test_csi_split_across_feeds(self):
        self.assertEqual(self.p.feed(b"\x1b["), [])
        self.assertEqual(self.p.feed(b"<0;3;"), [])
        self.assertEqual(self.p.feed(b"4M"), [MouseEvent(2, 3, 0, "press")])

    def test_pending_does_not_swallow_following_keys(self):
        self.p.feed(b"\x1b")
        self.p.resolve_pending()
        self.assertEqual(keys(self.p.feed(b"q")), ["q"])


class ParserMouse(unittest.TestCase):
    def setUp(self):
        self.p = _Parser()

    def test_sgr_press_and_release_are_zero_based(self):
        self.assertEqual(self.p.feed(b"\x1b[<0;10;20M"), [MouseEvent(9, 19, 0, "press")])
        self.assertEqual(self.p.feed(b"\x1b[<0;10;20m"), [MouseEvent(9, 19, 0, "release")])

    def test_sgr_origin(self):
        self.assertEqual(self.p.feed(b"\x1b[<0;1;1M"), [MouseEvent(0, 0, 0, "press")])

    def test_middle_and_right_buttons(self):
        self.assertEqual(self.p.feed(b"\x1b[<1;5;6M"), [MouseEvent(4, 5, 1, "press")])
        self.assertEqual(self.p.feed(b"\x1b[<2;5;6m"), [MouseEvent(4, 5, 2, "release")])

    def test_wheel_up_and_down(self):
        self.assertEqual(self.p.feed(b"\x1b[<64;5;6M"), [MouseEvent(4, 5, 3, "wheel")])
        self.assertEqual(self.p.feed(b"\x1b[<65;5;6M"), [MouseEvent(4, 5, 4, "wheel")])

    def test_drag(self):
        self.assertEqual(self.p.feed(b"\x1b[<32;4;5M"), [MouseEvent(3, 4, 0, "drag")])
        self.assertEqual(self.p.feed(b"\x1b[<33;4;5M"), [MouseEvent(3, 4, 1, "drag")])

    def test_malformed_mouse_is_ignored(self):
        self.assertEqual(self.p.feed(b"\x1b[<0;1M"), [])
        self.assertEqual(self.p.feed(b"\x1b[<abc;1;2M"), [])

    def test_private_mode_sequences_ignored(self):
        self.assertEqual(self.p.feed(b"\x1b[?1049h"), [])


class ParserUtf8(unittest.TestCase):
    def setUp(self):
        self.p = _Parser()

    def test_multibyte_char(self):
        self.assertEqual(keys(self.p.feed("中".encode("utf-8"))), ["中"])

    def test_split_at_every_byte_boundary(self):
        data = "中文é".encode("utf-8")
        for cut in range(1, len(data)):
            with self.subTest(cut=cut):
                p = _Parser()
                first = p.feed(data[:cut])
                second = p.feed(data[cut:])
                self.assertEqual(keys(first + second), ["中", "文", "é"])
                self.assertFalse(p.has_pending())

    def test_split_multibyte_inside_a_stream(self):
        data = "a中b".encode("utf-8")
        self.assertEqual(keys(self.p.feed(data[:2])), ["a"])
        self.assertEqual(keys(self.p.feed(data[2:])), ["中", "b"])

    def test_invalid_bytes_do_not_crash(self):
        ev = self.p.feed(b"\xff\xfe")
        self.assertIsInstance(ev, list)


if __name__ == "__main__":
    unittest.main()