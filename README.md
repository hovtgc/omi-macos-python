# Sideband: an Omi pendant on your Mac

A Python Mac app for the [Omi](https://github.com/BasedHardware/omi) pendant. It:

- holds the pendant's Bluetooth link in the background and reconnects after drops,
- maps single and double taps to Mac actions: open or switch apps, keystrokes, Shortcuts, URLs, volume, notifications, AppleScript, shell,
- shows every live input (button, mic stream, battery, device state) in one window,
- includes **Omi Flap 3D**, a first-person tap-to-flap game that steers with pendant tilt once the firmware streams motion (arrow keys until then).

Audio never leaves the Mac, and nothing is recorded unless you ask for a WAV. MIT licensed. This is not the Omi phone app.

## Setup

```sh
python3 -m venv .venv            # Python 3.10+
.venv/bin/pip install -e '.[audio,firmware]'
sh scripts/test.sh
.venv/bin/sideband build-app     # ~/Applications/Sideband.app, holds the Bluetooth permission
.venv/bin/sideband --via-app scan
.venv/bin/sideband --via-app ui
```

Wake the pendant and keep it next to the Mac. macOS asks once for Bluetooth for **Sideband**. For keystroke actions, turn Sideband on in System Settings → Privacy & Security → Accessibility (the window has a button for it).

Why the app wrapper: macOS gives Bluetooth to the app that launched a process. Python started from an IDE, an agent, or launchd has no such app and is killed silently. `Sideband.app` is a tiny signed-ad-hoc bundle that carries the permission and runs this venv's Python.

## Run in the background

```sh
.venv/bin/sideband install --address <id-from-scan>
.venv/bin/sideband status
.venv/bin/sideband uninstall
```

## Buttons

The pendant detects gestures itself: a single tap arrives about 300 ms after the press, and a double tap uses a 600 ms window. **Holding for 3 s powers the pendant off**, so it can't be mapped.

## Motion

The pendant has an LSM6DS3TR-C 6-axis IMU, but stock firmware compiles motion out. `firmware/accel-stream.patch` enables a 50 Hz stream; `NOTES.md` records what has been verified. The bootloader has no rollback, so a crashing build needs a debug probe to recover.

Agents: read `AGENTS.md` (Claude Code also reads `CLAUDE.md`) and do the first unchecked item in `TASKS.md`.
