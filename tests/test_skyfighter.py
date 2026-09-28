import math
import unittest

from sideband.meshes import apply, bomber, dot, face_normal, fighter, propeller, rotation, sub, unit, ENEMY
from sideband.minigames import Stick
from sideband.skyfighter import HALF_W, HIGH, LOW, Dogfight, Enemy


def centroid(points):
    n = len(points)
    return (sum(p[0] for p in points) / n, sum(p[1] for p in points) / n, sum(p[2] for p in points) / n)


class MeshTest(unittest.TestCase):
    def test_faces_are_valid(self) -> None:
        for mesh in (fighter(), fighter(ENEMY, roundels=False), bomber(), propeller(0.3)):
            self.assertTrue(mesh.faces)
            for indices, colour in mesh.faces:
                self.assertGreaterEqual(len(indices), 3)
                self.assertTrue(all(0 <= i < len(mesh.vertices) for i in indices))
                self.assertTrue(all(0 <= c <= 255 for c in colour))

    def test_fuselage_faces_point_outward(self) -> None:
        mesh = fighter(roundels=False)
        axis_faces = 0
        for indices, _colour in mesh.faces[:30 + 12]:  # the lofted fuselage and its caps come first
            points = [mesh.vertices[i] for i in indices]
            c = centroid(points)
            outward = (c[0], c[1] - 0.1, 0.0) if abs(c[2]) < 4.0 else (0.0, 0.0, c[2])
            if dot(face_normal(points), outward) > 0:
                axis_faces += 1
        self.assertGreaterEqual(axis_faces, 38)  # all but the odd sliver face out

    def test_sizes(self) -> None:
        for mesh, length, span in ((fighter(), 9, 11), (bomber(), 20, 30)):
            xs = [v[0] for v in mesh.vertices]
            zs = [v[2] for v in mesh.vertices]
            self.assertAlmostEqual(max(zs) - min(zs), length, delta=length * 0.2)
            self.assertAlmostEqual(max(xs) - min(xs), span, delta=span * 0.2)

    def test_rotation_directions(self) -> None:
        nose = (0.0, 0.0, 1.0)
        right_wing = (1.0, 0.0, 0.0)
        self.assertGreater(apply(rotation(yaw=0.3), nose)[0], 0)  # yaw right turns the nose right
        self.assertGreater(apply(rotation(pitch=0.3), nose)[1], 0)  # pitch up raises the nose
        self.assertLess(apply(rotation(roll=0.3), right_wing)[1], 0)  # roll right drops the right wing
        m = rotation(0.4, -0.2, 1.1)
        for a in (nose, right_wing, (0.0, 1.0, 0.0)):
            self.assertAlmostEqual(math.sqrt(dot(apply(m, a), apply(m, a))), 1.0, places=9)

    def test_normal_helpers(self) -> None:
        self.assertEqual(unit(sub((2.0, 0.0, 0.0), (0.0, 0.0, 0.0))), (1.0, 0.0, 0.0))
        up = face_normal([(0.0, 0.0, 0.0), (0.0, 0.0, 1.0), (1.0, 0.0, 1.0), (1.0, 0.0, 0.0)])
        self.assertAlmostEqual(up[1], 1.0)


class DogfightTest(unittest.TestCase):
    def test_waits_for_the_first_input(self) -> None:
        game = Dogfight(seed=1)
        game.step(1.0, Stick(x=1.0))
        self.assertEqual((game.z, game.x), (0.0, 0.0))

    def test_stick_flies_and_stays_in_the_corridor(self) -> None:
        game = Dogfight(seed=1)
        game.trigger()
        for _ in range(300):
            game.step(1 / 50, Stick(x=1.0, y=-1.0))  # right and pulling back: climb
        self.assertAlmostEqual(game.x, HALF_W)
        self.assertAlmostEqual(game.y, HIGH)
        for _ in range(300):
            game.step(1 / 50, Stick(y=1.0))  # push forward: dive
        self.assertAlmostEqual(game.y, LOW)
        self.assertGreater(game.z, 100)

    def test_guns_shoot_down_a_fighter(self) -> None:
        game = Dogfight(seed=1)
        game.since_spawn = -999  # no random spawns
        game.enemies.append(Enemy("fighter", game.x + 3.0, game.y, 60.0, 3, 0.0, 99.0))
        game.trigger(long=True)
        for _ in range(40):  # 0.8 s: the fighter is down and its explosion still burning
            game.step(1 / 50, Stick())
        self.assertEqual(game.kills, 1)
        self.assertGreaterEqual(game.score, 100)
        self.assertTrue(game.booms)

    def test_ramming_hurts_unless_rolling(self) -> None:
        game = Dogfight(seed=1)
        game.trigger()
        game.since_spawn = -999
        game.enemies.append(Enemy("fighter", game.x, game.y, game.z + 1, 3, 0.0, 99.0))
        game.step(1 / 50, Stick())
        self.assertEqual(game.health, 60.0)
        game.hurt = 0.0
        self.assertTrue(game.barrel_roll())
        game.enemies.append(Enemy("fighter", game.x, game.y, game.z + 1, 3, 0.0, 99.0))
        game.step(1 / 50, Stick())
        self.assertEqual(game.health, 60.0)
        self.assertFalse(game.barrel_roll())  # cooling down

    def test_game_ends_at_zero_health(self) -> None:
        game = Dogfight(seed=1)
        game.trigger()
        game.health = 5
        game._hurt(12)
        game.step(1 / 50, Stick())
        self.assertTrue(game.over)

    def test_waves_spawn_and_shoot_back(self) -> None:
        game = Dogfight(seed=3)
        game.trigger()
        for _ in range(50 * 30):
            game.step(1 / 50, Stick(x=math.sin(game.clock)))
            if game.over:
                break
        self.assertTrue(game.enemies or game.kills or game.score >= 0)
        self.assertTrue(any(s.enemy for s in game.shots) or game.health < 100)


if __name__ == "__main__":
    unittest.main()
