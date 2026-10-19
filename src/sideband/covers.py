"""Shelf cover art. The JPEGs live in the package; nothing is downloaded at runtime.

The file name is the picture. `desert-91.jpg` is the oil-fire desert, `sky-ace-1943.jpg` is the
P-51, `corn-maze.jpg` is the pumpkin in the corn, `omi-catch.jpg` is the basket of stars,
`voice-flap.jpg` is the green microphone bird. `omi-flap-3d.jpg` and `star-dodger.jpg` match
their names too. `CoverTest` pins the file bytes so a swap cannot land quietly.

A game with no file here gets a painted fallback (the title on a gradient) drawn by the hub.
That list is `missing_covers`.
"""

from __future__ import annotations

from pathlib import Path

from sideband.platform import LIBRARY, GameSpec

DIR = Path(__file__).resolve().parent / "assets" / "covers"

# 960×540, no baked-in title. The hub draws the name underneath.
FILES: dict[str, str] = {
    "desert": "desert-91.jpg",
    "fighter": "sky-ace-1943.jpg",
    "flap": "omi-flap-3d.jpg",
    "corn": "corn-maze.jpg",
    "dodger": "star-dodger.jpg",
    "catch": "omi-catch.jpg",
    "voice": "voice-flap.jpg",
}


def cover_path(key: str) -> Path | None:
    name = FILES.get(key)
    if not name:
        return None
    path = DIR / name
    return path if path.is_file() else None


def missing_covers() -> tuple[str, ...]:
    """Games that still need a real cover. The hub draws a stand-in until one is added."""
    return tuple(spec.key for spec in LIBRARY if cover_path(spec.key) is None)


def controls_line(spec: GameSpec) -> str:
    """What can drive this game, in the order the shelf cares about."""
    look = "Mouse look" if spec.key == "desert" else "Mouse"
    return f"Keyboard · {look} · Gamepad · Omi"
