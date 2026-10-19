"""Windows for Beat Tap, Quickdraw, Omi Dash and Simon Omi.

Same flow as the other arcade games: Enter or a single tap starts, resumes or plays again;
Esc or a double tap leaves; hold pauses. During play the button is the game's button.
A shout (the mic crossing the line) counts as that button in Beat Tap, Quickdraw and Omi Dash.
"""

from __future__ import annotations

import random
import time
import tkinter as tk
from typing import TYPE_CHECKING, Callable

from sideband.legend import draw_ear, draw_legend, legend, round_rect
from sideband.platform import VolumeEdge, game
from sideband.shelf_games import SHELF_KEYS, make

if TYPE_CHECKING:
    from sideband.ui import Hub

W, H = 900, 640
FRAME_MS = 16


def _mix(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> str:
    t = max(0.0, min(1.0, t))
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * t) for x, y in zip(a, b))


class ShelfGameWindow:
    def __init__(self, hub: Hub, name: str, on_close: Callable[[], None]) -> None:
        self.hub, self.name, self.on_close = hub, name, on_close
        spec = game(name)
        self.title = spec.title if spec is not None else name.upper()
        self.blurb = spec.blurb if spec is not None else ""
        self.top = tk.Toplevel(hub.root)
        self.top.title(f"Omi Arcade · {self.title.title()}")
        self.top.resizable(False, False)
        self.canvas = tk.Canvas(self.top, width=W, height=H, bg="#07010f", highlightthickness=0)
        self.canvas.pack()
        self.keys: set[str] = set()
        self.taps = 0
        self.pad = 0  # Simon's second button
        self.edge = VolumeEdge()
        self.recorded = False
        self.top.bind("<KeyPress>", self._key_down)
        self.top.bind("<KeyRelease>", lambda e: self.keys.discard(e.keysym.lower()))
        self.canvas.bind("<Button-1>", self._click)
        self.top.protocol("WM_DELETE_WINDOW", self.close)
        self.new_game()
        self.top.focus_force()
        self._tick()

    def new_game(self) -> None:
        self.game = make(self.name, random.randrange(1 << 30))
        self.state = "ready"
        self.over_at = 0.0
        self.recorded = False
        self.taps = self.pad = 0

    @property
    def playing(self) -> bool:
        return self.state == "playing"

    def on_tap(self, kind: str) -> None:
        forward = kind == "single"
        if self.state == "playing":
            if self.name == "simon":
                self.game.press(0 if forward else 1)
            elif forward:
                self.taps += 1
            else:
                self.pad += 1
                self.taps += 1
            return
        if not forward:
            self.close()
            return
        if self.state == "over":
            if time.monotonic() - self.over_at < 0.6:
                return
            self.new_game()
        self.state = "playing"

    def on_hold(self) -> None:
        if self.state == "playing":
            self.state = "paused"

    def on_shake(self) -> None:
        if self.state == "playing" and self.name != "simon":
            self.taps += 1

    def _key_down(self, event: tk.Event) -> None:
        key = event.keysym.lower()
        self.keys.add(key)
        self.hub.note_device("keys")
        if key in ("space", "return", "up", "w"):
            self.on_tap("single")
        elif key in ("x", "d", "right"):
            if self.state == "playing" and self.name == "simon":
                self.on_tap("double")
            elif key == "x" and self.state == "playing":
                self.on_tap("single")
        elif key == "escape":
            self.on_hold() if self.state == "playing" else self.on_tap("double")
        elif key == "b":
            self.on_shake()

    def _click(self, event: tk.Event) -> None:
        self.hub.note_device("keys")
        if self.state == "playing" and self.name == "simon":
            self.on_tap("single" if event.x < W / 2 else "double")
            return
        self.on_tap("single")

    def _tick(self) -> None:
        self._job = self.top.after(FRAME_MS, self._tick)
        level, _caption, _age = self.hub.ear_state()
        if self.state == "playing" and self.name != "simon" and self.edge.rising(level or 0.0):
            self.taps += 1
        if self.state == "playing":
            if self.name == "simon":
                self.game.step(FRAME_MS / 1000)
            else:
                self.game.step(FRAME_MS / 1000, self.taps)
            if self.game.over:
                self.state = "over"
                self.over_at = time.monotonic()
        self.taps = self.pad = 0
        if self.state == "over" and not self.recorded:
            self.recorded = True
            self.hub.record_score(self.name, float(self.game.score))
        self.canvas.delete("dyn")
        getattr(self, f"_draw_{self.name}")()
        self._hud()

    def _hud(self) -> None:
        c = self.canvas
        device = self.hub.active_device()
        c.create_rectangle(0, H - 40, W, H, fill="#07010f", outline="", tags="dyn")
        draw_legend(c, W / 2, H - 20, legend(self.name, device=device), size=13, max_width=W - 24)
        draw_ear(c, W - 12, H - 58, *self.hub.ear_state())
        colours = {"ready": "#ffe66d", "paused": "#7fd4ff", "over": "#ff6b5b"}
        if self.state not in colours:
            return
        title = {"ready": self.title, "paused": "PAUSED", "over": "GAME OVER"}[self.state]
        sub = self.blurb if self.state == "ready" else f"score {self.game.score} · best {int(self.hub.best(self.name) or 0)}"
        colour = colours[self.state]
        round_rect(c, W / 2 - 320, H / 2 - 110, W / 2 + 320, H / 2 + 100, 24, fill="#140426", outline=colour, width=4, tags="dyn")
        c.create_text(W / 2, H / 2 - 48, text=title, fill=colour, font=("Helvetica", 36, "bold"), tags="dyn")
        c.create_text(W / 2, H / 2 + 2, text=sub, fill="#f4ecff", font=("Helvetica", 14, "bold"), width=560, tags="dyn")
        draw_legend(c, W / 2, H / 2 + 58, legend(self.name, self.state, device=device), size=16)

    def _draw_beat(self) -> None:
        c, g = self.canvas, self.game
        for i in range(12):
            c.create_rectangle(0, i * H / 12, W, (i + 1) * H / 12 + 1, fill=_mix((20, 0, 30), (60, 8, 40), i / 11), outline="", tags="dyn")
        line = H * 0.72
        c.create_line(80, line, W - 80, line, fill="#ff4d6d", width=4, tags="dyn")
        c.create_text(80, line - 16, anchor="w", text="HIT", fill="#ff4d6d", font=("Helvetica", 12, "bold"), tags="dyn")
        for note in g.notes:
            offset = note.t - g.clock
            if not -0.3 < offset < 2.4:
                continue
            x = W / 2 + offset * 280
            colour = "#3ddc84" if note.hit else "#ffffff"
            c.create_rectangle(x - 16, line - 70, x + 16, line - 8, fill=colour, outline="", tags="dyn")
        c.create_text(36, 36, anchor="w", text=str(g.score), fill="#ffffff", font=("Helvetica", 32, "bold"), tags="dyn")
        c.create_text(36, 72, anchor="w", text=f"{g.combo} combo   misses {g.misses}/{g.max_misses}", fill="#ffd1dc", font=("Helvetica", 14, "bold"), tags="dyn")
        if g.judge:
            c.create_text(W - 36, 48, anchor="e", text=g.judge, fill="#ffe66d", font=("Helvetica", 22, "bold"), tags="dyn")

    def _draw_draw(self) -> None:
        c, g = self.canvas, self.game
        c.create_rectangle(0, 0, W, H, fill="#1a0a04", outline="", tags="dyn")
        colour = "#ff4d6d" if g.phase == "draw" else "#ffe66d"
        c.create_text(W / 2, H / 2 - 150, text=g.message, fill=colour, font=("Helvetica", 72, "bold"), tags="dyn")
        c.create_text(36, 36, anchor="w", text=f"{g.score}", fill="#ffffff", font=("Helvetica", 28, "bold"), tags="dyn")
        c.create_text(W - 36, 36, anchor="e", text=f"round {min(g.round + 1, g.rounds)}/{g.rounds}   fouls {g.fouls}", fill="#ffd8a8", font=("Helvetica", 16, "bold"), tags="dyn")
        if g.best_ms is not None:
            c.create_text(W / 2, H / 2 - 80, text=f"best {g.best_ms:.0f} ms", fill="#ffffff", font=("Helvetica", 18, "bold"), tags="dyn")

    def _draw_dash(self) -> None:
        c, g = self.canvas, self.game
        c.create_rectangle(0, 0, W, H, fill="#07140f", outline="", tags="dyn")
        ground = H * 0.72
        c.create_rectangle(0, ground, W, H, fill="#12362a", outline="", tags="dyn")
        c.create_line(0, ground, W, ground, fill="#3ddc84", width=3, tags="dyn")
        scale = 46
        rx = 160
        ry = ground - (g.y + g.RUN_H) * scale
        c.create_rectangle(rx, ry, rx + g.RUN_W * scale, ground - g.y * scale, fill="#eafff4", outline="", tags="dyn")
        for ox, width, height in g.obstacles:
            screen = rx + (ox - (g.travel + g.RUN_X)) * scale
            if -40 < screen < W + 40:
                c.create_rectangle(screen, ground - height * scale, screen + width * scale, ground, fill="#ffb020", outline="", tags="dyn")
        c.create_text(36, 36, anchor="w", text=str(g.score), fill="#ffffff", font=("Helvetica", 32, "bold"), tags="dyn")

    def _draw_simon(self) -> None:
        c, g = self.canvas, self.game
        c.create_rectangle(0, 0, W, H, fill="#0c1024", outline="", tags="dyn")
        pads = (("#3ddc84", 0), ("#ffb020", 1))
        for colour, index in pads:
            cx = W * (0.32 if index == 0 else 0.68)
            lit = g.lit == index
            c.create_oval(cx - 90, H / 2 - 120, cx + 90, H / 2 + 80, fill=colour if lit else "#1a2038", outline=colour, width=8, tags="dyn")
            c.create_text(cx, H / 2 - 16, text="TAP" if index == 0 else "DOUBLE", fill="#ffffff" if lit else colour, font=("Helvetica", 18, "bold"), tags="dyn")
        c.create_text(W / 2, 70, text=g.message, fill="#ffffff", font=("Helvetica", 28, "bold"), tags="dyn")
        shown = " ".join("●" if pad == 0 else "●●" for pad in g.pattern)
        c.create_text(W / 2, 114, text=shown, fill="#c9d4ff", font=("Helvetica", 16, "bold"), tags="dyn")
        c.create_text(36, 36, anchor="w", text=str(g.score), fill="#ffffff", font=("Helvetica", 28, "bold"), tags="dyn")

    def close(self) -> None:
        self.top.after_cancel(self._job)
        self.top.destroy()
        self.on_close()

    def lift(self) -> None:
        self.top.deiconify()
        self.top.lift()
        self.top.focus_force()


# Imported by the hub so a typo in the registry fails at import.
assert set(SHELF_KEYS) <= {spec.key for spec in __import__("sideband.platform", fromlist=["LIBRARY"]).LIBRARY}
