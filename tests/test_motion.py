import math
import struct
import unittest

from sideband.motion import ACCEL_LSB, G, Motion, Tilt, parse_motion


def tilted(deg: float) -> Motion:
    """Gravity rotated `deg` about the y axis, pendant otherwise still."""
    r = math.radians(deg)
    return Motion(G * math.sin(r), 0.0, G * math.cos(r), 0.0, 0.0, 0.0)


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
    def test_zero_at_rest_and_signed(self) -> None:
        tilt = Tilt(smooth=1.0)
        self.assertAlmostEqual(tilt.update(tilted(0)), 0.0)
        self.assertAlmostEqual(tilt.update(tilted(15)), 0.5, places=3)
        self.assertAlmostEqual(tilt.update(tilted(-60)), -1.0)
        tilt.invert = True
        self.assertAlmostEqual(tilt.update(tilted(15)), -0.5, places=3)

    def test_relative_to_calibration(self) -> None:
        tilt = Tilt(smooth=1.0)
        tilt.calibrate(tilted(20))
        self.assertAlmostEqual(tilt.update(tilted(20)), 0.0)
        self.assertAlmostEqual(tilt.update(tilted(35)), 0.5, places=3)

    def test_smoothing(self) -> None:
        tilt = Tilt(smooth=0.5)
        tilt.calibrate(tilted(0))
        self.assertAlmostEqual(tilt.update(tilted(30)), 0.5, places=3)


if __name__ == "__main__":
    unittest.main()
