"""Keyboard and mouse that do not depend on which toolkit owns the window.

`Sideband.app` is an agent (`LSUIElement`). macOS will not deliver key events to an agent
until the process activates itself, and Tk and Panda then disagree about which window is
key. The arcade therefore polls the HID keyboard and the cursor on a Mac, and still
accepts events Tk or Ursina managed to deliver. Tests push samples in; nothing here
opens a window.

F3 toggles an on-screen line: the last key or mouse event, and what is held.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field

# macOS virtual key codes (ANSI). Tk keysyms use the same names we store.
MAC_CODES: dict[int, str] = {
    0: "a", 1: "s", 2: "d", 13: "w",
    12: "q", 14: "e", 15: "r", 17: "t",
    6: "z", 7: "x", 8: "c", 9: "v", 11: "b",
    18: "1", 19: "2", 20: "3", 21: "4", 23: "5",
    36: "return", 49: "space", 53: "escape",
    123: "left", 124: "right", 125: "down", 126: "up",
    99: "f3", 103: "f11", 122: "f1",
}

URSINA_NAMES = {
    "left": "left arrow",
    "right": "right arrow",
    "up": "up arrow",
    "down": "down arrow",
    "return": "enter",
    "mouse": "left mouse",
}


@dataclass
class Board:
    """One process-wide keyboard. `sample` replaces the Mac poll in tests."""

    held: set[str] = field(default_factory=set)
    pressed: set[str] = field(default_factory=set)
    released: set[str] = field(default_factory=set)
    seen: set[str] = field(default_factory=set)
    last: str = ""
    look: tuple[float, float] = (0.0, 0.0)
    debug: bool = False
    activated: str = ""
    pointer: bool = False
    hid: bool = False
    sample: object | None = None  # () -> (dict[str, bool], dx, dy, mouse_down) or None
    _lock_at: tuple[float, float] | None = None
    _skip_look: int = 0

    def observe(self, name: str, down: bool) -> None:
        """Tk or Ursina already saw this. Remember it so the HID poll does not repeat it."""
        name = _canon(name)
        self.seen.add(name)
        if down:
            self.held.add(name)
            self.last = f"key down {name}"
        else:
            self.held.discard(name)
            self.last = f"key up {name}"
        if name == "f3" and down:
            self.debug = not self.debug

    def poll(self) -> None:
        """Fold one HID sample into `held` and `pressed`. No-op when the platform has none."""
        sample = self.sample() if self.sample is not None else _platform_sample(self)
        if not sample:
            self.look = (0.0, 0.0)
            return
        state, dx, dy, mouse_down = sample
        self.hid = True
        for name, down in state.items():
            if name in self.seen:
                continue
            if down and name not in self.held:
                self.held.add(name)
                self.pressed.add(name)
                self.last = f"key down {name}"
                if name == "f3":
                    self.debug = not self.debug
            elif not down and name in self.held:
                self.held.discard(name)
                self.released.add(name)
                self.last = f"key up {name}"
        if mouse_down and "mouse" not in self.held and "mouse" not in self.seen:
            self.held.add("mouse")
            self.pressed.add("mouse")
            self.last = "mouse down"
        elif not mouse_down and "mouse" in self.held and "mouse" not in self.seen:
            self.held.discard("mouse")
            self.released.add("mouse")
            self.last = "mouse up"
        if abs(dx) + abs(dy) > 0.4:
            self.last = f"mouse {dx:+.0f},{dy:+.0f}"
        self.look = (dx, dy)

    def end_frame(self) -> None:
        # F3 stays in `held` until it is actually released, so a held F3 toggles once.
        self.pressed.clear()
        self.released.clear()
        self.seen.clear()

    def down(self, *names: str) -> bool:
        return any(_canon(name) in self.held or name in self.held for name in names)

    def overlay(self) -> str:
        if not self.debug:
            return ""
        held = " ".join(sorted(self.held)[:10]) or "none"
        where = self.activated or "not activated"
        return f"F3 input   last {self.last or 'none yet'}   held {held}   {where}"

    def arm_pointer(self) -> None:
        self.pointer = True
        self._lock_at = None
        self._skip_look = 2

    def release_pointer(self) -> None:
        self.pointer = False
        self._lock_at = None
        _associate_cursor(True)


BOARD = Board()


def _canon(name: str) -> str:
    name = name.lower().replace(" arrow", "")
    return {"enter": "return", "left mouse": "mouse", "spacebar": "space"}.get(name, name)


def activate() -> str:
    """Ask macOS to make this process the foreground app. Other platforms are a no-op.

    Safe to call again when a new window opens: the policy sticks, and the front
    window is made key each time. An agent (`LSUIElement`) otherwise never receives keys.
    """
    if sys.platform != "darwin":
        BOARD.activated = BOARD.activated or "not macOS"
        return BOARD.activated
    try:
        BOARD.activated = _activate_cocoa()
    except Exception as exc:
        BOARD.activated = f"activate failed ({exc})"
    return BOARD.activated


def keyboard_check() -> tuple[bool | None, str, str]:
    """`(ok, detail, fix)` for `sideband doctor`. None means the check does not apply."""
    if sys.platform != "darwin":
        return None, "not macOS; the focused window takes the keyboard", ""
    if _coregraphics() is None:
        return False, "CoreGraphics keyboard poll is missing", "Reinstall macOS command line tools, then sh scripts/setup.sh"
    return True, "HID poll ready. Sideband.app is an agent, so the arcade activates itself and reads the keyboard directly", ""


def attach(widget: object) -> None:
    """Record Tk key and click events on `widget` without replacing its own bindings."""
    widget.bind("<KeyPress>", lambda event: BOARD.observe(event.keysym, True), add="+")  # type: ignore[attr-defined]
    widget.bind("<KeyRelease>", lambda event: BOARD.observe(event.keysym, False), add="+")  # type: ignore[attr-defined]
    widget.bind("<ButtonPress-1>", lambda _event: BOARD.observe("mouse", True), add="+")  # type: ignore[attr-defined]
    widget.bind("<ButtonRelease-1>", lambda _event: BOARD.observe("mouse", False), add="+")  # type: ignore[attr-defined]


def ursina_names(names: set[str]) -> set[str]:
    out = set(names)
    for name in names:
        alias = URSINA_NAMES.get(name)
        if alias:
            out.add(alias)
    return out


def flush_widget(top: object, keys: set[str] | None = None, canvas: object | None = None) -> str:
    """Poll, then deliver edges Tk did not already see. Returns the F3 overlay line.

    Tk bindings run first and call `observe`, so those edges are not delivered twice.
    A Mac that never delivered the event still shows up here, and `keys` is brought
    in line with what is physically held so WASD does not stick.
    """
    BOARD.poll()
    overlay = BOARD.overlay()
    for name in list(BOARD.pressed):
        if name == "f3":
            continue
        if name == "mouse":
            _emit(canvas, "<ButtonPress-1>", None)
        else:
            _emit(top, "<KeyPress>", _keysym(name))
    for name in list(BOARD.released):
        if name == "f3":
            continue
        if name == "mouse":
            _emit(canvas, "<ButtonRelease-1>", None)
        else:
            _emit(top, "<KeyRelease>", _keysym(name))
    if keys is not None:
        _adopt(keys)
    BOARD.end_frame()
    return overlay


def focus(widget: object) -> str:
    """Bring `widget` forward. On a Mac, also activate the process so it can take keys."""
    try:
        widget.lift()  # type: ignore[attr-defined]
        widget.focus_force()  # type: ignore[attr-defined]
    except Exception:
        pass
    return activate()


def stamp(canvas: object, x: float, y: float, text: str) -> None:
    if not text:
        return
    try:
        canvas.create_text(  # type: ignore[attr-defined]
            x, y, anchor="w", text=text, fill="#f6edd4", font=("Menlo", 11), tags="dyn",
        )
    except Exception:
        pass


def _keysym(name: str) -> str:
    return {
        "return": "Return",
        "escape": "Escape",
        "left": "Left",
        "right": "Right",
        "up": "Up",
        "down": "Down",
        "space": "space",
        "f11": "F11",
        "f1": "F1",
    }.get(name, name)


def _emit(widget: object | None, sequence: str, keysym: str | None) -> None:
    if widget is None:
        return
    try:
        if keysym is None:
            widget.event_generate(sequence)  # type: ignore[attr-defined]
        else:
            widget.event_generate(sequence, keysym=keysym)  # type: ignore[attr-defined]
    except Exception:
        pass


def _adopt(keys: set[str]) -> None:
    if BOARD.hid:
        tracked = set(MAC_CODES.values())
        for name in list(keys):
            if name in tracked and name not in BOARD.held:
                keys.discard(name)
        for name in BOARD.held:
            if name not in ("f3", "mouse"):
                keys.add(name)
        return
    for name in BOARD.held:
        if name not in ("f3", "mouse"):
            keys.add(name)


def _platform_sample(board: Board) -> tuple[dict[str, bool], float, float, bool] | None:
    cg = _coregraphics()
    if cg is None:
        return None
    try:
        state = {name: bool(cg.CGEventSourceKeyState(1, code)) for code, name in MAC_CODES.items()}
        mouse_down = bool(cg.CGEventSourceButtonState(1, 0))
        dx, dy = _pointer_delta(board, cg)
        return state, dx, dy, mouse_down
    except Exception:
        return None


def _pointer_delta(board: Board, cg: object) -> tuple[float, float]:
    if not board.pointer:
        return 0.0, 0.0
    point = _cursor(cg)
    if point is None:
        return 0.0, 0.0
    if board._lock_at is None or board._skip_look > 0:
        board._lock_at = point
        board._skip_look = max(0, board._skip_look - 1)
        _warp(cg, point)
        return 0.0, 0.0
    dx, dy = point[0] - board._lock_at[0], point[1] - board._lock_at[1]
    _warp(cg, board._lock_at)
    _associate_cursor(False)
    return dx, dy


_CG = None
_CG_TRIED = False


def _coregraphics() -> object | None:
    global _CG, _CG_TRIED
    if _CG_TRIED:
        return _CG
    _CG_TRIED = True
    if sys.platform != "darwin":
        return None
    import ctypes

    try:
        cg = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
    except OSError:
        return None

    class CGPoint(ctypes.Structure):
        _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]

    cg.CGEventSourceKeyState.argtypes = [ctypes.c_int, ctypes.c_uint16]
    cg.CGEventSourceKeyState.restype = ctypes.c_bool
    cg.CGEventSourceButtonState.argtypes = [ctypes.c_int, ctypes.c_int]
    cg.CGEventSourceButtonState.restype = ctypes.c_bool
    cg.CGEventCreate.argtypes = [ctypes.c_void_p]
    cg.CGEventCreate.restype = ctypes.c_void_p
    cg.CGEventGetLocation.argtypes = [ctypes.c_void_p]
    cg.CGEventGetLocation.restype = CGPoint
    cg.CGWarpMouseCursorPosition.argtypes = [CGPoint]
    cg.CGWarpMouseCursorPosition.restype = ctypes.c_int
    cg.CGAssociateMouseAndMouseCursorPosition.argtypes = [ctypes.c_bool]
    cg.CGAssociateMouseAndMouseCursorPosition.restype = ctypes.c_int
    cg._Point = CGPoint
    _CG = cg
    return cg


def _cursor(cg: object) -> tuple[float, float] | None:
    event = cg.CGEventCreate(None)
    if not event:
        return None
    point = cg.CGEventGetLocation(event)
    return float(point.x), float(point.y)


def _warp(cg: object, point: tuple[float, float]) -> None:
    cg.CGWarpMouseCursorPosition(cg._Point(point[0], point[1]))


def _associate_cursor(connected: bool) -> None:
    cg = _coregraphics()
    if cg is None:
        return
    try:
        cg.CGAssociateMouseAndMouseCursorPosition(connected)
    except Exception:
        pass


def _activate_cocoa() -> str:
    import ctypes
    import ctypes.util

    lib = ctypes.util.find_library("objc")
    if not lib:
        return "objc missing"
    objc = ctypes.cdll.LoadLibrary(lib)
    objc.objc_getClass.restype = ctypes.c_void_p
    objc.objc_getClass.argtypes = [ctypes.c_char_p]
    objc.sel_registerName.restype = ctypes.c_void_p
    objc.sel_registerName.argtypes = [ctypes.c_char_p]

    def msg(restype: object, argtypes: list[object], obj: object, name: bytes, *args: object) -> object:
        send = objc.objc_msgSend
        send.restype = restype
        send.argtypes = [ctypes.c_void_p, ctypes.c_void_p, *argtypes]
        return send(obj, objc.sel_registerName(name), *args)

    app = msg(ctypes.c_void_p, [], objc.objc_getClass(b"NSApplication"), b"sharedApplication")
    if not app:
        return "no NSApplication"
    # Regular, not accessory. An agent stays out of the Dock in the plist, but a
    # playing window has to be allowed to become key or the keyboard never arrives.
    msg(ctypes.c_bool, [ctypes.c_long], app, b"setActivationPolicy:", ctypes.c_long(0))
    msg(None, [ctypes.c_bool], app, b"activateIgnoringOtherApps:", True)
    _front_window(msg, app)
    return "activated"


def _front_window(msg: object, app: object) -> None:
    import ctypes

    windows = msg(ctypes.c_void_p, [], app, b"windows")
    if not windows:
        return
    count = int(msg(ctypes.c_ulong, [], windows, b"count") or 0)
    if not count:
        return
    # `windows` is front to back. Take the frontmost window that belongs to the arcade,
    # and otherwise the frontmost window so a newly opened Panda view still becomes key.
    hints = ("Sideband", "Desert", "Sky", "Arcade", "Flap", "Omi", "Maze", "Catch")
    chosen = None
    for index in range(count):
        window = msg(ctypes.c_void_p, [ctypes.c_ulong], windows, b"objectAtIndex:", ctypes.c_ulong(index))
        title = _nsstring(msg, msg(ctypes.c_void_p, [], window, b"title"))
        if any(hint in title for hint in hints):
            chosen = window
            break
    if chosen is None:
        chosen = msg(ctypes.c_void_p, [ctypes.c_ulong], windows, b"objectAtIndex:", ctypes.c_ulong(0))
    if chosen is not None:
        msg(None, [ctypes.c_void_p], chosen, b"makeKeyAndOrderFront:", None)


def _nsstring(msg: object, text: object) -> str:
    import ctypes

    if not text:
        return ""
    raw = msg(ctypes.c_void_p, [], text, b"UTF8String")
    if not raw:
        return ""
    return ctypes.string_at(raw).decode("utf-8", "replace")
