"""The thought map: every thought (a recording or a typed note) is filed into a folder 2 to 3 levels deep.

The model reads the thought plus the folders that already exist and replies with a folder path and a
short title. Everything here is pure: the prompt, parsing the reply, storing the filing in the
transcript file, and the folder tree the window draws. The transcript files are the only store, so
the map is rebuilt from disk every time and a file moved by hand keeps its folder.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path

BUCKET_START, BUCKET_END = "<!-- bucket -->", "<!-- /bucket -->"
MAX_DEPTH = 3
NAME_CHARS = 32
TITLE_WORDS = 10
THOUGHT_CHARS = 6_000  # the start of a long recording says enough about where it goes
SEP = " › "

Path_ = tuple[str, ...]


@dataclass(frozen=True)
class Filed:
    folder: Path_
    title: str


def bucket_messages(text: str, known: list[Path_]) -> list[dict[str, str]]:
    """Ask where one thought belongs. `known` is every folder already on the map."""
    listing = "\n".join("- " + " / ".join(p) for p in known[:80]) or "(none yet: you are starting the map)"
    return [
        {
            "role": "system",
            "content": (
                "You file the owner's spoken thoughts into a map of folders, like a tidy notes app. "
                "Folders go 2 or 3 levels deep: a broad area, then a topic, then a specific thread. "
                "Use the third level whenever the thought names a specific client, project, product, person or event, "
                "so related thoughts gather there. Examples: Work / Clients / Acme Rebrand, Work / Hiring / Designer Role, "
                "Health / Running, Home / Renovation / Kitchen, Ideas / Side Projects / Recipe App, Family / Kids / School.\n"
                "Rules:\n"
                "- Reuse an existing folder whenever the thought fits it; spell it exactly as listed.\n"
                "- Make a new folder only when nothing fits, and hang it under an existing area when you can.\n"
                "- Folder names are 1 to 3 words, Title Case, no dates, no emoji.\n"
                "- The title is 3 to 8 plain words that say what the thought is about.\n"
                "Reply with exactly two lines, nothing else:\n"
                "Folder: <Area> / <Topic> / <Thread>\n"
                "Title: <title>\n\n"
                f"Folders on the map now:\n{listing}"
            ),
        },
        {"role": "user", "content": f"Thought:\n{text[:THOUGHT_CHARS]}"},
    ]


def _clean_name(name: str) -> str:
    name = re.sub(r"[*_#`\"“”<>\[\]{}|]", "", name)
    name = re.sub(r"[^\w\s&'+.,-]", "", name)  # drops emoji and stray symbols
    name = " ".join(name.split()).strip(" .,-")[:NAME_CHARS].strip()
    return name[:1].upper() + name[1:]


def split_path(text: str) -> Path_:
    parts = re.split(r"\s*(?:/|›|>|»|\\|→)\s*", text)
    return tuple(p for p in (_clean_name(part) for part in parts) if p)


def match_known(folder: Path_, known: list[Path_]) -> Path_:
    """Reuse the spelling of folders already on the map, so 'work / hiring' lands in 'Work / Hiring'."""
    out: list[str] = []
    for depth, name in enumerate(folder):
        prefix = tuple(out)
        siblings = {p[depth] for p in known if len(p) > depth and p[:depth] == prefix}
        out.append(next((s for s in siblings if s.lower() == name.lower()), name))
    return tuple(out)


def parse_bucket(reply: str, known: list[Path_]) -> Filed | None:
    """The model's two lines as a `Filed`, or None when it gave no usable folder."""
    folder: Path_ = ()
    title = ""
    for line in reply.strip().splitlines():
        key, _, value = line.partition(":")
        key = key.strip(" *-#").lower()
        if key == "folder" and not folder:
            folder = split_path(value)
        elif key == "title" and not title:
            title = clean_title(value)
    if not folder:  # a bare path on the first line still counts
        first = reply.strip().splitlines()[0] if reply.strip() else ""
        folder = split_path(first) if "/" in first else ()
    if not folder:
        return None
    return Filed(match_known(folder[:MAX_DEPTH], known), title)


def clean_title(text: str) -> str:
    text = re.sub(r"[*_#`\"“”\[\]|]", "", text)
    words = text.split()[:TITLE_WORDS]
    return " ".join(words).strip(" .,:;-")


def with_bucket(markdown: str, filed: Filed) -> str:
    """Store the filing under the heading lines, before the callout, summary and spoken lines."""
    lines = [f"📁 {SEP.join(filed.folder)}"] + ([f"📝 {filed.title}"] if filed.title else [])
    block = f"{BUCKET_START}\n" + "\n".join(lines) + f"\n{BUCKET_END}\n"
    if BUCKET_START in markdown and BUCKET_END in markdown:
        head, rest = markdown.split(BUCKET_START, 1)
        tail = rest.split(BUCKET_END, 1)[1].lstrip("\n")
        return head + block + "\n" + tail
    rows = markdown.splitlines(keepends=True)
    cut = next((i for i, row in enumerate(rows) if row.startswith(("**[", "_Nothing", "<!-- "))), len(rows))
    return "".join(rows[:cut]) + block + "\n" + "".join(rows[cut:])


def bucket_of(markdown: str) -> Filed | None:
    if BUCKET_START not in markdown or BUCKET_END not in markdown:
        return None
    body = markdown.split(BUCKET_START, 1)[1].split(BUCKET_END, 1)[0]
    folder: Path_ = ()
    title = ""
    for line in body.strip().splitlines():
        if line.startswith("📁"):
            folder = tuple(p.strip() for p in line[1:].split(SEP.strip()) if p.strip())
        elif line.startswith("📝"):
            title = line[1:].strip()
    return Filed(folder, title) if folder else None


def read_bucket(path: Path | None) -> Filed | None:
    if path is None:
        return None
    try:
        return bucket_of(path.read_text(encoding="utf-8"))
    except OSError:
        return None


def all_folders(folders: list[Path_]) -> list[Path_]:
    """Every folder and its parents, sorted, for the prompt and the tree."""
    out: set[Path_] = set()
    for folder in folders:
        for depth in range(1, len(folder) + 1):
            out.add(folder[:depth])
    return sorted(out, key=lambda p: tuple(s.lower() for s in p))


def folder_counts(folders: list[Path_]) -> dict[Path_, int]:
    """Thoughts in each folder, counting everything below it."""
    counts: dict[Path_, int] = {}
    for folder in folders:
        for depth in range(1, len(folder) + 1):
            counts[folder[:depth]] = counts.get(folder[:depth], 0) + 1
    return counts


def is_new_folder(folder: Path_, known: list[Path_]) -> Path_ | None:
    """The shallowest part of `folder` that was not on the map yet, or None if it all existed."""
    have = set(all_folders(known))
    return next((folder[:d] for d in range(1, len(folder) + 1) if folder[:d] not in have), None)


def note_markdown(started: float, text: str) -> str:
    """A typed thought, in the same shape as a transcript so the rest of the app treats it alike."""
    title = time.strftime("%A %d %B %Y, %H:%M", time.localtime(started))
    body = [f"**[00:00]** {line.strip()}  " for line in text.strip().splitlines() if line.strip()]
    return "\n".join([f"# Typed thought, {title}", "", "Typed on this Mac.", "", *body]).rstrip() + "\n"
