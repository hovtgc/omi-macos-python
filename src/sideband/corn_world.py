"""Corn Maze in Ursina. The marble and the walls stay in `minigames.MarbleMaze`.

Dusk hedges, a glowing pumpkin at the barn, a chase camera over the marble.
A tap still brakes. Reaching the flag records the level time, shorter is better.
"""

from __future__ import annotations

import math
import random
import time
from typing import Any

from sideband.minigames import WALL_E, WALL_N, WALL_S, WALL_W, MarbleMaze, Stick
from sideband.stage import Session, glow, haze, label, paint, sand_image, sky_image, stick, sun, toggle_fullscreen

CELL = 2.35


class CornSession(Session):
    key = "corn"
    title = "Corn Maze — Sideband"

    def __init__(self, hub: Any, on_close: Any) -> None:
        super().__init__(hub, on_close)
        self.rng = random.Random(11)
        self.game = MarbleMaze(seed=self.rng.randrange(1 << 30))
        self.taps = 0
        self.shake = False
        self._level = -1
        self._walls: Any = None
        self._marble: Any = None
        self._pumpkin: Any = None
        self._texts: dict[str, Any] = {}
        self._yaw = 0.0

    def on_tap(self, kind: str) -> None:
        forward = kind == "single"
        if self.state == "playing":
            if self.game.won:
                if forward:
                    self.game.next_level()
                else:
                    self.close()
                return
            self.taps += 1 if forward else 2
            return
        if not forward:
            self.close()
            return
        if self.state == "over":
            if time.monotonic() - self.over_at < 0.8:
                return
            self.game = MarbleMaze(seed=self.rng.randrange(1 << 30))
            self.recorded = False
            self._level = -1
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

        window.color = color.rgba32(70, 36, 48, 255)
        camera.fov = 68
        camera.clip_plane_far = 80
        dusk = paint("dusk", sky_image([
            (0.0, (48, 28, 64)),
            (0.4, (196, 92, 48)),
            (0.7, (232, 140, 64)),
            (1.0, (120, 64, 48)),
        ]))
        haze((180, 100, 60), 10, 42, 150)
        self.own(Sky(texture=dusk, color=color.white, unlit=True))
        sand = paint("sand", sand_image())
        span = 40
        self.own(Entity(model="plane", texture=sand, texture_scale=(8, 8), shader=lit, scale=(span, 1, span), position=(span / 4, 0, span / 4), color=color.rgba32(150, 110, 60, 255)))
        light, fill = sun(warm=(255, 186, 130), ambient=(150, 110, 80), shadows=True, rotation=(36, -20, 0))
        self.own(light)
        self.own(fill)
        haze((180, 100, 60), 10, 42, 150)
        self._marble = self.own(Entity(model="sphere", shader=lit, color=color.rgba32(232, 214, 180, 255), scale=0.55))
        self.light_owned()
        self._texts["hud"] = self.own(label("CORN MAZE", (-0.86, 0.46), 1.7))
        self._texts["center"] = self.own(label("", (-0.42, 0.05), 2.0))
        self._rebuild()

    def _rebuild(self) -> None:
        from ursina import Entity, color, destroy
        from ursina.shaders import lit_with_shadows_shader as lit

        if self._walls is not None:
            destroy(self._walls)
            self.owned = [e for e in self.owned if e is not self._walls]
        maze = self.game
        root = self.own(Entity())
        self._walls = root
        hedge = color.rgba32(118, 150, 62, 255)
        stalk = color.rgba32(214, 176, 64, 255)
        h = 2.15
        for y in range(maze.rows):
            for x in range(maze.cols):
                flags = maze.walls[y][x]
                cx, cz = (x + 0.5) * CELL, (y + 0.5) * CELL
                if flags & WALL_N:
                    Entity(parent=root, model="cube", shader=lit, color=hedge, position=(cx, h / 2, y * CELL), scale=(CELL, h, 0.22))
                if flags & WALL_W:
                    Entity(parent=root, model="cube", shader=lit, color=hedge, position=(x * CELL, h / 2, cz), scale=(0.22, h, CELL))
                if y == maze.rows - 1 and flags & WALL_S:
                    Entity(parent=root, model="cube", shader=lit, color=hedge, position=(cx, h / 2, (y + 1) * CELL), scale=(CELL, h, 0.22))
                if x == maze.cols - 1 and flags & WALL_E:
                    Entity(parent=root, model="cube", shader=lit, color=hedge, position=((x + 1) * CELL, h / 2, cz), scale=(0.22, h, CELL))
                Entity(parent=root, model="cube", shader=lit, color=stalk, position=(cx, h + 0.35, cz), scale=(0.08, 0.8, 0.08))
        gx, gy = maze.goal
        px, pz = (gx + 0.5) * CELL, (gy + 0.5) * CELL
        self._pumpkin = Entity(parent=root, model="sphere", shader=lit, color=color.rgba32(214, 92, 24, 255), position=(px, 0.55, pz), scale=(0.9, 0.7, 0.9))
        Entity(parent=root, model="cube", shader=lit, color=color.rgba32(40, 110, 36, 255), position=(px, 1.05, pz), scale=(0.12, 0.35, 0.12))
        glow(root, (px, 1.4, pz), (255, 140, 60), (1, 0.6, 0.2))
        from sideband.stage import shade_tree

        shade_tree(root)
        self._level = maze.level

    def frame(self, dt: float) -> None:
        from ursina import camera

        self._keys()
        g = self.game
        if self._level != g.level:
            self._rebuild()
        if self.state == "playing":
            g.step(dt, Stick(*self._axes(), self.taps, self.shake))
            if g.won and not self.recorded:
                self.recorded = True
                self.hub.record_score("corn", g.elapsed, lower_is_better=True)
            elif not g.won:
                self.recorded = False
        self.taps, self.shake = 0, False
        mx, mz = g.x * CELL, g.y * CELL
        if self._marble is not None:
            self._marble.position = (mx, 0.32, mz)
            self._marble.rotation_z += g.vx * 40 * dt
            self._marble.rotation_x += g.vy * 40 * dt
        speed = math.hypot(g.vx, g.vy)
        if speed > 0.4:
            self._yaw = math.atan2(g.vx, g.vy)
        back = 8.0
        camera.position = (mx - math.sin(self._yaw) * back, 9.0, mz - math.cos(self._yaw) * back)
        camera.look_at((mx + math.sin(self._yaw) * 2.0, 0.3, mz + math.cos(self._yaw) * 2.0))
        best = self.hub.best("corn")
        tail = f"   best {best:.1f}s" if best else ""
        self._texts["hud"].text = f"LEVEL {g.level}   {g.elapsed:0.1f}s{tail}"
        center = ""
        if self.state == "ready":
            center = "CLICK TO ROLL"
        elif self.state == "paused":
            center = "PAUSED"
        elif g.won:
            center = "HOME TO THE BARN"
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
        if "c" in pressed:
            self.hub.recentre()

    def _axes(self) -> tuple[float, float]:
        x, y = stick()
        if x == 0.0 and y == 0.0:
            axes = self.hub.play_axes()
            if axes is not None:
                return max(-1.0, min(1.0, axes[0])), max(-1.0, min(1.0, axes[1]))
        return x, y
