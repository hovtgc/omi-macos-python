# Sideband

Python app for a Mac. It keeps an Omi pendant's Bluetooth link alive in the background, maps the pendant's button to Mac actions, and ships a tap-and-tilt demo game.

You are a coding agent (Codex, Claude Code, or similar). Work only inside this directory. Ignore any parent folder.

This stays a Python application. Do not rewrite it in Swift, JavaScript, or as a web UI. The window is tkinter.

## Product

The official phone app drops the pendant when it leaves the foreground. This process is the countermeasure. Audio frames are counted locally. Nothing is uploaded. There is no account.

USB does not carry audio. Do not add a USB transport.

## Invariants

- The application object is `SidebandApp` in `src/sideband/app.py`. `cli.py` only parses arguments and calls it.
- Gap rule lives only in `src/sideband/watchdog.py`. Silence of `GAP_S` (2.0) while `holding` is one drop, then a reconnect. Do not invent a second threshold.
- Packet header is 3 bytes. Strip it with `protocol.strip_packet`. Do not decode those bytes.
- Codec ids are in `protocol.CODECS`. Opus is 20 and 21, 16 kHz mono.
- `radio.py` is the only module allowed to import `bleak` or `smpclient`.
- Button gestures come from the firmware's codes (`inputs.BUTTON_CODES`). Do not re-derive them from timing. A 3 s hold powers the pendant off and cannot be mapped.
- Tests must pass with no pendant and no Bluetooth adapter.
- Do not add Deepgram, Firebase, accounts, or network transcription. Nothing is recorded unless the user passes `--wav`.
- Never flash firmware without the owner's explicit yes in chat. The bootloader has no rollback.

## Bluetooth permission (read this first)

macOS charges Bluetooth to the app that launched the process. Python started from an agent, an IDE, or launchd is killed by TCC with SIGABRT and no Python traceback. `Sideband.app` (built by `sideband build-app` into `~/Applications`) carries `NSBluetoothAlwaysUsageDescription` and execs this venv's python, so run radio commands through it:

```sh
.venv/bin/sideband --via-app scan
```

`--via-app` (or `SIDEBAND_VIA_APP=1`) streams output back and returns the exit code. Keystroke actions need Sideband turned on in Privacy & Security → Accessibility; only the owner can grant that.

## Commands

```sh
sh scripts/test.sh
python3 -m venv .venv && .venv/bin/pip install -e '.[audio,firmware]'
.venv/bin/sideband protocol
.venv/bin/sideband --via-app scan
.venv/bin/sideband --via-app services --address <id>
.venv/bin/sideband --via-app ui [--address <id>]
.venv/bin/sideband --via-app hold --address <id> [--seconds 60] [--wav out.wav]
.venv/bin/sideband --via-app firmware --address <id>     # read-only image slots
.venv/bin/sideband install --address <id>                # login agent
.venv/bin/sideband status
```

A connected pendant stops advertising. Close the window before `firmware` or `scan`.

## Layout

| Path | Role |
|---|---|
| `src/sideband/app.py` | `SidebandApp`. The Python app. |
| `src/sideband/cli.py` | Argument parsing only. |
| `src/sideband/protocol.py` | UUIDs, header, codec names. Pure. |
| `src/sideband/watchdog.py` | Hold / gap / reconnect decision. Pure. |
| `src/sideband/status.py` | Log summary lines. Pure. |
| `src/sideband/inputs.py` | Characteristic names, button codes, Mac actions, gesture map. Pure. |
| `src/sideband/motion.py` | Motion payload parsing and tilt. Pure. |
| `src/sideband/game.py` | Omi Flap 3D: pure `Flight` plus a Tk renderer. |
| `src/sideband/audio.py` | Optional WAV capture (PyAV for Opus). |
| `src/sideband/bundle.py` | Sideband.app and LaunchAgent builders. |
| `src/sideband/radio.py` | bleak and SMP sessions. |
| `src/sideband/ui.py` | tkinter input explorer. |
| `src/sideband/log.py` | stdout plus an optional file. |
| `firmware/accel-stream.patch` | Upstream firmware patch that streams the IMU at 50 Hz. |
| `tests/` | Unit tests. No radio required. |
| `TASKS.md` | Do the first unchecked item, then stop. |
| `NOTES.md` | Run notes from a real pendant. Append, never delete. |

## How to change the code

1. Read `TASKS.md` and do only the first unchecked item.
2. Keep new logic on `SidebandApp` or in a pure module next to `watchdog.py`. Test the pure part.
3. Run `sh scripts/test.sh`. Leave it green.
4. Check the box and write one paragraph in `NOTES.md` if you touched a real pendant. Do not check a box you only simulated.
