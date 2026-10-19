"""The shelf, the scorebook, and the bitmap titles. No window, no pendant."""

import json
import tempfile
import unittest
from pathlib import Path

from sideband.legend import PLAY, legend
from sideband.platform import LIBRARY, SYSTEM, Scorebook, Shelf, VolumeEdge, game, pixels, score_badge, shelf_slots, spoken_aliases


class ShelfTest(unittest.TestCase):
    def test_tap_moves_and_wraps_hold_launches(self) -> None:
        shelf = Shelf(keys=("a", "b", "c"))
        shelf.move(1)
        self.assertEqual(shelf.index, 1)
        shelf.move(1)
        shelf.move(1)
        self.assertEqual(shelf.index, 0)
        self.assertEqual(shelf.activate(), "play:a")

    def test_back_is_the_previous_card_and_closes_settings(self) -> None:
        shelf = Shelf(keys=("a", "b", "c"))
        shelf.move(1)
        self.assertEqual(shelf.back(), "prev")
        self.assertEqual(shelf.index, 0)
        self.assertEqual(shelf.back(), "prev")
        self.assertEqual(shelf.index, 2)  # wraps, it does not open settings
        shelf.open_page("system")
        self.assertEqual(shelf.activate(), f"sys:{SYSTEM[0][0]}")
        shelf.move(1)
        self.assertEqual(shelf.sub, 1)
        self.assertEqual(shelf.back(), "games")
        self.assertEqual(shelf.page, "games")

    def test_settings_then_controllers_then_back(self) -> None:
        shelf = Shelf()
        shelf.open_page("controllers")
        shelf.move(2, page_count=4)
        self.assertEqual(shelf.sub, 2)
        self.assertEqual(shelf.activate(), "pad:2")
        self.assertEqual(shelf.back(), "system")
        self.assertEqual(shelf.back(), "games")

    def test_cards_center_on_the_focused_one(self) -> None:
        slots = shelf_slots(4, 0, 1000, card_w=300, gap=20)
        self.assertAlmostEqual(slots[0][0], 500)
        self.assertGreater(slots[0][1], slots[1][1])
        slots = shelf_slots(4, 2, 1000, card_w=300, gap=20)
        self.assertAlmostEqual(slots[2][0], 500)
        self.assertGreater(slots[2][1], slots[0][1])


class ScoreTest(unittest.TestCase):
    def test_legacy_file_and_recent_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "arcade.json"
            path.write_text(json.dumps({"fighter": 12, "corn": 9.5}), encoding="utf-8")
            book = Scorebook(path)
            self.assertEqual(book.best("fighter"), 12)
            self.assertFalse(book.record("fighter", 3))
            self.assertTrue(book.record("fighter", 40))
            book.touch("dash")
            book.touch("beat")
            self.assertEqual(book.recent[:2], ["beat", "dash"])
            self.assertEqual(book.stats("beat")["plays"], 1)
            again = Scorebook(path)
            self.assertEqual(again.best("fighter"), 40)
            self.assertEqual(again.recent[0], "beat")
            self.assertTrue(again.record("corn", 4, lower_is_better=True))
            self.assertFalse(again.record("corn", 8, lower_is_better=True))

    def test_badge(self) -> None:
        corn = game("corn")
        dash = game("dash")
        assert corn is not None and dash is not None
        self.assertEqual(score_badge(dash, None), "NEW")
        self.assertEqual(score_badge(dash, 1200), "BEST 1,200")
        self.assertEqual(score_badge(corn, 12.34), "BEST 12.3s")


class LibraryTest(unittest.TestCase):
    def test_every_game_has_a_legend_art_and_a_spoken_name(self) -> None:
        names = spoken_aliases()
        for spec in LIBRARY:
            self.assertIn(spec.key, PLAY)
            self.assertIn(("hold", "PAUSE"), legend(spec.key, device="omi"))
            self.assertEqual(legend(spec.key, "ready", device="omi")[1], ("double", "ARCADE"))
            self.assertEqual(legend(spec.key, "ready")[0], ("enter", "START"))
            width, _height, pts = pixels(spec.title)
            self.assertGreater(width, 0)
            self.assertGreater(len(pts), 0)
            self.assertIn(spec.key, names.values())
        self.assertGreaterEqual(sum(1 for spec in LIBRARY if spec.stock), 4)
        self.assertEqual(len(SYSTEM), 7)
        from sideband.arcade import GAMES, ArcadeWindow

        self.assertGreaterEqual(len(GAMES), 10)
        self.assertTrue(callable(ArcadeWindow))


class VolumeTest(unittest.TestCase):
    def test_shout_is_a_rising_edge(self) -> None:
        edge = VolumeEdge(0.6)
        self.assertFalse(edge.rising(0.2))
        self.assertTrue(edge.rising(0.8))
        self.assertFalse(edge.rising(0.95))
        self.assertFalse(edge.rising(0.1))
        self.assertTrue(edge.rising(0.7))


if __name__ == "__main__":
    unittest.main()
