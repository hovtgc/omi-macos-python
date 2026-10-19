"""Desert 91 on a Tk canvas: a Wolfenstein-style raycaster.

Keyboard and mouse are the controls. WASD moves, the pointer looks (locked while you play),
click or Space fires, R reloads, 1 and 2 swap the rifle and the pistol, Esc pauses.
A gamepad stick moves and turns, A fires, Y reloads, Start pauses. Omi tilt does the same
job as the stick, a tap fires, a shake reloads, a hold pauses.
"""

from __future__ import annotations

import math
import os
import random
import subprocess
import tempfile
import time
import tkinter as tk
from typing import TYPE_CHECKING, Callable

from sideband.desert import MISSIONS, Orders, Raid, cast, project, tone_wav
from sideband.legend import draw_legend, legend, round_rect

if TYPE_CHECKING:
    from sideband.ui import Hub

# RAID_WAVES imported by mistake? I didn't export that. Remove.
W, H = 960, 640
VIEW_H = 460
RAYS = 200
FOV = math.radians(66)
FRAME_MS = 16
HAZE = (214, 126, 58)
WALL = {
    "#": ((214, 176, 112), (162, 124, 72)),
    "B": ((118, 122, 108), (72, 76, 66)),
    "F": ((78, 32, 18), (36, 16, 12)),
}
SPRITE = {
    "soldier": ("#6d7a48", 0.32, 0.85),
    "jeep": ("#c4a46a", 0.7, 0.55),
    "truck": ("#5c5348", 0.95, 0.7),
}


