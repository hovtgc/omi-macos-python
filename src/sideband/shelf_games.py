"""Four small games that need nothing but a button. Pure state; the window is in `shelf_view`.

All four play on stock pendant firmware (single tap, double tap, a shout) and on a keyboard:
space is the button, D or a double tap is Simon's second pad. No tilt.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field


# --- Beat Tap ----------------------------------------------------------------------------------


@dataclass
class Note:
    t: float
    judged: bool = False
    hit: bool = False


@dataclass
class BeatTap:
    """Notes ride toward a hit line. Tap inside the window. Eight misses and the song ends."""

    seed: int = 0
    bpm: float = 104
    score: int = 0
    combo: int = 0
    best_combo: int = 0
    misses: int = 0
    max_misses: int = 8
    over: bool = False
    clock: float = 0.0
    judge: str = ""
    notes: list[Note] = field(default_factory=list)
    next_t: float = 1.1
    window: float = 0.14
    perfect: float = 0.055

    def __post_init__(self) -> None:
        self.rng = random.Random(self.seed)
        self._spawn_ahead()

    @property
    def interval(self) -> float:
        return 60.0 / self.bpm

    def _spawn_ahead(self) -> None:
        while self.next_t < self.clock + 3.2:
            self.notes.append(Note(self.next_t))
            gap = self.interval * (2 if self.rng.random() < 0.22 else 1)
            self.next_t += gap

    def step(self, dt: float, taps: int = 0) -> None:
        if self.over:
            return
        self.clock += dt
        if self.clock > 8.0:
            self.bpm = min(128.0, 104.0 + (self.clock - 8.0) * 0.45)
        self._spawn_ahead()
        if taps:
            near = [note for note in self.notes if not note.judged and abs(note.t - self.clock) <= self.window]
            if near:
                note = min(near, key=lambda item: abs(item.t - self.clock))
                note.judged = note.hit = True
                self.combo += 1
                self.best_combo = max(self.best_combo, self.combo)
                self.score += (100 if abs(note.t - self.clock) <= self.perfect else 50) + 10 * (self.combo // 4)
                self.judge = "PERFECT" if abs(note.t - self.clock) <= self.perfect else "GOOD"
            else:
                self.combo = 0
                self.judge = "MISS"
        for note in self.notes:
            if not note.judged and self.clock > note.t + self.window:
                note.judged = True
                self.misses += 1
                self.combo = 0
                self.judge = "MISS"
                if self.misses >= self.max_misses:
                    self.over = True
        self.notes = [note for note in self.notes if note.t > self.clock - 0.6]


# --- Quickdraw ---------------------------------------------------------------------------------


@dataclass
class Quickdraw:
    """Wait. When the word is DRAW, tap. Tapping during the wait is a foul. Five rounds."""

    seed: int = 0
    rounds: int = 5
    round: int = 0
    phase: str = "wait"  # wait, draw, gap, over
    left: float = 0.0
    clock: float = 0.0
    draw_at: float = 0.0
    score: int = 0
    fouls: int = 0
    last_ms: float | None = None
    best_ms: float | None = None
    streak: int = 0
    message: str = "WAIT"
    over: bool = False

    def __post_init__(self) -> None:
        self.rng = random.Random(self.seed)
        self.left = self.rng.uniform(0.9, 2.2)

    def step(self, dt: float, taps: int = 0) -> None:
        if self.over:
            return
        self.clock += dt
        if self.phase == "wait":
            if taps:
                self.fouls += 1
                self.streak = 0
                self.message = "TOO SOON"
                self.phase, self.left = "gap", 0.7
                return
            self.left -= dt
            if self.left <= 0:
                self.phase, self.draw_at, self.message = "draw", self.clock, "DRAW"
            return
        if self.phase == "draw":
            if taps:
                ms = max(0.0, (self.clock - self.draw_at) * 1000)
                self.last_ms = ms
                self.best_ms = ms if self.best_ms is None else min(self.best_ms, ms)
                self.streak += 1
                gain = max(40, int(1000 - ms)) + 80 * (self.streak - 1)
                if ms < 220:
                    gain += 120
                self.score += gain
                self.round += 1
                self.message = f"{ms:.0f} ms" + ("  PERFECT" if ms < 220 else "")
                if self.round >= self.rounds:
                    self.over = True
                    self.phase = "over"
                else:
                    self.phase, self.left = "gap", 0.65
                return
            if self.clock - self.draw_at > 1.15:
                self.fouls += 1
                self.streak = 0
                self.message = "TOO SLOW"
                self.round += 1
                if self.round >= self.rounds:
                    self.over = True
                    self.phase = "over"
                else:
                    self.phase, self.left = "gap", 0.7
            return
        if self.phase == "gap":
            self.left -= dt
            if self.left <= 0:
                self.phase = "wait"
                self.left = self.rng.uniform(0.85, 2.3)
                self.message = "WAIT"


# --- Omi Dash ----------------------------------------------------------------------------------


@dataclass
class Dash:
    """Run forever. Tap to jump. A box you don't clear ends the run. Score is distance."""

    seed: int = 0
    y: float = 0.0
    vy: float = 0.0
    travel: float = 0.0
    speed: float = 7.5
    score: int = 0
    over: bool = False
    obstacles: list[list[float]] = field(default_factory=list)  # world x, width, height
    next_x: float = 16.0
    coyote: float = 0.0
    jumped: bool = False
    bonus: int = 0

    RUN_X = 3.0
    RUN_W = 0.75
    RUN_H = 1.15
    JUMP = 9.4
    GRAVITY = 26.0

    def __post_init__(self) -> None:
        self.rng = random.Random(self.seed)

    def step(self, dt: float, taps: int = 0) -> None:
        if self.over:
            return
        grounded = self.y <= 0.001
        if grounded:
            self.coyote = 0.1
            self.jumped = False
        else:
            self.coyote = max(0.0, self.coyote - dt)
        if taps and not self.jumped and (grounded or self.coyote > 0):
            self.vy = self.JUMP
            self.jumped = True
            self.coyote = 0.0
        self.vy -= self.GRAVITY * dt
        self.y += self.vy * dt
        if self.y <= 0.0:
            self.y, self.vy = 0.0, 0.0
        self.travel += self.speed * dt
        self.speed = min(16.0, self.speed + 0.35 * dt)
        while self.next_x < self.travel + 28:
            height = 0.85 if self.rng.random() < 0.65 else 1.4
            self.obstacles.append([self.next_x, 0.7, height])
            self.next_x += self.rng.uniform(8.0, 12.0)
        left, right = self.travel + self.RUN_X, self.travel + self.RUN_X + self.RUN_W
        step = self.speed * dt
        for ox, width, height in self.obstacles:
            if right > ox and left < ox + width and self.y < height:
                self.over = True
                break
            if ox + width < left and ox + width >= left - step and height <= self.y < height + 0.55:
                self.bonus += 50
        self.obstacles = [item for item in self.obstacles if item[0] + item[1] > self.travel - 2]
        self.score = int(self.travel) + self.bonus


