"""The local arcade platform: the game shelf, scores, and one input frame for every controller.

Pure. Nothing here opens a window or touches Bluetooth. A game is a `GameSpec` in `LIBRARY`.
The shelf (`Shelf`) is the home screen's focus: keyboard, mouse, the Omi and a gamepad all
call the same `move` / `back` / `activate`. `Scorebook` keeps bests, play counts and recents
in `arcade.json`. `InputFrame` is what a game reads each tick, whoever produced it.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GameSpec:
    """One game on the shelf. `score` is "points" (higher wins) or "time" (lower wins)."""

    key: str
    title: str
    blurb: str
    colors: tuple[str, str]
    icon: str
    motion: bool  # the intended way to steer needs the motion firmware; taps still do something
    score: str = "points"
    aliases: tuple[str, ...] = ()
    stock: bool = False  # fun on stock firmware: taps, holds, voice, mic level. No tilt required.


# Order is the shelf order. The first six are the games that were already here.
LIBRARY: tuple[GameSpec, ...] = (
    GameSpec("fighter", "SKY ACE 1943", "WWII dogfight. Tilt to fly, tap to fire, shake to roll.",
             ("#ff9f1c", "#7a2210"), "plane", True, aliases=("fighter", "ace", "plane", "sky")),
    GameSpec("flap", "OMI FLAP 3D", "Tap to flap. Tilt, or the arrow keys, to steer.",
             ("#3ad0ff", "#1a3c9c"), "ball", True, aliases=("flap",)),
    GameSpec("corn", "CORN MAZE", "Roll the pumpkin home to the red barn.",
             ("#ffd23f", "#2f7a22"), "corn", True, score="time", aliases=("corn",)),
    GameSpec("dodger", "STAR DODGER", "Tilt to fly. Tap fires. Shake drops a bomb.",
             ("#b56cff", "#3a1578"), "rocket", True, aliases=("dodger",)),
    GameSpec("catch", "OMI CATCH", "Slide the basket. Catch stars, dodge bombs.",
             ("#ff5fa2", "#8a1458"), "basket", True, aliases=("catch",)),
    GameSpec("voice", "VOICE FLAP", "Say go left, right, up, down. Tap the mic.",
             ("#4dffb0", "#0e6a48"), "bubble", False, stock=True, aliases=("voice",)),
    GameSpec("beat", "BEAT TAP", "Tap on the beat. A shout counts too.",
             ("#ff4d6d", "#6e1028"), "beat", False, stock=True, aliases=("beat", "rhythm")),
    GameSpec("draw", "QUICKDRAW", "Wait for DRAW, then tap. Too soon and you foul.",
             ("#ffe66d", "#a86210"), "draw", False, stock=True, aliases=("draw", "quickdraw", "reaction")),
    GameSpec("dash", "OMI DASH", "One button. Tap or shout to jump the boxes.",
             ("#3ddc84", "#0c5c38"), "dash", False, stock=True, aliases=("dash", "runner")),
    GameSpec("simon", "SIMON OMI", "Repeat the pattern. Single tap, then double tap.",
             ("#7aa2ff", "#1c2c66"), "simon", False, stock=True, aliases=("simon", "memory")),
)

# What the gear opens. Not on the game row.
SYSTEM: tuple[tuple[str, str, str], ...] = (
    ("thoughts", "THOUGHT MAP", "Transcription, folders, summaries, the assistant"),
    ("controls", "CONTROLS", "What a tap does on this Mac when you are not playing"),
    ("bluetooth", "BLUETOOTH", "Connect, scan and switch pendants"),
    ("ai", "AI SETTINGS", "A model on this Mac, or an API you opt into"),
    ("status", "STATUS", "What is installed and what to do next"),
    ("controllers", "CONTROLLERS", "Keyboard, Omi, or a gamepad"),
    ("log", "EVENT LOG", "The connection log"),
)

# `sideband open` names. `marble` is the old name for Corn Maze.
OPEN_NAMES: tuple[str, ...] = (
    "launcher", "thoughts", "transcriber", "controls", "arcade", "bluetooth", "marble",
    *[spec.key for spec in LIBRARY],
)


def game(key: str) -> GameSpec | None:
    return next((spec for spec in LIBRARY if spec.key == key), None)


def spoken_aliases() -> dict[str, str]:
    """Spoken words to game keys. Extras cover names people actually say."""
    names = {"marble": "corn", "maze": "corn", "star": "dodger"}
    for spec in LIBRARY:
        for word in spec.aliases:
            names[word] = spec.key
    return names


def score_badge(spec: GameSpec, best: float | None) -> str:
    if best is None:
        return "NEW"
    if spec.score == "time":
        return f"BEST {best:.1f}s"
    return f"BEST {int(best):,}"


# --- shelf focus -------------------------------------------------------------------------------


@dataclass
class Shelf:
    """Which card is highlighted, and whether the gear's menu is open.

    `move` walks the row (arrows, wheel, a single tap, a d-pad).
    `back` goes to the previous card, or closes the menu (double tap, Esc, B).
    `activate` launches the focused game or the focused settings row (Enter, hold, A).
    """

    keys: tuple[str, ...] = tuple(spec.key for spec in LIBRARY)
    index: int = 0
    sub: int = 0
    page: str = "games"  # games, system, controllers, status

    def count_for(self, page_count: int | None = None) -> int:
        if self.page == "games":
            return len(self.keys)
        if self.page == "system":
            return len(SYSTEM)
        return page_count or 1

    def move(self, delta: int, page_count: int | None = None) -> None:
        count = self.count_for(page_count)
        if count <= 0 or delta == 0:
            return
        if self.page == "games":
            self.index = (self.index + delta) % count
        else:
            self.sub = (self.sub + delta) % count

    def back(self) -> str:
        """Close a menu, or step to the previous game. Returns where we ended up."""
        if self.page in ("controllers", "status"):
            self.page, self.sub = "system", 0
            return "system"
        if self.page == "system":
            self.page = "games"
            return "games"
        self.index = (self.index - 1) % len(self.keys)
        return "prev"

    def activate(self) -> str:
        if self.page == "games":
            return f"play:{self.keys[self.index]}"
        if self.page == "system":
            return f"sys:{SYSTEM[self.sub][0]}"
        if self.page == "controllers":
            return f"pad:{self.sub}"
        return "status"

    def open_page(self, page: str) -> None:
        self.page, self.sub = page, 0

    def focus_key(self, key: str) -> None:
        if key in self.keys:
            self.index = self.keys.index(key)
            self.page = "games"


def shelf_slots(count: int, focus: float, view_w: float, card_w: float = 300, gap: float = 28) -> list[tuple[float, float]]:
    """`(center_x, scale)` for each card. The focused card sits in the middle and is the largest."""
    pitch = card_w * 0.72 + gap
    slots = []
    for i in range(count):
        dist = i - focus
        scale = 1.12 - 0.24 * min(1.0, abs(dist))
        slots.append((view_w / 2 + dist * pitch, scale))
    return slots


# --- one input frame ---------------------------------------------------------------------------


@dataclass
class InputFrame:
    """What a game consumes in one tick, after every controller has been folded in.

    `x` and `y` are -1..1 (right and up). `taps` is how many action presses landed this tick.
    `pad` is a second button (double tap, keyboard D, gamepad B) for games that need two.
    `volume` is the mic meter 0..1. `device` is "keys", "omi" or "pad".
    """

    x: float = 0.0
    y: float = 0.0
    taps: int = 0
    pad: int = 0
    shake: bool = False
    volume: float = 0.0
    device: str = "keys"


class VolumeEdge:
    """A shout: the mic crossing `threshold` on the way up is one press."""

    def __init__(self, threshold: float = 0.62) -> None:
        self.threshold = threshold
        self.hot = False

    def rising(self, level: float) -> bool:
        on = level >= self.threshold
        fired = on and not self.hot
        self.hot = on
        return fired


# --- scores ------------------------------------------------------------------------------------


class Scorebook:
    """Bests, how many times each game was opened, and the recent row. One JSON file, on this Mac."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.bests: dict[str, float] = {}
        self.plays: dict[str, int] = {}
        self.last: dict[str, float] = {}
        self.recent: list[str] = []
        self.load()

    def load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return
        if not isinstance(raw, dict):
            return
        legacy = "best" not in raw and all(isinstance(value, (int, float)) for value in raw.values())
        if legacy:
            self.bests = {str(key): float(value) for key, value in raw.items()}
            return
        self.bests = {str(key): float(value) for key, value in dict(raw.get("best") or {}).items()}
        self.plays = {str(key): int(value) for key, value in dict(raw.get("plays") or {}).items()}
        self.last = {str(key): float(value) for key, value in dict(raw.get("last") or {}).items()}
        self.recent = [str(key) for key in list(raw.get("recent") or [])]

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "best": self.bests,
            "plays": self.plays,
            "last": self.last,
            "recent": self.recent[:12],
        }
        self.path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    def best(self, key: str) -> float | None:
        return self.bests.get(key)

    def record(self, key: str, score: float, lower_is_better: bool = False) -> bool:
        old = self.bests.get(key)
        better = old is None or (score < old if lower_is_better else score > old)
        if better:
            self.bests[key] = float(score)
            self.save()
        return better

    def touch(self, key: str) -> None:
        """The player opened this game. It becomes the most recent."""
        self.plays[key] = self.plays.get(key, 0) + 1
        self.last[key] = time.time()
        self.recent = [key] + [item for item in self.recent if item != key]
        self.recent = self.recent[:12]
        self.save()

    def stats(self, key: str) -> dict[str, float | int | None]:
        return {"best": self.bests.get(key), "plays": self.plays.get(key, 0), "last": self.last.get(key)}


