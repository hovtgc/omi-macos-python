"""Gamepad edges, with no pygame and no hardware."""

import unittest

from sideband.pads import A, B, START, PadBank, RawPad, edges


def pad(name: str, index: int = 0, buttons: tuple[int, ...] = (), hat: tuple[int, int] = (0, 0), axes: tuple[float, float] = (0.0, 0.0)) -> RawPad:
    full = buttons + (0,) * (16 - len(buttons))
    return RawPad(name, index, full[:16], axes, hat)


class EdgeTest(unittest.TestCase):
    def test_confirm_fires_once_while_held(self) -> None:
        prev: dict = {}
        buttons = (0,) * 16
        first = edges([pad("Xbox", buttons=buttons)], prev)
        assert first is not None
        self.assertFalse(first.confirm)
        pressed = list(buttons)
        pressed[A] = 1
        down = edges([pad("Xbox", buttons=tuple(pressed))], prev)
        assert down is not None
        self.assertTrue(down.confirm)
        held = edges([pad("Xbox", buttons=tuple(pressed))], prev)
        assert held is not None
        self.assertFalse(held.confirm)

    def test_hat_and_cancel_and_preferred_pad(self) -> None:
        prev: dict = {}
        event = edges([pad("Xbox", hat=(1, 0)), pad("DualSense", index=1)], prev, preferred="sense")
        assert event is not None
        self.assertEqual(event.name, "DualSense")
        self.assertEqual(event.dpad_x, 0)
        prev.clear()
        event = edges([pad("Xbox", hat=(1, 0))], prev)
        assert event is not None
        self.assertEqual(event.dpad_x, 1)
        again = edges([pad("Xbox", hat=(1, 0))], prev)
        assert again is not None
        self.assertEqual(again.dpad_x, 0)
        pressed = [0] * 16
        pressed[B] = 1
        pressed[START] = 1
        both = edges([pad("Xbox", buttons=tuple(pressed), hat=(0, 0))], prev)
        assert both is not None
        self.assertTrue(both.cancel)
        self.assertTrue(both.menu)

    def test_stick_up_is_positive_and_deadzone_is_quiet(self) -> None:
        prev: dict = {}
        event = edges([pad("Xbox", axes=(0.05, -0.9))], prev)
        assert event is not None
        self.assertEqual(event.x, 0.0)
        self.assertAlmostEqual(event.y, 0.9)

    def test_unplug_clears_and_bank_uses_the_reader(self) -> None:
        prev: dict = {}
        edges([pad("Xbox")], prev)
        self.assertIsNone(edges([], prev))
        self.assertEqual(prev, {})
        seen = {"n": 0}

        def reader():
            seen["n"] += 1
            return [pad("Xbox")] if seen["n"] == 1 else []

        bank = PadBank(reader=reader)
        self.assertEqual(bank.poll().name, "Xbox")  # type: ignore[union-attr]
        self.assertIsNone(bank.poll())
        self.assertEqual(bank.names(), ())


if __name__ == "__main__":
    unittest.main()
