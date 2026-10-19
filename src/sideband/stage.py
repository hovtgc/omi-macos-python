"""One Ursina window for the arcade, launched from the Tk hub.

Ursina's `application.quit` calls `sys.exit()`, which would take Sideband with it.
Games leave by setting `session.done`. This module pumps the Tk root every frame
so pendant taps and gamepad edges still arrive, then returns to the hub.

Meshes are Ursina's procedural primitives (MIT, pokepetter/ursina). Textures are
generated here with Pillow. Nothing is downloaded at runtime.
"""

from __future__ import annotations

import importlib.util
from typing import Any

_app: Any = None
_session: Any = None
_textures: dict[str, Any] = {}


def available() -> bool:
    """True when Ursina can be imported. Does not open a window."""
    return importlib.util.find_spec("ursina") is not None


class Focus:
    """Stand-in for a Tk toplevel. The hub calls `top.lift()` to bring a game forward."""

    def lift(self) -> None:
        if _app is not None and _session is not None:
            _show(_session.title)


class Session:
    """A game inside the shared window. Subclasses build the scene and step it."""

    key = ""
    title = "Sideband"

    def __init__(self, hub: Any, on_close: Any) -> None:
        self.hub = hub
        self.on_close = on_close
        self.top = Focus()
        self.state = "ready"
        self.done = False
        self.recorded = False
        self.over_at = 0.0
        self.owned: list[Any] = []
        self._held: set[str] = set()
        self._returned = False

    @property
    def playing(self) -> bool:
        return self.state == "playing"

    def close(self) -> None:
        self.done = True

    def own(self, entity: Any) -> Any:
        self.owned.append(entity)
        return entity

    def light_owned(self) -> None:
        """Panda's auto shader lights and shadows the world. Ursina's shadow shader crashes some GL drivers."""
        for entity in self.owned:
            shade_tree(entity)

    def teardown(self) -> None:
        from ursina import destroy

        for entity in self.owned:
            try:
                if entity:
                    destroy(entity)
            except Exception:
                pass
        self.owned.clear()
        try:
            from ursina import application

            application.base.render.clearLight()
        except Exception:
            pass

    def fresh(self) -> set[str]:
        from ursina import held_keys

        now = {name for name, down in held_keys.items() if down}
        pressed = now - self._held
        self._held = now
        return pressed

    def build(self) -> None:
        raise NotImplementedError

    def frame(self, dt: float) -> None:
        raise NotImplementedError

    def finish(self) -> None:
        """Tell the hub the window is gone. Once."""
        if self._returned:
            return
        self._returned = True
        self.on_close()


def ensure() -> Any:
    """Open the Panda window, once per process. Raises if the display will not come up."""
    global _app
    if _app is not None:
        return _app
    from ursina import Ursina
    import ursina.application as ursina_app

    _app = Ursina(
        title="Sideband",
        size=(1280, 720),
        fullscreen=False,
        borderless=False,
        vsync=False,
        development_mode=False,
        editor_ui_enabled=False,
        show_ursina_splash=False,
    )
    # Clicking the window's close box, or anything that calls Ursina's quit, must
    # come back to the hub. The real quit ends the process.
    _app.finalizeExit = lambda: None

    def _quit() -> None:
        if _session is not None:
            _session.close()

    ursina_app.quit = _quit
    try:
        _app.win.setCloseRequestEvent("sideband-close-window")
        _app.accept("sideband-close-window", _quit)
    except Exception:
        pass
    _hide()
    return _app


def play(hub: Any, session: Session) -> None:
    """Block on the 3D window until the session leaves, then hand control back."""
    global _session
    _session = session
    try:
        app = ensure()
    except Exception as exc:
        hub.log(f"{session.title}: 3D window failed ({exc})")
        session.finish()
        _session = None
        return
    _show(session.title)
    arcade = getattr(hub, "arcade", None)
    if arcade is not None:
        try:
            arcade.top.withdraw()
        except Exception:
            pass
    try:
        session.build()
        while not session.done:
            app.step()
            import time

            dt = float(getattr(time, "dt", 1 / 60) or 1 / 60)
            _pump(hub, session)
            if session.done:
                break
            session.frame(max(0.0, min(0.05, dt)))
    except Exception as exc:
        hub.log(f"{session.title}: {exc}")
        session.done = True
    finally:
        _unlock()
        try:
            session.teardown()
        except Exception:
            pass
        _hide()
        _session = None
        session.finish()


def stick() -> tuple[float, float]:
    """Arrow keys and WASD as (x right, y up), each axis in -1..1."""
    from ursina import held_keys

    x = float(bool(held_keys["d"] or held_keys["right arrow"])) - float(bool(held_keys["a"] or held_keys["left arrow"]))
    y = float(bool(held_keys["w"] or held_keys["up arrow"])) - float(bool(held_keys["s"] or held_keys["down arrow"]))
    return x, y


