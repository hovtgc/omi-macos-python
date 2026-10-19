"""Desert 91 in Ursina. The fight stays in `desert.py`; this file is the scene.

Outside Kuwait, 1991: sand, a low sun, haze, burning wells, berms, bunkers, soldiers
and two vehicles. A downed figure is a dust puff. No gore, no real people.

Geometry is Ursina's procedural cube, plane, sphere and cylinder (MIT). Sand and sky
textures are generated with Pillow when the window opens. Nothing is fetched.
"""

from __future__ import annotations

import math
import random
from typing import Any

from sideband.desert import MISSIONS, Orders, Raid
from sideband.sfx import blip
from sideband.stage import Session, glow, haze, label, lock, paint, sand_image, sky_image, stick, sun, toggle_fullscreen

CELL = 4.0
EYE = 1.68
YAW = 2.9  # radians per mouse unit; about the same as the flat view's pixels
PITCH = 220.0


def _yaw(angle: float) -> float:
    """Sim angle 0 faces +X. Ursina yaw 90 does the same."""
    return 90.0 - math.degrees(angle)


class DesertSession(Session):
    key = "desert"
    title = "Desert 91 — Sideband"

    def __init__(self, hub: Any, on_close: Any) -> None:
        super().__init__(hub, on_close)
        self.raid = Raid()
        self.pitch = 4.0
        self.look = True
        self.fire_pulse = False
        self.firing = False
        self.reload_pulse = False
        self.weapon_pick: str | None = None
        self.kick = 0.0
        self.mark = 0.0
        self._skip_look = 0
        self._bodies: dict[int, Any] = {}
        self._prev: dict[int, tuple[float, float]] = {}
        self._flames: list[Any] = []
        self._rifle: Any = None
        self._flash: Any = None
        self._texts: dict[str, Any] = {}
        self._marks: list[Any] = []
        self._vignette: Any = None
        self._rebuild = False

    def on_tap(self, kind: str) -> None:
        forward = kind == "single"
        if self.state == "playing":
            if forward:
                self.fire_pulse = True
            else:
                self.reload_pulse = True
            return
        if not forward:
            self.close()
            return
        if self.state in ("over", "won"):
            import time

            if time.monotonic() - self.over_at < 0.6:
                return
            self._restart()
        self.state = "playing"
        self._skip_look = 2
        if self.look:
            lock(True)

    def on_hold(self) -> None:
        if self.state == "playing":
            self.state = "paused"
            lock(False)

    def on_shake(self) -> None:
        if self.state == "playing":
            self.reload_pulse = True

    def _restart(self) -> None:
        self.raid = Raid()
        self.recorded = False
        self.pitch = 4.0
        self.kick = 0.0
        self._rebuild = True
        self.state = "ready"

    def build(self) -> None:
        from ursina import Entity, camera, color, window
        from ursina.models.procedural.cylinder import Cylinder
        from ursina.prefabs.sky import Sky
        from ursina.shaders import lit_with_shadows_shader as lit
        from ursina.shaders import unlit_shader

        window.color = color.rgba32(48, 28, 18, 255)
        camera.fov = 76
        camera.clip_plane_near = 0.06
        camera.clip_plane_far = 240
        sand = paint("sand", sand_image())
        sky = paint("desert-sky", sky_image([
            (0.0, (92, 132, 168)),
            (0.35, (214, 126, 64)),
            (0.62, (232, 156, 78)),
            (1.0, (196, 112, 58)),
        ]))
        haze((214, 132, 72), 18, 95, 200)
        self.own(Sky(texture=sky, color=color.white, unlit=True))
        self.own(Entity(model="sphere", color=color.rgba32(255, 214, 140, 255), position=(70, 28, 18), scale=7, shader=unlit_shader, unlit=True))
        ground = self.own(Entity(
            model="plane", texture=sand, texture_scale=(18, 14), shader=lit,
            position=(8 * CELL, 0, 6 * CELL), scale=(96, 1, 72),
            color=color.rgba32(210, 168, 110, 255),
        ))
        self._dunes(lit, sand)
        self._blocks(lit, Cylinder)
        self._actors(lit, Cylinder)
        self._pickups(lit)
        light, fill = sun(shadows=True, rotation=(28, -42, 0))
        self.own(light)
        self.own(fill)
        haze((214, 132, 72), 18, 95, 200)
        self._viewmodel(lit, unlit_shader)
        self._hud()
        self.light_owned()
        self._place_camera()
        del ground

    def _dunes(self, lit: Any, sand: Any) -> None:
        from ursina import Entity, color

        rng = random.Random(19)
        for i in range(9):
            self.own(Entity(
                model="sphere", shader=lit, texture=sand,
                position=(rng.uniform(-8, 78), -1.2, rng.uniform(-10, 62)),
                scale=(rng.uniform(10, 22), rng.uniform(1.4, 3.2), rng.uniform(8, 16)),
                color=color.rgba32(196, 150, 90, 255),
            ))

    def _blocks(self, lit: Any, cylinder: Any) -> None:
        from ursina import Entity, color

        rng = random.Random(7)
        sand = color.rgba32(186, 148, 92, 255)
        bag = color.rgba32(168, 132, 78, 255)
        concrete = color.rgba32(122, 112, 98, 255)
        for iy, row in enumerate(self.raid.grid):
            for ix, cell in enumerate(row):
                x, z = (ix + 0.5) * CELL, (iy + 0.5) * CELL
                if cell == "#":
                    self.own(Entity(model="cube", shader=lit, position=(x, 0.38, z), scale=(3.7, 0.76, 3.7), color=sand))
                    for k in range(3):
                        self.own(Entity(
                            model="cube", shader=lit, color=bag,
                            position=(x - 1.15 + k * 1.15, 0.95, z + rng.uniform(-0.2, 0.2)),
                            scale=(1.2, 0.36, 0.62), rotation=(0, rng.uniform(-8, 8), 0),
                        ))
                elif cell == "B":
                    self.own(Entity(model="cube", shader=lit, position=(x, 1.7, z), scale=(3.8, 3.4, 3.8), color=concrete))
                    self.own(Entity(model="cube", shader=lit, position=(x, 2.5, z - 1.7), scale=(1.6, 0.28, 0.2), color=color.rgba32(24, 22, 20, 255)))
                elif cell == "F":
                    self._well(x, z, lit, cylinder)
        # A burnt-out truck, scenery only. It is not a person and it does not shoot.
        self.own(Entity(model="cube", shader=lit, position=(7.2 * CELL, 0.7, 6.4 * CELL), scale=(2.2, 1.3, 5.4), rotation=(0, 18, 8), color=color.rgba32(58, 52, 46, 255)))
        self.own(Entity(model="cube", shader=lit, position=(7.0 * CELL, 1.5, 5.6 * CELL), scale=(2.0, 1.1, 1.8), rotation=(0, 18, 0), color=color.rgba32(72, 64, 54, 255)))

    def _well(self, x: float, z: float, lit: Any, cylinder: Any) -> None:
        from ursina import Entity, color
        from ursina.shaders import unlit_shader

        metal = color.rgba32(70, 64, 58, 255)
        for ox, oz in ((-0.7, -0.7), (0.7, -0.7), (-0.7, 0.7), (0.7, 0.7)):
            self.own(Entity(model="cube", shader=lit, position=(x + ox, 2.2, z + oz), scale=(0.18, 4.4, 0.18), color=metal))
        self.own(Entity(model="cube", shader=lit, position=(x, 4.3, z), scale=(2.4, 0.18, 2.4), color=metal))
        self.own(Entity(model=cylinder(resolution=8, radius=0.28, height=3.2), shader=lit, position=(x, 1.6, z), color=color.rgba32(40, 36, 32, 255)))
        self.own(glow(None, (x, 2.4, z), (255, 120, 40), (1, 0.22, 0.08)))
        bits: list[Any] = []
        for i in range(14):
            bit = self.own(Entity(model="sphere", shader=unlit_shader, unlit=True, position=(x, 1.2, z), scale=0.3, color=color.rgba32(255, 140, 40, 220)))
            bit._age = i / 14
            bits.append(bit)
        smoke: list[Any] = []
        for i in range(12):
            puff = self.own(Entity(model="sphere", shader=unlit_shader, unlit=True, position=(x, 4, z), scale=0.8, color=color.rgba32(48, 46, 44, 150)))
            puff._age = i / 12
            smoke.append(puff)
        self._flames.append((x, z, bits, smoke))

    def _actors(self, lit: Any, cylinder: Any) -> None:
        for actor in self.raid.actors:
            if actor.kind == "soldier":
                body = self._soldier(lit)
            elif actor.kind == "jeep":
                body = self._jeep(lit, cylinder)
            else:
                body = self._truck(lit, cylinder)
            self._bodies[id(actor)] = body
            self._prev[id(actor)] = (actor.x, actor.y)

    def _soldier(self, lit: Any) -> Any:
        from ursina import Entity, color

        olive = color.rgba32(92, 96, 62, 255)
        root = self.own(Entity())
        torso = Entity(parent=root, model="cube", shader=lit, color=olive, scale=(0.46, 0.58, 0.28), y=1.18)
        Entity(parent=root, model="sphere", shader=lit, color=color.rgba32(186, 142, 102, 255), scale=0.22, y=1.58)
        Entity(parent=root, model="sphere", shader=lit, color=color.rgba32(72, 78, 52, 255), scale=(0.26, 0.14, 0.26), y=1.68)
        left = Entity(parent=root, model="cube", shader=lit, color=olive, scale=(0.14, 0.62, 0.14), position=(-0.12, 0.48, 0.02))
        right = Entity(parent=root, model="cube", shader=lit, color=olive, scale=(0.14, 0.62, 0.14), position=(0.12, 0.48, -0.02))
        Entity(parent=root, model="cube", shader=lit, color=color.rgba32(28, 26, 24, 255), scale=(0.08, 0.08, 0.72), position=(0.22, 1.12, 0.28))
        root._torso = torso
        root._legs = (left, right)
        root._olive = olive
        return root

    def _jeep(self, lit: Any, cylinder: Any) -> Any:
        from ursina import Entity, color

        root = self.own(Entity())
        Entity(parent=root, model="cube", shader=lit, color=color.rgba32(78, 86, 52, 255), scale=(1.7, 0.7, 3.4), y=0.85)
        Entity(parent=root, model="cube", shader=lit, color=color.rgba32(64, 70, 44, 255), scale=(1.55, 0.7, 1.4), position=(0, 1.4, -0.4))
        for ox, oz in ((-0.75, -1.1), (0.75, -1.1), (-0.75, 1.1), (0.75, 1.1)):
            Entity(parent=root, model=cylinder(resolution=8, radius=0.32, height=0.28), shader=lit, position=(ox, 0.34, oz), rotation=(0, 0, 90), color=color.rgba32(28, 26, 24, 255))
        root._legs = ()
        return root

    def _truck(self, lit: Any, cylinder: Any) -> Any:
        from ursina import Entity, color

        root = self.own(Entity())
        Entity(parent=root, model="cube", shader=lit, color=color.rgba32(88, 78, 60, 255), scale=(2.1, 1.5, 4.6), position=(0, 1.3, 0.4))
        Entity(parent=root, model="cube", shader=lit, color=color.rgba32(70, 74, 58, 255), scale=(2.0, 1.5, 1.6), position=(0, 1.6, -1.8))
        for oz in (-1.6, 1.5):
            for ox in (-0.9, 0.9):
                Entity(parent=root, model=cylinder(resolution=8, radius=0.4, height=0.3), shader=lit, position=(ox, 0.4, oz), rotation=(0, 0, 90), color=color.rgba32(24, 22, 20, 255))
        root._legs = ()
        return root

    def _pickups(self, lit: Any) -> None:
        from ursina import Entity, color

        self._crates: dict[int, Any] = {}
        for item in self.raid.pickups:
            tint = (86, 150, 78) if item.kind == "health" else (196, 160, 64)
            crate = self.own(Entity(
                model="cube", shader=lit, color=color.rgba32(*tint, 255),
                position=(item.x * CELL, 0.35, item.y * CELL), scale=(0.55, 0.45, 0.55),
            ))
            self._crates[id(item)] = crate

    def _viewmodel(self, lit: Any, unlit: Any) -> None:
        from ursina import Entity, camera, color

        rifle = self.own(Entity(parent=camera, position=(0.32, -0.36, 1.15), scale=0.55, rotation=(2, 8, 0)))
        Entity(parent=rifle, model="cube", shader=lit, color=color.rgba32(62, 58, 48, 255), scale=(0.08, 0.1, 0.55), position=(0, 0, 0.15))
        Entity(parent=rifle, model="cube", shader=lit, color=color.rgba32(48, 52, 40, 255), scale=(0.09, 0.14, 0.28), position=(0, -0.02, -0.12))
        Entity(parent=rifle, model="cube", shader=lit, color=color.rgba32(36, 34, 30, 255), scale=(0.07, 0.16, 0.08), position=(0, -0.12, 0.05))
        flash = Entity(parent=rifle, model="sphere", shader=unlit, unlit=True, color=color.rgba32(255, 220, 140, 255), position=(0, 0.02, 0.48), scale=0.08, enabled=False)
        self._rifle = rifle
        self._flash = flash

    def _hud(self) -> None:
        from ursina import Entity, camera, color

        self.own(Entity(parent=camera.ui, model="quad", color=color.rgba32(16, 10, 8, 150), scale=(1.9, 0.16), position=(0, 0.44), z=1))
        self._texts["health"] = self.own(label("HEALTH  100", (-0.86, 0.47), 1.7))
        self._texts["ammo"] = self.own(label("RIFLE  30 / 60", (-0.86, 0.40), 1.45))
        self._texts["mission"] = self.own(label("1/3  BERM PATROL", (-0.22, 0.47), 1.55))
        self._texts["score"] = self.own(label("0", (0.42, 0.47), 1.55))
        self._texts["center"] = self.own(label("", (-0.46, 0.08), 2.2))
        self._texts["sub"] = self.own(label("", (-0.5, -0.02), 1.3))
        self.own(Entity(parent=camera.ui, model="quad", color=color.rgba32(255, 248, 236, 220), scale=(0.003, 0.018), position=(0, 0)))
        self.own(Entity(parent=camera.ui, model="quad", color=color.rgba32(255, 248, 236, 220), scale=(0.018, 0.003), position=(0, 0)))
        self._marks = []
        for px, py, sx, sy in ((0.02, 0.02, 0.012, 0.003), (-0.02, 0.02, 0.012, 0.003), (0.02, -0.02, 0.012, 0.003), (-0.02, -0.02, 0.012, 0.003)):
            mark = self.own(Entity(parent=camera.ui, model="quad", color=color.rgba32(255, 196, 96, 0), scale=(sx, sy), position=(px, py), rotation=(0, 0, 45)))
            self._marks.append(mark)
        self._vignette = self.own(Entity(parent=camera.ui, model="quad", color=color.rgba32(120, 24, 16, 0), scale=(2.2, 1.2), z=1))

    def frame(self, dt: float) -> None:
        if self._rebuild:
            self._rebuild = False
            self.teardown()
            self._bodies.clear()
            self._flames = []
            self._texts.clear()
            self._marks = []
            self.build()
            del flames
        self._keys(dt)
        self._fires(dt)
        if self.state == "playing" and self.look:
            lock(True)
        if self.state == "playing":
            before = self.raid.score
            mag = self.raid.gun.mag
            self.raid.step(dt, self._orders(dt))
            if self.raid.score > before:
                self.mark = 0.18
                self.kick = min(1.0, self.kick + 0.45)
                blip("hit", 520, 40, 0.2)
            elif self.raid.gun.mag < mag:
                self.kick = min(1.0, self.kick + 0.7)
                blip("shot", 180, 35, 0.24, noise=0.55)
            if self.raid.over and not self.recorded:
                import time

                self.recorded = True
                self.over_at = time.monotonic()
                self.state = "won" if self.raid.won else "over"
                lock(False)
                self.hub.record_score("desert", float(self.raid.score))
        self.kick = max(0.0, self.kick - dt * 6)
        self.mark = max(0.0, self.mark - dt)
        self._sync()
        self._place_camera()
        self._draw_hud()

    def _keys(self, dt: float) -> None:
        del dt
        pressed = self.fresh()
        if pressed & {"w", "a", "s", "d", "left arrow", "right arrow", "up arrow", "down arrow", "space", "left mouse", "r", "escape"}:
            self.hub.note_device("keys")
        if "f11" in pressed:
            toggle_fullscreen()
        if "escape" in pressed:
            if self.state == "playing":
                self.on_hold()
            else:
                self.close()
            return
        if "r" in pressed:
            self.reload_pulse = True
        if "1" in pressed:
            self.weapon_pick = "rifle"
        if "2" in pressed:
            self.weapon_pick = "pistol"
        if self.state != "playing":
            self.firing = False
            if pressed & {"enter", "space", "left mouse"}:
                self.on_tap("single")
            return
        self.firing = bool(self._held & {"left mouse", "space", "enter"})

    def _orders(self, dt: float) -> Orders:
        forward, strafe = stick()[1], stick()[0]
        turn = 0.0
        if self.look and self._skip_look <= 0:
            from ursina import mouse

            if mouse.locked:
                turn -= mouse.velocity[0] * YAW
                self.pitch = max(-32.0, min(36.0, self.pitch - mouse.velocity[1] * PITCH))
                if abs(mouse.velocity[0]) + abs(mouse.velocity[1]) > 0.001:
                    self.hub.note_device("keys")
        else:
            self._skip_look = max(0, self._skip_look - 1)
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

    def _fires(self, dt: float) -> None:
        for x, z, bits, smoke in self._flames:
            for bit in bits:
                bit._age = (bit._age + dt * 1.6) % 1.0
                t = bit._age
                bit.position = (x + math.sin(t * 11) * 0.18, 1.1 + t * 2.4, z + math.cos(t * 9) * 0.18)
                bit.scale = 0.16 + t * 0.45
            for puff in smoke:
                puff._age = (puff._age + dt * 0.18) % 1.0
                t = puff._age
                puff.position = (x + math.sin(t * 4) * 0.8, 3.2 + t * 16, z + math.cos(t * 3) * 0.6)
                puff.scale = 0.7 + t * 5.5

    def _sync(self) -> None:
        from ursina import color

        raid = self.raid
        for actor in raid.actors:
            body = self._bodies.get(id(actor))
            if body is None:
                continue
            body.enabled = actor.alive and actor.wave <= raid.wave
            if not body.enabled:
                continue
            prev = self._prev.get(id(actor), (actor.x, actor.y))
            moved = math.hypot(actor.x - prev[0], actor.y - prev[1]) > 0.001
            self._prev[id(actor)] = (actor.x, actor.y)
            body.position = (actor.x * CELL, 0, actor.y * CELL)
            body.look_at((raid.x * CELL, 1.0, raid.y * CELL))
            body.rotation_x = 0
            body.rotation_z = 0
            if actor.kind == "soldier":
                swing = math.sin(raid.time * 9) * (28 if moved else 0)
                legs = getattr(body, "_legs", ())
                if len(legs) == 2:
                    legs[0].rotation_x = swing
                    legs[1].rotation_x = -swing
                if actor.hurt > 0 and getattr(body, "_torso", None) is not None:
                    body._torso.color = color.rgba32(170, 70, 48, 255)
                elif getattr(body, "_torso", None) is not None:
                    body._torso.color = body._olive
            else:
                body.y = 0.05 + math.sin(raid.time * 7 + actor.x) * 0.04
        for item in raid.pickups:
            crate = self._crates.get(id(item))
            if crate is not None:
                crate.enabled = not item.taken
                crate.rotation_y = raid.time * 40
        if self._flash is not None:
            self._flash.enabled = self.kick > 0.35
        if self._rifle is not None:
            self._rifle.rotation_x = -self.kick * 10
            self._rifle.z = 1.15 - self.kick * 0.08

    def _place_camera(self) -> None:
        from ursina import camera

        raid = self.raid
        shake = self.kick * 0.015
        camera.position = (raid.x * CELL, EYE - self.kick * 0.03, raid.y * CELL + shake)
        camera.rotation = (-self.pitch - self.kick * 3.5, _yaw(raid.angle), math.sin(raid.time * 1.5) * 0.15)

    def _draw_hud(self) -> None:
        from ursina import color

        raid = self.raid
        gun = raid.gun
        self._texts["health"].text = f"HEALTH  {raid.health}"
        self._texts["ammo"].text = f"{gun.name}  {gun.mag} / {gun.reserve}" + ("  RELOADING" if raid.reload_t > 0 else "")
        left = len(raid.live())
        self._texts["mission"].text = f"{raid.wave}/3  {raid.mission.upper()}  ·  {left} LEFT"
        best = self.hub.best("desert")
        best_bit = f"   BEST {best:g}" if best else ""
        self._texts["score"].text = f"{raid.score}{best_bit}"
        title, sub = "", ""
        if self.state == "ready":
            title, sub = "DESERT 91", "Outside Kuwait, 1991. Click to take the rifle. Esc returns."
        elif self.state == "paused":
            title, sub = "PAUSED", "Enter resumes. Esc returns to the shelf."
        elif self.state == "won":
            title, sub = "WELLS ARE BEHIND YOU", f"Score {raid.score}. Enter runs it again."
        elif self.state == "over":
            title, sub = "LEFT ON THE SAND", f"Score {raid.score}. Enter tries again."
        elif raid.banner_t > 0:
            nxt = MISSIONS.get(raid.wave + 1, "Clear")
            title, sub = "SECTOR CLEAR", nxt
        self._texts["center"].text = title
        self._texts["sub"].text = sub
        shown = 255 if self.mark > 0 else 0
        for mark in self._marks:
            mark.color = color.rgba32(255, 196, 96, shown)
        if self._vignette is not None:
            alpha = 140 if raid.hit_flash > 0 else 0
            self._vignette.color = color.rgba32(140, 28, 18, alpha)
