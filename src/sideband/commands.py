"""Talk to Sideband: one voice layer for every screen. Pure.

In conversation mode the pendant's mic stays open. Each finished phrase goes to the assistant with
what is on screen, and comes back as one command. Anything that is not a command is a thought: it is
saved (its audio goes through Whisper like any recording), filed and matured. Keywords stand in when
no model is available, so the basics work without one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

VERBS = (
    "go",       # go <place>: thoughts, inbox, arcade, controls, pendant, or a folder path
    "record",   # record start|stop
    "note",     # note <text>: save a thought
    "ask",      # ask <question>: answer from the thoughts
    "mature",   # suggest a next step for the folder on screen
    "act",      # send the folder's next step to Reminders
    "file",     # file the inbox
    "read",     # read the latest (or shown) thought's callout aloud
    "play",     # play <game>
    "exit",     # leave the game
    "pause",
    "back",
    "stop",     # stop listening
    "help",
    "none",
)
STOP_PHRASES = ("that's all", "thats all", "stop listening", "go to sleep", "goodbye", "good bye", "never mind", "nevermind")
PLACES = {"thoughts": "thoughts", "thought": "thoughts", "map": "thoughts", "notes": "thoughts", "inbox": "inbox",
          "arcade": "arcade", "games": "arcade", "controls": "controls", "buttons": "controls",
          "pendant": "pendant", "bluetooth": "pendant", "omi": "pendant", "home": "thoughts"}


@dataclass
class Context:
    place: str = "thoughts"  # thoughts, inbox, folder, arcade, game, controls, pendant
    folder: tuple[str, ...] = ()
    folders: list[tuple[str, ...]] = field(default_factory=list)
    games: list[tuple[str, str]] = field(default_factory=list)  # (key, spoken title)
    recording: bool = False


@dataclass(frozen=True)
class Command:
    verb: str
    arg: str = ""

    def __str__(self) -> str:
        return f"{self.verb} {self.arg}".strip()


def suggestions(ctx: Context) -> list[str]:
    """What to say, for the screen you are on. Shown under the caption."""
    if ctx.place == "game":
        return ["“exit game”", "“pause”", "“play again”"]
    if ctx.place == "arcade":
        names = [f"“play {title}”" for _key, title in ctx.games[:2]]
        return names + ["“back to my thoughts”"]
    if ctx.place == "folder" and ctx.folder:
        return ["just say a thought", "“what's the next step?”", "“make it an action”", f"“what's in {ctx.folder[-1]}?”"]
    tips = ["just say a thought", "“what did I promise this week?”"]
    tips.append("“stop recording”" if ctx.recording else "“start recording”")
    if ctx.folders:
        tips.append(f"“open {ctx.folders[0][-1]}”")
    return tips


def command_messages(heard: str, ctx: Context) -> list[dict[str, str]]:
    folders = "\n".join("- " + " / ".join(f) for f in ctx.folders[:60]) or "(none yet)"
    games = ", ".join(f"{key} ({title})" for key, title in ctx.games) or "(none)"
    here = {"folder": f"the folder {' / '.join(ctx.folder)}", "game": "playing a game", "arcade": "the Arcade menu",
            "inbox": "the Inbox", "controls": "the Controls", "pendant": "the pendant settings"}.get(ctx.place, "their thought map")
    return [
        {
            "role": "system",
            "content": (
                "You are the voice of Sideband, a Mac app the owner talks to through their Omi pendant while sitting back. "
                "They said one phrase out loud. Speech recognition is rough, so match by sound and meaning. "
                "Decide if it is a command for the app or a thought to keep. When unsure, it is a thought.\n"
                f"They are looking at {here}. Recording now: {'yes' if ctx.recording else 'no'}.\n"
                f"Folders:\n{folders}\nGames: {games}\n"
                "Reply with exactly one line, nothing else:\n"
                "go <thoughts|inbox|arcade|controls|pendant|Area / Topic / Thread>  (open a place or folder)\n"
                "record start | record stop\n"
                "note <the thought, cleaned up>  (an idea, reminder, plan, feeling: anything to keep)\n"
                "ask <question>  (a question about their own thoughts, notes or promises)\n"
                "mature  (what's next for this, how far along is it)\n"
                "act  (make it an action, remind me, add to my list)\n"
                "file  (sort or file the inbox)\n"
                "read  (read it out, what was that)\n"
                "play <game key> | exit | pause | back\n"
                "stop  (stop listening, that's all, goodbye)\n"
                "help  (what can I say)\n"
                "Examples: 'open shopify' -> go Work / Clients / Shopify. 'show me the inbox' -> go inbox. "
                "'I should call Dana about the portfolio tomorrow' -> note Call Dana about the portfolio tomorrow. "
                "'what did I promise this week' -> ask what did I promise this week. 'what's next here' -> mature. "
                "'remind me to do that' -> act. 'sort out my inbox' -> file. 'show me the inbox' -> go inbox. "
                "'let's play sky ace' -> play fighter. 'that's all' -> stop."
            ),
        },
        {"role": "user", "content": heard},
    ]


def match_folder(text: str, folders: list[tuple[str, ...]]) -> tuple[str, ...] | None:
    """A spoken or written folder name to a folder on the map: full path, else the deepest name that matches."""
    wanted = [w for w in re.split(r"\s*(?:/|›|>)\s*", text.strip().lower()) if w]
    if not wanted:
        return None
    for folder in folders:
        if [p.lower() for p in folder] == wanted:
            return folder
    last = wanted[-1]
    hits = [f for f in folders if f[-1].lower() == last] or [f for f in folders if last in f[-1].lower() or f[-1].lower() in last]
    return max(hits, key=len) if hits else None


def parse_command(reply: str, ctx: Context) -> Command:
    line = reply.strip().splitlines()[0] if reply.strip() else ""
    line = line.strip("`*\"' ").replace("<", "").replace(">", "")
    verb, _, arg = line.partition(" ")
    verb, arg = verb.lower().rstrip(":"), arg.strip()
    if verb not in VERBS:
        return Command("none")
    if verb == "go":
        place = PLACES.get(arg.lower())
        if place:
            return Command("go", place)
        folder = match_folder(arg, ctx.folders)
        return Command("go", " / ".join(folder)) if folder else Command("none")
    if verb == "record":
        return Command("record", "stop" if "stop" in arg.lower() else "start")
    if verb == "play":
        keys = [k for k, _t in ctx.games]
        key = next((k for k in keys if k == arg.lower()), None) or next(
            (k for k, t in ctx.games if t.lower() in arg.lower() or arg.lower() in t.lower()), None) if arg else None
        return Command("play", key) if key else Command("none")
    if verb in ("note", "ask") and not arg:
        return Command("none")
    return Command(verb, arg)


def guess_command(heard: str, ctx: Context) -> Command:
    """No model at hand: keywords for the common commands; anything longer is kept as a thought."""
    text = heard.lower().replace("'", "").strip()
    words = text.split()
    said = set(words)
    if not words:
        return Command("none")
    if any(p.replace("'", "") in text for p in STOP_PHRASES):
        return Command("stop")
    if ctx.place == "game":
        if said & {"exit", "quit", "leave"}:
            return Command("exit")
        if said & {"pause", "wait"}:
            return Command("pause")
        return Command("none")  # chatter while playing does nothing
    if said & {"record", "recording"}:
        return Command("record", "stop" if "stop" in said else "start")
    if "help" in said or text in ("what can i say", "what can you do"):
        return Command("help")
    if said & {"remind", "action"}:
        return Command("act")
    if said & {"next", "mature"} and len(words) <= 6:
        return Command("mature")
    if {"play"} & said:
        for key, title in ctx.games:
            if key in said or title.lower() in text:
                return Command("play", key)
    if words[0] in ("open", "show", "go") and len(words) > 1:
        rest = " ".join(w for w in words[1:] if w not in ("me", "the", "my", "to", "folder"))
        if rest in PLACES:
            return Command("go", PLACES[rest])
        folder = match_folder(rest, ctx.folders)
        if folder:
            return Command("go", " / ".join(folder))
    if words[0] in ("what", "when", "who", "where", "why", "how", "did", "do", "have") and len(words) > 2:
        return Command("ask", heard.strip())
    if len(words) >= 4:
        return Command("note", heard.strip())
    return Command("none")


def spoken_reply(command: Command) -> str:
    """A few words said back, so you know it worked without looking."""
    return {
        "note": "Got it.",
        "record": "Recording." if command.arg == "start" else "Stopped.",
        "file": "Filing your inbox.",
        "mature": "Let me think about what's next.",
        "act": "Added to Reminders.",
        "stop": "Okay.",
    }.get(command.verb, "")
