"""Voice commands. Local only, nothing recorded.

Two vocabularies: the Voice Flap game ("go left / right / up / down / stop") and the launcher's
voice menu ("open arcade", "play marble", "start recording", "close", …). Vosk (the `voice` extra)
runs with a grammar of just those words, so it answers fast and does not turn random speech into
commands. The Arcade listens with an open vocabulary instead (`free`): the local LLM reads what was said
in the menu, and `ingame_command` picks "exit game" / "pause" / "play again" out of speech during a game. PCM from the pendant (16 kHz mono s16) goes in; commands come out. `CommandSpotter`,
`menu_command` and `MenuSpotter` are the pure parts.
"""

from __future__ import annotations

import json
import queue
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from sideband.protocol import PCM_RATE_HZ

COMMANDS = ("left", "right", "up", "down", "stop", "exit", "quit")  # exit / quit leave Voice Flap
GRAMMAR = ["go", *COMMANDS, "game", "[unk]"]
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


MENU_WORDS = [
    "open", "play", "show", "start", "stop", "close", "cancel", "home", "launcher", "the",
    "recording", "record", "transcriber", "controls", "arcade", "bluetooth",
    "voice", "flap", "marble", "maze", "corn", "star", "dodger", "catch", "fighter", "ace", "plane", "sky",
    "summarize", "summarise", "summary", "that", "last", "latest", "[unk]",
]
APPS = {"transcriber": "transcriber", "controls": "controls", "arcade": "arcade", "bluetooth": "bluetooth"}
GAMES = {"marble": "corn", "maze": "corn", "corn": "corn", "star": "dodger", "dodger": "dodger", "catch": "catch", "flap": "flap",
         "fighter": "fighter", "ace": "fighter", "plane": "fighter", "sky": "fighter"}


def menu_command(text: str) -> str | None:
    """A spoken menu phrase as `open:<app>`, `play:<game>`, `record:start|stop|toggle`, `summarize`,
    `close`, `home` or `cancel`. None until the phrase names something."""
    words = [w for w in text.lower().split() if w not in ("the", "[unk]")]
    if not words:
        return None
    said = set(words)
    if "cancel" in said:
        return "cancel"
    if said & {"summarize", "summarise", "summary"}:  # before record: "summarize last recording"
        return "summarize"
    if said & {"recording", "record"}:
        if "stop" in said:
            return "record:stop"
        if "start" in said:
            return "record:start"
        return "record:toggle"
    if "close" in said:
        return "close"
    if "home" in said or "launcher" in said:
        return "home"
    if "voice" in said and "flap" in said:
        return "play:voice"
    for word in words:
        if word in APPS:
            return f"open:{APPS[word]}"
        if word in GAMES:
            return f"play:{GAMES[word]}"
    return None


@dataclass
class MenuSpotter:
    """Fires one menu command per utterance, as soon as the partial result names one."""

    fired: bool = False

    def partial(self, text: str) -> list[str]:
        command = None if self.fired else menu_command(text)
        if command:
            self.fired = True
            return [command]
        return []

    def final(self, text: str) -> list[str]:
        out = self.partial(text)
        self.fired = False
        return out


EXIT_WORDS = {"exit", "quit", "leave"}


def ingame_command(text: str) -> str | None:
    """A phrase said during an Arcade game (free-form speech): `exit`, `pause` or `go` (start, resume,
    play again). None for anything else, so chatter while playing does nothing."""
    words = text.lower().replace("'", "").split()
    said = set(words)
    if said & EXIT_WORDS or "main menu" in text.lower() or ({"back", "menu"} <= said) or ({"back", "arcade"} <= said):
        return "exit"
    if said & {"pause", "wait", "hold"}:
        return "pause"
    if said & {"resume", "continue", "again", "restart", "unpause"} or words[:2] in (["start"], ["play"], ["go"], ["lets", "go"]):
        return "go"
    return None


def model_path(support_dir: Path) -> Path:
    return support_dir / "models" / MODEL_NAME


class VoiceListener(threading.Thread):
    """Feed PCM with `feed`; `on_command(word)` and `on_text(text)` are called from this thread."""

    def __init__(
        self,
        model_dir: Path,
        on_command: Callable[[str], None],
        on_text: Callable[[str], None],
        menu: bool = False,
        free: bool = False,
    ) -> None:
        super().__init__(daemon=True)
        self.model_dir = model_dir
        self.on_command = on_command
        self.on_text = on_text
        self.free = free  # open vocabulary: every partial goes to on_text, each finished phrase to on_command
        self.grammar = MENU_WORDS if menu else GRAMMAR
        self.make_spotter = MenuSpotter if menu else CommandSpotter
        self.spotter = self.make_spotter()
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
        model = vosk.Model(str(self.model_dir))
        recognizer = vosk.KaldiRecognizer(model, PCM_RATE_HZ) if self.free else vosk.KaldiRecognizer(model, PCM_RATE_HZ, json.dumps(self.grammar))
        self.on_text("listening")
        while True:
            pcm = self._audio.get()
            if pcm is None:
                return
            if not pcm:  # reset marker
                recognizer.Reset()
                self.spotter = self.make_spotter()
                continue
            if self.free:
                if recognizer.AcceptWaveform(pcm):
                    text = json.loads(recognizer.Result()).get("text", "")
                    if text:
                        self.on_command(text)
                else:
                    text = json.loads(recognizer.PartialResult()).get("partial", "")
                    if text:
                        self.on_text(text)
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
