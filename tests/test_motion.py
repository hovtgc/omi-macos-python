import math
import struct
import unittest

from sideband.motion import ACCEL_LSB, G, Motion, ShakeDetector, Tilt2D, parse_motion


def rotate(v: tuple[float, float, float], axis: str, deg: float) -> tuple[float, float, float]:
    r = math.radians(deg)
    c, n = math.cos(r), math.sin(r)
    x, y, z = v
    if axis == "x":
        return x, y * c - z * n, y * n + z * c
    if axis == "y":
        return x * c + z * n, y, -x * n + z * c
    return x * c - y * n, x * n + y * c, z


def still(g: tuple[float, float, float]) -> Motion:
    return Motion(g[0], g[1], g[2], 0.0, 0.0, 0.0)


FLAT = (0.0, 0.0, -G)  # lying face down, as measured on the pendant
HANGING = (0.0, -G, 0.0)  # hanging on its cord


class ParseTest(unittest.TestCase):
    def test_upstream_sensor_values(self) -> None:
        # Six Zephyr sensor_value pairs: 9.5 m/s² is (9, 500000).
        raw = struct.pack("<12i", 0, 0, 0, -250000, 9, 500000, 1, 0, 0, 0, -2, -500000)
        m = parse_motion(raw)
        self.assertAlmostEqual(m.az, 9.5)
        self.assertAlmostEqual(m.ay, -0.25)
        self.assertAlmostEqual(m.gx, 1.0)
        self.assertAlmostEqual(m.gz, -2.5)

    def test_compact_int16(self) -> None:
        one_g = round(G / ACCEL_LSB)
        m = parse_motion(struct.pack("<6h", 0, 0, one_g, 0, 0, 0))
        self.assertAlmostEqual(m.az, G, places=2)

    def test_unknown_length(self) -> None:
        self.assertIsNone(parse_motion(b"\x00" * 7))


class TiltTest(unittest.TestCase):
    def test_zero_at_rest_and_proportional(self) -> None:
        tilt = Tilt2D(smooth=1.0)
        self.assertEqual(tilt.update(still(FLAT)), (0.0, 0.0))
        x, y = tilt.update(still(rotate(FLAT, "y", 12.5)))
        self.assertAlmostEqual(abs(x) + abs(y), 0.5, places=2)  # 12.5 of 25 degrees, on one axis

    def test_held_in_hand_needs_no_calibration(self) -> None:
        """Right side down steers right and far edge down steers forward, for the natural grips."""
        grips = {
            # grip: (resting reading, roll-right as (axis, degrees), tilt-forward as (axis, degrees))
            # Readings point "up". Right edge down: up leans to -x (face up). Far edge down: up leans to -y.
            "flat, face up": ((0.0, 0.0, G), ("y", -15), ("x", 15)),
            # Face down the pendant's x and z point the other way, so the same hand motions mirror.
            "flat, face down": ((0.0, 0.0, -G), ("y", -15), ("x", -15)),
            # Upright facing you: y up, z toward you; rolling clockwise leans up toward -x.
            "upright, facing you": ((0.0, G, 0.0), ("z", 15), ("x", 15)),
        }
        for name, (rest, (roll_axis, roll), (pitch_axis, pitch)) in grips.items():
            tilt = Tilt2D(smooth=1.0)
            tilt.update(still(rest))
            x, y = tilt.update(still(rotate(rest, roll_axis, roll)))
            self.assertAlmostEqual(x, 0.6, places=2, msg=f"{name}: right")
            self.assertAlmostEqual(y, 0.0, places=2, msg=f"{name}: right")
            x, y = tilt.update(still(rotate(rest, pitch_axis, pitch)))
            self.assertAlmostEqual(y, 0.6, places=2, msg=f"{name}: forward")
            self.assertAlmostEqual(x, 0.0, places=2, msg=f"{name}: forward")

    def test_wizard_orients_both_axes(self) -> None:
        for rest, right_axis, forward_axis in ((FLAT, "y", "x"), (HANGING, "z", "x")):
            tilt = Tilt2D(smooth=1.0)
            tilt.learn("rest", still(rest))
            self.assertFalse(tilt.learn("right", still(rotate(rest, right_axis, 3))))  # too small to read
            self.assertTrue(tilt.learn("right", still(rotate(rest, right_axis, 20))))
            self.assertTrue(tilt.learn("forward", still(rotate(rest, forward_axis, 20))))
            x, y = tilt.update(still(rotate(rest, right_axis, 15)))
            self.assertAlmostEqual(x, 0.6, places=2)
            self.assertAlmostEqual(y, 0.0, places=2)
            x, y = tilt.update(still(rotate(rest, forward_axis, -15)))
            self.assertAlmostEqual(y, -0.6, places=2)
            self.assertAlmostEqual(x, 0.0, places=2)

    def test_settings_round_trip(self) -> None:
        tilt = Tilt2D(swap=True, invert_y=True)
        other = Tilt2D()
        other.load(tilt.settings())
        self.assertEqual(other.settings(), {"swap": True, "invert_x": False, "invert_y": True})

    def test_smoothing(self) -> None:
        tilt = Tilt2D(smooth=0.5)
        tilt.calibrate(still(FLAT))
        tilt.update(still(rotate(FLAT, "y", 25)))
        self.assertAlmostEqual(abs(tilt.x) + abs(tilt.y), 0.5, places=2)


