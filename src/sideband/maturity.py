"""Maturing ideas: the AI reads every thought in a folder and suggests the step from thought to action.

A folder moves through stages: seed (a passing thought), growing (it keeps coming back, taking shape),
ready (clear enough to act on), then action once the owner turns the suggested next step into a
reminder. The model's read of a folder is kept in `maturity.json` next to the thoughts, keyed by the
folder path, with how many thoughts it had seen so it can mature again when the folder grows. Pure.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

STAGES = {"seed": "🌱", "growing": "🌿", "ready": "🌳", "action": "✅"}
MIN_THOUGHTS = 3  # a folder matures on its own once it holds this many thoughts
FILE = "maturity.json"
Folder = tuple[str, ...]


@dataclass(frozen=True)
class Maturity:
    stage: str  # one of STAGES
    next_action: str
    text: str  # the model's full read, Markdown
    count: int = 0  # thoughts in the folder when it was read
    at: float = 0.0
    acted: str = ""  # the action the owner took, once they took it

    @property
    def badge(self) -> str:
        return STAGES.get(self.stage, "🌱")


def key(folder: Folder) -> str:
    return " / ".join(folder)


def mature_messages(folder: Folder, thoughts: list[tuple[str, str]]) -> list[dict[str, str]]:
    """`thoughts` is (when, text), oldest first, so the model sees how the idea grew."""
    body = "\n\n".join(f"### {when}\n{text}" for when, text in thoughts) or "(empty)"
    return [
        {
            "role": "system",
            "content": (
                "You help the owner turn their own spoken thoughts into action. Below are all their thoughts in one folder "
                "of their thought map, oldest first. Read how the idea has grown, then say how mature it is and the single "
                "best next step. Use only what they said; do not invent facts, names or dates.\n"
                "Stages: seed (a passing thought, still vague), growing (it keeps coming back and is taking shape), "
                "ready (clear enough to act on now).\n"
                "Reply in exactly this shape, nothing else:\n"
                "Stage: <seed|growing|ready>\n"
                "Where it stands: <one or two sentences>\n"
                "Next action: <one concrete step they can do in under an hour, starting with a verb, naming who or what>\n"
                "Why now: <one sentence>\n"
                "Open questions:\n- <question>\n- <question>"
            ),
        },
        {"role": "user", "content": f"Folder: {key(folder)}\n\nThoughts:\n{body}"},
    ]


def field(reply: str, name: str) -> str:
    match = re.search(rf"^[\s*#-]*{name}\s*\**\s*:\s*\**\s*(.+)$", reply, flags=re.IGNORECASE | re.MULTILINE)
    return match.group(1).strip().strip("*_ ") if match else ""


def parse_maturity(reply: str, count: int, at: float) -> Maturity | None:
    """The model's read as a `Maturity`, or None when it gave no next action."""
    stage_word = field(reply, "stage").lower()
    stage = next((s for s in ("seed", "growing", "ready") if s in stage_word), "seed")
    action = field(reply, "next action")
    if not action:
        return None
    return Maturity(stage, action, reply.strip(), count, at)


def needs_maturing(entry: Maturity | None, count: int, minimum: int = MIN_THOUGHTS) -> bool:
    """Mature a folder on its own once it is big enough, and again each time it gains a thought."""
    if count < minimum:
        return False
    return entry is None or (count > entry.count and not entry.acted)


def load(folder: Path) -> dict[str, Maturity]:
    try:
        raw = json.loads((folder / FILE).read_text(encoding="utf-8"))
        return {k: Maturity(**v) for k, v in raw.items()}
    except (OSError, ValueError, TypeError):
        return {}


def save(folder: Path, entries: dict[str, Maturity]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    data = {k: asdict(v) for k, v in sorted(entries.items())}
    (folder / FILE).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def acted(entry: Maturity, action: str) -> Maturity:
    return Maturity("action", entry.next_action, entry.text, entry.count, entry.at, action)
