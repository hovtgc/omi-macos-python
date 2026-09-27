"""Local transcription of finished recordings with Whisper on Apple silicon (the `transcribe` extra).

The model is fetched once from Hugging Face and cached; audio never leaves the Mac. One worker thread
transcribes recordings in the order they finish.
"""

from __future__ import annotations

import os
import queue
import threading
import wave
from pathlib import Path
from typing import Callable

from sideband.recordings import started_at, write_transcript

MODEL = "mlx-community/whisper-large-v3-turbo"


def read_pcm(path: Path) -> tuple[bytes, int]:
    with wave.open(str(path)) as handle:
        if handle.getsampwidth() != 2 or handle.getnchannels() != 1:
            raise ValueError(f"{path.name}: expected 16-bit mono")
        return handle.readframes(handle.getnframes()), handle.getframerate()


def _cached(model: str) -> bool:
    hub = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")) / "hub"
    snapshots = hub / f"models--{model.replace('/', '--')}" / "snapshots"
    return snapshots.is_dir() and any(snapshots.iterdir())


class Transcriber(threading.Thread):
    """`submit(wav)`; `on_done(wav, transcript_or_None, message)` is called from this thread."""

    def __init__(self, on_done: Callable[[Path, Path | None, str], None], model: str = MODEL) -> None:
        super().__init__(daemon=True)
        self.model = model
        self.on_done = on_done
        self.jobs: queue.Queue[Path | None] = queue.Queue()
        self.busy: Path | None = None

    def submit(self, wav: Path) -> None:
        self.jobs.put(wav)

    def close(self) -> None:
        self.jobs.put(None)

    def pending(self) -> int:
        return self.jobs.qsize() + (1 if self.busy else 0)

    def run(self) -> None:
        if _cached(self.model):  # once the model is on disk, never go online for it
            os.environ.setdefault("HF_HUB_OFFLINE", "1")
        try:
            import mlx_whisper
            import numpy as np
        except ImportError:
            message = "transcription needs the transcribe extra: pip install -e '.[transcribe]'"
            while (job := self.jobs.get()) is not None:
                self.on_done(job, None, message)
            return
        while (wav := self.jobs.get()) is not None:
            self.busy = wav
            try:
                pcm, rate = read_pcm(wav)
                seconds = len(pcm) / 2 / rate
                if seconds < 0.5:
                    segments: list[tuple[float, float, str]] = []
                else:
                    audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
                    result = mlx_whisper.transcribe(
                        audio, path_or_hf_repo=self.model, condition_on_previous_text=False, verbose=None
                    )
                    segments = [(float(s["start"]), float(s["end"]), str(s["text"])) for s in result.get("segments", [])]
                started = started_at(wav.stem) or wav.stat().st_mtime
                path = write_transcript(wav, started, seconds, segments)
                words = sum(len(t.split()) for _a, _b, t in segments)
                self.on_done(wav, path, f"{words} words from {int(seconds)}s")
            except Exception as exc:
                self.on_done(wav, None, f"transcription failed: {exc}")
            finally:
                self.busy = None
