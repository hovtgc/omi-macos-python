# Sideband: your Omi pendant, on your Mac

**Tap your [Omi](https://github.com/BasedHardware/omi) to record. Your Mac transcribes it, summarizes it, pulls out the action items, and answers questions about everything you've said. Nothing leaves your Mac.**

Sideband is a Python Mac app that turns an Omi pendant into a Mac companion:

| | App | What it does |
|---|---|---|
| 🎙 | **Transcriber** | Tap to record (or pick any audio file). Whisper transcribes it on the Mac; a local LLM adds a summary and action items and answers questions about one recording or all of them. Audio deletes itself after 24 hours; transcripts stay. |
| 🎛 | **Controls** | Map single / double / triple / hold taps to Mac actions: open apps, keystrokes, Shortcuts, URLs, volume, record, voice menu, AppleScript, shell. |
| 🗣 | **Voice menu** | Press ⌘L or tap, then say "start recording", "summarize that", "open arcade", "close". |
| 🕹 | **Arcade** | Omi Flap 3D (tap to flap, tilt to steer), Voice Flap ("go left"), Marble Maze, Star Dodger, Omi Catch. |
| 📶 | **Bluetooth** | Connect, scan, switch pendants, and see what the link is doing. |

It runs Whisper large-v3-turbo, Qwen2.5-7B (MLX) and Vosk locally. There is no account, no cloud, and no telemetry. MIT licensed. Not affiliated with Based Hardware; this is not the Omi phone app.

## Quick start: let your agent do it

Clone the repo, open the folder in **Claude Code** or **Codex**, and say:

> **Set me up.**

The agent follows [ONBOARDING.md](ONBOARDING.md): it installs everything with one script, checks each step, and stops when it needs you (allowing Bluetooth, tapping the pendant). You'll be transcribing in about 15 minutes, most of it the one-time model download.

## Quick start: by hand

```sh
git clone https://github.com/hovtgc/omi-macos-python.git && cd omi-macos-python
sh scripts/setup.sh                # Python 3.12 via uv, packages, tests, Sideband.app, models (~6 GB)
.venv/bin/sideband open launcher   # then allow Bluetooth when macOS asks
```

Tap the pendant to wake it; the launcher connects on its own. Open the **Transcriber** (⌘1), click the red button, talk, click again. Next time, double-click **Sideband** in `~/Applications` or find it in Spotlight.

`.venv/bin/sideband doctor` tells you what's ready and what to do next.

## Requirements

- An **Omi pendant**. Motion (tilt games) needs the Omi CV 1 and the optional motion firmware; everything else works on stock firmware.
- A **Mac with Apple silicon** (M1 or later) on **macOS 13+** for the transcriber and assistant (MLX). On Intel Macs, Bluetooth, Controls and the Arcade still work.
- About **8 GB** free disk for the models.

## Motion firmware (optional)

Stock Omi firmware leaves the pendant's 6-axis sensor off. Sideband ships a small firmware patch that streams it for tilt and shake, as a prebuilt, checksum-pinned release plus the source. Installing it is optional, needs your explicit yes, and the pendant has **no rollback**, so read [ONBOARDING.md step 7](ONBOARDING.md#7-optional-motion-firmware-for-tilt-games-omi-cv-1-only) first. Details: [firmware/README.md](firmware/README.md).

## How it fits together

```
Omi pendant ──Bluetooth──▶ Sideband.app (holds the permission)
                              └─ launcher: one connection shared by the apps
                                   ├─ recorder → Whisper → transcript.md → local LLM → summary / answers
                                   ├─ taps → your Mac actions      ├─ voice menu (Vosk)
                                   └─ Arcade (taps, tilt, shake)   └─ Bluetooth tools
```

Why an app wrapper? macOS only gives Bluetooth to the app that started a process, so Python run from a terminal, IDE or agent is killed silently. `Sideband.app` is a tiny ad-hoc-signed bundle that holds the permission and runs this repo's Python.

## Commands

```sh
sideband open launcher|transcriber|controls|arcade|bluetooth   # reuses a running launcher
sideband doctor [--pendant]                                   # checks and next steps
sideband models --download
sideband --via-app scan                                       # radio commands from a shell go through the app
sideband firmware --install official|motion [--yes-flash]
sideband install --address <id>                               # keep the link alive at login
```

`sideband open …` works from Shortcuts, Raycast and Alfred too. Inside the app, the **Apps** menu has ⌘1–⌘4.

## Contributing

Read [AGENTS.md](AGENTS.md) (the contract for people and coding agents), then [TASKS.md](TASKS.md). `sh scripts/test.sh` must stay green; tests need no pendant. [NOTES.md](NOTES.md) records what was verified on real hardware.
