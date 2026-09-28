# Sideband

A Mac app, in Python, that turns an Omi pendant into a Mac companion: tap-to-record transcription with a local AI assistant, tap / tilt / voice controls for the Mac, and a small arcade. Everything runs on the Mac.

You are a coding agent (Codex, Claude Code, or similar). Work only inside this directory. Ignore any parent folder.

## First: what does the user want?

- **Set it up, or use it** ("set me up", "get this running", "install", "start the transcriber", "play the game", "flash the motion firmware"): follow **[ONBOARDING.md](ONBOARDING.md)** step by step. Do not open `TASKS.md`. Stop at the 🧑 steps and wait for the user. Start with `sh scripts/setup.sh` and `.venv/bin/sideband doctor`.
- **Change the code:** read the rest of this file, then `TASKS.md`.

Never flash firmware without the user's explicit yes in chat, asked again before each flash. Never run radio commands bare from your shell; use `--via-app` or `sideband open` (see Bluetooth permission).

This stays a Python application. Do not rewrite it in Swift, JavaScript, or as a web UI. The window is tkinter.

## Product

Transcriber first: tap to record, Whisper transcribes on the Mac, a local LLM (Qwen2.5-7B via MLX) writes summaries and action items and answers questions. Then Controls (taps → Mac actions), a voice menu, the Arcade, and a Bluetooth tool. It also holds the pendant's link in the background, which the official phone app drops when it leaves the foreground. Nothing is uploaded. There is no account.

USB does not carry audio. Do not add a USB transport.

## Invariants

- The application object is `SidebandApp` in `src/sideband/app.py`. `cli.py` only parses arguments and calls it.
- Gap rule lives only in `src/sideband/watchdog.py`. Silence of `GAP_S` (2.0) while `holding` is one drop, then a reconnect. Do not invent a second threshold.
- Packet header is 3 bytes. Strip it with `protocol.strip_packet`. Do not decode those bytes.
- Codec ids are in `protocol.CODECS`. Opus is 20 and 21, 16 kHz mono.
- `radio.py` is the only module allowed to import `bleak` or `smpclient`.
- Button gestures come from the firmware's codes (`inputs.BUTTON_CODES`). Do not re-derive them from timing. A 3 s hold powers the pendant off and cannot be mapped.
- Arcade flow is the same in every game: double tap = forward (start, again, resume), single tap = back, hold = pause. Keep it that way for new games.
- Tests must pass with no pendant and no Bluetooth adapter.
- Keep models local: Whisper, the assistant LLM and Vosk run on the Mac. Do not add cloud transcription or cloud LLMs without the owner asking.
- Do not add Deepgram, Firebase, accounts, or network transcription. Nothing is recorded unless the user passes `--wav`. Voice commands use offline Vosk with a fixed command grammar; audio is dropped after recognition.
- Never flash firmware without the owner's explicit yes in chat. The bootloader has no rollback.

## Bluetooth permission (read this first)

macOS charges Bluetooth to the app that launched the process. Python started from an agent, an IDE, or launchd is killed by TCC with SIGABRT and no Python traceback. `Sideband.app` (built by `sideband build-app` into `~/Applications`) carries `NSBluetoothAlwaysUsageDescription` and execs this venv's python, so run radio commands through it:

```sh
.venv/bin/sideband --via-app scan
```

`--via-app` (or `SIDEBAND_VIA_APP=1`) streams output back and returns the exit code. Keystroke actions need Sideband turned on in Privacy & Security → Accessibility; only the owner can grant that.

## Commands

```sh
sh scripts/setup.sh                                      # everything, once; safe to rerun
sh scripts/test.sh
.venv/bin/sideband doctor [--pendant]                    # what is ready and the next step
.venv/bin/sideband open launcher|transcriber|controls|arcade|bluetooth
.venv/bin/sideband models --download
.venv/bin/sideband firmware --install official|motion    # dry run; --yes-flash to install
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
| `src/sideband/game.py` | Omi Flap 3D and Voice Flap: pure `Flight` plus a Tk renderer. |
| `src/sideband/voice.py` | Voice commands: pure `CommandSpotter` plus a Vosk listener thread. |
| `src/sideband/audio.py` | Optional WAV capture (PyAV for Opus). |
| `src/sideband/bundle.py` | Sideband.app and LaunchAgent builders. |
| `src/sideband/radio.py` | bleak and SMP sessions. |
| `src/sideband/ui.py` | Launcher (`Hub`): the pendant connection, gesture actions, recorder, transcriber, assistant, voice menu, 24 h audio limit. |
| `src/sideband/transcriber_app.py` | Transcriber window: record, read, summarize, ask. |
| `src/sideband/controls.py` | Controls window: live inputs and the gesture map. |
| `src/sideband/arcade.py` | Omi Arcade menu (pendant-driven, calibrates on open), mini game windows, Corn Maze art. |
| `src/sideband/skyfighter.py` | Sky Ace 1943 game state. Pure. |
| `src/sideband/skyfighter_view.py` | Sky Ace 1943 software 3D renderer (Tk). |
| `src/sideband/meshes.py` | Low-poly aircraft meshes and 3D math. Pure. |
| `src/sideband/speech.py` | Spoken callouts through macOS `say`; voice choice. |
| `src/sideband/minigames.py` | Corn Maze (`MarbleMaze`), Star Dodger, Omi Catch. Pure. |
| `src/sideband/bluetooth_app.py` | Bluetooth window: scan, switch, reconnect, debug. |
| `src/sideband/recordings.py` | Recording files, transcripts, the 24 h audio limit. Pure. |
| `src/sideband/transcribe.py` | Whisper worker (mlx-whisper). |
| `src/sideband/llm.py` | Local LLM: prompts, context, summaries (pure) and the MLX worker. |
| `src/sideband/doctor.py` | `sideband doctor`: setup checks and next steps. |
| `src/sideband/log.py` | stdout plus an optional file. |
| `ONBOARDING.md` | Setup playbook for users and their agents. |
| `scripts/setup.sh` | One-command install. |
| `firmware/README.md` | What the motion patch changes, the release, building it yourself. |
| `firmware/accel-stream.patch` | Upstream firmware patch that streams the IMU at 50 Hz. |
| `tests/` | Unit tests. No radio required. |
| `TASKS.md` | Development work: do the first unchecked item, then stop. Not for setup. |
| `NOTES.md` | Run notes from a real pendant. Append, never delete. |

## How to change the code

1. Read `TASKS.md` and do only the first unchecked item.
2. Keep new logic on `SidebandApp` or in a pure module next to `watchdog.py`. Test the pure part.
3. Run `sh scripts/test.sh`. Leave it green.
4. Check the box and write one paragraph in `NOTES.md` if you touched a real pendant. Do not check a box you only simulated.
