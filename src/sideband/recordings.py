"""Recordings on disk: naming, listing, transcripts, and the 24-hour audio limit. Pure file work.

Each recording is `omi-YYYYmmdd-HHMMSS.wav` in the recordings folder, with its transcript next to
it as `omi-YYYYmmdd-HHMMSS.md`. Audio older than `AUDIO_TTL_S` is deleted by `sweep`; transcripts
are kept. The start time comes from the file name, so copying or touching a file does not change
when it expires.
"""

from __future__ import annotations

import time
import wave
from dataclasses import dataclass
from pathlib import Path

AUDIO_TTL_S = 24 * 3600
STAMP = "%Y%m%d-%H%M%S"
PREFIX = "omi-"


@dataclass(frozen=True)
class Recording:
    stem: str
    started: float  # epoch seconds, from the name
    audio: Path | None  # None once swept
    transcript: Path | None
    seconds: float | None  # audio length, when the audio is still there

    @property
    def label(self) -> str:
        return time.strftime("%a %d %b %H:%M:%S", time.localtime(self.started))


def new_path(folder: Path, now: float) -> Path:
    """A fresh recording path. Adds a suffix if two start within the same second."""
    base = PREFIX + time.strftime(STAMP, time.localtime(now))
    path, n = folder / f"{base}.wav", 1
    while path.exists() or path.with_suffix(".md").exists():
        n += 1
        path = folder / f"{base}-{n}.wav"
    return path


def started_at(stem: str) -> float | None:
    if not stem.startswith(PREFIX):
        return None
    try:
        return time.mktime(time.strptime(stem[len(PREFIX) : len(PREFIX) + 15], STAMP))
    except ValueError:
        return None


def wav_seconds(path: Path) -> float | None:
    try:
        with wave.open(str(path)) as handle:
            return handle.getnframes() / handle.getframerate()
    except (OSError, EOFError, wave.Error):
        return None


def list_recordings(folder: Path) -> list[Recording]:
    """Newest first. A recording shows up while it has audio or a transcript."""
    if not folder.is_dir():
        return []
    stems: dict[str, float] = {}
    for path in folder.iterdir():
        if path.suffix in (".wav", ".md"):
            started = started_at(path.stem)
            if started is not None:
                stems[path.stem] = started
    rows = []
    for stem, started in stems.items():
        audio, transcript = folder / f"{stem}.wav", folder / f"{stem}.md"
        has_audio = audio.exists()
        rows.append(
            Recording(
                stem,
                started,
                audio if has_audio else None,
                transcript if transcript.exists() else None,
                wav_seconds(audio) if has_audio else None,
            )
        )
    return sorted(rows, key=lambda r: r.started, reverse=True)


def expired_audio(folder: Path, now: float, ttl_s: float = AUDIO_TTL_S, keep: set[Path] | None = None) -> list[Path]:
    """Audio files whose recording started more than `ttl_s` ago. `keep` protects a file in use."""
    keep = keep or set()
    out = []
    for rec in list_recordings(folder):
        if rec.audio is not None and rec.audio not in keep and now - rec.started > ttl_s:
            out.append(rec.audio)
    return out


def sweep(folder: Path, now: float, ttl_s: float = AUDIO_TTL_S, keep: set[Path] | None = None) -> list[Path]:
    """Delete expired audio. Transcripts stay. Returns what was removed."""
    removed = []
    for path in expired_audio(folder, now, ttl_s, keep):
        try:
            path.unlink()
            removed.append(path)
        except OSError:
            pass
    return removed


def _clock(seconds: float) -> str:
    whole = int(seconds)
    return f"{whole // 60:02d}:{whole % 60:02d}"


def transcript_markdown(started: float, seconds: float, segments: list[tuple[float, float, str]]) -> str:
    """Transcript file body: a heading with the start time, then one timestamped line per segment."""
    title = time.strftime("%A %d %B %Y, %H:%M", time.localtime(started))
    lines = [f"# Omi recording, {title}", "", f"Length {_clock(seconds)}. Transcribed on this Mac; audio is deleted after 24 hours.", ""]
    spoken = [(a, text.strip()) for a, _b, text in segments if text.strip()]
    if not spoken:
        lines.append("_Nothing intelligible was heard._")
    for at, text in spoken:
        lines.append(f"**[{_clock(at)}]** {text}  ")
    return "\n".join(lines).rstrip() + "\n"


def write_transcript(audio: Path, started: float, seconds: float, segments: list[tuple[float, float, str]]) -> Path:
    path = audio.with_suffix(".md")
    path.write_text(transcript_markdown(started, seconds, segments), encoding="utf-8")
    return path