class ShakeTest(unittest.TestCase):
    def test_jolt_and_twist_with_cooldown(self) -> None:
        shake = ShakeDetector()
        self.assertFalse(shake.feed(still(FLAT), 0.0))
        self.assertTrue(shake.feed(Motion(0, 0, -G - 9, 0, 0, 0), 1.0))
        self.assertFalse(shake.feed(Motion(0, 0, -G - 9, 0, 0, 0), 1.2))  # cooling down
        self.assertTrue(shake.feed(Motion(0, 0, -G, 7.0, 0, 0), 2.0))



class SteadyTest(unittest.TestCase):
    def test_median_ignores_a_button_jolt(self) -> None:
        from sideband.motion import Motion, steady

        held = [Motion(0.0, 0.0, 9.8, 0.0, 0.0, 0.0)] * 20
        jolt = [Motion(6.0, -5.0, 3.0, 4.0, 4.0, 4.0)] * 4
        self.assertEqual(steady(held[:10] + jolt + held[10:]), held[0])
        self.assertIsNone(steady([]))

    def test_degrees_from_rest(self) -> None:
        from sideband.motion import Motion, Tilt2D

        tilt = Tilt2D()
        flat = Motion(0.0, 0.0, 9.8, 0.0, 0.0, 0.0)
        self.assertIsNone(tilt.degrees_from_rest(flat))
        tilt.calibrate(flat)
        self.assertAlmostEqual(tilt.degrees_from_rest(flat), 0.0, places=3)
        tipped = Motion(9.8 * math.sin(math.radians(10)), 0.0, 9.8 * math.cos(math.radians(10)), 0.0, 0.0, 0.0)
        self.assertAlmostEqual(tilt.degrees_from_rest(tipped), 10.0, places=3)


class ShakeGateTest(unittest.TestCase):
    def test_a_press_is_not_a_shake(self) -> None:
        from sideband.motion import ShakeGate

        gate = ShakeGate(wait_s=0.65)
        gate.shake(10.0)
        gate.button(10.3)  # the tap's code arrives: that jolt was the press
        self.assertFalse(gate.due(11.0))

    def test_a_real_shake_fires_once_after_the_wait(self) -> None:
        from sideband.motion import ShakeGate

        gate = ShakeGate(wait_s=0.65)
        gate.shake(10.0)
        self.assertFalse(gate.due(10.3))
        self.assertTrue(gate.due(10.7))
        self.assertFalse(gate.due(10.8))
        gate.button(11.5)  # a later press does not matter
        gate.shake(12.0)
        gate.button(13.0)  # too late to be this shake's press
        self.assertTrue(gate.due(13.1))

if __name__ == "__main__":
    unittest.main()
