import json
import unittest

from sideband.buckets import (
    BUCKET_START,
    Filed,
    all_folders,
    bucket_messages,
    bucket_of,
    folder_counts,
    is_new_folder,
    match_known,
    note_markdown,
    parse_bucket,
    split_path,
    with_bucket,
)
from sideband.llm import (
    CALLOUT_START,
    SUMMARY_START,
    Backend,
    api_request,
    spoken_lines,
    sse_tokens,
    transcript_text,
    with_callout,
    with_summary,
)

TRANSCRIPT = """# Omi recording, Saturday 26 September 2026, 12:00

Length 00:12. Transcribed on this Mac; audio is deleted after 24 hours.

**[00:00]** We should hire a designer for the Omi plugin.
**[00:05]** Ask Dana for portfolios by Friday.
"""

KNOWN = [("Work", "Hiring"), ("Work", "Hiring", "Designer Role"), ("Health", "Running")]


class ParseTest(unittest.TestCase):
    def test_two_lines(self) -> None:
        filed = parse_bucket("Folder: Work / Hiring / Designer Role\nTitle: Ask Dana for designer portfolios", KNOWN)
        self.assertEqual(filed, Filed(("Work", "Hiring", "Designer Role"), "Ask Dana for designer portfolios"))

    def test_reuses_existing_spelling_and_caps_depth(self) -> None:
        filed = parse_bucket("**Folder:** work / hiring / new thread / too deep\n**Title:** \"Hi\"", KNOWN)
        self.assertEqual(filed.folder, ("Work", "Hiring", "New thread"))
        self.assertEqual(filed.title, "Hi")

    def test_other_separators_and_emoji(self) -> None:
        self.assertEqual(split_path(" 📁 Ideas › App Ideas > Omi plugins "), ("Ideas", "App Ideas", "Omi plugins"))
        self.assertEqual(split_path("home\\kitchen"), ("Home", "Kitchen"))

    def test_bare_path_and_garbage(self) -> None:
        self.assertEqual(parse_bucket("Health / Running", KNOWN).folder, ("Health", "Running"))
        self.assertIsNone(parse_bucket("I am not sure.", KNOWN))
        self.assertIsNone(parse_bucket("", KNOWN))

    def test_match_known_only_among_siblings(self) -> None:
        self.assertEqual(match_known(("health", "hiring"), KNOWN), ("Health", "hiring"))


class StoreTest(unittest.TestCase):
    def test_round_trip_and_replace(self) -> None:
        once = with_bucket(TRANSCRIPT, Filed(("Work", "Hiring"), "Hire a designer"))
        self.assertEqual(bucket_of(once), Filed(("Work", "Hiring"), "Hire a designer"))
        self.assertEqual(spoken_lines(once), spoken_lines(TRANSCRIPT))
        twice = with_bucket(once, Filed(("Ideas", "Omi Plugins"), ""))
        self.assertEqual(twice.count(BUCKET_START), 1)
        self.assertEqual(bucket_of(twice), Filed(("Ideas", "Omi Plugins"), ""))
        self.assertIsNone(bucket_of(TRANSCRIPT))

    def test_lives_with_callout_and_summary_in_any_order(self) -> None:
        text = with_summary(with_callout(TRANSCRIPT, "You want a designer."), "## Summary\nx\n## Action items\n- none")
        text = with_bucket(text, Filed(("Work", "Hiring"), "Designer"))
        self.assertLess(text.index(BUCKET_START), text.index(CALLOUT_START))
        self.assertLess(text.index(CALLOUT_START), text.index(SUMMARY_START))
        self.assertEqual(spoken_lines(text), spoken_lines(TRANSCRIPT))
        later = with_callout(with_bucket(TRANSCRIPT, Filed(("A", "B"), "t")), "said")
        self.assertEqual(bucket_of(later), Filed(("A", "B"), "t"))
        self.assertLess(later.index(BUCKET_START), later.index(CALLOUT_START))

    def test_typed_thought_reads_like_a_transcript(self) -> None:
        note = note_markdown(0, "Buy milk\n\nCall mum")
        self.assertEqual(transcript_text(note), "[00:00] Buy milk\n[00:00] Call mum")


class TreeTest(unittest.TestCase):
    def test_parents_counts_and_new(self) -> None:
        folders = [("Work", "Hiring"), ("Work", "Hiring", "Designer Role"), ("Health", "Running")]
        self.assertEqual(all_folders(folders)[:2], [("Health",), ("Health", "Running")])
        self.assertEqual(folder_counts(folders)[("Work",)], 2)
        self.assertEqual(folder_counts(folders)[("Work", "Hiring", "Designer Role")], 1)
        self.assertIsNone(is_new_folder(("Work", "Hiring"), folders))
        self.assertEqual(is_new_folder(("Work", "Sales", "Q4"), folders), ("Work", "Sales"))
        self.assertEqual(is_new_folder(("Family", "Kids"), []), ("Family",))

    def test_prompt_lists_the_map(self) -> None:
        messages = bucket_messages(transcript_text(TRANSCRIPT), all_folders(KNOWN))
        self.assertIn("- Work / Hiring / Designer Role", messages[0]["content"])
        self.assertIn("Folder:", messages[0]["content"])
        self.assertIn("designer", messages[1]["content"])
        self.assertIn("starting the map", bucket_messages("x", [])[0]["content"])


class ApiTest(unittest.TestCase):
    def test_request_shape(self) -> None:
        backend = Backend("api", "llama3.2", "http://localhost:11434/v1/", "")
        request = api_request(backend, [{"role": "user", "content": "hi"}], 50)
        self.assertEqual(request.full_url, "http://localhost:11434/v1/chat/completions")
        body = json.loads(request.data)
        self.assertEqual((body["model"], body["max_tokens"], body["stream"]), ("llama3.2", 50, True))
        self.assertIsNone(request.get_header("Authorization"))
        keyed = api_request(Backend("api", "m", "https://openrouter.ai/api/v1", "sk-1"), [], 5)
        self.assertEqual(keyed.get_header("Authorization"), "Bearer sk-1")

    def test_local_or_not(self) -> None:
        self.assertTrue(Backend().local)
        self.assertTrue(Backend("api", "m", "http://localhost:11434/v1").local)
        self.assertTrue(Backend("api", "m", "http://127.0.0.1:1234/v1").local)
        self.assertFalse(Backend("api", "m", "https://api.openai.com/v1").local)

    def test_stream(self) -> None:
        lines = [
            b": keep-alive\n",
            b'data: {"choices":[{"delta":{"role":"assistant"}}]}\n',
            b'data: {"choices":[{"delta":{"content":"Folder: "}}]}\n',
            b"\n",
            b'data: {"choices":[{"delta":{"content":"Work"}}]}\n',
            b"data: [DONE]\n",
            b'data: {"choices":[{"delta":{"content":"ignored"}}]}\n',
        ]
        self.assertEqual("".join(sse_tokens(lines)), "Folder: Work")
        with self.assertRaises(RuntimeError):
            list(sse_tokens([b'data: {"error":{"message":"bad key"}}']))


if __name__ == "__main__":
    unittest.main()
