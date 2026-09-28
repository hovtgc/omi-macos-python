"""Sky Ace 1943: a WWII dogfight flown with the Omi. Pure game state; the renderer is `skyfighter_view.py`.

You fly forward (z) through a corridor of sky. Tilt steers: left/right banks and slides, forward dives,
back climbs. A tap fires a burst from the wing guns, a double tap a long burst, a shake barrel-rolls
out of trouble. Enemy fighters and bombers come at you in waves and shoot tracers back.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from sideband.minigames import Stick

SPEED = 42.0  # forward, units per second
HALF_W, LOW, HIGH = 34.0, 5.0, 44.0  # corridor the player can fly in
SIDE_SPEED, CLIMB_SPEED = 30.0, 20.0
RESPONSE = 5.0  # how fast velocity follows the stick
SPAWN_AHEAD = 260.0
FIRE_EVERY = 0.07
BULLET_SPEED = 170.0
BULLET_LIFE = 1.4
BURST_S, LONG_BURST_S = 0.6, 1.4
ROLL_S, ROLL_COOLDOWN = 0.9, 3.0
TRACER_SPEED = 95.0
PLAYER_R = 2.2

KINDS = {
    # name: (hit points, radius, score, speed toward you, fire every s)
    "fighter": (3, 4.5, 100, 26.0, 1.8),
    "bomber": (12, 11.0, 500, 8.0, 2.4),
}


@dataclass
class Enemy:
    kind: str
    x: float
    y: float
    z: float
    hp: int
    phase: float  # weave offset
    reload: float
    hit_flash: float = 0.0

    @property
    def radius(self) -> float:
        return KINDS[self.kind][1]


@dataclass
class Shot:
    x: float
    y: float
    z: float
    vx: float
    vy: float
    vz: float
    life: float
    enemy: bool = False


@dataclass
class Boom:
    x: float
    y: float
    z: float
    age: float = 0.0
    size: float = 1.0


@dataclass
class Dogfight:
    seed: int = 0
    x: float = 0.0
    y: float = 20.0
    z: float = 0.0
    vx: float = 0.0
    vy: float = 0.0
    health: float = 100.0
    score: int = 0
    kills: int = 0
    wave: int = 1
    clock: float = 0.0
    firing: float = 0.0
    since_shot: float = 0.0
    roll: float = 0.0  # barrel roll progress 0..1, 0 when not rolling
    roll_ready: float = 0.0
    hurt: float = 0.0
    started: bool = False
    over: bool = False
    enemies: list[Enemy] = field(default_factory=list)
    shots: list[Shot] = field(default_factory=list)
    booms: list[Boom] = field(default_factory=list)
    since_spawn: float = 0.0

    def __post_init__(self) -> None:
        self.rng = random.Random(self.seed)

    # --- input ---------------------------------------------------------------------------

    def trigger(self, long: bool = False) -> None:
        self.started = True
        self.firing = max(self.firing, LONG_BURST_S if long else BURST_S)

    def barrel_roll(self) -> bool:
        if self.roll or self.roll_ready > 0:
            return False
        self.started = True
        self.roll = 1e-6
        self.roll_ready = ROLL_COOLDOWN
        return True

    @property
    def bank(self) -> float:
        """Visual bank angle in radians: follows sideways speed, plus a full turn while rolling."""
        lean = -0.9 * self.vx / SIDE_SPEED
        return lean + (2 * math.pi * self.roll if self.roll else 0.0)

    @property
    def pitch(self) -> float:
        return 0.5 * self.vy / CLIMB_SPEED

    @property
    def invulnerable(self) -> bool:
        return bool(self.roll) or self.hurt > 0

    # --- simulation ----------------------------------------------------------------------

    def step(self, dt: float, stick: Stick) -> None:
        if self.over or not self.started:
            return
        self.clock += dt
        self.wave = 1 + int(self.clock // 40)
        self.hurt = max(0.0, self.hurt - dt)
        self.roll_ready = max(0.0, self.roll_ready - dt)
        if self.roll:
            self.roll += dt / ROLL_S
            if self.roll >= 1.0:
                self.roll = 0.0
        # Stick: x right, y forward = nose down (dive), like a real control column.
        ease = min(1.0, RESPONSE * dt)
        self.vx += (stick.x * SIDE_SPEED - self.vx) * ease
        self.vy += (-stick.y * CLIMB_SPEED - self.vy) * ease
        self.x = max(-HALF_W, min(HALF_W, self.x + self.vx * dt))
        self.y = max(LOW, min(HIGH, self.y + self.vy * dt))
        self.z += SPEED * dt
        self._guns(dt)
        self._spawn(dt)
        self._move(dt)
        self._hits()
        for boom in self.booms:
            boom.age += dt
        self.booms = [b for b in self.booms if b.age < 1.2]
        if self.health <= 0:
            self.health = 0.0
            self.over = True
            self.booms.append(Boom(self.x, self.y, self.z + 2, size=2.5))

    def _guns(self, dt: float) -> None:
        self.since_shot += dt
        if self.firing > 0:
            self.firing -= dt
            while self.since_shot >= FIRE_EVERY:
                self.since_shot -= FIRE_EVERY
                for side in (-3.2, 3.2):  # wing guns, converging a little ahead
                    self.shots.append(Shot(self.x + side, self.y - 0.2, self.z + 3, -side * 0.9, 0.0, SPEED + BULLET_SPEED, BULLET_LIFE))
        else:
            self.since_shot = min(self.since_shot, FIRE_EVERY)

    def _spawn(self, dt: float) -> None:
        self.since_spawn += dt
        every = max(0.9, 3.2 - 0.35 * self.wave)
        if self.since_spawn < every or len(self.enemies) >= 4 + self.wave:
            return
        self.since_spawn = 0.0
        kind = "bomber" if self.rng.random() < min(0.35, 0.08 * self.wave) else "fighter"
        hp = KINDS[kind][0]
        self.enemies.append(
            Enemy(kind, self.rng.uniform(-HALF_W * 0.8, HALF_W * 0.8), self.rng.uniform(LOW + 4, HIGH - 4),
                  self.z + SPAWN_AHEAD, hp, self.rng.uniform(0, math.tau), self.rng.uniform(0.5, 2.0))
        )

    def _move(self, dt: float) -> None:
        for e in self.enemies:
            _hp, _r, _score, speed, every = KINDS[e.kind]
            e.z -= speed * dt
            weave = 1.0 if e.kind == "fighter" else 0.3
            e.x += math.sin(self.clock * 1.3 + e.phase) * 9 * weave * dt
            e.y += math.cos(self.clock * 0.9 + e.phase) * 4 * weave * dt
            e.hit_flash = max(0.0, e.hit_flash - dt)
            e.reload -= dt
            ahead = e.z - self.z
            if e.reload <= 0 and 30 < ahead < 170:
                e.reload = every * (1.2 - min(0.5, 0.06 * self.wave))
                dx, dy, dz = self.x - e.x, self.y - e.y, self.z + SPEED * 0.6 - e.z
                n = math.sqrt(dx * dx + dy * dy + dz * dz) or 1.0
                self.shots.append(Shot(e.x, e.y, e.z - 3, dx / n * TRACER_SPEED, dy / n * TRACER_SPEED,
                                       dz / n * TRACER_SPEED + SPEED * 0.3, 3.0, enemy=True))
        for s in self.shots:
            s.x += s.vx * dt
            s.y += s.vy * dt
            s.z += s.vz * dt
            s.life -= dt
        self.shots = [s for s in self.shots if s.life > 0 and s.z > self.z - 20]
        escaped = [e for e in self.enemies if e.z < self.z - 25]
        self.enemies = [e for e in self.enemies if e.z >= self.z - 25]
        for _ in escaped:
            self.score = max(0, self.score - 10)

    def _hits(self) -> None:
        for shot in list(self.shots):
            if shot.enemy:
                if not self.invulnerable and _near(shot, self.x, self.y, self.z, PLAYER_R):
                    self.shots.remove(shot)
                    self._hurt(12)
                continue
            for e in self.enemies:
                if _near(shot, e.x, e.y, e.z, e.radius):
                    self.shots.remove(shot)
                    e.hp -= 1
                    e.hit_flash = 0.12
                    if e.hp <= 0:
                        self.enemies.remove(e)
                        self.kills += 1
                        self.score += KINDS[e.kind][2]
                        self.booms.append(Boom(e.x, e.y, e.z, size=1.0 if e.kind == "fighter" else 2.2))
                    break
        for e in list(self.enemies):
            if abs(e.z - self.z) < e.radius and math.hypot(e.x - self.x, e.y - self.y) < e.radius + PLAYER_R:
                self.enemies.remove(e)
                self.booms.append(Boom(e.x, e.y, e.z))
                if not self.invulnerable:
                    self._hurt(40)

    def _hurt(self, amount: float) -> None:
        self.health -= amount
        self.hurt = 0.6


def _near(shot: Shot, x: float, y: float, z: float, radius: float) -> bool:
    return abs(shot.z - z) < radius + 3 and math.hypot(shot.x - x, shot.y - y) < radius
