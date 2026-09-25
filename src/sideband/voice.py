"""Voice commands for Omi Flap 3D: "go left / right / up / down". Local only, nothing recorded.

Vosk (the `voice` extra) runs with a grammar of just the command words, so it answers fast and
does not turn random speech into commands. PCM from the pendant (16 kHz mono s16) goes in; command
words come out. `CommandSpotter` is the pure part: it turns Vosk's partial and final word lists
into commands, each spoken word firing once.
"""

from __future__ import annotations

import json
import queue
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from sideband.protocol import PCM_RATE_HZ

COMMANDS = ("left", "right", "up", "down", "stop")
GRAMMAR = ["go", *COMMANDS, "[unk]"]
MODEL_NAME = "vosk-model-small-en-us-0.15"
MODEL_URL = f"https://alphacephei.com/vosk/models/{MODEL_NAME}.zip"


class VoiceUnavailable(RuntimeError):
    pass


@dataclass
class CommandSpotter:
    """Vosk revises partial results as you speak. Fire each command word once per utterance."""

    fired: int = 0  # command words already fired in the current utterance
    heard: list[str] = field(default_factory=list)

    def partial(self, text: str) -> list[str]:
        words = [w for w in text.split() if w in COMMANDS]
        new = words[self.fired :]
        self.fired = max(self.fired, len(words))
        return new

    def final(self, text: str) -> list[str]:
        new = self.partial(text)
        self.fired = 0
        return new


def model_path(support_dir: Path) -> Path:
    return support_dir / "models" / MODEL_NAME


class VoiceListener(threading.Thread):
    """Feed PCM with `feed`; `on_command(word)` and `on_text(text)` are called from this thread."""

    def __init__(self, model_dir: Path, on_command: Callable[[str], None], on_text: Callable[[str], None]) -> None:
        super().__init__(daemon=True)
        self.model_dir = model_dir
        self.on_command = on_command
        self.on_text = on_text
        self.spotter = CommandSpotter()
        self._audio: queue.Queue[bytes | None] = queue.Queue(maxsize=200)
        self.error: str | None = None

    def feed(self, pcm: bytes) -> None:
        try:
            self._audio.put_nowait(pcm)
        except queue.Full:  # fall behind rather than build up latency
            pass

    def close(self) -> None:
        self._audio.put(None)

    def run(self) -> None:
        try:
            import vosk
        except ImportError:
            self.error = "voice needs the voice extra: pip install -e '.[voice]'"
            self.on_text(self.error)
            return
        if not self.model_dir.is_dir():
            self.error = f"voice model missing: {self.model_dir} (download {MODEL_URL})"
            self.on_text(self.error)
            return
        vosk.SetLogLevel(-1)
        recognizer = vosk.KaldiRecognizer(vosk.Model(str(self.model_dir)), PCM_RATE_HZ, json.dumps(GRAMMAR))
        self.on_text("listening")
        while True:
            pcm = self._audio.get()
            if pcm is None:
                return
            if not pcm:  # reset marker
                recognizer.Reset()
                self.spotter = CommandSpotter()
                continue
            if recognizer.AcceptWaveform(pcm):
                text = json.loads(recognizer.Result()).get("text", "")
                commands = self.spotter.final(text)
            else:
                text = json.loads(recognizer.PartialResult()).get("partial", "")
                commands = self.spotter.partial(text)
            if text:
                self.on_text(text)
            for command in commands:
                self.on_command(command)

    def reset(self) -> None:
        """Forget a half-heard utterance (after unmuting). Runs on the listener thread."""
        self._audio.put(b"")
