"""Omi Flap 3D: fly a ball through a tunnel of walls. Tap to flap, tilt to steer.

Voice mode (Omi Voice Flap): a pendant tap mutes / unmutes the mic, and "go left / right / up /
down / stop" nudge the ball, which hovers instead of falling.

Pendant tap (or space / up / click) flaps; a double tap flaps harder. Steering comes from pendant
tilt when the firmware streams motion, otherwise from the left/right arrow keys (or A/D). Tuned
slow and forgiving: stock firmware reports a single tap about 300 ms after the press.

`Flight` is the pure game (y is up, z is forward). `GameWindow` draws it on a Tk canvas from a chase
camera just behind and above the ball.
"""

from __future__ import annotations

import random
import tkinter as tk
from dataclasses import dataclass, field
from typing import Callable

# World
HALF_W, CEIL = 6.0, 8.0
RADIUS = 0.25
HOLE = 3.8  # side of the square gap in each wall
WALL_EVERY = 20.0
SPEED = 9.0
GRAVITY = 8.0
FLAP_V = 4.2
BOOST = 1.35
MAX_FALL = 6.5
STEER_SPEED = 6.5
STEER_ACCEL = 10.0
RETRY_S = 0.6
KEEP_BEHIND = 6.0  # passed walls stay until they are behind the chase camera
# Voice mode: no gravity. Each spoken command drifts the ball for NUDGE_S, then it holds position.
VOICE_SPEED = 5.8
NUDGE_S = 0.8
NUDGE_SIDE = 4.0  # units per second sideways while a nudge lasts
NUDGE_LIFT = 3.2  # units per second up or down

# View
WIDTH, HEIGHT = 900, 620
FOCAL = 520.0
NEAR, FAR = 0.3, WALL_EVERY * 6
FRAME_MS = 16
CAM_BACK, CAM_UP = 4.5, 0.9  # chase camera offset from the ball
CAM_LAG = 0.12  # seconds; the camera eases after the ball so flaps read on screen
BALL_R = 0.42  # drawn size; the hitbox stays RADIUS
TRAIL = 10
SKY_TOP, SKY_HORIZON = (8, 12, 30), (38, 58, 120)
FLOOR_NEAR, FLOOR_FAR = (22, 30, 58), (12, 17, 36)
FOG = (18, 26, 54)
WALL = (58, 132, 255)
WALL_DARK = (28, 72, 170)
RIM = (255, 216, 77)
BALL_LIT, BALL_BODY, BALL_DARK = (255, 255, 255), (255, 196, 64), (190, 96, 20)
FLASH = (255, 244, 170)
CRASH = (255, 90, 80)


