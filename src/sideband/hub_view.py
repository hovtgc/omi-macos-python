"""The home screen: a row of large cover cards, the way a current console does it.

Keyboard and mouse are the main way through: arrows or A/D, Enter, Esc, the wheel, hover and click.
A single Omi tap moves to the next card, a double tap goes back, a hold launches. A gamepad's stick
or d-pad moves, A launches, B goes back, Start opens settings. The gear in the top bar is the same
menu, and it is not a card on the row. Saying "play desert" or "settings" still works.

Covers are bundled JPEGs. A game without one gets a flat panel in its own colours.
"""

from __future__ import annotations

import math
import os
import struct
import subprocess
import tempfile
import time
import tkinter as tk
import wave
from typing import TYPE_CHECKING

from sideband.covers import controls_line, cover_path
from sideband.legend import draw_legend, draw_mic, legend, round_rect
from sideband.platform import LIBRARY, SYSTEM, Shelf, game, pixels, score_badge, shelf_slots

if TYPE_CHECKING:
    from sideband.ui import Hub

AW, AH = 1240, 760
CARD_W = 520
GAP = 28
MENU_MS = 16
INK = "#0e0f12"
PAPER = "#f5f6f8"
MUTED = "#a4a6ad"
PANEL = "#16171c"
LINE = "#2c2e36"
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


