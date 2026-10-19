"""The keyboard board: HID edges, Tk dedup, F3, and the stick it feeds."""

import unittest

from sideband.keys import BOARD, MAC_CODES, flush_widget, keyboard_check, ursina_names
from sideband.stage import alloy_image, cloth_image, cloud_image, concrete_image, stick


def _reset() -> None:
    BOARD.held.clear()
    BOARD.pressed.clear()
    BOARD.released.clear()
    BOARD.seen.clear()
    BOARD.last = ""
    BOARD.look = (0.0, 0.0)
    BOARD.debug = False
    BOARD.hid = False
    BOARD.pointer = False
    BOARD.sample = None


class _Widget:
    def __init__(self) -> None:
        self.events: list[tuple[str, str | None]] = []

    def event_generate(self, sequence: str, keysym: str | None = None) -> None:
        self.events.append((sequence, keysym))


class BoardTest(unittest.TestCase):
    def setUp(self) -> None:
        _reset()

    def tearDown(self) -> None:
        _reset()

    def test_mac_codes_cover_the_arcade_keys(self) -> None:
        self.assertEqual(MAC_CODES[13], "w")
        self.assertEqual(MAC_CODES[49], "space")
        self.assertEqual(MAC_CODES[53], "escape")
        self.assertEqual(MAC_CODES[123], "left")
        self.assertEqual(MAC_CODES[99], "f3")

    def test_poll_edges_and_mouse_look(self) -> None:
        BOARD.sample = lambda: ({"w": True, "a": False}, 12.0, -4.0, False)
        BOARD.poll()
        self.assertIn("w", BOARD.pressed)
        self.assertIn("w", BOARD.held)
        self.assertNotIn("a", BOARD.held)
        self.assertEqual(BOARD.look, (12.0, -4.0))
        self.assertIn("mouse", BOARD.last)
        BOARD.end_frame()
        BOARD.poll()
        self.assertNotIn("w", BOARD.pressed)
        self.assertIn("w", BOARD.held)

    def test_observe_suppresses_a_second_edge(self) -> None:
        BOARD.observe("Left Arrow", True)
        self.assertIn("left", BOARD.held)
        self.assertNotIn("left", BOARD.pressed)
        BOARD.sample = lambda: ({"left": True}, 0.0, 0.0, False)
        BOARD.poll()
        self.assertNotIn("left", BOARD.pressed)
        BOARD.end_frame()
        BOARD.poll()
        self.assertNotIn("left", BOARD.pressed)

    def test_f3_toggles_once_while_held(self) -> None:
        down = {"f3": True}

        def sample():
            return ({"f3": down["f3"]}, 0.0, 0.0, False)

        BOARD.sample = sample
        BOARD.poll()
        self.assertTrue(BOARD.debug)
        overlay = BOARD.overlay()
        self.assertIn("f3", overlay)
        self.assertIn("key down f3", overlay)
        BOARD.end_frame()
        BOARD.poll()
        self.assertTrue(BOARD.debug)
        down["f3"] = False
        BOARD.poll()
        self.assertNotIn("f3", BOARD.held)
        down["f3"] = True
        BOARD.poll()
        self.assertFalse(BOARD.debug)
        self.assertEqual(BOARD.overlay(), "")

    def test_flush_delivers_hid_edges_once_and_tracks_holds(self) -> None:
        state = {"space": True, "w": True}

        def sample():
            return (dict(state), 0.0, 0.0, True)

        BOARD.sample = sample
        top, canvas = _Widget(), _Widget()
        keys: set[str] = set()
        flush_widget(top, keys, canvas)
        self.assertIn((" <KeyPress>".strip(), "space"), [(event[0], event[1]) for event in top.events])
        self.assertEqual(top.events[0][0], "<KeyPress>")
        self.assertIn("space", keys)
        self.assertIn("w", keys)
        self.assertTrue(any(event[0] == "<ButtonPress-1>" for event in canvas.events))
        top.events.clear()
        canvas.events.clear()
        flush_widget(top, keys, canvas)
        self.assertEqual(top.events, [])
        self.assertEqual(canvas.events, [])
        self.assertIn("w", keys)
        state["space"] = False
        state["w"] = False
        BOARD.sample = lambda: (dict(state), 0.0, 0.0, False)
        flush_widget(top, keys, canvas)
        self.assertIn((" <KeyRelease>".replace(" ", ""), "space"), [(event[0], event[1]) for event in top.events] or [("miss", None)])
        self.assertTrue(any(event[0] == "<KeyRelease>" and event[1] == "space" for event in top.events))
        self.assertTrue(any(event[0] == "<ButtonRelease-1>" for event in canvas.events))
        self.assertNotIn("w", keys)
        self.assertNotIn("space", keys)

    def test_ursina_names_and_stick(self) -> None:
        self.assertIn("left arrow", ursina_names({"left"}))
        self.assertIn("enter", ursina_names({"return"}))
        self.assertIn("left mouse", ursina_names({"mouse"}))
        BOARD.held.update({"d", "w"})
        self.assertEqual(stick(), (1.0, 1.0))
        BOARD.held.clear()
        BOARD.held.update({"a", "s", "left arrow"})
        self.assertEqual(stick(), (-1.0, -1.0))

    def test_keyboard_check_does_not_fail_here(self) -> None:
        ok, detail, fix = keyboard_check()
        self.assertIsNot(ok, False)
        self.assertTrue(detail)
        self.assertEqual(fix, "")


class ArtTest(unittest.TestCase):
    def test_generated_materials_have_pixels(self) -> None:
        self.assertEqual(concrete_image().size, (128, 128))
        self.assertEqual(cloth_image().size, (64, 64))
        self.assertEqual(alloy_image().size, (128, 64))
        cloud = cloud_image()
        self.assertEqual(cloud.size, (128, 128))
        self.assertEqual(cloud.mode, "RGBA")


if __name__ == "__main__":
    unittest.main()
