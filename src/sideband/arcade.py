"""Arcade: the game menu, the tilt calibration wizard, and windows for the mini games.

The launcher owns the pendant; it hands every game the same inputs: 2-axis tilt (`Hub.stick`), taps
(`on_tap`) and shakes (`on_shake`). Arrow keys, space and B stand in when there is no motion stream.
"""

from __future__ import annotations

import math
import random
import time
import tkinter as tk
from tkinter import ttk
from typing import TYPE_CHECKING, Callable

from sideband.minigames import (
    CATCH_W,
    BASKET_HALF,
    FIELD_H,
    FIELD_W,
    MARBLE_R,
    SHIP_R,
    WALL_E,
    WALL_N,
    WALL_S,
    WALL_W,
    Catch,
    MarbleMaze,
    StarDodger,
    Stick,
)
from sideband.motion import Motion

if TYPE_CHECKING:
    from sideband.ui import Hub

GREY = "#8a8f98"
GAMES = (
    ("flap", "🕹", "Omi Flap 3D", "tap: flap · tilt: steer"),
    ("voice", "🗣", "Voice Flap", "tap: mute/unmute · say go left / right / up / down"),
    ("marble", "🔮", "Marble Maze", "tilt: roll in 2D · tap: brake"),
    ("dodger", "🚀", "Star Dodger", "tilt: fly · tap: fire · shake: bomb"),
    ("catch", "🧺", "Omi Catch", "tilt: move the basket · avoid bombs"),
)
WIZARD = (
    ("rest", "Hold the pendant the way you will play, and keep it still…"),
    ("right", "Now tilt it to the RIGHT and hold…"),
    ("forward", "Now tilt it FORWARD (away from you) and hold…"),
)
W, H = 760, 560
FRAME_MS = 16


