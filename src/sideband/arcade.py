"""Omi Arcade: a neon game menu played entirely with the pendant, and the mini game windows.

On open it calibrates motion (hold still, tilt right, tilt forward; after the first time just hold still),
and again, quickly, every time you come back from a game. Then the pendant is a menu joystick: flick it
toward a game to move one tile, one tap plays, a double tap goes to the next game (so taps alone work
without motion), hold recentres, and ⟲ (up from the top row) runs the full calibration. Every game shares
the same flow: one tap to start, resume or play again, double tap back to the Arcade, hold to pause.
The legend at the bottom (`legend.py`) always says what each control does right now.
"""

from __future__ import annotations

import math
import random
import subprocess
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
from sideband.legend import chip, draw_legend, legend, round_rect
from sideband.motion import Motion

if TYPE_CHECKING:
    from sideband.ui import Hub

# key, title, how to play, tile colours (top, bottom), icon
GAMES = (
    ("fighter", "SKY ACE 1943", "WWII dogfight · tilt to fly · tap fires · shake rolls", ("#ff9f1c", "#b8321a"), "plane"),
    ("flap", "OMI FLAP 3D", "tap to flap · tilt to steer", ("#3ad0ff", "#2250c8"), "ball"),
    ("corn", "CORN MAZE", "tilt to roll the pumpkin to the barn", ("#ffd23f", "#4f9e2f"), "corn"),
    ("dodger", "STAR DODGER", "tilt to fly · tap fires · shake bombs", ("#b56cff", "#4a1d9e"), "rocket"),
    ("catch", "OMI CATCH", "tilt the basket · catch stars · dodge bombs", ("#ff5fa2", "#a8166b"), "basket"),
    ("voice", "VOICE FLAP", "tap for the mic · say go left / right / up / down", ("#4dffb0", "#157a5a"), "bubble"),
)
AW, AH = 1040, 700
RECAL = len(GAMES)  # the ⟲ RECALIBRATE button, selectable like a tile
RECAL_BOX = (AW - 250, 20, AW - 24, 62)
REST_S = 1.0
QUICK_REST_S = 0.6
PINNED_S = 1.5
SOUNDS = {"move": "Pop", "back": "Bottle", "play": "Hero", "step": "Tink", "done": "Glass", "recal": "Purr"}