@dataclass
class Flight:
    seed: int = 0
    x: float = 0.0
    y: float = CEIL / 2
    z: float = 0.0
    vx: float = 0.0
    vy: float = 0.0
    walls: list[list[float]] = field(default_factory=list)  # [z, hole x, hole y]
    score: int = 0
    best: int = 0
    started: bool = False
    alive: bool = True
    since_death: float = 0.0
    voice: bool = False
    nudge_x: float = 0.0  # -1, 0, 1 while a spoken nudge lasts
    nudge_y: float = 0.0
    nudge_left_s: float = 0.0

    def __post_init__(self) -> None:
        self.rng = random.Random(self.seed)
        self._fill()

    def reset(self) -> None:
        best, seed = self.best, self.rng.randrange(1 << 30)
        self.__init__(seed=seed, voice=self.voice)  # type: ignore[misc]
        self.best = best

    def flap(self, strength: float = 1.0) -> None:
        if not self.alive:
            if self.since_death < RETRY_S:
                return
            self.reset()
        self.started = True
        self.vy = FLAP_V * strength

    def command(self, word: str) -> None:
        """Voice mode: "left", "right", "up", "down" nudge for NUDGE_S; "stop" holds. Any word starts or retries."""
        if not self.alive:
            if self.since_death < RETRY_S:
                return
            self.reset()
        self.started = True
        if word == "stop":
            self.nudge_x = self.nudge_y = 0.0
            self.nudge_left_s = 0.0
            return
        self.nudge_x = {"left": -1.0, "right": 1.0}.get(word, 0.0)
        self.nudge_y = {"up": 1.0, "down": -1.0}.get(word, 0.0)
        self.nudge_left_s = NUDGE_S

    def step(self, dt: float, steer: float = 0.0) -> None:
        """Advance by `dt` seconds. `steer` is -1 (left) … 1 (right)."""
        if not self.alive:
            self.since_death += dt
            return
        if not self.started:
            return
        if self.voice:
            self.nudge_left_s = max(0.0, self.nudge_left_s - dt)
            active = self.nudge_left_s > 0
            side = steer if steer else (self.nudge_x if active else 0.0)
            target_x = max(-1.0, min(1.0, side)) * (STEER_SPEED if steer else NUDGE_SIDE)
            target_y = (self.nudge_y if active else 0.0) * NUDGE_LIFT
            self.vy += max(-STEER_ACCEL * dt, min(STEER_ACCEL * dt, target_y - self.vy))
            speed = VOICE_SPEED
        else:
            target_x = max(-1.0, min(1.0, steer)) * STEER_SPEED
            self.vy = max(self.vy - GRAVITY * dt, -MAX_FALL)
            speed = SPEED
        self.vx += max(-STEER_ACCEL * dt, min(STEER_ACCEL * dt, target_x - self.vx))
        self.x = max(-HALF_W + RADIUS, min(HALF_W - RADIUS, self.x + self.vx * dt))
        self.y = min(self.y + self.vy * dt, CEIL - RADIUS)
        before, self.z = self.z, self.z + speed * dt
        for wall in self.walls:
            if before < wall[0] <= self.z:
                if self._through(wall):
                    self.score += 1
                else:
                    self._crash()
                    return
        if self.y <= RADIUS:
            self._crash()
            return
        self.walls = [w for w in self.walls if w[0] > self.z - KEEP_BEHIND]
        self._fill()

    def _through(self, wall: list[float]) -> bool:
        room = HOLE / 2 - RADIUS
        return abs(self.x - wall[1]) <= room and abs(self.y - wall[2]) <= room

    def _crash(self) -> None:
        self.alive = False
        self.since_death = 0.0
        self.best = max(self.best, self.score)

    def _fill(self) -> None:
        while not self.walls or self.walls[-1][0] < self.z + FAR:
            if not self.walls:
                self.walls.append([WALL_EVERY * 1.5, 0.0, CEIL / 2])  # first gap straight ahead
                continue
            z, hx, hy = self.walls[-1]
            limit_x, low_y, high_y = HALF_W - HOLE / 2, HOLE / 2 + 0.3, CEIL - HOLE / 2
            hx = max(-limit_x, min(limit_x, hx + self.rng.uniform(-3.0, 3.0)))
            hy = max(low_y, min(high_y, hy + self.rng.uniform(-1.8, 1.8)))
            self.walls.append([z + WALL_EVERY, hx, hy])


def _mix(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> str:
    return "#%02x%02x%02x" % _blend(a, b, t)


def _blend(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    t = max(0.0, min(1.0, t))
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))  # type: ignore[return-value]


