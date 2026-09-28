"""A local LLM over your transcripts: summaries with action items, and questions. Nothing leaves the Mac.

MLX on Apple silicon (the `llm` extra) runs a small instruct model fetched once from Hugging Face and
cached. Prompt building, context selection and writing the summary into the transcript file are pure
and tested; `LocalLLM` is one worker thread that streams tokens back.
"""

from __future__ import annotations

import os
import queue
import threading
import time
from dataclasses import dataclass
from typing import Callable

MODEL = "mlx-community/Qwen2.5-7B-Instruct-4bit"
SUMMARY_START, SUMMARY_END = "<!-- summary -->", "<!-- /summary -->"
CALLOUT_START, CALLOUT_END = "<!-- callout -->", "<!-- /callout -->"
CALLOUT_WORDS = 60
CONTEXT_CHARS = 18_000  # about 4.5k tokens of transcripts per question keeps answers quick

SYSTEM = (
    "You help the owner of an Omi pendant with their own voice recordings, transcribed on their Mac. "
    "Use only what the transcripts say. If they do not say, answer that you could not find it. "
    "Be brief and concrete. When you point at a moment, copy the [mm:ss] time of the exact line you used."
)


def spoken_lines(markdown: str) -> list[str]:
    """`[mm:ss] text` for each spoken line of a transcript file."""
    out = []
    for line in markdown.splitlines():
        if line.startswith("**[") and "]**" in line:
            stamp, text = line[3:].split("]**", 1)
            out.append(f"[{stamp}] {text.strip()}")
    return out


def transcript_text(markdown: str) -> str:
    return "\n".join(spoken_lines(markdown))


def title(markdown: str) -> str:
    first = markdown.splitlines()[0] if markdown else ""
    return first.lstrip("# ").strip() or "Recording"


def summary_messages(text: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": SYSTEM},
        {
            "role": "user",
            "content": (
                "Summarise this recording. Reply in Markdown with exactly two sections:\n"
                "## Summary\n2 to 4 sentences.\n"
                "## Action items\nOne '- [ ] ' line per task, promise or follow-up that was said, "
                "with who and when if mentioned. Only if there are no tasks at all, write the single line '- none'.\n\n"
                f"Transcript:\n{text}"
            ),
        },
    ]


def callout_messages(text: str) -> list[dict[str, str]]:
    """A summary written to be heard: spoken right after a recording, so it must work by ear alone."""
    return [
        {
            "role": "system",
            "content": (
                "You write short spoken callouts of the owner's own voice recordings. They are read aloud by "
                "a text-to-speech voice right after the recording ends, so write for the ear:\n"
                "- One to three short sentences, at most 60 words.\n"
                "- Start with the main point. Then the specifics that matter: names, numbers, dates, decisions.\n"
                "- If the owner promised or planned to do something, end with it, like: You said you'd send Dana the notes by Friday.\n"
                "- Talk to the owner as 'you'. Plain spoken words: no lists, bullet points, headings, symbols, emoji or quotes.\n"
                "- Say numbers the way a person would: 18 dollars, the third of October, 400 units.\n"
                "- Use only what was said. Never invent. Do not start with 'In this recording' or 'The speaker'.\n"
                "- If nothing meaningful was said, reply exactly: Nothing much in that one."
            ),
        },
        {"role": "user", "content": f"Recording:\n{text}"},
    ]


def clean_callout(text: str, max_words: int = CALLOUT_WORDS) -> str:
    """Make a model reply safe to speak: no markdown or list marks, one paragraph, bounded length."""
    import re

    text = re.sub(r"[*_#`>\[\]|]", "", text)
    text = re.sub(r"^\s*([-•]|\d+[.)])\s+", "", text, flags=re.MULTILINE)
    text = " ".join(text.split())
    words = text.split()
    if len(words) > max_words:
        cut = " ".join(words[:max_words])
        end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
        text = cut[: end + 1] if end > 0 else cut.rstrip(",;:") + "."
    return text