def boot_tone(enabled: bool = True) -> None:
    """One short power-on tick. The shelf stays quiet after that."""
    if not enabled:
        return
    try:
        fd, path = tempfile.mkstemp(prefix="sideband-boot-", suffix=".wav")
        os.close(fd)
        rate, count = 22050, 1600
        with wave.open(path, "w") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(rate)
            frames = bytearray()
            for i in range(count):
                env = (1 - i / count) ** 2
                sample = env * 0.18 * math.sin(2 * math.pi * 140 * i / rate)
                frames += struct.pack("<h", int(max(-1.0, min(1.0, sample)) * 32767))
            handle.writeframes(frames)
        subprocess.Popen(["afplay", "-v", "0.35", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        return


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


class ArcadeWindow:
    """Console home. The launcher calls on_tap, on_hold, on_speech, on_intent and on_motion."""

    def __init__(self, hub: Hub) -> None:
        self.hub = hub
        self.shelf = Shelf()
        self.top = tk.Toplevel(hub.root)
        self.top.title("Sideband")
        self.top.resizable(False, False)
        self.top.protocol("WM_DELETE_WINDOW", self.close)
        self.canvas = tk.Canvas(self.top, width=AW, height=AH, highlightthickness=0, bg=INK, cursor="hand2")
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
        self.gear_box = (AW - 56, 14, AW - 16, 54)
        self.status_lines: list[str] = []
        self._moved = 0.0
        self._tilt_at = 0.0
        self.level = 0.0
        self._photos: dict[tuple, tk.PhotoImage] = {}
        self._bgs: dict[str, tk.PhotoImage | None] = {}
        self._bg_key = ""
        self.canvas.create_rectangle(0, 0, AW, AH, fill=INK, outline="", tags="bg")
        boot_tone(bool(hub.settings.get("arcade_sound", True)))
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
        self.focus += (self.shelf.index - self.focus) * min(1.0, dt * 8)
        c = self.canvas
        c.delete("dyn")
        self.card_hits, self.row_hits, self.recent_hits = [], [], []
        self._backdrop()
        self._topbar()
        if self.shelf.page == "games":
            self._recent()
            self._cards()
            self._details()
        else:
            self._blade()
        if self.step is not None:
            self._calibration()
        text, at = self.toast
        if text and now - at < 3.2:
            round_rect(c, AW / 2 - 280, 78, AW / 2 + 280, 118, 14, fill=PANEL, outline=LINE, width=1, tags="dyn")
            c.create_text(AW / 2, 98, text=text, fill=PAPER, font=("Helvetica", 13), tags="dyn")

    def _backdrop(self) -> None:
        spec = LIBRARY[max(0, min(len(LIBRARY) - 1, int(round(self.focus))))]
        if spec.key == self._bg_key:
            return
        self.canvas.delete("bg")
        photo = self._background(spec.key)
        if photo is not None:
            self.canvas.create_image(0, 0, image=photo, anchor="nw", tags="bg")
        else:
            top = _hex(spec.colors[0])
            self.canvas.create_rectangle(0, 0, AW, AH, fill=_mix(tuple(int(v * 0.22) for v in top), (12, 13, 16), 0.45), outline="", tags="bg")
        self.canvas.create_rectangle(0, 0, AW, AH, fill="#05060a", stipple="gray25", outline="", tags="bg")
        self._bg_key = spec.key

    def _background(self, key: str) -> tk.PhotoImage | None:
        if key in self._bgs:
            return self._bgs[key]
        path = cover_path(key)
        photo = None
        if path is not None:
            try:
                from PIL import Image, ImageEnhance, ImageFilter, ImageTk

                image = Image.open(path).convert("RGB").resize((AW, AH), Image.Resampling.LANCZOS)
                image = image.filter(ImageFilter.GaussianBlur(radius=26))
                image = ImageEnhance.Brightness(image).enhance(0.32)
                image = ImageEnhance.Color(image).enhance(0.8)
                photo = ImageTk.PhotoImage(image)
            except Exception:
                photo = None
        self._bgs[key] = photo
        return photo

    def _cover(self, key: str, width: int) -> tk.PhotoImage | None:
        width = max(160, int(width) // 16 * 16)
        token = (key, width)
        cached = self._photos.get(token)
        if cached is not None:
            return cached
        path = cover_path(key)
        if path is None:
            return None
        try:
            from PIL import Image, ImageDraw, ImageTk

            height = max(1, round(width * 9 / 16))
            image = Image.open(path).convert("RGBA").resize((width, height), Image.Resampling.LANCZOS)
            radius = max(16, width // 22)
            mask = Image.new("L", image.size, 0)
            ImageDraw.Draw(mask).rounded_rectangle((0, 0, width - 1, height - 1), radius=radius, fill=255)
            image.putalpha(mask)
            photo = ImageTk.PhotoImage(image)
        except Exception:
            return None
        self._photos[token] = photo
        if len(self._photos) > 40:
            self._photos.pop(next(iter(self._photos)))
        return photo

    def _topbar(self) -> None:
        c = self.canvas
        c.create_rectangle(0, 0, AW, 68, fill="#101114", outline="", tags="dyn")
        c.create_line(0, 68, AW, 68, fill=LINE, tags="dyn")
        pixel_text(c, "SB", 36, 34, 2, PAPER, "dyn", anchor="w")
        c.create_text(78, 34, anchor="w", text="Sideband", fill=PAPER, font=("Helvetica", 18), tags="dyn")
        device = {"keys": "Keyboard & mouse", "omi": "Omi", "pad": "Gamepad"}.get(self.hub.active_device(), "Keyboard & mouse")
        if self.hub.active_device() == "pad":
            names = self.hub.pad_names()
            if names:
                device = names[0]
        c.create_text(250, 34, anchor="w", text=device, fill=MUTED, font=("Helvetica", 13), tags="dyn")
        c.create_text(AW - 78, 34, anchor="e", text=time.strftime("%H:%M"), fill=PAPER, font=("Helvetica", 15), tags="dyn")
        self._gear()

    def _gear(self) -> None:
        c = self.canvas
        x0, y0, x1, y1 = self.gear_box
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        on = self.shelf.page != "games"
        c.create_oval(x0, y0, x1, y1, fill="#1c1e24" if not on else "#2a2d36", outline=PAPER if on else LINE, width=1, tags="dyn")
        c.create_oval(cx - 5, cy - 5, cx + 5, cy + 5, outline=PAPER, width=2, tags="dyn")
        for k in range(8):
            angle = k / 8 * math.tau
            c.create_line(cx + math.cos(angle) * 7, cy + math.sin(angle) * 7, cx + math.cos(angle) * 11, cy + math.sin(angle) * 11, fill=PAPER, width=2, tags="dyn")

    def _recent(self) -> None:
        c = self.canvas
        recent = [key for key in self.hub.recent_games() if game(key) is not None][:5]
        if not recent:
            return
        c.create_text(36, 96, anchor="w", text="Recent", fill=MUTED, font=("Helvetica", 12), tags="dyn")
        x = 100
        for key in recent:
            spec = game(key)
            assert spec is not None
            label = spec.title.title()
            width = 28 + len(label) * 7
            box = (x, 80, x + width, 112)
            self.recent_hits.append((key, box))
            chosen = key == self.shelf.keys[self.shelf.index]
            round_rect(c, *box, 16, fill="#22242c" if chosen else "#17181d", outline=PAPER if chosen else LINE, width=1, tags="dyn")
            c.create_text((box[0] + box[2]) / 2, 96, text=label, fill=PAPER, font=("Helvetica", 11), tags="dyn")
            x += width + 8

    def _cards(self) -> None:
        c = self.canvas
        slots = shelf_slots(len(LIBRARY), self.focus, AW, CARD_W, GAP, spread=0.96)
        order = sorted(range(len(LIBRARY)), key=lambda i: abs(i - self.focus), reverse=True)
        cy = 318
        for i in order:
            spec = LIBRARY[i]
            cx, scale = slots[i]
            width, height = CARD_W * scale, CARD_W * scale * 9 / 16
            if cx + width / 2 < -60 or cx - width / 2 > AW + 60:
                continue
            x0, y0, x1, y1 = cx - width / 2, cy - height / 2, cx + width / 2, cy + height / 2
            self._card(spec, x0, y0, x1, y1, abs(i - self.shelf.index) < 0.5)
            self.card_hits.append((i, (x0, y0, x1, y1)))

    def _card(self, spec: object, x0: float, y0: float, x1: float, y1: float, focused: bool) -> None:
        c = self.canvas
        radius = max(16, (x1 - x0) / 22)
        round_rect(c, x0 + 10, y0 + 16, x1 + 10, y1 + 16, radius, fill="#05060a", outline="", tags="dyn")
        if focused:
            pulse = 8 + 2 * math.sin(self.clock * 2.2)
            round_rect(c, x0 - pulse, y0 - pulse, x1 + pulse, y1 + pulse, radius + 8, fill="", outline="#d5e4ff", width=2, tags="dyn")
        photo = self._cover(spec.key, x1 - x0)  # type: ignore[attr-defined]
        if photo is not None:
            c.create_image((x0 + x1) / 2, (y0 + y1) / 2, image=photo, tags="dyn")
        else:
            self._fallback(spec, x0, y0, x1, y1, radius)
        if focused:
            round_rect(c, x0, y0, x1, y1, radius, fill="", outline="#ffffff", width=2, tags="dyn")

    def _fallback(self, spec: object, x0: float, y0: float, x1: float, y1: float, radius: float) -> None:
        """A quiet panel for a game that does not have a cover yet."""
        c = self.canvas
        top = tuple(int(channel * 0.45) for channel in _hex(spec.colors[0]))  # type: ignore[attr-defined]
        bottom = tuple(int(channel * 0.25) for channel in _hex(spec.colors[1]))  # type: ignore[attr-defined]
        round_rect(c, x0, y0, x1, y1, radius, fill=_mix(top, bottom, 0.45), outline="", tags="dyn")
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        accent = spec.colors[0]  # type: ignore[attr-defined]
        key = spec.key  # type: ignore[attr-defined]
        if key == "beat":
            for i, bh in enumerate((18, 36, 24, 44, 20)):
                c.create_rectangle(cx - 70 + i * 28, cy + 20 - bh, cx - 54 + i * 28, cy + 20, fill=accent, outline="", tags="dyn")
        elif key == "draw":
            c.create_oval(cx - 36, cy - 36, cx + 36, cy + 36, outline=accent, width=4, tags="dyn")
            c.create_oval(cx - 8, cy - 8, cx + 8, cy + 8, fill=accent, outline="", tags="dyn")
        elif key == "dash":
            c.create_rectangle(cx - 70, cy + 16, cx + 80, cy + 22, fill=accent, outline="", tags="dyn")
            c.create_rectangle(cx - 20, cy - 18, cx + 4, cy + 16, fill=PAPER, outline="", tags="dyn")
        elif key == "simon":
            c.create_oval(cx - 48, cy - 28, cx - 4, cy + 28, fill=accent, outline="", tags="dyn")
            c.create_oval(cx + 4, cy - 28, cx + 48, cy + 28, fill=PAPER, outline="", tags="dyn")
        else:
            c.create_oval(cx - 28, cy - 28, cx + 28, cy + 28, fill=accent, outline="", tags="dyn")

    def _details(self) -> None:
        c = self.canvas
        spec = LIBRARY[self.shelf.index]
        badge = score_badge(spec, self.hub.best(spec.key))
        round_rect(c, 48, 530, AW - 48, 710, 20, fill=PANEL, outline=LINE, width=1, tags="dyn")
        c.create_text(76, 568, anchor="w", text=spec.title.title(), fill=PAPER, font=("Helvetica", 28), tags="dyn")
        if badge == "NEW":
            round_rect(c, AW - 150, 548, AW - 76, 580, 12, fill="#f5f6f8", outline="", tags="dyn")
            c.create_text(AW - 113, 564, text="New", fill=INK, font=("Helvetica", 13, "bold"), tags="dyn")
        else:
            c.create_text(AW - 76, 568, anchor="e", text=badge.title(), fill=MUTED, font=("Helvetica", 16), tags="dyn")
        c.create_text(76, 608, anchor="w", text=spec.blurb, fill="#d5d6db", font=("Helvetica", 14), tags="dyn")
        c.create_text(76, 642, anchor="w", text=controls_line(spec), fill=MUTED, font=("Helvetica", 13), tags="dyn")
        device = self.hub.active_device()
        hint = {"keys": "Arrows move  ·  Enter plays  ·  Esc back", "pad": "Stick moves  ·  A plays  ·  B back", "omi": "Tap next  ·  Double back  ·  Hold plays"}.get(device, "")
        level, caption, age = self.hub.ear_state()
        if self.mode == "thinking":
            hint = f"“{self.heard}”"
        elif caption and age < 3:
            hint = f"“{caption}”"
        c.create_text(76, 678, anchor="w", text=hint, fill="#8d9098", font=("Helvetica", 12), tags="dyn")
        if level is not None:
            draw_mic(c, AW - 96, 678, "#c9ccd4", 0.7, "dyn")

    def _blade(self) -> None:
        c = self.canvas
        round_rect(c, 160, 110, AW - 160, AH - 48, 22, fill=PANEL, outline=LINE, width=1, tags="dyn")
        if self.shelf.page == "status":
            c.create_text(AW / 2, 150, text="Status", fill=PAPER, font=("Helvetica", 22), tags="dyn")
            c.create_text(200, 190, text="\n".join(self.status_lines[:16]), fill="#d5d6db", font=("Menlo", 13), justify="left", anchor="nw", tags="dyn")
            c.create_text(AW / 2, AH - 78, text="Esc goes back", fill=MUTED, font=("Helvetica", 13), tags="dyn")
            return
        rows = self._controller_rows() if self.shelf.page == "controllers" else [(key, title, blurb) for key, title, blurb in SYSTEM]
        heading = "Controllers" if self.shelf.page == "controllers" else "Settings"
        c.create_text(200, 148, anchor="w", text=heading, fill=PAPER, font=("Helvetica", 22), tags="dyn")
        top = 186
        for i, (_key, title, blurb) in enumerate(rows):
            y = top + i * 64
            box = (196, y, AW - 196, y + 54)
            self.row_hits.append(box)
            focused = i == self.shelf.sub
            round_rect(c, *box, 12, fill="#22242c" if focused else "#121318", outline=PAPER if focused else LINE, width=1, tags="dyn")
            c.create_text(216, y + 18, anchor="w", text=title.title(), fill=PAPER, font=("Helvetica", 15), tags="dyn")
            c.create_text(216, y + 38, anchor="w", text=blurb, fill=MUTED, font=("Helvetica", 11), tags="dyn")

    def _calibration(self) -> None:
        c = self.canvas
        name, big, small = WIZARD[self.step or 0]
        c.create_rectangle(0, 0, AW, AH, fill="#0e0f12", stipple="gray50", outline="", tags="dyn")
        round_rect(c, AW / 2 - 340, AH / 2 - 180, AW / 2 + 340, AH / 2 + 180, 22, fill=PANEL, outline=LINE, width=1, tags="dyn")
        c.create_text(AW / 2, AH / 2 - 120, text=f"Tilt setup  ·  {(self.step or 0) + 1} / {len(WIZARD)}", fill=MUTED, font=("Helvetica", 13), tags="dyn")
        c.create_text(AW / 2, AH / 2 - 64, text=big.title(), fill=PAPER, font=("Helvetica", 28), tags="dyn")
        c.create_text(AW / 2, AH / 2 - 18, text=small, fill=MUTED, font=("Helvetica", 14), tags="dyn")
        degrees = self._step_degrees()
        if name != "rest" and degrees is not None:
            c.create_text(AW / 2, AH / 2 + 36, text=f"{degrees:.0f}°", fill=PAPER, font=("Helvetica", 26), tags="dyn")
        device = self.hub.active_device()
        lock = {"keys": (("enter", "LOCK IT IN"), ("esc", "SKIP")),
                "pad": (("a", "LOCK IT IN"), ("b", "SKIP"))}.get(device, (("tap", "LOCK IT IN"), ("double", "SKIP")))
        draw_legend(c, AW / 2, AH / 2 + 110, lock, size=15)

    def close(self) -> None:
        if getattr(self, "_job", None) is not None:
            self.top.after_cancel(self._job)
        self.top.destroy()
        self.hub.window_closed(self)

    def lift(self) -> None:
        self.top.deiconify()
        self.top.lift()
        self.top.focus_force()