# --- Simon Omi ---------------------------------------------------------------------------------


@dataclass
class Simon:
    """A growing pattern of two pads. Pad 0 is a single tap, pad 1 is a double tap."""

    seed: int = 0
    pattern: list[int] = field(default_factory=list)
    phase: str = "show"  # show, input, success, fail
    show_i: int = 0
    show_on: bool = False
    timer: float = 0.35
    input_i: int = 0
    lit: int = -1
    score: int = 0
    over: bool = False
    message: str = "WATCH"

    def __post_init__(self) -> None:
        self.rng = random.Random(self.seed)
        if not self.pattern:
            self.pattern = [self.rng.randrange(2)]

    def step(self, dt: float) -> None:
        if self.over or self.phase == "input":
            if self.phase == "input":
                self.timer += dt
                self.lit = -1
                if self.timer > 3.0:
                    self._fail()
            return
        self.timer -= dt
        if self.timer > 0:
            return
        if self.phase == "show":
            if not self.show_on:
                self.show_on = True
                self.lit = self.pattern[self.show_i]
                self.timer = max(0.22, 0.42 - 0.03 * max(0, len(self.pattern) - 2))
                return
            self.show_on = False
            self.lit = -1
            self.show_i += 1
            if self.show_i >= len(self.pattern):
                self.phase, self.input_i, self.timer, self.message = "input", 0, 0.0, "YOUR TURN"
            else:
                self.timer = 0.18
            return
        if self.phase == "success":
            self.pattern.append(self.rng.randrange(2))
            self.phase, self.show_i, self.show_on = "show", 0, False
            self.timer, self.message, self.lit = 0.45, "WATCH", -1

    def press(self, pad: int) -> None:
        if self.phase != "input" or self.over:
            return
        self.lit = pad
        self.timer = 0.0
        if pad != self.pattern[self.input_i]:
            self._fail()
            return
        self.input_i += 1
        if self.input_i >= len(self.pattern):
            self.score += 1
            self.phase, self.timer, self.message = "success", 0.45, "NICE"

    def _fail(self) -> None:
        self.phase, self.over, self.message, self.lit = "fail", True, "WRONG", -1


SHELF_KEYS = ("beat", "draw", "dash", "simon")


def make(key: str, seed: int) -> BeatTap | Quickdraw | Dash | Simon:
    return {"beat": BeatTap, "draw": Quickdraw, "dash": Dash, "simon": Simon}[key](seed=seed)
