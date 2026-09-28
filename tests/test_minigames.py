import random
import unittest
from collections import deque

from sideband.minigames import (
    WALL_E,
    WALL_N,
    WALL_S,
    WALL_W,
    Catch,
    MarbleMaze,
    StarDodger,
    Stick,
    make_maze,
)


def reachable(walls: list[list[int]]) -> int:
    seen, todo = {(0, 0)}, deque([(0, 0)])
    moves = ((0, -1, WALL_N), (1, 0, WALL_E), (0, 1, WALL_S), (-1, 0, WALL_W))
    while todo:
        x, y = todo.popleft()
        for dx, dy, wall in moves:
            if not walls[y][x] & wall and (x + dx, y + dy) not in seen:
                seen.add((x + dx, y + dy))
                todo.append((x + dx, y + dy))
    return len(seen)


class MazeTest(unittest.TestCase):
    def test_every_cell_reachable_and_walls_agree(self) -> None:
        walls = make_maze(9, 6, random.Random(4))
        self.assertEqual(reachable(walls), 9 * 6)
        for y in range(6):
            for x in range(8):
                self.assertEqual(bool(walls[y][x] & WALL_E), bool(walls[y][x + 1] & WALL_W))

    def test_marble_stays_inside_walls(self) -> None:
        game = MarbleMaze(seed=2)
        for i in range(2000):
            game.step(1 / 60, Stick(x=1.0 if (i // 90) % 2 else -1.0, y=-1.0 if (i // 150) % 2 else 1.0))
            self.assertTrue(0 < game.x < game.cols and 0 < game.y < game.rows)

    def test_marble_never_passes_through_a_wall(self) -> None:
        rng = random.Random(9)
        for seed in range(5):
            game = MarbleMaze(seed=seed)
            stick = Stick()
            for i in range(3000):
                if i % 40 == 0:
                    stick = Stick(x=rng.uniform(-1, 1), y=rng.uniform(-1, 1))
                before = (int(game.x), int(game.y))
                game.step(1 / 60, stick)
                after = (int(game.x), int(game.y))
                if game.won:
                    break
                if after != before:
                    # The marble moves along x, then y, so a corner can take it through two cells in a frame.
                    self.assertLessEqual(abs(after[0] - before[0]), 1, f"jumped {before}->{after}")
                    self.assertLessEqual(abs(after[1] - before[1]), 1, f"jumped {before}->{after}")
                    middle = (after[0], before[1])
                    for a, b in ((before, middle), (middle, after)):
                        if a != b:
                            wall = {(1, 0): WALL_E, (-1, 0): WALL_W, (0, 1): WALL_S, (0, -1): WALL_N}[(b[0] - a[0], b[1] - a[1])]
                            self.assertFalse(game.walls[a[1]][a[0]] & wall, f"through a wall {a}->{b}")

    def test_reaching_the_flag_wins_and_a_tap_levels_up(self) -> None:
        game = MarbleMaze(seed=1)
        game.x, game.y = game.goal[0] + 0.5, game.goal[1] + 0.5
        game.step(1 / 60, Stick())
        self.assertTrue(game.won)
        cols = game.cols
        game.step(1 / 60, Stick(taps=1))
        self.assertEqual(game.level, 2)
        self.assertGreater(game.cols, cols)
        self.assertFalse(game.won)

    def test_tap_brakes(self) -> None:
        game = MarbleMaze(seed=3)
        game.vx = 4.0
        game.step(1 / 60, Stick(taps=1))
        self.assertLess(abs(game.vx), 1.0)


class DodgerTest(unittest.TestCase):
    def test_tap_fires_and_bullets_score(self) -> None:
        game = StarDodger(seed=1)
        game.rocks.append([game.x, game.y - 30, 5.0, 0.0])
        game.step(1 / 60, Stick(taps=1))
        self.assertEqual(len(game.bullets), 1)
        for _ in range(30):
            game.step(1 / 60, Stick())
        self.assertGreaterEqual(game.score, 10)

    def test_shake_bombs_three_times(self) -> None:
        game = StarDodger(seed=1)
        for _ in range(4):
            game.rocks.append([50.0, 10.0, 5.0, 0.0])
            game.step(1 / 60, Stick(shake=True))
        self.assertEqual(game.bombs, 0)
        self.assertEqual(len(game.rocks), 1)  # the fourth shake had no bomb left

    def test_three_hits_end_the_game(self) -> None:
        game = StarDodger(seed=1)
        for _ in range(3):
            game.hurt_s = 0.0
            game.rocks.append([game.x, game.y, 5.0, 0.0])
            game.step(1 / 60, Stick())
        self.assertTrue(game.over)

    def test_ship_stays_in_its_zone(self) -> None:
        game = StarDodger(seed=1)
        for _ in range(600):
            game.step(1 / 60, Stick(x=1.0, y=1.0))
        self.assertLessEqual(game.x, 100.0)
        self.assertGreaterEqual(game.y, 140.0 * 0.45)


class CatchTest(unittest.TestCase):
    def test_basket_follows_tilt(self) -> None:
        game = Catch(seed=1)
        for _ in range(60):
            game.step(1 / 60, Stick(x=1.0))
        self.assertGreater(game.basket, 80)

    def test_catch_scores_bomb_ends_misses_end(self) -> None:
        game = Catch(seed=1)
        game.drops = [[game.basket, 91.9, 30.0, 0.0]]
        game.since_drop = -99
        game.step(1 / 60, Stick())
        self.assertEqual(game.score, 1)
        game.drops = [[game.basket, 91.9, 30.0, 1.0]]
        game.step(1 / 60, Stick())
        self.assertTrue(game.over)
        game = Catch(seed=1)
        game.since_drop = -99
        game.drops = [[5.0, 99.9, 30.0, 0.0] for _ in range(3)]
        game.basket = 90.0
        game.step(1 / 60, Stick(x=1.0))
        self.assertTrue(game.over)


class LegendTest(unittest.TestCase):
    def test_same_flow_in_every_game(self) -> None:
        from sideband.legend import PLAY, legend

        for game in PLAY:
            if game == "menu":
                continue
            self.assertEqual(legend(game, "ready"), (("tap", "START"), ("double", "ARCADE"), ("say", "EXIT GAME")))
            self.assertEqual(legend(game, "paused")[1], ("double", "ARCADE"))
            self.assertEqual(legend(game, "over")[0], ("tap", "AGAIN"))
            self.assertIn(("hold", "PAUSE"), legend(game))
            self.assertTrue(any(control == "say" and "EXIT" in label for control, label in legend(game)))

    def test_menu_is_tap_to_talk(self) -> None:
        from sideband.legend import legend

        self.assertEqual(legend("menu")[0], ("tap", "TALK"))
        self.assertNotIn("tilt", [control for control, _ in legend("menu")])
        self.assertIn(("tilt", "STEER · ARROWS"), legend("flap", motion=False))


if __name__ == "__main__":
    unittest.main()
