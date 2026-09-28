"""Sky Ace 1943 on a Tk canvas: a small software 3D renderer for `skyfighter.Dogfight`.

Chase camera behind the plane that rolls with its bank (the horizon tilts), flat-shaded polygons lit by
the sun, back faces culled, depth fog, painter's order. Controls come from the launcher:
tilt steers, tap fires, double tap fires long, shake barrel-rolls, hold pauses.
"""

from __future__ import annotations

import math
import random
import time
import tkinter as tk
from typing import TYPE_CHECKING, Callable

from sideband.legend import draw_legend, legend
from sideband.meshes import ENEMY, SPITFIRE, Mesh, Vec, apply, bomber, dot, face_normal, fighter, propeller, rotation, unit
from sideband.minigames import Stick
from sideband.skyfighter import Dogfight

if TYPE_CHECKING:
    from sideband.ui import Hub

W, H = 960, 640
FOCAL = 560.0
NEAR, FAR = 1.5, 420.0
FRAME_MS = 22
CAM_BACK, CAM_UP = 17.0, 4.0
SUN = unit((0.45, 0.85, -0.35))
SKY_TOP, SKY_LOW = (70, 120, 190), (196, 214, 226)
HAZE = (190, 206, 220)
SEA, LAND = (46, 88, 112), (88, 110, 70)


def _rgb(c: tuple[float, float, float]) -> str:
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(v))) for v in c)


def _mix(a, b, t: float) -> tuple[float, float, float]:
    t = max(0.0, min(1.0, t))
    return tuple(x + (y - x) * t for x, y in zip(a, b))  # type: ignore[return-value]


