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
        from sideband.keys import BOARD, ursina_names

        try:
            from ursina import held_keys

            ursina_down = {name for name, down in held_keys.items() if down}
        except Exception:
            ursina_down = set()
        now = ursina_down | ursina_names(set(BOARD.held))
        pressed = (now - self._held) | ursina_names(set(BOARD.pressed))
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
    from sideband import keys

    keys.activate()
    _show(session.title)
    debug_label = None
    arcade = getattr(hub, "arcade", None)
    if arcade is not None:
        try:
            arcade.top.withdraw()
        except Exception:
            pass
    try:
        session.build()
        try:
            app.step()  # apply the title and size before asking macOS for the key window
        except Exception:
            pass
        keys.activate()
        debug_label = _debug_label()
        if debug_label is not None:
            session.own(debug_label)
        while not session.done:
            app.step()
            from ursina import time as ursina_time

            dt = float(getattr(ursina_time, "dt", 0) or 1 / 60)
            _pump(hub, session)
            if session.done:
                break
            keys.BOARD.poll()
            if debug_label is not None:
                debug_label.text = keys.BOARD.overlay()
                debug_label.enabled = keys.BOARD.debug
            session.frame(max(0.0, min(0.05, dt)))
            keys.BOARD.end_frame()
    except Exception as exc:
        hub.log(f"{session.title}: {exc}")
        session.done = True
    finally:
        _unlock()
        keys.BOARD.release_pointer()
        _clear_grade()
        try:
            session.teardown()
        except Exception:
            pass
        _hide()
        _session = None
        session.finish()


def stick() -> tuple[float, float]:
    """Arrow keys and WASD as (x right, y up), each axis in -1..1.

    The Mac HID board wins when it sees the key. Ursina's own table is the other path.
    """
    from sideband.keys import BOARD

    try:
        from ursina import held_keys
    except Exception:
        held_keys = {}

    def axis(neg: tuple[str, ...], pos: tuple[str, ...]) -> float:
        down_neg = BOARD.down(*neg) or any(bool(held_keys[name]) for name in neg if name in held_keys)
        down_pos = BOARD.down(*pos) or any(bool(held_keys[name]) for name in pos if name in held_keys)
        return float(down_pos) - float(down_neg)

    return axis(("a", "left", "left arrow"), ("d", "right", "right arrow")), axis(("s", "down", "down arrow"), ("w", "up", "up arrow"))


def aim(keys: tuple[float, float]) -> tuple[float, float]:
    """Keys win on an axis. A mouse that has left the middle fills an axis they are not holding."""
    x, y = keys
    px, py = 0.0, 0.0
    try:
        from ursina import mouse

        px = max(-1.0, min(1.0, float(mouse.position[0]) * 2.4))
        py = max(-1.0, min(1.0, float(mouse.position[1]) * 2.4))
    except Exception:
        pass
    if abs(px) < 0.12 and abs(py) < 0.12:
        cursor = _cursor_axes()
        if cursor is not None:
            px, py = cursor
    if abs(x) < 0.05 and abs(px) > 0.12:
        x = px
    if abs(y) < 0.05 and abs(py) > 0.12:
        y = py
    return x, y


def _cursor_axes() -> tuple[float, float] | None:
    """Cursor offset from the Panda window, -1..1. None when there is no Mac poll."""
    from sideband.keys import _coregraphics, _cursor

    cg = _coregraphics()
    if cg is None:
        return None
    point = _cursor(cg)
    if point is None:
        return None
    try:
        from ursina import application

        props = application.base.win.getProperties()
        width, height = props.getXSize(), props.getYSize()
        origin_x, origin_y = props.getXOrigin(), props.getYOrigin()
    except Exception:
        return None
    if width < 20 or height < 20:
        return None
    local_x = (point[0] - origin_x) / width * 2 - 1
    local_y = 1 - (point[1] - origin_y) / height * 2
    return max(-1.0, min(1.0, local_x * 1.35)), max(-1.0, min(1.0, local_y * 1.35))


