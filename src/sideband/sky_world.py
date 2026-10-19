"""Sky Ace 1943 in Ursina. The dogfight stays in `skyfighter.py`.

A chase camera behind a silver fighter, golden-hour desert under the wings, tracers
and bombers ahead. Keyboard and mouse fly it; tilt and a pad come through the hub.
"""

from __future__ import annotations

import math
import random
import time
from typing import Any

from sideband.minigames import Stick
from sideband.sfx import blip
from sideband.skyfighter import Dogfight
from sideband.stage import (
    Session, aim, alloy_image, cloud_image, grade, haze, label, paint, sand_image, sky_image, stick, sun,
    toggle_fullscreen, vignette,
)


class SkySession(Session):
    key = "fighter"
    title = "Sky Ace 1943 — Sideband"

    def __init__(self, hub: Any, on_close: Any) -> None:
        super().__init__(hub, on_close)
        self.rng = random.Random(1943)
        self.game = Dogfight(seed=self.rng.randrange(1 << 30))
        self._craft: dict[int, Any] = {}
        self._shots: list[Any] = []
        self._booms: list[Any] = []
        self._plane: Any = None
        self._ground: Any = None
        self._texts: dict[str, Any] = {}
        self._hurt = 0.0

    def on_tap(self, kind: str) -> None:
        forward = kind == "single"
        if self.state == "playing":
            self.game.trigger(long=not forward)
            blip("guns", 240, 30, 0.16, noise=0.4)
            return
        if not forward:
            self.close()
            return
        if self.state == "over":
            if time.monotonic() - self.over_at < 0.8:
                return
            self._restart()
        self.hub.recentre()
        self.state = "playing"
        self.game.started = True

    def on_hold(self) -> None:
        if self.state == "playing":
            self.state = "paused"

    def on_shake(self) -> None:
        if self.state == "playing" and self.game.barrel_roll():
            blip("roll", 180, 90, 0.18)

    def _restart(self) -> None:
        self.game = Dogfight(seed=self.rng.randrange(1 << 30))
        self.recorded = False
        self.state = "ready"
        self._hurt = 0.0

    def build(self) -> None:
        from ursina import Entity, camera, color, window
        from ursina.prefabs.sky import Sky
        from ursina.shaders import lit_with_shadows_shader as lit

        window.color = color.rgba32(86, 120, 168, 255)
        camera.fov = 70
        camera.clip_plane_far = 420
        camera.clip_plane_near = 0.2
        sky = paint("ace-sky", sky_image([
            (0.0, (36, 78, 160)),
            (0.9, (92, 150, 206)),
            (0.96, (236, 168, 96)),
            (1.0, (204, 132, 72)),
        ]))
        haze((232, 176, 120), 80, 360, 150)
        dome = self.own(Sky(texture=sky, color=color.white, unlit=True))
        from ursina.shaders import unlit_shader

        try:
            dome.setFogOff()
        except Exception:
            pass
        sand = paint("sand", sand_image())
        self._ground = self.own(Entity(model="plane", texture=sand, texture_scale=(24, 24), shader=lit, scale=(500, 1, 500), color=color.rgba32(210, 168, 112, 255)))
        light, fill = sun(warm=(255, 210, 160), ambient=(130, 118, 108), shadows=True, rotation=(18, -36, 0))
        self.own(light)
        self.own(fill)
        haze((232, 176, 120), 50, 320, 180)
        self._plane = self._fighter(lit, (188, 196, 206), (176, 132, 48), (36, 64, 112))
        self._clouds(unlit_shader)
        self.light_owned()
        grade("sky")
        vignette(self)
        self._texts["hud"] = self.own(label("SKY ACE 1943", (-0.86, 0.46), 1.7))
        self._texts["sub"] = self.own(label("Arrows fly. Space fires. B rolls. Esc pauses.", (-0.86, 0.39), 1.2))
        self._texts["center"] = self.own(label("", (-0.4, 0.06), 2.0))

    def _clouds(self, unlit: Any) -> None:
        from ursina import Entity, color

        puff = paint("cloud", cloud_image())
        self._cloud_bits = []
        rng = random.Random(19)
        for _i in range(10):
            bit = self.own(Entity(
                model="quad", texture=puff, shader=unlit, unlit=True, double_sided=True,
                color=color.rgba(1, 0.97, 0.92, 0.55),
                position=(rng.choice((-1, 1)) * rng.uniform(36, 170), rng.uniform(36, 64), rng.uniform(50, 240)),
                scale=rng.uniform(14, 28),
                rotation=(12, rng.uniform(0, 180), 0),
            ))
            bit._unlit = True
            bit._band = bit.z
            self._cloud_bits.append(bit)

    def _drift_clouds(self, z: float) -> None:
        for bit in getattr(self, "_cloud_bits", ()):
            if bit.z < z - 30:
                bit.z += 280

    def _fighter(self, lit: Any, body: tuple[int, int, int], nose: tuple[int, int, int], wing: tuple[int, int, int], scale: float = 1.0) -> Any:
        from ursina import Entity, color

        metal = paint("alloy", alloy_image())
        root = self.own(Entity(scale=scale))
        Entity(parent=root, model="cube", shader=lit, texture=metal, color=color.rgba32(*body, 255), scale=(0.72, 0.58, 3.4), position=(0, 0, 0.15))
        Entity(parent=root, model="cube", shader=lit, texture=metal, color=color.rgba32(*nose, 255), scale=(0.42, 0.36, 0.9), position=(0, 0, 1.85))
        Entity(parent=root, model="cube", shader=lit, texture=metal, color=color.rgba32(*wing, 255), scale=(6.6, 0.07, 1.15), position=(0, 0.02, 0.15))
        Entity(parent=root, model="cube", shader=lit, color=color.rgba32(180, 40, 36, 255), scale=(0.55, 0.06, 0.55), position=(-2.2, 0.08, 0.15))
        Entity(parent=root, model="cube", shader=lit, color=color.rgba32(180, 40, 36, 255), scale=(0.55, 0.06, 0.55), position=(2.2, 0.08, 0.15))
        Entity(parent=root, model="cube", shader=lit, texture=metal, color=color.rgba32(*body, 255), scale=(0.1, 1.05, 0.72), position=(0, 0.62, -1.25))
        Entity(parent=root, model="cube", shader=lit, color=color.rgba32(*wing, 255), scale=(2.4, 0.05, 0.5), position=(0, 1.05, -1.35))
        from ursina.shaders import unlit_shader

        canopy = Entity(parent=root, model="sphere", shader=unlit_shader, unlit=True, color=color.rgba32(150, 196, 210, 160), scale=(0.46, 0.28, 0.9), position=(0, 0.34, 0.2))
        canopy._unlit = True
        prop = Entity(parent=root, position=(0, 0, 2.35))
        Entity(parent=prop, model="cube", shader=lit, color=color.rgba32(36, 38, 42, 255), scale=(1.85, 0.08, 0.06))
        Entity(parent=prop, model="cube", shader=lit, color=color.rgba32(36, 38, 42, 255), scale=(0.08, 1.85, 0.06))
        root._prop = prop
        from sideband.stage import shade_tree

        shade_tree(root)
        return root

    def frame(self, dt: float) -> None:
        from ursina import camera, color
        from ursina.shaders import lit_with_shadows_shader as lit
        from ursina.shaders import unlit_shader

        self._keys()
        g = self.game
        if self.state == "playing":
            before = g.score
            x, y = self._axes()
            g.step(dt, Stick(x, y))
            if g.score > before:
                blip("hit", 660, 40, 0.18)
            if g.hurt > self._hurt:
                blip("ping", 140, 50, 0.16)
            self._hurt = g.hurt
            if g.over and not self.recorded:
                self.recorded = True
                self.over_at = time.monotonic()
                self.state = "over"
                self.hub.record_score("fighter", float(g.score))
        if self._plane is not None:
            self._plane.position = (g.x, g.y, g.z)
            self._plane.rotation = (math.degrees(g.pitch), 0, -math.degrees(g.bank))
            prop = getattr(self._plane, "_prop", None)
            if prop is not None:
                prop.rotation_z += dt * 1600
        self._drift_clouds(g.z)
        if self._ground is not None:
            self._ground.position = (0, 0, g.z)
        self._sync_enemies(lit)
        self._sync_shots(unlit_shader)
        self._sync_booms()
        jolt = g.shake * 0.35
        camera.position = (g.x * 0.85 + math.sin(g.clock * 40) * jolt, g.y + 6.5, g.z - 16)
        camera.look_at((g.x, g.y + 0.5, g.z + 36))
        best = self.hub.best("fighter")
        tail = f"   best {best:g}" if best else ""
        chain = f"   ×{g.combo}" if g.combo else ""
        self._texts["hud"].text = f"WAVE {g.wave}   {g.score}{chain}{tail}   HULL {int(g.health)}"
        center = ""
        if self.state == "ready":
            center = "CLICK TO TAKE OFF"
        elif self.state == "paused":
            center = "PAUSED"
        elif self.state == "over":
            center = f"SHOT DOWN   {g.score}"
        self._texts["center"].text = center
        if g.hurt > 0:
            self._texts["center"].color = color.rgba32(255, 140, 120, 255)
        else:
            self._texts["center"].color = color.rgba32(245, 240, 230, 255)

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
        if "c" in pressed:
            self.hub.recentre()

    def _axes(self) -> tuple[float, float]:
        x, y = aim(stick())
        if x == 0.0 and y == 0.0:
            axes = self.hub.play_axes()
            if axes is not None:
                return max(-1.0, min(1.0, axes[0])), max(-1.0, min(1.0, axes[1]))
        return x, y

    def _sync_enemies(self, lit: Any) -> None:
        from ursina import color

        from ursina import destroy

        live = {id(e): e for e in self.game.enemies}
        for key, body in list(self._craft.items()):
            if key not in live:
                destroy(body)
                self._craft.pop(key, None)
        for enemy in self.game.enemies:
            body = self._craft.get(id(enemy))
            if body is None:
                scale = 1.15 if enemy.kind == "fighter" else 2.4
                paint_body = (70, 78, 58) if enemy.kind == "fighter" else (90, 78, 60)
                body = self._fighter(lit, paint_body, (40, 36, 32), (50, 56, 44), scale=scale)
                self._craft[id(enemy)] = body
            body.enabled = True
            body.position = (enemy.x, enemy.y, enemy.z)
            body.rotation_y = 180
            if enemy.hit_flash > 0:
                body.color = color.rgba32(255, 180, 120, 255)

    def _sync_shots(self, unlit: Any) -> None:
        from ursina import Entity, color

        shots = self.game.shots[:48]
        while len(self._shots) < len(shots):
            self._shots.append(self.own(Entity(model="cube", shader=unlit, unlit=True, scale=(0.15, 0.15, 1.4))))
        for entity, shot in zip(self._shots, shots):
            entity.enabled = True
            entity.position = (shot.x, shot.y, shot.z)
            entity.color = color.rgba32(255, 90, 70, 255) if shot.enemy else color.rgba32(255, 230, 140, 255)
        for entity in self._shots[len(shots):]:
            entity.enabled = False

    def _sync_booms(self) -> None:
        from ursina import Entity, color
        from ursina.shaders import unlit_shader

        booms = self.game.booms
        while len(self._booms) < len(booms):
            self._booms.append(self.own(Entity(model="sphere", shader=unlit_shader, unlit=True)))
        for entity, boom in zip(self._booms, booms):
            entity.enabled = True
            grow = boom.size * (0.6 + boom.age * 4)
            entity.position = (boom.x, boom.y, boom.z)
            entity.scale = grow
            entity.color = color.rgba32(255, int(160 - boom.age * 80), 40, int(220 * (1 - boom.age)))
        for entity in self._booms[len(booms):]:
            entity.enabled = False