def _mix(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> str:
    t = max(0.0, min(1.0, t))
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def _ball(c: tk.Canvas, x: float, y: float, r: float, body: tuple[int, int, int], tag: str = "dyn") -> None:
    """Shaded sphere: rings from a dark rim to a lit spot up and to the left."""
    dark = tuple(int(v * 0.55) for v in body)
    for i in range(7):
        t = i / 6
        rr = r * (1 - 0.8 * t)
        ox = oy = -r * 0.3 * t
        colour = _mix(dark, body, t * 1.6) if t < 0.62 else _mix(body, (255, 255, 255), (t - 0.62) / 0.38)  # type: ignore[arg-type]
        c.create_oval(x + ox - rr, y + oy - rr, x + ox + rr, y + oy + rr, fill=colour, outline="", tags=tag)


class ArcadeWindow:
    def __init__(self, hub: Hub) -> None:
        self.hub = hub
        self.top = tk.Toplevel(hub.root)
        self.top.title("Sideband · Arcade")
        self.top.geometry("820x560")
        self.top.protocol("WM_DELETE_WINDOW", self.close)
        self.step: int | None = None  # calibration wizard position
        self.step_since = 0.0
        self.best: dict[str, tk.StringVar] = {}
        self._build()
        self._tick()

    def _build(self) -> None:
        body = ttk.Frame(self.top, padding=16)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        ttk.Label(body, text="Arcade", font=("Helvetica", 24, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(body, text="Games played with your Omi: taps, tilt, shakes and your voice.", foreground=GREY).grid(
            row=1, column=0, sticky="w", pady=(0, 10)
        )
        games = ttk.Frame(body)
        games.grid(row=2, column=0, sticky="nsew")
        games.columnconfigure(2, weight=1)
        for i, (key, icon, title, controls) in enumerate(GAMES):
            ttk.Label(games, text=icon, font=("Helvetica", 26)).grid(row=i, column=0, padx=(0, 10), pady=6)
            ttk.Label(games, text=title, font=("Helvetica", 15, "bold")).grid(row=i, column=1, sticky="w")
            ttk.Label(games, text=controls, foreground=GREY).grid(row=i, column=2, sticky="w", padx=12)
            best = tk.StringVar(value=self._best_text(key))
            self.best[key] = best
            ttk.Label(games, textvariable=best, width=12).grid(row=i, column=3, sticky="e")
            ttk.Button(games, text="Play", command=lambda k=key: self.hub.open_game(k)).grid(row=i, column=4, padx=(10, 0))

        tilt = ttk.LabelFrame(body, text="Tilt", padding=10)
        tilt.grid(row=0, column=1, rowspan=3, sticky="ns", padx=(16, 0))
        self.pad = tk.Canvas(tilt, width=150, height=150, highlightthickness=0)
        self.pad.pack()
        self.source = tk.StringVar(value="")
        ttk.Label(tilt, textvariable=self.source, foreground=GREY, wraplength=170, justify="center").pack(pady=(6, 6))
        ttk.Button(tilt, text="Calibrate tilt", command=self._start_wizard).pack(fill="x")
        ttk.Button(tilt, text="Recentre", command=self.hub.recentre).pack(fill="x", pady=(6, 0))
        self.wizard = tk.StringVar(value="Calibrate once for the way you hold the pendant.")
        ttk.Label(tilt, textvariable=self.wizard, wraplength=170, justify="left").pack(pady=(10, 0))

    def _best_text(self, key: str) -> str:
        best = self.hub.best(key)
        if best is None:
            return "—"
        return f"best {best:.1f}s" if key == "marble" else f"best {int(best)}"

    def refresh_scores(self) -> None:
        for key, var in self.best.items():
            var.set(self._best_text(key))

    # --- calibration wizard ----------------------------------------------------------------

    def _start_wizard(self) -> None:
        if self.hub.latest_motion() is None:
            self.wizard.set("No motion from the pendant. Motion needs the motion firmware (see README).")
            return
        self.step, self.step_since = 0, time.monotonic()
        self.wizard.set(WIZARD[0][1])

    def on_motion(self, sample: Motion) -> None:
        if self.step is None:
            return
        name = WIZARD[self.step][0]
        if name == "rest" and time.monotonic() - self.step_since < 1.5:
            return  # give the hand time to settle
        if not self.hub.tilt.learn(name, sample):
            return
        self.step += 1
        self.step_since = time.monotonic()
        if self.step >= len(WIZARD):
            self.step = None
            self.hub.save_tilt()
            self.wizard.set("Calibrated ✓  Tilt right moves right, forward moves up. Saved for next time.")
        else:
            self.wizard.set(WIZARD[self.step][1])

    # --- live tilt pad ---------------------------------------------------------------------

    def _tick(self) -> None:
        self._job = self.top.after(40, self._tick)
        c = self.pad
        c.delete("all")
        c.create_oval(5, 5, 145, 145, outline="#5b6a99", width=2)
        c.create_line(75, 10, 75, 140, fill="#3a4466")
        c.create_line(10, 75, 140, 75, fill="#3a4466")
        stick = self.hub.stick()
        if stick is None:
            self.source.set("no motion stream · games use arrow keys")
            return
        x, y, label = stick
        self.source.set(label)
        px, py = 75 + x * 62, 75 - y * 62
        c.create_oval(px - 11, py - 11, px + 11, py + 11, fill="#ffc440", outline="")

    def close(self) -> None:
        self.top.after_cancel(self._job)
        self.top.destroy()
        self.hub.window_closed(self)

    def lift(self) -> None:
        self.top.deiconify()
        self.top.lift()
        self.top.focus_force()


class MiniGameWindow:
    """One window for Marble Maze, Star Dodger and Omi Catch. The hub calls on_tap / on_shake."""

    TITLES = {"marble": "Marble Maze", "dodger": "Star Dodger", "catch": "Omi Catch"}

    def __init__(self, hub: Hub, name: str, on_close: Callable[[], None]) -> None:
        self.hub, self.name, self.on_close = hub, name, on_close
        self.top = tk.Toplevel(hub.root)
        self.top.title(f"Sideband · {self.TITLES[name]}")
        self.top.resizable(False, False)
        self.canvas = tk.Canvas(self.top, width=W, height=H, bg="#0b1022", highlightthickness=0)
        self.canvas.pack()
        self.keys: set[str] = set()
        self.taps = 0
        self.shake = False
        self.flash = 0
        self.over_at: float | None = None
        self.recorded = False
        self.stars = [(random.uniform(0, W), random.uniform(0, H), random.uniform(0.3, 1.0)) for _ in range(90)]
        self.maze_level = 0
        self.top.bind("<KeyPress>", self._key_down)
        self.top.bind("<KeyRelease>", lambda e: self.keys.discard(e.keysym.lower()))
        self.canvas.bind("<Button-1>", lambda _e: self.on_tap("single"))
        self.top.protocol("WM_DELETE_WINDOW", self.close)
        self.new_game()
        self.top.focus_force()
        self._tick()

    def new_game(self) -> None:
        seed = random.randrange(1 << 30)
        self.game = {"marble": MarbleMaze, "dodger": StarDodger, "catch": Catch}[self.name](seed=seed)
        self.over_at, self.recorded, self.maze_level = None, False, 0
        self.canvas.delete("all")

    # --- input -----------------------------------------------------------------------------

    def on_tap(self, kind: str) -> None:
        if self._finished() and self.over_at is not None and time.monotonic() - self.over_at > 0.8:
            self.new_game()
            return
        self.taps += 2 if kind == "double" else 1
        self.flash = 6

    def on_shake(self) -> None:
        self.shake = True

    def _key_down(self, event: tk.Event) -> None:
        key = event.keysym.lower()
        self.keys.add(key)
        if key == "space":
            self.on_tap("single")
        elif key == "b":
            self.on_shake()
        elif key == "c":
            self.hub.recentre()

    def _stick(self) -> tuple[float, float, str]:
        pendant = self.hub.stick()
        if pendant is not None:
            return pendant
        x = (1.0 if self.keys & {"right", "d"} else 0.0) - (1.0 if self.keys & {"left", "a"} else 0.0)
        y = (1.0 if self.keys & {"up", "w"} else 0.0) - (1.0 if self.keys & {"down", "s"} else 0.0)
        return x, y, "keys ← → ↑ ↓"

    def _finished(self) -> bool:
        return bool(getattr(self.game, "over", False))

    # --- loop ------------------------------------------------------------------------------

    def _tick(self) -> None:
        self._job = self.top.after(FRAME_MS, self._tick)  # first, so a drawing error cannot stop the loop
        x, y, label = self._stick()
        self.game.step(FRAME_MS / 1000, Stick(x, y, self.taps, self.shake))
        self.taps, self.shake = 0, False
        if self._finished() and self.over_at is None:
            self.over_at = time.monotonic()
            self._record()
        self.canvas.delete("dyn")
        getattr(self, f"_draw_{self.name}")()
        self._hud(label)
        self.flash = max(0, self.flash - 1)

    def _record(self) -> None:
        if self.recorded:
            return
        self.recorded = True
        if self.name == "marble":
            return
        self.hub.record_score(self.name, float(self.game.score))

    def _hud(self, label: str) -> None:
        c = self.canvas
        c.create_rectangle(0, H - 30, W, H, fill="#070b18", outline="", tags="dyn")
        help_text = {"marble": "tilt: roll · tap: brake · C: recentre", "dodger": "tilt: fly · tap: fire · shake (or B): bomb", "catch": "tilt: move basket · catch ★ · avoid ●"}[self.name]
        c.create_text(12, H - 15, anchor="w", text=f"steer: {label}   ·   {help_text}", fill="#9aa5c8", font=("Helvetica", 12), tags="dyn")
        if self._finished():
            c.create_rectangle(0, 0, W, H, fill="#b3261e", stipple="gray25", outline="", tags="dyn")
            c.create_text(W / 2, H / 2 - 30, text="Game over", fill="white", font=("Helvetica", 34, "bold"), tags="dyn")
            best = self.hub.best(self.name)
            c.create_text(W / 2, H / 2 + 14, text=f"score {self.game.score}  ·  best {int(best or 0)}  ·  tap to play again",
                          fill="white", font=("Helvetica", 16), tags="dyn")

    # --- Marble Maze -----------------------------------------------------------------------

    def _maze_geometry(self) -> tuple[float, float, float]:
        g = self.game
        cell = min((W - 60) / g.cols, (H - 90) / g.rows)
        ox = (W - cell * g.cols) / 2
        oy = 50 + (H - 90 - cell * g.rows) / 2
        return cell, ox, oy

    def _draw_marble(self) -> None:
        c, g = self.canvas, self.game
        cell, ox, oy = self._maze_geometry()
        if self.maze_level != g.level:  # walls are static per level: draw them once
            self.maze_level = g.level
            c.delete("maze")
            c.create_rectangle(ox, oy, ox + cell * g.cols, oy + cell * g.rows, fill="#121a33", outline="", tags="maze")
            gx, gy = g.goal
            c.create_rectangle(ox + gx * cell + 3, oy + gy * cell + 3, ox + (gx + 1) * cell - 3, oy + (gy + 1) * cell - 3,
                               fill="#1f6f46", outline="#3ddc84", width=2, tags="maze")
            c.create_text(ox + (gx + 0.5) * cell, oy + (gy + 0.5) * cell, text="⚑", fill="#c8ffd9", font=("Helvetica", int(cell * 0.5)), tags="maze")
            width = max(3, int(cell * 0.12))
            for row in range(g.rows):
                for col in range(g.cols):
                    walls = g.walls[row][col]
                    x0, y0, x1, y1 = ox + col * cell, oy + row * cell, ox + (col + 1) * cell, oy + (row + 1) * cell
                    for bit, line in ((WALL_N, (x0, y0, x1, y0)), (WALL_W, (x0, y0, x0, y1)), (WALL_S, (x0, y1, x1, y1)), (WALL_E, (x1, y0, x1, y1))):
                        if walls & bit:
                            c.create_line(*line, fill="#3d5bd9", width=width + 4, capstyle="round", tags="maze")
                            c.create_line(*line, fill="#8fb0ff", width=width, capstyle="round", tags="maze")
        px, py = ox + g.x * cell, oy + g.y * cell
        r = MARBLE_R * cell
        c.create_oval(px - r + 4, py - r + 6, px + r + 4, py + r + 6, fill="#070b18", outline="", tags="dyn")
        _ball(c, px, py, r, (255, 240, 170) if self.flash else (190, 120, 255))
        c.create_text(20, 22, anchor="w", text=f"Level {g.level}", fill="white", font=("Helvetica", 18, "bold"), tags="dyn")
        c.create_text(W - 20, 22, anchor="e", text=f"{g.elapsed:5.1f} s", fill="white", font=("Helvetica", 18, "bold"), tags="dyn")
        if g.won:
            if not self.recorded:
                self.recorded = True
                self.hub.record_score("marble", g.elapsed, lower_is_better=True)
            c.create_rectangle(0, H / 2 - 60, W, H / 2 + 60, fill="#0b3d24", stipple="gray50", outline="", tags="dyn")
            c.create_text(W / 2, H / 2 - 16, text=f"Level {g.level} cleared in {g.elapsed:.1f} s", fill="white", font=("Helvetica", 26, "bold"), tags="dyn")
            c.create_text(W / 2, H / 2 + 22, text="tap for a bigger maze", fill="#c8ffd9", font=("Helvetica", 16), tags="dyn")
        else:
            self.recorded = False

    # --- Star Dodger -----------------------------------------------------------------------

    def _draw_dodger(self) -> None:
        c, g = self.canvas, self.game
        scale = (H - 40) / FIELD_H
        ox = (W - FIELD_W * scale) / 2
        t = time.monotonic()
        for sx, sy, depth in self.stars:  # parallax starfield
            y = (sy + t * 40 * depth) % H
            c.create_oval(sx, y, sx + 1.5 * depth + 0.5, y + 1.5 * depth + 0.5, fill=_mix((60, 70, 110), (230, 235, 255), depth), outline="", tags="dyn")
        c.create_rectangle(ox, 0, ox + FIELD_W * scale, H - 30, outline="#27305a", tags="dyn")
        for rx, ry, rr, _speed in g.rocks:
            x, y, r = ox + rx * scale, ry * scale, rr * scale
            points = []
            for k in range(9):
                a = k / 9 * math.tau
                wobble = 0.8 + 0.2 * math.sin(k * 2.3 + rr)
                points += [x + math.cos(a) * r * wobble, y + math.sin(a) * r * wobble]
            c.create_polygon(points, fill="#7a6a5a", outline="#b8a48c", width=2, tags="dyn")
        for bx, by in g.bullets:
            x, y = ox + bx * scale, by * scale
            c.create_line(x, y, x, y + 10, fill="#7df9ff", width=3, tags="dyn")
        blink = g.hurt_s > 0 and int(g.hurt_s * 10) % 2 == 0
        if not blink:
            x, y, s = ox + g.x * scale, g.y * scale, SHIP_R * scale * 1.3
            c.create_polygon(x, y - s * 1.3, x - s, y + s, x, y + s * 0.5, x + s, y + s, fill="#ffc440", outline="#fff3c4", width=2, tags="dyn")
            c.create_oval(x - 4, y + s * 0.6, x + 4, y + s * 1.4, fill="#ff6b3d", outline="", tags="dyn")
        if g.flash_s > 0:
            c.create_rectangle(0, 0, W, H, fill="white", stipple="gray50", outline="", tags="dyn")
        c.create_text(20, 22, anchor="w", text=f"{g.score}", fill="white", font=("Helvetica", 22, "bold"), tags="dyn")
        c.create_text(W - 20, 22, anchor="e", text="♥" * g.lives, fill="#ff6b6b", font=("Helvetica", 20), tags="dyn")
        c.create_text(W - 20, 48, anchor="e", text=f"bombs {'◆' * g.bombs or '—'}  (shake)", fill="#ffb347", font=("Helvetica", 14, "bold"), tags="dyn")

    # --- Omi Catch -------------------------------------------------------------------------

    def _draw_catch(self) -> None:
        c, g = self.canvas, self.game
        sx, sy = W / CATCH_W, (H - 60) / 100.0
        for i in range(12):
            c.create_rectangle(0, i * H / 12, W, (i + 1) * H / 12 + 1, fill=_mix((12, 18, 44), (40, 30, 80), i / 11), outline="", tags="dyn")
        for x, y, _speed, bomb in g.drops:
            px, py = x * sx, 20 + y * sy
            if bomb:
                c.create_oval(px - 12, py - 12, px + 12, py + 12, fill="#222", outline="#ff4d4d", width=2, tags="dyn")
                c.create_line(px + 6, py - 10, px + 12, py - 20, fill="#ffb347", width=2, tags="dyn")
            else:
                c.create_text(px, py, text="★", fill="#ffd84d", font=("Helvetica", 30), tags="dyn")
        bx, by = g.basket * sx, 20 + 95 * sy
        half = BASKET_HALF * sx
        c.create_polygon(bx - half, by - 16, bx + half, by - 16, bx + half * 0.8, by + 12, bx - half * 0.8, by + 12,
                         fill="#c77d3a" if not self.flash else "#ffd08a", outline="#ffd08a", width=2, tags="dyn")
        c.create_text(20, 22, anchor="w", text=f"{g.score}", fill="white", font=("Helvetica", 22, "bold"), tags="dyn")
        streak = f"streak {g.streak}" if g.streak >= 5 else ""
        c.create_text(W / 2, 22, text=streak, fill="#ffd84d", font=("Helvetica", 16, "bold"), tags="dyn")
        c.create_text(W - 20, 22, anchor="e", text="✕" * g.misses + "○" * (3 - g.misses), fill="#ff8080", font=("Helvetica", 18), tags="dyn")

    def close(self) -> None:
        self.top.after_cancel(self._job)
        self.top.destroy()
        self.on_close()