def lock(on: bool) -> None:
    from sideband.keys import BOARD

    try:
        from ursina import mouse

        mouse.locked = bool(on)
    except Exception:
        pass
    if on:
        BOARD.arm_pointer()
    else:
        BOARD.release_pointer()


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


def concrete_image():
    """Poured concrete with form seams. Generated, not a photo."""
    import random
    from PIL import Image

    rng = random.Random(7)
    image = Image.new("RGB", (128, 128))
    pixels = image.load()
    for y in range(128):
        for x in range(128):
            grain = rng.randint(-20, 14)
            seam = 32 if x % 64 < 2 or y % 64 < 2 else 0
            pixels[x, y] = (
                max(0, 124 + grain - seam),
                max(0, 116 + grain - seam),
                max(0, 104 + grain - seam),
            )
    return image


def cloth_image():
    """Olive weave for uniforms."""
    import random
    from PIL import Image

    rng = random.Random(11)
    image = Image.new("RGB", (64, 64))
    pixels = image.load()
    for y in range(64):
        for x in range(64):
            weave = 10 if (x // 2 + y // 2) % 2 == 0 else -6
            grain = rng.randint(-8, 8)
            pixels[x, y] = (max(0, 78 + weave + grain), max(0, 84 + weave + grain), max(0, 52 + grain))
    return image


def alloy_image():
    """Brushed aluminium for the fighter."""
    import math
    import random
    from PIL import Image

    rng = random.Random(43)
    image = Image.new("RGB", (128, 64))
    pixels = image.load()
    for y in range(64):
        band = int(18 * math.sin(y / 3.5))
        for x in range(128):
            grain = rng.randint(-8, 8)
            shade = 168 + band + grain
            pixels[x, y] = (shade, shade + 2, shade + 8)
    return image


def cloud_image():
    """A soft puff. Alpha falls off from the centre."""
    import math
    from PIL import Image

    size = 128
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    pixels = image.load()
    for y in range(size):
        for x in range(size):
            nx, ny = (x / (size - 1) - 0.5) * 2, (y / (size - 1) - 0.5) * 2
            disc = max(0.0, 1.0 - math.sqrt(nx * nx + ny * ny))
            puff = disc * disc
            pixels[x, y] = (255, 248, 236, int(puff * 210))
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


def _debug_label() -> Any:
    try:
        return label("", (-0.86, -0.46), 1.15)
    except Exception:
        return None


def grade(mood: str = "neutral") -> str:
    """Reserved for bloom and exposure.

    CommonFilters bloom washes the sky out to white on the GL path this machine can
    render, so the call stays a no-op. The sun, fog and vignette are the grade.
    """
    return mood


_filters: Any = None


def _clear_grade() -> None:
    global _filters
    if _filters is None:
        return
    try:
        _filters.cleanup()
    except Exception:
        pass
    _filters = None


def vignette(session: Any) -> None:
    """A soft darkening at the edges, generated here. It sits behind the HUD text."""
    from ursina import Entity, camera, color

    session.own(Entity(
        parent=camera.ui, model="quad", texture=paint("vignette", _vignette_image()),
        color=color.rgba(1, 1, 1, 0.85), scale=(1.8, 1.15), z=0.8,
    ))


def _vignette_image() -> Any:
    from PIL import Image

    size = 256
    image = Image.new("RGBA", (size, size))
    pixels = image.load()
    for y in range(size):
        for x in range(size):
            nx, ny = (x / (size - 1) - 0.5) * 2, (y / (size - 1) - 0.5) * 2
            edge = max(0.0, min(1.0, (nx * nx + ny * ny - 0.55) / 0.9))
            pixels[x, y] = (8, 6, 10, int(edge * 170))
    return image


def _show(title: str) -> None:
    from panda3d.core import WindowProperties
    from ursina import application

    from sideband.keys import activate

    activate()
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