def with_callout(markdown: str, callout: str) -> str:
    """Store the spoken callout as a quote under the heading lines, replacing an older one."""
    block = f"{CALLOUT_START}\n> 🔊 {callout.strip()}\n{CALLOUT_END}\n"
    if CALLOUT_START in markdown and CALLOUT_END in markdown:
        head, rest = markdown.split(CALLOUT_START, 1)
        tail = rest.split(CALLOUT_END, 1)[1].lstrip("\n")
        return head + block + "\n" + tail
    lines = markdown.splitlines(keepends=True)
    cut = next(
        (i for i, line in enumerate(lines) if line.startswith(("**[", "_Nothing", SUMMARY_START))),
        len(lines),
    )
    return "".join(lines[:cut]) + block + "\n" + "".join(lines[cut:])


def callout_of(markdown: str) -> str | None:
    if CALLOUT_START not in markdown or CALLOUT_END not in markdown:
        return None
    return markdown.split(CALLOUT_START, 1)[1].split(CALLOUT_END, 1)[0].strip().removeprefix("> 🔊").strip()


def ask_messages(question: str, text: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": f"Transcript:\n{text}\n\nQuestion: {question}"},
    ]


@dataclass(frozen=True)
class Doc:
    name: str  # heading of the transcript, with its date
    text: str


def pick_context(docs: list[Doc], budget: int = CONTEXT_CHARS) -> list[Doc]:
    """Newest first until the budget is spent; the last one that fits partly is cut at a line."""
    picked, used = [], 0
    for doc in docs:
        room = budget - used - len(doc.name) - 8
        if room <= 200:
            break
        text = doc.text if len(doc.text) <= room else doc.text[:room].rsplit("\n", 1)[0] + "\n[…]"
        picked.append(Doc(doc.name, text))
        used += len(doc.name) + len(text) + 8
    return picked


def ask_all_messages(question: str, docs: list[Doc]) -> list[dict[str, str]]:
    body = "\n\n".join(f"### {d.name}\n{d.text}" for d in docs) or "(no transcripts yet)"
    return [
        {"role": "system", "content": SYSTEM + " Several recordings follow, newest first; say which one you mean."},
        {"role": "user", "content": f"Recordings:\n{body}\n\nQuestion: {question}"},
    ]


def clean_summary(summary: str) -> str:
    """Drop a stray '- none' that small models add after real action items."""
    lines = summary.strip().splitlines()
    if any(line.lstrip().startswith("- [") for line in lines):
        lines = [line for line in lines if line.strip().lower() not in ("- none", "- none.")]
    return "\n".join(lines)


def with_summary(markdown: str, summary: str) -> str:
    """Put (or replace) the summary block after the heading lines, before the spoken lines."""
    block = f"{SUMMARY_START}\n{summary.strip()}\n{SUMMARY_END}\n"
    if SUMMARY_START in markdown and SUMMARY_END in markdown:
        head, rest = markdown.split(SUMMARY_START, 1)
        tail = rest.split(SUMMARY_END, 1)[1].lstrip("\n")
        return head + block + "\n" + tail
    lines = markdown.splitlines(keepends=True)
    cut = next((i for i, line in enumerate(lines) if line.startswith("**[") or line.startswith("_Nothing")), len(lines))
    return "".join(lines[:cut]) + block + "\n" + "".join(lines[cut:])


def summary_of(markdown: str) -> str | None:
    if SUMMARY_START not in markdown or SUMMARY_END not in markdown:
        return None
    return markdown.split(SUMMARY_START, 1)[1].split(SUMMARY_END, 1)[0].strip()


ARCADE_ACTIONS = ("recalibrate", "close", "help", "none")
THIS_WORDS = {"this", "that", "it", "one", "again", "selected", "highlighted"}


def arcade_messages(heard: str, games: list[tuple[str, str, str]], selected: str | None) -> list[dict[str, str]]:
    """Ask which Arcade action a spoken request means. `games` is (key, title, what it is)."""
    listing = "\n".join(f"- {key}: {title.title()} ({how})" for key, title, how in games)
    focus = next((title.title() for key, title, _how in games if key == selected), None)
    return [
        {
            "role": "system",
            "content": (
                "You are the voice menu of the Omi Arcade, a set of small games. The player said something out loud. "
                "Speech recognition is rough and often mishears game names (sky ace may come out as 'skies', "
                "'a's', 'sky a' or 'ski ace'; corn maze as 'con maze' or 'corn may'), so match by sound and meaning.\n"
                f"Games:\n{listing}\n"
                f"Highlighted game: {focus or 'none'}. Words like 'this', 'that', 'it', 'this one' or 'again' mean the highlighted game.\n"
                "Reply with exactly one line, nothing else:\n"
                "play <key>  (start that game)\n"
                "show <key>  (only when they ask a question about a game; just naming a game means play it)\n"
                "recalibrate  (fix, reset or calibrate the tilt controls)\n"
                "close  (leave or close the arcade)\n"
                "help  (they ask what they can say or which games there are)\n"
                "none  (anything else)\n"
                "Examples: 'play a's' -> play fighter. 'I want to shoot some planes' -> play fighter. "
                "'the pumpkin one' -> play corn. 'what's star dodger' -> show dodger. 'play this' -> play <the highlighted key>. "
                "'the controls feel off' -> recalibrate. 'what can I play' -> help. 'nice weather' -> none."
            ),
        },
        {"role": "user", "content": heard},
    ]


