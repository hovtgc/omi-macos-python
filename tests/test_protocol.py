import unittest

from sideband.protocol import PACKET_HEADER_BYTES, codec_name, strip_packet


class ProtocolTest(unittest.TestCase):
    def test_strip_drops_short_notifications(self) -> None:
        self.assertEqual(strip_packet(b"\x01\x02"), b"")
        self.assertEqual(strip_packet(b"\x01\x02\x03"), b"")

    def test_strip_keeps_the_frame(self) -> None:
        payload = bytes([20, 21, 22, 23])
        packet = b"\x00\x01\x02" + payload
        self.assertEqual(len(b"\x00\x01\x02"), PACKET_HEADER_BYTES)
        self.assertEqual(strip_packet(packet), payload)

    def test_codec_names(self) -> None:
        self.assertEqual(codec_name(20), "opus-16k")
        self.assertEqual(codec_name(21), "opus-fs320")
        self.assertEqual(codec_name(99), "unknown-99")


if __name__ == "__main__":
    unittest.main()
