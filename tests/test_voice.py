import unittest

from sideband.game import CEIL, NUDGE_S, Flight
from sideband.voice import CommandSpotter, MenuSpotter, menu_command


class SpotterTest(unittest.TestCase):
    def test_each_word_fires_once_as_partials_grow(self) -> None:
        spot = CommandSpotter()
        self.assertEqual(spot.partial("go"), [])
        self.assertEqual(spot.partial("go left"), ["left"])
        self.assertEqual(spot.partial("go left"), [])
        self.assertEqual(spot.partial("go left go up"), ["up"])
        self.assertEqual(spot.final("go left go up"), [])

    def test_final_catches_words_partials_missed_and_resets(self) -> None:
        spot = CommandSpotter()
        self.assertEqual(spot.final("go right"), ["right"])
        self.assertEqual(spot.partial("go right"), ["right"])  # a new utterance

    def test_ignores_non_commands(self) -> None:
        self.assertEqual(CommandSpotter().final("[unk] go"), [])


class MenuTest(unittest.TestCase):
    def test_phrases(self) -> None:
        cases = {
            "open the arcade": "open:arcade",
            "open transcriber": "open:transcriber",
            "bluetooth": "open:bluetooth",
            "play marble": "play:corn",
            "play the maze": "play:corn",
            "play corn maze": "play:corn",
            "play sky ace": "play:fighter",
            "play fighter": "play:fighter",
            "play star dodger": "play:dodger",
            "play voice flap": "play:voice",
            "play flap": "play:flap",
            "start recording": "record:start",
            "stop recording": "record:stop",
            "record": "record:toggle",
            "close": "close",
            "go home": "home",
            "show launcher": "home",
            "cancel": "cancel",
            "summarize that": "summarize",
            "summarize last recording": "summarize",
            "summary": "summarize",
        }
        for said, command in cases.items():
            self.assertEqual(menu_command(said), command, said)

    def test_incomplete_or_unrelated_speech_does_nothing(self) -> None:
        for said in ("", "open", "play", "play voice", "start", "[unk] the", "hello there"):
            self.assertIsNone(menu_command(said), said)

    def test_spotter_fires_once_per_utterance(self) -> None:
        spot = MenuSpotter()
        self.assertEqual(spot.partial("open"), [])
        self.assertEqual(spot.partial("open arcade"), ["open:arcade"])
        self.assertEqual(spot.partial("open arcade please"), [])
        self.assertEqual(spot.final("open arcade"), [])
        self.assertEqual(spot.final("play catch"), ["play:catch"])  # next utterance


class VoiceFlightTest(unittest.TestCase):
    def test_hovers_without_commands(self) -> None:
        game = Flight(voice=True)
        game.command("stop")
        for _ in range(600):
            game.step(1 / 60)
        self.assertAlmostEqual(game.y, CEIL / 2, places=3)

    def test_nudge_moves_then_holds(self) -> None:
        game = Flight(voice=True)
        game.command("up")
        for _ in range(int(NUDGE_S * 60)):
            game.step(1 / 60)
        risen = game.y - CEIL / 2
        self.assertGreater(risen, 1.0)
        for _ in range(120):
            game.step(1 / 60)
        after = game.y
        for _ in range(60):
            game.step(1 / 60)
        self.assertAlmostEqual(game.y, after, places=2)

    def test_left_and_right(self) -> None:
        game = Flight(voice=True)
        game.command("left")
        for _ in range(60):
            game.step(1 / 60)
        self.assertLess(game.x, -1.0)

    def test_retry_keeps_voice_mode(self) -> None:
        game = Flight(voice=True)
        game.command("down")
        while game.alive:
            game.command("down")
            game.step(1 / 60)
        game.step(1.0)
        game.command("up")
        self.assertTrue(game.alive and game.voice)



class IngameCommandTest(unittest.TestCase):
    def test_phrases(self) -> None:
        from sideband.voice import ingame_command

        for said in ("exit game", "exit", "quit the game", "back to the menu", "main menu", "leave", "go back to the arcade"):
            self.assertEqual(ingame_command(said), "exit", said)
        self.assertEqual(ingame_command("pause"), "pause")
        self.assertEqual(ingame_command("wait a second"), "pause")
        for said in ("play again", "resume", "continue", "restart", "start", "let's go"):
            self.assertEqual(ingame_command(said), "go", said)
        for said in ("nice shot", "oh no", "i'm going left", "the weather is nice", ""):
            self.assertIsNone(ingame_command(said), said)


class ArcadeIntentTest(unittest.TestCase):
    KEYS = ["fighter", "flap", "corn", "dodger", "catch", "voice"]

    def test_parse(self) -> None:
        from sideband.llm import parse_arcade

        self.assertEqual(parse_arcade("play fighter", self.KEYS, None), "play:fighter")
        self.assertEqual(parse_arcade("Play corn\n", self.KEYS, None), "play:corn")
        self.assertEqual(parse_arcade("play <dodger>", self.KEYS, None), "play:dodger")
        self.assertEqual(parse_arcade("show catch", self.KEYS, None), "show:catch")
        self.assertEqual(parse_arcade("play this", self.KEYS, "flap"), "play:flap")
        self.assertEqual(parse_arcade("play", self.KEYS, "corn"), "play:corn")
        self.assertEqual(parse_arcade("play pacman", self.KEYS, "corn"), "none")
        self.assertEqual(parse_arcade("recalibrate", self.KEYS, None), "recalibrate")
        self.assertEqual(parse_arcade("Sure! Let me", self.KEYS, None), "none")
        self.assertEqual(parse_arcade("", self.KEYS, None), "none")

    def test_prompt_names_the_highlighted_game(self) -> None:
        from sideband.llm import arcade_messages

        games = [("fighter", "SKY ACE 1943", "dogfight"), ("corn", "CORN MAZE", "maze")]
        system = arcade_messages("play this", games, "corn")[0]["content"]
        self.assertIn("Highlighted game: Corn Maze", system)
        self.assertIn("- fighter: Sky Ace 1943", system)

    def test_keyword_fallback(self) -> None:
        from sideband.llm import guess_arcade
        from sideband.voice import GAMES

        self.assertEqual(guess_arcade("play the corn maze", GAMES, None), "play:corn")
        self.assertEqual(guess_arcade("play this", GAMES, "catch"), "play:catch")
        self.assertEqual(guess_arcade("play", GAMES, "catch"), "play:catch")
        self.assertEqual(guess_arcade("recalibrate the controls", GAMES, None), "recalibrate")
        self.assertEqual(guess_arcade("close the arcade", GAMES, None), "close")
        self.assertEqual(guess_arcade("nice weather", GAMES, "catch"), "none")

if __name__ == "__main__":
    unittest.main()