def parse_arcade(reply: str, keys: list[str], selected: str | None) -> str:
    """The model's line as `play:<key>`, `show:<key>`, one of ARCADE_ACTIONS, or `none`."""
    words = reply.strip().lower().replace("<", " ").replace(">", " ").replace(":", " ").split()
    if not words:
        return "none"
    verb = words[0]
    if verb in ("play", "show"):
        key = next((w for w in words[1:] if w in keys), None)
        if key is None and selected in keys and (len(words) == 1 or set(words[1:]) & THIS_WORDS):
            key = selected
        return f"{verb}:{key}" if key else "none"
    return verb if verb in ARCADE_ACTIONS else "none"


def guess_arcade(heard: str, names: dict[str, str], selected: str | None) -> str:
    """No model at hand: keywords. `names` maps spoken words (sky, corn, dodger…) to game keys."""
    words = heard.lower().replace("'", "").split()
    said = set(words)
    if any("calibrat" in w for w in words) or {"reset", "fix"} & said:
        return "recalibrate"
    if said & {"close", "quit", "exit", "leave"}:
        return "close"
    if "help" in said or {"what", "can"} <= said:
        return "help"
    for word in words:
        if word in names:
            return f"play:{names[word]}"
    this = bool(said & THIS_WORDS) or words == ["play"]
    if selected and said & {"play", "start", "go"} and this:
        return f"play:{selected}"
    return "none"


@dataclass
class Job:
    messages: list[dict[str, str]]
    on_token: Callable[[str], None]
    on_done: Callable[[str, str], None]  # full text, error ("" when fine)
    max_tokens: int = 600


class LocalLLM(threading.Thread):
    """One model, loaded on first use. Jobs run in order; tokens stream through the job's callbacks."""

    def __init__(self, on_status: Callable[[str], None], model: str = MODEL) -> None:
        super().__init__(daemon=True)
        self.model_name = model
        self.on_status = on_status
        self.jobs: queue.Queue[Job | None] = queue.Queue()
        self.busy = False
        self.ready = False

    def submit(self, job: Job) -> None:
        self.jobs.put(job)

    def close(self) -> None:
        self.jobs.put(None)

    def run(self) -> None:
        from sideband.transcribe import _cached

        if _cached(self.model_name):
            os.environ.setdefault("HF_HUB_OFFLINE", "1")
        try:
            from mlx_lm import load, stream_generate
            from mlx_lm.sample_utils import make_sampler
        except ImportError:
            error = "the assistant needs the llm extra: pip install -e '.[llm]'"
            self.on_status(error)
            while (job := self.jobs.get()) is not None:
                job.on_done("", error)
            return
        model = tokenizer = None
        sampler = make_sampler(temp=0.2)
        while (job := self.jobs.get()) is not None:
            self.busy = True
            try:
                if model is None:
                    self.on_status(f"loading {self.model_name.split('/')[-1]}…")
                    started = time.monotonic()
                    model, tokenizer = load(self.model_name)
                    self.ready = True
                    self.on_status(f"assistant ready ({time.monotonic() - started:.0f}s to load)")
                prompt = tokenizer.apply_chat_template(job.messages, add_generation_prompt=True, tokenize=False)
                text = ""
                for piece in stream_generate(model, tokenizer, prompt, max_tokens=job.max_tokens, sampler=sampler):
                    text += piece.text
                    job.on_token(piece.text)
                job.on_done(text.strip(), "")
            except Exception as exc:
                job.on_done("", f"{type(exc).__name__}: {exc}")
            finally:
                self.busy = False
