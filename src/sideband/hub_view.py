"""The home screen: a sideways shelf of big game cards, the way a console does it.

Keyboard and mouse are the main way through: arrows or A/D, Enter, Esc, the wheel, hover and click.
A single Omi tap moves to the next card, a double tap goes back, a hold launches. A gamepad's stick
or d-pad moves, A launches, B goes back, Start opens settings. The gear in the corner is the same
menu, and it is not a card on the row. Saying "play sky ace" or "settings" still works.

Card art is drawn here. Nothing is fetched.
"""

from __future__ import annotations

import math
import subprocess
import time
import tkinter as tk
from typing import TYPE_CHECKING

from sideband.legend import draw_legend, draw_meter, draw_mic, legend, round_rect
from sideband.platform import LIBRARY, SYSTEM, Shelf, game, pixels, score_badge, shelf_slots

if TYPE_CHECKING:
    from sideband.ui import Hub

AW, AH = 1240, 760
CARD_W, CARD_H = 300, 430
GAP = 26
MENU_MS = 33
NEON = "#ff4fd8"
SOUNDS = {"move": "Pop", "back": "Bottle", "play": "Hero", "step": "Tink", "done": "Glass", "recal": "Purr"}
WIZARD = (
    ("rest", "HOLD IT HOW YOU PLAY", "get comfy, like a joystick, then tap once to lock it in"),
    ("right", "TILT RIGHT", "tip the right side down, keep it there, then tap"),
    ("forward", "TILT FORWARD", "tip the far edge down, keep it there, then tap"),
)
MIN_TILT_DEG = 8.0


