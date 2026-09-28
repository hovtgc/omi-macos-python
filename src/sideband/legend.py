"""The Arcade's button legend: what each pendant control does right now, drawn the same way everywhere.

Every control has one colour and one keycap, in the menu and in every game:
● TAP (green) goes forward, ●● DOUBLE (amber) goes back, TILT (pink) moves, HOLD (blue) pauses,
“ SAY ” (mint) is something to say out loud.
`legend` is pure (which controls to show for a game and state); `draw_legend` draws them as chips.
"""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont

# control: (keycap text, colour)
CONTROLS = {
    "tap": ("● TAP", "#3ddc84"),
    "double": ("●● DOUBLE", "#ffb020"),
    "hold": ("▬ HOLD", "#4db8ff"),
    "tilt": ("✥ TILT", "#ff4fd8"),
    "shake": ("≋ SHAKE", "#ffe66d"),
    "say": ("“ SAY ”", "#4dffb0"),
}

PLAY = {
    "menu": (("tap", "TALK"), ("say", "PLAY SKY ACE · PLAY THIS · RECALIBRATE")),
    "fighter": (("tilt", "FLY"), ("tap", "FIRE"), ("double", "BURST"), ("shake", "ROLL"), ("hold", "PAUSE")),
    "flap": (("tilt", "STEER"), ("tap", "FLAP"), ("double", "BIG FLAP"), ("hold", "PAUSE")),
    "voice": (("tap", "MIC ON / OFF"), ("say", "GO LEFT · RIGHT · UP · DOWN · EXIT"), ("hold", "PAUSE")),
    "corn": (("tilt", "ROLL"), ("tap", "BRAKE"), ("hold", "PAUSE")),
    "dodger": (("tilt", "FLY"), ("tap", "FIRE"), ("shake", "BOMB"), ("hold", "PAUSE")),
    "catch": (("tilt", "MOVE"), ("hold", "PAUSE")),
}
STATES = {"ready": "START", "paused": "RESUME", "over": "AGAIN", "won": "NEXT LEVEL"}


def legend(game: str, state: str = "playing", motion: bool = True) -> tuple[tuple[str, str], ...]:
    """The controls to show for `game` ("menu" or a game key) in `state`, as (control, label) pairs.

    Outside play every game is the same: one tap goes forward, a double tap goes back to the Arcade.
    The mic stays on in every game, so saying "exit game" also goes back; `draw_ear` shows that.
    """
    if game == "menu":
        return PLAY[game]
    if state == "playing":
        items = PLAY[game]
    else:
        items = (("tap", STATES[state]), ("double", "ARCADE"))
    if not motion:  # arrow keys stand in for tilt
        items = tuple((control, f"{label} · ARROWS" if control == "tilt" else label) for control, label in items)
    return items


def round_rect(c: tk.Canvas, x0: float, y0: float, x1: float, y1: float, r: float, **kw) -> int:
    points = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1, x1 - r, y1, x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]
    return c.create_polygon(points, smooth=True, **kw)


_widths: dict[tuple[tuple, str], int] = {}


def _measure(c: tk.Canvas, spec: tuple, text: str) -> int:
    """Text width in pixels, cached: Tk's measure is a round trip too slow to call every frame."""
    if (spec, text) not in _widths:
        _widths[spec, text] = tkfont.Font(root=c, font=spec).measure(text)
    return _widths[spec, text]


def chip(c: tk.Canvas, x: float, cy: float, control: str, label: str, size: int = 15, tag: str = "dyn", measure_only: bool = False) -> float:
    """One [KEYCAP] LABEL chip with its left edge at x. Returns its width."""
    cap, colour = CONTROLS[control]
    cap_font, label_font = ("Helvetica", size - 2, "bold"), ("Helvetica", size + 2, "bold")
    pad, h = size * 0.6, size * 1.9
    cap_w = _measure(c, cap_font, cap) + pad * 2
    width = cap_w + size * 0.5 + _measure(c, label_font, label)
    if not measure_only:
        round_rect(c, x, cy - h / 2, x + cap_w, cy + h / 2, h * 0.45, fill=colour, outline="", tags=tag)
        c.create_text(x + cap_w / 2, cy, text=cap, fill="#12002b", font=cap_font, tags=tag)
        c.create_text(x + cap_w + size * 0.5, cy, anchor="w", text=label, fill="#ffffff", font=label_font, tags=tag)
    return width


