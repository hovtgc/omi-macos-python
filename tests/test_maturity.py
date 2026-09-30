import tempfile
import unittest
from pathlib import Path

from sideband import maturity
from sideband.maturity import Maturity, acted, mature_messages, needs_maturing, parse_maturity

REPLY = """**Stage:** Ready
Where it stands: The Shopify landing page is waiting on your feedback and a CDN move.
Next action: Email the Shopify client your landing page feedback and the CDN plan.
Why now: You promised it by Thursday.
Open questions:
- Who uploads the hero image?
- Is the feedback round the last one?
"""


class MaturityTest(unittest.TestCase):
    def test_parse(self) -> None:
        entry = parse_maturity(REPLY, 3, 10.0)
        self.assertEqual(entry.stage, "ready")
        self.assertEqual(entry.badge, "🌳")
        self.assertTrue(entry.next_action.startswith("Email the Shopify client"))
        self.assertEqual(maturity.field(entry.text, "why now"), "You promised it by Thursday.")
        self.assertEqual(parse_maturity("Stage: whatever\nNext action: Call Dana", 1, 0).stage, "seed")
        self.assertIsNone(parse_maturity("Stage: seed\nNo idea yet.", 1, 0))

    def test_when_to_mature(self) -> None:
        self.assertFalse(needs_maturing(None, 2))
        self.assertTrue(needs_maturing(None, 3))
        entry = Maturity("growing", "Do it", "", count=3)
        self.assertFalse(needs_maturing(entry, 3))
        self.assertTrue(needs_maturing(entry, 4))
        self.assertFalse(needs_maturing(acted(entry, "Do it"), 5))  # acted on: leave it be

    def test_prompt_and_store(self) -> None:
        messages = mature_messages(("Work", "Clients"), [("Mon", "[00:00] first"), ("Tue", "[00:00] second")])
        self.assertIn("Next action:", messages[0]["content"])
        self.assertLess(messages[1]["content"].index("first"), messages[1]["content"].index("second"))
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            self.assertEqual(maturity.load(folder), {})
            entry = acted(parse_maturity(REPLY, 3, 1.0), "Email the client")
            maturity.save(folder, {maturity.key(("Work", "Clients")): entry})
            back = maturity.load(folder)["Work / Clients"]
            self.assertEqual((back.stage, back.badge, back.acted), ("action", "✅", "Email the client"))


if __name__ == "__main__":
    unittest.main()
