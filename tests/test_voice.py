import unittest

from sideband.game import CEIL, NUDGE_S, Flight
from sideband.voice import CommandSpotter


class SpotterTest(unittest.TestCase):
    def test_each_word_fires_once_as_partials_grow(self) -> None:
        spot = CommandSpotter()
        self.assertEqual(spot.partial("go"), [])
        self.assertEqual(spot.partial("go left"), ["left"])
        self.assertEqual(spot.partial("go left"), [])
        self.assertEqual(spot.partial("go left go up"), ["up"])
        self.assertEqual(spot.final("go left go up"), [])

    def test_final_catches_words_partials_missed_and_resets(self) -> None:
        spot = CommandSpotter()
        self.assertEqual(spot.final("go right"), ["right"])
        self.assertEqual(spot.partial("go right"), ["right"])  # a new utterance

    def test_ignores_non_commands(self) -> None:
        self.assertEqual(CommandSpotter().final("[unk] go"), [])


class VoiceFlightTest(unittest.TestCase):
    def test_hovers_without_commands(self) -> None:
        game = Flight(voice=True)
        game.command("stop")
        for _ in range(600):
            game.step(1 / 60)
        self.assertAlmostEqual(game.y, CEIL / 2, places=3)

    def test_nudge_moves_then_holds(self) -> None:
        game = Flight(voice=True)
        game.command("up")
        for _ in range(int(NUDGE_S * 60)):
            game.step(1 / 60)
        risen = game.y - CEIL / 2
        self.assertGreater(risen, 1.0)
        for _ in range(120):
            game.step(1 / 60)
        after = game.y
        for _ in range(60):
            game.step(1 / 60)
        self.assertAlmostEqual(game.y, after, places=2)

    def test_left_and_right(self) -> None:
        game = Flight(voice=True)
        game.command("left")
        for _ in range(60):
            game.step(1 / 60)
        self.assertLess(game.x, -1.0)

    def test_retry_keeps_voice_mode(self) -> None:
        game = Flight(voice=True)
        game.command("down")
        while game.alive:
            game.command("down")
            game.step(1 / 60)
        game.step(1.0)
        game.command("up")
        self.assertTrue(game.alive and game.voice)


if __name__ == "__main__":
    unittest.main()