def sfx(name: str, enabled: bool = True) -> None:
    """A short macOS system sound, fire and forget."""
    if enabled and name in SOUNDS:
        try:
            subprocess.Popen(["afplay", "-v", "0.35", f"/System/Library/Sounds/{SOUNDS[name]}.aiff"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass


W, H = 760, 560
FRAME_MS = 16
MENU_MS = 33
NEON = "#ff4fd8"


def _mix(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> str:
    t = max(0.0, min(1.0, t))
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def _hex(colour: str) -> tuple[int, int, int]:
    return int(colour[1:3], 16), int(colour[3:5], 16), int(colour[5:7], 16)


def _ball(c: tk.Canvas, x: float, y: float, r: float, body: tuple[int, int, int], tag: str = "dyn") -> None:
    """Shaded sphere: rings from a dark rim to a lit spot up and to the left."""
    dark = tuple(int(v * 0.55) for v in body)
    for i in range(7):
        t = i / 6
        rr = r * (1 - 0.8 * t)
        ox = oy = -r * 0.3 * t
        colour = _mix(dark, body, t * 1.6) if t < 0.62 else _mix(body, (255, 255, 255), (t - 0.62) / 0.38)  # type: ignore[arg-type]
        c.create_oval(x + ox - rr, y + oy - rr, x + ox + rr, y + oy + rr, fill=colour, outline="", tags=tag)


def _icon(c: tk.Canvas, kind: str, x: float, y: float, s: float, tag: str) -> None:
    """Little vector art for each game, drawn at centre (x, y) and size s."""
    if kind == "plane":
        c.create_polygon(x - s, y + s * 0.1, x + s, y + s * 0.1, x + s * 0.9, y + s * 0.3, x - s * 0.9, y + s * 0.3, fill="#5a6b3c", outline="#2a3320", tags=tag)
        c.create_polygon(x - s * 0.18, y - s * 0.9, x + s * 0.18, y - s * 0.9, x + s * 0.22, y + s * 0.9, x - s * 0.22, y + s * 0.9, fill="#6b7d46", outline="#2a3320", tags=tag)
        c.create_polygon(x - s * 0.45, y + s * 0.75, x + s * 0.45, y + s * 0.75, x + s * 0.4, y + s * 0.9, x - s * 0.4, y + s * 0.9, fill="#5a6b3c", tags=tag)
        for r, col in ((0.22, "#1c3a8a"), (0.14, "#f2f2f2"), (0.07, "#c0282d")):
            for side in (-0.62, 0.62):
                c.create_oval(x + side * s - r * s, y + 0.2 * s - r * s, x + side * s + r * s, y + 0.2 * s + r * s, fill=col, outline="", tags=tag)
        c.create_oval(x - s * 0.5, y - s * 1.08, x + s * 0.5, y - s * 0.92, outline="#dddddd", tags=tag)
    elif kind == "ball":
        _ball(c, x, y, s * 0.7, (255, 196, 64), tag)
        for k in range(3):
            c.create_oval(x - s * 1.1 + k * s * 0.25, y + s * 0.2 - k * s * 0.1, x - s * 0.95 + k * s * 0.25, y + s * 0.35 - k * s * 0.1, fill="#fff3c4", outline="", tags=tag)
    elif kind == "corn":
        c.create_oval(x - s * 0.35, y - s * 0.95, x + s * 0.35, y + s * 0.75, fill="#ffd23f", outline="#c79a00", width=2, tags=tag)
        for row in range(6):
            for col in range(3):
                cx, cy = x - s * 0.2 + col * s * 0.2, y - s * 0.65 + row * s * 0.24
                c.create_oval(cx - s * 0.07, cy - s * 0.08, cx + s * 0.07, cy + s * 0.08, fill="#ffe680", outline="", tags=tag)
        c.create_polygon(x, y + s * 0.95, x - s * 0.75, y - s * 0.2, x - s * 0.2, y + s * 0.4, fill="#3fa34d", outline="#2a6e33", tags=tag)
        c.create_polygon(x, y + s * 0.95, x + s * 0.75, y - s * 0.2, x + s * 0.2, y + s * 0.4, fill="#4fbf5a", outline="#2a6e33", tags=tag)
    elif kind == "rocket":
        c.create_polygon(x, y - s, x + s * 0.4, y + s * 0.3, x - s * 0.4, y + s * 0.3, fill="#f2f2ff", outline="#9c8cff", width=2, tags=tag)
        c.create_polygon(x - s * 0.4, y + s * 0.3, x - s * 0.7, y + s * 0.7, x - s * 0.2, y + s * 0.4, fill="#ff5fa2", tags=tag)
        c.create_polygon(x + s * 0.4, y + s * 0.3, x + s * 0.7, y + s * 0.7, x + s * 0.2, y + s * 0.4, fill="#ff5fa2", tags=tag)
        c.create_oval(x - s * 0.15, y - s * 0.35, x + s * 0.15, y - s * 0.05, fill="#3ad0ff", outline="", tags=tag)
        c.create_polygon(x - s * 0.2, y + s * 0.35, x + s * 0.2, y + s * 0.35, x, y + s * 1.0, fill="#ffb347", tags=tag)
    elif kind == "basket":
        c.create_polygon(x - s * 0.8, y, x + s * 0.8, y, x + s * 0.6, y + s * 0.7, x - s * 0.6, y + s * 0.7, fill="#c77d3a", outline="#7a4a1c", width=2, tags=tag)
        for k in range(4):
            c.create_line(x - s * 0.7 + k * s * 0.47, y, x - s * 0.55 + k * s * 0.37, y + s * 0.7, fill="#7a4a1c", tags=tag)
        c.create_text(x, y - s * 0.55, text="★", fill="#ffd84d", font=("Helvetica", int(s * 1.1)), tags=tag)
    elif kind == "bubble":
        round_rect(c, x - s, y - s * 0.75, x + s, y + s * 0.45, s * 0.35, fill="#e9fff6", outline="#157a5a", width=2, tags=tag)
        c.create_polygon(x - s * 0.4, y + s * 0.4, x - s * 0.1, y + s * 0.4, x - s * 0.55, y + s * 0.9, fill="#e9fff6", outline="#157a5a", tags=tag)
        c.create_text(x, y - s * 0.15, text="go ◀ ▶", fill="#157a5a", font=("Helvetica", int(s * 0.42), "bold"), tags=tag)


WIZARD = (
    ("rest", "HOLD STILL", "Hold the Omi like a joystick, the way you'll play"),
    ("right", "TILT RIGHT ▶", "Tip the right side down and hold"),
    ("forward", "TILT FORWARD ▲", "Tip the far edge down and hold"),
)


class SnapNav:
    """Tilt as a menu joystick: a flick past FIRE moves one step, then come back past REARM for the next.

    Starts disarmed, so a pendant still tipped from the last game moves nothing until it is centred.
    """

    FIRE, REARM = 0.5, 0.25

    def __init__(self) -> None:
        self.armed = False

    def feed(self, x: float, y: float) -> tuple[int, int] | None:
        """(dx, dy) in screen steps (dy -1 is up, from tilting forward), or None."""
        reach = max(abs(x), abs(y))
        if not self.armed:
            self.armed = reach < self.REARM
            return None
        if reach < self.FIRE:
            return None
        self.armed = False
        return (1 if x > 0 else -1, 0) if abs(x) >= abs(y) else (0, -1 if y > 0 else 1)


def menu_step(selected: int, dx: int, dy: int, last: int, cols: int = 3, count: int = len(GAMES)) -> int:
    """Move the menu selection. Left / right run through the games and wrap; up from the top row
    reaches ⟲ RECALIBRATE; anything from ⟲ goes back to the last game."""
    if selected == RECAL:
        return RECAL if dy < 0 else last
    if dx:
        return (selected + dx) % count
    if dy < 0:
        return RECAL if selected < cols else selected - cols
    if dy > 0 and selected + cols < count:
        return selected + cols
    return selected


class ArcadeWindow:
    def __init__(self, hub: Hub) -> None:
        self.hub = hub
        self.top = tk.Toplevel(hub.root)
        self.top.title("Omi Arcade")
        self.top.resizable(False, False)
        self.top.protocol("WM_DELETE_WINDOW", self.close)
        self.canvas = tk.Canvas(self.top, width=AW, height=AH, highlightthickness=0, bg="#12002b")
        self.canvas.pack()
        self.selected = 0
        self.last_game = 0
        self.nav = SnapNav()
        self.pinned_since: float | None = None
        self.clock = 0.0
        self.toast: tuple[str, float] = ("", 0.0)
        self.stars = [(random.uniform(0, AW), random.uniform(0, AH * 0.55), random.uniform(0, math.tau)) for _ in range(120)]
        self.tiles: list[tuple[float, float, float, float]] = []
        self._layout()
        self.glow = list(self._box(self.selected))  # the selection frame, eased toward the chosen item
        self._background()
        self.top.bind("<KeyPress>", self._key)
        # Calibrate straight away: the full wizard the first time, then just "hold still".
        self._start_calibration(full=not self.hub.tilt_calibrated())
        self._last = time.monotonic()
        self._tick()

    # --- layout ---------------------------------------------------------------------------

    def _layout(self) -> None:
        cols, rows, gap = 3, 2, 26
        left, top, width, height = 60, 190, AW - 120, 400
        tw, th = (width - gap * (cols - 1)) / cols, (height - gap * (rows - 1)) / rows
        self.tiles = [(left + (i % cols) * (tw + gap), top + (i // cols) * (th + gap), tw, th) for i in range(len(GAMES))]

    def _box(self, item: int) -> tuple[float, float, float, float]:
        if item == RECAL:
            return RECAL_BOX
        x, y, w, h = self.tiles[item]
        return x, y, x + w, y + h

    def _background(self) -> None:
        c = self.canvas
        for i in range(28):
            y0 = i * AH * 0.6 / 28
            c.create_rectangle(0, y0, AW, y0 + AH * 0.6 / 28 + 1, fill=_mix((18, 0, 43), (120, 20, 110), i / 27), outline="", tags="bg")
        sun_y = AH * 0.6
        for i in range(12):  # striped synthwave sun sinking into the horizon
            r = 150
            y = sun_y - r + i * r * 2 / 12
            half = math.sqrt(max(0.0, r * r - (y - sun_y) ** 2))
            if i % 2 == 0 or i < 6:
                c.create_rectangle(AW / 2 - half, y, AW / 2 + half, y + r * 2 / 12 * (0.9 if i < 6 else 0.55),
                                   fill=_mix((255, 222, 89), (255, 60, 150), i / 11), outline="", tags="bg")
        c.create_rectangle(0, sun_y, AW, AH, fill="#0d0221", outline="", tags="bg")

    # --- the Omi --------------------------------------------------------------------------

    def on_tap(self, kind: str) -> None:
        if self.step is not None:
            if kind == "single":
                self._finish_calibration("Skipped: using the last calibration")
            return
        if kind == "single":  # forward: play the game (or recalibrate) under the frame
            if self.selected == RECAL:
                self.recalibrate()
            else:
                self._sfx("play")
                self.hub.open_game(GAMES[self.selected][0])
        else:  # the next game along; works with no motion at all
            self._select(self.selected + 1 if self.selected != RECAL else 0, wrap=True)
            self._toast(GAMES[self.selected][1])

    def on_hold(self) -> None:
        self._start_calibration(full=False)

    def recalibrate(self) -> None:
        self._start_calibration(full=True)

    def returned(self, game: str) -> None:
        """Back from a game: frame the game just played and recentre to the hand's new grip."""
        keys = [g[0] for g in GAMES]
        if game in keys:
            self.selected = self.last_game = keys.index(game)
        self._start_calibration(full=False, quick=True)

    def _start_calibration(self, full: bool, quick: bool = False) -> None:
        if self.hub.latest_motion() is not None or full:
            self._sfx("recal")
        now = time.monotonic()
        self.step, self.full, self.quick = 0, full, quick
        self.step_since = self.step_started = now
        self.nav = SnapNav()
        self.pinned_since = None

    def _select(self, item: int, wrap: bool = False) -> None:
        if wrap and item != RECAL:
            item %= len(GAMES)
        if item != self.selected:
            self.selected = item
            if item != RECAL:
                self.last_game = item
            self._sfx("move")
        else:
            self._sfx("back")  # an edge: nowhere further that way

    def _sfx(self, name: str) -> None:
        sfx(name, bool(self.hub.settings.get("arcade_sound", True)))

    def on_motion(self, sample: Motion) -> None:
        if self.step is None:
            return
        name = WIZARD[self.step][0]
        if name == "rest":
            still = math.sqrt(sample.gx ** 2 + sample.gy ** 2 + sample.gz ** 2) < 1.0
            if not still:
                self.step_since = time.monotonic()
            if time.monotonic() - self.step_since < (QUICK_REST_S if self.quick else REST_S):
                return
        elif not self.hub.tilt.learn(name, sample, min_deg=14.0):
            return
        if name == "rest":
            self.hub.tilt.learn("rest", sample)
        self.step += 1
        self.step_since = time.monotonic()
        if self.step >= len(WIZARD) or not self.full:
            if self.full:
                self.hub.save_tilt()
            self._sfx("done")
            self._finish_calibration("Centred ✓  flick the Omi to move · ● TAP to play" if not self.full
                                     else "Calibrated ✓  flick the Omi to move · ● TAP to play")
        else:
            self._sfx("step")

    def _finish_calibration(self, message: str) -> None:
        self.step = None
        self.nav = SnapNav()
        self._toast(message)

    def _toast(self, text: str) -> None:
        self.toast = (text, time.monotonic())

    def _key(self, event: tk.Event) -> None:
        key = event.keysym.lower()
        arrows = {"right": (1, 0), "left": (-1, 0), "up": (0, -1), "down": (0, 1)}
        if key in ("return", "space"):
            self.on_tap("single")
        elif key in ("escape", "backspace", "tab"):
            self.on_tap("double")
        elif key in arrows and self.step is None:
            self._select(menu_step(self.selected, *arrows[key], self.last_game))
        elif key == "c":
            self.recalibrate()
        elif key == "m":
            on = not self.hub.settings.get("arcade_sound", True)
            self.hub.set_setting("arcade_sound", on)
            self._toast("sound on" if on else "sound off")

    def refresh_scores(self) -> None:
        pass  # scores are read fresh every frame

    # --- drawing --------------------------------------------------------------------------

    def _tick(self) -> None:
        self._job = self.top.after(MENU_MS, self._tick)
        now = time.monotonic()
        dt, self._last = now - self._last, now
        self.clock += dt
        if self.step is not None and self.hub.latest_motion() is None and now - self.step_started > 1.5:
            self._finish_calibration("No motion stream · ● TAP plays · ●● DOUBLE goes to the next game")
        stick = self.hub.stick()
        if stick is not None and self.step is None:
            move = self.nav.feed(stick[0], stick[1])
            if move is not None:
                self._select(menu_step(self.selected, *move, self.last_game))
            self._auto_recentre(stick, now)
        target = self._box(self.selected)
        ease = min(1.0, dt * 14)
        self.glow = [g + (t - g) * ease for g, t in zip(self.glow, target)]
        c = self.canvas
        c.delete("dyn")
        self._grid()
        self._title()
        self._status()
        self._recal_button()
        for i, game in enumerate(GAMES):
            self._tile(i, game)
        self._frame()
        self._footer(stick)
        if self.step is not None:
            self._calibration()
        text, at = self.toast
        if text and now - at < 2.6:
            fade = min(1.0, (now - at) / 2.6)
            round_rect(c, AW / 2 - 330, 140, AW / 2 + 330, 178, 18, fill="#1b0540", outline=NEON, width=2, tags="dyn")
            c.create_text(AW / 2, 159, text=text, fill=_mix((255, 255, 255), (255, 79, 216), fade), font=("Helvetica", 16, "bold"), tags="dyn")

    def _auto_recentre(self, stick: tuple[float, float, str], now: float) -> None:
        """Tilt jammed at an edge while the hand is still: the grip changed, so recentre."""
        sample = self.hub.latest_motion()
        still = sample is not None and math.sqrt(sample.gx ** 2 + sample.gy ** 2 + sample.gz ** 2) < 0.5
        if max(abs(stick[0]), abs(stick[1])) > 0.85 and still:
            if self.pinned_since is None:
                self.pinned_since = now
            elif now - self.pinned_since > PINNED_S:
                self.hub.recentre()
                self.pinned_since = None
                self.nav = SnapNav()
                self._sfx("done")
                self._toast("Recentred to how you're holding it")
        else:
            self.pinned_since = None

    def _status(self) -> None:
        c, hub = self.canvas, self.hub
        connected = hub.status.get() == "connected"
        level = hub.battery_level
        parts = ["OMI"] + ([f"{level}%"] if level is not None else []) + (["⚡"] if hub.charging else [])
        parts.append("motion ✓" if hub.latest_motion() is not None else "no motion")
        text = "  ".join(parts) if connected else f"OMI {hub.status.get()}"
        round_rect(c, 24, 20, 24 + 30 + 10.5 * len(text), 62, 18, fill="#1b0540", outline="#3ddc84" if connected else "#ff6b6b", width=2, tags="dyn")
        c.create_oval(36, 36, 46, 46, fill="#3ddc84" if connected else "#ff6b6b", outline="", tags="dyn")
        c.create_text(54, 41, anchor="w", text=text, fill="#ffffff", font=("Helvetica", 13, "bold"), tags="dyn")

    def _recal_button(self) -> None:
        c = self.canvas
        x0, y0, x1, y1 = RECAL_BOX
        chosen = self.selected == RECAL
        round_rect(c, x0, y0, x1, y1, 20, fill="#ff4fd8" if chosen else "#1b0540", outline=NEON, width=2, tags="dyn")
        label = "⟲ RECALIBRATE" if chosen else "▲ ⟲ RECALIBRATE"
        c.create_text((x0 + x1) / 2, (y0 + y1) / 2, text=label, fill="#ffffff", font=("Helvetica", 15, "bold"), tags="dyn")

    def _frame(self) -> None:
        """The selection frame: neon rings that glide from item to item."""
        c = self.canvas
        x0, y0, x1, y1 = self.glow
        pulse = 2 + 2 * math.sin(self.clock * 6)
        for k, colour, width in ((10 + pulse, "#3a0a52", 4), (6 + pulse, NEON, 4), (2, "#ffffff", 3)):
            round_rect(c, x0 - k, y0 - k, x1 + k, y1 + k, 24, fill="", outline=colour, width=width, tags="dyn")

    def _grid(self) -> None:
        c, horizon = self.canvas, AH * 0.6
        for sx, sy, phase in self.stars:
            twinkle = 0.5 + 0.5 * math.sin(self.clock * 2 + phase)
            c.create_oval(sx, sy, sx + 2, sy + 2, fill=_mix((90, 60, 140), (255, 255, 255), twinkle), outline="", tags="dyn")
        offset = (self.clock * 0.9) % 1.0
        for k in range(14):
            t = (k + offset) / 14
            y = horizon + (AH - horizon) * t * t
            c.create_line(0, y, AW, y, fill=_mix((255, 79, 216), (60, 10, 90), 1 - t), width=2, tags="dyn")
        for k in range(-12, 13):
            c.create_line(AW / 2 + k * 18, horizon, AW / 2 + k * 160, AH, fill="#8a1fa0", width=2, tags="dyn")

    def _title(self) -> None:
        c = self.canvas
        bob = 4 * math.sin(self.clock * 2)
        for dx, dy, colour in ((5, 5, "#3a0060"), (-2, -2, "#00e5ff"), (2, 2, "#ff2bd6"), (0, 0, "#fff6ff")):
            c.create_text(AW / 2 + dx, 70 + dy + bob, text="OMI ARCADE", fill=colour, font=("Helvetica", 64, "bold italic"), tags="dyn")
        blink = int(self.clock * 2) % 2 == 0
        c.create_text(AW / 2, 124, text="★ PLAYED WITH YOUR PENDANT ★" if blink else "★ TILT · TAP · SHAKE · TALK ★",
                      fill="#ffe66d", font=("Helvetica", 16, "bold"), tags="dyn")

    def _tile(self, i: int, game: tuple) -> None:
        c = self.canvas
        key, title, how, (top_colour, bottom_colour), icon = game
        x0, y0, x1, y1 = self._box(i)
        chosen = i == self.selected
        dim = 0.0 if chosen else 0.45  # the others fade back so the chosen game pops
        top_rgb, bottom_rgb = (_hex(_mix(_hex(colour), (18, 0, 43), dim)) for colour in (top_colour, bottom_colour))
        steps = 10
        for s in range(steps):
            round_rect(c, x0, y0 + (y1 - y0) * s / steps, x1, y1, 22,
                       fill=_mix(top_rgb, bottom_rgb, s / (steps - 1)), outline="", tags="dyn")
        round_rect(c, x0, y0, x1, y1, 22, fill="", outline="#ffffff" if chosen else "#2b1150", width=3, tags="dyn")
        _icon(c, icon, x0 + 62, y0 + (y1 - y0) / 2 - 8, 42 if chosen else 34, "dyn")
        c.create_text(x0 + 118, y0 + 30, anchor="w", text=title, fill="#1a0033", font=("Helvetica", 19, "bold italic"), tags="dyn")
        c.create_text(x0 + 116, y0 + 28, anchor="w", text=title, fill="#ffffff", font=("Helvetica", 19, "bold italic"), tags="dyn")
        c.create_text(x0 + 118, y0 + 62, anchor="nw", text=how, fill="#fff8e6", width=x1 - x0 - 130, font=("Helvetica", 12, "bold"), tags="dyn")
        best = self.hub.best(key)
        badge = "NEW!" if best is None else (f"BEST {best:.1f}s" if key == "corn" else f"BEST {int(best):,}")
        round_rect(c, x1 - 118, y1 - 40, x1 - 14, y1 - 12, 12, fill="#1a0033", outline="", tags="dyn")
        c.create_text(x1 - 66, y1 - 26, text=badge, fill="#ffe66d", font=("Helvetica", 12, "bold"), tags="dyn")
        if chosen:
            chip(c, x0 + 16, y1 - 26, "tap", "PLAY", size=13)

    def _footer(self, stick: tuple[float, float, str] | None) -> None:
        """The legend: what every control does here, plus a little gauge of the live tilt."""
        c = self.canvas
        y0, y1 = AH - 84, AH - 18
        round_rect(c, 40, y0, AW - 40, y1, 26, fill="#1b0540", outline=NEON, width=2, tags="dyn")
        cy = (y0 + y1) / 2
        left = 40
        if stick is not None:
            gx, r = 92, 24
            c.create_oval(gx - r, cy - r, gx + r, cy + r, outline="#5a2a8a", width=2, tags="dyn")
            ring = r * SnapNav.FIRE
            c.create_oval(gx - ring, cy - ring, gx + ring, cy + ring, outline="#8a4ab0", dash=(2, 3), tags="dyn")
            dx, dy = stick[0] * r, -stick[1] * r
            colour = "#ff4fd8" if self.nav.armed else "#ffffff"
            c.create_line(gx, cy, gx + dx, cy + dy, fill=colour, width=3, tags="dyn")
            c.create_oval(gx + dx - 6, cy + dy - 6, gx + dx + 6, cy + dy + 6, fill=colour, outline="", tags="dyn")
            left = 130
        items = legend("menu", motion=stick is not None)
        draw_legend(c, (left + AW - 40) / 2, cy, items, size=16, max_width=AW - 40 - left - 30)
        c.create_text(AW - 44, AH - 7, anchor="e", text="keys: arrows move · space play · esc next · C recalibrate · M sound",
                      fill="#7a6a9a", font=("Helvetica", 10), tags="dyn")

    def _calibration(self) -> None:
        c = self.canvas
        name, big, small = WIZARD[self.step or 0]
        if self.quick:  # coming back from a game: a small card, not the whole wizard
            round_rect(c, AW / 2 - 250, AH / 2 - 70, AW / 2 + 250, AH / 2 + 70, 26, fill="#1b0540", outline="#3ddc84", width=4, tags="dyn")
            c.create_text(AW / 2, AH / 2 - 34, text="WELCOME BACK · RECENTRING", fill="#00e5ff", font=("Helvetica", 15, "bold"), tags="dyn")
            c.create_text(AW / 2, AH / 2 + 4, text="hold the Omi how you'll play…", fill="#ffffff", font=("Helvetica", 20, "bold"), tags="dyn")
            ring = (time.monotonic() - self.step_since) / QUICK_REST_S
            c.create_rectangle(AW / 2 - 180, AH / 2 + 36, AW / 2 + 180, AH / 2 + 46, outline="#3ddc84", tags="dyn")
            c.create_rectangle(AW / 2 - 180, AH / 2 + 36, AW / 2 - 180 + 360 * min(1.0, ring), AH / 2 + 46, fill="#3ddc84", outline="", tags="dyn")
            return
        c.create_rectangle(0, 0, AW, AH, fill="#0d0221", stipple="gray75", outline="", tags="dyn")
        total = len(WIZARD) if self.full else 1
        round_rect(c, AW / 2 - 330, AH / 2 - 170, AW / 2 + 330, AH / 2 + 170, 30, fill="#1b0540", outline=NEON, width=4, tags="dyn")
        c.create_text(AW / 2, AH / 2 - 128, text=f"CALIBRATING · STEP {(self.step or 0) + 1} OF {total}", fill="#00e5ff", font=("Helvetica", 16, "bold"), tags="dyn")
        for dx, colour in ((3, "#ff2bd6"), (0, "#ffffff")):
            c.create_text(AW / 2 + dx, AH / 2 - 70 + dx, text=big, fill=colour, font=("Helvetica", 44, "bold italic"), tags="dyn")
        c.create_text(AW / 2, AH / 2 - 20, text=small, fill="#ffe66d", font=("Helvetica", 17, "bold"), tags="dyn")
        # the pendant as a disc that tilts the way we want
        cx, cy = AW / 2, AH / 2 + 60
        wobble = math.sin(self.clock * 3)
        if name == "rest":
            ring = (time.monotonic() - self.step_since) / REST_S
            c.create_arc(cx - 46, cy - 46, cx + 46, cy + 46, start=90, extent=-360 * min(1.0, ring), style="arc", outline="#3ddc84", width=6, tags="dyn")
            c.create_oval(cx - 30, cy - 30, cx + 30, cy + 30, fill="#e8e8f0", outline="#9c8cff", width=3, tags="dyn")
        elif name == "right":
            tilt = 0.5 + 0.3 * wobble
            c.create_polygon(cx - 60, cy - 30 * tilt, cx + 60, cy + 30 * tilt, cx + 60, cy + 30 * tilt + 12, cx - 60, cy - 30 * tilt + 12,
                             fill="#e8e8f0", outline="#9c8cff", width=3, tags="dyn")
            c.create_text(cx + 110, cy, text="▶", fill=NEON, font=("Helvetica", 40, "bold"), tags="dyn")
        else:
            squash = 0.5 + 0.3 * wobble
            c.create_oval(cx - 60, cy - 30 * squash, cx + 60, cy + 30 * squash, fill="#e8e8f0", outline="#9c8cff", width=3, tags="dyn")
            c.create_text(cx, cy - 70, text="▲", fill=NEON, font=("Helvetica", 34, "bold"), tags="dyn")
        draw_legend(c, AW / 2, AH / 2 + 140, (("tap", "SKIP"),), size=14)

    def close(self) -> None:
        self.top.after_cancel(self._job)
        self.top.destroy()
        self.hub.window_closed(self)

    def lift(self) -> None:
        self.top.deiconify()
        self.top.lift()
        self.top.focus_force()


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
        if key in ("space", "return"):
            self.on_tap("single")
        elif key == "escape":
            self.on_hold() if self.state == "playing" else self.on_tap("double")
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
        draw_legend(c, W / 2, H - 17, legend(self.name, motion=label != "keys"), size=12, max_width=W - 24)
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
        draw_legend(c, W / 2, H / 2 + 46, legend(self.name, self.state), size=18)

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
            draw_legend(c, W / 2, H / 2 + 44, legend("corn", "won"), size=16)
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
        if g.flash_s > 0:
            c.create_rectangle(0, 0, W, H, fill="white", stipple="gray50", outline="", tags="dyn")
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
