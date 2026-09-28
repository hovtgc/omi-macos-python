import unittest

from sideband.llm import CALLOUT_START, SUMMARY_START, callout_messages, callout_of, clean_callout, spoken_lines, with_callout, with_summary
from sideband.speech import pick_voice

TRANSCRIPT = """# Omi recording, Saturday 26 September 2026, 12:00

Length 00:12. Transcribed on this Mac; audio is deleted after 24 hours.

**[00:00]** Call the supplier about batteries.  
"""
LISTING = """Albert              en_US    # Hello! My name is Albert.
Daniel              en_GB    # Hello! My name is Daniel.
Samantha            en_US    # Hello! My name is Samantha.
Amélie              fr_CA    # Bonjour ! Je m’appelle Amélie.
"""


class CalloutTest(unittest.TestCase):
    def test_prompt_is_written_for_the_ear(self) -> None:
        system = callout_messages("[00:00] hi")[0]["content"]
        for rule in ("read aloud", "60 words", "no lists", "Nothing much in that one"):
            self.assertIn(rule, system)

    def test_clean_strips_markdown_and_bounds_length(self) -> None:
        self.assertEqual(clean_callout("**You** said:\n- call Dana\n- book a room"), "You said: call Dana book a room")
        long = "One two three. " * 30
        cleaned = clean_callout(long, max_words=10)
        self.assertLessEqual(len(cleaned.split()), 10)
        self.assertTrue(cleaned.endswith("."))

    def test_stored_above_the_transcript_and_replaced(self) -> None:
        once = with_callout(TRANSCRIPT, "You need to call the supplier.")
        self.assertLess(once.index(CALLOUT_START), once.index("**[00:00]**"))
        self.assertEqual(callout_of(once), "You need to call the supplier.")
        self.assertEqual(spoken_lines(once), spoken_lines(TRANSCRIPT))
        twice = with_callout(once, "Batteries.")
        self.assertEqual(twice.count(CALLOUT_START), 1)
        self.assertEqual(callout_of(twice), "Batteries.")
        both = with_summary(twice, "## Summary\nx")
        self.assertLess(both.index(CALLOUT_START), both.index(SUMMARY_START))
        self.assertEqual(callout_of(both), "Batteries.")
        self.assertIsNone(callout_of(TRANSCRIPT))


class VoiceTest(unittest.TestCase):
    def test_prefers_premium_then_samantha(self) -> None:
        self.assertEqual(pick_voice(LISTING), "Samantha")
        premium = LISTING + "Ava (Premium)       en_US    # Hello! My name is Ava.\n"
        self.assertEqual(pick_voice(premium), "Ava (Premium)")
        self.assertIsNone(pick_voice("Amélie              fr_CA    # Bonjour\n"))


if __name__ == "__main__":
    unittest.main()
