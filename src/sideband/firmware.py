"""Omi OTA packages and MCUboot image headers. Pure: reads bytes, never talks to a device.

An Omi OTA zip (from `west build --sysbuild`, or a BasedHardware release) holds `manifest.json`
and one signed MCUboot image per core: image 0 the application core, image 1 the network core.
"""

from __future__ import annotations

import json
import struct
import zipfile
from dataclasses import dataclass
from pathlib import Path

IMAGE_MAGIC = 0x96F3B83D
TLV_INFO_MAGIC = 0x6907
TLV_PROT_INFO_MAGIC = 0x6908
TLV_SHA256 = 0x10
TLV_KEYHASH = 0x01


class FirmwareError(ValueError):
    pass


@dataclass(frozen=True)
class Image:
    index: int
    name: str
    data: bytes
    version: str
    digest: bytes  # the SHA256 TLV, which is what SMP image state reports as "hash"

    @property
    def size(self) -> int:
        return len(self.data)


def read_image(data: bytes) -> tuple[str, bytes]:
    """Version string and SHA256 digest of a signed MCUboot image."""
    if len(data) < 32:
        raise FirmwareError("image shorter than an MCUboot header")
    magic, _load, hdr_size, _prot_size, img_size, _flags = struct.unpack_from("<IIHHII", data, 0)
    if magic != IMAGE_MAGIC:
        raise FirmwareError(f"not an MCUboot image (magic {magic:#x})")
    major, minor, revision, build = struct.unpack_from("<BBHI", data, 20)
    offset = hdr_size + img_size  # protected TLVs (if any, `prot_size` bytes) come first, then the rest
    digest = b""
    while offset + 4 <= len(data):
        magic, total = struct.unpack_from("<HH", data, offset)
        if magic not in (TLV_INFO_MAGIC, TLV_PROT_INFO_MAGIC):
            break
        end, cursor = offset + total, offset + 4
        while cursor + 4 <= end:
            kind, length = struct.unpack_from("<HH", data, cursor)
            if kind == TLV_SHA256:
                digest = bytes(data[cursor + 4 : cursor + 4 + length])
            cursor += 4 + length
        offset = end
    if not digest:
        raise FirmwareError("image has no SHA256 TLV")
    return f"{major}.{minor}.{revision}+{build}", digest


def read_package(path: Path) -> list[Image]:
    """Images in an OTA zip, ordered by image index. Refuses anything not built for the Omi nRF5340."""
    try:
        bundle = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise FirmwareError(f"cannot open {path}: {exc}") from exc
    with bundle:
        try:
            manifest = json.loads(bundle.read("manifest.json"))
        except (KeyError, ValueError) as exc:
            raise FirmwareError("zip has no readable manifest.json") from exc
        images = []
        for entry in manifest.get("files", []):
            if entry.get("soc") != "nrf5340" or not str(entry.get("board", "")).startswith("omi"):
                raise FirmwareError(f"{entry.get('file')} is for {entry.get('board')}/{entry.get('soc')}, not the Omi nRF5340")
            data = bundle.read(entry["file"])
            version, digest = read_image(data)
            images.append(Image(int(entry["image_index"]), entry["file"], data, version, digest))
    if not images:
        raise FirmwareError("manifest lists no images")
    return sorted(images, key=lambda image: image.index)


def describe(images: list[Image]) -> list[str]:
    core = {0: "app core", 1: "net core"}
    return [
        f"image {i.index} ({core.get(i.index, '?')})  {i.name}  {i.size} bytes  version {i.version}  sha256 {i.digest.hex()[:16]}…"
        for i in images
    ]