class FighterWindow:
    def __init__(self, hub: Hub, on_close: Callable[[], None]) -> None:
        self.hub, self.on_close = hub, on_close
        self.top = tk.Toplevel(hub.root)
        self.top.title("Omi Arcade · Sky Ace 1943")
        self.top.resizable(False, False)
        self.canvas = tk.Canvas(self.top, width=W, height=H, highlightthickness=0, bg=_rgb(SKY_TOP))
        self.canvas.pack()
        self.models = {"player": fighter(SPITFIRE), "fighter": fighter(ENEMY, roundels=False), "bomber": bomber()}
        self.keys: set[str] = set()
        self.state = "ready"  # ready → playing ⇄ paused → over
        self.cam = [0.0, 20.0 + CAM_UP]
        self.cam_roll = 0.0
        self.prop = 0.0
        self.rng = random.Random()
        self.recorded = False
        self.new_game()
        self.clouds = [self._cloud(self.rng.uniform(0, FAR)) for _ in range(26)]
        self._sky()
        self.top.bind("<KeyPress>", self._key_down)
        self.top.bind("<KeyRelease>", lambda e: self.keys.discard(e.keysym.lower()))
        self.top.protocol("WM_DELETE_WINDOW", self.close)
        self.top.focus_force()
        self._last = time.monotonic()
        self._tick()

    def new_game(self) -> None:
        self.game = Dogfight(seed=self.rng.randrange(1 << 30))
        self.state, self.recorded, self.over_at = "ready", False, 0.0
        self.hub.recentre()

    # --- the Omi's buttons: same flow in every Arcade game -----------------------------------

    def on_tap(self, kind: str) -> None:
        """In the air: tap fires, double tap fires long. Otherwise one tap goes forward, double tap back."""
        forward = kind == "single"
        if self.state == "playing":
            self.game.trigger(long=not forward)
            return
        if not forward:
            self.close()  # back to the Arcade
            return
        if self.state == "over":
            if time.monotonic() - self.over_at < 0.8:
                return  # a late trigger tap should not restart at once
            self.new_game()
        self.hub.recentre()  # take off or resume from however you're holding it now
        self.state = "playing"
        self.game.started = True

    @property
    def playing(self) -> bool:
        return self.state == "playing"

    def on_shake(self) -> None:
        if self.state == "playing":
            self.game.barrel_roll()

    def on_hold(self) -> None:
        if self.state == "playing":
            self.state = "paused"

    def _key_down(self, event: tk.Event) -> None:
        key = event.keysym.lower()
        self.keys.add(key)
        if key in ("space", "return"):
            self.on_tap("single")
        elif key == "escape":
            self.on_tap("double") if self.state != "playing" else self.on_hold()
        elif key == "b":
            self.on_shake()
        elif key == "c":
            self.hub.recentre()

    def _stick(self) -> tuple[float, float, str]:
        pendant = self.hub.stick()
        if pendant is not None:
            return pendant
        x = (1.0 if self.keys & {"right", "d"} else 0.0) - (1.0 if self.keys & {"left", "a"} else 0.0)
        y = (1.0 if self.keys & {"down", "s"} else 0.0) - (1.0 if self.keys & {"up", "w"} else 0.0)
        return x, -y, "keys"

    # --- loop -----------------------------------------------------------------------------

    def _tick(self) -> None:
        self._job = self.top.after(FRAME_MS, self._tick)
        now = time.monotonic()
        dt = min(0.05, now - self._last)
        self._last = now
        g = self.game
        x, y, self.source = self._stick()
        if self.state == "playing":
            g.step(dt, Stick(x, y))
            if g.over:
                self.state = "over"
                self.over_at = time.monotonic()
        if g.over and not self.recorded:
            self.recorded = True
            self.hub.record_score("fighter", float(g.score))
        ease = min(1.0, dt * 4)
        self.cam[0] += (g.x - self.cam[0]) * ease
        self.cam[1] += (g.y + CAM_UP - self.cam[1]) * ease
        self.cam_roll += (g.bank * 0.55 - self.cam_roll) * min(1.0, dt * 3)
        self.prop += dt * 40
        for cloud in self.clouds:
            if cloud[2] < g.z - 10:
                cloud[:] = self._cloud(FAR * 0.9)
        self._draw()

    def _cloud(self, ahead: float) -> list[float]:
        return [self.rng.uniform(-150, 150), self.rng.uniform(20, 90), self.game.z + ahead, self.rng.uniform(8, 22)]

    # --- 3D -------------------------------------------------------------------------------

    def _to_camera(self, p: Vec) -> Vec:
        x, y, z = p[0] - self.cam[0], p[1] - self.cam[1], p[2] - (self.game.z - CAM_BACK)
        c, s = math.cos(self.cam_roll), math.sin(self.cam_roll)
        return x * c - y * s, x * s + y * c, z  # the camera rolls with the plane

    def _project(self, v: Vec) -> tuple[float, float]:
        return W / 2 + FOCAL * v[0] / v[2], H / 2 - FOCAL * v[1] / v[2]

    def _mesh(self, mesh: Mesh, at: Vec, matrix, flash: bool, out: list) -> None:
        world = [(at[0] + r[0], at[1] + r[1], at[2] + r[2]) for r in (apply(matrix, v) for v in mesh.vertices)]
        cam = [self._to_camera(p) for p in world]
        for indices, colour in mesh.faces:
            pts = [cam[i] for i in indices]
            if min(p[2] for p in pts) < NEAR:
                continue
            normal = face_normal([world[i] for i in indices])
            eye = world[indices[0]]
            view = (eye[0] - self.cam[0], eye[1] - self.cam[1], eye[2] - (self.game.z - CAM_BACK))
            if dot(normal, view) >= 0:
                continue  # back face
            depth = sum(p[2] for p in pts) / len(pts)
            screen = [self._project(p) for p in pts]
            area = abs(sum(screen[i][0] * screen[(i + 1) % len(screen)][1] - screen[(i + 1) % len(screen)][0] * screen[i][1] for i in range(len(screen)))) / 2
            if area < 1.5:
                continue
            light = 0.38 + 0.62 * max(0.0, dot(normal, SUN))
            base = (255, 255, 255) if flash else colour
            shade = _mix(tuple(c * light for c in base), HAZE, (depth / FAR) ** 1.4)
            out.append((depth, "poly", [c for xy in screen for c in xy], _rgb(shade)))

    def _sky(self) -> None:
        for i in range(20):
            self.canvas.create_rectangle(0, i * H / 20, W, (i + 1) * H / 20 + 1,
                                         fill=_rgb(_mix(SKY_TOP, SKY_LOW, i / 19)), outline="", tags="sky")

    def _ground(self) -> None:
        c, g = self.canvas, self.game
        far = [self._to_camera((x, 0.0, g.z + 3000)) for x in (-6000, 6000)]
        left, right = (self._project(p) for p in far)
        dx, dy = right[0] - left[0], right[1] - left[1]
        n = math.hypot(dx, dy) or 1
        down = (-dy / n * 3000, dx / n * 3000)
        if self._project(self._to_camera((g.x, 0.0, g.z + 40)))[1] < left[1] + (right[1] - left[1]) / 2:
            down = (-down[0], -down[1])
        c.create_polygon(left[0], left[1], right[0], right[1], right[0] + down[0], right[1] + down[1],
                         left[0] + down[0], left[1] + down[1], fill=_rgb(SEA), outline="", tags="dyn")
        base = int(g.z // 30) * 30
        for k in range(1, 14):  # waves and field lines rushing by
            z = base + k * 30
            a = self._to_camera((g.x - 400, 0.0, z))
            b = self._to_camera((g.x + 400, 0.0, z))
            if a[2] > NEAR and b[2] > NEAR:
                shade = _rgb(_mix((70, 120, 145), SEA, z / (g.z + FAR)))
                c.create_line(*self._project(a), *self._project(b), fill=shade, tags="dyn")
        for x in range(-240, 241, 60):
            a, b = self._to_camera((x, 0.0, g.z + 3)), self._to_camera((x, 0.0, g.z + FAR))
            if a[2] > NEAR:
                c.create_line(*self._project(a), *self._project(b), fill=_rgb(_mix(SEA, LAND, 0.5)), tags="dyn")

    def _draw(self) -> None:
        c, g = self.canvas, self.game
        c.delete("dyn")
        self._ground()
        items: list = []
        for cx, cy, cz, size in self.clouds:
            v = self._to_camera((cx, cy, cz))
            if 45 < v[2] < FAR:  # closer than that a cloud would swallow the screen
                sx, sy = self._project(v)
                r = FOCAL * size / v[2]
                items.append((v[2], "cloud", (sx, sy, r), _rgb(_mix((250, 250, 252), HAZE, v[2] / FAR))))
        for e in g.enemies:
            wobble = math.sin(g.clock * 1.3 + e.phase) * 0.5
            self._mesh(self.models[e.kind], (e.x, e.y, e.z), rotation(yaw=math.pi, roll=-wobble), e.hit_flash > 0, items)
            if e.kind == "fighter":
                self._mesh(propeller(-self.prop), (e.x, e.y, e.z), rotation(yaw=math.pi), False, items)
        for s in g.shots:
            a = self._to_camera((s.x, s.y, s.z))
            b = self._to_camera((s.x - s.vx * 0.03, s.y - s.vy * 0.03, s.z - s.vz * 0.03))
            if a[2] > NEAR and b[2] > NEAR:
                colour = "#ff7a3d" if s.enemy else "#fff1a8"
                items.append((a[2], "line", [*self._project(a), *self._project(b)], colour))
        for boom in g.booms:
            v = self._to_camera((boom.x, boom.y, boom.z))
            if v[2] > NEAR:
                sx, sy = self._project(v)
                r = FOCAL * boom.size * (2 + 9 * boom.age) / v[2]
                items.append((v[2], "boom", (sx, sy, r, boom.age), ""))
        hidden = g.hurt > 0 and int(g.hurt * 12) % 2 == 0
        if not hidden and not (g.over and self.state == "over"):
            matrix = rotation(pitch=g.pitch, roll=g.bank)
            self._mesh(self.models["player"], (g.x, g.y, g.z), matrix, False, items)
            self._mesh(propeller(self.prop), (g.x, g.y, g.z), matrix, False, items)
        for depth, kind, data, colour in sorted(items, key=lambda item: -item[0]):
            if kind == "poly":
                c.create_polygon(data, fill=colour, outline=colour, tags="dyn")
            elif kind == "line":
                c.create_line(data, fill=colour, width=3, tags="dyn")
            elif kind == "cloud":
                sx, sy, r = data
                for ox, oy, k in ((-0.6, 0.1, 0.7), (0.5, 0.15, 0.75), (0.0, -0.15, 1.0)):
                    c.create_oval(sx + ox * r - k * r, sy + oy * r - k * r * 0.55, sx + ox * r + k * r, sy + oy * r + k * r * 0.55,
                                  fill=colour, outline="", stipple="gray75", tags="dyn")
            else:
                sx, sy, r, age = data
                for k, col in ((1.0, "#5a5048"), (0.7, "#ff8a1c"), (0.4, "#ffe27a")):
                    if age < 0.9 or k == 1.0:
                        c.create_oval(sx - r * k, sy - r * k, sx + r * k, sy + r * k, fill=col, outline="",
                                      stipple="gray50" if age > 0.6 else "", tags="dyn")
        self._hud()

    # --- HUD ------------------------------------------------------------------------------

    def _hud(self) -> None:
        c, g = self.canvas, self.game
        sight = self._to_camera((g.x, g.y, g.z + 90))
        if sight[2] > NEAR and self.state == "playing":
            sx, sy = self._project(sight)
            c.create_oval(sx - 16, sy - 16, sx + 16, sy + 16, outline="#ffe27a", width=2, tags="dyn")
            c.create_line(sx - 26, sy, sx - 8, sy, fill="#ffe27a", width=2, tags="dyn")
            c.create_line(sx + 8, sy, sx + 26, sy, fill="#ffe27a", width=2, tags="dyn")
        c.create_rectangle(0, 0, W, 44, fill="#0b1633", outline="", stipple="gray50", tags="dyn")
        c.create_text(18, 22, anchor="w", text=f"{g.score:,}", fill="white", font=("Helvetica", 22, "bold"), tags="dyn")
        c.create_text(150, 22, anchor="w", text=f"✈ {g.kills} down · wave {g.wave}", fill="#cfe0ff", font=("Helvetica", 15, "bold"), tags="dyn")
        bar = 220 * g.health / 100
        colour = "#3ddc84" if g.health > 50 else "#ffb347" if g.health > 25 else "#ff4d4d"
        c.create_rectangle(W - 250, 14, W - 30, 30, outline="#cfe0ff", width=2, tags="dyn")
        c.create_rectangle(W - 250, 14, W - 250 + bar, 30, fill=colour, outline="", tags="dyn")
        roll = "ROLL READY · shake" if not g.roll_ready and not g.roll else ("ROLLING!" if g.roll else f"roll in {g.roll_ready:.1f}s")
        c.create_text(W - 260, 22, anchor="e", text=roll, fill="#ffe27a", font=("Helvetica", 13, "bold"), tags="dyn")
        c.create_rectangle(0, H - 36, W, H, fill="#0b1633", outline="", stipple="gray50", tags="dyn")
        draw_legend(c, W / 2, H - 18, legend("fighter", motion=self.source != "keys"), size=12, max_width=W - 24)
        if self.state == "ready":
            self._banner("SKY ACE 1943", "shoot down the bombers · watch your six", legend("fighter", "ready"), "#ffcf3d")
        elif self.state == "paused":
            self._banner("PAUSED", "", legend("fighter", "paused"), "#7fd4ff")
        elif self.state == "over":
            best = int(self.hub.best("fighter") or 0)
            self._banner("SHOT DOWN", f"score {g.score:,} · {g.kills} kills · best {best:,}", legend("fighter", "over"), "#ff6b5b")

    def _banner(self, title: str, text: str, items: tuple[tuple[str, str], ...], colour: str) -> None:
        c = self.canvas
        c.create_rectangle(W / 2 - 330, H / 2 - 110, W / 2 + 330, H / 2 + 90, fill="#0b1633", outline=colour, width=4, stipple="gray75", tags="dyn")
        c.create_text(W / 2 + 3, H / 2 - 52, text=title, fill="#000000", font=("Helvetica", 46, "bold italic"), tags="dyn")
        c.create_text(W / 2, H / 2 - 55, text=title, fill=colour, font=("Helvetica", 46, "bold italic"), tags="dyn")
        if text:
            c.create_text(W / 2, H / 2 + 2, text=text, fill="white", font=("Helvetica", 16, "bold"), justify="center", tags="dyn")
        draw_legend(c, W / 2, H / 2 + 50, items, size=18)

    def close(self) -> None:
        self.top.after_cancel(self._job)
        self.top.destroy()
        self.on_close()