class DesertWindow:
    def __init__(self, hub: Hub, on_close: Callable[[], None]) -> None:
        self.hub, self.on_close = hub, on_close
        self.top = tk.Toplevel(hub.root)
        self.top.title("Sideband · Desert 91")
        self.top.resizable(False, False)
        self.canvas = tk.Canvas(self.top, width=W, height=H, highlightthickness=0, bg="#14120e", cursor="arrow")
        self.canvas.pack()
        self.keys: set[str] = set()
        self.state = "ready"
        self.pitch = 0.0
        self.firing = False
        self.fire_pulse = False
        self.reload_pulse = False
        self.weapon_pick: str | None = None
        self.locked = False
        self._warping = False
        self.recorded = False
        self.over_at = 0.0
        self.jolt = 0
        self.motes = [(random.random(), random.random(), random.uniform(0.2, 1)) for _ in range(48)]
        self._wavs = _tones()
        self.raid = Raid()
        self.top.bind("<KeyPress>", self._key_down)
        self.top.bind("<KeyRelease>", self._key_up)
        self.canvas.bind("<Motion>", self._motion)
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<ButtonRelease-1>", lambda _e: setattr(self, "firing", False))
        self.top.protocol("WM_DELETE_WINDOW", self.close)
        self.top.focus_force()
        self._last = time.monotonic()
        self._tick()

    @property
    def playing(self) -> bool:
        return self.state == "playing"

    def new_game(self) -> None:
        self.raid = Raid()
        self.recorded = False
        self.pitch = 0.0
        self.state = "ready"

    def on_tap(self, kind: str) -> None:
        forward = kind == "single"
        if self.state == "playing":
            if forward:
                self.fire_pulse = True
            else:
                self.reload_pulse = True
            return
        if not forward:
            self._unlock()
            self.close()
            return
        if self.state in ("over", "won"):
            if time.monotonic() - self.over_at < 0.6:
                return
            self.new_game()
        self.state = "playing"
        self._lock()

    def on_hold(self) -> None:
        if self.state == "playing":
            self.state = "paused"
            self._unlock()

    def on_shake(self) -> None:
        if self.state == "playing":
            self.reload_pulse = True

    def _lock(self) -> None:
        self.locked = True
        self.canvas.configure(cursor="none")
        self._warp()

    def _unlock(self) -> None:
        self.locked = False
        self.firing = False
        self.canvas.configure(cursor="arrow")

    def _warp(self) -> None:
        self._warping = True
        try:
            self.canvas.event_generate("<Motion>", warp=True, x=W // 2, y=VIEW_H // 2)
        except tk.TclError:
            pass
        self._warping = False

    def _motion(self, event: tk.Event) -> None:
        if self._warping or not self.locked or self.state != "playing":
            return
        dx, dy = event.x - W / 2, event.y - VIEW_H / 2
        if abs(dx) < 1 and abs(dy) < 1:
            return
        self.hub.note_device("keys")
        self.raid.angle = (self.raid.angle - dx * 0.0042) % math.tau
        self.pitch = max(-90.0, min(90.0, self.pitch - dy * 0.35))
        self._warp()

    def _press(self, _event: tk.Event) -> None:
        self.hub.note_device("keys")
        if self.state != "playing":
            self.on_tap("single")
            return
        self.firing = True
        self.fire_pulse = True

    def _key_down(self, event: tk.Event) -> None:
        key = event.keysym.lower()
        self.keys.add(key)
        self.hub.note_device("keys")
        if key == "r":
            self.reload_pulse = True
        elif key == "1":
            self.weapon_pick = "rifle"
        elif key == "2":
            self.weapon_pick = "pistol"
        elif key == "escape":
            self._unlock()
            if self.state == "playing":
                self.on_hold()
            else:
                self.on_tap("double")
        elif key in ("return", "space"):
            if self.state == "playing":
                self.fire_pulse = True
                self.firing = True
            else:
                self.on_tap("single")

    def _key_up(self, event: tk.Event) -> None:
        key = event.keysym.lower()
        self.keys.discard(key)
        if key in ("space", "return"):
            self.firing = False

    def _orders(self, dt: float) -> Orders:
        forward = (1.0 if self.keys & {"w", "up"} else 0.0) - (1.0 if self.keys & {"s", "down"} else 0.0)
        strafe = (1.0 if self.keys & {"d", "right"} else 0.0) - (1.0 if self.keys & {"a", "left"} else 0.0)
        turn = 0.0
        axes = self.hub.play_axes()
        if axes is not None and forward == 0.0 and strafe == 0.0:
            strafe = max(-1.0, min(1.0, axes[0] * 0.35))
            forward = max(-1.0, min(1.0, axes[1]))
            turn += axes[0] * 1.7 * dt
        fire = self.firing or self.fire_pulse
        reload = self.reload_pulse
        weapon = self.weapon_pick
        self.fire_pulse = False
        self.reload_pulse = False
        self.weapon_pick = None
        return Orders(forward, strafe, turn, fire, reload, weapon)

    def _tick(self) -> None:
        self._job = self.top.after(FRAME_MS, self._tick)
        now = time.monotonic()
        dt = min(0.05, now - self._last)
        self._last = now
        before = self.raid.score
        mag = self.raid.gun.mag
        if self.state == "playing":
            self.raid.step(dt, self._orders(dt))
            if self.raid.score > before:
                _blip(self._wavs["hit"])
                self.jolt = 5
            elif self.raid.gun.mag < mag:
                _blip(self._wavs["shot"])
                self._kick = 26
            if self.raid.over and not self.recorded:
                self.recorded = True
                self.over_at = now
                self.state = "won" if self.raid.won else "over"
                self._unlock()
                self.hub.record_score("desert", float(self.raid.score))
        self._draw()

    def _draw(self) -> None:
        c = self.canvas
        c.delete("dyn")
        self._world()
        self._rifle()
        self._hud()
        if self.jolt:
            c.move("dyn", random.randint(-self.jolt, self.jolt), random.randint(-self.jolt, self.jolt))
            self.jolt -= 1

    def _world(self) -> None:
        c, raid = self.canvas, self.raid
        horizon = VIEW_H / 2 + self.pitch
        sky = ((120, 48, 28), (186, 78, 32), (232, 122, 48), (255, 168, 84))
        for i, colour in enumerate(sky):
            y0, y1 = horizon * i / len(sky), horizon * (i + 1) / len(sky)
            c.create_rectangle(0, max(0, y0), W, y1 + 1, fill="#%02x%02x%02x" % colour, outline="", tags="dyn")
        ground = ((196, 150, 86), (176, 128, 70), (150, 108, 62))
        for i, colour in enumerate(ground):
            y0 = horizon + (VIEW_H - horizon) * i / len(ground)
            y1 = horizon + (VIEW_H - horizon) * (i + 1) / len(ground)
            c.create_rectangle(0, y0, W, y1 + 1, fill="#%02x%02x%02x" % colour, outline="", tags="dyn")
        for u, v, depth in self.motes:
            mx = (u * W + time.monotonic() * 12 * depth) % W
            my = v * max(8, horizon)
            c.create_oval(mx, my, mx + 2, my + 2, fill="#f0c090", outline="", tags="dyn")
        zbuf = [99.0] * RAYS
        half = math.tan(FOV / 2)
        col_w = W / RAYS
        for i in range(RAYS):
            cam = (2 * i / (RAYS - 1) - 1) * half
            ray = math.atan2(math.sin(raid.angle) + math.cos(raid.angle) * cam, math.cos(raid.angle) - math.sin(raid.angle) * cam)
            dist, cell, side = cast(raid.grid, raid.x, raid.y, ray)
            zbuf[i] = dist
            shade = WALL.get(cell, WALL["#"])[side]
            fog = min(1.0, dist / 11)
            base = tuple(int(channel + (haze - channel) * fog) for channel, haze in zip(shade, HAZE))
            height = min(VIEW_H * 1.4, (VIEW_H * 0.85) / dist)
            xmid = i * col_w + col_w / 2
            top = horizon - height / 2
            if cell == "#" and dist < 7:
                for band in range(5):
                    tone = tuple(max(0, min(255, int(ch * (0.76 if band % 2 else 1)))) for ch in base)
                    y0 = top + height * band / 5
                    y1 = top + height * (band + 1) / 5
                    c.create_line(xmid, y0, xmid, y1, fill="#%02x%02x%02x" % tone, width=col_w + 1, tags="dyn")
            else:
                c.create_line(xmid, top, xmid, horizon + height / 2, fill="#%02x%02x%02x" % base, width=col_w + 1, tags="dyn")
            if cell == "F":
                c.create_line(xmid, horizon, xmid, horizon + height * 0.45, fill="#ff5a12", width=col_w + 1, tags="dyn")
        sprites: list[tuple[float, str, float, float, str]] = []
        for actor in raid.live():
            fill, wide, tall = SPRITE[actor.kind]
            if actor.hurt > 0:
                fill = "#f4f0e6"
            sprites.append((math.hypot(actor.x - raid.x, actor.y - raid.y), actor.kind, actor.x, actor.y, fill))
        for item in raid.pickups:
            if not item.taken:
                sprites.append((math.hypot(item.x - raid.x, item.y - raid.y), item.kind, item.x, item.y, "#7dcea0" if item.kind == "health" else "#e6c15a"))
        for puff in raid.puffs:
            sprites.append((math.hypot(puff[0] - raid.x, puff[1] - raid.y), "puff", puff[0], puff[1], "#d9c7a2"))
        focal = (RAYS / 2) / half
        for dist, kind, sx, sy, fill in sorted(sprites, key=lambda item: -item[0]):
            side, depth = project(sx - raid.x, sy - raid.y, raid.angle)
            if depth < 0.25:
                continue
            screen = W / 2 + (side / depth) * focal * col_w
            size = (VIEW_H * 0.7) / depth
            wide = size * (0.35 if kind == "soldier" else 0.15 if kind in ("health", "ammo", "puff") else 0.85)
            tall = size * (0.9 if kind == "soldier" else 0.35 if kind in ("health", "ammo") else 0.4 if kind == "puff" else 0.6)
            mid = int(screen / col_w)
            if mid < 0 or mid >= RAYS or zbuf[mid] < depth:
                continue
            c.create_rectangle(screen - wide / 2, horizon - tall, screen + wide / 2, horizon + tall * 0.15, fill=fill, outline="", tags="dyn")
        self._columns(horizon, zbuf, half, col_w)
        self._tank(horizon, zbuf, half, col_w)
        if raid.hit_flash > 0:
            c.create_rectangle(8, 8, W - 8, VIEW_H - 8, outline="#ffb15a", width=8, tags="dyn")
        c.create_rectangle(W / 2 - 8, horizon - 1, W / 2 - 3, horizon + 1, fill="#f7f4ee", outline="", tags="dyn")
        c.create_rectangle(W / 2 + 3, horizon - 1, W / 2 + 8, horizon + 1, fill="#f7f4ee", outline="", tags="dyn")
        c.create_rectangle(W / 2 - 1, horizon - 8, W / 2 + 1, horizon - 3, fill="#f7f4ee", outline="", tags="dyn")
        c.create_rectangle(W / 2 - 1, horizon + 3, W / 2 + 1, horizon + 8, fill="#f7f4ee", outline="", tags="dyn")

    def _billboard(self, wx: float, wy: float, horizon: float, zbuf: list[float], half: float, col_w: float) -> tuple[float, float, float] | None:
        side, depth = project(wx - self.raid.x, wy - self.raid.y, self.raid.angle)
        if depth < 0.45:
            return None
        focal = (RAYS / 2) / half
        screen = W / 2 + (side / depth) * focal * col_w
        mid = int(screen / col_w)
        if mid < 0 or mid >= RAYS or zbuf[mid] + 1.5 < depth:
            return None
        return screen, depth, (VIEW_H * 0.55) / depth

    def _columns(self, horizon: float, zbuf: list[float], half: float, col_w: float) -> None:
        c, raid = self.canvas, self.raid
        for y, row in enumerate(raid.grid):
            for x, cell in enumerate(row):
                if cell != "F":
                    continue
                placed = self._billboard(x + 0.5, y + 0.5, horizon, zbuf, half, col_w)
                if placed is None:
                    continue
                screen, _depth, size = placed
                for k in range(6):
                    rise = size * (0.55 + k * 0.62)
                    radius = size * (0.28 + k * 0.2)
                    drift = math.sin(time.monotonic() * 0.55 + k + x) * (3 + k * 2)
                    shade = 28 + k * 16
                    c.create_oval(screen - radius + drift, horizon - rise - radius * 0.45,
                                  screen + radius + drift, horizon - rise + radius * 0.35,
                                  fill="#%02x%02x%02x" % (shade, max(0, shade - 10), max(0, shade - 18)), outline="", tags="dyn")
                c.create_oval(screen - size * 0.22, horizon - size * 0.2, screen + size * 0.22, horizon + size * 0.08,
                              fill="#ff6a14", outline="", tags="dyn")

    def _tank(self, horizon: float, zbuf: list[float], half: float, col_w: float) -> None:
        placed = self._billboard(8.2, 14.8, horizon, zbuf, half, col_w)
        if placed is None:
            return
        screen, _depth, size = placed
        c = self.canvas
        w, h = size * 1.4, size * 0.45
        c.create_polygon(screen - w, horizon, screen + w, horizon, screen + w * 0.7, horizon - h, screen - w * 0.7, horizon - h,
                         fill="#3e4634", outline="#1c2018", tags="dyn")
        c.create_rectangle(screen - w * 0.2, horizon - h * 1.7, screen + w * 0.55, horizon - h * 0.7, fill="#2c3226", outline="", tags="dyn")
        c.create_oval(screen - w * 0.7, horizon - h * 0.35, screen - w * 0.2, horizon + h * 0.15, fill="#1a1c16", outline="", tags="dyn")
        c.create_oval(screen + w * 0.15, horizon - h * 0.35, screen + w * 0.7, horizon + h * 0.15, fill="#1a1c16", outline="", tags="dyn")

    def _rifle(self) -> None:
        c = self.canvas
        kick = getattr(self, "_kick", 0)
        bob = math.sin(time.monotonic() * 7) * 3
        x, y = W * 0.58, VIEW_H - 8 + bob - kick
        c.create_polygon(x, y, x + 250, y + 18, x + 230, y + 64, x - 30, y + 42, fill="#6d734c", outline="#2a2e20", width=2, tags="dyn")
        c.create_polygon(x + 36, y + 6, x + 230, y - 8, x + 214, y + 22, x + 24, y + 30, fill="#8c9364", outline="", tags="dyn")
        c.create_rectangle(x + 160, y + 4, x + 360, y + 16, fill="#2e3228", outline="", tags="dyn")
        c.create_oval(x + 78, y + 22, x + 142, y + 58, fill="#c4a574", outline="", tags="dyn")
        self._kick = max(0, kick - 4)

    def _hud(self) -> None:
        c, raid = self.canvas, self.raid
        c.create_rectangle(0, VIEW_H, W, H, fill="#12110e", outline="", tags="dyn")
        c.create_text(28, VIEW_H + 36, anchor="w", text=str(raid.score), fill="#f7f4ee", font=("Helvetica", 28, "bold"), tags="dyn")
        c.create_text(28, VIEW_H + 68, anchor="w", text=raid.mission, fill="#c7bba8", font=("Helvetica", 14), tags="dyn")
        c.create_text(W - 28, VIEW_H + 34, anchor="e", text=raid.gun.name, fill="#f7f4ee", font=("Helvetica", 16, "bold"), tags="dyn")
        ammo = "RELOADING" if raid.reload_t > 0 else f"{raid.gun.mag}  /  {raid.gun.reserve}"
        c.create_text(W - 28, VIEW_H + 62, anchor="e", text=ammo, fill="#e6c15a", font=("Helvetica", 18, "bold"), tags="dyn")
        c.create_rectangle(240, VIEW_H + 28, 520, VIEW_H + 44, outline="#3a342c", width=1, tags="dyn")
        c.create_rectangle(240, VIEW_H + 28, 240 + 280 * raid.health / 100, VIEW_H + 44, fill="#d9c7a2", outline="", tags="dyn")
        c.create_text(240, VIEW_H + 58, anchor="w", text=f"HEALTH {raid.health}", fill="#a39888", font=("Helvetica", 11), tags="dyn")
        device = self.hub.active_device()
        draw_legend(c, W / 2, H - 22, legend("desert", device=device), size=11, max_width=W - 40)
        state = self.state if self.state in ("ready", "paused", "over", "won") else ""
        if raid.banner_t > 0 and self.state == "playing":
            nxt = MISSIONS.get(raid.pending, "Clear")
            self._banner("AREA CLEAR", nxt, legend("desert", "ready", device=device))
        elif state == "ready":
            self._banner("DESERT 91", "Outside Kuwait, 1991. Clear three positions.", legend("desert", "ready", device=device))
        elif state == "paused":
            self._banner("PAUSED", "", legend("desert", "paused", device=device))
        elif state == "over":
            best = int(self.hub.best("desert") or 0)
            self._banner("DOWN", f"score {raid.score:,} · best {best:,}", legend("desert", "over", device=device))
        elif state == "won":
            best = int(self.hub.best("desert") or raid.score)
            self._banner("POSITIONS CLEAR", f"score {raid.score:,} · best {best:,}", legend("desert", "over", device=device))

    def _banner(self, title: str, text: str, items: tuple[tuple[str, str], ...]) -> None:
        c = self.canvas
        round_rect(c, 160, 140, W - 160, 340, 18, fill="#16140f", outline="#e6c15a", width=2, tags="dyn")
        c.create_text(W / 2, 190, text=title, fill="#f7f4ee", font=("Helvetica", 32, "bold"), tags="dyn")
        if text:
            c.create_text(W / 2, 236, text=text, fill="#d9c7a2", font=("Helvetica", 14), tags="dyn")
        draw_legend(c, W / 2, 290, items, size=14)

    def close(self) -> None:
        self._unlock()
        self.top.after_cancel(self._job)
        self.top.destroy()
        self.on_close()

    def lift(self) -> None:
        self.top.deiconify()
        self.top.lift()
        self.top.focus_force()


def _tones() -> dict[str, str]:
    paths: dict[str, str] = {}
    for name, (freq, ms, noise) in {"shot": (110, 70, 0.9), "hit": (240, 80, 0.35)}.items():
        try:
            fd, path = tempfile.mkstemp(prefix=f"sideband-{name}-", suffix=".wav")
            os.close(fd)
            with open(path, "wb") as handle:
                handle.write(tone_wav(freq, ms, 0.35, noise))
            paths[name] = path
        except OSError:
            continue
    return paths


def _blip(path: str | None) -> None:
    if not path:
        return
    try:
        subprocess.Popen(["afplay", "-v", "0.45", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass
