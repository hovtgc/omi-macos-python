"""Star Dodger in Ursina. Rocks still come from `minigames.StarDodger`.

A small ship in a purple nebula, asteroids drifting in, shots going out ahead.
The stick mapping matches the flat game, including the pendant and a pad.
"""

from __future__ import annotations

import random
import time
from typing import Any

from sideband.minigames import FIELD_H, FIELD_W, StarDodger, Stick
from sideband.sfx import blip
from sideband.stage import Session, aim, haze, label, paint, sky_image, stick, sun, toggle_fullscreen

SCALE = 0.16


def _place(x: float, y: float) -> tuple[float, float, float]:
    return ((x - FIELD_W / 2) * SCALE, 0.0, (FIELD_H * 0.75 - y) * SCALE)


class DodgerSession(Session):
    key = "dodger"
    title = "Star Dodger — Sideband"

    def __init__(self, hub: Any, on_close: Any) -> None:
        super().__init__(hub, on_close)
        self.rng = random.Random(7)
        self.game = StarDodger(seed=self.rng.randrange(1 << 30))
        self.taps = 0
        self.shake = False
        self._ship: Any = None
        self._rocks: list[Any] = []
        self._shots: list[Any] = []
        self._texts: dict[str, Any] = {}

    def on_tap(self, kind: str) -> None:
        forward = kind == "single"
        if self.state == "playing":
            self.taps += 1 if forward else 2
            return
        if not forward:
            self.close()
            return
        if self.state == "over":
            if time.monotonic() - self.over_at < 0.8:
                return
            self.game = StarDodger(seed=self.rng.randrange(1 << 30))
            self.recorded = False
        self.hub.recentre()
        self.state = "playing"

    def on_hold(self) -> None:
        if self.state == "playing":
            self.state = "paused"

    def on_shake(self) -> None:
        if self.state == "playing":
            self.shake = True

    def build(self) -> None:
        from ursina import Entity, camera, color, window
        from ursina.prefabs.sky import Sky
        from ursina.shaders import lit_with_shadows_shader as lit
        from ursina.shaders import unlit_shader

        window.color = color.rgba32(18, 10, 36, 255)
        camera.fov = 72
        camera.clip_plane_far = 80
        nebula = paint("nebula", sky_image([
            (0.0, (18, 10, 40)),
            (0.4, (70, 30, 110)),
            (0.7, (140, 50, 120)),
            (1.0, (40, 16, 70)),
        ]))
        haze((48, 24, 72), 8, 36, 140)
        self.own(Sky(texture=nebula, color=color.white, unlit=True))
        rng = random.Random(3)
        for _ in range(40):
            self.own(Entity(
                model="sphere", shader=unlit_shader, unlit=True,
                position=(rng.uniform(-16, 16), rng.uniform(-4, 8), rng.uniform(-4, 28)),
                scale=rng.uniform(0.02, 0.08), color=color.rgba32(255, 240, 255, 255),
            ))
        light, fill = sun(warm=(180, 140, 255), ambient=(40, 30, 70), shadows=False, rotation=(40, 20, 0))
        self.own(light)
        self.own(fill)
        self._ship = self.own(Entity())
        Entity(parent=self._ship, model="cube", shader=lit, color=color.rgba32(230, 236, 245, 255), scale=(0.35, 0.12, 0.9))
        Entity(parent=self._ship, model="cube", shader=lit, color=color.rgba32(90, 180, 255, 255), scale=(1.5, 0.05, 0.35), position=(0, 0, -0.1))
        Entity(parent=self._ship, model="sphere", shader=unlit_shader, unlit=True, color=color.rgba32(120, 220, 255, 255), scale=0.12, position=(0, 0.08, 0.35))
        self.light_owned()
        self._texts["hud"] = self.own(label("STAR DODGER", (-0.86, 0.46), 1.7))
        self._texts["center"] = self.own(label("", (-0.4, 0.04), 2.0))

    def frame(self, dt: float) -> None:
        from ursina import camera, color

        self._keys()
        g = self.game
        if self.state == "playing":
            before = g.score
            x, y = self._axes()
            g.step(dt, Stick(x, y, self.taps, self.shake))
            if g.score > before:
                blip("pop", 640, 40, 0.16)
            if g.over and not self.recorded:
                self.recorded = True
                self.over_at = time.monotonic()
                self.state = "over"
                self.hub.record_score("dodger", float(g.score))
        self.taps, self.shake = 0, False
        if self._ship is not None:
            self._ship.position = _place(g.x, g.y)
            self._ship.rotation_z = -x_lean(g)
            flash = g.flash_s > 0
            if flash:
                self._ship.color = color.rgba32(255, 255, 255, 255)
        self._sync_rocks()
        self._sync_shots()
        sx, sy, sz = _place(g.x, g.y)
        camera.position = (sx * 0.3, 2.1, sz - 3.4)
        camera.look_at((sx * 0.2, 0.3, sz + 7))
        best = self.hub.best("dodger")
        tail = f"   best {best:g}" if best else ""
        chain = f"   ×{g.combo}" if g.combo else ""
        self._texts["hud"].text = f"WAVE {g.wave}   {g.score}{chain}{tail}   LIVES {g.lives}   BOMBS {g.bombs}"
        center = ""
        if self.state == "ready":
            center = "CLICK TO LAUNCH"
        elif self.state == "paused":
            center = "PAUSED"
        elif self.state == "over":
            center = f"HULL GONE   {g.score}"
        self._texts["center"].text = center

    def _keys(self) -> None:
        pressed = self.fresh()
        if pressed:
            self.hub.note_device("keys")
        if "f11" in pressed:
            toggle_fullscreen()
        if "escape" in pressed:
            if self.state == "playing":
                self.on_hold()
            else:
                self.close()
            return
        if self.state != "playing":
            if pressed & {"enter", "space", "left mouse"}:
                self.on_tap("single")
            return
        if pressed & {"space", "enter", "left mouse"}:
            self.on_tap("single")
        if "x" in pressed:
            self.on_tap("double")
        if "b" in pressed:
            self.on_shake()

    def _axes(self) -> tuple[float, float]:
        x, y = aim(stick())
        if x == 0.0 and y == 0.0:
            axes = self.hub.play_axes()
            if axes is not None:
                return max(-1.0, min(1.0, axes[0])), max(-1.0, min(1.0, axes[1]))
        return x, y

    def _sync_rocks(self) -> None:
        from ursina import Entity, color
        from ursina.shaders import lit_with_shadows_shader as lit

        rocks = self.game.rocks
        while len(self._rocks) < len(rocks):
            tint = ((120, 90, 140), (90, 70, 110), (160, 100, 80))[len(self._rocks) % 3]
            rock = self.own(Entity(model="sphere", shader=lit, color=color.rgba32(*tint, 255)))
            from sideband.stage import shade_tree

            shade_tree(rock)
            self._rocks.append(rock)
        for entity, rock in zip(self._rocks, rocks):
            entity.enabled = True
            entity.position = _place(rock[0], rock[1])
            entity.scale = rock[2] * SCALE * 2.4
        for entity in self._rocks[len(rocks):]:
            entity.enabled = False

    def _sync_shots(self) -> None:
        from ursina import Entity, color
        from ursina.shaders import unlit_shader

        shots = self.game.bullets
        while len(self._shots) < len(shots):
            self._shots.append(self.own(Entity(model="cube", shader=unlit_shader, unlit=True, color=color.rgba32(140, 220, 255, 255), scale=(0.06, 0.06, 0.4))))
        for entity, shot in zip(self._shots, shots):
            entity.enabled = True
            entity.position = _place(shot[0], shot[1])
        for entity in self._shots[len(shots):]:
            entity.enabled = False


def x_lean(game: StarDodger) -> float:
    return max(-18.0, min(18.0, (game.x - FIELD_W / 2) * 0.4))
