import time
import unittest

from sideband.buckets import Filed, note_markdown, with_bucket
from sideband.commands import Command, Context, command_messages, guess_command, match_folder, parse_command, suggestions
from sideband.llm import with_callout, with_summary
from sideband.thoughtdoc import friendly_when, parse_thought

FOLDERS = [("Work",), ("Work", "Clients"), ("Work", "Clients", "Shopify"), ("Health",), ("Health", "Running")]
GAMES = [("fighter", "Sky Ace 1943"), ("corn", "Corn Maze")]
CTX = Context("thoughts", (), FOLDERS, GAMES)


class ParseTest(unittest.TestCase):
    def test_places_and_folders(self) -> None:
        self.assertEqual(parse_command("go inbox", CTX), Command("go", "inbox"))
        self.assertEqual(parse_command("go Work / Clients / Shopify", CTX), Command("go", "Work / Clients / Shopify"))
        self.assertEqual(parse_command("go shopify", CTX), Command("go", "Work / Clients / Shopify"))
        self.assertEqual(parse_command("go Mars / Base", CTX), Command("none"))

    def test_verbs(self) -> None:
        self.assertEqual(parse_command("note Call Dana tomorrow", CTX), Command("note", "Call Dana tomorrow"))
        self.assertEqual(parse_command("`ask what did I promise`", CTX), Command("ask", "what did I promise"))
        self.assertEqual(parse_command("record stop", CTX), Command("record", "stop"))
        self.assertEqual(parse_command("play <fighter>", CTX), Command("play", "fighter"))
        self.assertEqual(parse_command("play corn maze", CTX), Command("play", "corn"))
        self.assertEqual(parse_command("play chess", CTX), Command("none"))
        self.assertEqual(parse_command("mature", CTX), Command("mature"))
        self.assertEqual(parse_command("note", CTX), Command("none"))
        self.assertEqual(parse_command("Sure! Here is the command", CTX), Command("none"))

    def test_match_folder(self) -> None:
        self.assertEqual(match_folder("clients", FOLDERS), ("Work", "Clients"))
        self.assertEqual(match_folder("work / clients", FOLDERS), ("Work", "Clients"))
        self.assertIsNone(match_folder("", FOLDERS))


class GuessTest(unittest.TestCase):
    def test_without_a_model(self) -> None:
        self.assertEqual(guess_command("that's all", CTX).verb, "stop")
        self.assertEqual(guess_command("start recording", CTX), Command("record", "start"))
        self.assertEqual(guess_command("open shopify", CTX), Command("go", "Work / Clients / Shopify"))
        self.assertEqual(guess_command("show me the inbox", CTX), Command("go", "inbox"))
        self.assertEqual(guess_command("what did I promise this week", CTX).verb, "ask")
        self.assertEqual(guess_command("let's play corn maze", CTX), Command("play", "corn"))
        self.assertEqual(guess_command("I should buy more coffee beans", CTX).verb, "note")
        self.assertEqual(guess_command("uh", CTX).verb, "none")

    def test_in_a_game_chatter_does_nothing(self) -> None:
        game = Context("game", (), FOLDERS, GAMES)
        self.assertEqual(guess_command("exit game", game).verb, "exit")
        self.assertEqual(guess_command("I should buy more coffee beans", game).verb, "none")

    def test_prompt_and_hints_follow_the_screen(self) -> None:
        folder = Context("folder", ("Work", "Clients", "Shopify"), FOLDERS, GAMES)
        self.assertIn("the folder Work / Clients / Shopify", command_messages("hi", folder)[0]["content"])
        self.assertIn("“what's in Shopify?”", suggestions(folder))
        self.assertIn("“exit game”", suggestions(Context("game")))
        self.assertIn("“stop recording”", suggestions(Context(recording=True)))


class ThoughtDocTest(unittest.TestCase):
    def test_parts_without_markup(self) -> None:
        md = note_markdown(0, "Call Dana")
        md = with_summary(with_callout(md, "Call Dana."), "## Summary\nA call.\n## Action items\n- [ ] Call Dana\n- [x] Find number\n- none")
        md = with_bucket(md, Filed(("Work", "Clients"), "Call Dana"))
        doc = parse_thought(md)
        self.assertEqual((doc.title, doc.folder, doc.callout, doc.summary), ("Call Dana", ("Work", "Clients"), "Call Dana.", "A call."))
        self.assertEqual(doc.actions, [(False, "Call Dana"), (True, "Find number")])
        self.assertEqual(doc.lines, [("00:00", "Call Dana")])
        self.assertTrue(doc.typed)
        self.assertEqual(doc.meta, "Typed on this Mac.")
        self.assertNotIn("<!--", doc.snippet())

    def test_friendly_when(self) -> None:
        now = time.mktime((2026, 9, 29, 15, 0, 0, 0, 0, -1))
        self.assertEqual(friendly_when(now - 3600, now), "Today 14:00")
        self.assertTrue(friendly_when(now - 86400, now).startswith("Yesterday"))
        self.assertEqual(friendly_when(time.mktime((2026, 1, 5, 9, 0, 0, 0, 0, -1)), now), "5 Jan")


if __name__ == "__main__":
    unittest.main()
