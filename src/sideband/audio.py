"""Optional WAV capture. Feed it payloads from `protocol.strip_packet`. Nothing leaves the Mac.

PCM codecs need only the standard library. Opus needs the `audio` extra (PyAV).
"""

from __future__ import annotations

import threading
import wave
from pathlib import Path

from sideband.protocol import PCM_RATE_HZ


class AudioUnavailable(RuntimeError):
    pass


class _Pcm:
    def decode(self, payload: bytes) -> bytes:
        return payload[: len(payload) - len(payload) % 2]


class _Opus:
    def __init__(self) -> None:
        try:
            import av
        except ImportError as exc:
            raise AudioUnavailable("Opus capture needs the audio extra: pip install -e '.[audio]'") from exc
        self._av = av
        self._ctx = av.CodecContext.create("libopus", "r")
        self._ctx.sample_rate = PCM_RATE_HZ
        self._ctx.layout = "mono"
        self._resample = av.AudioResampler(format="s16", layout="mono", rate=PCM_RATE_HZ)

    def decode(self, payload: bytes) -> bytes:
        out = bytearray()
        for frame in self._ctx.decode(self._av.Packet(payload)):
            for pcm in self._resample.resample(frame):
                out += bytes(pcm.planes[0])[: pcm.samples * 2]
        return bytes(out)


def decoder_for(codec: str) -> _Pcm | _Opus:
    if codec.startswith("opus"):
        return _Opus()
    if codec == "pcm16-16k":
        return _Pcm()
    raise AudioUnavailable(f"no WAV decoder for codec {codec}")


class WavSink:
    """16-bit mono WAV at 16 kHz. Bad frames are counted and skipped, never fatal."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.frames = 0
        self.bad = 0
        self._samples = 0
        self._decoder: _Pcm | _Opus | None = None
        self._wav: wave.Wave_write | None = None
        self._lock = threading.Lock()

    def open(self, codec: str) -> None:
        """Pick the decoder once the codec is read. Reconnects keep appending to the same file."""
        with self._lock:
            if self._decoder is None:
                self._decoder = decoder_for(codec)
            if self._wav is None:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self._wav = wave.open(str(self.path), "wb")
                self._wav.setnchannels(1)
                self._wav.setsampwidth(2)
                self._wav.setframerate(PCM_RATE_HZ)

    def feed(self, payload: bytes) -> None:
        with self._lock:
            if self._decoder is None or self._wav is None:
                return
            try:
                pcm = self._decoder.decode(payload)
            except Exception:
                self.bad += 1
                return
            self._wav.writeframes(pcm)
            self.frames += 1
            self._samples += len(pcm) // 2

    def seconds(self) -> float:
        with self._lock:
            return self._samples / PCM_RATE_HZ

    def close(self) -> None:
        with self._lock:
            if self._wav is not None:
                self._wav.close()
                self._wav = None