def sfx(name: str, enabled: bool = True) -> None:
    if enabled and name in SOUNDS:
        try:
            subprocess.Popen(
                ["afplay", "-v", "0.35", f"/System/Library/Sounds/{SOUNDS[name]}.aiff"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except OSError:
            pass


def _mix(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> str:
    t = max(0.0, min(1.0, t))
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def _hex(colour: str) -> tuple[int, int, int]:
    return int(colour[1:3], 16), int(colour[3:5], 16), int(colour[5:7], 16)


def pixel_text(c: tk.Canvas, text: str, x: float, y: float, scale: int, fill: str, tag: str, anchor: str = "center") -> float:
    """Chunky bitmap letters. Returns the width drawn."""
    width, height, pts = pixels(text)
    px_w = max(width, 1) * scale
    px_h = height * scale
    ox = x - px_w / 2 if anchor == "center" else x
    oy = y - px_h / 2
    for gx, gy in pts:
        c.create_rectangle(
            ox + gx * scale, oy + gy * scale,
            ox + (gx + 1) * scale - max(1, scale // 5), oy + (gy + 1) * scale - max(1, scale // 5),
            fill=fill, outline="", tags=tag,
        )
    return px_w


def _keyart(c: tk.Canvas, key: str, x0: float, y0: float, x1: float, y1: float, tag: str) -> None:
    """A little scene for one card, drawn inside the card. Local geometry only."""
    w, h = x1 - x0, y1 - y0
    cx, cy = (x0 + x1) / 2, y0 + h * 0.38
    if key == "fighter":
        c.create_polygon(x0, y0 + h * 0.62, cx, y0 + h * 0.28, x1, y0 + h * 0.62, fill="#ffb347", outline="", tags=tag)
        c.create_rectangle(x0, y0 + h * 0.62, x1, y1, fill="#12305f", outline="", tags=tag)
        c.create_polygon(cx, cy - 36, cx + 54, cy + 10, cx - 8, cy + 4, fill="#f4f1e4", outline="#1b1b1b", width=2, tags=tag)
        c.create_polygon(cx - 8, cy + 4, cx + 18, cy + 8, cx - 20, cy + 22, fill="#c9c3b0", outline="", tags=tag)
        c.create_oval(cx + 28, cy - 4, cx + 40, cy + 6, fill="#1c3a8a", outline="", tags=tag)
    elif key == "flap":
        for i, shade in enumerate(("#1a3c9c", "#2a5ad4", "#3ad0ff")):
            inset = 18 + i * 22
            c.create_rectangle(x0 + inset, y0 + 24 + i * 8, x1 - inset, y0 + h * 0.72 - i * 6, outline=shade, width=6, tags=tag)
        c.create_oval(cx - 22, cy - 10, cx + 22, cy + 34, fill="#ffc440", outline="#a85a10", width=2, tags=tag)
    elif key == "corn":
        c.create_rectangle(x0, y0 + h * 0.55, x1, y1, fill="#7ccf4a", outline="", tags=tag)
        for col in range(6):
            bx = x0 + 28 + col * (w - 56) / 5
            c.create_rectangle(bx, y0 + 70, bx + 18, y0 + h * 0.62, fill="#ffd23f", outline="#c79a00", tags=tag)
        c.create_oval(cx - 26, cy + 20, cx + 26, cy + 68, fill="#f08020", outline="#a34d00", width=2, tags=tag)
        c.create_rectangle(cx - 4, cy + 8, cx + 4, cy + 28, fill="#2f7a22", outline="", tags=tag)
    elif key == "dodger":
        for i in range(18):
            sx = x0 + (i * 47 % int(w - 20)) + 8
            sy = y0 + 20 + (i * 29 % int(h * 0.5))
            c.create_oval(sx, sy, sx + 3, sy + 3, fill="#ffffff", outline="", tags=tag)
        c.create_polygon(cx, cy - 40, cx + 22, cy + 28, cx, cy + 12, cx - 22, cy + 28, fill="#f2f2ff", outline="#9c8cff", width=2, tags=tag)
        c.create_polygon(cx - 10, cy + 24, cx + 10, cy + 24, cx, cy + 48, fill="#ffb347", outline="", tags=tag)
    elif key == "catch":
        for i, px in enumerate((cx - 50, cx, cx + 46)):
            c.create_text(px, y0 + 70 + i * 18, text="★", fill="#ffd84d", font=("Helvetica", 22), tags=tag)
        c.create_polygon(cx - 50, cy + 40, cx + 50, cy + 40, cx + 36, cy + 78, cx - 36, cy + 78, fill="#c77d3a", outline="#7a4a1c", width=2, tags=tag)
    elif key == "voice":
        round_rect(c, cx - 70, cy - 36, cx + 70, cy + 28, 18, fill="#e9fff6", outline="#157a5a", width=3, tags=tag)
        c.create_polygon(cx - 20, cy + 24, cx, cy + 24, cx - 36, cy + 58, fill="#e9fff6", outline="#157a5a", tags=tag)
        c.create_text(cx, cy - 4, text="go", fill="#157a5a", font=("Helvetica", 28, "bold"), tags=tag)
    elif key == "beat":
        c.create_line(x0 + 24, y0 + h * 0.62, x1 - 24, y0 + h * 0.62, fill="#ff4d6d", width=4, tags=tag)
        for i, bh in enumerate((30, 58, 40, 72, 36, 64, 28)):
            bx = x0 + 36 + i * 34
            c.create_rectangle(bx, y0 + h * 0.62 - bh, bx + 18, y0 + h * 0.62, fill="#ffd1dc" if i == 3 else "#ff4d6d", outline="", tags=tag)
    elif key == "draw":
        c.create_oval(cx - 58, cy - 48, cx + 58, cy + 68, outline="#ffe66d", width=6, tags=tag)
        c.create_oval(cx - 28, cy - 18, cx + 28, cy + 38, outline="#ffffff", width=4, tags=tag)
        c.create_oval(cx - 8, cy + 2, cx + 8, cy + 18, fill="#ff4d6d", outline="", tags=tag)
    elif key == "dash":
        c.create_rectangle(x0, y0 + h * 0.7, x1, y1, fill="#12362a", outline="", tags=tag)
        c.create_line(x0, y0 + h * 0.7, x1, y0 + h * 0.7, fill="#3ddc84", width=3, tags=tag)
        c.create_rectangle(x0 + 48, y0 + h * 0.7 - 36, x0 + 72, y0 + h * 0.7, fill="#eafff4", outline="", tags=tag)
        c.create_rectangle(x1 - 90, y0 + h * 0.7 - 28, x1 - 58, y0 + h * 0.7, fill="#ffb020", outline="", tags=tag)
    elif key == "simon":
        c.create_oval(cx - 62, cy - 20, cx - 8, cy + 40, fill="#3ddc84", outline="#08321c", width=3, tags=tag)
        c.create_oval(cx + 8, cy - 20, cx + 62, cy + 40, fill="#ffb020", outline="#3a2400", width=3, tags=tag)
        c.create_text(cx, cy + 62, text="1    2", fill="#ffffff", font=("Helvetica", 14, "bold"), tags=tag)
    else:
        c.create_oval(cx - 30, cy - 30, cx + 30, cy + 30, fill="#ffffff", outline="", tags=tag)


class ArcadeWindow:
    """Console home. The launcher calls on_tap, on_hold, on_speech, on_intent and on_motion."""

    def __init__(self, hub: Hub) -> None:
        self.hub = hub
        self.shelf = Shelf()
        self.top = tk.Toplevel(hub.root)
        self.top.title("Omi Arcade")
        self.top.resizable(False, False)
        self.top.protocol("WM_DELETE_WINDOW", self.close)
        self.canvas = tk.Canvas(self.top, width=AW, height=AH, highlightthickness=0, bg="#07010f", cursor="hand2")
        self.canvas.pack()
        self.focus = 0.0
        self.mode = "idle"
        self.heard = ""
        self.think_since = 0.0
        self.clock = 0.0
        self.toast: tuple[str, float] = ("", 0.0)
        self.step: int | None = None
        self.step_started = 0.0
        self.card_hits: list[tuple[int, tuple[float, float, float, float]]] = []
        self.row_hits: list[tuple[float, float, float, float]] = []
        self.recent_hits: list[tuple[str, tuple[float, float, float, float]]] = []
        self.gear_box = (AW - 78, 18, AW - 22, 74)
        self.status_lines: list[str] = []
        self._moved = 0.0
        self._tilt_at = 0.0
        self.level = 0.0
        self._background()
        self.top.bind("<KeyPress>", self._key)
        self.canvas.bind("<Button-1>", self._click)
        self.canvas.bind("<Motion>", self._hover)
        for widget in (self.top, self.canvas):
            widget.bind("<MouseWheel>", self._wheel)
            widget.bind("<Button-4>", self._wheel)
            widget.bind("<Button-5>", self._wheel)
        self.top.bind("<Tab>", lambda _e: self._tab())
        self._last = time.monotonic()
        self._tick()

    # --- input ---------------------------------------------------------------------------------

    def on_tap(self, kind: str) -> None:
        if self.step is not None:
            if kind == "single":
                self._lock()
            else:
                self._finish_calibration("Kept the last calibration")
            return
        self.hub.note_device("omi")
        if kind == "single":
            self._move(1)
        else:
            self._back()

    def on_hold(self) -> None:
        if self.step is not None:
            return
        self.hub.note_device("omi")
        self._activate()

    def move(self, delta: int) -> None:
        self._move(delta)

    def back(self) -> None:
        self._back()

    def activate(self) -> None:
        self._activate()

    def open_system(self) -> None:
        if self.shelf.page == "games":
            self.shelf.open_page("system")
            self._sfx("step")

    def _tab(self) -> str:
        self.hub.note_device("keys")
        if self.shelf.page == "games":
            self.open_system()
        else:
            self._back()
        return "break"

    def _move(self, delta: int) -> None:
        now = time.monotonic()
        if now - self._moved < 0.12:
            return
        self._moved = now
        before = (self.shelf.index, self.shelf.sub, self.shelf.page)
        self.shelf.move(delta, self._page_count())
        if (self.shelf.index, self.shelf.sub, self.shelf.page) != before:
            self._sfx("move")

    def _back(self) -> None:
        self._sfx("back")
        self.shelf.back()

    def _activate(self) -> None:
        action = self.shelf.activate()
        self._sfx("play")
        if action.startswith("play:"):
            self.hub.open_game(action.split(":", 1)[1])
            return
        if action.startswith("sys:"):
            self._open_setting(action.split(":", 1)[1])
            return
        if action.startswith("pad:"):
            self._pick_controller(int(action.split(":", 1)[1]))

    def _open_setting(self, key: str) -> None:
        if key == "controllers":
            self.shelf.open_page("controllers")
        elif key == "status":
            self._load_status()
            self.shelf.open_page("status")
        elif key == "ai":
            self.hub.open_ai()
        elif key == "log":
            self.hub.show()
        else:
            self.hub.open(key)

    def _pick_controller(self, index: int) -> None:
        rows = self._controller_rows()
        if not 0 <= index < len(rows):
            return
        ident, title, _blurb = rows[index]
        if ident == "need":
            self._toast("Gamepads need pygame:  uv pip install -e '.[gamepad]'")
            return
        if ident.startswith("name:"):
            self.hub.set_controller("pad", ident.split(":", 1)[1])
        else:
            self.hub.set_controller(ident)
        self._toast(f"Playing with {title.title()}")

    def _page_count(self) -> int:
        if self.shelf.page == "controllers":
            return len(self._controller_rows())
        return self.shelf.count_for()

    def _controller_rows(self) -> list[tuple[str, str, str]]:
        rows = [
            ("auto", "AUTO", "Legend follows whatever you used last"),
            ("keys", "KEYBOARD AND MOUSE", "Arrows, Enter, Esc, scroll wheel"),
            ("omi", "OMI PENDANT", "Tap next · double back · hold play"),
        ]
        names = self.hub.pad_names()
        if not names and not self.hub.pads_ready():
            rows.append(("need", "NO GAMEPAD LIBRARY", "Install the gamepad extra (pygame) for Xbox, PlayStation and others"))
        for name in names:
            rows.append((f"name:{name}", name.upper(), "Hot-plugged. Hold or Enter to use this one."))
        return rows

    def _load_status(self) -> None:
        from sideband.doctor import report

        lines, ok = report(self.hub.app)
        self.status_lines = (["All required checks pass.", ""] if ok else ["Something still needs doing.", ""]) + lines

    def on_speech(self, text: str, final: bool) -> None:
        """The mic stays open on the shelf, so naming a game is enough. No tap-to-talk first."""
        if self.step is not None or self.mode == "thinking":
            self.heard = text
            return
        self.heard = text
        if final and text.strip():
            self.mode, self.think_since = "thinking", time.monotonic()
            self.hub.arcade_intent(text, self.shelf.keys[self.shelf.index])

    def on_intent(self, intent: str, heard: str) -> None:
        if self.mode != "thinking":
            return
        self.mode = "idle"
        verb, _, key = intent.partition(":")
        if verb in ("play", "show") and game(key) is not None:
            self.shelf.focus_key(key)
            spec = game(key)
            assert spec is not None
            if verb == "play":
                self._sfx("play")
                self._toast(f"▶  {spec.title}")
                self.hub.open_game(key)
            else:
                self._toast(f"{spec.title} · {spec.blurb}")
        elif intent == "recalibrate":
            self.recalibrate()
        elif intent == "settings":
            self.shelf.open_page("system")
            self._toast("Settings")
        elif intent == "close":
            self.close()
        elif intent == "help":
            self._toast("Arrows move · Enter plays · or say “play sky ace” · “settings”")
        else:
            self._sfx("back")
            self._toast(f"Heard “{heard}” · try a game name, or “settings”")

    def _key(self, event: tk.Event) -> None:
        key = event.keysym.lower()
        if key == "tab":
            return
        self.hub.note_device("keys")
        if self.step is not None:
            if key in ("space", "return"):
                self._lock()
            elif key == "escape":
                self._finish_calibration("Kept the last calibration")
            return
        if key in ("left", "a", "up", "w"):
            self._move(-1)
        elif key in ("right", "d", "down", "s"):
            self._move(1)
        elif key in ("return", "space"):
            self._activate()
        elif key == "escape":
            self._back()

    def _wheel(self, event: tk.Event) -> None:
        self.hub.note_device("keys")
        number = getattr(event, "num", None)
        delta = getattr(event, "delta", 0)
        self._move(-1 if number == 4 or delta > 0 else 1)

    def _click(self, event: tk.Event) -> None:
        self.hub.note_device("keys")
        if self.step is not None:
            self._lock()
            return
        x0, y0, x1, y1 = self.gear_box
        if x0 <= event.x <= x1 and y0 <= event.y <= y1:
            if self.shelf.page == "games":
                self.open_system()
            else:
                self._back()
            return
        if self.shelf.page != "games":
            for i, box in enumerate(self.row_hits):
                if box[0] <= event.x <= box[2] and box[1] <= event.y <= box[3]:
                    self.shelf.sub = i
                    self._activate()
            return
        for key, box in self.recent_hits:
            if box[0] <= event.x <= box[2] and box[1] <= event.y <= box[3]:
                self.shelf.focus_key(key)
                self._activate()
                return
        for i, box in reversed(self.card_hits):
            if box[0] <= event.x <= box[2] and box[1] <= event.y <= box[3]:
                self.shelf.index = i
                self._activate()
                return

    def _hover(self, event: tk.Event) -> None:
        if self.step is not None:
            return
        if self.shelf.page != "games":
            for i, box in enumerate(self.row_hits):
                if box[0] <= event.x <= box[2] and box[1] <= event.y <= box[3] and i != self.shelf.sub:
                    self.shelf.sub = i
                    self.hub.note_device("keys")
                    self._sfx("move")
            return
        for i, box in reversed(self.card_hits):
            if box[0] <= event.x <= box[2] and box[1] <= event.y <= box[3]:
                if i != self.shelf.index:
                    self.shelf.index = i
                    self.hub.note_device("keys")
                    self._sfx("move")
                return

    def returned(self, name: str) -> None:
        self.shelf.focus_key(name)
        self.mode = "idle"

    def refresh_scores(self) -> None:
        pass  # the shelf reads the scorebook while it draws

    def _sfx(self, name: str) -> None:
        sfx(name, bool(self.hub.settings.get("arcade_sound", True)))

    def _toast(self, text: str) -> None:
        self.toast = (text, time.monotonic())

    # --- calibration, still optional: say "recalibrate" ----------------------------------------

    def recalibrate(self) -> None:
        self._sfx("recal")
        self.mode = "idle"
        self.step = 0
        self.step_started = time.monotonic()

    def _lock(self) -> None:
        sample = self.hub.steady_motion()
        if sample is None:
            self._finish_calibration("No motion stream: tilt games need the motion firmware")
            return
        name = WIZARD[self.step or 0][0]
        if name != "rest" and not self.hub.tilt.learn(name, sample, min_deg=MIN_TILT_DEG):
            self._sfx("back")
            self._toast("A little further, hold it, then tap")
            return
        if name == "rest":
            self.hub.tilt.learn("rest", sample)
        self.step = (self.step or 0) + 1
        if self.step >= len(WIZARD):
            self.hub.save_tilt()
            self._sfx("done")
            self._finish_calibration("Calibrated. Arrows, a tap, or say what to play.")
        else:
            self._sfx("step")

    def _step_degrees(self) -> float | None:
        sample = self.hub.latest_motion()
        return None if sample is None else self.hub.tilt.degrees_from_rest(sample)

    def on_motion(self, sample: object) -> None:
        if self.step is not None or self.shelf.page != "games":
            return
        tilt_x = self.hub.tilt.x
        now = time.monotonic()
        if abs(tilt_x) >= 0.62 and now - self._tilt_at > 0.45:
            self._tilt_at = now
            self.hub.note_device("omi")
            self._move(1 if tilt_x > 0 else -1)

    def _finish_calibration(self, message: str) -> None:
        self.step = None
        self._toast(message)

    # --- drawing -------------------------------------------------------------------------------

    def _tick(self) -> None:
        self._job = self.top.after(MENU_MS, self._tick)
        now = time.monotonic()
        dt, self._last = min(0.05, now - self._last), now
        self.clock += dt
        if self.mode == "thinking" and now - self.think_since > 8:
            self.mode = "idle"
        self.focus += (self.shelf.index - self.focus) * min(1.0, dt * 9)
        c = self.canvas
        c.delete("dyn")
        self.card_hits, self.row_hits, self.recent_hits = [], [], []
        self._floor()
        self._header()
        if self.shelf.page == "games":
            self._recent()
            self._cards()
        else:
            self._blade()
        self._footer(now)
        self._gear()
        if self.step is not None:
            self._calibration()
        text, at = self.toast
        if text and now - at < 3.2:
            round_rect(c, AW / 2 - 340, 148, AW / 2 + 340, 186, 16, fill="#1b0540", outline=NEON, width=2, tags="dyn")
            c.create_text(AW / 2, 167, text=text, fill="#ffffff", font=("Helvetica", 14, "bold"), tags="dyn")
        # A CRT veil: one stippled black sheet, plus a bright line so it reads as scanlines.
        c.create_rectangle(0, 0, AW, AH, fill="#000000", stipple="gray12", outline="", tags="dyn")
        scan = int(self.clock * 40) % AH
        c.create_line(0, scan, AW, scan, fill="#ffffff", stipple="gray25", tags="dyn")

    def _background(self) -> None:
        c = self.canvas
        for i in range(24):
            y0 = i * AH / 24
            c.create_rectangle(0, y0, AW, y0 + AH / 24 + 1, fill=_mix((8, 0, 22), (48, 8, 64), i / 23), outline="", tags="bg")
        c.create_oval(AW / 2 - 180, AH * 0.42, AW / 2 + 180, AH * 0.42 + 200, fill="#ff4d8d", outline="", tags="bg")
        c.create_rectangle(0, AH * 0.55, AW, AH, fill="#07010f", outline="", tags="bg")

    def _floor(self) -> None:
        c, horizon = self.canvas, AH * 0.55
        for k in range(8):
            t = (k + (self.clock * 0.35) % 1) / 8
            y = horizon + (AH - horizon) * t * t
            c.create_line(0, y, AW, y, fill="#5a146e", tags="dyn")
        for k in range(-8, 9):
            c.create_line(AW / 2 + k * 40, horizon, AW / 2 + k * 220, AH, fill="#3a0a48", tags="dyn")

    def _header(self) -> None:
        c = self.canvas
        bob = 3 * math.sin(self.clock * 2)
        pixel_text(c, "OMI ARCADE", AW / 2 + 4, 58 + bob, 5, "#ff2bd6", "dyn")
        pixel_text(c, "OMI ARCADE", AW / 2 - 3, 56 + bob, 5, "#7ef9ff", "dyn")
        pixel_text(c, "OMI ARCADE", AW / 2, 55 + bob, 5, "#fff6ff", "dyn")
        connected = self.hub.status.get() == "connected"
        level = self.hub.battery_level
        bits = ["OMI"] + ([f"{level}%"] if level is not None else [])
        bits.append("LINKED" if connected else self.hub.status.get().upper())
        c.create_text(28, 36, anchor="w", text="  ".join(bits), fill="#3ddc84" if connected else "#ff8fa3", font=("Helvetica", 12, "bold"), tags="dyn")

    def _gear(self) -> None:
        c = self.canvas
        x0, y0, x1, y1 = self.gear_box
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        on = self.shelf.page != "games"
        c.create_oval(x0, y0, x1, y1, fill="#1b0540", outline="#ffe66d" if on else NEON, width=3, tags="dyn")
        c.create_oval(cx - 8, cy - 8, cx + 8, cy + 8, outline="#ffe66d", width=3, tags="dyn")
        for k in range(8):
            a = k / 8 * math.tau + self.clock * 0.4
            c.create_line(cx + math.cos(a) * 10, cy + math.sin(a) * 10, cx + math.cos(a) * 18, cy + math.sin(a) * 18, fill="#ffe66d", width=3, tags="dyn")
        c.create_text(cx, y1 + 12, text="TAB", fill="#ffe66d", font=("Helvetica", 9, "bold"), tags="dyn")

    def _recent(self) -> None:
        c = self.canvas
        recent = [key for key in self.hub.recent_games() if game(key) is not None][:5]
        if not recent:
            c.create_text(AW / 2, 118, text="PICK A GAME  ·  ARROWS OR SCROLL  ·  ENTER TO PLAY", fill="#c9b6e8", font=("Helvetica", 11, "bold"), tags="dyn")
            return
        c.create_text(70, 112, anchor="w", text="RECENT", fill="#ffe66d", font=("Helvetica", 11, "bold"), tags="dyn")
        x = 140
        for key in recent:
            spec = game(key)
            assert spec is not None
            label = spec.title
            width = 16 + len(label) * 8
            box = (x, 98, x + width, 128)
            self.recent_hits.append((key, box))
            chosen = key == self.shelf.keys[self.shelf.index]
            round_rect(c, *box, 12, fill="#1b0540", outline="#ffffff" if chosen else "#5a3a78", width=2, tags="dyn")
            c.create_text((box[0] + box[2]) / 2, 113, text=label, fill="#ffffff", font=("Helvetica", 11, "bold"), tags="dyn")
            x += width + 10

    def _cards(self) -> None:
        c = self.canvas
        slots = shelf_slots(len(LIBRARY), self.focus, AW, CARD_W, GAP)
        order = sorted(range(len(LIBRARY)), key=lambda i: abs(i - self.focus), reverse=True)
        cy = 400
        for i in order:
            spec = LIBRARY[i]
            cx, scale = slots[i]
            w, h = CARD_W * scale, CARD_H * scale
            if cx + w / 2 < -40 or cx - w / 2 > AW + 40:
                continue
            x0, y0, x1, y1 = cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2
            self._card(i, spec, x0, y0, x1, y1, scale, abs(i - self.shelf.index) < 0.5)
            self.card_hits.append((i, (x0, y0, x1, y1)))

    def _card(self, index: int, spec: object, x0: float, y0: float, x1: float, y1: float, scale: float, focused: bool) -> None:
        c = self.canvas
        top, bottom = spec.colors  # type: ignore[attr-defined]
        top_rgb, bottom_rgb = _hex(top), _hex(bottom)
        steps = 8
        for s in range(steps):
            round_rect(
                c, x0, y0 + (y1 - y0) * s / steps, x1, y1, 26 * scale,
                fill=_mix(top_rgb, bottom_rgb, s / (steps - 1)), outline="", tags="dyn",
            )
        _keyart(c, spec.key, x0, y0, x1, y1, "dyn")  # type: ignore[attr-defined]
        # scrim so the title stays readable over the art
        round_rect(c, x0, y1 - 118 * scale, x1, y1, 26 * scale, fill="#12021f", outline="", tags="dyn")
        c.create_rectangle(x0, y1 - 118 * scale, x1, y1 - 90 * scale, fill="#12021f", outline="", tags="dyn")
        title_scale = 3 if scale > 0.95 else 2
        pixel_text(c, spec.title, (x0 + x1) / 2, y1 - 78 * scale, title_scale, "#ffffff", "dyn")  # type: ignore[attr-defined]
        if focused:
            c.create_text((x0 + x1) / 2, y1 - 48 * scale, text=spec.blurb, fill="#f3e9ff", font=("Helvetica", 11, "bold"), width=x1 - x0 - 28, tags="dyn")  # type: ignore[attr-defined]
        badge = score_badge(spec, self.hub.best(spec.key))  # type: ignore[attr-defined]
        pill = "#ffe66d" if focused else "#c9b6e8"
        c.create_text((x0 + x1) / 2, y1 - 22 * scale, text=badge, fill=pill, font=("Helvetica", 12, "bold"), tags="dyn")
        kind = "BUTTON" if spec.stock else "TILT"  # type: ignore[attr-defined]
        c.create_text(x0 + 16, y0 + 18, anchor="w", text=kind, fill="#ffffff", font=("Helvetica", 10, "bold"), tags="dyn")
        outline = "#ffffff" if focused else "#2a1048"
        round_rect(c, x0, y0, x1, y1, 26 * scale, fill="", outline=outline, width=4 if focused else 2, tags="dyn")
        if focused:
            pulse = 6 + 3 * math.sin(self.clock * 5)
            for grow, colour, width in ((pulse + 10, "#3a0a52", 6), (pulse, NEON, 3)):
                round_rect(c, x0 - grow, y0 - grow, x1 + grow, y1 + grow, 30, fill="", outline=colour, width=width, tags="dyn")

    def _blade(self) -> None:
        c = self.canvas
        round_rect(c, 80, 130, AW - 80, AH - 120, 28, fill="#140426", outline=NEON, width=3, tags="dyn")
        if self.shelf.page == "status":
            c.create_text(AW / 2, 168, text="STATUS", fill="#ffe66d", font=("Helvetica", 22, "bold"), tags="dyn")
            c.create_text(AW / 2, 210, text="\n".join(self.status_lines[:16]), fill="#f4ecff", font=("Menlo", 13), justify="left", anchor="n", tags="dyn")
            c.create_text(AW / 2, AH - 150, text="ESC OR DOUBLE TAP GOES BACK", fill="#c9b6e8", font=("Helvetica", 12, "bold"), tags="dyn")
            return
        rows = self._controller_rows() if self.shelf.page == "controllers" else [(key, title, blurb) for key, title, blurb in SYSTEM]
        heading = "CONTROLLERS" if self.shelf.page == "controllers" else "SETTINGS"
        c.create_text(AW / 2, 168, text=heading, fill="#ffe66d", font=("Helvetica", 22, "bold"), tags="dyn")
        top = 210
        for i, (_key, title, blurb) in enumerate(rows):
            y = top + i * 62
            box = (140, y, AW - 140, y + 54)
            self.row_hits.append(box)
            focused = i == self.shelf.sub
            round_rect(c, *box, 14, fill="#2a0c4a" if focused else "#1b0536", outline="#ffffff" if focused else "#3a1860", width=2, tags="dyn")
            c.create_text(164, y + 18, anchor="w", text=title, fill="#ffffff", font=("Helvetica", 16, "bold"), tags="dyn")
            c.create_text(164, y + 38, anchor="w", text=blurb, fill="#d5c6ee", font=("Helvetica", 11), tags="dyn")

    def _footer(self, now: float) -> None:
        c = self.canvas
        device = self.hub.active_device()
        items = legend("menu", device=device)
        round_rect(c, 36, AH - 78, AW - 36, AH - 16, 22, fill="#140426", outline=NEON, width=2, tags="dyn")
        draw_legend(c, AW / 2 - 40, AH - 58, items, size=13, max_width=AW - 220)
        level, caption, age = self.hub.ear_state()
        target = level or 0.0
        self.level = max(target, self.level - 0.08)
        if self.mode == "thinking":
            words = f"“{self.heard}”"
        elif self.heard and age < 3:
            words = f"“{caption or self.heard}”"
        else:
            words = "say a game, or “settings”"
        c.create_text(70, AH - 34, anchor="w", text=words, fill="#ffffff", font=("Helvetica", 13, "bold"), tags="dyn")
        if level is not None:
            draw_meter(c, AW - 150, AH - 40, self.level, 18)
            draw_mic(c, AW - 170, AH - 34, "#4dffb0", 0.7)

    def _calibration(self) -> None:
        c = self.canvas
        name, big, small = WIZARD[self.step or 0]
        c.create_rectangle(0, 0, AW, AH, fill="#07010f", stipple="gray50", outline="", tags="dyn")
        round_rect(c, AW / 2 - 340, AH / 2 - 180, AW / 2 + 340, AH / 2 + 180, 28, fill="#1b0540", outline=NEON, width=4, tags="dyn")
        c.create_text(AW / 2, AH / 2 - 130, text=f"TILT SETUP  ·  {(self.step or 0) + 1} / {len(WIZARD)}", fill="#7ef9ff", font=("Helvetica", 14, "bold"), tags="dyn")
        c.create_text(AW / 2, AH / 2 - 70, text=big, fill="#ffffff", font=("Helvetica", 36, "bold"), tags="dyn")
        c.create_text(AW / 2, AH / 2 - 24, text=small, fill="#ffe66d", font=("Helvetica", 14, "bold"), tags="dyn")
        degrees = self._step_degrees()
        if name != "rest" and degrees is not None:
            c.create_text(AW / 2, AH / 2 + 30, text=f"{degrees:.0f}°", fill="#3ddc84" if degrees >= MIN_TILT_DEG else "#ffb020", font=("Helvetica", 28, "bold"), tags="dyn")
        device = self.hub.active_device()
        lock = {"keys": (("enter", "LOCK IT IN"), ("esc", "SKIP")),
                "pad": (("a", "LOCK IT IN"), ("b", "SKIP"))}.get(device, (("tap", "LOCK IT IN"), ("double", "SKIP")))
        draw_legend(c, AW / 2, AH / 2 + 120, lock, size=16)

    def close(self) -> None:
        if getattr(self, "_job", None) is not None:
            self.top.after_cancel(self._job)
        self.top.destroy()
        self.hub.window_closed(self)

    def lift(self) -> None:
        self.top.deiconify()
        self.top.lift()
        self.top.focus_force()
