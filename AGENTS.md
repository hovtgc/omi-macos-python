# Sideband

Python app for a Mac. It keeps an Omi pendant's Bluetooth notifications alive in the background.

You are a coding agent (Codex, Claude Code, or similar). Work only inside this directory. Ignore any parent folder.

This stays a Python application. Do not rewrite it in Swift, JavaScript, or as a web UI.

## Product

The official phone app drops the pendant when it leaves the foreground. This process is the countermeasure. Audio frames are counted locally. Nothing is uploaded. There is no account.

USB does not carry audio. Do not add a USB transport.

## Invariants

- The application object is `SidebandApp` in `src/sideband/app.py`. `cli.py` only parses arguments and calls it.
- Gap rule lives only in `src/sideband/watchdog.py`. Silence of `GAP_S` (2.0) while `holding` is one drop, then a reconnect. Do not invent a second threshold.
- Packet header is 3 bytes. Strip it with `protocol.strip_packet`. Do not decode those bytes.
- Codec ids are in `protocol.CODECS`. Opus is 20 and 21, 16 kHz mono.
- `radio.py` is the only module allowed to import `bleak`.
- Tests must pass with no pendant and no Bluetooth adapter.
- Do not add Deepgram, Firebase, or accounts.
- Do not start a Swift or TestFlight target. That is a later repo.

## Commands

```sh
sh scripts/test.sh
python3 -m venv .venv && .venv/bin/pip install -e .
.venv/bin/sideband protocol
.venv/bin/sideband scan
.venv/bin/sideband hold --address <id-from-scan>
```

`scan` and `hold` need the Mac's Bluetooth. Grant access under System Settings → Privacy & Security → Bluetooth for the terminal or the Python binary. Tests do not need it.

## Layout

| Path | Role |
|---|---|
| `src/sideband/app.py` | `SidebandApp`. The Python app. |
| `src/sideband/cli.py` | Argument parsing only. |
| `src/sideband/protocol.py` | UUIDs, header, codec names. Pure. |
| `src/sideband/watchdog.py` | Hold / gap / reconnect decision. Pure. |
| `src/sideband/radio.py` | bleak session. |
| `src/sideband/log.py` | stdout plus an optional file. |
| `tests/` | Unit tests. No radio required. |
| `launchd/com.sideband.hold.plist` | Login item so the Python process survives after the terminal quits. |
| `TASKS.md` | Do the first unchecked item, then stop. |
| `NOTES.md` | Run notes from a real pendant. Append, never delete. |

## How to change the code

1. Read `TASKS.md` and do only the first unchecked item.
2. Keep new logic on `SidebandApp` or in a pure module next to `watchdog.py`. Test the pure part.
3. Run `sh scripts/test.sh`. Leave it green.
4. Check the box and write one paragraph in `NOTES.md` if you touched a real pendant. Do not check a box you only simulated.

## Mac background

A hidden Terminal window is not enough after logout. `launchd/com.sideband.hold.plist` is `KeepAlive` and runs this Python app. Fill the python path and the device address before loading it. Do not codesign an app bundle in this pass.
