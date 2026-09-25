import unittest

from sideband.app import SidebandApp


class AppTest(unittest.TestCase):
    def test_protocol_lines_name_the_gap(self) -> None:
        lines = SidebandApp().protocol_lines()
        text = "\n".join(lines)
        self.assertIn("19b10001-e8f2-537e-4f6c-d104768a1214", text)
        self.assertIn("2.0s", text)
        self.assertIn("3 bytes", text)


if __name__ == "__main__":
    unittest.main()