def lock(on: bool) -> None:
    from ursina import mouse

    mouse.locked = bool(on)


def _unlock() -> None:
    try:
        lock(False)
    except Exception:
        pass


def toggle_fullscreen() -> None:
    from ursina import window

    window.fullscreen = not window.fullscreen


def paint(name: str, image: Any) -> Any:
    """Cache a generated Pillow image as an Ursina texture."""
    cached = _textures.get(name)
    if cached is None:
        from ursina import Texture

        cached = Texture(image)
        _textures[name] = cached
    return cached


def sand_image():
    import math
    import random
    from PIL import Image

    rng = random.Random(91)
    image = Image.new("RGB", (256, 256))
    pixels = image.load()
    for y in range(256):
        for x in range(256):
            grain = rng.randint(-16, 16)
            dune = int(14 * math.sin(x / 31.0) * math.cos(y / 23.0))
            pixels[x, y] = (
                max(0, min(255, 198 + grain + dune)),
                max(0, min(255, 154 + grain // 2 + dune // 2)),
                max(0, min(255, 92 + grain // 3)),
            )
    return image


def sky_image(stops: list[tuple[float, tuple[int, int, int]]]):
    from PIL import Image

    image = Image.new("RGB", (8, 128))
    pixels = image.load()
    for y in range(128):
        t = y / 127
        colour = stops[-1][1]
        for i in range(len(stops) - 1):
            t0, c0 = stops[i]
            t1, c1 = stops[i + 1]
            if t0 <= t <= t1 and t1 > t0:
                mix = (t - t0) / (t1 - t0)
                colour = tuple(int(a + (b - a) * mix) for a, b in zip(c0, c1))
                break
        for x in range(8):
            pixels[x, y] = colour
    return image


def shade_tree(entity: Any) -> None:
    """Swap in Panda's lit shader, which casts the sun's shadow map without sampling an empty one."""
    model = getattr(entity, "model", None)
    if model is not None and not getattr(entity, "_unlit", False):
        try:
            from ursina import camera

            if not entity.has_ancestor(camera.ui):
                entity.setShaderAuto()
        except Exception:
            pass
    for child in list(getattr(entity, "children", ())):
        shade_tree(child)


def sun(warm: tuple[int, int, int] = (255, 206, 150), ambient: tuple[int, int, int] = (78, 64, 52), shadows: bool = True, rotation: tuple[float, float, float] = (32, -48, 0)) -> tuple[Any, Any]:
    from ursina import AmbientLight, DirectionalLight, color

    light = DirectionalLight(shadows=False, color=color.rgba32(*warm, 255))
    light.rotation = rotation
    if shadows:
        try:
            light._light.set_shadow_caster(True, 1024, 1024)
            light.update_bounds()
        except Exception:
            pass
    fill = AmbientLight(color=color.rgba32(*ambient, 255))
    return light, fill


def haze(rgb: tuple[int, int, int], start: float, end: float, alpha: int = 210) -> None:
    from ursina import color, scene
    from ursina.shaders import lit_with_shadows_shader as lit

    fog = color.rgba32(*rgb, alpha)
    lit.default_input["fog_color"] = fog
    lit.default_input["fog_start"] = start
    lit.default_input["fog_end"] = end
    scene.fog_color = fog
    scene.fog_density = (start, end)


def glow(parent: Any, position: tuple[float, float, float], rgb: tuple[int, int, int], attenuation: tuple[float, float, float] = (1, 0.35, 0.12)) -> Any:
    from ursina import PointLight, color

    light = PointLight(parent=parent, position=position, color=color.rgba32(*rgb, 255))
    try:
        light._light.setAttenuation(attenuation)
    except Exception:
        pass
    return light


def label(text: str, position: tuple[float, float], scale: float = 1.0) -> Any:
    from ursina import Text, camera, color

    return Text(
        parent=camera.ui,
        text=text,
        position=position,
        origin=(-0.5, 0.5),
        scale=scale,
        color=color.rgba32(245, 240, 230, 255),
    )


def _show(title: str) -> None:
    from panda3d.core import WindowProperties
    from ursina import application

    props = WindowProperties()
    props.setMinimized(False)
    props.setTitle(title)
    props.setForeground(True)
    props.setSize(1280, 720)
    application.base.win.requestProperties(props)


def _hide() -> None:
    try:
        from panda3d.core import WindowProperties
        from ursina import application

        props = WindowProperties()
        props.setMinimized(True)
        application.base.win.requestProperties(props)
    except Exception:
        pass


def _pump(hub: Any, session: Session) -> None:
    root = getattr(hub, "root", None)
    if root is None or getattr(hub, "_pumping", False):
        return
    hub._pumping = True
    try:
        root.update()
    except Exception:
        session.done = True
    finally:
        hub._pumping = False
