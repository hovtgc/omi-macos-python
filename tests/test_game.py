import unittest

from sideband.game import CEIL, RETRY_S, Flight


def fly(seed: int, tap_delay: float, seconds: float = 60.0) -> Flight:
    """A bot that aims for the next gap. Taps land `tap_delay` late like the pendant; steering is live."""
    game, t, pending, dt = Flight(seed=seed), 0.0, [], 1 / 60
    game.flap()
    while game.alive and t < seconds:
        ahead = [w for w in game.walls if w[0] > game.z]
        _, hx, hy = ahead[0] if ahead else (0.0, 0.0, CEIL / 2)
        future_y = game.y + game.vy * tap_delay - 4.0 * tap_delay * tap_delay
        if future_y < hy - 0.4 and not pending:
            pending.append(t + tap_delay)
        if pending and t >= pending[0]:
            pending.pop(0)
            game.flap()
        steer = max(-1.0, min(1.0, (hx - game.x) * 1.5 - game.vx * 0.3))
        game.step(dt, steer)
        t += dt
    return game


class FlightTest(unittest.TestCase):
    def test_waits_for_first_tap(self) -> None:
        game = Flight()
        game.step(5.0)
        self.assertTrue(game.alive)
        self.assertEqual(game.z, 0.0)

    def test_falling_ends_the_game(self) -> None:
        game = Flight()
        game.flap()
        for _ in range(600):
            game.step(1 / 60)
        self.assertFalse(game.alive)

    def test_walls_stay_ahead_and_reachable(self) -> None:
        game = Flight(seed=3)
        self.assertGreater(len(game.walls), 3)
        for (z0, x0, y0), (z1, x1, y1) in zip(game.walls, game.walls[1:]):
            self.assertLess(z0, z1)
            self.assertLessEqual(abs(x1 - x0), 3.0 + 1e-9)
            self.assertLessEqual(abs(y1 - y0), 1.8 + 1e-9)

    def test_steering_is_bounded(self) -> None:
        game = Flight()
        game.flap()
        for _ in range(120):
            game.flap()
            game.step(1 / 60, steer=5.0)
        self.assertLess(game.x, 6.0)

    def test_late_tap_does_not_restart(self) -> None:
        game = Flight()
        game.flap()
        while game.alive:
            game.step(1 / 60)
        game.flap()
        self.assertFalse(game.alive)
        game.step(RETRY_S)
        game.flap()
        self.assertTrue(game.alive)
        self.assertEqual(game.score, 0)

    def test_playable_with_pendant_latency(self) -> None:
        for seed in range(4):
            game = fly(seed, tap_delay=0.33)
            self.assertTrue(game.alive, f"seed {seed} crashed at score {game.score}")
            self.assertGreater(game.score, 20)


if __name__ == "__main__":
    unittest.main()