class GameWindow:
    """`steer_source()` returns (steer, label) from the pendant, or None to fall back to the keyboard."""

    def __init__(
        self,
        parent: tk.Misc,
        on_close: Callable[[], None],
        steer_source: Callable[[], tuple[float, str] | None] = lambda: None,
        on_key: Callable[[str], None] = lambda _k: None,
        voice: bool = False,
        voice_status: Callable[[], tuple[bool, str]] = lambda: (False, ""),
    ) -> None:
        self.game = Flight(seed=random.randrange(1 << 30), voice=voice)
        self.voice = voice
        self.voice_status = voice_status
        self.last_command: tuple[str, float] = ("", -10.0)
        self.clock = 0.0
        self.on_close = on_close
        self.steer_source = steer_source
        self.on_key = on_key
        self.keys: set[str] = set()
        self.flash = 0
        self.trail: list[tuple[float, float, float]] = []
        self.cam = [self.game.x, self.game.y + CAM_UP]
        self.steer_now, self.steer_label = 0.0, ""
        self.top = tk.Toplevel(parent)
        self.top.title("Omi Voice Flap" if voice else "Omi Flap 3D")
        self.top.resizable(False, False)
        self.canvas = tk.Canvas(self.top, width=WIDTH, height=HEIGHT, bg=_mix(SKY_TOP, SKY_TOP, 0), highlightthickness=0)
        self.canvas.pack()
        self._sky()
        if voice:  # arrow keys stand in for spoken commands, space starts / holds
            for key, word in (("<Up>", "up"), ("<Down>", "down"), ("<Left>", "left"), ("<Right>", "right"), ("<space>", "stop")):
                self.top.bind(key, lambda _e, w=word: self.command(w))
        else:
            for key in ("<space>", "<Up>", "w"):
                self.top.bind(key, lambda _e: self.flap())
        self.canvas.bind("<Button-1>", lambda _e: self.flap())
        self.top.bind("<KeyPress>", self._key_down)
        self.top.bind("<KeyRelease>", lambda e: self.keys.discard(e.keysym.lower()))
        self.top.protocol("WM_DELETE_WINDOW", self.close)
        self.top.focus_force()
        self._tick()

    def flap(self, strength: float = 1.0) -> None:
        self.game.flap(strength)
        self.flash = 8

    def command(self, word: str) -> None:
        """A spoken (or arrow-key) command in voice mode."""
        self.game.command(word)
        self.last_command = (word, self.clock)
        self.flash = 8

    def _key_down(self, event: tk.Event) -> None:
        key = event.keysym.lower()
        self.keys.add(key)
        if key in ("c", "x", "i"):
            self.on_key(key)

    def _steer(self) -> tuple[float, str]:
        if self.voice:
            return 0.0, "voice"
        pendant = self.steer_source()
        if pendant is not None:
            return pendant
        steer = (1.0 if self.keys & {"right", "d"} else 0.0) - (1.0 if self.keys & {"left", "a"} else 0.0)
        return steer, "keys ← →"

    def _tick(self) -> None:
        dt = FRAME_MS / 1000
        self.clock += dt
        self.steer_now, self.steer_label = self._steer()
        g = self.game
        g.step(dt, self.steer_now)
        ease = min(1.0, dt / CAM_LAG)
        self.cam[0] += (g.x - self.cam[0]) * ease
        self.cam[1] += (g.y + CAM_UP - self.cam[1]) * ease
        if g.started and g.alive:
            self.trail = (self.trail + [(g.x, g.y, g.z)])[-TRAIL:]
        elif not g.started:
            self.trail = []
        self._job = self.top.after(FRAME_MS, self._tick)  # first, so a drawing error cannot stop the loop
        self._draw()

    # --- drawing ---------------------------------------------------------------------------

    def _project(self, x: float, y: float, z: float) -> tuple[float, float, float] | None:
        """Screen x, y and depth from the camera, or None behind the near plane."""
        dz = z - (self.game.z - CAM_BACK)
        if dz <= NEAR:
            return None
        sx = WIDTH / 2 + FOCAL * (x - self.cam[0]) / dz
        sy = HEIGHT / 2 - FOCAL * (y - self.cam[1]) / dz
        return max(-5000.0, min(5000.0, sx)), max(-5000.0, min(5000.0, sy)), dz

    def _sky(self) -> None:
        """Static gradient behind everything, drawn once."""
        c, bands = self.canvas, 24
        for i in range(bands):
            y0, y1 = HEIGHT / 2 * i / bands, HEIGHT / 2 * (i + 1) / bands + 1
            c.create_rectangle(0, y0, WIDTH, y1, fill=_mix(SKY_TOP, SKY_HORIZON, i / (bands - 1)), outline="", tags="bg")
        for i in range(bands):
            y0, y1 = HEIGHT / 2 + HEIGHT / 2 * i / bands, HEIGHT / 2 + HEIGHT / 2 * (i + 1) / bands + 1
            c.create_rectangle(0, y0, WIDTH, y1, fill=_mix(FLOOR_FAR, FLOOR_NEAR, i / (bands - 1)), outline="", tags="bg")
        rng = random.Random(7)
        for _ in range(60):
            x, y = rng.uniform(0, WIDTH), rng.uniform(0, HEIGHT * 0.42)
            shade = _mix(SKY_HORIZON, (220, 230, 255), rng.uniform(0.3, 0.9))
            c.create_oval(x, y, x + 1.6, y + 1.6, fill=shade, outline="", tags="bg")

    def _floor(self) -> None:
        c, g = self.canvas, self.game
        grid = 3.0
        z = (int(g.z / grid) + 1) * grid - CAM_BACK
        while z < g.z + FAR:
            a, b = self._project(-HALF_W, 0, z), self._project(HALF_W, 0, z)
            if a and b:
                c.create_line(a[0], a[1], b[0], b[1], fill=_mix((70, 100, 190), FLOOR_FAR, a[2] / FAR), tags="dyn")
            z += grid
        x = -HALF_W
        while x <= HALF_W + 1e-6:
            a, b = self._project(x, 0, g.z - CAM_BACK + NEAR + 0.05), self._project(x, 0, g.z + FAR)
            if a and b:
                edge = abs(x) > HALF_W - 1e-6
                colour = _mix((120, 150, 240), FLOOR_FAR, 0.2) if edge else _mix((70, 100, 190), FLOOR_FAR, 0.45)
                c.create_line(a[0], a[1], b[0], b[1], fill=colour, width=2 if edge else 1, tags="dyn")
            x += 2.0
        for side in (-HALF_W, HALF_W):  # ceiling rails
            a, b = self._project(side, CEIL, g.z - CAM_BACK + NEAR + 0.05), self._project(side, CEIL, g.z + FAR)
            if a and b:
                c.create_line(a[0], a[1], b[0], b[1], fill=_mix((90, 110, 190), SKY_HORIZON, 0.4), tags="dyn")

    def _wall(self, wz: float, hx: float, hy: float) -> None:
        c = self.canvas
        corner0, corner1 = self._project(-HALF_W, CEIL, wz), self._project(HALF_W, 0.0, wz)
        h = HOLE / 2
        gap0, gap1 = self._project(hx - h, hy + h, wz), self._project(hx + h, hy - h, wz)
        if not (corner0 and corner1 and gap0 and gap1):
            return
        fog = (corner0[2] / FAR) ** 0.8
        face_rgb = _blend(WALL, FOG, fog)
        face, shade = _mix(face_rgb, face_rgb, 0), _mix(WALL_DARK, FOG, fog)
        x0, y0, x1, y1 = corner0[0], corner0[1], corner1[0], corner1[1]
        gx0, gy0, gx1, gy1 = gap0[0], gap0[1], gap1[0], gap1[1]
        for rect in ((x0, y0, gx0, y1), (gx1, y0, x1, y1), (gx0, y0, gx1, gy0), (gx0, gy1, gx1, y1)):
            c.create_rectangle(*rect, fill=face, outline="", tags="dyn")
        # Inner bevel on the lower and right edges of the gap, so it reads as a hole in a slab.
        bevel = max(2.0, (gx1 - gx0) * 0.06)
        c.create_rectangle(gx0, gy1 - bevel, gx1, gy1, fill=shade, outline="", tags="dyn")
        c.create_rectangle(gx1 - bevel, gy0, gx1, gy1, fill=shade, outline="", tags="dyn")
        glow = _mix(RIM, FOG, fog * 0.9)
        width = max(1, round(6 * (1 - fog)))
        c.create_rectangle(gx0, gy0, gx1, gy1, outline=_mix(RIM, face_rgb, 0.6), width=width + 4, tags="dyn")
        c.create_rectangle(gx0, gy0, gx1, gy1, outline=glow, width=width, tags="dyn")

    def _ball(self) -> None:
        c, g = self.canvas, self.game
        centre = self._project(g.x, g.y, g.z)
        if centre is None:
            return
        sx, sy, dz = centre
        r = FOCAL * BALL_R / dz
        floor = self._project(g.x, 0.0, g.z)
        if floor:  # shadow shrinks and fades with height
            lift = max(0.0, min(1.0, g.y / CEIL))
            w = r * (1.3 - 0.7 * lift)
            c.create_oval(floor[0] - w, floor[1] - w * 0.28, floor[0] + w, floor[1] + w * 0.28,
                          fill=_mix((4, 6, 14), FLOOR_NEAR, 0.25 + 0.6 * lift), outline="", tags="dyn")
        for i, (tx, ty, tz) in enumerate(self.trail[:-1]):
            p = self._project(tx, ty, tz)
            if p:
                k = (i + 1) / len(self.trail)
                tr = FOCAL * BALL_R * 0.55 * k / p[2]
                c.create_oval(p[0] - tr, p[1] - tr, p[0] + tr, p[1] + tr,
                              fill=_mix(SKY_HORIZON, BALL_BODY, 0.25 + 0.5 * k), outline="", tags="dyn")
        if not g.alive:
            body, dark = CRASH, (120, 20, 20)
        elif self.flash:
            body, dark = FLASH, BALL_BODY
        else:
            body, dark = BALL_BODY, BALL_DARK
        self.flash = max(0, self.flash - 1)
        c.create_oval(sx - r * 1.35, sy - r * 1.35, sx + r * 1.35, sy + r * 1.35,
                      fill="", outline=_mix(body, SKY_HORIZON, 0.55), width=3, tags="dyn")
        steps = 7  # shaded sphere: rings from the dark rim to a lit spot up and to the left
        for i in range(steps):
            t = i / (steps - 1)
            rr = r * (1 - 0.82 * t)
            ox, oy = -r * 0.32 * t, -r * 0.32 * t
            colour = "#%02x%02x%02x" % (_blend(dark, body, t * 1.6) if t < 0.62 else _blend(body, BALL_LIT, (t - 0.62) / 0.38))
            c.create_oval(sx + ox - rr, sy + oy - rr, sx + ox + rr, sy + oy + rr, fill=colour, outline="", tags="dyn")

    def _hud(self) -> None:
        c, g = self.canvas, self.game
        cx, cy = WIDTH / 2, HEIGHT / 2
        c.create_text(cx + 2, 48, text=str(g.score), fill="#000000", font=("Helvetica", 44, "bold"), tags="dyn")
        c.create_text(cx, 46, text=str(g.score), fill="white", font=("Helvetica", 44, "bold"), tags="dyn")
        if g.best:
            c.create_text(WIDTH - 20, 26, anchor="e", text=f"best {g.best}", fill="#c9d4ff", font=("Helvetica", 14), tags="dyn")
        c.create_rectangle(0, HEIGHT - 40, WIDTH, HEIGHT, fill="#0a0f22", outline="", stipple="gray50", tags="dyn")
        c.create_text(16, HEIGHT - 20, anchor="w", fill="#aab4d4", font=("Helvetica", 12), tags="dyn",
                      text=("tap pendant: mute / unmute   ·   say go left · right · up · down · stop   ·   arrow keys work too"
                            if self.voice else f"steer: {self.steer_label}   ·   tap: flap   ·   double tap: big flap"))
        bx = WIDTH - 150
        c.create_rectangle(bx, HEIGHT - 27, bx + 130, HEIGHT - 13, outline="#5b6a99", tags="dyn")
        c.create_line(bx + 65, HEIGHT - 30, bx + 65, HEIGHT - 10, fill="#5b6a99", tags="dyn")
        c.create_rectangle(bx + 65, HEIGHT - 25, bx + 65 + 63 * self.steer_now, HEIGHT - 15, fill="#ffd84d", outline="", tags="dyn")
        if self.voice:
            self._voice_hud()
        if not g.started:
            title, hint = (
                ("Tap the pendant to unmute, then say “go up”", "say go left · go right · go up · go down · stop")
                if self.voice
                else ("Tap the pendant to start", "fly the ball through the glowing gaps  ·  tilt or ← → to steer")
            )
            c.create_text(cx, cy + 150, text=title, fill="white", font=("Helvetica", 24, "bold"), tags="dyn")
            c.create_text(cx, cy + 184, fill="#c9d4ff", font=("Helvetica", 14), tags="dyn", text=hint)
        elif not g.alive:
            c.create_rectangle(0, 0, WIDTH, HEIGHT, fill="#b3261e", stipple="gray25", outline="", tags="dyn")
            c.create_text(cx, cy - 110, text="Crashed", fill="white", font=("Helvetica", 34, "bold"), tags="dyn")
            retry = "say a command to retry" if self.voice else "tap to retry"
            c.create_text(cx, cy - 72, text=f"score {g.score}  ·  best {g.best}  ·  {retry}", fill="white",
                          font=("Helvetica", 16), tags="dyn")

    def _voice_hud(self) -> None:
        c = self.canvas
        listening, heard = self.voice_status()
        badge, colour = ("● LISTENING", "#3ddc84") if listening else ("MUTED · tap pendant", "#ff6b6b")
        c.create_rectangle(14, 14, 214, 44, fill="#0a0f22", outline=colour, width=2, tags="dyn")
        c.create_text(114, 29, text=badge, fill=colour, font=("Helvetica", 14, "bold"), tags="dyn")
        if heard:
            c.create_text(14, 62, anchor="w", text=f"heard: {heard}", fill="#c9d4ff", font=("Helvetica", 13), tags="dyn")
        word, at = self.last_command
        age = self.clock - at
        if word and age < 0.7:
            fade = _mix((255, 216, 77), SKY_HORIZON, age / 0.7)
            cx, cy = WIDTH / 2, HEIGHT / 2 - 150
            arrows = {"left": "◀", "right": "▶", "up": "▲", "down": "▼", "stop": "■"}
            c.create_text(cx, cy, text=arrows.get(word, word), fill=fade, font=("Helvetica", 64, "bold"), tags="dyn")
            c.create_text(cx, cy + 50, text=word.upper(), fill=fade, font=("Helvetica", 18, "bold"), tags="dyn")

    def _draw(self) -> None:
        c, g = self.canvas, self.game
        c.delete("dyn")
        self._floor()
        # Walls and the ball, far to near, so the ball shows through gaps and passes in front of walls.
        items: list[tuple[float, str, tuple[float, float, float]]] = [(w[0], "wall", (w[0], w[1], w[2])) for w in g.walls]
        items.append((g.z, "ball", (0.0, 0.0, 0.0)))
        for depth, kind, data in sorted(items, key=lambda item: -item[0]):
            if depth - (g.z - CAM_BACK) > FAR:
                continue
            if kind == "wall":
                self._wall(*data)
            else:
                self._ball()
        self._hud()

    def close(self) -> None:
        self.top.after_cancel(self._job)
        self.top.destroy()
        self.on_close()
