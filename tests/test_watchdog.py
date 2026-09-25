import unittest

from sideband.protocol import GAP_S
from sideband.watchdog import Phase, Hold, mark_recovering, on_clock, on_packet


class WatchdogTest(unittest.TestCase):
    def test_frames_hold(self) -> None:
        state = Hold()
        tick = on_packet(state, 10.0)
        self.assertEqual(tick.state.phase, Phase.HOLDING)
        self.assertEqual(tick.state.packets, 1)
        self.assertFalse(tick.reconnect)

        later = on_clock(tick.state, 10.0 + GAP_S - 0.1)
        self.assertEqual(later.state.phase, Phase.HOLDING)
        self.assertFalse(later.reconnect)
        self.assertEqual(later.state.drops, 0)

    def test_silence_drops_once(self) -> None:
        state = on_packet(Hold(), 0.0).state
        gap = on_clock(state, GAP_S)
        self.assertTrue(gap.reconnect)
        self.assertEqual(gap.state.phase, Phase.GAP)
        self.assertEqual(gap.state.drops, 1)
        self.assertIn("gap", gap.note)

        again = on_clock(gap.state, GAP_S + 5)
        self.assertFalse(again.reconnect)
        self.assertEqual(again.state.drops, 1)

    def test_frame_after_gap_is_link_back(self) -> None:
        state = on_packet(Hold(), 0.0).state
        gap = on_clock(state, GAP_S).state
        recovering = mark_recovering(gap)
        self.assertEqual(recovering.phase, Phase.RECOVERING)
        back = on_packet(recovering, GAP_S + 1)
        self.assertEqual(back.note, "link back")
        self.assertEqual(back.state.phase, Phase.HOLDING)
        self.assertEqual(back.state.drops, 1)

    def test_idle_clock_does_nothing(self) -> None:
        tick = on_clock(Hold(), 50.0)
        self.assertEqual(tick.state.phase, Phase.IDLE)
        self.assertFalse(tick.reconnect)


if __name__ == "__main__":
    unittest.main()
