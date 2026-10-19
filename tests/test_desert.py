"""Desert 91, headless: the raycaster, the fight, and the cover files. No window."""

import math
import unittest

from sideband.covers import cover_path, missing_covers
from sideband.desert import Orders, Raid, _actor, cast, cell_at, project, tone_wav
from sideband.legend import legend


class RayTest(unittest.TestCase):
    def test_east_ray_hits_the_far_berm(self) -> None:
        dist, cell, _side = cast(Raid().grid, 2.5, 2.5, 0.0)
        self.assertEqual(cell, "B")
        self.assertAlmostEqual(dist, 8.5, delta=0.08)

    def test_a_point_ahead_projects_in_front(self) -> None:
        side, depth = project(4.0, 0.0, 0.0)
        self.assertAlmostEqual(depth, 4.0)
        self.assertAlmostEqual(side, 0.0)
        side, depth = project(0.0, 3.0, 0.0)
        self.assertGreater(side, 0)
        self.assertAlmostEqual(depth, 0.0, places=5)

    def test_everyone_stands_on_open_sand(self) -> None:
        raid = Raid()
        self.assertEqual(cell_at(raid.grid, raid.x, raid.y), ".")
        for actor in raid.actors:
            self.assertEqual(cell_at(raid.grid, actor.x, actor.y), ".", actor.kind)
        for item in raid.pickups:
            self.assertEqual(cell_at(raid.grid, item.x, item.y), ".")


class FightTest(unittest.TestCase):
    def test_a_berm_stops_the_player(self) -> None:
        raid = Raid()
        raid.angle = math.pi
        for actor in raid.actors:
            actor.cooldown = 30
        for _ in range(40):
            raid.step(0.05, Orders(forward=1))
        self.assertGreater(raid.x, 1.0)
        self.assertLess(raid.x, 2.5)

    def test_a_shot_drops_the_soldier_in_front(self) -> None:
        raid = self._lane()
        soldier = raid.actors[0]
        raid.step(0.05, Orders(fire=True))
        self.assertEqual(raid.gun.mag, 29)
        self.assertLess(soldier.hp, soldier.max_hp)
        raid.gun.cooldown = 0
        raid.step(0.05, Orders(fire=True))
        self.assertFalse(soldier.alive)
        self.assertEqual(raid.score, 300)  # the kill, then the mission clear
        self.assertGreater(raid.banner_t, 0)
        self.assertTrue(raid.puffs)

    def test_a_berm_stops_the_bullet(self) -> None:
        raid = self._lane(8.5)
        rows = [list(row) for row in raid.grid]
        rows[2][4] = "#"
        raid.grid = ["".join(row) for row in rows]
        raid.step(0.05, Orders(fire=True))
        self.assertEqual(raid.actors[0].hp, raid.actors[0].max_hp)
        self.assertEqual(raid.gun.mag, 29)

    def test_reload_fills_the_magazine_from_the_reserve(self) -> None:
        raid = self._lane()
        gun = raid.gun
        gun.mag, gun.reserve = 0, 40
        raid.step(0.02, Orders(reload=True))
        self.assertGreater(raid.reload_t, 0)
        self.assertEqual(gun.mag, 0)
        raid.step(1.3, Orders())
        self.assertEqual(gun.mag, 30)
        self.assertEqual(gun.reserve, 10)

    def test_the_pistol_is_a_second_weapon(self) -> None:
        raid = self._lane()
        raid.step(0.05, Orders(weapon="pistol", fire=True))
        self.assertEqual(raid.slot, "pistol")
        self.assertEqual(raid.gun.name, "PISTOL")
        self.assertEqual(raid.gun.mag, 14)

    def test_an_enemy_with_a_clear_line_hits_back(self) -> None:
        raid = self._lane(5.5)
        raid.actors[0].cooldown = 0
        raid.step(0.05, Orders())
        self.assertLess(raid.health, 100)

    def test_pickups_restore_health_and_ammo(self) -> None:
        raid = self._lane()
        raid.x, raid.y, raid.health = 9.5, 2.5, 40
        raid.gun.reserve = 10
        raid.step(0.05, Orders())
        self.assertEqual(raid.health, 75)
        self.assertTrue(raid.pickups[0].taken)
        raid.x, raid.y = 3.5, 7.5
        raid.step(0.05, Orders())
        self.assertGreater(raid.gun.reserve, 10)

    def test_three_missions_then_the_run_is_won(self) -> None:
        raid = Raid()
        for actor in raid.actors:
            actor.cooldown = 30
        for wave in (1, 2, 3):
            self.assertEqual(raid.wave, wave)
            for actor in raid.actors:
                if actor.wave == wave:
                    actor.alive = False
            raid.step(0.05, Orders())
            self.assertGreater(raid.banner_t, 0)
            raid.step(1.2, Orders())
        self.assertTrue(raid.won)
        self.assertTrue(raid.over)
        self.assertGreaterEqual(raid.score, 600)

    def test_zero_health_ends_it(self) -> None:
        raid = self._lane(4.5)
        raid.health = 8
        raid.actors[0].cooldown = 0
        raid.step(0.05, Orders())
        self.assertTrue(raid.over)
        self.assertFalse(raid.won)
        self.assertEqual(raid.health, 0)

    def _lane(self, soldier_x: float = 6.5) -> Raid:
        raid = Raid()
        raid.x, raid.y, raid.angle = 2.5, 2.5, 0.0
        raid.actors = [_actor(soldier_x, 2.5, "soldier", 1)]
        return raid


class SoundTest(unittest.TestCase):
    def test_a_shot_is_a_generated_wave(self) -> None:
        data = tone_wav(140, 40, noise=0.5)
        self.assertTrue(data.startswith(b"RIFF"))
        self.assertGreater(len(data), 100)


class CoverTest(unittest.TestCase):
    def test_bundled_covers_and_the_ones_still_missing(self) -> None:
        for key in ("desert", "fighter", "flap", "corn", "dodger", "catch", "voice"):
            path = cover_path(key)
            self.assertIsNotNone(path)
            assert path is not None
            self.assertGreater(path.stat().st_size, 10_000)
        self.assertEqual(missing_covers(), ("beat", "draw", "dash", "simon"))

    def test_the_keyboard_legend_names_the_mouse_and_reload(self) -> None:
        shown = legend("desert", device="keys")
        self.assertIn(("mouse", "LOOK"), shown)
        self.assertIn(("rkey", "RELOAD"), shown)
        self.assertIn(("hold", "PAUSE"), legend("desert", device="omi"))

    def test_the_window_class_imports(self) -> None:
        from sideband.desert_view import DesertWindow

        self.assertTrue(callable(DesertWindow))


if __name__ == "__main__":
    unittest.main()