def draw_legend(c: tk.Canvas, cx: float, cy: float, items: tuple[tuple[str, str], ...], size: int = 15,
                max_width: float | None = None, tag: str = "dyn") -> None:
    """A centred row of chips; shrinks the text until the row fits in max_width."""
    while True:
        gap = size * 1.6
        widths = [chip(c, 0, 0, control, label, size, measure_only=True) for control, label in items]
        total = sum(widths) + gap * (len(items) - 1)
        if max_width is None or total <= max_width or size <= 10:
            break
        size -= 1
    x = cx - total / 2
    for (control, label), width in zip(items, widths):
        chip(c, x, cy, control, label, size, tag)
        x += width + gap


METER_BARS = 10


def draw_meter(c: tk.Canvas, x: float, cy: float, level: float, height: float = 22, tag: str = "dyn") -> float:
    """A little equaliser: bars that light up with the mic level. Returns its width."""
    bar, gap = 4, 2
    for i in range(METER_BARS):
        t = (i + 1) / METER_BARS
        h = height * (0.35 + 0.65 * t)
        lit = level >= t - 0.5 / METER_BARS
        colour = ("#3ddc84" if t <= 0.6 else "#ffd23f" if t <= 0.85 else "#ff4d6d") if lit else "#3a2a5a"
        bx = x + i * (bar + gap)
        c.create_rectangle(bx, cy + height / 2 - h, bx + bar, cy + height / 2, fill=colour, outline="", tags=tag)
    return METER_BARS * (bar + gap) - gap


def draw_mic(c: tk.Canvas, x: float, cy: float, colour: str = "#ffffff", s: float = 1.0, tag: str = "dyn") -> None:
    """A drawn microphone (Tk on macOS draws emoji unreliably)."""
    round_rect(c, x - 6 * s, cy - 13 * s, x + 6 * s, cy + 4 * s, 6 * s, fill=colour, outline="", tags=tag)
    c.create_arc(x - 10 * s, cy - 8 * s, x + 10 * s, cy + 9 * s, start=200, extent=140, style="arc", outline=colour, width=max(2, int(2 * s)), tags=tag)
    c.create_line(x, cy + 9 * s, x, cy + 14 * s, fill=colour, width=max(2, int(2 * s)), tags=tag)


def draw_ear(c: tk.Canvas, right: float, cy: float, level: float | None, caption: str, age: float,
             hint: str = "say “exit”", fresh_s: float = 2.5, tag: str = "dyn") -> None:
    """The in-game mic badge, anchored at its right edge: a small volume meter and what the pendant just
    heard (only while fresh; otherwise a tiny hint)."""
    if level is None:
        return
    fresh = bool(caption) and age < fresh_s
    text = (f"“{caption}”" if not caption.startswith("“") else caption) if fresh else hint
    spec = ("Helvetica", 13 if fresh else 10, "bold")
    bars = METER_BARS * 6 - 2
    width = 12 + 14 + 6 + bars * 0.6 + 8 + _measure(c, spec, text) + 12
    x0 = right - width
    round_rect(c, x0, cy - 13, right, cy + 13, 12, fill="#12002b", outline="#4dffb0" if fresh else "#2b1a4a", width=2, tags=tag)
    draw_mic(c, x0 + 17, cy + 1, "#4dffb0" if level > 0.15 else "#9c8cff", 0.6, tag)
    mx = x0 + 32
    for i in range(METER_BARS):  # a slimmer meter than the menu's
        t = (i + 1) / METER_BARS
        h = 14 * (0.35 + 0.65 * t)
        lit = level >= t - 0.5 / METER_BARS
        colour = ("#3ddc84" if t <= 0.6 else "#ffd23f" if t <= 0.85 else "#ff4d6d") if lit else "#3a2a5a"
        c.create_rectangle(mx + i * 3.6, cy + 7 - h, mx + i * 3.6 + 2.4, cy + 7, fill=colour, outline="", tags=tag)
    c.create_text(mx + bars * 0.6 + 8, cy, anchor="w", text=text, fill="#ffffff" if fresh else "#7a6a9a", font=spec, tags=tag)
