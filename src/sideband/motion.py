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


@dataclass
class Tilt:
    """Left/right tilt in [-1, 1] relative to how the pendant hung at calibration.

    `axis` picks which sensor axis reads as left/right (0 x, 1 y, 2 z); `invert` flips it.
    `full_deg` of tilt maps to ±1. `smooth` is the low-pass weight of the newest sample.
    """

    axis: int = 0
    invert: bool = False
    full_deg: float = 30.0
    smooth: float = 0.25
    rest: tuple[float, float, float] | None = None
    value: float = 0.0

    def calibrate(self, sample: Motion) -> None:
        self.rest = _unit(sample.accel)
        self.value = 0.0

    def update(self, sample: Motion) -> float:
        if self.rest is None:
            self.calibrate(sample)
        now = _unit(sample.accel)
        assert self.rest is not None
        # Change of the gravity direction along the chosen axis, as an angle.
        delta = max(-1.0, min(1.0, now[self.axis]))
        base = max(-1.0, min(1.0, self.rest[self.axis]))
        angle = math.degrees(math.asin(delta) - math.asin(base))
        raw = max(-1.0, min(1.0, angle / self.full_deg)) * (-1 if self.invert else 1)
        self.value += (raw - self.value) * self.smooth
        return self.value

    def next_axis(self) -> None:
        self.axis = (self.axis + 1) % 3
        self.rest = None
