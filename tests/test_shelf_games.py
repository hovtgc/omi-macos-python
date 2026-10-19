"""Beat Tap, Quickdraw, Omi Dash and Simon. Driven with taps only, no window."""

import unittest

from sideband.shelf_games import BeatTap, Dash, Quickdraw, Simon, make


class BeatTest(unittest.TestCase):
    def test_an_on_time_tap_scores_and_a_miss_counts(self) -> None:
        game = BeatTap(seed=1)
        first = game.notes[0].t
        while game.clock < first - 0.02 and not game.over:
            game.step(0.01, 0)
        game.step(0.02, 1)
        self.assertGreater(game.score, 0)
        self.assertEqual(game.combo, 1)
        # Let every remaining note sail past with no taps.
        for _ in range(400):
            if game.over:
                break
            game.step(0.05, 0)
        self.assertTrue(game.over)
        self.assertGreaterEqual(game.misses, game.max_misses)

    def test_an_early_tap_does_not_invent_points(self) -> None:
        game = BeatTap(seed=2)
        game.step(0.05, 1)
        self.assertEqual(game.score, 0)


class DrawTest(unittest.TestCase):
    def test_waiting_tap_is_a_foul_and_draw_tap_scores(self) -> None:
        foul = Quickdraw(seed=1)
        foul.step(0.05, 1)
        self.assertEqual(foul.fouls, 1)
        self.assertNotEqual(foul.phase, "draw")
        game = Quickdraw(seed=1)
        for _ in range(80):
            if game.phase == "draw":
                break
            game.step(0.05, 0)
        self.assertEqual(game.phase, "draw")
        game.step(0.05, 1)
        self.assertGreater(game.score, 0)
        self.assertIsNotNone(game.last_ms)
        self.assertEqual(game.round, 1)

    def test_five_rounds_end_it(self) -> None:
        game = Quickdraw(seed=3, rounds=2)
        for _ in range(2):
            for _step in range(80):
                if game.phase == "draw":
                    break
                game.step(0.05, 0)
            game.step(0.04, 1)
            if game.phase == "gap":
                while game.phase == "gap":
                    game.step(0.1, 0)
        self.assertTrue(game.over)


class DashTest(unittest.TestCase):
    def test_jump_clears_a_low_box_and_standing_still_does_not(self) -> None:
        jumped = Dash(seed=1)
        jumped.obstacles = [[jumped.travel + Dash.RUN_X + 2.0, 0.7, 0.8]]
        jumped.next_x = 10_000
        jumped.step(1 / 60, 1)
        for _ in range(50):
            jumped.step(1 / 60, 0)
        self.assertFalse(jumped.over)
        self.assertGreater(jumped.score, 0)

        crashed = Dash(seed=1)
        crashed.obstacles = [[crashed.travel + Dash.RUN_X + 0.3, 0.7, 0.8]]
        crashed.next_x = 10_000
        for _ in range(20):
            crashed.step(1 / 60, 0)
        self.assertTrue(crashed.over)

    def test_no_double_jump(self) -> None:
        game = Dash(seed=1)
        game.obstacles.clear()
        game.next_x = 10_000
        game.step(1 / 60, 1)
        air = game.y
        game.step(1 / 60, 1)
        self.assertGreater(game.y, air)
        self.assertLess(game.vy, Dash.JUMP)


class SimonTest(unittest.TestCase):
    def test_repeating_the_pattern_grows_it_and_a_wrong_pad_ends_it(self) -> None:
        game = Simon(seed=1)
        game.pattern = [0, 1]
        for _ in range(200):
            if game.phase == "input":
                break
            game.step(0.05)
        self.assertEqual(game.phase, "input")
        game.press(0)
        game.press(1)
        self.assertEqual(game.score, 1)
        self.assertEqual(game.phase, "success")
        for _ in range(30):
            if game.phase == "show":
                break
            game.step(0.05)
        self.assertEqual(len(game.pattern), 3)

        wrong = Simon(seed=1)
        wrong.pattern = [0]
        for _ in range(80):
            if wrong.phase == "input":
                break
            wrong.step(0.05)
        wrong.press(1)
        self.assertTrue(wrong.over)

    def test_factory_covers_the_four(self) -> None:
        for key in ("beat", "draw", "dash", "simon"):
            game = make(key, 1)
            game.step(0.016) if key == "simon" else game.step(0.016, 0)
            self.assertFalse(game.over)


if __name__ == "__main__":
    unittest.main()
