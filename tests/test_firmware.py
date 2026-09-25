import json
import struct
import tempfile
import unittest
import zipfile
from pathlib import Path

from sideband.firmware import IMAGE_MAGIC, FirmwareError, read_image, read_package


def fake_image(digest: bytes, version: tuple[int, int, int, int] = (0, 0, 0, 0), protected: bool = False) -> bytes:
    body = b"\xaa" * 64
    header = struct.pack("<IIHHII", IMAGE_MAGIC, 0, 32, 8 if protected else 0, len(body), 0)
    header += struct.pack("<BBHI", *version) + b"\x00" * 4
    tlvs = b""
    if protected:
        tlvs += struct.pack("<HH", 0x6908, 8) + struct.pack("<HH", 0x50, 0)
    sha = struct.pack("<HH", 0x10, len(digest)) + digest
    tlvs += struct.pack("<HH", 0x6907, 4 + len(sha)) + sha
    return header + body + tlvs


def fake_zip(path: Path, board: str = "omi") -> None:
    manifest = {
        "files": [
            {"board": f"{board}/nrf5340/cpunet", "soc": "nrf5340", "image_index": "1", "file": "net.bin"},
            {"board": board, "soc": "nrf5340", "image_index": "0", "file": "app.bin"},
        ]
    }
    with zipfile.ZipFile(path, "w") as bundle:
        bundle.writestr("manifest.json", json.dumps(manifest))
        bundle.writestr("app.bin", fake_image(b"\x01" * 32, (3, 0, 21, 7)))
        bundle.writestr("net.bin", fake_image(b"\x02" * 32))


class ImageTest(unittest.TestCase):
    def test_version_and_digest(self) -> None:
        version, digest = read_image(fake_image(b"\x05" * 32, (1, 2, 3, 4)))
        self.assertEqual(version, "1.2.3+4")
        self.assertEqual(digest, b"\x05" * 32)

    def test_protected_tlvs_are_walked(self) -> None:
        _, digest = read_image(fake_image(b"\x06" * 32, protected=True))
        self.assertEqual(digest, b"\x06" * 32)

    def test_rejects_non_mcuboot(self) -> None:
        with self.assertRaises(FirmwareError):
            read_image(b"\x00" * 64)


class PackageTest(unittest.TestCase):
    def test_images_sorted_by_core(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ota.zip"
            fake_zip(path)
            images = read_package(path)
            self.assertEqual([i.index for i in images], [0, 1])
            self.assertEqual(images[0].version, "3.0.21+7")

    def test_refuses_other_boards(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ota.zip"
            fake_zip(path, board="nrf5340dk")
            with self.assertRaises(FirmwareError):
                read_package(path)


if __name__ == "__main__":
    unittest.main()
