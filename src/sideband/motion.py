"""Pendant motion: parse the LSM6DS3TR-C accelerometer/gyro notification and turn it into tilt. Pure.

Stock firmware 3.0.x compiles motion out (CONFIG_OMI_ENABLE_ACCELEROMETER=n). With it on, the
service below appears. Two payloads are understood:

- 48 bytes: upstream `struct sensors`, six Zephyr `sensor_value`s (int32 whole, int32 millionths),
  accel in m/s², gyro in rad/s.
- 12 bytes: six little-endian int16 raw samples (accel ±4 g, gyro ±500 dps), the compact 50 Hz
  format from `firmware/accel-stream.patch` in this repo.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass

MOTION_SERVICE_UUID = "32403790-0000-1000-7450-bf445e5829a2"
MOTION_UUID = "32403791-0000-1000-7450-bf445e5829a2"

G = 9.80665
ACCEL_LSB = 0.122e-3 * G  # ±4 g full scale, m/s² per LSB
GYRO_LSB = math.radians(17.5e-3)  # ±500 dps full scale, rad/s per LSB


@dataclass(frozen=True)
class Motion:
    ax: float
    ay: float
    az: float
    gx: float
    gy: float
    gz: float

    @property
    def accel(self) -> tuple[float, float, float]:
        return self.ax, self.ay, self.az


def steady(samples: list[Motion]) -> Motion | None:
    """The median of each axis: how the pendant is held, ignoring the jolt of a button press."""
    if not samples:
        return None

    def median(values: list[float]) -> float:
        values = sorted(values)
        mid = len(values) // 2
        return values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2

    return Motion(*(median([getattr(s, axis) for s in samples]) for axis in ("ax", "ay", "az", "gx", "gy", "gz")))


def parse_motion(raw: bytes) -> Motion | None:
    if len(raw) == 48:
        parts = struct.unpack("<12i", raw)
        values = [whole + frac / 1e6 for whole, frac in zip(parts[0::2], parts[1::2])]
        return Motion(*values)
    if len(raw) == 12:
        a = struct.unpack("<6h", raw)
        return Motion(a[0] * ACCEL_LSB, a[1] * ACCEL_LSB, a[2] * ACCEL_LSB, a[3] * GYRO_LSB, a[4] * GYRO_LSB, a[5] * GYRO_LSB)
    return None


def _unit(v: tuple[float, float, float]) -> tuple[float, float, float]:
    n = math.sqrt(sum(c * c for c in v)) or 1.0
    return v[0] / n, v[1] / n, v[2] / n


def _dot(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: tuple[float, float, float], b: tuple[float, float, float]) -> tuple[float, float, float]:
    return a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]


def _angle(component: float) -> float:
    return math.degrees(math.asin(max(-1.0, min(1.0, component))))


@dataclass
class Tilt2D:
    """Two-axis tilt, each in [-1, 1], relative to how the pendant was held at calibration.

    Held in the hand, flat in the palm or upright facing you, the pendant's width axis (sensor x)
    is level, and tilting it left or right swings gravity along that axis. So left/right always
    comes from sensor x; forward/back comes from the other level direction. Holding the pendant
    face-down mirrors x, which the calibration notices from which way the face points.
    `learn` (tilt right, then forward) or `swap` / `invert_x` / `invert_y` can override the default
    for unusual grips. `x` > 0 is right, `y` > 0 is forward (up on screen).
    """

    full_deg: float = 25.0
    smooth: float = 0.3
    swap: bool = False
    invert_x: bool = False
    invert_y: bool = False
    rest: tuple[float, float, float] | None = None
    u: tuple[float, float, float] = (1.0, 0.0, 0.0)
    v: tuple[float, float, float] = (0.0, 1.0, 0.0)
    x: float = 0.0
    y: float = 0.0

    def calibrate(self, sample: Motion) -> None:
        rest = _unit(sample.accel)
        # Left/right is the pendant's width axis (sensor x), made level. If x is nearly vertical
        # (held on its side), fall back to the sensor axis most at right angles to gravity.
        axis = 0 if abs(rest[0]) < 0.8 else min(range(3), key=lambda i: abs(rest[i]))
        e = tuple(1.0 if i == axis else 0.0 for i in range(3))
        along = _dot(e, rest)  # type: ignore[arg-type]
        u = _unit(tuple(e[i] - along * rest[i] for i in range(3)))  # type: ignore[arg-type]
        # Accelerometers read "up". Tilting the right side down moves that reading toward -x, so
        # with the face up (+z up) right is -x; face down mirrors it.
        face_up = rest[2] >= 0 if abs(rest[2]) >= abs(rest[1]) else rest[1] >= 0
        self.u = u if not face_up else (-u[0], -u[1], -u[2])
        self.v = _cross(rest, self.u)  # forward: the far edge dipping reads as +y
        self.rest = rest
        self.x = self.y = 0.0

    def raw(self, sample: Motion) -> tuple[float, float]:
        """Unsmoothed tilt toward the two calibration directions, in degrees, before swap and inverts."""
        if self.rest is None:
            self.calibrate(sample)
        now = _unit(sample.accel)
        return _angle(_dot(now, self.u)), _angle(_dot(now, self.v))

    def degrees_from_rest(self, sample: Motion) -> float | None:
        """How far the pendant is tipped, in any direction, from the calibrated rest."""
        if self.rest is None:
            return None
        return math.degrees(math.acos(max(-1.0, min(1.0, _dot(_unit(sample.accel), self.rest)))))

    def update(self, sample: Motion) -> tuple[float, float]:
        a, b = self.raw(sample)
        if self.swap:
            a, b = b, a
        rx = max(-1.0, min(1.0, a / self.full_deg)) * (-1 if self.invert_x else 1)
        ry = max(-1.0, min(1.0, b / self.full_deg)) * (-1 if self.invert_y else 1)
        self.x += (rx - self.x) * self.smooth
        self.y += (ry - self.y) * self.smooth
        return self.x, self.y

    def learn(self, step: str, sample: Motion, min_deg: float = 10.0) -> bool:
        """Calibration wizard. `rest`: record resting gravity. `right`: the user is tilting right now.
        `forward`: the user is tilting forward now. False while the tilt is still too small to read."""
        if step == "rest":
            self.calibrate(sample)
            return True
        a, b = self.raw(sample)
        if step == "right":
            if max(abs(a), abs(b)) < min_deg:
                return False
            self.swap = abs(b) > abs(a)
            self.invert_x = (b if self.swap else a) < 0
            return True
        if step == "forward":
            along = a if self.swap else b  # the direction not used for right
            if abs(along) < min_deg:
                return False
            self.invert_y = along < 0
            return True
        raise ValueError(step)

    def settings(self) -> dict[str, bool]:
        return {"swap": self.swap, "invert_x": self.invert_x, "invert_y": self.invert_y}

    def load(self, saved: dict[str, object]) -> None:
        self.swap = bool(saved.get("swap", False))
        self.invert_x = bool(saved.get("invert_x", False))
        self.invert_y = bool(saved.get("invert_y", False))


@dataclass
class ShakeDetector:
    """A jolt (acceleration well away from 1 g) or a fast twist (gyro), at most once per cooldown."""

    jolt_ms2: float = 7.0
    twist_rads: float = 6.0
    cooldown_s: float = 0.6
    last_at: float = -1e9

    def feed(self, sample: Motion, now: float) -> bool:
        jolt = abs(math.sqrt(_dot(sample.accel, sample.accel)) - G)
        twist = math.sqrt(sample.gx ** 2 + sample.gy ** 2 + sample.gz ** 2)
        if (jolt >= self.jolt_ms2 or twist >= self.twist_rads) and now - self.last_at >= self.cooldown_s:
            self.last_at = now
            return True
        return False


@dataclass
class ShakeGate:
    """Pressing the button jolts the pendant like a small shake. The firmware only reports the tap
    about 300 ms later (600 ms for a double), so hold each shake for `wait_s` and drop it when a
    button event turns up: that jolt was the press."""

    wait_s: float = 0.65
    pending: float | None = None

    def shake(self, at: float) -> None:
        if self.pending is None:
            self.pending = at

    def button(self, at: float) -> None:
        if self.pending is not None and at - self.pending < self.wait_s:
            self.pending = None

    def due(self, now: float) -> bool:
        """True once, when a held shake had no button event after it."""
        if self.pending is not None and now - self.pending >= self.wait_s:
            self.pending = None
            return True
        return False
