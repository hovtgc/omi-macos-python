import math
import tempfile
import unittest
import wave
from pathlib import Path

from sideband.audio import AudioUnavailable, WavSink, decoder_for

try:
    import av
except ImportError:
    av = None


class WavTest(unittest.TestCase):
    def test_pcm_needs_no_extra(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sink = WavSink(Path(tmp) / "out.wav")
            sink.open("pcm16-16k")
            sink.feed(b"\x01\x00" * 160)
            sink.close()
            self.assertAlmostEqual(sink.seconds(), 0.01)
            with wave.open(str(sink.path)) as handle:
                self.assertEqual(handle.getnframes(), 160)

    def test_unknown_codec(self) -> None:
        with self.assertRaises(AudioUnavailable):
            decoder_for("pcm16-8k")

    @unittest.skipIf(av is None, "audio extra not installed")
    def test_opus_round_trip(self) -> None:
        # Encode a synthetic 440 Hz tone as 20 ms Opus frames, then decode through the sink.
        enc = av.CodecContext.create("libopus", "w")
        enc.sample_rate, enc.layout, enc.format = 16000, "mono", "s16"
        tone = bytes()
        for i in range(16000):
            tone += int(8000 * math.sin(2 * math.pi * 440 * i / 16000)).to_bytes(2, "little", signed=True)
        packets = []
        for start in range(0, len(tone), 640):
            frame = av.AudioFrame(format="s16", layout="mono", samples=320)
            frame.sample_rate = 16000
            frame.planes[0].update(tone[start : start + 640])
            packets += [bytes(p) for p in enc.encode(frame)]
        with tempfile.TemporaryDirectory() as tmp:
            sink = WavSink(Path(tmp) / "tone.wav")
            sink.open("opus-fs320")
            for packet in packets:
                sink.feed(packet)
            sink.close()
            self.assertEqual(sink.bad, 0)
            self.assertGreater(sink.seconds(), 0.8)


if __name__ == "__main__":
    unittest.main()
