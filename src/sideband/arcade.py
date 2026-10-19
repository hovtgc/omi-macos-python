"""Corn Maze, Star Dodger and Omi Catch. The shelf itself is `hub_view.ArcadeWindow`.

Every game shares one flow: confirm starts, resumes or plays again; cancel goes back to the shelf;
hold pauses. Confirm is a single tap, Enter or A. Cancel is a double tap, Esc or B.
"""

from __future__ import annotations

import math
import random
import time
import tkinter as tk
from typing import TYPE_CHECKING, Callable

from sideband.minigames import (
    BASKET_HALF,
    CATCH_W,
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
from sideband.legend import draw_ear, draw_legend, legend, round_rect
from sideband.platform import LIBRARY

if TYPE_CHECKING:
    from sideband.ui import Hub

# key, title, how to play, tile colours (top, bottom), icon. Same list the shelf draws.
GAMES = tuple((spec.key, spec.title, spec.blurb, spec.colors, spec.icon) for spec in LIBRARY)

W, H = 760, 560
FRAME_MS = 16


def _mix(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> str:
    t = max(0.0, min(1.0, t))
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * t) for x, y in zip(a, b))


class MiniGameWindow:
    """Corn Maze, Star Dodger and Omi Catch. The launcher calls on_tap / on_shake / on_hold."""

    TITLES = {"corn": "CORN MAZE", "dodger": "STAR DODGER", "catch": "OMI CATCH"}
    HOW = {
        "corn": "roll the pumpkin home to the red barn",
        "dodger": "dodge the rocks, blast them for points",
        "catch": "catch the ★ stars, dodge the bombs",
    }

    def __init__(self, hub: Hub, name: str, on_close: Callable[[], None]) -> None:
        self.hub, self.name, self.on_close = hub, name, on_close
        self.top = tk.Toplevel(hub.root)
        self.top.title(f"Omi Arcade · {self.TITLES[name].title()}")
        self.top.resizable(False, False)
        self.canvas = tk.Canvas(self.top, width=W, height=H, bg="#0b1022", highlightthickness=0)
        self.canvas.pack()
        self.keys: set[str] = set()
        self.taps = 0
        self.shake = False
        self.flash = 0
        self.recorded = False
        self.stars = [(random.uniform(0, W), random.uniform(0, H), random.uniform(0.3, 1.0)) for _ in range(90)]
        self.maze_level = 0
        self.top.bind("<KeyPress>", self._key_down)
        self.top.bind("<KeyRelease>", lambda e: self.keys.discard(e.keysym.lower()))
        self.canvas.bind("<Button-1>", lambda _e: self._pointer())
        self.top.protocol("WM_DELETE_WINDOW", self.close)
        self.new_game()
        self.top.focus_force()
        self._tick()

    def new_game(self) -> None:
        seed = random.randrange(1 << 30)
        self.game = {"corn": MarbleMaze, "dodger": StarDodger, "catch": Catch}[self.name](seed=seed)
        self.state = "ready"
        self.over_at = 0.0
        self.recorded, self.maze_level = False, 0
        self.canvas.delete("all")
        self.hub.recentre()

    @property
    def playing(self) -> bool:
        return self.state == "playing"

    # --- the Omi's buttons ----------------------------------------------------------------

    def on_tap(self, kind: str) -> None:
        """One tap: forward (start, resume, again, next level). Double tap: back to the Arcade."""
        forward = kind == "single"
        if self.state == "playing":
            if self.name == "corn" and self.game.won:
                self.game.next_level() if forward else self.close()
                return
            self.taps += 1 if forward else 2
            self.flash = 6
            return
        if not forward:
            self.close()  # back to the Arcade
            return
        if self.state == "over":
            if time.monotonic() - self.over_at < 0.8:
                return  # a late tap from play should not restart at once
            self.new_game()
        self.hub.recentre()  # start or resume from however you're holding it now
        self.state = "playing"

    def on_shake(self) -> None:
        if self.state == "playing":
            self.shake = True

    def on_hold(self) -> None:
        if self.state == "playing":
            self.state = "paused"

    def _key_down(self, event: tk.Event) -> None:
        key = event.keysym.lower()
        self.keys.add(key)
        self.hub.note_device("keys")
        # Arrows and WASD only steer. Space and Enter are the button, so holding W does not brake or fire.
        if key in ("space", "return"):
            self.on_tap("single")
        elif key == "x" and self.state == "playing":
            self.on_tap("double")
        elif key == "escape":
            self.on_hold() if self.state == "playing" else self.on_tap("double")
        elif key == "b" and self.state == "playing":
            self.on_shake()
        elif key == "c":
            self.hub.recentre()

    def _pointer(self) -> None:
        self.hub.note_device("keys")
        self.on_tap("single")

    def _stick(self) -> tuple[float, float, str]:
        pendant = self.hub.play_axes()
        if pendant is not None:
            return pendant
        x = (1.0 if self.keys & {"right", "d"} else 0.0) - (1.0 if self.keys & {"left", "a"} else 0.0)
        y = (1.0 if self.keys & {"up", "w"} else 0.0) - (1.0 if self.keys & {"down", "s"} else 0.0)
        return x, y, "keys"

    # --- loop -----------------------------------------------------------------------------

    def _tick(self) -> None:
        self._job = self.top.after(FRAME_MS, self._tick)  # first, so a drawing error cannot stop the loop
        x, y, label = self._stick()
        if self.state == "playing":
            self.game.step(FRAME_MS / 1000, Stick(x, y, self.taps, self.shake))
            if getattr(self.game, "over", False):
                self.state = "over"
                self.over_at = time.monotonic()
        self.taps, self.shake = 0, False
        if self.state == "over" and not self.recorded:
            self.recorded = True
            if hasattr(self.game, "score"):
                self.hub.record_score(self.name, float(self.game.score))
        self.canvas.delete("dyn")
        getattr(self, f"_draw_{self.name}")()
        self._hud(label)
        self.flash = max(0, self.flash - 1)

    def _hud(self, label: str) -> None:
        c = self.canvas
        c.create_rectangle(0, H - 34, W, H, fill="#070b18", outline="", tags="dyn")
        device = self.hub.active_device()
        draw_legend(c, W / 2, H - 17, legend(self.name, device=device, motion=device == "omi" and label != "keys"), size=12, max_width=W - 24)
        draw_ear(c, W - 10, H - 52, *self.hub.ear_state())
        colours = {"ready": "#ffd23f", "paused": "#7fd4ff", "over": "#ff6b5b"}
        if self.state not in colours:
            return
        title = {"ready": self.TITLES[self.name], "paused": "PAUSED", "over": "GAME OVER"}[self.state]
        sub = ""
        if self.state == "over" and hasattr(self.game, "score"):
            sub = f"score {self.game.score} · best {int(self.hub.best(self.name) or 0)}"
        elif self.state == "ready":
            sub = self.HOW[self.name]
        colour = colours[self.state]
        round_rect(c, W / 2 - 300, H / 2 - 100, W / 2 + 300, H / 2 + 86, 26, fill="#12002b", outline=colour, width=4, tags="dyn")
        for dx, col in ((3, "#000000"), (0, colour)):
            c.create_text(W / 2 + dx, H / 2 - 50 + dx, text=title, fill=col, font=("Helvetica", 40, "bold italic"), tags="dyn")
        if sub:
            c.create_text(W / 2, H / 2 + 2, text=sub, fill="#e8e8ff", font=("Helvetica", 15, "bold"), tags="dyn")
        draw_legend(c, W / 2, H / 2 + 46, legend(self.name, self.state, device=self.hub.active_device()), size=18)

    # --- Corn Maze ------------------------------------------------------------------------

    def _maze_geometry(self) -> tuple[float, float, float]:
        g = self.game
        cell = min((W - 110) / g.cols, (H - 140) / g.rows)
        ox = (W - cell * g.cols) / 2
        oy = 62 + (H - 140 - cell * g.rows) / 2
        return cell, ox, oy

    def _farm(self) -> None:
        """The static farm: grass, fence, sunflowers, dirt paths, corn rows, the barn. Drawn once a level."""
        c, g = self.canvas, self.game
        cell, ox, oy = self._maze_geometry()
        rng = random.Random(g.level)
        c.create_rectangle(0, 0, W, H, fill="#7ccf4a", outline="", tags="maze")
        c.create_rectangle(0, 0, W, 50, fill="#8fd4ff", outline="", tags="maze")
        c.create_oval(W - 110, -40, W - 10, 60, fill="#ffe66d", outline="", tags="maze")
        for _ in range(140):  # grass tufts
            x, y = rng.uniform(0, W), rng.uniform(52, H - 32)
            c.create_line(x, y, x - 3, y - 7, fill="#5aa83a", width=2, tags="maze")
            c.create_line(x, y, x + 3, y - 7, fill="#5aa83a", width=2, tags="maze")
        x0, y0, x1, y1 = ox, oy, ox + cell * g.cols, oy + cell * g.rows
        c.create_rectangle(x0 - 16, y0 - 16, x1 + 16, y1 + 16, fill="#d6a86b", outline="", tags="maze")  # dirt yard
        for row in range(g.rows):
            for col in range(g.cols):
                shade = "#c99656" if (row + col) % 2 else "#d0a060"
                c.create_rectangle(ox + col * cell, oy + row * cell, ox + (col + 1) * cell, oy + (row + 1) * cell, fill=shade, outline="", tags="maze")
        for k in range(int((x1 - x0 + 40) // 26) + 1):  # fence posts and rails
            px = x0 - 20 + k * 26
            for py in (y0 - 24, y1 + 14):
                c.create_rectangle(px, py, px + 6, py + 14, fill="#8a5a2b", outline="#5c3a18", tags="maze")
        for py in (y0 - 20, y0 - 13, y1 + 18, y1 + 25):
            c.create_line(x0 - 20, py, x1 + 24, py, fill="#a06b35", width=3, tags="maze")
        for sx, sy in ((28, 90), (30, H - 110), (W - 34, 120), (W - 30, H - 90), (40, H / 2), (W - 40, H / 2 + 30)):
            c.create_line(sx, sy + 8, sx, sy + 40, fill="#3f8a2a", width=3, tags="maze")
            for k in range(10):
                a = k / 10 * math.tau
                c.create_oval(sx + math.cos(a) * 10 - 5, sy + math.sin(a) * 10 - 5, sx + math.cos(a) * 10 + 5, sy + math.sin(a) * 10 + 5,
                              fill="#ffd23f", outline="", tags="maze")
            c.create_oval(sx - 6, sy - 6, sx + 6, sy + 6, fill="#6b3d12", outline="", tags="maze")
        width = max(6, int(cell * 0.26))
        for row in range(g.rows):  # corn rows on every wall
            for col in range(g.cols):
                walls = g.walls[row][col]
                ax, ay, bx, by = ox + col * cell, oy + row * cell, ox + (col + 1) * cell, oy + (row + 1) * cell
                for bit, line in ((WALL_N, (ax, ay, bx, ay)), (WALL_W, (ax, ay, ax, by)), (WALL_S, (ax, by, bx, by)), (WALL_E, (bx, ay, bx, by))):
                    if not walls & bit:
                        continue
                    c.create_line(*line, fill="#2f7d24", width=width + 4, capstyle="round", tags="maze")
                    c.create_line(*line, fill="#4fae34", width=width, capstyle="round", tags="maze")
                    steps = 3
                    for k in range(steps + 1):
                        px = line[0] + (line[2] - line[0]) * k / steps
                        py = line[1] + (line[3] - line[1]) * k / steps
                        c.create_oval(px - width * 0.22, py - width * 0.45, px + width * 0.22, py + width * 0.2, fill="#ffd23f", outline="#c79a00", tags="maze")
        c.create_text(ox + cell / 2, oy + cell * 0.18, text="START", fill="#5c3a18", font=("Helvetica", max(8, int(cell * 0.16)), "bold"), tags="maze")
        gx, gy = g.goal  # the red barn
        bx, by = ox + gx * cell + cell / 2, oy + gy * cell + cell / 2
        s = cell * 0.36
        c.create_rectangle(bx - s, by - s * 0.3, bx + s, by + s, fill="#c0282d", outline="#7a1216", width=2, tags="maze")
        c.create_polygon(bx - s * 1.15, by - s * 0.3, bx, by - s * 1.05, bx + s * 1.15, by - s * 0.3, fill="#8a1a1e", outline="#5a0e10", tags="maze")
        c.create_rectangle(bx - s * 0.42, by + s * 0.2, bx + s * 0.42, by + s, fill="#f4f0e6", outline="", tags="maze")
        c.create_line(bx - s * 0.42, by + s * 0.2, bx + s * 0.42, by + s, fill="#c0282d", width=2, tags="maze")
        c.create_line(bx + s * 0.42, by + s * 0.2, bx - s * 0.42, by + s, fill="#c0282d", width=2, tags="maze")

    def _draw_corn(self) -> None:
        c, g = self.canvas, self.game
        cell, ox, oy = self._maze_geometry()
        if self.maze_level != g.level:
            self.maze_level = g.level
            c.delete("maze")
            self._farm()
            c.tag_lower("maze")
        px, py = ox + g.x * cell, oy + g.y * cell
        r = MARBLE_R * cell * 1.05
        c.create_oval(px - r + 3, py - r * 0.2 + r * 0.9, px + r + 3, py + r * 0.35 + r * 0.9, fill="#8a6a3c", outline="", tags="dyn")
        spin = (g.x + g.y) * 2.2  # the pumpkin's ribs roll as it moves
        body = (255, 200, 90) if self.flash else (245, 128, 25)
        c.create_oval(px - r, py - r * 0.9, px + r, py + r * 0.9, fill=_mix(body, (120, 50, 0), 0.25), outline="#a34d00", width=2, tags="dyn")
        for k in range(-2, 3):
            offset = math.sin(spin + k * 0.7) * r * 0.55
            c.create_oval(px + offset - r * 0.35, py - r * 0.88, px + offset + r * 0.35, py + r * 0.88, outline="#c45f00", width=2, tags="dyn")
        c.create_oval(px - r * 0.45, py - r * 0.6, px - r * 0.05, py - r * 0.25, fill="#ffc07a", outline="", tags="dyn")
        c.create_rectangle(px - r * 0.12, py - r * 1.25, px + r * 0.12, py - r * 0.8, fill="#3f7a22", outline="", tags="dyn")
        c.create_text(20, 26, anchor="w", text=f"CORN MAZE · level {g.level}", fill="#1d4d12", font=("Helvetica", 20, "bold italic"), tags="dyn")
        c.create_text(W - 20, 26, anchor="e", text=f"⏱ {g.elapsed:5.1f} s", fill="#1d4d12", font=("Helvetica", 20, "bold"), tags="dyn")
        if g.won:
            if not self.recorded:
                self.recorded = True
                self.hub.record_score("corn", g.elapsed, lower_is_better=True)
            round_rect(c, W / 2 - 290, H / 2 - 90, W / 2 + 290, H / 2 + 80, 24, fill="#fff4d6", outline="#c0282d", width=4, tags="dyn")
            c.create_text(W / 2, H / 2 - 44, text="HOME TO THE BARN!", fill="#c0282d", font=("Helvetica", 32, "bold italic"), tags="dyn")
            c.create_text(W / 2, H / 2 - 4, text=f"level {g.level} in {g.elapsed:.1f} s", fill="#5c3a18", font=("Helvetica", 16, "bold"), tags="dyn")
            round_rect(c, W / 2 - 275, H / 2 + 22, W / 2 + 275, H / 2 + 66, 20, fill="#12002b", outline="", tags="dyn")
            draw_legend(c, W / 2, H / 2 + 44, legend("corn", "won", device=self.hub.active_device()), size=16)
        else:
            self.recorded = False

    # --- Star Dodger ----------------------------------------------------------------------

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
        if g.flash_s > 0:  # the bomb: a shockwave ring out from the ship
            t = 1 - g.flash_s / 0.35
            x, y, r = ox + g.x * scale, g.y * scale, 30 + t * W
            for k, colour, width in ((0, "#ffffff", 6), (14, "#ffb347", 4), (28, "#ff5fa2", 2)):
                c.create_oval(x - r + k, y - r + k, x + r - k, y + r - k, outline=colour, width=width, tags="dyn")
        c.create_text(20, 22, anchor="w", text=f"{g.score}", fill="white", font=("Helvetica", 22, "bold"), tags="dyn")
        c.create_text(W - 20, 22, anchor="e", text="♥" * g.lives, fill="#ff6b6b", font=("Helvetica", 20), tags="dyn")
        c.create_text(W - 20, 48, anchor="e", text=f"bombs {'◆' * g.bombs or '—'}  (shake)", fill="#ffb347", font=("Helvetica", 14, "bold"), tags="dyn")

    # --- Omi Catch ------------------------------------------------------------------------

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


# The home screen lives in hub_view. Re-exported so `from sideband.arcade import ArcadeWindow` keeps working.
from sideband.hub_view import ArcadeWindow  # noqa: E402
