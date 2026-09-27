import tempfile
import time
import unittest
import wave
from pathlib import Path

from sideband.recordings import (
    AUDIO_TTL_S,
    expired_audio,
    list_recordings,
    new_path,
    started_at,
    sweep,
    transcript_markdown,
)


def make_wav(path: Path, seconds: float = 1.0) -> None:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x00\x00" * int(16000 * seconds))


class RecordingsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.now = time.mktime(time.strptime("20260926-120000", "%Y%m%d-%H%M%S"))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_names_round_trip_and_never_collide(self) -> None:
        first = new_path(self.dir, self.now)
        self.assertEqual(first.name, "omi-20260926-120000.wav")
        self.assertEqual(started_at(first.stem), self.now)
        make_wav(first)
        second = new_path(self.dir, self.now)
        self.assertEqual(second.name, "omi-20260926-120000-2.wav")
        self.assertEqual(started_at(second.stem), self.now)
        self.assertIsNone(started_at("notes"))

    def test_sweep_deletes_old_audio_and_keeps_transcripts(self) -> None:
        old = new_path(self.dir, self.now - AUDIO_TTL_S - 60)
        make_wav(old)
        old.with_suffix(".md").write_text("# old\n")
        fresh = new_path(self.dir, self.now - 3600)
        make_wav(fresh, 2.0)
        self.assertEqual(expired_audio(self.dir, self.now), [old])
        self.assertEqual(sweep(self.dir, self.now), [old])
        self.assertFalse(old.exists())
        self.assertTrue(old.with_suffix(".md").exists())
        rows = list_recordings(self.dir)
        self.assertEqual([r.stem for r in rows], [fresh.stem, old.stem])  # newest first
        self.assertAlmostEqual(rows[0].seconds, 2.0)
        self.assertIsNone(rows[1].audio)
        self.assertIsNotNone(rows[1].transcript)

    def test_sweep_spares_the_recording_in_progress(self) -> None:
        live = new_path(self.dir, self.now - AUDIO_TTL_S - 60)
        make_wav(live)
        self.assertEqual(sweep(self.dir, self.now, keep={live}), [])
        self.assertTrue(live.exists())

    def test_transcript_markdown(self) -> None:
        text = transcript_markdown(self.now, 65.0, [(0.0, 3.0, " Call the supplier. "), (61.5, 64.0, "  ")])
        self.assertIn("# Omi recording, Saturday 26 September 2026, 12:00", text)
        self.assertIn("Length 01:05.", text)
        self.assertIn("**[00:00]** Call the supplier.", text)
        self.assertNotIn("[01:01]", text)  # blank segments are dropped
        self.assertIn("Nothing intelligible", transcript_markdown(self.now, 2.0, []))


if __name__ == "__main__":
    unittest.main()
