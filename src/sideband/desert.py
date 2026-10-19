"""Desert 91: a raycaster outside Kuwait, 1991. Pure. No window.

Three short missions. A rifle and a pistol, health and ammo on the sand, soldiers and two
vehicles. Nobody is a real person. Nothing bleeds: a downed figure is a dust puff.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

SOLID = frozenset("#BF")
WAVES = 3
SPEED = 3.3
MISSIONS = {1: "Berm patrol", 2: "Bunker road", 3: "Smoke line"}


def build_grid() -> list[str]:
    width, height = 16, 12
    rows = [["#" for _ in range(width)] for _ in range(height)]
    for y in range(1, height - 1):
        for x in range(1, width - 1):
            rows[y][x] = "."
    for x in range(1, 8):
        rows[5][x] = "#"
    for x in range(10, 15):
        rows[5][x] = "#"
    rows[5][12] = "."  # bunker door, south side
    rows[5][13] = "."
    for y in range(2, 5):
        rows[y][11] = "B"
        rows[y][14] = "B"
    rows[2][12] = "B"
    rows[2][13] = "B"
    rows[8][13] = "F"
    rows[7][14] = "F"
    rows[9][14] = "F"
    return ["".join(row) for row in rows]


def cell_at(grid: list[str], x: float, y: float) -> str:
    ix, iy = int(x), int(y)
    if iy < 0 or ix < 0 or iy >= len(grid) or ix >= len(grid[0]):
        return "#"
    return grid[iy][ix]


def blocked(grid: list[str], x: float, y: float, radius: float = 0.18) -> bool:
    for ox in (-radius, radius):
        for oy in (-radius, radius):
            if cell_at(grid, x + ox, y + oy) in SOLID:
                return True
    return False


def cast(grid: list[str], x: float, y: float, angle: float, limit: float = 24.0) -> tuple[float, str, int]:
    """Perpendicular distance to the first solid cell, its character, and which side was hit.

    `side` is 0 for a vertical face and 1 for a horizontal one.
    """
    cos_a = math.cos(angle)
    sin_a = math.sin(angle)
    if abs(cos_a) < 1e-8:
        cos_a = 1e-8 if cos_a >= 0 else -1e-8
    if abs(sin_a) < 1e-8:
        sin_a = 1e-8 if sin_a >= 0 else -1e-8
    map_x, map_y = int(x), int(y)
    delta_x, delta_y = abs(1 / cos_a), abs(1 / sin_a)
    if cos_a < 0:
        step_x, side_x = -1, (x - map_x) * delta_x
    else:
        step_x, side_x = 1, (map_x + 1.0 - x) * delta_x
    if sin_a < 0:
        step_y, side_y = -1, (y - map_y) * delta_y
    else:
        step_y, side_y = 1, (map_y + 1.0 - y) * delta_y
    side = 0
    for _ in range(48):
        if side_x < side_y:
            side_x += delta_x
            map_x += step_x
            side = 0
        else:
            side_y += delta_y
            map_y += step_y
            side = 1
        if map_y < 0 or map_x < 0 or map_y >= len(grid) or map_x >= len(grid[0]):
            return limit, "#", side
        cell = grid[map_y][map_x]
        if cell in SOLID:
            if side == 0:
                dist = (map_x - x + (1 - step_x) / 2) / cos_a
            else:
                dist = (map_y - y + (1 - step_y) / 2) / sin_a
            return max(0.05, dist), cell, side
    return limit, ".", side


def project(dx: float, dy: float, angle: float) -> tuple[float, float]:
    """`(side, depth)` in camera space. Positive side is to the right. Positive depth is in front."""
    depth = dx * math.cos(angle) + dy * math.sin(angle)
    side = -dx * math.sin(angle) + dy * math.cos(angle)
    return side, depth


def tone_wav(freq: float, ms: int, volume: float = 0.3, noise: float = 0.0) -> bytes:
    """A tiny PCM wave, generated here. Shot, reload and pickup sounds come from this."""
    import io
    import random
    import struct
    import wave

    rate = 8000
    count = max(1, int(rate * ms / 1000))
    rng = random.Random(int(freq * 10) + ms)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        frames = bytearray()
        for i in range(count):
            env = (1 - i / count) ** 2
            sample = math.sin(2 * math.pi * freq * i / rate)
            if noise:
                sample = sample * (1 - noise) + rng.uniform(-1, 1) * noise
            frames += struct.pack("<h", int(max(-1.0, min(1.0, sample * env * volume)) * 32767))
        handle.writeframes(frames)
    return buf.getvalue()


@dataclass
class Orders:
    """One tick of intent, after keyboard, mouse, pad and pendant have been folded together."""

    forward: float = 0.0
    strafe: float = 0.0
    turn: float = 0.0
    fire: bool = False
    reload: bool = False
    weapon: str | None = None


@dataclass
class Gun:
    name: str
    damage: int
    mag_size: int
    mag: int
    reserve: int
    fire_s: float
    reload_s: float
    reach: float
    cooldown: float = 0.0


def _guns() -> dict[str, Gun]:
    return {
        "rifle": Gun("RIFLE", 26, 30, 30, 60, 0.12, 1.15, 16),
        "pistol": Gun("PISTOL", 16, 15, 15, 45, 0.28, 0.8, 9),
    }


@dataclass
class Actor:
    x: float
    y: float
    kind: str
    wave: int
    hp: int
    max_hp: int
    damage: int
    speed: float
    standoff: float
    reach: float
    refire: float
    radius: float
    points: int
    cooldown: float = 0.5
    alive: bool = True
    hurt: float = 0.0


def _actor(x: float, y: float, kind: str, wave: int) -> Actor:
    # hp, damage, speed, standoff, reach, refire, radius, points
    table = {
        "soldier": (50, 8, 1.35, 2.1, 7.5, 1.05, 0.28, 100),
        "jeep": (120, 12, 0.85, 3.3, 9.0, 1.35, 0.42, 250),
        "truck": (180, 14, 0.55, 4.0, 10.0, 1.55, 0.48, 400),
    }
    hp, damage, speed, standoff, reach, refire, radius, points = table[kind]
    return Actor(x, y, kind, wave, hp, hp, damage, speed, standoff, reach, refire, radius, points)


@dataclass
class Pickup:
    x: float
    y: float
    kind: str
    taken: bool = False


@dataclass
class Raid:
    grid: list[str] = field(default_factory=build_grid)
    x: float = 2.5
    y: float = 2.5
    angle: float = 0.0
    health: int = 100
    score: int = 0
    wave: int = 1
    time: float = 0.0
    slot: str = "rifle"
    guns: dict[str, Gun] = field(default_factory=_guns)
    reload_t: float = 0.0
    over: bool = False
    won: bool = False
    banner_t: float = 0.0
    pending: int = 0
    hit_flash: float = 0.0
    combo: int = 0
    kick: float = 0.0
    muzzle: float = 0.0
    shake: float = 0.0
    stop: float = 0.0
    vx: float = 0.0
    vy: float = 0.0
    actors: list[Actor] = field(default_factory=list)
    pickups: list[Pickup] = field(default_factory=list)
    puffs: list[list[float]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.actors:
            self.actors = [
                _actor(8.5, 3.5, "soldier", 1),
                _actor(12.5, 7.5, "soldier", 1),
                _actor(4.5, 8.5, "soldier", 1),
                _actor(9.5, 8.5, "soldier", 2),
                _actor(6.5, 9.5, "soldier", 2),
                _actor(11.5, 9.5, "jeep", 2),
                _actor(3.5, 3.5, "soldier", 3),
                _actor(13.5, 3.5, "soldier", 3),
                _actor(8.5, 10.5, "truck", 3),
            ]
        if not self.pickups:
            self.pickups = [Pickup(9.5, 2.5, "health"), Pickup(3.5, 7.5, "ammo"), Pickup(12.5, 9.5, "ammo")]

    @property
    def mission(self) -> str:
        return MISSIONS.get(self.wave, "Clear")

    @property
    def objective(self) -> str:
        return {
            1: "Drop the patrol on the berm",
            2: "Clear the bunker road",
            3: "Push through the smoke line",
        }.get(self.wave, "Clear the position")

    @property
    def gun(self) -> Gun:
        return self.guns[self.slot]

    def live(self, wave: int | None = None) -> list[Actor]:
        which = self.wave if wave is None else wave
        return [actor for actor in self.actors if actor.alive and actor.wave == which]

    def step(self, dt: float, orders: Orders) -> None:
        if self.over:
            return
        dt = max(0.0, min(float(dt), 2.0))
        self.time += dt
        self.hit_flash = max(0.0, self.hit_flash - dt)
        self.kick = max(0.0, self.kick - dt * 8.0)
        self.muzzle = max(0.0, self.muzzle - dt)
        self.shake = max(0.0, self.shake - dt)
        for actor in self.actors:
            actor.hurt = max(0.0, actor.hurt - dt)
        self.puffs = [puff for puff in self.puffs if puff[2] < 0.5]
        for puff in self.puffs:
            puff[2] += dt
        if self.stop > 0:
            self.stop -= dt
            if self.stop > 0:
                return
            dt = -self.stop
            self.stop = 0.0
        self.angle = (self.angle + orders.turn) % math.tau
        if orders.weapon in self.guns and self.reload_t <= 0:
            self.slot = orders.weapon
        if self.banner_t > 0:
            self._slide(dt, orders.forward, orders.strafe)
            self.banner_t -= dt
            if self.banner_t <= 0 and self.pending:
                if self.pending > WAVES:
                    self.won = True
                    self.over = True
                    self.score += 500 + int(self.health)
                else:
                    self.wave = self.pending
                self.pending = 0
            return
        self._slide(dt, orders.forward, orders.strafe)
        self._collect()
        self._hostiles(dt)
        self._weapon(dt, orders.fire, orders.reload)
        if self.health <= 0:
            self.health = 0
            self.over = True
            return
        if not self.live() and not self.pending:
            self.score += 200
            self.banner_t = 1.15
            self.pending = self.wave + 1

    def _slide(self, dt: float, forward: float, strafe: float) -> None:
        forward = max(-1.0, min(1.0, forward))
        strafe = max(-1.0, min(1.0, strafe))
        cos_a, sin_a = math.cos(self.angle), math.sin(self.angle)
        wish_x = (cos_a * forward - sin_a * strafe) * SPEED
        wish_y = (sin_a * forward + cos_a * strafe) * SPEED
        rate = 16.0 if forward or strafe else 12.0
        blend = min(1.0, rate * dt)
        self.vx += (wish_x - self.vx) * blend
        self.vy += (wish_y - self.vy) * blend
        left = dt
        while left > 1e-9:
            tick = min(0.05, left)
            if not blocked(self.grid, self.x + self.vx * tick, self.y):
                self.x += self.vx * tick
            else:
                self.vx = 0.0
            if not blocked(self.grid, self.x, self.y + self.vy * tick):
                self.y += self.vy * tick
            else:
                self.vy = 0.0
            left -= tick

    def _collect(self) -> None:
        for item in self.pickups:
            if item.taken or math.hypot(item.x - self.x, item.y - self.y) > 0.45:
                continue
            item.taken = True
            if item.kind == "health":
                self.health = min(100, self.health + 35)
            else:
                for gun in self.guns.values():
                    cap = 180 if gun.name == "RIFLE" else 90
                    gun.reserve = min(cap, gun.reserve + (30 if gun.name == "RIFLE" else 15))

    def _sees(self, x: float, y: float) -> bool:
        dist = math.hypot(x - self.x, y - self.y)
        if dist < 0.2:
            return True
        wall, _cell, _side = cast(self.grid, self.x, self.y, math.atan2(y - self.y, x - self.x))
        return wall > dist - 0.25

    def _hostiles(self, dt: float) -> None:
        for actor in self.live():
            actor.cooldown = max(0.0, actor.cooldown - dt)
            if not self._sees(actor.x, actor.y):
                continue
            dist = math.hypot(actor.x - self.x, actor.y - self.y)
            pace = 1.0 + 0.22 * (actor.wave - 1)
            if dist > 0.2:
                ux, uy = (self.x - actor.x) / dist, (self.y - actor.y) / dist
                if dist > actor.standoff:
                    step = min(actor.speed * pace * dt, dist - actor.standoff)
                    nx, ny = actor.x + ux * step, actor.y + uy * step
                else:
                    # Hold the line and sidestep so a still target is not a still target.
                    step = actor.speed * 0.65 * pace * dt
                    nx, ny = actor.x - uy * step, actor.y + ux * step
                if not blocked(self.grid, nx, ny, actor.radius * 0.6) and math.hypot(nx - self.x, ny - self.y) > 0.55:
                    actor.x, actor.y = nx, ny
                elif not blocked(self.grid, nx, actor.y, actor.radius * 0.6):
                    actor.x = nx
            if dist <= actor.reach and actor.cooldown <= 0:
                self.health -= actor.damage
                self.combo = 0
                self.hit_flash = 0.18
                self.shake = max(self.shake, 0.22)
                actor.cooldown = actor.refire * max(0.6, 1.0 - 0.12 * (actor.wave - 1))

    def _weapon(self, dt: float, fire: bool, reload: bool) -> None:
        gun = self.gun
        gun.cooldown = max(0.0, gun.cooldown - dt)
        if self.reload_t > 0:
            self.reload_t -= dt
            if self.reload_t <= 0:
                need = gun.mag_size - gun.mag
                take = min(need, gun.reserve)
                gun.mag += take
                gun.reserve -= take
                self.reload_t = 0
            return
        if reload and gun.mag < gun.mag_size and gun.reserve > 0:
            self.reload_t = gun.reload_s
            return
        if not fire or gun.cooldown > 0:
            return
        if gun.mag <= 0:
            if gun.reserve > 0:
                self.reload_t = gun.reload_s
            return
        gun.mag -= 1
        gun.cooldown = gun.fire_s
        self.kick = min(1.0, self.kick + 0.72)
        self.muzzle = 0.055
        self.shake = max(self.shake, 0.06)
        target = self._hitscan(gun)
        if target is None:
            return
        target.hp -= gun.damage
        target.hurt = 0.12
        if target.hp <= 0:
            target.alive = False
            self.combo += 1
            # The first kill in a chain is face value. Later kills pay a rising bonus.
            extra = 0 if self.combo < 2 else 50 * (self.combo - 1)
            self.score += target.points + extra
            self.stop = 0.04
            self.shake = max(self.shake, 0.28)
            self.puffs.append([target.x, target.y, 0.0])

    def _hitscan(self, gun: Gun) -> Actor | None:
        wall, _cell, _side = cast(self.grid, self.x, self.y, self.angle)
        limit = min(gun.reach, wall)
        best: Actor | None = None
        ux, uy = math.cos(self.angle), math.sin(self.angle)
        for actor in self.live():
            dx, dy = actor.x - self.x, actor.y - self.y
            along = dx * ux + dy * uy
            if along < 0.3 or along > limit:
                continue
            perp = abs(dx * uy - dy * ux)
            if perp <= actor.radius and (best is None or along < limit):
                best = actor
                limit = along
        return best