# --- chunky bitmap font (5x7), so titles look like a cabinet even without a pixel font file ----

_RAW: dict[str, list[str]] = {
    "A": ["01110", "10001", "10001", "11111", "10001", "10001", "10001"],
    "B": ["11110", "10001", "10001", "11110", "10001", "10001", "11110"],
    "C": ["01110", "10001", "10000", "10000", "10000", "10001", "01110"],
    "D": ["11110", "10001", "10001", "10001", "10001", "10001", "11110"],
    "E": ["11111", "10000", "10000", "11110", "10000", "10000", "11111"],
    "F": ["11111", "10000", "10000", "11110", "10000", "10000", "10000"],
    "G": ["01110", "10001", "10000", "10111", "10001", "10001", "01111"],
    "H": ["10001", "10001", "10001", "11111", "10001", "10001", "10001"],
    "I": ["11111", "00100", "00100", "00100", "00100", "00100", "11111"],
    "J": ["00111", "00010", "00010", "00010", "10010", "10010", "01100"],
    "K": ["10001", "10010", "10100", "11000", "10100", "10010", "10001"],
    "L": ["10000", "10000", "10000", "10000", "10000", "10000", "11111"],
    "M": ["10001", "11011", "10101", "10101", "10001", "10001", "10001"],
    "N": ["10001", "11001", "10101", "10011", "10001", "10001", "10001"],
    "O": ["01110", "10001", "10001", "10001", "10001", "10001", "01110"],
    "P": ["11110", "10001", "10001", "11110", "10000", "10000", "10000"],
    "Q": ["01110", "10001", "10001", "10001", "10101", "10010", "01101"],
    "R": ["11110", "10001", "10001", "11110", "10100", "10010", "10001"],
    "S": ["01111", "10000", "10000", "01110", "00001", "00001", "11110"],
    "T": ["11111", "00100", "00100", "00100", "00100", "00100", "00100"],
    "U": ["10001", "10001", "10001", "10001", "10001", "10001", "01110"],
    "V": ["10001", "10001", "10001", "10001", "10001", "01010", "00100"],
    "W": ["10001", "10001", "10001", "10101", "10101", "10101", "01010"],
    "X": ["10001", "10001", "01010", "00100", "01010", "10001", "10001"],
    "Y": ["10001", "10001", "01010", "00100", "00100", "00100", "00100"],
    "Z": ["11111", "00001", "00010", "00100", "01000", "10000", "11111"],
    "0": ["01110", "10001", "10011", "10101", "11001", "10001", "01110"],
    "1": ["00100", "01100", "00100", "00100", "00100", "00100", "01110"],
    "2": ["01110", "10001", "00001", "00010", "00100", "01000", "11111"],
    "3": ["11110", "00001", "00001", "01110", "00001", "00001", "11110"],
    "4": ["00010", "00110", "01010", "10010", "11111", "00010", "00010"],
    "5": ["11111", "10000", "10000", "11110", "00001", "00001", "11110"],
    "6": ["01110", "10000", "10000", "11110", "10001", "10001", "01110"],
    "7": ["11111", "00001", "00010", "00100", "01000", "01000", "01000"],
    "8": ["01110", "10001", "10001", "01110", "10001", "10001", "01110"],
    "9": ["01110", "10001", "10001", "01111", "00001", "00001", "01110"],
    ".": ["00000", "00000", "00000", "00000", "00000", "01100", "01100"],
    "!": ["00100", "00100", "00100", "00100", "00100", "00000", "00100"],
    "'": ["00100", "00100", "01000", "00000", "00000", "00000", "00000"],
    "-": ["00000", "00000", "00000", "11111", "00000", "00000", "00000"],
    "?": ["01110", "10001", "00001", "00010", "00100", "00000", "00100"],
    " ": ["00000", "00000", "00000", "00000", "00000", "00000", "00000"],
}
GLYPHS: dict[str, tuple[int, ...]] = {ch: tuple(int(row, 2) for row in rows) for ch, rows in _RAW.items()}


def pixels(text: str) -> tuple[int, int, list[tuple[int, int]]]:
    """Bitmap points for `text`, plus the width and height of the block. Unknown marks become a box."""
    points: list[tuple[int, int]] = []
    x = 0
    for ch in text.upper():
        if ch == " ":
            x += 4
            continue
        rows = GLYPHS.get(ch, GLYPHS["?"])
        for ry, bits in enumerate(rows):
            for rx in range(5):
                if bits & (1 << (4 - rx)):
                    points.append((x + rx, ry))
        x += 6
    return max(x - 1, 0), 7, points
