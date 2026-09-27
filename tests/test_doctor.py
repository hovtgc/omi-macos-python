import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sideband.doctor import Check, features, pendant_lines
from sideband.firmware import RELEASES, FirmwareError, fetch_release


class DoctorTest(unittest.TestCase):
    def test_feature_bits_seen_on_an_omi_cv1(self) -> None:
        self.assertNotIn("motion", features(bytes.fromhex("ec010000")))  # stock 3.0.19 / 3.0.21
        self.assertIn("motion", features(bytes.fromhex("ee010000")))  # motion build
        self.assertEqual(features(b""), [])

    def test_pendant_lines_point_to_the_next_step(self) -> None:
        stock = {"model": b"Omi CV 1", "firmware": b"3.0.21", "hardware": b"5.0", "battery": b"\x40", "features": bytes.fromhex("ec010000")}
        text = "\n".join(pendant_lines(stock))
        self.assertIn("firmware 3.0.21", text)
        self.assertIn("ONBOARDING.md step 7", text)
        moving = dict(stock, features=bytes.fromhex("ee010000"))
        self.assertIn("tilt games work", "\n".join(pendant_lines(moving)))
        other = dict(stock, model=b"Omi DevKit 2")
        self.assertIn("only built for the Omi CV 1", "\n".join(pendant_lines(other)))

    def test_check_shows_the_fix_only_when_failing(self) -> None:
        self.assertNotIn("→", Check("x", True, "fine", "do this").line())
        self.assertIn("→ do this", Check("x", False, "broken", "do this").line())


class ReleaseTest(unittest.TestCase):
    def test_pinned_checksum_is_enforced(self) -> None:
        def fake_download(_url: str, target: Path) -> None:
            Path(target).write_bytes(b"not the real firmware")

        with tempfile.TemporaryDirectory() as tmp, mock.patch("urllib.request.urlretrieve", fake_download):
            with self.assertRaises(FirmwareError):
                fetch_release("official", Path(tmp))
            self.assertEqual(list(Path(tmp).iterdir()), [])  # the bad file is not kept

    def test_good_file_passes(self) -> None:
        body = b"pretend zip"
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(RELEASES, {"test": ("https://x/y.zip", hashlib.sha256(body).hexdigest(), "")}):
            with mock.patch("urllib.request.urlretrieve", lambda _u, t: Path(t).write_bytes(body)):
                self.assertEqual(fetch_release("test", Path(tmp)).read_bytes(), body)


if __name__ == "__main__":
    unittest.main()
