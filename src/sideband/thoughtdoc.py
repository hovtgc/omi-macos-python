"""A thought file read for display: the parts of a transcript Markdown file, without its markup. Pure.

The file holds a heading, a meta line, then optional blocks (folder, spoken callout, summary with
action items) and the spoken lines. The window draws each part in its own style instead of showing
the raw Markdown and HTML comments.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from sideband.buckets import BUCKET_END, BUCKET_START, bucket_of
from sideband.llm import CALLOUT_END, CALLOUT_START, SUMMARY_END, SUMMARY_START, callout_of, summary_of


@dataclass
class ThoughtDoc:
    heading: str = ""
    meta: str = ""
    title: str = ""  # from the folder block, when filed
    folder: tuple[str, ...] = ()
    callout: str = ""
    summary: str = ""  # the prose under "## Summary"
    actions: list[tuple[bool, str]] = field(default_factory=list)
    lines: list[tuple[str, str]] = field(default_factory=list)  # (mm:ss, text)
    typed: bool = False

    @property
    def said(self) -> str:
        return " ".join(text for _stamp, text in self.lines)

    def snippet(self, chars: int = 140) -> str:
        text = self.callout or self.said or self.meta
        return text if len(text) <= chars else text[:chars].rsplit(" ", 1)[0] + "…"


def _strip_blocks(markdown: str) -> str:
    for start, end in ((BUCKET_START, BUCKET_END), (CALLOUT_START, CALLOUT_END), (SUMMARY_START, SUMMARY_END)):
        while start in markdown and end in markdown:
            head, rest = markdown.split(start, 1)
            markdown = head + rest.split(end, 1)[1]
    return markdown


def parse_thought(markdown: str) -> ThoughtDoc:
    doc = ThoughtDoc()
    filed = bucket_of(markdown)
    if filed is not None:
        doc.folder, doc.title = filed.folder, filed.title
    doc.callout = callout_of(markdown) or ""
    summary = summary_of(markdown) or ""
    section = ""
    prose: list[str] = []
    for line in summary.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            section = stripped.lstrip("# ").lower()
        elif section.startswith("action"):
            if stripped.startswith(("- [", "* [")):
                done = stripped[3:4].lower() == "x"
                doc.actions.append((done, stripped.split("]", 1)[1].strip()))
            elif stripped.startswith(("-", "*")) and stripped.strip("-* .").lower() not in ("none", ""):
                doc.actions.append((False, stripped.lstrip("-* ").strip()))
        elif stripped:
            prose.append(stripped)
    doc.summary = " ".join(prose)
    for line in _strip_blocks(markdown).splitlines():
        if line.startswith("# "):
            doc.heading = line[2:].strip()
            doc.typed = doc.heading.lower().startswith("typed")
        elif line.startswith("**[") and "]**" in line:
            stamp, text = line[3:].split("]**", 1)
            doc.lines.append((stamp, text.strip()))
        elif line.strip() and not doc.meta and not line.startswith(("_", "<!--")):
            doc.meta = line.strip()
    return doc


def friendly_when(started: float, now: float | None = None) -> str:
    """'Today 10:02', 'Yesterday 18:40', 'Mon 10:02' this week, else '28 Sep'."""
    now = time.time() if now is None else now
    then, today = time.localtime(started), time.localtime(now)
    days = (time.mktime(today[:3] + (0, 0, 0, 0, 0, -1)) - time.mktime(then[:3] + (0, 0, 0, 0, 0, -1))) / 86400
    clock = time.strftime("%H:%M", then)
    if days < 1:
        return f"Today {clock}"
    if days < 2:
        return f"Yesterday {clock}"
    if days < 7:
        return time.strftime("%a ", then) + clock
    return time.strftime("%-d %b" if then.tm_year == today.tm_year else "%-d %b %Y", then)
