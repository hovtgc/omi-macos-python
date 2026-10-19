"""Gamepads, as the same buttons the shelf and the games already understand.

pygame (the `gamepad` extra) talks to Xbox, PlayStation and generic pads through SDL, including
hot-plug. This module still imports cleanly when pygame is absent: `read_pygame` returns nothing
and the picker says so. Edge detection is pure, so tests never open a device.
"""

from __future__ import annotations

from dataclasses import dataclass, field

DEADZONE = 0.18
# SDL / pygame layout. Xbox A and PlayStation Cross are both button 0.
A, B, X, Y = 0, 1, 2, 3
LB, RB, BACK, START = 4, 5, 6, 7
# Some pads report the d-pad as buttons instead of a hat.
DPAD_UP, DPAD_DOWN, DPAD_LEFT, DPAD_RIGHT = 11, 12, 13, 14


@dataclass(frozen=True)
class RawPad:
    name: str
    index: int
    buttons: tuple[int, ...]
    axes: tuple[float, float]
    hat: tuple[int, int] = (0, 0)


@dataclass
class PadEvent:
    """One poll. Axes are held; the button fields are edges (pressed since the previous poll).

    `y` is up-positive, matching pendant tilt. `dpad_x` is +1 to the right.
    """

    name: str
    index: int
    x: float = 0.0
    y: float = 0.0
    confirm: bool = False  # A / Cross
    cancel: bool = False  # B / Circle
    menu: bool = False  # Start
    fire: bool = False  # X / Square
    shake: bool = False  # Y / Triangle or LB
    dpad_x: int = 0
    dpad_y: int = 0
    connected: tuple[str, ...] = ()


def _bit(buttons: tuple[int, ...], index: int) -> int:
    return buttons[index] if 0 <= index < len(buttons) else 0


def _rising(now: tuple[int, ...], was: tuple[int, ...], index: int) -> bool:
    return bool(_bit(now, index) and not _bit(was, index))


def _dpad(pad: RawPad) -> tuple[int, int]:
    if pad.hat != (0, 0):
        return pad.hat
    return (_bit(pad.buttons, DPAD_RIGHT) - _bit(pad.buttons, DPAD_LEFT),
            _bit(pad.buttons, DPAD_UP) - _bit(pad.buttons, DPAD_DOWN))


def edges(raw: list[RawPad], prev: dict[int, tuple[tuple[int, ...], tuple[int, int]]], preferred: str | None = None) -> PadEvent | None:
    """Fold a poll into one event for the preferred pad (or the first). Updates `prev`."""
    if not raw:
        prev.clear()
        return None
    pick = raw[0]
    if preferred:
        wanted = preferred.lower()
        for pad in raw:
            if wanted in pad.name.lower():
                pick = pad
                break
    was_buttons, was_hat = prev.get(pick.index, ((), (0, 0)))
    hat = _dpad(pick)
    # Edge only when a direction newly becomes non-zero. Holding the hat does not repeat.
    dpx = hat[0] if hat[0] != 0 and hat[0] != was_hat[0] else 0
    dpy = hat[1] if hat[1] != 0 and hat[1] != was_hat[1] else 0
    prev[pick.index] = (pick.buttons, hat)
    # Drop pads that disappeared so a replug starts clean.
    live = {pad.index for pad in raw}
    for index in [key for key in prev if key not in live]:
        del prev[index]
    x, y = pick.axes
    if abs(x) < DEADZONE:
        x = 0.0
    if abs(y) < DEADZONE:
        y = 0.0
    return PadEvent(
        name=pick.name,
        index=pick.index,
        x=x,
        y=-y,
        confirm=_rising(pick.buttons, was_buttons, A),
        cancel=_rising(pick.buttons, was_buttons, B),
        menu=_rising(pick.buttons, was_buttons, START) or _rising(pick.buttons, was_buttons, BACK),
        fire=_rising(pick.buttons, was_buttons, X) or _rising(pick.buttons, was_buttons, RB),
        shake=_rising(pick.buttons, was_buttons, Y) or _rising(pick.buttons, was_buttons, LB),
        dpad_x=dpx,
        dpad_y=dpy,
        connected=tuple(pad.name for pad in raw),
    )


_pygame = None
_joys: dict[int, object] = {}


def pygame_ready() -> bool:
    try:
        import pygame  # noqa: F401
    except ImportError:
        return False
    return True


def read_pygame() -> list[RawPad]:
    """The pads plugged in right now. Empty when pygame isn't installed or nothing is connected."""
    global _pygame
    try:
        import pygame
    except ImportError:
        return []
    if _pygame is None:
        pygame.init()
        pygame.joystick.init()
        _pygame = pygame
    pygame.event.pump()
    count = pygame.joystick.get_count()
    live: set[int] = set()
    found: list[RawPad] = []
    for index in range(count):
        joy = _joys.get(index)
        if joy is None:
            joy = pygame.joystick.Joystick(index)
            joy.init()
            _joys[index] = joy
        live.add(index)
        buttons = tuple(int(joy.get_button(bit)) for bit in range(min(16, joy.get_numbuttons())))
        axes = (
            float(joy.get_axis(0)) if joy.get_numaxes() else 0.0,
            float(joy.get_axis(1)) if joy.get_numaxes() > 1 else 0.0,
        )
        hat = tuple(joy.get_hat(0)) if joy.get_numhats() else (0, 0)
        found.append(RawPad(str(joy.get_name()), index, buttons, axes, hat))  # type: ignore[arg-type]
    for index in [key for key in _joys if key not in live]:
        try:
            _joys[index].quit()  # type: ignore[attr-defined]
        except Exception:
            pass
        del _joys[index]
    return found


@dataclass
class PadBank:
    """Polls pygame (or a stand-in) and remembers the last axes so games can steer between edges."""

    preferred: str | None = None
    latest: PadEvent | None = None
    _prev: dict[int, tuple[tuple[int, ...], tuple[int, int]]] = field(default_factory=dict)
    reader: object = read_pygame

    def names(self) -> tuple[str, ...]:
        return () if self.latest is None else self.latest.connected

    def poll(self) -> PadEvent | None:
        raw = self.reader()  # type: ignore[operator]
        self.latest = edges(list(raw), self._prev, self.preferred)
        return self.latest
