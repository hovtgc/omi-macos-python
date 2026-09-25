"""Omi BLE constants. See the public protocol: audio notifications carry a 3-byte header."""

OMI_SERVICE_UUID = "19b10000-e8f2-537e-4f6c-d104768a1214"
AUDIO_DATA_UUID = "19b10001-e8f2-537e-4f6c-d104768a1214"
AUDIO_CODEC_UUID = "19b10002-e8f2-537e-4f6c-d104768a1214"
BATTERY_SERVICE_UUID = "0000180f-0000-1000-8000-00805f9b34fb"
BATTERY_LEVEL_UUID = "00002a19-0000-1000-8000-00805f9b34fb"

PACKET_HEADER_BYTES = 3
GAP_S = 2.0
PCM_RATE_HZ = 16000

CODECS = {
    0: "pcm16-16k",
    1: "pcm16-8k",
    20: "opus-16k",
    21: "opus-fs320",
}


def strip_packet(packet: bytes) -> bytes:
    """Return the codec payload. Empty when the notification is too short to be a frame."""
    if len(packet) <= PACKET_HEADER_BYTES:
        return b""
    return bytes(packet[PACKET_HEADER_BYTES:])


def codec_name(codec_id: int) -> str:
    return CODECS.get(codec_id, f"unknown-{codec_id}")
