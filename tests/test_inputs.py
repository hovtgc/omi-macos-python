import tempfile
import unittest
from pathlib import Path

from sideband.inputs import (
    ACTIONS,
    TRIPLE_WINDOW_S,
    ButtonDecoder,
    InputMap,
    Mapping,
    action_command,
    button_code,
    button_kind,
    installed_apps,
    keystroke_script,
)


class ButtonTest(unittest.TestCase):
    def test_firmware_codes(self) -> None:
        # Seen on an Omi CV 1: 8-byte little-endian codes.
        self.assertEqual(button_code(bytes.fromhex("0100000000000000")), 1)
        self.assertEqual(button_kind(1), "single")
        self.assertEqual(button_kind(2), "double")
        self.assertEqual(button_kind(5), "release")
        self.assertEqual(button_kind(9), "code-9")
        self.assertIsNone(button_code(b""))


class DecoderTest(unittest.TestCase):
    def run_codes(self, events: list[tuple[float, int]], triples: bool = True, until: float = 5.0) -> list[str]:
        decoder, out = ButtonDecoder(triples=triples), []
        for at, code in events:
            out += decoder.feed(code, at)
        out += decoder.poll(until)
        return out

    def test_single_is_immediate_and_its_release_is_swallowed(self) -> None:
        decoder = ButtonDecoder()
        self.assertEqual(decoder.feed(1, 0.30), ["single"])
        self.assertEqual(decoder.feed(5, 0.34), [])

    def test_double_waits_for_a_possible_third_tap(self) -> None:
        decoder = ButtonDecoder()
        self.assertEqual(decoder.feed(2, 0.40), [])
        self.assertEqual(decoder.feed(5, 0.60), [])
        self.assertEqual(decoder.poll(0.40 + TRIPLE_WINDOW_S / 2), [])
        self.assertEqual(decoder.poll(0.41 + TRIPLE_WINDOW_S), ["double"])

    def test_double_is_immediate_without_triples(self) -> None:
        self.assertEqual(self.run_codes([(0.4, 2), (0.6, 5)], triples=False), ["double"])

    def test_triple_is_double_then_single(self) -> None:
        self.assertEqual(self.run_codes([(0.40, 2), (0.60, 5), (0.95, 1), (0.99, 5)]), ["triple"])

    def test_late_single_after_double_is_two_gestures(self) -> None:
        self.assertEqual(self.run_codes([(0.4, 2), (0.6, 5), (2.0, 1), (2.04, 5)]), ["double", "single"])

    def test_hold_is_a_lone_release(self) -> None:
        self.assertEqual(self.run_codes([(1.5, 5)]), ["hold"])
        self.assertEqual(self.run_codes([(0.3, 1), (0.34, 5), (3.0, 5)]), ["single", "hold"])


class ActionTest(unittest.TestCase):
    def test_open_app(self) -> None:
        self.assertEqual(action_command("open app", " Spotify ", "single"), ["open", "-a", "Spotify"])
        self.assertIsNone(action_command("open app", "", "single"))

    def test_notify_quotes_text(self) -> None:
        cmd = action_command("notify", 'say "hi"', "double")
        self.assertEqual(cmd[:2], ["osascript", "-e"])
        self.assertIn('\\"hi\\"', cmd[2])

    def test_keystrokes(self) -> None:
        self.assertEqual(
            keystroke_script("cmd+shift+4"),
            'tell application "System Events" to keystroke "4" using {command down, shift down}',
        )
        self.assertEqual(keystroke_script("right"), 'tell application "System Events" to key code 124')
        self.assertIsNone(keystroke_script("cmd"))
        self.assertIsNone(keystroke_script("hyper+a"))
        self.assertIsNone(keystroke_script(""))

    def test_every_action_is_handled(self) -> None:
        for action in ACTIONS:
            action_command(action, "x", "single")
        self.assertIsNone(action_command("microphone", "", "single"))
        self.assertIsNone(action_command("none", "", "single"))

    def test_installed_apps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Zed.app").mkdir()
            (root / "Utilities" / "Terminal.app").mkdir(parents=True)
            (root / "notes.txt").write_text("")
            self.assertEqual(installed_apps([root, root / "missing"]), ["Terminal", "Zed"])


class MapTest(unittest.TestCase):
    def test_round_trip_and_bad_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "map.json"
            self.assertEqual(InputMap.load(path).gestures["single"].action, "notify")
            found = InputMap()
            found.gestures["double"] = Mapping("open app", "Spotify")
            found.save(path)
            self.assertEqual(InputMap.load(path).gestures["double"], Mapping("open app", "Spotify"))
            path.write_text('{"single": {"action": "rm -rf"}}')
            self.assertEqual(InputMap.load(path).gestures["single"].action, "none")


if __name__ == "__main__":
    unittest.main()
