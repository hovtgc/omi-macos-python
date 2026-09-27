"""Arcade mini games, as pure state machines. Renderers live in `arcade.py`.

Every game takes the same input each frame: a `Stick` (2-axis tilt in [-1, 1], x right, y up), the
number of taps since the last frame, and whether the pendant was shaken. Keys stand in when the
firmware sends no motion.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field


@dataclass
class Stick:
    x: float = 0.0
    y: float = 0.0
    taps: int = 0
    shake: bool = False


# --- Marble Maze -------------------------------------------------------------------------------

WALL_N, WALL_E, WALL_S, WALL_W = 1, 2, 4, 8
MARBLE_R = 0.28  # in cells
ROLL_ACCEL = 9.0  # cells per s² at full tilt
ROLL_FRICTION = 1.6  # per second
BOUNCE = 0.3


def make_maze(cols: int, rows: int, rng: random.Random) -> list[list[int]]:
    """Perfect maze by depth-first carving. Each cell holds the walls still standing."""
    walls = [[WALL_N | WALL_E | WALL_S | WALL_W for _ in range(cols)] for _ in range(rows)]
    seen = [[False] * cols for _ in range(rows)]
    stack = [(0, 0)]
    seen[0][0] = True
    steps = ((0, -1, WALL_N, WALL_S), (1, 0, WALL_E, WALL_W), (0, 1, WALL_S, WALL_N), (-1, 0, WALL_W, WALL_E))
    while stack:
        cx, cy = stack[-1]
        options = [(cx + dx, cy + dy, a, b) for dx, dy, a, b in steps if 0 <= cx + dx < cols and 0 <= cy + dy < rows and not seen[cy + dy][cx + dx]]
        if not options:
            stack.pop()
            continue
        nx, ny, here, there = rng.choice(options)
        walls[cy][cx] &= ~here
        walls[ny][nx] &= ~there
        seen[ny][nx] = True
        stack.append((nx, ny))
    return walls


@dataclass
class MarbleMaze:
    """Tilt rolls the marble; a tap brakes. Reach the flag. Each level adds cells."""

    seed: int = 0
    level: int = 1
    x: float = 0.5
    y: float = 0.5
    vx: float = 0.0
    vy: float = 0.0
    elapsed: float = 0.0
    total: float = 0.0
    won: bool = False
    walls: list[list[int]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.rng = random.Random(self.seed)
        self._build()

    @property
    def cols(self) -> int:
        return 5 + self.level * 2

    @property
    def rows(self) -> int:
        return 4 + self.level

    @property
    def goal(self) -> tuple[int, int]:
        return self.cols - 1, self.rows - 1

    def _build(self) -> None:
        self.walls = make_maze(self.cols, self.rows, self.rng)
        self.x, self.y, self.vx, self.vy, self.elapsed, self.won = 0.5, 0.5, 0.0, 0.0, 0.0, False

    def next_level(self) -> None:
        self.level += 1
        self._build()

    def step(self, dt: float, stick: Stick) -> None:
        if self.won:
            if stick.taps:
                self.next_level()
            return
        self.elapsed += dt
        self.total += dt
        if stick.taps:
            self.vx *= 0.2
            self.vy *= 0.2
        # Screen y grows downward; forward tilt (stick.y > 0) rolls the marble up.
        self.vx += stick.x * ROLL_ACCEL * dt
        self.vy += -stick.y * ROLL_ACCEL * dt
        drag = max(0.0, 1.0 - ROLL_FRICTION * dt)
        self.vx *= drag
        self.vy *= drag
        # Small sub-steps so a fast marble cannot pass through a wall.
        steps = max(1, int(max(abs(self.vx), abs(self.vy)) * dt / 0.1) + 1)
        for _ in range(steps):
            self._move(self.vx * dt / steps, self.vy * dt / steps)
        if (int(self.x), int(self.y)) == self.goal:
            self.won = True

    def _move(self, dx: float, dy: float) -> None:
        cx, cy = int(self.x), int(self.y)
        walls = self.walls[cy][cx]
        nx = self.x + dx
        if dx > 0 and walls & WALL_E and nx + MARBLE_R > cx + 1:
            nx, self.vx = cx + 1 - MARBLE_R, -self.vx * BOUNCE
        elif dx < 0 and walls & WALL_W and nx - MARBLE_R < cx:
            nx, self.vx = cx + MARBLE_R, -self.vx * BOUNCE
        self.x = min(max(nx, MARBLE_R), self.cols - MARBLE_R)
        cx = int(self.x)
        walls = self.walls[cy][cx]
        ny = self.y + dy
        if dy > 0 and walls & WALL_S and ny + MARBLE_R > cy + 1:
            ny, self.vy = cy + 1 - MARBLE_R, -self.vy * BOUNCE
        elif dy < 0 and walls & WALL_N and ny - MARBLE_R < cy:
            ny, self.vy = cy + MARBLE_R, -self.vy * BOUNCE
        self.y = min(max(ny, MARBLE_R), self.rows - MARBLE_R)


# --- Star Dodger -------------------------------------------------------------------------------

FIELD_W, FIELD_H = 100.0, 140.0  # world units; the ship lives in the lower part
SHIP_R, ROCK_R_MIN, ROCK_R_MAX = 3.0, 3.0, 7.0
SHIP_SPEED = 70.0
BULLET_SPEED = 150.0
ROCK_EVERY_S = 0.9
FIRE_COOLDOWN_S = 0.15


@dataclass
class StarDodger:
    """Tilt flies the ship in 2D, taps fire, a shake bombs every rock on screen (three per game)."""

    seed: int = 0
    x: float = FIELD_W / 2
    y: float = FIELD_H * 0.8
    rocks: list[list[float]] = field(default_factory=list)  # x, y, r, speed
    bullets: list[list[float]] = field(default_factory=list)  # x, y
    score: int = 0
    lives: int = 3
    bombs: int = 3
    over: bool = False
    clock: float = 0.0
    since_rock: float = 0.0
    since_fire: float = FIRE_COOLDOWN_S
    hurt_s: float = 0.0  # invulnerable after a hit
    flash_s: float = 0.0  # screen flash after a bomb

    def __post_init__(self) -> None:
        self.rng = random.Random(self.seed)

    def step(self, dt: float, stick: Stick) -> None:
        if self.over:
            return
        self.clock += dt
        self.hurt_s = max(0.0, self.hurt_s - dt)
        self.flash_s = max(0.0, self.flash_s - dt)
        self.since_fire += dt
        self.x = min(max(self.x + stick.x * SHIP_SPEED * dt, SHIP_R), FIELD_W - SHIP_R)
        self.y = min(max(self.y - stick.y * SHIP_SPEED * dt, FIELD_H * 0.45), FIELD_H - SHIP_R)
        if stick.taps and self.since_fire >= FIRE_COOLDOWN_S:
            self.bullets.append([self.x, self.y - SHIP_R])
            self.since_fire = 0.0
        if stick.shake and self.bombs:
            self.bombs -= 1
            self.score += 5 * len(self.rocks)
            self.rocks.clear()
            self.flash_s = 0.35
        pace = 1.0 + self.clock / 45.0  # gets busier over time
        self.since_rock += dt * pace
        if self.since_rock >= ROCK_EVERY_S:
            self.since_rock = 0.0
            r = self.rng.uniform(ROCK_R_MIN, ROCK_R_MAX)
            self.rocks.append([self.rng.uniform(r, FIELD_W - r), -r, r, self.rng.uniform(22, 40) * pace])
        for bullet in self.bullets:
            bullet[1] -= BULLET_SPEED * dt
        for rock in self.rocks:
            rock[1] += rock[3] * dt
        for bullet in list(self.bullets):
            for rock in list(self.rocks):
                if math.hypot(bullet[0] - rock[0], bullet[1] - rock[1]) < rock[2]:
                    self.rocks.remove(rock)
                    if bullet in self.bullets:
                        self.bullets.remove(bullet)
                    self.score += 10
                    break
        if not self.hurt_s:
            for rock in self.rocks:
                if math.hypot(self.x - rock[0], self.y - rock[1]) < rock[2] + SHIP_R * 0.8:
                    self.rocks.remove(rock)
                    self.lives -= 1
                    self.hurt_s = 1.5
                    if self.lives <= 0:
                        self.over = True
                    break
        self.rocks = [r for r in self.rocks if r[1] - r[2] < FIELD_H]
        self.bullets = [b for b in self.bullets if b[1] > -5]
        self.score += int(self.clock) - int(self.clock - dt)  # one point per second alive


# --- Omi Catch ---------------------------------------------------------------------------------

CATCH_W = 100.0
BASKET_HALF = 9.0
DROP_EVERY_S = 0.75
BOMB_CHANCE = 0.22


@dataclass
class Catch:
    """Tilt left/right sets where the basket is. Catch stars, dodge bombs, miss three stars and it ends."""

    seed: int = 0
    basket: float = CATCH_W / 2
    drops: list[list[float]] = field(default_factory=list)  # x, y, speed, is_bomb
    score: int = 0
    misses: int = 0
    over: bool = False
    clock: float = 0.0
    since_drop: float = 0.0
    streak: int = 0

    def __post_init__(self) -> None:
        self.rng = random.Random(self.seed)

    def step(self, dt: float, stick: Stick) -> None:
        if self.over:
            return
        self.clock += dt
        # Position control feels direct with tilt: the basket eases toward where you point.
        target = CATCH_W / 2 + stick.x * (CATCH_W / 2 - BASKET_HALF)
        self.basket += (target - self.basket) * min(1.0, dt * 12)
        pace = 1.0 + self.clock / 60.0
        self.since_drop += dt * pace
        if self.since_drop >= DROP_EVERY_S:
            self.since_drop = 0.0
            bomb = self.rng.random() < BOMB_CHANCE
            self.drops.append([self.rng.uniform(5, CATCH_W - 5), 0.0, self.rng.uniform(28, 42) * pace, 1.0 if bomb else 0.0])
        kept = []
        for drop in self.drops:
            drop[1] += drop[2] * dt
            if drop[1] >= 92.0 and abs(drop[0] - self.basket) <= BASKET_HALF:
                if drop[3]:
                    self.over = True
                else:
                    self.streak += 1
                    self.score += 1 + self.streak // 5
                continue
            if drop[1] > 100.0:
                if not drop[3]:
                    self.misses += 1
                    self.streak = 0
                    if self.misses >= 3:
                        self.over = True
                continue
            kept.append(drop)
        self.drops = kept
