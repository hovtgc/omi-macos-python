"""Speak callouts aloud with macOS's built-in speech (`say`). Offline; nothing leaves the Mac.

`pick_voice` prefers a Premium or Enhanced English voice when one is installed (System Settings →
Accessibility → Spoken Content → Manage Voices), then the standard US voice.
"""

from __future__ import annotations

import re
import subprocess

FALLBACKS = ("Samantha", "Daniel", "Karen", "Moira", "Tessa", "Rishi")
RATE_WPM = 190  # a little quicker than the default 175; callouts are short


def voices(listing: str) -> list[tuple[str, str]]:
    """(name, locale) from `say -v '?'` output."""
    out = []
    for line in listing.splitlines():
        match = re.match(r"^(.+?)\s+([a-z]{2}_[A-Z]{2})\s+#", line)
        if match:
            out.append((match.group(1).strip(), match.group(2)))
    return out


def pick_voice(listing: str) -> str | None:
    """The best English voice in a `say -v '?'` listing, or None to use the system default."""
    english = [(name, locale) for name, locale in voices(listing) if locale.startswith("en_")]
    for quality in ("Premium", "Enhanced"):
        for prefer_us in (True, False):
            for name, locale in english:
                if quality in name and (locale == "en_US") == prefer_us:
                    return name
    names = {name for name, _ in english}
    return next((name for name in FALLBACKS if name in names), None)


class Speaker:
    """One utterance at a time; a new one or `stop()` cuts off the current one."""

    def __init__(self, voice: str | None = None, rate: int = RATE_WPM) -> None:
        self.rate = rate
        self.voice = voice
        self._proc: subprocess.Popen | None = None

    def _voice(self) -> str | None:
        if self.voice is None:
            try:
                listing = subprocess.run(["say", "-v", "?"], capture_output=True, text=True, timeout=10).stdout
            except (OSError, subprocess.TimeoutExpired):
                listing = ""
            self.voice = pick_voice(listing) or ""
        return self.voice or None

    def speak(self, text: str) -> None:
        self.stop()
        voice = self._voice()
        command = ["say", "-r", str(self.rate)] + (["-v", voice] if voice else []) + [text]
        self._proc = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    @property
    def speaking(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def stop(self) -> None:
        if self.speaking:
            assert self._proc is not None
            self._proc.terminate()
        self._proc = None
