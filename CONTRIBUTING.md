# Contributing

Sideband is a local Mac arcade. The shelf is the home screen. Thought Map, Controls and Bluetooth stay in the app, behind the gear. MIT, see [LICENSE](LICENSE).

```sh
sh scripts/setup.sh --no-models   # once, if you only want to hack
sh scripts/test.sh                # must stay green; no pendant, no network
```

Keyboard and mouse have to be enough to play anything you add. The Omi and gamepads are extras on the same input frame.

## Add a game

Games are data plus a pure step function. The shelf, the scores and the legend pick them up from one registry.

1. **Describe it** in `LIBRARY` in `src/sideband/platform.py`:

```python
GameSpec(
    "pong",
    "OMI PONG",
    "Tap to bump the ball back.",
    ("#7ef9ff", "#12305a"),
    "pong",
    motion=False,          # True only if the fun path is tilt
    stock=True,            # plays with taps / voice / mic, no motion firmware
    aliases=("pong",),
)
```

`stock=True` puts a BUTTON tag on the card. `score="time"` means a lower number is the better score (Corn Maze). Anything else is points, higher wins.

2. **Say what the buttons do** in `PLAY` in `src/sideband/legend.py`. Use the Omi words (`tap`, `double`, `hold`, `tilt`, `shake`, `say`). The legend rewrites them for the keyboard and for a pad, so you do not keep a second list. Outside of play, every game already shows Enter / Esc (or tap / double tap, or A / B) for start and back. Add a `PLAY` entry or the shelf test fails.

3. **Write the rules with no Tk.** A `@dataclass` with `step(self, dt, taps=0)` and `score` / `over` is enough. Put a one-button game in `src/sideband/shelf_games.py` and add its key to `SHELF_KEYS` and `make()`. The window in `shelf_view.py` already starts, pauses, records the score and treats a shout as a tap. Look at `Dash` or `BeatTap`.

   A game that needs its own drawing (the way Sky Ace does) keeps a window with `on_tap`, `on_hold`, `on_shake`, `close`, `playing` and `top`, and a branch in `Hub.open_game` in `src/sideband/ui.py`. Read the stick from `hub.play_axes()`, and fall back to the arrow keys when that returns None. Call `hub.record_score(key, score)` when the run ends. Corn Maze passes `lower_is_better=True`.

4. **Give it a cover.** A 16:9 JPEG with no baked-in title, saved under `src/sideband/assets/covers/` and named in `FILES` in `src/sideband/covers.py`. The file name has to be that game's picture (the desert file is the desert, the corn file is the corn). `tests/test_desert.py` pins the bundled bytes so a rename cannot swap two paintings. Until that file exists the shelf draws a titled gradient from the game's colours. No downloaded images at runtime.

5. **Test it** in `tests/` with scripted taps. No pendant, no window. `sh scripts/test.sh`.

`spoken_aliases()` is built from `aliases`, so "play pong" works in the keyword fallback without another table. The open-vocabulary listener still asks the local model when one is installed.

## Controllers

`InputFrame` in `platform.py` is the shape: `x`, `y` (right and up, -1..1), `taps`, `pad` (the second button), `shake`, `volume` (mic 0..1), `device`.

- Keyboard and mouse always work, including when a pad is pinned.
- Omi taps are delivered by the hub while the shelf or a game is open.
- Gamepads go through `src/sideband/pads.py`. pygame is an optional extra (`gamepad` in `pyproject.toml`). `edges()` is pure and is what the tests drive. Hot-plug is `read_pygame`, polled every tick.

The on-screen legend uses `legend(game, state, device=hub.active_device())`. Auto mode follows the last device that did something. The gear's Controllers page pins one.

## Shelf controls (do not invent a second scheme)

On the shelf: single tap or d-pad right moves on, double tap or B or Esc moves back, hold or A or Enter launches. Tab or Start or the gear opens settings. Settings is not a card on the row.

In a game: confirm starts, resumes or plays again; cancel leaves; hold pauses; "exit game" leaves. That is `legend.py` and the windows, not a per-game invention.

## Do not

- Flash firmware unless the owner said yes, in chat, for that flash.
- Import `bleak` or `smpclient` outside `radio.py`.
- Add a cloud transcript, an account, or a network call from a game.
- Put personal paths, keys, pendant addresses or private notes in a commit. `NOTES.md` is an append-only hardware log; do not paste new identifiers into it from a machine that is not the owner's.

## A game, end to end, in one sitting

`BeatTap` is the template: rules in `shelf_games.py`, a row in `LIBRARY`, a `PLAY` line, a few rectangles in `_keyart`, and `tests/test_shelf_games.py` tapping on the beat and missing on purpose. Copy that shape.
