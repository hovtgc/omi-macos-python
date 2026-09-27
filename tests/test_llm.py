import unittest

from sideband.llm import (
    SUMMARY_END,
    SUMMARY_START,
    Doc,
    clean_summary,
    ask_all_messages,
    pick_context,
    spoken_lines,
    summary_messages,
    summary_of,
    title,
    transcript_text,
    with_summary,
)

TRANSCRIPT = """# Omi recording, Saturday 26 September 2026, 12:00

Length 00:12. Transcribed on this Mac; audio is deleted after 24 hours.

**[00:00]** Call the supplier about batteries.
**[00:05]** Send the notes before noon.
"""


class TranscriptTest(unittest.TestCase):
    def test_spoken_lines_and_title(self) -> None:
        self.assertEqual(spoken_lines(TRANSCRIPT), ["[00:00] Call the supplier about batteries.", "[00:05] Send the notes before noon."])
        self.assertEqual(title(TRANSCRIPT), "Omi recording, Saturday 26 September 2026, 12:00")
        self.assertIn("[00:05]", transcript_text(TRANSCRIPT))

    def test_summary_goes_before_the_spoken_lines_and_is_replaced(self) -> None:
        once = with_summary(TRANSCRIPT, "## Summary\nBatteries.\n## Action items\n- [ ] Call supplier")
        self.assertLess(once.index(SUMMARY_START), once.index("**[00:00]**"))
        self.assertEqual(spoken_lines(once), spoken_lines(TRANSCRIPT))  # transcript untouched
        self.assertIn("- [ ] Call supplier", summary_of(once))
        twice = with_summary(once, "## Summary\nNew.\n## Action items\n- none")
        self.assertEqual(twice.count(SUMMARY_START), 1)
        self.assertEqual(twice.count(SUMMARY_END), 1)
        self.assertIn("New.", summary_of(twice))
        self.assertNotIn("Batteries.", twice)
        self.assertIsNone(summary_of(TRANSCRIPT))

    def test_summary_prompt_carries_the_transcript(self) -> None:
        messages = summary_messages(transcript_text(TRANSCRIPT))
        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("## Action items", messages[1]["content"])
        self.assertIn("Send the notes", messages[1]["content"])


class CleanTest(unittest.TestCase):
    def test_stray_none_is_dropped_only_next_to_real_items(self) -> None:
        self.assertEqual(clean_summary("## Action items\n- [ ] Call Dana\n- none"), "## Action items\n- [ ] Call Dana")
        self.assertEqual(clean_summary("## Action items\n- none"), "## Action items\n- none")


class ContextTest(unittest.TestCase):
    def test_newest_first_within_budget(self) -> None:
        docs = [Doc(f"rec {i}", "\n".join(f"line {j} of {i}" for j in range(200))) for i in range(5)]
        picked = pick_context(docs, budget=5000)
        self.assertEqual(picked[0].name, "rec 0")
        self.assertLessEqual(sum(len(d.name) + len(d.text) + 8 for d in picked), 5000 + 10)
        self.assertTrue(picked[-1].text.endswith("[…]"))

    def test_ask_all_names_each_recording(self) -> None:
        messages = ask_all_messages("what did I promise?", [Doc("Mon", "[00:01] I will call Ana")])
        self.assertIn("### Mon", messages[1]["content"])
        self.assertIn("what did I promise?", messages[1]["content"])
        self.assertIn("no transcripts", ask_all_messages("x", [])[1]["content"])


if __name__ == "__main__":
    unittest.main()
